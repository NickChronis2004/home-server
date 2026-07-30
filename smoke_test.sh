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
PROTECT_RESPONSE=$(curl -s -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Restart the vaultwarden container"}]}')
echo "$PROTECT_RESPONSE" | grep -qi "protected\|unable\|cannot"
check "vaultwarden restart request is refused"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
if [ $FAIL -gt 0 ]; then
    exit 1
fi
exit 0
