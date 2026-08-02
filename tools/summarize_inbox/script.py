#!/usr/bin/env python3
"""
summarize_inbox — read-only IMAP fetch tool for JARVIS.

Connects to the CSD UoC mailbox over IMAP4_SSL, opens the mailbox in
EXPLICIT READONLY MODE (protocol-level guarantee — the server itself will
reject any state-changing command in this session, not just "we didn't
write code that changes flags"), and returns header + short body preview
data for the calling model to summarize.

This tool never sends EXPIRE, STORE, or COPY commands. Extending it to
support actions (reply, mark-as-read, delete) later requires a *new*,
separate write-capable tool with its own confirm-required tier — not a
flag flip on this one, by design (mirrors the read/lifecycle/maintenance
proxy separation used for Docker elsewhere in JARVIS).

Env vars required:
  CSD_MAIL_USER      — full address, e.g. csd1234@csd.uoc.gr
  CSD_MAIL_PASSWORD  — LDAP password
  CSD_MAIL_HOST      — defaults to mailhost.csd.uoc.gr if unset
  CSD_MAIL_PORT      — defaults to 993 if unset
"""

import imaplib
import email
import email.utils
import email.message
import html.parser as _html_parser
import os
import sys
import json
from datetime import datetime, timedelta, timezone
from email.header import decode_header


DEFAULT_HOST = "mailhost.csd.uoc.gr"
DEFAULT_PORT = 993
MAX_BODY_PREVIEW_CHARS = 500


class InboxError(Exception):
    pass


def _env_or_raise(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise InboxError(f"Missing required environment variable: {name}")
    return val


def _decode_mime_header(raw: str) -> str:
    if not raw:
        return ""
    parts = decode_header(raw)
    decoded = []
    for text, enc in parts:
        if isinstance(text, bytes):
            decoded.append(text.decode(enc or "utf-8", errors="replace"))
        else:
            decoded.append(text)
    return "".join(decoded)


class _HTMLTextExtractor(_html_parser.HTMLParser):
    """Minimal HTML-to-text: strips tags, drops <script>/<style> content
    entirely, keeps everything else as plain text. Not meant to be a full
    renderer — just enough to avoid dumping raw markup into a summary."""

    def __init__(self):
        super().__init__()
        self._chunks = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._chunks.append(data)

    def get_text(self) -> str:
        return " ".join(self._chunks)


def _html_to_text(html: str) -> str:
    parser = _HTMLTextExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    return parser.get_text()


def _extract_body_preview(msg: email.message.Message) -> str:
    """Best-effort plain-text preview, capped in length. Never fetches
    attachments. Prefers text/plain; falls back to stripped text/html if
    that's the only part present, rather than dumping raw markup."""
    plain_body = ""
    html_body = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition") or "")
            if "attachment" in disposition:
                continue
            if content_type == "text/plain" and not plain_body:
                try:
                    charset = part.get_content_charset() or "utf-8"
                    plain_body = part.get_payload(decode=True).decode(charset, errors="replace")
                except Exception:
                    pass
            elif content_type == "text/html" and not html_body:
                try:
                    charset = part.get_content_charset() or "utf-8"
                    html_body = part.get_payload(decode=True).decode(charset, errors="replace")
                except Exception:
                    pass
            if plain_body:
                break
    else:
        try:
            charset = msg.get_content_charset() or "utf-8"
            payload = msg.get_payload(decode=True)
            if payload:
                decoded = payload.decode(charset, errors="replace")
                if msg.get_content_type() == "text/html":
                    html_body = decoded
                else:
                    plain_body = decoded
        except Exception:
            pass

    body = plain_body if plain_body else _html_to_text(html_body)

    body = " ".join(body.split())  # collapse whitespace
    if len(body) > MAX_BODY_PREVIEW_CHARS:
        body = body[:MAX_BODY_PREVIEW_CHARS] + "…"
    return body


def _normalize_since_date(raw: str) -> str:
    """Accepts IMAP-format dates (02-Aug-2026) or ISO (2026-08-02) and
    returns IMAP-format. Raises InboxError on anything unparseable —
    no silent fallback to 'today'."""
    raw = raw.strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%d-%b-%Y")
        except ValueError:
            continue
    raise InboxError(f"Unrecognized since_date format: {raw!r}")


def fetch_inbox_summary(mode: str = "since", since_date: str = None, max_messages: int = 50) -> dict:
    host = os.environ.get("CSD_MAIL_HOST", DEFAULT_HOST)
    port = int(os.environ.get("CSD_MAIL_PORT", DEFAULT_PORT))
    user = _env_or_raise("CSD_MAIL_USER")
    password = _env_or_raise("CSD_MAIL_PASSWORD")

    if mode == "since":
        if not since_date:
            # cron path defaults to "yesterday" if not explicitly given
            since_dt = datetime.now(timezone.utc) - timedelta(days=1)
            imap_date = since_dt.strftime("%d-%b-%Y")
        else:
            imap_date = _normalize_since_date(since_date)
        search_criteria = f'(SINCE "{imap_date}")'
    elif mode == "unseen":
        search_criteria = "(UNSEEN)"
    else:
        raise InboxError(f"Unknown mode: {mode!r}")

    conn = None
    try:
        conn = imaplib.IMAP4_SSL(host, port)
        conn.login(user, password)

        # readonly=True is the protocol-level guarantee: the server will
        # reject STORE/EXPUNGE/COPY commands in this session regardless of
        # what the client code does or doesn't send.
        status, _ = conn.select("INBOX", readonly=True)
        if status != "OK":
            raise InboxError("Failed to select INBOX (readonly)")

        status, data = conn.search(None, search_criteria)
        if status != "OK":
            raise InboxError(f"IMAP SEARCH failed: {search_criteria}")

        msg_ids = data[0].split()
        total_matched = len(msg_ids)

        # Cap and take the most recent N, not the oldest N
        truncated = total_matched > max_messages
        msg_ids = msg_ids[-max_messages:] if truncated else msg_ids

        messages = []
        for mid in msg_ids:
            status, msg_data = conn.fetch(mid, "(RFC822)")
            if status != "OK" or not msg_data or msg_data[0] is None:
                continue
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            subject = _decode_mime_header(msg.get("Subject", ""))
            from_addr = _decode_mime_header(msg.get("From", ""))
            date_hdr = msg.get("Date", "")
            try:
                parsed_date = email.utils.parsedate_to_datetime(date_hdr).isoformat()
            except Exception:
                parsed_date = date_hdr

            messages.append({
                "subject": subject,
                "from": from_addr,
                "date": parsed_date,
                "preview": _extract_body_preview(msg),
            })

        conn.close()
        conn.logout()

        return {
            "status": "success",
            "mode": mode,
            "search_criteria": search_criteria,
            "total_matched": total_matched,
            "returned": len(messages),
            "truncated": truncated,
            "messages": messages,
        }

    except imaplib.IMAP4.error as e:
        raise InboxError(f"IMAP error: {e}")
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass


def main():
    mode = os.environ.get("TOOL_ARG_MODE", "since")
    since_date = os.environ.get("TOOL_ARG_SINCE_DATE") or None
    max_messages = int(os.environ.get("TOOL_ARG_MAX_MESSAGES", "50"))

    try:
        result = fetch_inbox_summary(mode=mode, since_date=since_date, max_messages=max_messages)
        print(json.dumps(result))
    except InboxError as e:
        print(json.dumps({"status": "error", "error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
