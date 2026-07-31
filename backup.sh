#!/bin/bash
#
# jarvis-backup.sh
# Deterministic backup script for the JARVIS home server.
# NOT AI-driven — this runs as a plain scheduled script (cron), independent
# of the orchestrator/LLM. It touches JARVIS config, JARVIS logs, and
# Docker named volumes. It never touches other services' data beyond
# reading their volumes for archival.
#
# Usage:
#   ./backup.sh              -> run a backup now
#   ./backup.sh --dry-run    -> show what would happen, change nothing
#
set -uo pipefail
# NOTE: intentionally not using `set -e` — a single failed step (e.g. one
# volume backup failing) should not abort the whole run. Each step is
# checked and logged individually instead. See run_step().

# ============================================================
# CONFIG — edit these to match your setup
# ============================================================

JARVIS_HOME="${JARVIS_HOME:-$HOME/jarvis}"
BACKUP_ROOT="${BACKUP_ROOT:-$HOME/jarvis-backups}"
EXTERNAL_MOUNT="${EXTERNAL_MOUNT:-/mnt/backup_external}"   # USB disk mount point, when it exists
RETENTION_COUNT="${RETENTION_COUNT:-7}"                     # how many local backups to keep

# Used ONLY for `docker run -v <path>:...` arguments, never for direct
# file operations (tar/cp/mkdir) in this script. Those keep using
# $BACKUP_ROOT directly, which is correct whether this script runs on
# the host shell or inside a container that has $JARVIS_HOME bind-mounted
# 1:1 with the host (e.g. /app/jarvis == host's ~/jarvis).
#
# But `docker run -v` is different: it's a request to the DOCKER DAEMON
# (potentially the HOST's daemon, reached via a mounted docker.sock),
# not a filesystem operation performed by this process. The daemon
# resolves that path against ITS OWN filesystem view - the host's - not
# this process's view. If this script runs inside a container, its own
# $BACKUP_ROOT (e.g. /app/jarvis/jarvis-backups) is meaningless to the
# host daemon; the daemon needs the real host path instead (e.g.
# /home/nickchronis2004/jarvis/jarvis-backups). Defaults to $BACKUP_ROOT
# unchanged, so plain host-shell usage needs no extra configuration.
DOCKER_HOST_BACKUP_ROOT="${DOCKER_HOST_BACKUP_ROOT:-$BACKUP_ROOT}"

# Docker volumes to back up: auto-discovered, not hardcoded — any new
# service's volume is picked up automatically, no script edit needed.
#
# Anonymous volumes (Docker-assigned 64-char hex names, created when a
# container doesn't specify a volume name) are filtered out automatically
# — they're usually orphaned leftovers, not something you deliberately
# named and rely on.
#
# VOLUME_EXCLUDES is for volumes you DO want to deliberately skip, e.g.
# because they're just re-downloadable cache/model data, not original
# data. Add a name (exact match) per line.
VOLUME_EXCLUDES=(
    ollama_ollama_data   # just downloaded model weights — `ollama pull` restores it in minutes
)

is_excluded() {
    local vol="$1"
    for ex in "${VOLUME_EXCLUDES[@]}"; do
        [[ "$vol" == "$ex" ]] && return 0
    done
    return 1
}

# A Docker anonymous volume name is exactly 64 hex characters. Named
# volumes are anything else (they come from a compose `volumes:` key
# or an explicit `docker volume create`).
is_anonymous_volume() {
    [[ "$1" =~ ^[0-9a-f]{64}$ ]]
}

discover_volumes() {
    local vol
    docker volume ls -q | while read -r vol; do
        is_anonymous_volume "$vol" && continue
        is_excluded "$vol" && continue
        echo "$vol"
    done
}

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
fi

# ============================================================
# SETUP
# ============================================================

TIMESTAMP="$(date +%Y-%m-%d_%H%M)"
RUN_DIR="$BACKUP_ROOT/backup_${TIMESTAMP}"
LOG_FILE="$BACKUP_ROOT/backup.log"

mkdir -p "$BACKUP_ROOT"
mkdir -p "$RUN_DIR"/{config,logs,volumes,secrets}

STEP_RESULTS=()   # collects "name:status" for the summary at the end

log() {
    local msg="$1"
    local line="[$(date '+%Y-%m-%d %H:%M:%S')] $msg"
    echo "$line"
    echo "$line" >> "$LOG_FILE"
}

# run_step NAME COMMAND...
# Runs a step, captures success/fail, never kills the script.
run_step() {
    local name="$1"
    shift
    if $DRY_RUN; then
        log "[DRY-RUN] would run: $name"
        STEP_RESULTS+=("$name:SKIPPED(dry-run)")
        return 0
    fi
    if "$@" >> "$LOG_FILE" 2>&1; then
        log "OK   - $name"
        STEP_RESULTS+=("$name:OK")
        return 0
    else
        log "FAIL - $name (see $LOG_FILE for details)"
        STEP_RESULTS+=("$name:FAIL")
        return 1
    fi
}

