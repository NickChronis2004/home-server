#!/bin/bash
echo "=== JARVIS Smoke Test ==="
echo ""

PASS=0
FAIL=0

check() {
    if [ $? -eq 0 ]; then
        echo "PASS: $1"
        PASS=$((PASS+1))
    else
        echo "FAIL: $1"
        FAIL=$((FAIL+1))
    fi
}

echo "-- Core containers --"
for c in pihole jellyfin samba vaultwarden uptime-kuma portainer; do
    docker ps --format '{{.Names}}' | grep -q "^${c}$"
    check "container '$c' is running"
done

echo ""
echo "-- AI layer containers --"
for c in ollama open-webui jarvis-orchestrator; do
    docker ps --format '{{.Names}}' | grep -q "^${c}$"
    check "container '$c' is running"
done

echo ""
echo "-- Orchestrator health --"
HEALTH=$(curl -s http://localhost:8001/health)
echo "$HEALTH" | grep -q '"status":"ok"'
check "orchestrator /health returns ok"

TOOLS_COUNT=$(echo "$HEALTH" | grep -o '"tools_loaded":[0-9]*' | grep -o '[0-9]*')
echo "  -> tools_loaded: $TOOLS_COUNT"

echo ""
echo "-- End-to-end chat test --"
RESPONSE=$(curl -s -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What Docker containers are running?"}]}')
echo "$RESPONSE" | grep -q "jarvis-response"
check "chat completions endpoint responds"

echo ""
echo "-- Vaultwarden protection check --"
curl -s -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Restart the vaultwarden container"}]}' > /dev/null
LAST_ERROR_CODE=$(docker exec jarvis-orchestrator python3 -c "
import sqlite3
conn = sqlite3.connect('/app/jarvis/logs/audit.db')
row = conn.execute(\"SELECT error_code FROM tool_calls WHERE tool_name='restart_container' ORDER BY id DESC LIMIT 1\").fetchone()
print(row[0] if row else '')
conn.close()
")
[ "$LAST_ERROR_CODE" = "TOOL_LOGICAL_ERROR" ]
check "vaultwarden restart request is refused (verified via audit log)"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
if [ $FAIL -gt 0 ]; then
    exit 1
fi
exit 0
