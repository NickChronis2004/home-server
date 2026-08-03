#!/usr/bin/env python3
"""
list_recent_backups — read-only tool, no Docker proxy involved.

Lists protocol_permafrost backup runs found under the orchestrator's
own view of the backup directory (~/jarvis/jarvis-backups/ when running
inside the container — see STATUS.md note on the two trigger paths).

For each run, reports:
  - timestamp (parsed from the directory name)
  - total size on disk (du -sh equivalent)
  - which Docker volumes are included (from volumes/*.tar.gz filenames)
  - whether that run's backup.log entry shows OK / FAIL / WARN per
    component, and whether external USB sync happened
  - a top-level ok/fail summary so a human or the model can spot a
    bad run without reading every line

This tool never writes, deletes, or modifies anything — it only reads
directory listings, file sizes, and the shared backup.log.
"""

import os
import re
import subprocess
import sys
import json
from datetime import datetime
from pathlib import Path

BACKUP_DIR = Path(os.environ.get("JARVIS_BACKUP_DIR", "/app/jarvis/jarvis-backups"))
LOG_FILE = BACKUP_DIR / "backup.log"

RUN_DIR_RE = re.compile(r"^backup_(\d{4}-\d{2}-\d{2})_(\d{4})$")

# Matches a single component-status line inside a backup.log run summary
# block, e.g.:
#   [2026-08-02 00:48:15]   volume:jellyfin_jellyfin_cache:OK
#   [2026-08-02 00:48:15]   secrets(.env):FAIL
#   [2026-08-02 00:48:15]   sync-external:SKIPPED(not mounted)
SUMMARY_LINE_RE = re.compile(
    r"^\[(?P<ts>[\d-]+ [\d:]+)\]\s+(?P<component>[\w().:-]+?):(?P<status>OK|FAIL|SKIPPED(?:\([^)]*\))?|WARN)$"
)

RUN_HEADER_RE = re.compile(r"^\[(?P<ts>[\d-]+ [\d:]+)\]\s+Backup run summary:$")
RUN_FOOTER_RE = re.compile(r"^\[(?P<ts>[\d-]+ [\d:]+)\]\s+Backup completed")


def human_size(num_bytes: int) -> str:
    """Format bytes roughly the way `du -sh` would."""
    size = float(num_bytes)
    for unit in ["B", "K", "M", "G", "T"]:
        if size < 1024 or unit == "T":
            return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}{unit}"
        size /= 1024
    return f"{size:.1f}T"


