# JARVIS Project Status

Last updated: 2026-08-03

Purpose of this file: a quick snapshot of "what's built, what's left, what's been decided but not implemented" — without needing to dig through old chats. Updated at the end of every session alongside the README.

---

## Completed

| Feature | What it does | Date |
|---|---|---|
| **Core orchestrator** | FastAPI service, tool discovery from manifests, confirm-flow, audit logging (SQLite) | — |
| **Emergency protocols** (SNOWFALL / BLACKOUT / DAYBREAK) | SNOWFALL: instant soft lockdown via chat. BLACKOUT: hard stop of the orchestrator, SSH only. DAYBREAK: recovery, SSH only, never via chat | — |
| **Kill switch** | Stops only Ollama + Open WebUI, not the orchestrator | — |
| **Backups** (`protocol_permafrost`) | `backup.sh`/`restore.sh`, auto-discovery of Docker volumes, 7-run retention, external USB sync, `--test` sandbox mode | — |
| **Sandbox** (gVisor) | Python code execution, fully isolated | — |
| **`diagnose_system`** | Read-only, full picture: container status/health/restarts, log scan, disk usage | 2026-08-01 |
| **`repair_system`** | `clean_docker_disk` (non-functional, see known limitations) + `clean_build_cache` (functional) | 2026-08-01 |
| **Docker Policy Broker** | 3 dedicated proxies (read/lifecycle/maintenance), no direct `docker.sock` mount, mount split (`:ro` everywhere except `logs/`, `jarvis-backups/`). Routing complete across 7/7 tools. Negative tests passed | 2026-08-01/02 |
| **`summarize_inbox`** | Read-only IMAP, CSD UoC mailbox, explicit readonly mode | 2026-08-02 |
| **Loki + Grafana** | Centralized log aggregation, isolated `observability-net`, Grafana on port 3002 | 2026-08-03 |
| **`list_recent_backups`** | Read-only listing of backup runs — size, volumes, USB sync, per-component OK/FAIL/WARN | 2026-08-03 |
| **`os-helper`** | Host-side systemd daemon, 3 read-only endpoints (failed units, disk health, network state) | 2026-08-03 |
| **`ufw`** | Enabled on the host, with SSH+os-helper rules | 2026-08-03 |
| **`get_listening_ports` / `get_memory_pressure`** | 2 new read-only `os-helper` endpoints — listening TCP ports (exposure classification), OOM events + PSI memory pressure | 2026-08-03 |
| **`integrity_check.py`** | Standalone SSH-only script, SHA-256 baseline for `.env`/`policy.yaml`, explicit `--accept` flow — not a JARVIS tool | 2026-08-03 |
| **Morning digest** | `morning_digest.py` + `jarvis-morning-digest.timer` (07:00 daily), merges backups+failed_units+disk_health+integrity into one markdown file | 2026-08-03 |

---

## 🔧 Docker Policy Broker — technical details

### Architecture

3 proxy instances (`docker-read-proxy`, `docker-lifecycle-proxy`, `docker-maintenance-proxy`), `tecnativa/docker-socket-proxy`, digest-pinned, each on its own internal network:

- **read-proxy**: `CONTAINERS=1, SYSTEM=1, VOLUMES=1, POST=0` — read-only
- **lifecycle-proxy**: `POST=1, CONTAINERS=0, ALLOW_START/STOP/RESTARTS=1` — only 3 lifecycle endpoints
- **maintenance-proxy**: `POST=1, CONTAINERS=1, BUILD=1, SYSTEM=0, IMAGES=0, NETWORKS=0`

Mount split on the orchestrator: `policy.yaml`, `tools/`, `lib/`, scripts all `:ro`. Only `logs/` and `jarvis-backups/` are `:rw`. Port 8001 bound to `127.0.0.1` only.

`lib/docker_env.py`: `docker_env(proxy)` → env dict with the correct `DOCKER_HOST`. Import pattern: `sys.path.insert(0, "/app/jarvis/lib")` (flat import, `lib/` is not a package).

### Routing — 7/7 tools

`restart_container`, `stop_container`, `start_container`, `check_docker_status`, `diagnose_system`, `repair_system`, `sandbox` — all routed. `protocol_permafrost` needed **dual-proxy** routing (`docker_read()`/`docker_maintenance()` wrappers in `backup.sh`, no-op fallback to the local socket for SSH/manual usage).

### Bugs found + fixed

