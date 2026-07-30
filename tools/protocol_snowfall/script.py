import json
import time
from pathlib import Path

LOCKDOWN_FILE = Path("/app/jarvis/logs/.lockdown")

def run():
    LOCKDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCKDOWN_FILE.write_text(json.dumps({
        "activated_at": time.time(),
        "activated_via": "chat"
    }))
    return {
        "status": "success",
        "protocol": "SNOWFALL",
        "message": "Emergency lockdown is now active. All write actions (restart/stop/start) are disabled. Diagnostics remain available. Recovery requires direct server access."
    }

if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False))