def dir_size_bytes(path: Path) -> int:
    """Sum of file sizes under path. Equivalent to `du -sb` but pure
    Python so we don't depend on subprocess exit-code edge cases."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            fp = Path(root) / f
            try:
                total += fp.stat().st_size
            except OSError:
                # File vanished mid-walk, or a broken symlink. Skip
                # rather than fail the whole listing over one file.
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


def volumes_in_run(run_path: Path):
    vol_dir = run_path / "volumes"
    if not vol_dir.is_dir():
        return []
    return sorted(
        f.name[: -len(".tar.gz")] if f.name.endswith(".tar.gz") else f.name
        for f in vol_dir.iterdir()
        if f.is_file()
    )


def parse_backup_log(log_path: Path):
    """
    Parses backup.log into a dict keyed by the run's summary timestamp
    (the [timestamp] on the 'Backup run summary:' header line), each
    value a dict of {component: status}.

    backup.log is append-only across all runs, so this walks the whole
    file once and groups lines between a 'Backup run summary:' header
    and the following 'Backup completed' footer.
    """
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
                    # A new run started — flush whatever we were
                    # building for the previous one first. We don't
                    # rely on a "Backup completed" footer line to close
                    # a block, since that exact phrasing isn't always
                    # present; the next header (or EOF) is what
                    # actually delimits one run's summary from another.
                    if current_run_ts is not None:
                        runs[current_run_ts] = current_components
                    current_run_ts = header.group("ts")
                    current_components = {}
                    continue

                if current_run_ts is not None:
                    summary_line = SUMMARY_LINE_RE.match(line)
                    if summary_line:
                        current_components[summary_line.group("component")] = summary_line.group("status")
                        continue
                    # Any other line (the "====" separator, a
                    # "Backup completed" line if present, blank lines,
                    # etc.) is ignored — it's not a component status
                    # line, so it doesn't affect the current block.

        # Flush the last block in the file (no header follows it).
        if current_run_ts is not None:
            runs[current_run_ts] = current_components
    except OSError as e:
        # Log unreadable for some reason — don't fail the whole tool,
        # just return what we have (nothing), so directory-based info
        # still comes through.
        print(f"warning: could not read backup.log: {e}", file=sys.stderr)

    return runs


def match_runs_to_log_entries(run_dirs, log_runs, max_delta_seconds=900):
    """
    Matches each backup_* directory to its log.py summary block.

    Two things make naive "nearest by absolute time" matching unsafe
    here:

    1. A backup's summary is written when it *finishes*, which can be
       well after the directory timestamp (which is when it *started*
       — and only has minute precision, since the directory name is
       backup_YYYY-MM-DD_HHMM with no seconds). A run that took over a
       minute can end up closer in absolute time to an unrelated
       neighboring run's summary than to its own.
    2. Multiple runs can happen back-to-back (e.g. a dry-run followed
       a minute later by a real run) — without removing a log entry
       once it's used, two directories could both match the same
       summary block.

    Fix: only match a summary at or after the directory's start time
    (a run cannot finish before it starts), take the earliest such
    summary, and consume it so no other run can also claim it.
    """
    available = dict(log_runs)  # ts_str -> components, consumed as matched
    parsed_available = {}
    for ts_str in available:
        try:
            parsed_available[ts_str] = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

    # Earliest directory first, so an earlier run always gets first
    # claim on the earliest valid summary — mirrors the real order
    # backups actually ran in.
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


def main():
    limit = 10
    if len(sys.argv) > 1:
        try:
            limit = max(1, int(sys.argv[1]))
        except ValueError:
            pass

    if not BACKUP_DIR.is_dir():
        print(json.dumps({
            "error": f"Backup directory not found: {BACKUP_DIR}",
            "runs": [],
        }))
        return

    log_runs = parse_backup_log(LOG_FILE)

    run_dirs = []
    for entry in BACKUP_DIR.iterdir():
        if not entry.is_dir():
            continue
        ts = parse_run_timestamp(entry.name)
        if ts is None:
            continue  # not a backup_* run dir (e.g. stray file/folder)
        run_dirs.append((ts, entry))

    run_dirs.sort(key=lambda pair: pair[0], reverse=True)
    run_dirs = run_dirs[:limit]

    # Match against the full set of discovered dirs (not just the
    # limited slice) so consuming a log entry for a run outside the
    # limit doesn't free it up incorrectly — but for simplicity and
    # since backup.log is small, matching against just the displayed
    # slice is fine in practice: dry-run/adjacent entries outside the
    # window won't collide with displayed runs anyway due to the
    # forward-only constraint.
    matches = match_runs_to_log_entries(run_dirs, log_runs)

    results = []
    for ts, path in run_dirs:
        components = matches.get(path.name) or {}

        failures = [c for c, s in components.items() if s == "FAIL"]
        warnings = [c for c, s in components.items() if s.startswith("WARN") or s.startswith("SKIPPED")]

        sync_status = components.get("sync-external", "unknown")
        if sync_status.startswith("OK"):
            synced = True
        elif sync_status == "unknown":
            synced = None  # no log entry found for this run
        else:
            synced = False  # SKIPPED or FAIL

        size_bytes = dir_size_bytes(path)

        if not components:
            overall_status = "UNKNOWN"  # no log entry — don't claim OK
        elif failures:
            overall_status = "FAIL"
        elif warnings:
            overall_status = "WARN"
        else:
            overall_status = "OK"

        results.append({
            "run": path.name,
            "timestamp": ts.strftime("%Y-%m-%d %H:%M"),
            "size": human_size(size_bytes),
            "size_bytes": size_bytes,
            "volumes": volumes_in_run(path),
            "synced_to_usb": synced,
            "sync_detail": sync_status if sync_status != "unknown" else None,
            "failures": failures,
            "warnings": warnings,
            "overall_status": overall_status,
            "log_entry_found": bool(components),
        })

    print(json.dumps({
        "backup_dir": str(BACKUP_DIR),
        "count": len(results),
        "runs": results,
    }, indent=2))


if __name__ == "__main__":
    main()
