#!/bin/bash
# sandbox_reaper.sh -- Ανεξάρτητο safety net για το JARVIS sandbox tool.
#
# Σκοτώνει οποιοδήποτε container με prefix "jarvis-sandbox-run-" που ζει
# πάνω από MAX_AGE_SECONDS. Αυτό υπάρχει ως δεύτερη γραμμή άμυνας: το
# ίδιο το sandbox.py tool έχει δικό του cleanup (finally block), αλλά αν
# ο orchestrator κάνει SIGKILL στο tool's process (π.χ. λόγω του δικού
# του 120s hard timeout) πριν προλάβει να τρέξει το finally, θα μας
# μείνει ορφανό container. Αυτό το script τα καθαρίζει.
#
# Προτεινόμενο cron: κάθε 5 λεπτά.
#   */5 * * * * /home/nickchronis2004/jarvis/tools/sandbox/sandbox_reaper.sh >> /home/nickchronis2004/jarvis/logs/sandbox_reaper.log 2>&1

set -euo pipefail

MAX_AGE_SECONDS=300   # 5 λεπτά -- πολύ πάνω από το normal ~60s worst-case του tool
PREFIX="jarvis-sandbox-run-"
NOW=$(date +%s)

CONTAINERS=$(docker ps -a --filter "name=${PREFIX}" --format '{{.Names}}' || true)

if [ -z "$CONTAINERS" ]; then
    exit 0
fi

while IFS= read -r name; do
    [ -z "$name" ] && continue

    created_raw=$(docker inspect "$name" --format '{{.Created}}' 2>/dev/null || echo "")
    if [ -z "$created_raw" ]; then
        continue
    fi

    created_epoch=$(date -d "$created_raw" +%s 2>/dev/null || echo "0")
    age=$((NOW - created_epoch))

    if [ "$age" -gt "$MAX_AGE_SECONDS" ]; then
        echo "[$(date -Iseconds)] Reaping orphaned sandbox container: $name (age: ${age}s)"
        docker rm -f "$name" >/dev/null 2>&1 || true
    fi
done <<< "$CONTAINERS"
