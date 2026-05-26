#!/bin/bash
# dist-upgrade-debian.sh — Guided Debian major release upgrade (e.g. 12→13)
# Version 1.0.0 — 26.05.2026
#
# Performs an in-place Debian major upgrade by rewriting the apt codename across
# ALL sources (sources.list + sources.list.d/*.list + *.sources), then running
# the phased upgrade the Debian release notes recommend.
#
# Generic: the current codename is auto-detected and mapped to the next Debian
# release (bookworm→trixie→forky→...). Pass a target codename to override.
#
# SAFE BY DESIGN:
#   - Refuses to run on non-Debian (use 'do-release-upgrade' on Ubuntu)
#   - Backs up every sources file to ~/history/<timestamp>/ before editing
#   - Confirmation prompt before starting (skip with --yes)
#   - Keeps existing conffiles on conflict (review *.dpkg-dist afterwards)
#   - Asks before rebooting at the end
#
# Usage (as root):
#   ./dist-upgrade-debian.sh                 # auto: current → next release
#   ./dist-upgrade-debian.sh trixie          # force target codename
#   ./dist-upgrade-debian.sh --yes           # no confirmation prompt
#
# STRONGLY recommended: run inside screen/tmux and have a snapshot/backup ready.
##############################################################################

set -Eeuo pipefail

SCRIPT_VERSION="1.0.0"
SCRIPT_DATE="26.05.2026"

# Ordered Debian release codenames — used to map current → next.
DEBIAN_SEQUENCE=(buster bullseye bookworm trixie forky)

export DEBIAN_FRONTEND=noninteractive
# Keep existing configs on conffile conflicts so the upgrade never blocks on a
# prompt; new defaults are written as <file>.dpkg-dist for later review.
APT_DPKG_OPTS=(-o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)

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

# ── Argument parsing ─────────────────────────────────────────
ASSUME_YES=0
TARGET_CODENAME=""
for arg in "$@"; do
    case "$arg" in
        --yes|-y) ASSUME_YES=1 ;;
        --help|-h) sed -n '2,30p' "$0"; exit 0 ;;
        -*) die "Unknown option: $arg" ;;
        *) TARGET_CODENAME="$arg" ;;
    esac
done

# ── Preconditions ────────────────────────────────────────────
[ "$(id -u)" -eq 0 ] || die "This script must be run as root."
[ -r /etc/os-release ] || die "/etc/os-release not found."
# shellcheck disable=SC1091
. /etc/os-release
[ "${ID:-}" = "debian" ] || die "Not Debian (ID=${ID:-?}). On Ubuntu use 'do-release-upgrade'."

CURRENT_CODENAME="${VERSION_CODENAME:-}"
[ -n "$CURRENT_CODENAME" ] || die "Could not determine current codename (VERSION_CODENAME)."

# ── Determine target codename ────────────────────────────────
if [ -z "$TARGET_CODENAME" ]; then
    idx=-1
    for i in "${!DEBIAN_SEQUENCE[@]}"; do
        [ "${DEBIAN_SEQUENCE[$i]}" = "$CURRENT_CODENAME" ] && idx=$i && break
    done
    [ "$idx" -ge 0 ] || die "Current codename '$CURRENT_CODENAME' not in known sequence — pass a target explicitly."
    next_idx=$((idx + 1))
    [ "$next_idx" -lt "${#DEBIAN_SEQUENCE[@]}" ] || die "No known release after '$CURRENT_CODENAME'. Update DEBIAN_SEQUENCE."
    TARGET_CODENAME="${DEBIAN_SEQUENCE[$next_idx]}"
fi

[ "$TARGET_CODENAME" != "$CURRENT_CODENAME" ] || die "Target equals current codename ('$CURRENT_CODENAME') — nothing to do."

section "Debian major upgrade v${SCRIPT_VERSION}: ${CURRENT_CODENAME} → ${TARGET_CODENAME}"
warn "This is a MAJOR OS upgrade. Run it inside screen/tmux and have a snapshot ready."
warn "Existing conffiles are kept on conflict; review *.dpkg-dist files afterwards."

if [ "$ASSUME_YES" -ne 1 ]; then
    read -r -p "Proceed with ${CURRENT_CODENAME} → ${TARGET_CODENAME}? (j/N): " answer
    case "${answer,,}" in j|ja|y|yes) ;; *) die "Aborted by user." ;; esac
fi

# ── Phase 0: fully patch the current release first ───────────
section "Phase 0/5: Fully updating current release (${CURRENT_CODENAME})"
apt-get update
apt-get -y "${APT_DPKG_OPTS[@]}" full-upgrade

# ── Phase 1: back up + rewrite sources ───────────────────────
section "Phase 1/5: Backing up and rewriting apt sources"
BACKUP_DIR="${HOME}/history/apt-sources-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

changed=0
rewrite_file() {
    local f="$1"
    [ -f "$f" ] || return 0
    if grep -q "$CURRENT_CODENAME" "$f" 2>/dev/null; then
        cp -a "$f" "$BACKUP_DIR/"
        sed -i "s/\b${CURRENT_CODENAME}\b/${TARGET_CODENAME}/g" "$f"
        log "Rewrote: $f"
        changed=$((changed + 1))
    fi
}

rewrite_file /etc/apt/sources.list
if [ -d /etc/apt/sources.list.d ]; then
    for f in /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
        [ -e "$f" ] && rewrite_file "$f"
    done
fi
log "Backups stored in: ${BACKUP_DIR}"
[ "$changed" -gt 0 ] || warn "No sources mentioned '${CURRENT_CODENAME}' — check your apt configuration."

# ── Phase 2: refresh indices against the new release ─────────
section "Phase 2/5: Refreshing package indices (${TARGET_CODENAME})"
if ! apt-get update; then
    err "apt-get update failed against ${TARGET_CODENAME}."
    err "A third-party repo may not serve ${TARGET_CODENAME} yet. Restore from ${BACKUP_DIR} and retry."
    exit 1
fi

# ── Phase 3: minimal upgrade (no new packages) ───────────────
section "Phase 3/5: Minimal upgrade (apt-get upgrade)"
apt-get -y "${APT_DPKG_OPTS[@]}" upgrade

# ── Phase 4: full upgrade ────────────────────────────────────
section "Phase 4/5: Full upgrade (apt-get full-upgrade)"
apt-get -y "${APT_DPKG_OPTS[@]}" full-upgrade

# ── Phase 5: cleanup ─────────────────────────────────────────
section "Phase 5/5: Removing obsolete packages"
apt-get -y --purge autoremove
apt-get -y autoclean

# ── Result + reboot prompt ───────────────────────────────────
NEW_PRETTY="$(. /etc/os-release; echo "${PRETTY_NAME:-unknown}")"
section "Upgrade complete"
log "Now running: ${NEW_PRETTY}"
log "Source backups: ${BACKUP_DIR}"
warn "Review kept configs: find / -name '*.dpkg-dist' 2>/dev/null"

if [ "$ASSUME_YES" -eq 1 ]; then
    warn "A reboot is required to finish the upgrade. Reboot manually: systemctl reboot"
else
    read -r -p "Reboot now to finish the upgrade? (j/N): " r
    case "${r,,}" in
        j|ja|y|yes) log "Rebooting..."; systemctl reboot ;;
        *) warn "Reboot skipped — remember to reboot soon: systemctl reboot" ;;
    esac
fi