- **`start_container`**: one of the two subprocess calls forgot `env=docker_env(...)`. Lesson: after every multi-call routing change, `grep -c 'subprocess.run'` against `grep -c 'env=docker_env'`.
- **`clean_build_cache`**: `docker builder prune` is a buildx CLI command, not a daemon API call — doesn't work through the proxy (buildx context state doesn't exist inside the orchestrator). Fix: direct `POST /build/prune` via `urllib`, already covered by `BUILD=1, POST=1`.
- **`VOLUMES=1` duplicate on the read proxy**: the first attempt added `VOLUMES=1` but a forgotten `VOLUMES=0` already existed further down the same compose block — in YAML list-style environment entries, the last one wins.
- **🔴 Self-referential tar in `backup_config()`** (serious): the tar of `$JARVIS_HOME` didn't exclude the `jarvis-backups/` directory (itself inside `$JARVIS_HOME`), so it tried to include its own output file — unbounded growth, 7.6GB → 23GB → 35GB across consecutive failed runs, disk usage reached 129GB. Fix: `--exclude` the backup output directory. Affected the SSH-manual path too, not just JARVIS-triggered runs.
- **Confirmation-flow bug (system prompt)**: JARVIS would reply "type /confirm" in natural language without calling the tool with `confirmed=false` first — no pending action was ever created. Fix: explicit system prompt instruction to always call the tool first.

### Known limitations (intentional, not bugs)

- **Lifecycle proxy does no per-container filtering** — action-level only. Vaultwarden protection lives exclusively at the Python `policy.yaml` layer.
- **Maintenance proxy is the widest** (`POST=1, CONTAINERS=1`) — sandbox/permafrost genuinely need container-create access.
- **`clean_docker_disk` non-functional** — needs `NETWORKS`/`IMAGES`, which we deliberately haven't opened up.

### Backup regression (accepted)

After the mount split, backups no longer include `README.md`, `STATUS.md`, `docker-compose.proxies.yml`, `.git/` — these already live in the GitHub repo.

### Future — custom broker (explicitly out of scope)

Evaluated, consciously decided against for now: a custom FastAPI broker (Docker SDK) with sanitized endpoints, separate fixed-function agents (maintenance/permafrost/sandbox), a lifecycle broker with real per-container policy. Will be re-evaluated if the threat model changes (e.g. exposure beyond Tailscale-only, more users).

---

## 📧 `summarize_inbox` — technical details (2026-08-02)

