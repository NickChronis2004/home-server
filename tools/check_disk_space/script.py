import subprocess
import json
import sys
sys.path.insert(0, "/app/jarvis/lib")
from redact import redact

# Only show these mount points - the ones that actually matter to the user
RELEVANT_MOUNTS = ["/"]

def run():
    result = subprocess.run(
        ["df", "-h", "--output=source,size,used,avail,pcent,target"],
        capture_output=True, text=True
    )
    lines = result.stdout.strip().split("\n")
    rows = []
    for line in lines[1:]:
        parts = line.split(None, 5)
        if len(parts) == 6:
            mount = parts[5]
            if mount in RELEVANT_MOUNTS:
                rows.append({
                    "size": parts[1],
                    "used": parts[2],
                    "available": parts[3],
                    "use_percent": parts[4],
                    "mounted_on": redact(mount)
                })
    return rows

if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False))
