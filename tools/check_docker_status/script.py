import subprocess
import json
import sys
sys.path.insert(0, "/app/jarvis/lib")
from redact import redact

PROTECTED_CONTAINERS = ["vaultwarden"]

def run():
    result = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{json .}}"],
        capture_output=True, text=True
    )
    containers = [json.loads(line) for line in result.stdout.strip().split("\n") if line]
    output = []
    for c in containers:
        name = c.get("Names")
        if name in PROTECTED_CONTAINERS:
            continue  # never expose protected containers, even status
        output.append({
            "name": name,
            "status": redact(c.get("Status", "")),
            "image": c.get("Image")
        })
    return output

if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False))