Read-only IMAP (`mailhost.csd.uoc.gr:993`), explicit `readonly=True` in `select()` — a protocol-level guarantee, not just "we didn't write write-code". Secrets in `orchestrator/.env` (**not** `~/jarvis/.env` — that doesn't exist). Default `mode=since` (yesterday) — `mode=unseen` was tried first, too noisy.

**Bugs:** manifest schema mismatch (first occurrence of this pattern bug, see the general section below) · `.env` path confusion (`orchestrator/.env`, not root) · `docker restart` doesn't reload `.env` (needs `--force-recreate`) · directory typo (`summirize_inbox`) · HTML-only emails returned raw markup (fix: strip tags via stdlib `html.parser`).

**Not implemented (deliberately):** cron-triggered daily run + Open WebUI message-posting — stays on-demand only, simpler.

---

## 📊 Loki + Grafana — technical details (2026-08-03)

Loki + Promtail (host-level, `docker_sd_configs` auto-discovery, **not** a driver plugin — zero changes to existing services) + Grafana, on their own isolated `observability-net`. Grafana on port **3002** (3000 = open-webui, 3001 = uptime-kuma, both already taken). 7-day retention.

**Bug:** a custom timestamp-extraction regex in the Promtail pipeline caused `"timestamp too new"` errors in Loki — fix: removed entirely, trusting the native Docker envelope timestamp instead of re-guessing it from the log text.

Separate, independent compose project (`~/jarvis-observability/`) — doesn't touch anything in `docker-compose.proxies.yml`. JARVIS doesn't query Loki via chat today (deemed unnecessary — the existing `get_container_logs` covers the everyday use case).

---

## 📦 `list_recent_backups` — technical details (2026-08-03)

Read-only, no proxy involved (pure filesystem read). Reads backup directories + `backup.log`.

**Bugs:**
- **Log-block parsing**: the parser expected a `"Backup completed"` line to close each run block — not always present in that exact form in the real log. Fix: the block now closes at the next header or EOF, not on specific footer text.
- **Many-to-one timestamp matching** (more serious): naive "nearest absolute distance" matching let one directory run "steal" the log summary of a **neighboring, different** run (a dry-run block ended up chronologically closer to the wrong directory than to its own correct summary, because the real run took over a minute to complete). Fix: forward-only, one-to-one matching — a log summary must be equal to or later than the directory's start time, and each log entry is consumed exactly once.
- **`~` resolves to `/root`**: see the general bugs section below.

---

## 🖥️ `os-helper` — technical details (2026-08-03)

### Purpose & architecture

The first host-OS-level tooling — until now all tools only saw the world through Docker. A separate systemd service on the host (`os-helper.service`, Python stdlib `http.server`, port 8787), **not** a container — `systemctl --failed` needs access to the host's systemd D-Bus socket, which from inside a container would mean `--pid=host` or similar, breaking the isolation model. The orchestrator talks to it via `host.docker.internal:8787` (`extra_hosts` in the compose file).

### Privilege separation for SMART data

The initial plan (`sudo smartctl` inside `os-helper.service`) failed — `NoNewPrivileges=true` disables **both** sudo **and** file capabilities (`setcap`) at `execve()` time, not just setuid binaries. Final solution, full privilege separation:

```
jarvis-smart-snapshot.timer (every 5 minutes)
        ↓
jarvis-smart-snapshot.service [root, oneshot, hardcoded device list, no network exposure]
        ↓ atomic write
/run/jarvis-os-helper/smart-health.json
        ↑ read-only
os-helper.service [jarvis-oshelper user, NoNewPrivileges=true]
```

`os-helper.service` never calls `smartctl` directly. `get_disk_health` reports `age_seconds`/`stale`.

### Bugs found + fixed

1. **Manifest schema mismatch** (recurred — already logged from the `summarize_inbox` session): `tier` → should have been `privilege_tier`, `parameters: {}` → should have been `parameters: []` (a list, never a dict). 4 tools affected (the 3 os-helper ones + `list_recent_backups`). Now documented in the README as a permanent checklist item.
2. **`sys.path.insert` wrong directory depth**: `lib/` is a **sibling** of `tools/` under `/app/jarvis/` (two separate compose mounts), not nested inside it. Needed `../../lib`, not `../lib`.
3. **`~` resolves to `/root`**: the orchestrator process runs as root inside the container. Standalone SSH tests (`~` = `/home/nickchronis2004`) showed it working, production didn't. Fix: hardcoded `/app/jarvis/jarvis-backups` instead of `os.path.expanduser("~/...")`.
4. **`docker restart` isn't enough for compose-level changes**: the `extra_hosts` directive required a full `--force-recreate` — same lesson as the `.env` finding from the `summarize_inbox` session, now confirmed to hold generally, not just for env vars.

**Observation:** bugs #2 and #3 are both variants of the same underlying mistake — assuming what the filesystem/environment looks like inside the container without confirming it first. The new "Adding a New Tool" checklist in the README exists explicitly for this reason.

### Known limitation (hardware, not a bug)

The external USB backup drive (`/dev/sdc`) doesn't support SMART passthrough through its specific USB-bridge chipset (Genesys Logic, VID:PID `0x05e3:0x0749`) — confirmed with `smartctl --scan-open` (doesn't find the device under any `-d` type, a hardware/firmware limitation, not fixable in software). Two additional `/dev/sda`/`/dev/sdb` slots (USB card reader, usually empty) are correctly recognized as "no medium present".

### Deployment

Host-side at `/opt/jarvis/os-helper/`, dedicated unprivileged user `jarvis-oshelper` for the main daemon, root only for the snapshot collector. JARVIS-side tools follow the standard `~/jarvis/tools/<name>/` pattern, new shared `~/jarvis/lib/os_helper_client.py`. End-to-end tested via chat.

---

## 🔥 `ufw` — enabling it + a Tailscale finding (2026-08-03)

### What happened

`ufw` was installed but **inactive** on the host — the rule for port 8787 (`172.16.0.0/12`) existed in the config but wasn't being enforced. Enabled carefully: first `sudo ufw allow ssh` (confirmed SSH port 22 first), Termux on the phone tested as a second, independent access channel before `enable`, then `sudo ufw enable`. No loss of access.

### Finding: the ufw rule doesn't block tailnet traffic

A verification test (curl from the phone via Termux, a different Tailscale device) showed port 8787 **remained accessible** despite the `ufw` rule. Cause: Tailscale `ShieldsUp: false` (confirmed via `tailscale debug prefs`) — Tailscale has its own netfilter/routing layer (`NetfilterMode: 2`) that handles incoming tailnet traffic **independently** of OS-level `ufw`, before that traffic even reaches the filtering chain that would see "normal" external traffic.

### Decision: accepted as-is

The real access-control boundary for `os-helper` (and for every service on this host) is, and remains, Tailscale tailnet membership itself — only our 3 devices (homeserver, desktop, phone) can reach it, same model as every other service in the stack. The `ufw` rule stays as a second layer of defense, and would take effect if the Tailscale configuration ever changes.

