# JARVIS Home Server — User Guide

Your home server with a local-first AI assistant. This document is the user guide — what you can do, how to talk to JARVIS, what each emergency protocol does, and how to back up / restore. For technical internals (architecture, code, bugs found/fixed, open items), see `STATUS.md`.

---

## Table of Contents

1. [Quick Access](#quick-access)
2. [What's Running on the Server](#whats-running-on-the-server)
3. [Talking to JARVIS](#talking-to-jarvis)
4. [JARVIS Tools](#jarvis-tools)
5. [Host Diagnostics (os-helper)](#host-diagnostics-os-helper)
6. [Observability (Loki + Grafana)](#observability-loki--grafana)
7. [Emergency Protocols](#emergency-protocols)
8. [Kill Switch](#kill-switch)
9. [Backup & Restore](#backup--restore)
10. [Sandbox — Running Code](#sandbox--running-code)
11. [Security — What's Protected](#security--whats-protected)
12. [File Integrity Check](#file-integrity-check)
13. [Morning Digest](#morning-digest)
14. [Adding a New Tool — Checklist](#adding-a-new-tool--checklist)
15. [Common Issues](#common-issues)
16. [Roadmap](#roadmap)

---

## Quick Access

| What | Where |
|---|---|
| SSH | `ssh nickchronis2004@100.103.21.5` |
| JARVIS chat (Open WebUI) | `http://100.103.21.5:3000` |
| Grafana (logs) | `http://100.103.21.5:3002` |
| Vaultwarden (passwords) | `https://homeserver.tailec97a4.ts.net` |
| Portainer (Docker UI) | `https://100.103.21.5:9443` |
| Jellyfin (media) | `http://100.103.21.5:8096` |
| Pi-hole (DNS/ads) | `http://100.103.21.5:8080` |
| Uptime Kuma (monitoring) | `http://100.103.21.5:3001` |
| Files (Samba) | `\\100.103.21.5\media` |
| Tailscale hostname | `homeserver.tailec97a4.ts.net` |

Everything is only reachable through your Tailscale VPN — no ports are forwarded to the public internet. This remains true even where a host-level firewall (`ufw`) rule looks narrower than that on paper — see the note in [Security](#security--whats-protected).

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

**Observability**:
- **Loki + Promtail + Grafana** — centralized log viewing across every container, separate isolated stack, see [Observability](#observability-loki--grafana)

**Host-level diagnostics**:
- **os-helper** — a small systemd service (not a container) giving JARVIS visibility into the host OS itself (failed services, disk health, network state) — see [Host Diagnostics](#host-diagnostics-os-helper)

**Networking**: Tailscale VPN for remote access, a separate isolated Docker network (`jarvis-ai-net`) for the AI stack, plus three more dedicated internal networks for the Docker Policy Broker proxies.

---

## Talking to JARVIS

Open Open WebUI (`http://100.103.21.5:3000`) and just type normally, in English or Greek. JARVIS understands natural language and decides on its own which tool fits.

**Example prompts that work:**

- "What containers are running?"
- "How much disk space is left?"
- "Show me jellyfin's logs"
- "Search for a file called bunny"
- "Restart jellyfin"
- "Is everything OK with the system?"
- "Run a backup now" / "activate protocol permafrost"
- "Show me recent backups"
- "Any failed services on the host?"
- "Are my disks healthy?"
- "Check the host's network state"
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
| `list_recent_backups` | Lists recent backup runs — size, which Docker volumes each includes, whether it synced to the external USB drive, and whether any component failed |
| `summarize_inbox` | Reads your university mailbox (read-only, IMAP) and gives a summary — defaults to "since yesterday" |
| `get_failed_units` | Host-level (not container-level) systemd services currently in a failed state — see [Host Diagnostics](#host-diagnostics-os-helper) |
| `get_disk_health` | SMART health per physical drive, plus filesystem usage — see [Host Diagnostics](#host-diagnostics-os-helper) |
| `get_network_state` | Host network interfaces and default route — see [Host Diagnostics](#host-diagnostics-os-helper) |
| `get_listening_ports` | TCP ports currently listening on the host, with bind address and exposure (localhost-only / all-interfaces / specific-interface) — see [Host Diagnostics](#host-diagnostics-os-helper) |
| `get_memory_pressure` | Recent OOM-kill events and current memory pressure (PSI) — explains a container "just restarting" with no obvious cause — see [Host Diagnostics](#host-diagnostics-os-helper) |

### Confirm-required (need `/confirm`)

| Tool | What it does | Allowed targets |
|---|---|---|
| `restart_container` | Restarts a container | jellyfin, pihole, samba, uptime-kuma |
| `stop_container` | Stops a container | same list |
| `start_container` | Starts a stopped container | same list |
| `repair_system` | Runs a specific pre-approved repair: `clean_docker_disk` (**currently unavailable**, needs Docker permissions not yet opened, see `STATUS.md`) or `clean_build_cache` (all build cache, any age — always safe) | — |
| `protocol_permafrost` | Full system backup | — (see [Backup & Restore](#backup--restore)) |

**Vaultwarden is never a valid target** for any of these — it doesn't even appear on the allowed-targets list. JARVIS cannot touch it in any way.

Every container-based action has a **120-second cooldown** — if you just restarted something, you can't immediately do it again (protection against restart loops).

### Emergency (run instantly, no confirmation)

| Tool | What it does |
|---|---|
| `protocol_snowfall` | Activates lockdown — see below |

---

## Host Diagnostics (os-helper)

Everything above (except `os-helper`'s own three tools) sees the world through Docker — containers, volumes, images. **`os-helper`** is different: it's a small, separate systemd service running directly on the host (not in a container), giving JARVIS visibility into the underlying operating system itself.

**Why a separate host service, not another container?** Some of what it checks (systemd's own state) needs access that would otherwise mean giving a container much broader visibility into the host than is comfortable — so instead, a narrowly-scoped host service exposes just three fixed, read-only questions over a local connection, and nothing else.

**What you can ask:**
- "Any failed services on the host?" → `get_failed_units` — distinct from container health; this is about the host's own systemd services (e.g. if a background system service crashed)
- "Are my disks healthy?" → `get_disk_health` — SMART status per physical drive, not just free space (which `check_disk_space` already covers). Disk health data refreshes every 5 minutes rather than being queried live — the response tells you how old the data is
- "What's the network state?" → `get_network_state` — host network interfaces and routing, filtered to just the physically meaningful ones (Docker's internal per-container networking is deliberately excluded — that's a lot of noise you don't usually need)
- "What's listening on the network?" / "Is anything exposed it shouldn't be?" → `get_listening_ports` — every TCP port currently listening, tagged as localhost-only, all-interfaces, or bound to a specific interface. Process-name attribution isn't included (the daemon runs unprivileged and can't resolve other users' process names) — cross-reference against `docker ps` or `diagnose_system` if a port's owner isn't obvious
- "Did anything get OOM-killed recently?" / "Why did X restart?" → `get_memory_pressure` — recent kernel OOM-kill events (last hour) plus current memory pressure (PSI). Useful specifically when a container shows up as "restarted" with no cause visible in its own logs — an OOM kill only shows up in the host's kernel log, not in Docker's own state

**Known limitation:** the external USB backup drive doesn't support SMART health checks at all — the USB enclosure's chipset doesn't pass that data through, confirmed on the hardware itself. `get_disk_health` reports this cleanly as an error for that drive rather than pretending it's fine.

This is read-only today — it can't restart anything or change host configuration. A future addition (not yet built) may let JARVIS restart a small, explicitly-allowed set of host-level services, following the same confirm-required pattern as container restarts.

---

## Observability (Loki + Grafana)

A separate stack (Loki + Promtail + Grafana) collects logs from every container into one place, so you don't have to check each container's logs individually.

**Access:** `http://100.103.21.5:3002` (log in, then Dashboards → JARVIS → "JARVIS — Log Overview")

What you get: live-tailed logs from every container, a log-volume-over-time chart per container, and a filtered view of error-looking lines. Log history is kept for 7 days.

This is a separate, independent stack from JARVIS itself — you view it directly in a browser, JARVIS doesn't currently query it through chat (though `get_container_logs` gives you a chat-accessible way to check a single container's recent logs, which covers most day-to-day needs without going to Grafana).

---

## Emergency Protocols

Three levels of response if something goes wrong, from mildest to most drastic.

### ❄️ SNOWFALL — Soft Lockdown

**How to activate:** From chat, just tell JARVIS (e.g. "activate protocol snowfall" or "something seems off, lock the system down"). Executes **instantly, no confirmation needed** — it's intentionally a defensive/reversible action, so no delay is required.

**What it does:** Disables all write actions (restart/stop/start container, backup) system-wide. Read-only diagnostics (container status, disk space, logs, host diagnostics, etc.) stay fully available.

**When to use it:** If you suspect something abnormal is happening — e.g. messages you don't recognize, tools being called that you didn't ask for, or you just want to proactively "freeze" the system while you investigate.

**How to lift it:** Only via Protocol DAYBREAK (see below) — it **cannot** be lifted through chat, it requires direct access to the server. This is a deliberate design choice: if JARVIS has been compromised or misused, whatever is responsible can't undo the lockdown from within the same conversation.

### 🔌 BLACKOUT — Full Orchestrator Shutdown

**How to activate:** SSH into the server, then:
```bash
~/jarvis/protocol-blackout.sh
```
Not available via chat (makes sense — if you stop the orchestrator, there's no chat left to send a command through).

**What it does:** Completely stops the `jarvis-orchestrator` container. JARVIS stops responding to anything — no AI functionality at all. Core services (Jellyfin, Pi-hole, Samba, Vaultwarden, Portainer, Uptime Kuma) **remain unaffected** and keep running normally. `os-helper` (the host service) and the Loki/Grafana stack also keep running — they don't depend on the orchestrator at all.

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

### Checking recent backups

Ask JARVIS "show me recent backups" (`list_recent_backups`) — gives you, per run: size, which Docker volumes it includes, whether it synced to the external USB, and whether any step (config, secrets, logs, or a specific volume) failed. This is the fastest way to spot a bad backup without SSH-ing in and reading `backup.log` by hand.

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
- **Fixed set of preinstalled packages**: numpy, pandas, matplotlib, pillow, scipy, sympy, pydantic, openpyxl, python-docx, pypdf. No way to install anything else at request time — since the container has no network, `pip install` inside a run would fail anyway
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

- **No direct Docker socket access.** The orchestrator has no mount of `/var/run/docker.sock`. Instead it talks to three separate, narrowly-scoped `docker-socket-proxy` instances — a **read** proxy (status/logs/disk usage, no writes possible), a **lifecycle** proxy (only start/stop/restart, no read access), and a **maintenance** proxy (for the sandbox and backups, which need to create containers). Each tool only gets the proxy it actually needs.
- **`os-helper` (host diagnostics) is separately isolated.** It's read-only, runs as a dedicated unprivileged user with no escalation path of any kind (`NoNewPrivileges=true` — this holds even against `sudo`, so there's genuinely no way for that service to gain elevated access even if something in it were compromised). The one thing it reports that *does* need elevated access — disk SMART health — is collected by a completely separate, privileged process that runs briefly, writes one file, and exits; the main service only ever reads that file, never touches the disk directly.
- **Vaultwarden is completely off-limits** to every tool, every operation, at every stage — it doesn't even appear on any allowed-targets list. JARVIS cannot touch it in any way.
- **Confirm-required actions** need an explicit `/confirm` — not natural language, so there's no risk of a misunderstood or accidental confirmation.
- **Emergency lockdown (SNOWFALL) cannot be undone through chat** — only DAYBREAK with SSH access.
- **Every action is logged** to an audit log (SQLite, `logs/audit.db`) — tier, status, duration, error codes, whether it was confirmed.
- **Every write action is independently verified** — e.g. `restart_container` doesn't just trust that the command "didn't error," it asks the Docker daemon again to confirm the state actually changed.
- **Secrets are never in plaintext logs or mixed into any other data** — the `.env` file always gets its own restrictive permissions (600), kept separate from everything else in a backup.
- **Host firewall (`ufw`) is active**, with SSH and the `os-helper` port scoped to only what needs them. Worth knowing: Tailscale traffic (i.e. anything from your own devices on your tailnet) currently bypasses this `ufw` filtering at the OS level — this is a Tailscale networking detail, not a gap in `ufw` itself. In practice this doesn't widen your actual exposure: Tailscale membership (only your own devices) *is* and always has been the real access boundary for everything on this server, `ufw` or not — see `STATUS.md` for the full technical explanation if you want it.

---

## File Integrity Check

A standalone SSH-only script — **not** a JARVIS tool, and deliberately not wired into chat. Checks whether `.env` or `policy.yaml` have changed since the last time you confirmed they were in a trusted state.

```bash
cd ~/jarvis
python3 integrity_check.py
```

**Why not a JARVIS tool:** the orchestrator itself is exactly the kind of component this check exists to watch — a tool that could silently accept a changed baseline defeats the point. This only runs by hand (or via the morning digest, see below), never through the orchestrator.

**How it works:**
- First run creates a baseline (SHA-256 hash + mtime of each watched file), stored at `~/jarvis/.integrity-baseline.json` (permissions locked to 600).
- Every run after that compares current state against the baseline. If everything matches, it says so and exits cleanly.
- If something changed, it shows you exactly what (old hash vs new hash, old mtime vs new mtime) and **does not update the baseline** — nothing is silently accepted.
- If the change was you (e.g. you rotated the API key), review it, then run:
  ```bash
  python3 integrity_check.py --accept
  ```
  This is the only way the baseline changes after the first run — an explicit, deliberate step, same spirit as JARVIS's own `/confirm` flow, just at the SSH layer.

Currently watches `~/jarvis/orchestrator/.env` and `~/jarvis/policy.yaml`. Add more files by editing the `WATCHED_FILES` list at the top of `integrity_check.py`.

---

## Morning Digest

A daily health summary, written automatically — no need to remember to ask JARVIS how things are doing.

**Where to find it:** `~/jarvis/morning-digest/digest_latest.md` (always the most recent), with a dated copy kept in `~/jarvis/morning-digest/archive/` for history.

**What's in it:**
- **Backups** — most recent run across both backup locations, its OK/WARN/FAIL status, and a warning if it's been longer than ~30 hours since the last one
- **Failed systemd units** (host-level, via `os-helper`)
- **Disk health** — SMART status per drive, filesystem usage with warnings at 75%/90% full
- **File integrity** — runs `integrity_check.py` and reports clean/changed

**How it runs:** a systemd timer (`jarvis-morning-digest.timer`), daily at 07:00, via a oneshot service running as your own user (not root — the script only needs read access to files you already own, plus a local HTTP call to `os-helper`).

```bash
systemctl list-timers jarvis-morning-digest.timer --no-pager
```

**Runs standalone, not through JARVIS or Docker.** Same reasoning as the integrity check: if the orchestrator container is down for any reason, the digest should still be able to tell you that, rather than failing silently along with it. Each section degrades independently — if `os-helper` is unreachable, that section shows a clear error while backups and integrity check (which don't depend on it) still report normally.

To run it manually instead of waiting for the timer:
```bash
python3 ~/jarvis/morning_digest.py
```

---

## Adding a New Tool — Checklist

A few mistakes have shown up more than once while adding new tools, all from *assuming* something about the environment instead of confirming it first. Run through this before writing a new tool, and you'll skip the debugging loop these caused:

1. **Manifest format.** `privilege_tier` (not `tier`), and `parameters` must be a **list** of `{name, type, description, required}` objects — even when there are no parameters at all, it's `parameters: []`, never `parameters: {}`. Copy an existing working manifest (`tools/restart_container/manifest.yaml`) as your starting template rather than writing one from scratch.
2. **Don't assume the container's directory layout — check it.** `tools/` and `lib/` are sibling directories under `/app/jarvis/` inside the orchestrator container (two separate mounts), not nested inside each other. If your tool needs to import something from `lib/`, confirm the real path first:
   ```bash
   docker exec jarvis-orchestrator ls -la /app/jarvis/
   ```
3. **Don't assume `~` means what you think inside the container.** The orchestrator process runs as root inside its container, so `~` resolves to `/root`, not to your own SSH home directory — even though a standalone SSH test of the same script (`~` = `/home/nickchronis2004`) would look like it works. Use an explicit, known container path instead (e.g. `/app/jarvis/jarvis-backups`), or read it from an environment variable with that as the fallback.
4. **`docker restart` is not always enough.** A tool's own `script.py`/`manifest.yaml` changes only need `docker restart jarvis-orchestrator` (they're live-mounted `:ro`). But anything that changes the **compose file itself** — a new env var, `extra_hosts`, a new volume mount — needs a full recreate:
   ```bash
   docker compose -f docker-compose.proxies.yml up -d --force-recreate jarvis-orchestrator
   ```
5. **Test the tool standalone before testing it through chat.** Reproduce exactly what the orchestrator does — arguments are passed as `TOOL_ARG_<name>` environment variables, not command-line args:
   ```bash
   docker exec -e TOOL_ARG_confirmed=false jarvis-orchestrator python3 /app/jarvis/tools/<name>/script.py
   ```
   If this doesn't return clean JSON with exit code 0, chat won't work either — and this is much faster to iterate on than going through Open WebUI each time.
6. **If something fails in chat with a vague error, check `docker logs jarvis-orchestrator --tail 50` first**, not the chat transcript — that's where the real Python traceback is. The chat response is JARVIS's natural-language gloss on the failure, not the failure itself.

---

## Common Issues

**"There is no pending action to confirm, or it has expired"**
Usually: more than 2 minutes passed between the request and `/confirm` — ask again and reply faster.

If this happens *immediately* after JARVIS asked you to type `/confirm` (not a timing issue), it likely means JARVIS described the action in plain language without actually calling the tool first — so no pending confirmation was ever created. This was seen and fixed once already (2026-08-01, system prompt update); if it resurfaces, check the audit log (`logs/audit.db`, `tool_calls` table) to confirm whether the tool was actually called with `confirmed=0` before you typed `/confirm`.

**Restart/backup on the same container/action doesn't work again right away**
Cooldown in effect (120s for containers, 300s for backup). Wait, or start a new chat.

**Changes to `main.py` don't seem to take effect**
`main.py` is baked into the Docker image (`COPY` in the Dockerfile) — it needs a full rebuild + recreate, not just `docker restart`. The orchestrator no longer mounts `/var/run/docker.sock` directly — it reaches Docker through three dedicated proxies instead (see [Security](#security--whats-protected)). The easiest way to recreate it correctly is via the compose file, which already has the right mounts and env vars:
```bash
cd ~/jarvis
docker build --no-cache -t jarvis-orchestrator:latest -f orchestrator/Dockerfile orchestrator/
docker compose -f docker-compose.proxies.yml up -d --force-recreate jarvis-orchestrator
```
Changes inside `~/jarvis/tools/...`, `~/jarvis/lib/...`, or to `backup.sh` **don't** need a rebuild — they're live-mounted (`:ro`), a plain `docker restart jarvis-orchestrator` is enough. See the [checklist above](#adding-a-new-tool--checklist) for when a full recreate (not just a rebuild) is separately needed.

**Note**: `docker compose up -d` alone does not always pick up changed environment variables or compose-level directives (`extra_hosts`, new mounts) on an already-running container — use `--force-recreate`, or to be certain, `stop` + `rm` + `up -d` explicitly.

**Samba write permissions**
The `dperson/samba` image runs as an internal user (uid 100), not the host user. Fix: `chmod -R 777 ~/media` (not ideal long-term, but works).

**Backup step `jarvis-config: FAIL`, or a backup directory that's unexpectedly huge (GBs instead of tens of MB)**
Fixed 2026-08-02 — was a self-referential tar bug: `backup_config()` archived all of `~/jarvis`, which includes `jarvis-backups/` itself, so it kept trying to include its own still-being-written output file, growing without bound on every failed retry (one instance reached 35GB before being caught). If you ever see this again on an older/restored copy of `backup.sh`, make sure it excludes the backup output directory by name. If a giant leftover backup directory shows up, it's safe to delete (`sudo rm -rf`, since files are owned by root when created via JARVIS) — it's not real data, just the runaway archive.

**`get_disk_health` reports one drive as unhealthy/errored that you know is fine**
If it's the external USB backup drive specifically: known limitation, not a bug — see [Host Diagnostics](#host-diagnostics-os-helper).

---

## Roadmap

Priority order for next steps:

1. ~~Backups (deterministic, script-based)~~ ✅ Done
2. ~~Sandbox~~ ✅ Done
3. ~~Unified diagnostics (`diagnose_system`) and disk cleanup (`repair_system`)~~ ✅ Done
4. ~~Docker Policy Broker (no more direct docker.sock access)~~ ✅ Done
5. ~~Loki + Grafana~~ ✅ Done
6. ~~`list_recent_backups`~~ ✅ Done
7. ~~`os-helper` (host OS diagnostics)~~ ✅ Done
8. ~~`get_listening_ports` / `get_memory_pressure`~~ ✅ Done
9. ~~`.env`/`policy.yaml` integrity check~~ ✅ Done
10. ~~Morning health digest~~ ✅ Done
11. **`os-helper` write actions** — a small, explicitly-allowed set of `systemctl restart <service>` calls, confirm-required, same pattern as container restarts
12. **`reconnect_network`** — detect and fix containers on the same Docker network that can't reach each other

See `STATUS.md` for the full technical history, every bug found and fixed along the way, and the reasoning behind decisions not listed here.
