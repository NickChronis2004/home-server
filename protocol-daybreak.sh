#!/bin/bash
set -e

LOCKDOWN_FILE="/home/nickchronis2004/jarvis/logs/.lockdown"

echo "🌅 Protocol DAYBREAK — restoring normal operation..."

# Step 1: lift lockdown flag if present
if [ -f "$LOCKDOWN_FILE" ]; then
    rm -f "$LOCKDOWN_FILE"
    echo "   ✔ Lockdown flag cleared."
else
    echo "   • No lockdown flag was set."
fi

# Step 2: check if orchestrator container is running; restart it if not
# NOTE: this uses the real compose file (docker-compose.proxies.yml) as the
# single source of truth for the orchestrator's service definition -
# proxy networks, DOCKER_*_PROXY env vars, every tool script mount, the
# scoped-proxy depends_on chain. An earlier version of this script had
# its own hardcoded inline definition (including a raw docker.sock mount,
# which the real setup deliberately avoids) that silently drifted out of
# sync with the actual compose file. Referencing the compose file means
# DAYBREAK can never restore a stale or under-privileged orchestrator.
COMPOSE_FILE="/home/nickchronis2004/jarvis/docker-compose.proxies.yml"
STATUS=$(docker inspect -f '{{.State.Status}}' jarvis-orchestrator 2>/dev/null || echo "missing")

if [ "$STATUS" = "running" ]; then
    echo "   • Orchestrator is already running."
else
    echo "   • Orchestrator is not running (status: $STATUS). Bringing it back up..."
    docker compose -f "$COMPOSE_FILE" up -d jarvis-orchestrator
    echo "   ✔ Orchestrator restarted."
fi

sleep 2
HEALTH=$(curl -s http://localhost:8001/health || echo "unreachable")
echo "   • Health check: $HEALTH"
echo "✅ Protocol DAYBREAK complete."
