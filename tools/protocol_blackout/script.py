import json
import os
import time
import subprocess
from pathlib import Path

PENDING_FILE = Path("/app/jarvis/logs/.pending_confirmation.json")

def set_pending():
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(json.dumps({
        "tool": "protocol_blackout",
        "container_name": "jarvis-orchestrator",
        "created_at": time.time()
    }))

def run(confirmed):
    if not confirmed:
        set_pending()
        return {
            "status": "confirmation_required",
            "message": "This will COMPLETELY STOP the JARVIS orchestrator - all access, including diagnostics, will be lost until someone restarts it directly on the server. Tell the user to type exactly /confirm (nothing else) within 2 minutes to proceed. Do not proceed without that exact command from the user."
        }
    # Schedule the stop slightly delayed so this response can still be returned to the user
    # before the container that's running this script goes down.
    subprocess.Popen(
        ["sh", "-c", "sleep 2 && docker stop jarvis-orchestrator"],
    )
    return {
        "status": "success",
        "protocol": "BLACKOUT",
        "message": "Stopping the orchestrator now. All access will be lost in a few seconds. Recovery requires direct server access (Protocol Daybreak)."
    }

if __name__ == "__main__":
    confirmed_raw = os.environ.get("TOOL_ARG_confirmed", "false")
    confirmed = confirmed_raw.lower() in ("true", "1", "yes")
    print(json.dumps(run(confirmed), indent=2, ensure_ascii=False))