**Alternatives evaluated and rejected:**
- `tailscale up --shields-up` — would fix the issue, but is a global policy change (blocks ALL incoming tailnet traffic to this host), a bigger change than needed.
- Tailscale ACLs (admin console) — more correct/targeted, needs web dashboard access, a separate future task if stricter per-service policy is ever needed.

---

## 🔌📊🔒 `get_listening_ports` / `get_memory_pressure` / integrity check / morning digest — technical details (2026-08-03)

### `get_listening_ports` + `get_memory_pressure`

Same pattern as the existing 3 `os-helper` endpoints — added to the same `os_helper.py`, same `ENDPOINTS` dict, nothing else changed in the daemon.

- **`get_listening_ports`**: `ss -H -tln` (no `-p` — process-name attribution needs elevated privileges the daemon deliberately doesn't have, `NoNewPrivileges=true`). Each port is categorized `localhost-only` / `all-interfaces` / `specific-interface` based on bind address. IPv4/IPv6 parsing handles both formats (`0.0.0.0:port`, `[::]:port`).
- **`get_memory_pressure`**: two independent signals — `journalctl -k --since "1 hour ago"` filtered for "killed process"/"out of memory" (OOM events), and `/proc/pressure/memory` (PSI) for current pressure. PSI reports `not available` if unsupported by the kernel config, instead of crashing.

Tested on the real server: 32 listening ports found correctly (SSH, Pi-hole, Samba, Tailscale HTTPS on port 443 correctly tagged `specific-interface`, Open WebUI, Grafana, orchestrator, Jellyfin, os-helper, Portainer, Ollama), zero OOM events, zero memory pressure. No bugs found on deployment — clean on the first try.

### `integrity_check.py`

Standalone, **not** a JARVIS tool — runs only over SSH, never through the orchestrator (deliberate: the orchestrator is exactly the component this script exists to keep watch over). SHA-256 hash + mtime for `~/jarvis/orchestrator/.env` and `~/jarvis/policy.yaml`, baseline stored in `~/jarvis/.integrity-baseline.json` (permissions 600).

**Design decision:** never auto-accepts a change. First run creates the baseline. Every subsequent run compares — if something changed, it shows exactly what (old/new hash, old/new mtime) and writes **nothing**. Only an explicit `--accept` run updates the baseline — same logic as JARVIS's own `/confirm` flow, carried over to the SSH layer. Also supports `--json` mode (for the morning digest, see below).

Tested locally across 7 scenarios before deploying (baseline creation, clean check, hash mismatch detection, `--accept` flow, missing-file detection, json output) — no bugs found in the real deployment.

### Morning digest

`morning_digest.py` — standalone, same reasoning as the integrity check: doesn't go through the orchestrator or Docker, so it keeps working even if the orchestrator is down. Calls:
- A standalone reimplementation of the `list_recent_backups` logic (forward-only matching etc., same code) — runs against **both** backup dirs (`~/jarvis-backups/` and `~/jarvis/jarvis-backups/`) and merges the results, showing the most recent run between the two, with a warning if more than 30 hours have passed
- `os-helper`'s `/get_failed_units` and `/get_disk_health` directly via `localhost:8787` (not via `host.docker.internal` — this script runs on the host, not in a container)
- `integrity_check.py --json` as a subprocess

Writes markdown to `~/jarvis/morning-digest/digest_latest.md` (always overwritten) + `archive/digest_<date>.md`. Each section is isolated — if `os-helper` is down, only the two related sections show an error, while backups+integrity continue normally (confirmed with a local test, mock server up/down).

**Systemd:** `jarvis-morning-digest.service` (oneshot, runs as `nickchronis2004`, **not** root — needs no privileges) + `jarvis-morning-digest.timer` (`OnCalendar=*-*-* 07:00:00`, `Persistent=true` for catch-up if the machine was off at 07:00).

**Real-world finding from the first actual run:** re-confirmed two already-known open items — the `secrets(.env):FAIL` in `backup_2026-08-02_0047`, and a possible sign of the already-logged race condition (two runs 1 minute apart, one with 0 bytes). Not new findings, but they confirm the digest's value — you see them without having to ask.

---

## General bug pattern today (2026-08-03) — worth logging separately

Three separate bugs today (manifest format, `sys.path` depth, `~` expansion) were all variants of the **same** underlying mistake: an incorrect assumption about what the filesystem/environment looks like inside the orchestrator container, made without confirming it first. The manifest-format bug had in fact already been logged from the `summarize_inbox` session and recurred.

**Action:** added a permanent "Adding a New Tool — Checklist" section to README.md, with explicit confirmation steps (directory layout, manifest format, `~` resolution, when `--force-recreate` is needed) to run through before writing new code.

---

## Known, logged open items

Not bugs — logged explicitly so they don't get rediscovered from scratch:

- **`secrets(.env): FAIL` on backup run `backup_2026-08-02_0047`** — `.env` wasn't found at the expected path at the time of that run (spotted via the new `list_recent_backups`). If it recurs, the most recent backup won't have a copy of the secrets. Not investigated further.
- **Possible race condition on concurrent `protocol_permafrost` runs** — two backup runs started very close together in time (`22:03`/`22:04` on August 1st), and one stepped on the other's files (`tar: file changed as we read it`, visible in `backup.log`). Possibly a missing lock/mutex. Not investigated.
- **Confirming whether `OPENAI_API_KEY` was revoked** — open since 2026-08-01 (it appeared in plaintext in chat via `docker inspect ... Config.Env` during debugging). Still not checked.
- **`ufw`/Tailscale interaction** — see the section above, explicitly documented as accepted, not a bug.

---

## Next up (priority order)

1. **`os-helper` write set** — allowlisted `systemctl restart <unit>`, confirm-required. A natural extension on top of the already-built read-only daemon.
2. **`reconnect_network`** — third repair_type, needs a proxy decision first (no proxy currently has `NETWORKS=1`).
3. **Database editing/rollback** — needs its own careful design, TOTP-level confirmation. Explicitly evaluated as **high risk / low reward** at the current stage — stays low priority deliberately, not just deferred.

### Small `os-helper` extensions (logged ideas, 2026-08-03)

`get_listening_ports` and `get_memory_pressure` ✅ completed (2026-08-03, see technical section above). Remaining ideas, same pattern:

- **`get_recent_boot_history`** (`journalctl --list-boots`) — when reboots/crashes happened.
- **`get_journal_errors`** (`journalctl -p err -b`) — host-level errors, complements Loki/Grafana (which only sees container logs).

**Explicitly out of scope:** process listing / `/proc` introspection in general — surveillance-adjacent with no clear use case, would undermine the narrow, targeted scope that's `os-helper`'s current strength.

### Considered, explicitly decided NOT now

- **Remote reboot via JARVIS** — evaluated 2026-08-03. Real risk: differs from `restart_container` (containerized, small blast radius) because it affects the host itself — if something goes wrong after reboot (e.g. network config), total loss of access until physical access is available. If ever built, needs a severity level equivalent to DAYBREAK/BLACKOUT, not a standard `/confirm` — likely with a pre-check that Tailscale will come back up correctly, possibly a watchdog. Not on the roadmap today.
- **Configurable model (`JARVIS_MODEL` env var)** — logged idea, not urgent. When needed: a small change (env var in `.env` instead of a hardcoded string in `main.py`), but recommend A/B testing tool-calling reliability before making it permanent — GPT-4o was deliberately chosen for that criterion, a newer model isn't automatically better at it.
- **Database query/read tool** (`query_audit_log`) — would be low-risk if built, but explicitly decided to stay out along with the edit/rollback item — no real need today, low reward.

---

## Security/production-learning track

Parallel track, learning value (PJPT/PNPT):

1. **Docker Policy Broker + rootless Docker** ✅ fully completed (2026-08-01/02).
2. **os-helper privilege separation model** ✅ completed (2026-08-03) — a good, recent example of `NoNewPrivileges` interacting with sudo/capabilities, the privileged-collector-with-shared-snapshot pattern.
3. **`ufw` + Tailscale netfilter interaction** ✅ investigated (2026-08-03) — a good example of overlay-network-vs-host-firewall interaction, relevant topic for PJPT/PNPT.
4. **Trivy** — CVE scanning on images, low effort, not started.
5. **AIDE / File Integrity Monitoring** — reduced practical value after the mount split (already `:ro`), not started.

**Decided to add later, not now:** Wazuh (RAM-heavy, waiting on a hardware upgrade), Suricata/Zeek (needs a managed switch), VLAN segmentation (needs a managed switch), Traefik (Tailscale already covers its value), CrowdSec (low value with no public-facing services), Vault (overkill), canary tokens (low priority).

---

## Open questions / decisions for next session

- When the hardware upgrade is worth it (custom build, RTX 2060/3060, €400-600) — e.g. "when we want Wazuh" as a practical trigger instead of a vague timeline.
- When it's worth starting the custom broker/agents project — e.g. if the threat model changes.
- Whether the morning health digest (see "Next up") ends up replacing or just supplementing the separate email/reports item.
