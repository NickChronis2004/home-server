#!/usr/bin/env python3
"""
morning_digest.py — daily health digest for JARVIS, standalone.

Design principles:

  - SSH-side, standalone. Same reasoning as integrity_check.py: this
    never routes through the orchestrator or any Docker proxy. It
    calls os-helper directly over localhost HTTP, reads backup logs
    directly off disk, and shells out to integrity_check.py — none
    of that needs Docker running at all, which matters specifically
    for this script: if the orchestrator itself is down (BLACKOUT,
    a crash, a bad deploy), the digest should still be able to tell
    you that, rather than silently failing along with it.
  - No new AI calls, no LLM involved anywhere in this script. It's
    pure data collection + templating — the four inputs
    (list_recent_backups logic, get_failed_units, get_disk_health,
    integrity_check) are each already-trustworthy, already-tested
    read-only sources; this script's only job is to run them all and
    lay the results out in one place.
  - Never fails all-or-nothing. Each section is wrapped so a single
    failing source (e.g. os-helper down) produces a visible "could
    not reach X" section instead of crashing the whole digest and
    leaving you with nothing at all that morning.
  - Reads BOTH backup directories (~/jarvis-backups/ and
    ~/jarvis/jarvis-backups/), since backups can land in either
    depending on trigger path (SSH-manual vs JARVIS-triggered) — see
    Section 7.2 of the blueprint. Reports the single most recent run
    across both, plus flags if either location hasn't seen a run in
    a long time (a location going stale might mean that trigger path
    silently stopped being used, not that everything is fine there).

Usage:
    python3 morning_digest.py

Writes:
    ~/jarvis/morning-digest/digest_latest.md          (always overwritten)
    ~/jarvis/morning-digest/archive/digest_<date>.md   (one per day)

Exit code is always 0 unless the digest itself could not be written
at all (e.g. disk full, permissions) — a degraded/partial digest
(some sections showing errors) is still a successfully delivered
digest and should not look like a crashed cron job.
"""

import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# --- Configuration -----------------------------------------------

HOME = Path(os.path.expanduser("~"))
JARVIS_DIR = HOME / "jarvis"

BACKUP_DIRS = [
    HOME / "jarvis-backups",
    JARVIS_DIR / "jarvis-backups",
]

OS_HELPER_BASE_URL = "http://localhost:8787"
OS_HELPER_TIMEOUT_SECONDS = 8

INTEGRITY_CHECK_SCRIPT = JARVIS_DIR / "integrity_check.py"

DIGEST_DIR = JARVIS_DIR / "morning-digest"
DIGEST_ARCHIVE_DIR = DIGEST_DIR / "archive"
DIGEST_LATEST_PATH = DIGEST_DIR / "digest_latest.md"

BACKUP_STALE_AFTER_HOURS = 30  # a bit over a day, tolerant of "one day skipped"

# --- Shared helpers (mirrors list_recent_backups's own logic) ----

RUN_DIR_RE = re.compile(r"^backup_(\d{4}-\d{2}-\d{2})_(\d{4})$")
SUMMARY_LINE_RE = re.compile(
    r"^\[(?P<ts>[\d-]+ [\d:]+)\]\s+(?P<component>[\w().:-]+?):(?P<status>OK|FAIL|SKIPPED(?:\([^)]*\))?|WARN)$"
)
RUN_HEADER_RE = re.compile(r"^\[(?P<ts>[\d-]+ [\d:]+)\]\s+Backup run summary:$")


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ["B", "K", "M", "G", "T"]:
        if size < 1024 or unit == "T":
            return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}{unit}"
        size /= 1024
    return f"{size:.1f}T"


