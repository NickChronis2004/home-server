#!/bin/bash
LOCKDOWN_FILE="/home/nickchronis2004/jarvis/logs/.lockdown"
mkdir -p "$(dirname "$LOCKDOWN_FILE")"
echo "{\"activated_at\": $(date +%s), \"activated_via\": \"local_script\"}" > "$LOCKDOWN_FILE"
echo "❄️  Protocol SNOWFALL active — write actions disabled, diagnostics still available."
echo "    Recovery: run protocol-daybreak.sh"
