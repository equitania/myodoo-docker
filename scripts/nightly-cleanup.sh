#!/bin/bash
# nightly-cleanup.sh — Memory-based Docker container restart with before/after reporting
# Version 1.1.0 — 11.06.2026
#
# Only restarts containers that exceed the configured memory threshold.
# Restart order: FastReport (independent) | Odoo stop → Postgres restart → pg_isready → Odoo start
#
# Usage:
#   /usr/local/bin/nightly-cleanup.sh              # Normal run
#   MEMORY_THRESHOLD=90 nightly-cleanup.sh         # Override threshold
#   DRY_RUN=1 nightly-cleanup.sh                   # Dry run (no restarts)
#
# Cron example (every night at 3:00):
#   0 3 * * * /usr/local/bin/nightly-cleanup.sh
##############################################################################

set -euo pipefail

# ──────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────

# Memory threshold in percent — containers below this are left alone
MEMORY_THRESHOLD="${MEMORY_THRESHOLD:-80}"

# Log file path
LOG="${CLEANUP_LOG:-/var/log/nightly-cleanup.log}"

# Dry run mode — set to 1 to only report without restarting
DRY_RUN="${DRY_RUN:-0}"

# Container name patterns (grep -iE patterns)
ODOO_PATTERN="${ODOO_PATTERN:-odoo}"
# Anchored db patterns: bare "db-|-db" also matched e.g. "redis-db-cache"
POSTGRES_PATTERN="${POSTGRES_PATTERN:-postgres|psql|pg-|^db-|-db\$}"
FASTREPORT_PATTERN="${FASTREPORT_PATTERN:-fastreport|fast-report|report}"

# Timeouts
STOP_TIMEOUT=30
PG_READY_TIMEOUT=60
PG_READY_INTERVAL=5

# Journal log retention
JOURNAL_RETENTION="7d"

SEPARATOR="────────────────────────────────────────────────────────"

# ──────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────

log_msg() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') | $*" >> "$LOG"
}

log_section() {
    echo "" >> "$LOG"
    echo "$SEPARATOR" >> "$LOG"
    log_msg "$*"
    echo "$SEPARATOR" >> "$LOG"
}

# Find containers matching a name pattern (only running containers)
get_containers_by_type() {
    local pattern="$1"
    docker ps --format '{{.Names}}' | grep -iE "$pattern" || true
}

# Get memory usage percentage for a running container
# Returns float value (e.g. "75.32") or empty string on failure
get_memory_percent() {
    local container="$1"
    local status
    status=$(docker inspect --format '{{.State.Status}}' "$container" 2>/dev/null || echo "unknown")
    if [[ "$status" != "running" ]]; then
        echo ""
        return
    fi
    docker stats --no-stream --format "{{.MemPerc}}" "$container" 2>/dev/null | tr -d '%' | xargs
}

# Get memory usage in human-readable format
get_memory_usage() {
    local container="$1"
    docker stats --no-stream --format "{{.MemUsage}}" "$container" 2>/dev/null || echo "n/a"
}

# Get container health status
get_health_status() {
    local container="$1"
    docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$container" 2>/dev/null || echo "unknown"
}

# Log container status and memory info
log_container_stats() {
    local container="$1"
    local status health mem mem_pct
    status=$(docker inspect --format '{{.State.Status}}' "$container" 2>/dev/null || echo "unknown")
    health=$(get_health_status "$container")
    mem=$(get_memory_usage "$container")
    mem_pct=$(get_memory_percent "$container")
    log_msg "  $container | Status: $status | Health: $health | RAM: ${mem:-n/a} (${mem_pct:-?}%)"
}

# Check if a container exceeds the memory threshold
# Returns 0 (true) if restart needed, 1 (false) if not
needs_restart() {
    local container="$1"
    local threshold="$2"
    local usage

    usage=$(get_memory_percent "$container")
    if [[ -z "$usage" ]]; then
        return 1  # Cannot read stats — skip
    fi

    # Compare floating point: usage > threshold
    if awk "BEGIN {exit !($usage > $threshold)}"; then
        return 0  # Exceeds threshold
    fi
    return 1
}

