#!/bin/bash
# setup-maintenance-cron.sh — Install the myodoo maintenance cron jobs + logrotate
# Version 1.2.0 — 11.06.2026
#
# Installs a declarative /etc/cron.d/ drop-in (versioned in this repo) instead of
# hand-edited per-user crontabs, plus a matching logrotate config. Idempotent:
# safe to re-run; re-running just refreshes the installed files.
#
# Jobs installed (see myodoo-maintenance.cron for the authoritative schedule):
#   - container2backup.py   02:00 + 14:00   (DB + filestore backup, RPO ~12h)
#   - ssl-renew.sh          00:00 daily     (Let's Encrypt renewal, no-op if nothing due)
#   - cleanup-weblogs.py    03:00 daily     (DSGVO: rotate/purge nginx logs >7 days)
#   - nightly-cleanup.sh    04:30 daily     (container restart cycle + journald vacuum)
#
# The cron entries reference the scripts in ${SCRIPT_DIR} (default /root, where
# getScripts.py deploys them). Override with SCRIPT_DIR=/path if they live elsewhere.
#
# Usage (as root or via sudo):
#   ./setup-maintenance-cron.sh            # install cron.d + logrotate
#   SCRIPT_DIR=/opt ./setup-maintenance-cron.sh
#   ./setup-maintenance-cron.sh --remove   # uninstall both files
#
# NOTE: This does NOT validate that container2backup.yaml exists or that TLS certs
# are issued — those are instance-specific. The backup job exits cleanly until a
# config is present; ssl-renew is a no-op until certs exist.
#
# Post-install also scans root's user-crontab (`crontab -l -u root`) for legacy
# entries referencing the now-managed scripts and warns about them — these would
# duplicate the cron.d jobs (e.g. backups running twice). The script never edits
# the user crontab; removal is left to the operator via `sudo crontab -e -u root`.
##############################################################################

set -Eeuo pipefail

SCRIPT_VERSION="1.2.0"
SCRIPT_DATE="11.06.2026"

# Where the maintenance scripts live (getScripts.py copies them to /root).
SCRIPT_DIR="${SCRIPT_DIR:-/root}"

CRON_DEST="/etc/cron.d/myodoo-maintenance"
LOGROTATE_DEST="/etc/logrotate.d/myodoo-maintenance"

# Templates ship next to this script.
SELF_DIR="$(cd "$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")" && pwd)"
CRON_SRC="${SELF_DIR}/myodoo-maintenance.cron"
LOGROTATE_SRC="${SELF_DIR}/myodoo-maintenance.logrotate"

# Scripts referenced by the cron entries (for an existence sanity-check).
MANAGED_SCRIPTS=(container2backup.py ssl-renew.sh cleanup-weblogs.py nginx-cert-guard.py nightly-cleanup.sh)

SEPARATOR="────────────────────────────────────────────────────────"
if [ -t 1 ]; then
    C_RED="$(printf '\033[0;31m')"; C_GREEN="$(printf '\033[0;32m')"
    C_YELLOW="$(printf '\033[1;33m')"; C_BLUE="$(printf '\033[0;34m')"; C_NC="$(printf '\033[0m')"
else
    C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_NC=""
fi

log()  { echo "${C_GREEN}$(date '+%Y-%m-%d %H:%M:%S')${C_NC} | $*"; }
warn() { echo "${C_YELLOW}$(date '+%Y-%m-%d %H:%M:%S') | WARN:${C_NC} $*" >&2; }
err()  { echo "${C_RED}$(date '+%Y-%m-%d %H:%M:%S') | ERROR:${C_NC} $*" >&2; }
die()  { err "$*"; exit 1; }
section() { echo ""; echo "${C_BLUE}${SEPARATOR}${C_NC}"; log "$*"; echo "${C_BLUE}${SEPARATOR}${C_NC}"; }

on_error() { local ec=$?; err "Aborted at line ${BASH_LINENO[0]} (exit ${ec}): ${BASH_COMMAND}"; exit "$ec"; }
trap on_error ERR

# Resolve a privilege-escalation prefix. Empty when already root.
SUDO=""
resolve_privilege() {
    if [ "$(id -u)" -eq 0 ]; then
        SUDO=""
    elif command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        die "Needs root privileges, but neither root nor sudo is available. Re-run as root."
    fi
}

remove_files() {
    section "Removing myodoo maintenance cron + logrotate"
    local removed=0
    for f in "$CRON_DEST" "$LOGROTATE_DEST"; do
        if [ -f "$f" ]; then
            $SUDO rm -f "$f"
            log "Removed: $f"
            removed=$((removed + 1))
        else
            log "Not present (nothing to remove): $f"
        fi
    done
    [ "$removed" -gt 0 ] && log "Maintenance cron uninstalled." || log "Nothing was installed."
}

