#!/bin/bash
echo "JARVIS Emergency Kill Switch — stopping AI layer containers..."
docker stop ollama open-webui 2>/dev/null
echo "Done. Core services (jellyfin, pihole, samba, vaultwarden, portainer, uptime-kuma) remain untouched."
