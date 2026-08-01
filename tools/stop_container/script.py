import subprocess
import json
import os
import time
import yaml
from pathlib import Path

import sys
sys.path.insert(0, "/app/jarvis/lib")
from docker_env import docker_env

POLICY_FILE = Path("/app/jarvis/policy.yaml")
PENDING_FILE = Path("/app/jarvis/logs/.pending_confirmation.json")

def load_policy():
    with open(POLICY_FILE) as f:
        return yaml.safe_load(f)

def set_pending(container_name):
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(json.dumps({
        "tool": "stop_container",
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

    container_name = container_name.strip().lower()

    if container_name in protected:
        return {"error": f"'{container_name}' is a protected resource and cannot be stopped via this tool."}

    if container_name not in allowed_targets:
        return {"error": f"'{container_name}' is not in the allowed list for this action. Allowed: {allowed_targets}"}

    if not confirmed:
        set_pending(container_name)
        return {
            "status": "confirmation_required",
            "message": f"This will STOP the '{container_name}' container. It will remain stopped until manually started again. Tell the user to type exactly /confirm within 2 minutes to proceed."
        }

    result = subprocess.run(
        ["docker", "stop", container_name],
        capture_output=True, text=True, timeout=30,
	env=docker_env("lifecycle"),
    )

    if result.returncode != 0:
        return {"error": f"Stop failed: {result.stderr[:300]}"}

    inspect_result = subprocess.run(
        ["docker", "inspect", "--format",
         "{{.State.Status}}|{{.State.StartedAt}}|{{.Id}}", container_name],
        capture_output=True, text=True, timeout=10,
	env=docker_env("read"),
    )
    parts = inspect_result.stdout.strip().split("|")
    new_status = parts[0] if len(parts) > 0 else "unknown"
    started_at = parts[1] if len(parts) > 1 else "unknown"
    container_id = parts[2][:12] if len(parts) > 2 else "unknown"

    return {
        "status": "success",
        "container": container_name,
        "action": "stopped",
        "current_state": new_status,
        "started_at": started_at,
        "container_id": container_id
    }

if __name__ == "__main__":
    container_name = os.environ.get("TOOL_ARG_container_name", "")
    confirmed_raw = os.environ.get("TOOL_ARG_confirmed", "false")
    confirmed = confirmed_raw.lower() in ("true", "1", "yes")
    print(json.dumps(run(container_name, confirmed), indent=2, ensure_ascii=False))
