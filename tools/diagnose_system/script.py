import subprocess
import json
import sys
sys.path.insert(0, "/app/jarvis/lib")
from redact import redact
from docker_env import docker_env

PROTECTED_CONTAINERS = ["vaultwarden"]

LOG_TAIL_LINES = 15
LOG_MAX_CHARS_PER_CONTAINER = 800
ERROR_PATTERNS = ["error", "fatal", "exception", "panic", "traceback", "denied", "refused"]


def get_containers():
    result = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{json .}}"],
        capture_output=True, text=True, timeout=15,
	env=docker_env("read"),
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker ps failed: {result.stderr[:300]}")
    containers = [json.loads(line) for line in result.stdout.strip().split("\n") if line]
    return [c for c in containers if c.get("Names") not in PROTECTED_CONTAINERS]


def get_health(name):
    result = subprocess.run(
        ["docker", "inspect", name, "--format",
         '{{json .State}}|||{{.RestartCount}}'],
        capture_output=True, text=True, timeout=10,
        env=docker_env("read"),
    )
    if result.returncode != 0:
        return {"health": "unknown", "restart_count": None}
    try:
        state_json, restart_count = result.stdout.strip().split("|||")
        state = json.loads(state_json)
        return {
            "status": state.get("Status"),
            "health": state.get("Health", {}).get("Status", "none"),
            "restart_count": int(restart_count)
        }
    except (ValueError, json.JSONDecodeError):
        return {"health": "unknown", "restart_count": None}


def get_error_lines(name):
    result = subprocess.run(
        ["docker", "logs", "--tail", str(LOG_TAIL_LINES), name],
        capture_output=True, text=True, timeout=10,
        env=docker_env("read"),
    )
    combined = (result.stdout + result.stderr).strip()
    if not combined:
        return []
    matches = [
        line for line in combined.split("\n")
        if any(p in line.lower() for p in ERROR_PATTERNS)
    ]
    joined = redact("\n".join(matches))
    if len(joined) > LOG_MAX_CHARS_PER_CONTAINER:
        joined = joined[-LOG_MAX_CHARS_PER_CONTAINER:]
    return joined.split("\n") if joined else []


def get_disk_usage():
    result = subprocess.run(
        ["docker", "system", "df", "--format", "{{json .}}"],
        capture_output=True, text=True, timeout=15,
        env=docker_env("read"),
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker system df failed: {result.stderr[:300]}")
    rows = [json.loads(line) for line in result.stdout.strip().split("\n") if line]
    return rows

def run():
    try:
        containers = get_containers()
    except RuntimeError as e:
        return {"error": str(e)}
    container_report = []
    for c in containers:
        name = c.get("Names")
        health = get_health(name)
        errors = get_error_lines(name)
        container_report.append({
            "name": name,
            "status": redact(c.get("Status", "")),
            "health": health.get("health"),
            "restart_count": health.get("restart_count"),
            "recent_error_lines": errors
        })
    try:
        disk_usage = get_disk_usage()
    except RuntimeError as e:
        disk_usage = {"error": str(e)}
    return {
        "containers": container_report,
        "disk_usage": disk_usage
    }

if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False))