# Wait for PostgreSQL to accept connections
wait_for_postgres() {
    local container="$1"
    local timeout="${2:-$PG_READY_TIMEOUT}"
    local interval="${3:-$PG_READY_INTERVAL}"
    local elapsed=0

    log_msg "  Waiting for $container to accept connections (timeout: ${timeout}s)..."

    while [[ $elapsed -lt $timeout ]]; do
        if docker exec "$container" pg_isready -U postgres > /dev/null 2>&1; then
            log_msg "  $container: ready after ${elapsed}s"
            return 0
        fi
        sleep "$interval"
        elapsed=$((elapsed + interval))
    done

    log_msg "  WARNING: $container not ready after ${timeout}s!"
    return 1
}

# Restart a container (respects DRY_RUN)
do_restart() {
    local container="$1"
    if [[ "$DRY_RUN" == "1" ]]; then
        log_msg "    -> DRY RUN: would restart $container"
    else
        docker restart --time="$STOP_TIMEOUT" "$container" >> "$LOG" 2>&1
        log_msg "    -> restarted"
    fi
}

# Stop a container (respects DRY_RUN)
do_stop() {
    local container="$1"
    if [[ "$DRY_RUN" == "1" ]]; then
        log_msg "    -> DRY RUN: would stop $container"
    else
        docker stop --time="$STOP_TIMEOUT" "$container" >> "$LOG" 2>&1
        log_msg "    -> stopped"
    fi
}

# Start a container (respects DRY_RUN)
do_start() {
    local container="$1"
    if [[ "$DRY_RUN" == "1" ]]; then
        log_msg "    -> DRY RUN: would start $container"
    else
        docker start "$container" >> "$LOG" 2>&1
        log_msg "    -> started"
    fi
}

# ──────────────────────────────────────────
# Main workflow
# ──────────────────────────────────────────

log_section "Nightly cleanup started (threshold: ${MEMORY_THRESHOLD}%, dry_run: ${DRY_RUN})"

# ──────────────────────────────────────────
# BEFORE: Capture system state
# ──────────────────────────────────────────
log_section "[BEFORE] System status"

RAM_USED_BEFORE=$(free -m | awk '/^Mem:/{print $3}')
RAM_AVAIL_BEFORE=$(free -m | awk '/^Mem:/{print $7}')
SWAP_USED_BEFORE=$(free -m | awk '/^Swap:/{print $3}')
DOCKER_IMAGES_BEFORE=$(docker images -q | wc -l)
DOCKER_VOLUMES_BEFORE=$(docker volume ls -q | wc -l)

free -m >> "$LOG"
log_msg "Disk root: $(df -h / | tail -1)"
echo "" >> "$LOG"
docker system df 2>/dev/null >> "$LOG"
log_msg ""
log_msg "Summary BEFORE:"
log_msg "  RAM used:        ${RAM_USED_BEFORE} MB"
log_msg "  RAM available:   ${RAM_AVAIL_BEFORE} MB"
log_msg "  Swap used:       ${SWAP_USED_BEFORE} MB"
log_msg "  Docker images:   ${DOCKER_IMAGES_BEFORE}"
log_msg "  Docker volumes:  ${DOCKER_VOLUMES_BEFORE}"

# Discover container groups
ODOO_CONTAINERS=$(get_containers_by_type "$ODOO_PATTERN")
POSTGRES_CONTAINERS=$(get_containers_by_type "$POSTGRES_PATTERN")
FASTREPORT_CONTAINERS=$(get_containers_by_type "$FASTREPORT_PATTERN")

log_msg ""
log_msg "Detected container groups:"
log_msg "  Odoo:       ${ODOO_CONTAINERS:-none}"
log_msg "  Postgres:   ${POSTGRES_CONTAINERS:-none}"
log_msg "  FastReport: ${FASTREPORT_CONTAINERS:-none}"

# ──────────────────────────────────────────
# Memory check for all running containers
# ──────────────────────────────────────────
log_section "[MEMORY CHECK] Checking container memory usage"

RESTART_COUNT=0

for container in $(docker ps --format '{{.Names}}'); do
    usage=$(get_memory_percent "$container")
    mem=$(get_memory_usage "$container")
    if [[ -n "$usage" ]]; then
        if awk "BEGIN {exit !($usage > $MEMORY_THRESHOLD)}"; then
            log_msg "  OVER  $container: ${mem} (${usage}%) > ${MEMORY_THRESHOLD}%"
        else
            log_msg "  OK    $container: ${mem} (${usage}%) <= ${MEMORY_THRESHOLD}%"
        fi
    else
        log_msg "  SKIP  $container: unable to read memory stats"
    fi
done

