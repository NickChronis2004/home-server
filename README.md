# JARVIS — Home Server AI Assistant

Personal home server με local-first AI assistant, βασισμένο σε Docker, με tool-calling ικανότητα πάνω στο ίδιο το σύστημα.

## Αρχιτεκτονική

Lenovo Yoga Slim 5 (Ubuntu Server 24.04, i5, 16GB RAM, 500GB SSD)
├── Core Services (Docker containers)
│ ├── Pi-hole :8080 — ad-blocking DNS
│ ├── Jellyfin :8096 — media server
│ ├── Samba 445 — file sharing (\100.103.21.5\media)
│ ├── Vaultwarden :8081 — password manager (HTTPS via Tailscale serve)
│ ├── Uptime Kuma :3001 — monitoring + Telegram alerts
│ └── Portainer :9443 — Docker management UI
│
├── AI Layer
│ ├── Ollama :11434 — local LLM (phi4-mini, unreliable tool-calling)
│ ├── Open WebUI :3000 — chat interface
│ └── jarvis-orchestrator :8001 — custom FastAPI service, tool execution
│
└── Networking
├── Tailscale VPN — remote access (100.103.21.5, homeserver.tailec97a4.ts.net)
└── jarvis-ai-net — isolated Docker network for AI stack


## JARVIS Tool System

jarvis/
├── policy.yaml # hardcoded safety rules
├── kill-switch.sh # emergency stop for AI layer only
├── lib/redact.py # strips secrets from tool output
├── tools/ # each tool = folder with manifest.yaml + script.py
│ ├── check_docker_status/
│ ├── check_disk_space/
│ ├── check_system_resources/
│ └── get_container_logs/
└── orchestrator/
├── main.py # FastAPI, OpenAI-compatible endpoint
├── errors.py # exception hierarchy
└── subprocess_wrapper.py # safe command execution


**Model**: GPT-4o (configurable via `JARVIS_MODEL` env var). Local phi4-mini kept for basic chat only — tool-calling reliability was ~50%, unacceptable for real use.

**Safety**: Vaultwarden is fully blacklisted from all tools. No tool has write access yet (read-only tier only, as of this writing).

## Setup History

| Phase | Ημερομηνία | Τι έγινε |
|---|---|---|
| 1 — Foundation | Day 1 | Ubuntu Server, SSH, Tailscale, Docker, Portainer |
| 2 — Core Services | Day 1 | Pi-hole, Jellyfin, Samba, Vaultwarden |
| 2.5 — Monitoring | Day 1 | Uptime Kuma + Telegram alerts |
| 3 — AI Layer | Day 2 | Ollama, Open WebUI, OpenAI integration |
| 3.5 — Tool System | Day 2 | jarvis-orchestrator, Phase 0 security (policy.yaml, kill switch, network isolation), 4 read-only tools |
| 3.6 — Hardening | Day 3 | Secret cleanup (.env), exception handling, GitHub repo |

## Known Issues / Quirks

- **Samba write permissions**: `dperson/samba` image runs as internal `smbuser` (uid 100), not the host user (uid 1000). Fixed with `chmod -R 777 ~/media`. Not ideal long-term but works.
- **jarvis-orchestrator ↔ Open WebUI DNS flakiness**: Fixed by declaring a static IP (`172.26.0.4`) directly in the Docker Compose network config (`ipv4_address` under `jarvis-ai-net`), instead of relying on hostname resolution. This IP is now permanent and will not change on container recreation.
- **Open WebUI auto-features**: "Αυτόματη Γενιά Τίτλων" and similar auto-generation features send extra requests to whatever model is selected, which can fail against custom endpoints. Disabled in Admin Panel → Settings → Interface.
- **Docker socket access**: jarvis-orchestrator has `/var/run/docker.sock` mounted to run `docker` commands. This is a known security tradeoff — see roadmap for planned "policy broker" pattern to reduce this exposure.

## Quick Reference

- SSH: `ssh nickchronis2004@100.103.21.5`
- Server Tailscale IP: `100.103.21.5`
- Vaultwarden HTTPS: `https://homeserver.tailec97a4.ts.net`
- Portainer: `https://100.103.21.5:9443`
- Rebuild orchestrator after code changes:
```bash
  cd ~/jarvis/orchestrator
  docker build --no-cache -t jarvis-orchestrator:latest .
  docker stop jarvis-orchestrator && docker rm jarvis-orchestrator
  docker compose -f - up -d << 'EOF'
  # (see orchestrator compose in Portainer for full config)
  EOF
```
- Kill switch (stop AI layer only, core services unaffected): `~/jarvis/kill-switch.sh`

## Roadmap

- [ ] Confirm-required tools (e.g. `restart_container`) with allowlists + cooldowns
- [ ] Central audit log (SQLite)
- [ ] Docker Policy Broker (reduce direct socket access)
- [ ] Backup/rollback system

## Confirm-Required Tools

Tools that change system state require explicit confirmation via a deterministic `/confirm` command — **not** natural language like "yes" or "go ahead". This is intentional: the orchestrator recognizes `/confirm` in code, before the message ever reaches the LLM, so there's no risk of the model misinterpreting ambiguous confirmation language.

Flow:
1. User requests an action (e.g. "restart jellyfin")
2. Tool checks policy (protected list, allowlist, cooldown) and writes a pending confirmation record if allowed
3. Tool returns a "confirmation_required" message; the LLM relays this to the user
4. User must type exactly `/confirm` (nothing else) within 2 minutes
5. Orchestrator intercepts `/confirm`, bypasses the LLM entirely, and executes the pending action directly

### `restart_container`
First confirm-required tool. Restarts an allowlisted Docker container (jellyfin, pihole, samba, uptime-kuma). Vaultwarden and other protected containers are rejected before any confirmation step. Has a 120-second cooldown per container to prevent restart loops.

**Known quirk**: Asking to restart the same container twice within the same chat session may cause GPT to respond based on conversation history instead of actually calling the tool again (no new confirmation gets created). Workaround: start a new chat for a repeat action, or wait for the existing confirmation prompt to naturally resolve first.
