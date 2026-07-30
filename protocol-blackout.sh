#!/bin/bash
echo "🔌 Protocol BLACKOUT — stopping jarvis-orchestrator completely..."
docker stop jarvis-orchestrator
echo "Orchestrator stopped. Recovery: run protocol-daybreak.sh"