# ──────────────────────────────────────────
# 1. Docker housekeeping: dangling images and build cache
# ──────────────────────────────────────────
log_section "[ACTION 1] Docker image and build cache prune"
docker image prune -f >> "$LOG" 2>&1
docker builder prune -f >> "$LOG" 2>&1

# ──────────────────────────────────────────
# 2. FastReport containers — independent restart if over threshold
# ──────────────────────────────────────────
log_section "[ACTION 2] FastReport containers (independent)"
if [[ -n "$FASTREPORT_CONTAINERS" ]]; then
    for container in $FASTREPORT_CONTAINERS; do
        log_container_stats "$container"
        if needs_restart "$container" "$MEMORY_THRESHOLD"; then
            log_msg "  $container exceeds threshold — restarting"
            do_restart "$container"
            RESTART_COUNT=$((RESTART_COUNT + 1))
        else
            log_msg "  $container within threshold — skipping"
        fi
    done
else
    log_msg "  No FastReport containers found."
fi

# ──────────────────────────────────────────
# 3. Odoo + Postgres — ordered restart if ANY exceeds threshold
#    Order: Stop Odoo → Restart Postgres → wait pg_isready → Start Odoo
# ──────────────────────────────────────────
log_section "[ACTION 3] Odoo + Postgres group (ordered restart)"

ODOO_PG_NEEDS_RESTART=false

# Check if any Odoo container exceeds threshold
if [[ -n "$ODOO_CONTAINERS" ]]; then
    for container in $ODOO_CONTAINERS; do
        if needs_restart "$container" "$MEMORY_THRESHOLD"; then
            log_msg "  $container (Odoo) exceeds threshold — group restart triggered"
            ODOO_PG_NEEDS_RESTART=true
            break
        fi
    done
fi

# Check if any Postgres container exceeds threshold
if [[ -n "$POSTGRES_CONTAINERS" ]]; then
    for container in $POSTGRES_CONTAINERS; do
        if needs_restart "$container" "$MEMORY_THRESHOLD"; then
            log_msg "  $container (Postgres) exceeds threshold — group restart triggered"
            ODOO_PG_NEEDS_RESTART=true
            break
        fi
    done
fi

if [[ "$ODOO_PG_NEEDS_RESTART" == "true" ]]; then
    # Step 3a: Stop all Odoo containers
    log_msg ""
    log_msg "  Step 3a: Stopping Odoo containers..."
    if [[ -n "$ODOO_CONTAINERS" ]]; then
        for container in $ODOO_CONTAINERS; do
            log_container_stats "$container"
            do_stop "$container"
            RESTART_COUNT=$((RESTART_COUNT + 1))
        done
    fi

    # Step 3b: Restart Postgres containers
    log_msg ""
    log_msg "  Step 3b: Restarting Postgres containers..."
    if [[ -n "$POSTGRES_CONTAINERS" ]]; then
        for container in $POSTGRES_CONTAINERS; do
            log_container_stats "$container"
            do_restart "$container"
            RESTART_COUNT=$((RESTART_COUNT + 1))
        done

        # Wait for Postgres to accept connections
        if [[ "$DRY_RUN" != "1" ]]; then
            sleep 5
            for container in $POSTGRES_CONTAINERS; do
                wait_for_postgres "$container" "$PG_READY_TIMEOUT" "$PG_READY_INTERVAL" || true
            done
        fi
    fi

    # Step 3c: Start Odoo containers
    log_msg ""
    log_msg "  Step 3c: Starting Odoo containers..."
    if [[ -n "$ODOO_CONTAINERS" ]]; then
        for container in $ODOO_CONTAINERS; do
            do_start "$container"
        done
    fi
else
    log_msg "  All Odoo/Postgres containers within threshold — no restart needed."
    # Log current stats for reference
    for container in $ODOO_CONTAINERS $POSTGRES_CONTAINERS; do
        log_container_stats "$container"
    done
fi

# ──────────────────────────────────────────
# 4. Other containers — individual restart if over threshold
# ──────────────────────────────────────────
log_section "[ACTION 4] Other containers (individual check)"

ALL_KNOWN="$ODOO_CONTAINERS $POSTGRES_CONTAINERS $FASTREPORT_CONTAINERS"
OTHER_RESTARTED=0

for container in $(docker ps --format '{{.Names}}'); do
    # Skip known groups
    if echo "$ALL_KNOWN" | grep -qw "$container" 2>/dev/null; then
        continue
    fi

    log_container_stats "$container"
    if needs_restart "$container" "$MEMORY_THRESHOLD"; then
        log_msg "  $container exceeds threshold — restarting"
        do_restart "$container"
        RESTART_COUNT=$((RESTART_COUNT + 1))
        OTHER_RESTARTED=$((OTHER_RESTARTED + 1))
    else
        log_msg "  $container within threshold — skipping"
    fi
