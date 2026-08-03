#!/usr/bin/env python3
"""
integrity_check.py — SHA-256 file-integrity check for JARVIS's most
critical files.

Design principles:

  - SSH-only, standalone. This never runs through the orchestrator
    or any Docker proxy — it's a plain script you run by hand (or,
    later, via the same timer as the morning digest). There is no
    JARVIS tool wrapping this and there won't be: a tool that can
    silently accept a changed baseline is not meaningfully different
    from having no integrity check at all, and the orchestrator is
    exactly the kind of component this check exists to watch, not
    the thing that should be trusted to run it unsupervised.
  - Never auto-updates the baseline on a detected change. A mismatch
    is reported and the run exits non-zero; the baseline file is
    left untouched. The only way the baseline changes is a separate,
    explicit `--accept` run — a deliberate, out-of-band decision,
    same spirit as JARVIS's own /confirm flow (Section 4.3 of the
    blueprint), just at the human/SSH layer instead of chat.
  - Plain JSON baseline file on the host filesystem
    (~/jarvis/.integrity-baseline.json by default) — not inside any
    container, not behind any proxy. Simple enough to read by eye if
    you ever want to sanity-check it directly.
  - Reports WHAT changed (old hash, new hash, mtime) rather than
    just "something changed" — you need that detail to judge whether
    a change is one you made yourself.

Usage:
    # First run — creates the baseline, nothing to compare against yet.
    python3 integrity_check.py

    # Every subsequent run — compares current state against baseline.
    python3 integrity_check.py

    # After reviewing a reported change you recognize as your own:
    python3 integrity_check.py --accept

Exit codes:
    0 — clean (no baseline existed and one was just created, OR
        baseline existed and everything matched)
    1 — mismatch detected (tampered, missing, or newly-created file
        not yet in the baseline) — nothing was written
    2 — usage/environment error (e.g. a watched file's directory
        doesn't exist at all)
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

# Edit this list to watch additional files. Paths are resolved
# relative to the current user's home directory by default via the
# ~ in each entry, same convention as the rest of the JARVIS scripts
# — but see the README "Adding a New Tool" checklist note on ~
# resolution: this script is meant to be run directly via SSH as
# yourself, NOT inside the orchestrator container, so ~ here
# resolves the way you'd expect (your own home dir), unlike inside
# the container where it resolves to /root.
WATCHED_FILES = [
    "~/jarvis/orchestrator/.env",
    "~/jarvis/policy.yaml",
]

DEFAULT_BASELINE_PATH = "~/jarvis/.integrity-baseline.json"


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot_current_state(paths):
    """
    Returns (state_dict, errors_list). state_dict is keyed by the
    original (unexpanded) path string so the baseline file stays
    portable/readable regardless of whose home directory it was
    generated under. errors_list holds files that couldn't be read
    (missing, permission denied) — these are reported, not silently
    skipped, since a watched file disappearing is itself a
    significant finding.
    """
    state = {}
    errors = []
    for raw_path in paths:
        expanded = os.path.expanduser(raw_path)
        if not os.path.exists(expanded):
            errors.append({"path": raw_path, "error": "file not found"})
            continue
        try:
            digest = sha256_of(expanded)
            mtime = os.path.getmtime(expanded)
            state[raw_path] = {
                "sha256": digest,
                "mtime": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
                "size_bytes": os.path.getsize(expanded),
            }
        except PermissionError:
            errors.append({"path": raw_path, "error": "permission denied"})
        except OSError as e:
            errors.append({"path": raw_path, "error": str(e)})
    return state, errors


def load_baseline(baseline_path):
    if not os.path.exists(baseline_path):
        return None
    with open(baseline_path) as f:
        return json.load(f)


def write_baseline(baseline_path, state):
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": state,
    }
    # Atomic write, same pattern as jarvis_smart_snapshot.py — a
    # reader (or a crashed write) never sees a half-written baseline.
    tmp_path = baseline_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp_path, baseline_path)
    # Baseline contains hashes of secrets-adjacent files' *paths* and
    # metadata, not the secrets themselves — but keep it locked down
    # anyway, consistent with how .env itself is always handled in
    # this project (600 permissions).
    os.chmod(baseline_path, 0o600)


def compare(baseline_files, current_state):
    """
    Returns a list of change dicts. Covers three cases: a watched
    file's hash changed, a watched file present in the baseline is
    now missing from current_state (already reported separately via
    read errors, but cross-checked here too), and a watched file has
    no baseline entry yet (e.g. WATCHED_FILES was edited to add a
    new path since the baseline was last written).
    """
    changes = []
    all_paths = set(baseline_files.keys()) | set(current_state.keys())
    for path in sorted(all_paths):
        old = baseline_files.get(path)
        new = current_state.get(path)
        if old is None and new is not None:
            changes.append({
                "path": path,
                "kind": "new_file_not_in_baseline",
                "current_sha256": new["sha256"],
            })
        elif old is not None and new is None:
            changes.append({
                "path": path,
                "kind": "missing_or_unreadable",
                "baseline_sha256": old["sha256"],
            })
        elif old["sha256"] != new["sha256"]:
            changes.append({
                "path": path,
                "kind": "hash_mismatch",
                "baseline_sha256": old["sha256"],
                "current_sha256": new["sha256"],
                "baseline_mtime": old["mtime"],
                "current_mtime": new["mtime"],
            })
    return changes


def main():
    parser = argparse.ArgumentParser(description="JARVIS file-integrity check")
    parser.add_argument(
        "--accept", action="store_true",
        help="Overwrite the baseline with the current state. Use this only "
             "after reviewing a reported change and confirming it was one "
             "you made yourself.",
    )
    parser.add_argument(
        "--baseline", default=DEFAULT_BASELINE_PATH,
        help=f"Path to the baseline file (default: {DEFAULT_BASELINE_PATH})",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON instead of human-readable text "
             "(useful once this is wired into the morning digest).",
    )
    args = parser.parse_args()

    baseline_path = os.path.expanduser(args.baseline)
    baseline_dir = os.path.dirname(baseline_path)
    if baseline_dir and not os.path.isdir(baseline_dir):
        print(f"ERROR: baseline directory does not exist: {baseline_dir}", file=sys.stderr)
        sys.exit(2)

    current_state, read_errors = snapshot_current_state(WATCHED_FILES)

    if args.accept:
        # Explicit, out-of-band acceptance — this is the ONLY code
        # path that writes the baseline after the very first run.
        # Files that errored (missing/unreadable) are intentionally
        # excluded from the new baseline rather than silently
        # dropped-and-forgotten — they're reported so you notice a
        # watched file has vanished, even on an --accept run.
        write_baseline(baseline_path, current_state)
        result = {
            "action": "accepted",
            "baseline_path": baseline_path,
            "files_recorded": len(current_state),
            "read_errors": read_errors,
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Baseline updated: {baseline_path}")
            print(f"  {len(current_state)} file(s) recorded.")
            for err in read_errors:
                print(f"  WARNING: {err['path']} — {err['error']} (not recorded)")
        sys.exit(0)

    existing_baseline = load_baseline(baseline_path)

    if existing_baseline is None:
        # First run ever — establish the baseline, nothing to
        # compare against. This is the one implicit write, since
        # there is by definition no prior state to have deviated
        # from yet.
        write_baseline(baseline_path, current_state)
        result = {
            "action": "baseline_created",
            "baseline_path": baseline_path,
            "files_recorded": len(current_state),
            "read_errors": read_errors,
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"No baseline found — created one at {baseline_path}")
            print(f"  {len(current_state)} file(s) recorded as the trusted state.")
            for err in read_errors:
                print(f"  WARNING: {err['path']} — {err['error']} (not recorded)")
        sys.exit(0)

    changes = compare(existing_baseline.get("files", {}), current_state)

    if not changes and not read_errors:
        result = {"action": "check", "status": "clean", "baseline_generated_at": existing_baseline.get("generated_at")}
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"OK — all {len(current_state)} watched file(s) match the baseline "
                  f"(recorded {existing_baseline.get('generated_at')}).")
        sys.exit(0)

    # Something changed — report in detail, write nothing.
    result = {
        "action": "check",
        "status": "CHANGED",
        "baseline_generated_at": existing_baseline.get("generated_at"),
        "changes": changes,
        "read_errors": read_errors,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("CHANGE DETECTED — baseline was NOT updated.")
        print(f"  Baseline recorded: {existing_baseline.get('generated_at')}")
        print()
        for c in changes:
            if c["kind"] == "hash_mismatch":
                print(f"  [MODIFIED] {c['path']}")
                print(f"      baseline hash: {c['baseline_sha256']}")
                print(f"      current  hash: {c['current_sha256']}")
                print(f"      baseline mtime: {c['baseline_mtime']}")
                print(f"      current  mtime: {c['current_mtime']}")
            elif c["kind"] == "missing_or_unreadable":
                print(f"  [MISSING]  {c['path']}")
                print(f"      was in baseline with hash: {c['baseline_sha256']}")
            elif c["kind"] == "new_file_not_in_baseline":
                print(f"  [NEW]      {c['path']}")
                print(f"      current hash: {c['current_sha256']}")
            print()
        for err in read_errors:
            print(f"  WARNING: could not read {err['path']} — {err['error']}")
        print()
        print("If you made this change yourself, review it, then run:")
        print(f"    python3 {os.path.basename(__file__)} --accept")
        print("to record it as the new trusted baseline.")

    sys.exit(1)


if __name__ == "__main__":
    main()