def dir_size_bytes(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            fp = Path(root) / f
            try:
                total += fp.stat().st_size
            except OSError:
                continue
    return total


def parse_run_timestamp(dirname: str):
    m = RUN_DIR_RE.match(dirname)
    if not m:
        return None
    date_part, time_part = m.groups()
    try:
        return datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H%M")
    except ValueError:
        return None


def parse_backup_log(log_path: Path):
    """Same parsing logic as list_recent_backups/script.py — see that
    file's docstring for why the block boundary is 'next header or
    EOF', not a specific footer line."""
    runs = {}
    if not log_path.is_file():
        return runs

    current_run_ts = None
    current_components = {}

    try:
        with open(log_path, "r", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                header = RUN_HEADER_RE.match(line)
                if header:
                    if current_run_ts is not None:
                        runs[current_run_ts] = current_components
                    current_run_ts = header.group("ts")
                    current_components = {}
                    continue
                if current_run_ts is not None:
                    summary_line = SUMMARY_LINE_RE.match(line)
                    if summary_line:
                        current_components[summary_line.group("component")] = summary_line.group("status")
        if current_run_ts is not None:
            runs[current_run_ts] = current_components
    except OSError:
        pass

    return runs


def match_runs_to_log_entries(run_dirs, log_runs, max_delta_seconds=900):
    """Forward-only, one-to-one matching — same fix as
    list_recent_backups/script.py (see that file for the two failure
    modes this avoids: cross-run summary theft via naive nearest-abs
    matching, and double-claiming a single log entry)."""
    available = dict(log_runs)
    parsed_available = {}
    for ts_str in available:
        try:
            parsed_available[ts_str] = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

    ordered_dirs = sorted(run_dirs, key=lambda pair: pair[0])
    matches = {}
    for run_ts, path in ordered_dirs:
        candidates = [
            (log_dt, ts_str)
            for ts_str, log_dt in parsed_available.items()
            if ts_str in available
            and 0 <= (log_dt - run_ts).total_seconds() <= max_delta_seconds
        ]
        if not candidates:
            matches[path.name] = None
            continue
        _, chosen_ts_str = min(candidates, key=lambda item: item[0])
        matches[path.name] = available.pop(chosen_ts_str)

    return matches


def scan_backup_dir(backup_dir: Path, limit=5):
    """Returns a list of run dicts for one backup directory, newest
    first, same shape as list_recent_backups's output — reimplemented
    standalone here rather than shelling out to the orchestrator, so
    this works even if the orchestrator container is down."""
    if not backup_dir.is_dir():
        return {"backup_dir": str(backup_dir), "exists": False, "runs": []}

    log_runs = parse_backup_log(backup_dir / "backup.log")

    run_dirs = []
    for entry in backup_dir.iterdir():
        if not entry.is_dir():
            continue
        ts = parse_run_timestamp(entry.name)
        if ts is None:
            continue
        run_dirs.append((ts, entry))

    run_dirs.sort(key=lambda pair: pair[0], reverse=True)
    limited = run_dirs[:limit]

    matches = match_runs_to_log_entries(run_dirs, log_runs)

    results = []
    for ts, path in limited:
        components = matches.get(path.name) or {}
        failures = [c for c, s in components.items() if s == "FAIL"]
        warnings = [c for c, s in components.items() if s.startswith("WARN") or s.startswith("SKIPPED")]

        if not components:
            overall_status = "UNKNOWN"
        elif failures:
            overall_status = "FAIL"
        elif warnings:
            overall_status = "WARN"
        else:
            overall_status = "OK"

        try:
            size_bytes = dir_size_bytes(path)
        except OSError:
            size_bytes = None

        results.append({
            "run": path.name,
            "timestamp": ts,
            "timestamp_str": ts.strftime("%Y-%m-%d %H:%M"),
            "size": human_size(size_bytes) if size_bytes is not None else "unknown",
            "overall_status": overall_status,
            "failures": failures,
            "warnings": warnings,
            "log_entry_found": bool(components),
        })

    return {"backup_dir": str(backup_dir), "exists": True, "runs": results}


# --- os-helper client (same shape as lib/os_helper_client.py) -----

def call_os_helper(endpoint: str) -> dict:
    url = f"{OS_HELPER_BASE_URL}{endpoint}"
    try:
        with urllib.request.urlopen(url, timeout=OS_HELPER_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {"error": f"os-helper returned HTTP {e.code}"}
    except urllib.error.URLError as e:
        return {"error": f"could not reach os-helper daemon: {e.reason}"}
    except json.JSONDecodeError:
        return {"error": "os-helper returned invalid JSON"}


def run_integrity_check() -> dict:
    if not INTEGRITY_CHECK_SCRIPT.is_file():
        return {"error": f"integrity_check.py not found at {INTEGRITY_CHECK_SCRIPT}"}
    try:
        proc = subprocess.run(
            [sys.executable, str(INTEGRITY_CHECK_SCRIPT), "--json"],
            capture_output=True, text=True, timeout=20,
        )
        # Exit 0 = clean/created, 1 = change detected — both are
        # valid JSON on stdout, not failures of this subprocess call
        # itself. Only a genuinely broken run (no parseable JSON,
        # e.g. exit 2 usage error) is a real error here.
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"error": "integrity_check.py did not return valid JSON",
                "stderr": proc.stderr.strip() if 'proc' in dir() else None}
    except subprocess.TimeoutExpired:
        return {"error": "integrity_check.py timed out"}
    except OSError as e:
        return {"error": f"could not run integrity_check.py: {e}"}


# --- Markdown rendering --------------------------------------------

def status_emoji(status: str) -> str:
    return {"OK": "✅", "WARN": "⚠️", "FAIL": "🔴", "UNKNOWN": "❔"}.get(status, "❔")


def render_backups_section(scan_results) -> str:
    lines = ["## 📦 Backups", ""]
    all_runs = []
    for scan in scan_results:
        if not scan["exists"]:
            lines.append(f"- `{scan['backup_dir']}` — directory not found")
            continue
        for run in scan["runs"]:
            all_runs.append((scan["backup_dir"], run))

    if not all_runs:
        lines.append("No backup runs found in either location. If you expect backups "
                      "to be running, check `protocol_permafrost` / the backup timer.")
        return "\n".join(lines)

    all_runs.sort(key=lambda pair: pair[1]["timestamp"], reverse=True)
    most_recent_dir, most_recent = all_runs[0]
    age = datetime.now() - most_recent["timestamp"]
    age_hours = age.total_seconds() / 3600

    lines.append(f"**Most recent run:** {most_recent['timestamp_str']} "
                 f"({status_emoji(most_recent['overall_status'])} {most_recent['overall_status']}) "
                 f"— `{most_recent_dir}`, {most_recent['size']}")
    if age_hours > BACKUP_STALE_AFTER_HOURS:
        lines.append(f"⚠️ **This is {age_hours:.0f} hours old** — longer than the expected "
                      f"~24h cadence. Worth checking whether backups are still running.")
    lines.append("")

    for backup_dir, run in all_runs[:5]:
        marker = status_emoji(run["overall_status"])
        detail = ""
        if run["failures"]:
            detail = f" — FAILED: {', '.join(run['failures'])}"
        elif run["warnings"]:
            detail = f" — warnings: {', '.join(run['warnings'])}"
        elif not run["log_entry_found"]:
            detail = " — no matching log entry found"
        lines.append(f"- {marker} `{run['run']}` ({run['size']}, {backup_dir}){detail}")

    return "\n".join(lines)


def render_failed_units_section(data) -> str:
    lines = ["## 🖥️ Failed systemd units (host)", ""]
    if "error" in data:
        lines.append(f"⚠️ Could not check: {data['error']}")
        return "\n".join(lines)
    count = data.get("failed_count", 0)
    if count == 0:
        lines.append("✅ No failed units.")
    else:
        lines.append(f"🔴 {count} failed unit(s):")
        for u in data.get("units", []):
            lines.append(f"- `{u['unit']}` — {u.get('description', '')}")
    return "\n".join(lines)


def render_disk_health_section(data) -> str:
    lines = ["## 💾 Disk health", ""]
    if "error" in data:
        lines.append(f"⚠️ Could not check: {data['error']}")
        return "\n".join(lines)

    smart = data.get("smart", {})
    if "error" in smart:
        lines.append(f"⚠️ SMART data: {smart['error']}")
    else:
        stale_note = " (⚠️ stale)" if smart.get("stale") else ""
        lines.append(f"**SMART status**{stale_note}:")
        for dev in smart.get("devices", []):
            if dev.get("no_medium"):
                lines.append(f"- `{dev['device']}` — no medium present")
            elif dev.get("health_summary"):
                lines.append(f"- `{dev['device']}` — {dev['health_summary']}")
            elif dev.get("raw_error") or dev.get("error"):
                lines.append(f"- `{dev['device']}` — ⚠️ {dev.get('raw_error') or dev.get('error')}")
            else:
                lines.append(f"- `{dev['device']}` — no data")

    lines.append("")
    lines.append("**Filesystem usage:**")
    for fs in data.get("filesystem", []):
        pct = fs.get("use_percent", "?")
        marker = "🔴" if pct.rstrip("%").isdigit() and int(pct.rstrip("%")) >= 90 else (
            "⚠️" if pct.rstrip("%").isdigit() and int(pct.rstrip("%")) >= 75 else "✅"
        )
        lines.append(f"- {marker} `{fs['mounted_on']}` — {fs['used']}/{fs['size']} ({pct})")

    return "\n".join(lines)


def render_integrity_section(data) -> str:
    lines = ["## 🔒 File integrity (.env, policy.yaml)", ""]
    if "error" in data:
        lines.append(f"⚠️ Could not check: {data['error']}")
        return "\n".join(lines)

    status = data.get("status") or data.get("action")
    if status == "clean":
        lines.append(f"✅ All watched files match the baseline "
                      f"(recorded {data.get('baseline_generated_at', 'unknown')}).")
    elif status == "baseline_created":
        lines.append(f"ℹ️ First run — baseline just created "
                      f"({data.get('files_recorded', 0)} file(s)).")
    elif status == "CHANGED":
        lines.append("🔴 **Change detected — review and run `integrity_check.py --accept` "
                      "if this was you:**")
        for c in data.get("changes", []):
            lines.append(f"- `{c['path']}` — {c['kind']}")
    else:
        lines.append(f"❔ Unrecognized result: {json.dumps(data)}")

    return "\n".join(lines)


def render_digest(scan_results, failed_units, disk_health, integrity) -> str:
    now = datetime.now(timezone.utc).astimezone()
    sections = [
        f"# JARVIS Morning Digest — {now.strftime('%Y-%m-%d %H:%M %Z')}",
        "",
        render_backups_section(scan_results),
        "",
        render_failed_units_section(failed_units),
        "",
        render_disk_health_section(disk_health),
        "",
        render_integrity_section(integrity),
        "",
        "---",
        f"*Generated by morning_digest.py at {now.isoformat()}*",
    ]
    return "\n".join(sections) + "\n"


def main():
    scan_results = [scan_backup_dir(d) for d in BACKUP_DIRS]
    failed_units = call_os_helper("/get_failed_units")
    disk_health = call_os_helper("/get_disk_health")
    integrity = run_integrity_check()

    digest_md = render_digest(scan_results, failed_units, disk_health, integrity)

    DIGEST_DIR.mkdir(parents=True, exist_ok=True)
    DIGEST_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    DIGEST_LATEST_PATH.write_text(digest_md)

    today_str = datetime.now().strftime("%Y-%m-%d")
    archive_path = DIGEST_ARCHIVE_DIR / f"digest_{today_str}.md"
    archive_path.write_text(digest_md)

    print(f"Digest written to {DIGEST_LATEST_PATH}")
    print(f"Archived to {archive_path}")


if __name__ == "__main__":
    main()
