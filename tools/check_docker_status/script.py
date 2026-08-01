import subprocess
import json
import sys
sys.path.insert(0, "/app/jarvis/lib")
from redact import redact
from docker_env import docker_env

PROTECTED_CONTAINERS = ["vaultwarden"]

def run():
    result = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{json .}}"],
        capture_output=True, text=True,
        env=docker_env("read"),
    )
    if result.returncode != 0:
        return {"error": f"docker ps failed: {result.stderr[:300]}"}
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
