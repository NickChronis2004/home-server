import sqlite3
import json
import time
from pathlib import Path

DB_PATH = Path("/app/jarvis/logs/audit.db")
SCHEMA_PATH = Path("/app/jarvis/orchestrator/schema.sql")


def init_db():
    """Create the audit.db file and table if they don't exist yet. Safe to call on every startup."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
    finally:
        conn.close()


def log_tool_call(tool_name, tool_tier, params, result_status, result_summary=None,
                   duration_ms=None, error_code=None, confirmed=False):
    """
    Write one row to the audit log. Never raises — a logging failure must not
    break tool execution. On failure, prints to stdout so it still shows in
    `docker logs`, and returns None so callers can tell logging didn't succeed.
    Returns the inserted row's id on success.
    """
    try:
        safe_params = json.dumps(params, ensure_ascii=False, default=str)[:1000]
        safe_summary = (result_summary or "")[:500]

        conn = sqlite3.connect(DB_PATH, timeout=5)
        try:
            cursor = conn.execute(
                """INSERT INTO tool_calls
                   (tool_name, tool_tier, params_json, result_status, result_summary,
                    duration_ms, error_code, confirmed)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (tool_name, tool_tier, safe_params, result_status, safe_summary,
                 duration_ms, error_code, int(bool(confirmed)))
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()
    except Exception as e:
        print(f"[JARVIS] AUDIT LOG FAILED: {type(e).__name__}: {str(e)[:200]}", flush=True)
        return None
