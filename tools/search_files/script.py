import os
import json
import subprocess

ALLOWED_ROOT = "/mnt/media"
MAX_RESULTS = 30

def run(query):
    if not query or len(query.strip()) < 2:
        return {"error": "Search query must be at least 2 characters."}

    query = query.strip()

    result = subprocess.run(
        ["find", ALLOWED_ROOT, "-iname", f"*{query}*", "-type", "f"],
        capture_output=True, text=True, timeout=15
    )

    if result.returncode != 0 and not result.stdout:
        return {"error": "Search failed or path not accessible."}

    files = [f for f in result.stdout.strip().split("\n") if f]
    truncated = len(files) > MAX_RESULTS
    files = files[:MAX_RESULTS]

    relative_files = [f.replace(ALLOWED_ROOT, "") for f in files]

    return {
        "query": query,
        "results_count": len(relative_files),
        "truncated": truncated,
        "files": relative_files
    }

if __name__ == "__main__":
    query = os.environ.get("TOOL_ARG_query", "")
    print(json.dumps(run(query), indent=2, ensure_ascii=False))