log "=============================================="
log "Starting JARVIS backup run -> $RUN_DIR"
$DRY_RUN && log "(DRY RUN — no changes will be made)"

# ============================================================
# 1. JARVIS config (everything except secrets and junk)
# ============================================================

backup_config() {
    local base
    base="$(basename "$JARVIS_HOME")"
    tar --exclude='__pycache__' \
        --exclude='.pending_confirmation.json' \
        --exclude="orchestrator/.env" \
        --exclude="${base}/logs" \
        -czf "$RUN_DIR/config/jarvis-config.tar.gz" \
        -C "$(dirname "$JARVIS_HOME")" "$base"
}
run_step "jarvis-config" backup_config

# ============================================================
# 2. Secrets (.env) — separate file, locked-down permissions,
#    never mixed with anything that might later go external/cloud
#    unencrypted.
# ============================================================

backup_secrets() {
    local env_file="$JARVIS_HOME/orchestrator/.env"
    if [[ -f "$env_file" ]]; then
        cp "$env_file" "$RUN_DIR/secrets/orchestrator.env"
        chmod 600 "$RUN_DIR/secrets/orchestrator.env"
    else
        log "WARN - no .env file found at $env_file, skipping secrets backup"
        return 1
    fi
}
run_step "secrets(.env)" backup_secrets

# ============================================================
# 3. JARVIS logs (audit.db + cooldown state)
# ============================================================

backup_logs() {
    tar -czf "$RUN_DIR/logs/jarvis-logs.tar.gz" \
        -C "$JARVIS_HOME" logs
}
run_step "jarvis-logs" backup_logs

# ============================================================
# 4. Docker named volumes
#    Each volume is archived via a throwaway alpine container that
#    mounts the volume read-only and tars it out. This avoids
#    needing root access to Docker's internal storage paths.
# ============================================================

# ============================================================
# 4. Docker named volumes (auto-discovered — see discover_volumes above)
#    Each volume is archived via a throwaway alpine container that
#    mounts the volume read-only and tars it out. This avoids
#    needing root access to Docker's internal storage paths.
# ============================================================

backup_volume() {
    local vol="$1"
    # DOCKER_HOST_RUN_DIR: what the Docker daemon needs for -v (host-real path)
    # RUN_DIR: what THIS process needs to check the resulting file exists
    #          afterward, if ever - stays in this process's own view.
    local docker_host_run_dir="${DOCKER_HOST_BACKUP_ROOT}/backup_${TIMESTAMP}/volumes"
    docker run --rm \
        -v "${vol}:/data:ro" \
        -v "${docker_host_run_dir}:/backup" \
        alpine:3.20 \
        tar -czf "/backup/${vol}.tar.gz" -C /data .
}

DISCOVERED_VOLUMES=()
while IFS= read -r vol; do
    [[ -n "$vol" ]] && DISCOVERED_VOLUMES+=("$vol")
done < <(discover_volumes)

log "Discovered ${#DISCOVERED_VOLUMES[@]} volume(s) to back up: ${DISCOVERED_VOLUMES[*]:-none}"

for vol in "${DISCOVERED_VOLUMES[@]}"; do
    run_step "volume:$vol" backup_volume "$vol"
done

# ============================================================
# 5. Sync to external disk, if mounted. Conditional on purpose —
#    the USB disk doesn't exist yet. When it does, mount it at
#    $EXTERNAL_MOUNT (or export EXTERNAL_MOUNT=... before running)
#    and this step activates automatically, no script changes needed.
# ============================================================

sync_external() {
    rsync -a --delete "$BACKUP_ROOT"/ "$EXTERNAL_MOUNT"/jarvis-backups/
}

if [[ -d "$EXTERNAL_MOUNT" ]] && mountpoint -q "$EXTERNAL_MOUNT" 2>/dev/null; then
    run_step "sync-external" sync_external
else
    log "WARN - external backup target '$EXTERNAL_MOUNT' not mounted, local-only this run"
    STEP_RESULTS+=("sync-external:SKIPPED(not mounted)")
fi

# ============================================================
# 6. Retention — keep only the last N local backup folders
# ============================================================

apply_retention() {
    local count
    count=$(find "$BACKUP_ROOT" -maxdepth 1 -type d -name 'backup_*' | wc -l)
    if (( count > RETENTION_COUNT )); then
        find "$BACKUP_ROOT" -maxdepth 1 -type d -name 'backup_*' | sort | head -n "$((count - RETENTION_COUNT))" | while read -r old; do
            log "Removing old backup: $old"
            rm -rf "$old"
        done
    fi
}
run_step "retention" apply_retention

# ============================================================
# SUMMARY
# ============================================================

log "----------------------------------------------"
log "Backup run summary:"
FAIL_COUNT=0
for r in "${STEP_RESULTS[@]}"; do
    log "  $r"
    [[ "$r" == *":FAIL" ]] && ((FAIL_COUNT++))
done
log "=============================================="

if (( FAIL_COUNT > 0 )); then
    log "Backup completed WITH ${FAIL_COUNT} failure(s)."
    exit 1
else
    log "Backup completed successfully."
    exit 0
fi