done

if [[ $OTHER_RESTARTED -eq 0 ]]; then
    log_msg "  No other containers needed restart."
fi

# ──────────────────────────────────────────
# 5. OS cleanup: page cache (safe, level 1 only)
# ──────────────────────────────────────────
log_section "[ACTION 5] OS page cache cleanup"
sync
if [[ -w /proc/sys/vm/drop_caches ]]; then
    echo 1 > /proc/sys/vm/drop_caches
    log_msg "  Page cache released (drop_caches=1)"
else
    log_msg "  Skipped: /proc/sys/vm/drop_caches not writable (non-root or container)"
fi

# ──────────────────────────────────────────
# 6. Swap cleanup (only if enough free RAM)
# ──────────────────────────────────────────
log_section "[ACTION 6] Swap cleanup"
FREE_RAM=$(free -m | awk '/^Mem:/{print $7}')
USED_SWAP=$(free -m | awk '/^Swap:/{print $3}')
if [[ "$USED_SWAP" -gt 0 ]] && [[ "$FREE_RAM" -gt "$USED_SWAP" ]]; then
    if [[ "$DRY_RUN" == "1" ]]; then
        log_msg "  DRY RUN: would reset swap (${USED_SWAP} MB used, ${FREE_RAM} MB free RAM)"
    else
        swapoff -a && swapon -a
        log_msg "  Swap reset (${USED_SWAP} MB released)"
    fi
else
    log_msg "  No swap reset needed (swap: ${USED_SWAP} MB, free RAM: ${FREE_RAM} MB)"
fi

# ──────────────────────────────────────────
# 7. Journal log vacuum
# ──────────────────────────────────────────
log_section "[ACTION 7] Journal log vacuum"
journalctl --vacuum-time="$JOURNAL_RETENTION" >> "$LOG" 2>&1 || log_msg "  journalctl not available — skipped"

# ──────────────────────────────────────────
# AFTER: Capture system state and compare
# ──────────────────────────────────────────
sleep 5

log_section "[AFTER] System status"

RAM_USED_AFTER=$(free -m | awk '/^Mem:/{print $3}')
RAM_AVAIL_AFTER=$(free -m | awk '/^Mem:/{print $7}')
SWAP_USED_AFTER=$(free -m | awk '/^Swap:/{print $3}')
DOCKER_IMAGES_AFTER=$(docker images -q | wc -l)
DOCKER_VOLUMES_AFTER=$(docker volume ls -q | wc -l)

free -m >> "$LOG"
log_msg "Disk root: $(df -h / | tail -1)"
echo "" >> "$LOG"
docker system df 2>/dev/null >> "$LOG"

# ──────────────────────────────────────────
# Comparison
# ──────────────────────────────────────────
RAM_DIFF=$((RAM_USED_BEFORE - RAM_USED_AFTER))
SWAP_DIFF=$((SWAP_USED_BEFORE - SWAP_USED_AFTER))
IMAGES_DIFF=$((DOCKER_IMAGES_BEFORE - DOCKER_IMAGES_AFTER))

log_section "[COMPARISON] Before -> After"
log_msg "  RAM used:        ${RAM_USED_BEFORE} MB -> ${RAM_USED_AFTER} MB (${RAM_DIFF} MB freed)"
log_msg "  RAM available:   ${RAM_AVAIL_BEFORE} MB -> ${RAM_AVAIL_AFTER} MB"
log_msg "  Swap used:       ${SWAP_USED_BEFORE} MB -> ${SWAP_USED_AFTER} MB (${SWAP_DIFF} MB freed)"
log_msg "  Docker images:   ${DOCKER_IMAGES_BEFORE} -> ${DOCKER_IMAGES_AFTER} (${IMAGES_DIFF} removed)"
log_msg "  Docker volumes:  ${DOCKER_VOLUMES_BEFORE} -> ${DOCKER_VOLUMES_AFTER}"
log_msg "  Containers restarted: ${RESTART_COUNT}"

# Container status at the end
log_msg ""
log_msg "Container status after cleanup:"
docker ps -a --format "  {{.Names}} | {{.Status}}" >> "$LOG"

log_section "Nightly cleanup finished — ${RESTART_COUNT} containers restarted"
