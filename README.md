# JARVIS Home Server — User Guide

Your home server with a local-first AI assistant. This document is the user guide — what you can do, how to talk to JARVIS, what each emergency protocol does, and how to back up / restore. For technical internals (architecture, code), see the comments inside the files themselves.

---

## Table of Contents

1. [Quick Access](#quick-access)
2. [What's Running on the Server](#whats-running-on-the-server)
3. [Talking to JARVIS](#talking-to-jarvis)
4. [JARVIS Tools](#jarvis-tools)
5. [Emergency Protocols](#emergency-protocols)
6. [Kill Switch](#kill-switch)
7. [Backup & Restore](#backup--restore)
8. [Sandbox — Running Code](#sandbox--running-code)
9. [Security — What's Protected](#security--whats-protected)
10. [Common Issues](#common-issues)
11. [Roadmap](#roadmap)

---

## Quick Access

| What | Where |
|---|---|
| SSH | `ssh nickchronis2004@100.103.21.5` |
| JARVIS chat (Open WebUI) | `http://100.103.21.5:3000` |
| Vaultwarden (passwords) | `https://homeserver.tailec97a4.ts.net` |
| Portainer (Docker UI) | `https://100.103.21.5:9443` |
| Jellyfin (media) | `http://100.103.21.5:8096` |
| Pi-hole (DNS/ads) | `http://100.103.21.5:8080` |
| Uptime Kuma (monitoring) | `http://100.103.21.5:3001` |
| Files (Samba) | `\\100.103.21.5\media` |
| Tailscale hostname | `homeserver.tailec97a4.ts.net` |

Everything is only reachable through your Tailscale VPN — no ports are forwarded to the public internet.

---

## What's Running on the Server

**Hardware**: Lenovo Yoga Slim 5 — Ubuntu Server 24.04, i5, 16GB RAM, 500GB SSD.

**Core services** (Docker containers):
- **Jellyfin** — media server
- **Pi-hole** — DNS-level ad blocking
- **Samba** — network file sharing
- **Vaultwarden** — password manager (fully protected, see [Security](#security--whats-protected))
- **Uptime Kuma** — monitoring with Telegram alerts
- **Portainer** — graphical Docker management UI

**AI layer**:
- **jarvis-orchestrator** — the "brain," a FastAPI service that receives your messages and decides which tools to call
- **Open WebUI** — the chat interface where you talk to JARVIS
- **Ollama** — local model (available for basic chat, but JARVIS uses GPT-4o for tool-calling due to reliability)

**Networking**: Tailscale VPN for remote access, a separate isolated Docker network (`jarvis-ai-net`) for the AI stack.

---

## Talking to JARVIS

Open Open WebUI (`http://100.103.21.5:3000`) and just type normally, in English or Greek. JARVIS understands natural language and decides on its own which tool fits.

**Example prompts that work:**

- "What containers are running?"
- "How much disk space is left?"
- "Show me jellyfin's logs"
- "Search for a file called bunny"
- "What are the largest files on the media drive?"
- "Restart jellyfin"
- "Is everything OK with the system?" / "check the docker disk usage"
- "Clean up the docker disk" / "free up build cache space now"
- "Run a backup now" / "activate protocol permafrost"
- "Activate emergency lockdown" / "activate protocol snowfall"

**Important — for actions that change something** (restarting a container, backups, etc.), JARVIS will **always** ask for confirmation before proceeding. You must reply with **exactly** `/confirm` (nothing else — not "yes" or "go ahead") within 2 minutes. This is intentional: the system recognizes `/confirm` before the message ever reaches the AI model, so there's no risk of a misread confirmation.

If 2 minutes pass without `/confirm`, the action is automatically cancelled and you'll need to ask again.

---

## JARVIS Tools

### Read-only (run automatically, no confirmation)

| Tool | What it does |
|---|---|
| `diagnose_system` | Full health check in one call: container status, health, restart counts, recent error-like log lines, and Docker disk usage breakdown. Use this first for anything that sounds like "check if everything's OK" |
| `check_docker_status` | Which containers are running and their health |
| `check_disk_space` | Available/used disk space |
| `check_system_resources` | CPU and RAM usage |
| `check_system_info` | Hardware specs, OS version, kernel |
| `get_container_logs` | Recent logs from a container |
| `search_files` | Search for files in media (movies, shows, music) |
| `list_large_files` | The largest files in media (useful for freeing space) |

### Confirm-required (need `/confirm`)

| Tool | What it does | Allowed targets |
|---|---|---|
| `restart_container` | Restarts a container | jellyfin, pihole, samba, uptime-kuma |
| `stop_container` | Stops a container | same list |
| `start_container` | Starts a stopped container | same list |
| `repair_system` | Runs a specific pre-approved repair: `clean_docker_disk` (dangling images, stopped containers >24h, unused networks, build cache >24h) or `clean_build_cache` (all build cache, any age — always safe, just slower next `docker build`) | — |
| `protocol_permafrost` | Full system backup | — (see [Backup & Restore](#backup--restore)) |

**Vaultwarden is never a valid target** for any of these — it doesn't even appear on the allowed-targets list. JARVIS cannot touch it in any way.

Every container-based action has a **120-second cooldown** — if you just restarted something, you can't immediately do it again (protection against restart loops).

### Emergency (run instantly, no confirmation)

| Tool | What it does |
|---|---|
| `protocol_snowfall` | Activates lockdown — see below |

---

## Emergency Protocols

Three levels of response if something goes wrong, from mildest to most drastic.

### ❄️ SNOWFALL — Soft Lockdown

**How to activate:** From chat, just tell JARVIS (e.g. "activate protocol snowfall" or "something seems off, lock the system down"). Executes **instantly, no confirmation needed** — it's intentionally a defensive/reversible action, so no delay is required.

**What it does:** Disables all write actions (restart/stop/start container, backup) system-wide. Read-only diagnostics (container status, disk space, logs, etc.) stay fully available.

**When to use it:** If you suspect something abnormal is happening — e.g. messages you don't recognize, tools being called that you didn't ask for, or you just want to proactively "freeze" the system while you investigate.

**How to lift it:** Only via Protocol DAYBREAK (see below) — it **cannot** be lifted through chat, it requires direct access to the server. This is a deliberate design choice: if JARVIS has been compromised or misused, whatever is responsible can't undo the lockdown from within the same conversation.

### 🔌 BLACKOUT — Full Orchestrator Shutdown

**How to activate:** SSH into the server, then:
```bash
~/jarvis/protocol-blackout.sh
```
Not available via chat (makes sense — if you stop the orchestrator, there's no chat left to send a command through).

**What it does:** Completely stops the `jarvis-orchestrator` container. JARVIS stops responding to anything — no AI functionality at all. Core services (Jellyfin, Pi-hole, Samba, Vaultwarden, Portainer, Uptime Kuma) **remain unaffected** and keep running normally.

**When to use it:** More severe than SNOWFALL — if you want to shut JARVIS down entirely (e.g. debugging, suspicious behavior that lockdown alone doesn't stop, or you want to make code changes without it running at the same time).

**How to lift it:** Protocol DAYBREAK.

### 🌅 DAYBREAK — Restore Normal Operation

**How to activate:** SSH into the server, then:
```bash
~/jarvis/protocol-daybreak.sh
```
Deliberately **never** available via chat — recovery must always go through physical/SSH access, never through the same channel that might have caused the problem.

**What it does:**
1. Clears the lockdown flag if present (undoes SNOWFALL)
2. Checks whether the orchestrator is running; if not, brings it back up (undoes BLACKOUT)
3. Runs a health check and shows you the result

After DAYBREAK, the system is fully operational again — nothing else needs to be done manually, unless the health check shows a problem.

---

## Kill Switch

Separate from the emergency protocols — a more "surgical" tool.

```bash
~/jarvis/kill-switch.sh
```

**What it does:** Stops **only** Ollama and Open WebUI (the AI/chat layer). **Does not** touch jarvis-orchestrator or any core service.

**When to use it:** Milder than BLACKOUT — e.g. if you want to temporarily free up the RAM/CPU the AI layer consumes, without losing the orchestrator's ability to run backups or other scheduled tasks.

**Difference from BLACKOUT:** BLACKOUT cuts off the "brain" itself (the orchestrator) — no JARVIS functionality at all. The kill switch only cuts the chat interface and the local model — the orchestrator can still work "in the background" (e.g. a scheduled backup via cron, if you set that up in the future).

---

## Backup & Restore

### How to back up

**Through JARVIS (chat):**
```
You: activate protocol permafrost now
JARVIS: [asks for confirmation]
You: /confirm
JARVIS: [runs the backup, returns a detailed per-step result]
```
Takes 1-2 minutes. 5-minute cooldown before you can run it again.

**Manually (SSH), if you prefer:**
```bash
~/jarvis/backup.sh
```

**Note on backup location:** these two methods write to different (but both fully valid) locations. Running it manually from SSH uses `~/jarvis-backups/` by default. Running it through JARVIS uses `~/jarvis/jarvis-backups/` instead — this is intentional, driven by how the orchestrator's container filesystem is mounted. Both are correct; just check the matching folder for the run you're looking for.

### What the backup includes

- **JARVIS config**: policy.yaml, tools, scripts (without secrets)
- **Secrets**: the `.env` file (API keys) — kept as a separate file, permissions locked to 600
- **Logs**: the audit log (audit.db) and other logs
- **Docker volumes**: automatic discovery of all named volumes (Jellyfin, Pi-hole, Vaultwarden, Uptime Kuma, Portainer, Open WebUI). Ollama is **deliberately excluded** — it's just downloaded model weights, restored in minutes with `ollama pull`, not worth the space/time.
- Any new services you add in the future are picked up **automatically** — no script changes needed.

### Where it's stored

- **Locally**: see the note above on backup location — `~/jarvis-backups/` or `~/jarvis/jarvis-backups/` depending on how the backup was triggered
- **Retention**: keeps the last 7 backup runs locally, automatically deletes older ones
- **External USB** (if connected and mounted at `/mnt/backup_external`): automatically synced on every backup run. If not connected, this step is simply skipped without failing the run.

  **Practical note**: sync only happens for backups run *while the USB is plugged in*. If you unplug it between backups, those runs stay local-only and never make it to the USB. If you're relying on the USB copy as your actual disaster-recovery safety net (e.g. "if the server's disk dies"), keep it plugged in permanently, or manually check `/mnt/backup_external/jarvis-backups/` from time to time to confirm it's actually up to date with what's on the server.

### How to restore

Always via SSH, never through chat (restore is a destructive action on live data — deliberately not exposed to JARVIS yet).

**Test run, without touching anything real** (recommended first, especially if you haven't restored before):
```bash
~/jarvis/restore.sh ~/jarvis-backups/backup_DATE_TIME --test
```
Creates a throwaway sandbox (`~/jarvis-restore-test/`, Docker volumes prefixed `test_restore_`). Clean up afterward:
```bash
rm -rf ~/jarvis-restore-test
docker volume ls -q | grep test_restore_ | xargs -r docker volume rm
```

**Real restore:**
```bash
~/jarvis/restore.sh ~/jarvis-backups/backup_DATE_TIME
```
**Safety net built in**: if something already exists where the restore is about to write (e.g. you're restoring onto an already-working system), the script **first** saves the current content to `~/jarvis-restore-safety-backups/` before overwriting it. Nothing is ever lost silently.

---
## Sandbox — Running Code

JARVIS can execute Python code on your behalf, fully isolated from the rest of the server.

**Through JARVIS (chat):**

```
You: use the sandbox tool to calculate the average of [1,2,3,4,5] with numpy
JARVIS: [runs it, returns the result]
```

No confirmation needed — this is deliberate, and explained below.

### What it's for

Calculations, data processing, text manipulation, generating small files, quickly testing a snippet — anything where it's more reliable for JARVIS to actually *run* code than to reason about what it would output.

### How isolated is "isolated"

Every run happens in a brand-new, disposable container, destroyed immediately after (`docker run --rm`). On top of normal Docker isolation, the container runs under **gVisor** (`--runtime=runsc`) — a user-space kernel that adds a real isolation boundary between the executed code and the host's actual kernel, not just process/namespace separation.

Concretely, each run has:
- **No network access at all** (`--network=none`) — not even DNS resolution works
- **No access to the host filesystem** — no bind mounts, nothing from `~/media`, no Docker socket, nothing
- **Read-only root filesystem** — the only writable space is `/tmp` and `/work`, both RAM-backed (`tmpfs`), wiped the moment the container exits
- **Non-root user** (uid 10001, no shell, no home directory)
- **All Linux capabilities dropped**, no privilege escalation possible
- **Resource limits**: 768MB RAM, 1 CPU, max 64 processes, 20-second execution timeout

This was verified with a 15-point security test — confirmed that the sandbox genuinely cannot reach the network, cannot see host files (tested against a canary file placed outside any mount), cannot see the Docker socket, cannot escape the memory/process/time limits, and is genuinely running under gVisor (not silently falling back to a regular container).

### Why no confirmation is required

Every other tool that changes something on the system (restarting a container, running a backup) requires `/confirm`. The sandbox doesn't, and that's intentional: because the container has no network and no access to anything on the host, there's nothing *to* confirm — the blast radius of anything that runs inside is the container itself, which no longer exists a few seconds later.

### Current limitations (v1)

- **Python only** — no Node.js or Bash yet
- **Fixed set of preinstalled packages**: numpy, pandas, matplotlib, pillow, scipy, sympy, pydantic, requests, beautifulsoup4. No way to install anything else at request time — since the container has no network, `pip install` inside a run would fail anyway
- **`requests` is installed but non-functional** — the package is there, but network calls will fail with no network access. This is expected, not a bug
- Output (stdout/stderr) is treated as **untrusted data** by JARVIS — if executed code prints something that looks like an instruction, JARVIS is designed to ignore it rather than act on it

### Rebuilding the sandbox image

If you want to add a package to what's preinstalled, edit `~/jarvis-sandbox-build/Dockerfile` and rebuild:

```
cd ~/jarvis-sandbox-build
docker build -t jarvis-python-sandbox:v1 .
```

No orchestrator restart needed — the next sandbox run just picks up the new image automatically.

---


## Security — What's Protected

- **Vaultwarden is completely off-limits** to every tool, every operation, at every stage — it doesn't even appear on any allowed-targets list. JARVIS cannot touch it in any way.
- **Confirm-required actions** need an explicit `/confirm` — not natural language, so there's no risk of a misunderstood or accidental confirmation.
- **Emergency lockdown (SNOWFALL) cannot be undone through chat** — only DAYBREAK with SSH access.
- **Every action is logged** to an audit log (SQLite, `logs/audit.db`) — tier, status, duration, error codes, whether it was confirmed.
- **Every write action is independently verified** — e.g. `restart_container` doesn't just trust that the command "didn't error," it asks the Docker daemon again to confirm the state actually changed.
- **Secrets are never in plaintext logs or mixed into any other data** — the `.env` file always gets its own restrictive permissions (600), kept separate from everything else in a backup.

---

## Common Issues

**"There is no pending action to confirm, or it has expired"**
More than 2 minutes passed between the request and `/confirm`. Ask for the action again and reply faster.

**Restart/backup on the same container/action doesn't work again right away**
Cooldown in effect (120s for containers, 300s for backup). Wait, or start a new chat.

**Changes to `main.py` don't seem to take effect**
`main.py` is baked into the Docker image (`COPY` in the Dockerfile) — it needs a full rebuild + recreate, not just `docker restart`:
```bash
cd ~/jarvis/orchestrator
docker build --no-cache -t jarvis-orchestrator:latest .
docker stop jarvis-orchestrator && docker rm jarvis-orchestrator
docker run -d \
  --name jarvis-orchestrator \
  --network jarvis-ai-net \
  --ip 172.26.0.4 \
  -p 8001:8001 \
  -v /home/nickchronis2004/media:/mnt/media:ro \
  -v /home/nickchronis2004/jarvis:/app/jarvis:rw \
  -v /var/run/docker.sock:/var/run/docker.sock:rw \
  -e JARVIS_WRITE_TOOLS_ENABLED=true \
  -e TZ=Europe/Athens \
  --env-file /home/nickchronis2004/jarvis/orchestrator/.env \
  --restart unless-stopped \
  jarvis-orchestrator:latest
```
Changes inside `~/jarvis/tools/...` or to `backup.sh` **don't** need a rebuild — they're live-mounted, a plain `docker restart jarvis-orchestrator` is enough.

**Samba write permissions**
The `dperson/samba` image runs as an internal user (uid 100), not the host user. Fix: `chmod -R 777 ~/media` (not ideal long-term, but works).

---

## Roadmap

Priority order for next steps:

1. ~~Backups (deterministic, script-based)~~ ✅ Done
2. ~~Sandbox~~ ✅ Done — isolated gVisor container for running Python code through JARVIS
3. ~~Unified diagnostics (`diagnose_system`) and disk cleanup (`repair_system`)~~ ✅ Done
4. **`reconnect_network`** — detect and fix containers on the same Docker network that can't reach each other (planned repair_system addition, not yet built)
5. **Email/daily reports** — read-only, based on the audit log
6. **Database editing/rollback** — needs its own careful design (likely TOTP-level confirmation, same reasoning as the future reboot/shutdown tools)

**Parallel security/production-learning track** (added 2026-08-01), priority order:

1. **Docker Policy Broker + rootless Docker** — remove the orchestrator's direct read-write access to `docker.sock`, replace with a narrow intermediary that only allows pre-approved operations
2. **Trivy** — container image vulnerability scanning (CVEs)
3. **AIDE / File Integrity Monitoring** — alert if critical files change (`policy.yaml`, `backup.sh`, `.env`)
4. **Loki + Grafana** — centralized logging across all containers

Deferred until hardware upgrade or different network topology: Wazuh (SIEM/HIDS, RAM-heavy), Suricata/Zeek (needs a span/mirror port), VLAN segmentation (needs a managed switch). See `STATUS.md` for full reasoning and current state of every item on this list.

Other ideas under consideration: a Docker Policy Broker (to reduce direct docker.sock exposure — confirmed during sandbox work that jarvis-orchestrator still has read-write access to the host's Docker socket, meaning gVisor isolation protects executed code from escaping, but does not protect the host from the orchestrator's own tool-call layer; a rootless, separate Docker daemon for sandboxed workloads is the eventual fix), a full restore flow through JARVIS (after a serious safety redesign, since it's deliberately SSH-only for now).