install_files() {
    section "Installing myodoo maintenance cron + logrotate (v${SCRIPT_VERSION})"

    [ -f "$CRON_SRC" ]      || die "Cron template not found: ${CRON_SRC}"
    [ -f "$LOGROTATE_SRC" ] || die "logrotate template not found: ${LOGROTATE_SRC}"

    # Sanity-check that the referenced scripts exist where the cron entries expect.
    local missing=0
    for s in "${MANAGED_SCRIPTS[@]}"; do
        if [ ! -f "${SCRIPT_DIR}/${s}" ]; then
            warn "Referenced script missing: ${SCRIPT_DIR}/${s} (its cron job will fail until present)."
            missing=$((missing + 1))
        fi
    done
    [ "$missing" -eq 0 ] && log "All referenced scripts present in ${SCRIPT_DIR}."

    # Install the cron.d drop-in. The template targets /root; rewrite to SCRIPT_DIR
    # if a different location was requested. cron ignores group/world-writable
    # files, so the destination must be 0644 root:root.
    local tmp_cron
    tmp_cron="$(mktemp)"
    if [ "$SCRIPT_DIR" = "/root" ]; then
        cat "$CRON_SRC" > "$tmp_cron"
    else
        # Only rewrite the command paths (" /root/<script>"), not the comment text.
        sed "s# /root/# ${SCRIPT_DIR%/}/#g" "$CRON_SRC" > "$tmp_cron"
    fi
    $SUDO install -m 0644 -o root -g root "$tmp_cron" "$CRON_DEST"
    rm -f "$tmp_cron"
    log "Installed: ${CRON_DEST} (0644 root:root)"

    # Legacy standalone cron from the old NIGHTLY_CLEANUP.md instructions —
    # would run IN ADDITION to the managed 04:30 job (and at 03:00, close to
    # the backup window). Warn only; never delete files we did not install.
    if [ -f /etc/cron.d/nightly-cleanup ]; then
        warn "Legacy /etc/cron.d/nightly-cleanup found — nightly-cleanup.sh now runs at 04:30 via ${CRON_DEST}."
        warn "Remove the legacy file to avoid duplicate runs: sudo rm /etc/cron.d/nightly-cleanup"
    fi

    # Install logrotate config.
    $SUDO install -m 0644 -o root -g root "$LOGROTATE_SRC" "$LOGROTATE_DEST"
    log "Installed: ${LOGROTATE_DEST}"

    # Validate the logrotate config in debug mode (read-only, writes nothing).
    if command -v logrotate >/dev/null 2>&1; then
        if $SUDO logrotate -d "$LOGROTATE_DEST" >/dev/null 2>&1; then
            log "logrotate config validated (logrotate -d)."
        else
            warn "logrotate -d reported issues for ${LOGROTATE_DEST} — review manually."
        fi
    else
        warn "logrotate not installed — install it so the maintenance logs get rotated."
    fi
}

# Read-only scan of root's user-crontab for legacy entries that would duplicate
# the jobs we just installed in /etc/cron.d/. Never writes — the user-crontab is
# off-limits for automated edits (it may contain unrelated operator entries).
detect_user_crontab_overlap() {
    command -v crontab >/dev/null 2>&1 || return 0

    # `crontab -l` exits 1 with "no crontab for <user>" when none exists. Swallow
    # both stderr and the non-zero exit; an empty stdin to the loop means "clean".
    local crontab_dump
    crontab_dump="$($SUDO crontab -l -u root 2>/dev/null || true)"
    [ -n "$crontab_dump" ] || return 0

    # Match by script basename so non-default SCRIPT_DIR installs are still
    # caught (e.g. legacy /root/... entries after the operator moved to /opt).
    local overlaps=()
    local line
    while IFS= read -r line; do
        # Skip empty lines and comments — they cannot schedule a job.
        [ -z "${line// /}" ] && continue
        case "$line" in \#*) continue ;; esac
        for s in "${MANAGED_SCRIPTS[@]}"; do
            if [[ "$line" == *"$s"* ]]; then
                overlaps+=("$line")
                break
            fi
        done
    done <<< "$crontab_dump"

    [ "${#overlaps[@]}" -eq 0 ] && return 0

    warn "Legacy entries in root's user-crontab reference scripts we now manage in ${CRON_DEST}:"
    local entry
    for entry in "${overlaps[@]}"; do
        echo "    ${C_YELLOW}>${C_NC} ${entry}" >&2
    done
    echo "" >&2
    echo "  ${C_YELLOW}These will run IN ADDITION to the cron.d jobs (e.g. duplicate backups).${C_NC}" >&2
    echo "  Remove them with:  ${C_GREEN}sudo crontab -e -u root${C_NC}" >&2
    echo "  (this script never edits the user crontab — it may contain unrelated entries)." >&2
    echo "" >&2
}

print_next_steps() {
    section "Maintenance cron installed"
    echo "${C_GREEN}Cron jobs are active via ${CRON_DEST}.${C_NC}"
    echo ""
    echo "${C_YELLOW}Reminders:${C_NC}"
    echo "  • Backup needs ${SCRIPT_DIR}/container2backup.yaml — until then it exits cleanly."
    echo "  • ssl-renew is a no-op until Let's Encrypt certs are issued (certbot certonly)."
    echo "  • nightly-cleanup restarts containers at 04:30 — tune ODOO_PATTERN etc. via env if needed."
    echo "  • Logs: /var/log/{container2backup,ssl-renew,cleanup-weblogs,nightly-cleanup}.log (rotated weekly)."
    echo "  • Uninstall any time with: $0 --remove"
    echo ""
}

main() {
    case "${1:-}" in
        --help|-h) sed -n '2,29p' "$0"; exit 0 ;;
        --remove)  resolve_privilege; remove_files; exit 0 ;;
        "")        : ;;
        *)         die "Unknown option: $1 (use --remove or --help)" ;;
    esac

    resolve_privilege
    install_files
    print_next_steps
    detect_user_crontab_overlap
}

main "$@"
