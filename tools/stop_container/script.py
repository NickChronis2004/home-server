import subprocess
import json
import os
import time
import yaml
from pathlib import Path

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

def run(container_name, confirmed):
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
        capture_output=True, text=True, timeout=30
    )

    if result.returncode != 0:
        return {"error": f"Stop failed: {result.stderr[:300]}"}

    status_result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", container_name],
        capture_output=True, text=True, timeout=10
    )
    new_status = status_result.stdout.strip()

    return {
        "status": "success",
        "container": container_name,
        "action": "stopped",
        "current_state": new_status
    }

if __name__ == "__main__":
    container_name = os.environ.get("TOOL_ARG_container_name", "")
    confirmed_raw = os.environ.get("TOOL_ARG_confirmed", "false")
    confirmed = confirmed_raw.lower() in ("true", "1", "yes")
    print(json.dumps(run(container_name, confirmed), indent=2, ensure_ascii=False))
