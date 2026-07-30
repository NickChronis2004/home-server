import os
import json
import subprocess

ALLOWED_ROOT = "/mnt/media"
DEFAULT_COUNT = 10
MAX_COUNT = 30

def run(count):
    try:
        count = int(count)
    except (ValueError, TypeError):
        count = DEFAULT_COUNT
    count = min(max(count, 1), MAX_COUNT)

    result = subprocess.run(
        ["find", ALLOWED_ROOT, "-type", "f", "-printf", "%s %p\\n"],
        capture_output=True, text=True, timeout=15
    )

    if result.returncode != 0:
        return {"error": "Failed to scan media directory."}

    lines = [l for l in result.stdout.strip().split("\n") if l]
    entries = []
    for line in lines:
        parts = line.split(" ", 1)
        if len(parts) == 2:
            try:
                size_bytes = int(parts[0])
                path = parts[1].replace(ALLOWED_ROOT, "")
                entries.append((size_bytes, path))
            except ValueError:
                continue

    entries.sort(reverse=True)
    top = entries[:count]

    def human_size(b):
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if b < 1024:
                return f"{b:.1f}{unit}"
            b /= 1024
        return f"{b:.1f}PB"

    return {
        "files": [{"path": p, "size": human_size(s)} for s, p in top]
    }

if __name__ == "__main__":
    count = os.environ.get("TOOL_ARG_count", "10")
    print(json.dumps(run(count), indent=2, ensure_ascii=False))
