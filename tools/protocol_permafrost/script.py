import subprocess
import json
import os
import time
import re
from pathlib import Path

# The orchestrator container only has /app/jarvis mounted (bind-mount
# of the host's ~/jarvis) - it does NOT see the host user's home
# directory. So the backup script must live inside ~/jarvis/ on the
# host (== /app/jarvis/ inside the container), not in the SSH user's
# home directory.
BACKUP_SCRIPT = Path("/app/jarvis/backup.sh")

# CRITICAL: backup.sh itself calls `docker run -v <path>:/backup ...` to
# archive each volume. Because the orchestrator talks to the HOST's
# Docker daemon via the mounted docker.sock (not a nested daemon), any
# path passed to `docker run -v` must be a path the HOST filesystem
# understands - not a path relative to this container's own filesystem
# view. /app/jarvis inside this container corresponds to a different,
# real path on the host: /home/nickchronis2004/jarvis. So we must
# explicitly set JARVIS_HOME/BACKUP_ROOT to their HOST-side equivalents
# before invoking backup.sh from here, overriding its container-blind
# $HOME-based defaults.
HOST_JARVIS_ROOT = "/home/nickchronis2004/jarvis"

PENDING_FILE = Path("/app/jarvis/logs/.pending_confirmation.json")
COOLDOWN_FILE = Path("/app/jarvis/logs/.permafrost_cooldowns.json")
PENDING_EXPIRY_SECONDS = 120
COOLDOWN_SECONDS = 300  # avoid accidental back-to-back runs; backups are I/O heavy

# Matches the summary lines backup.sh prints (each preceded by its own
# "[YYYY-MM-DD HH:MM:SS] " log timestamp), e.g.:
#   "[2026-07-31 11:38:26]   volume:vaultwarden_vaultwarden_data:OK"
#   "[2026-07-31 11:38:26]   secrets(.env):OK"
#   "[2026-07-31 11:38:26]   sync-external:SKIPPED(not mounted)"
STEP_LINE_PATTERN = re.compile(
    r'^\[[\d\- :]+\]\s+([\w:.\-()]+):(OK|FAIL|SKIPPED\([^)]*\))\s*$'
)


def get_cooldown_remaining():
    if not COOLDOWN_FILE.exists():
        return None
    try:
        last = json.loads(COOLDOWN_FILE.read_text()).get("last_run")
    except json.JSONDecodeError:
        return None
    if last is None:
        return None
    elapsed = time.time() - last
    if elapsed < COOLDOWN_SECONDS:
        return int(COOLDOWN_SECONDS - elapsed)
    return None


def set_cooldown():
    COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
    COOLDOWN_FILE.write_text(json.dumps({"last_run": time.time()}))


def set_pending():
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(json.dumps({
        "tool": "protocol_permafrost",
        "created_at": time.time()
    }))


def parse_summary(stdout: str):
    """Extract the per-step OK/FAIL/SKIPPED results backup.sh already
    logs, instead of re-deriving success from exit code alone. This is
    the same 'independent verification, don't just trust the claim'
    principle used in restart_container - here the source of truth is
    backup.sh's own structured summary block, not a guess."""
    steps = {}
    for line in stdout.splitlines():
        m = STEP_LINE_PATTERN.match(line)
        if m:
            steps[m.group(1)] = m.group(2)
    return steps


def run(confirmed):
    if not BACKUP_SCRIPT.exists():
        return {"error": f"Backup script not found at {BACKUP_SCRIPT}."}

    remaining = get_cooldown_remaining()
    if remaining:
        return {"error": f"PERMAFROST ran recently. Please wait {remaining} more seconds before running it again."}

    if not confirmed:
        set_pending()
        return {
            "status": "confirmation_required",
            "message": "This will run a full JARVIS backup (PERMAFROST): JARVIS config, secrets, logs, and all Docker volumes, synced to the external disk if mounted. It can take 1-2 minutes. Tell the user to type exactly /confirm (nothing else) within 2 minutes to proceed. Do not proceed without that exact command from the user."
        }

    try:
        env = {
            **os.environ,
            # JARVIS_HOME/BACKUP_ROOT drive this script's own file
            # operations (tar, cp, mkdir) - those run against THIS
            # process's filesystem view, which is the container's, where
            # /app/jarvis is the real, bind-mounted path (== host's
            # ~/jarvis). Using the host-string path here instead would
            # silently write into an unmounted, throwaway directory tree
            # inside the container that vanishes on rebuild and is
            # invisible from the host SSH session.
            "JARVIS_HOME": "/app/jarvis",
            "BACKUP_ROOT": "/app/jarvis/jarvis-backups",
            # DOCKER_HOST_BACKUP_ROOT is different: it's used ONLY for
            # `docker run -v <path>:...` arguments inside backup.sh,
            # which are resolved by the HOST's Docker daemon (reached via
            # the mounted docker.sock), not by this process. The daemon
            # needs the real host-side path.
            "DOCKER_HOST_BACKUP_ROOT": f"{HOST_JARVIS_ROOT}/jarvis-backups",
            # EXTERNAL_MOUNT intentionally left as backup.sh's own default
            # (/mnt/backup_external) - that path is set up directly on
            # the host and is the same whether accessed from here or
            # from the host shell.
        }
        result = subprocess.run(
            [str(BACKUP_SCRIPT)],
            capture_output=True, text=True, timeout=600,
            env=env
        )
    except subprocess.TimeoutExpired:
        return {"error": "Backup timed out after 10 minutes. Check backup.log on the server directly."}

    set_cooldown()
    steps = parse_summary(result.stdout)
    failed_steps = [name for name, status in steps.items() if status == "FAIL"]

    if result.returncode != 0 or failed_steps:
        return {
            "status": "completed_with_failures",
            "codename": "PERMAFROST",
            "exit_code": result.returncode,
            "failed_steps": failed_steps,
            "step_results": steps,
            "message": "Backup ran but one or more steps failed. Check ~/jarvis-backups/backup.log on the server for details."
        }

    return {
        "status": "success",
        "codename": "PERMAFROST",
        "step_results": steps,
        "message": "Backup completed successfully. All steps OK."
    }


if __name__ == "__main__":
    confirmed_raw = os.environ.get("TOOL_ARG_confirmed", "false")
    confirmed = confirmed_raw.lower() in ("true", "1", "yes")
    print(json.dumps(run(confirmed), indent=2, ensure_ascii=False))
