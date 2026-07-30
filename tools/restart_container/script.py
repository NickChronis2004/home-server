import subprocess
import json
import os
import time
import yaml
from pathlib import Path

POLICY_FILE = Path("/app/jarvis/policy.yaml")
COOLDOWN_FILE = Path("/app/jarvis/logs/.restart_cooldowns.json")
PENDING_FILE = Path("/app/jarvis/logs/.pending_confirmation.json")
PENDING_EXPIRY_SECONDS = 120

def load_policy():
    with open(POLICY_FILE) as f:
        return yaml.safe_load(f)

def get_cooldowns():
    if COOLDOWN_FILE.exists():
        try:
            return json.loads(COOLDOWN_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}

def set_cooldown(container_name):
    COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
    cooldowns = get_cooldowns()
    cooldowns[container_name] = time.time()
    COOLDOWN_FILE.write_text(json.dumps(cooldowns))

def check_cooldown(container_name, cooldown_seconds):
    cooldowns = get_cooldowns()
    last = cooldowns.get(container_name)
    if last is None:
        return None
    elapsed = time.time() - last
    if elapsed < cooldown_seconds:
        return int(cooldown_seconds - elapsed)
    return None

def set_pending(container_name):
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(json.dumps({
        "tool": "restart_container",
        "container_name": container_name,
        "created_at": time.time()
    }))

import re

VALID_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]*$')

def run(container_name, confirmed):
    if not container_name or not VALID_NAME_PATTERN.match(container_name.strip()):
        return {"error": "Invalid container name format."}

    policy = load_policy()
    allowed_targets = policy.get("restart_allowed_targets", [])
    protected = policy.get("protected_containers", [])
    cooldown_seconds = policy.get("limits", {}).get("restart_cooldown_seconds", 120)

    container_name = container_name.strip().lower()

    if container_name in protected:
        return {"error": f"'{container_name}' is a protected resource and cannot be restarted via this tool."}

    if container_name not in allowed_targets:
        return {"error": f"'{container_name}' is not in the allowed restart list. Allowed: {allowed_targets}"}

    remaining = check_cooldown(container_name, cooldown_seconds)
    if remaining:
        return {"error": f"'{container_name}' was recently restarted. Please wait {remaining} more seconds before trying again."}

    if not confirmed:
        set_pending(container_name)
        return {
            "status": "confirmation_required",
            "message": f"This will restart the '{container_name}' container. Tell the user to type exactly /confirm (nothing else) within 2 minutes to proceed. Do not proceed without that exact command from the user."
        }

    result = subprocess.run(
        ["docker", "restart", container_name],
        capture_output=True, text=True, timeout=30
    )

    if result.returncode != 0:
        return {"error": f"Restart failed: {result.stderr[:300]}"}

    set_cooldown(container_name)

    time.sleep(2)
    status_result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", container_name],
        capture_output=True, text=True, timeout=10
    )
    new_status = status_result.stdout.strip()

    return {
        "status": "success",
        "container": container_name,
        "action": "restarted",
        "current_state": new_status
    }

if __name__ == "__main__":
    container_name = os.environ.get("TOOL_ARG_container_name", "")
    confirmed_raw = os.environ.get("TOOL_ARG_confirmed", "false")
    confirmed = confirmed_raw.lower() in ("true", "1", "yes")
    print(json.dumps(run(container_name, confirmed), indent=2, ensure_ascii=False))
