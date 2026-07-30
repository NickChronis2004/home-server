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
STATUS=$(docker inspect -f '{{.State.Status}}' jarvis-orchestrator 2>/dev/null || echo "missing")

if [ "$STATUS" = "running" ]; then
    echo "   • Orchestrator is already running."
else
    echo "   • Orchestrator is not running (status: $STATUS). Bringing it back up..."
    docker rm -f jarvis-orchestrator > /dev/null 2>&1 || true
    docker compose -f - up -d << 'COMPOSE_EOF'
services:
  jarvis-orchestrator:
    container_name: jarvis-orchestrator
    image: jarvis-orchestrator:latest
    ports:
      - "8001:8001"
    volumes:
      - /home/nickchronis2004/jarvis:/app/jarvis
      - /var/run/docker.sock:/var/run/docker.sock
      - /home/nickchronis2004/media:/mnt/media:ro
    env_file:
      - /home/nickchronis2004/jarvis/orchestrator/.env
    environment:
      TZ: 'Europe/Athens'
    restart: unless-stopped
    networks:
      jarvis-ai-net:
        ipv4_address: 172.26.0.4

networks:
  jarvis-ai-net:
    external: true
COMPOSE_EOF
    echo "   ✔ Orchestrator restarted."
fi

sleep 2
HEALTH=$(curl -s http://localhost:8001/health || echo "unreachable")
echo "   • Health check: $HEALTH"
echo "✅ Protocol DAYBREAK complete."
