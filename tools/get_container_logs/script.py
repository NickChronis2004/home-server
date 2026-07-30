import subprocess
import json
import sys
import os
sys.path.insert(0, "/app/jarvis/lib")
from redact import redact

PROTECTED_CONTAINERS = ["vaultwarden"]
MAX_LINES = 50
MAX_CHARS = 4000

def run(container_name):
    if container_name in PROTECTED_CONTAINERS:
        return {"error": "Access to this container's logs is not permitted."}

    result = subprocess.run(
        ["docker", "logs", "--tail", str(MAX_LINES), container_name],
        capture_output=True, text=True, timeout=15
    )
    output = result.stdout + result.stderr
    output = redact(output)
    if len(output) > MAX_CHARS:
        output = output[-MAX_CHARS:]
    return {"container": container_name, "logs": output}

if __name__ == "__main__":
    container_name = os.environ.get("TOOL_ARG_container_name", "")
    print(json.dumps(run(container_name), indent=2, ensure_ascii=False))
