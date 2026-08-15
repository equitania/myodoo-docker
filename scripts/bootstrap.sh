#!/bin/bash
# bootstrap.sh — Out-of-the-box initializer for fresh Debian/Ubuntu servers
# Version 1.14.0 — 15.08.2026
#
# Supported: Debian 12 (bookworm) / 13 (trixie); Ubuntu 20.04/22.04/24.04/26.04
# (focal/jammy/noble/resolute). OS + codename are auto-detected from os-release;
# Docker and nginx.org repos exist for all of these. Repos for a codename an
# upstream does not (yet) serve are skipped / fall back to the distro package.
#
# Prepares a clean host so the myodoo-docker tooling can run:
#   1. Self-installs to /opt (so it stays available out-of-the-box)
#   2. Installs base packages (ca-certificates, curl, gnupg, git)
#      and ensures the en_US.UTF-8 locale is generated (minimal images)
#   3. Installs Docker CE from the official Docker repository (deb822 format)
#      and pins the classic overlay2 storage driver — FOR SPEED, which is not
#      the reason it was pinned before. Versions 1.7.0 to 1.12.0 pinned it as a
#      workaround for moby/moby#52431 (broken image export on the containerd
#      store); that justification was measured away on 14.08.2026, when five
#      2.2 GB builds on the containerd store came out correct.
#      The real Odoo build was then measured on 15.08.2026, same throwaway box,
#      Docker 29.7.2, 394 module archives pre-fetched exactly as
#      odoo_build_cache.py does in production:
#        cold build   overlay2 14s   containerd 37s   (2.6x)
#        export step  overlay2 3.5s  containerd 19.7s (5.6x)
#        warm build   overlay2  0-1s containerd 35-36s
#      The last line is the one that matters: on the containerd store the build
#      cache does not survive the `docker system prune -f` that
#      update_docker_odoo.py runs after every update, so every doup would be a
#      full rebuild. We get none of that store's benefits either — these images
#      are built locally, never pushed, single-platform, no attestations.
#      DOCKER_STORAGE_DRIVER="" leaves Docker's default in place.
#      What survives unconditionally is the check: a two-line image is built and
#      run after the install, because a daemon that exports images with no
#      filesystem passes every other check this script makes (one customer server,
#      14.08.2026).
#   4. Installs nginx from the official nginx.org repository (reverse proxy)
#      and hardens its systemd unit with two drop-ins: Restart=on-failure — the
#      nginx.org unit ships Restart=no, so a start that fails transiently (e.g.
#      while an apt upgrade swaps glibc/openssl underneath) leaves nginx down
#      until a human notices — and ExecReload via $MAINPID, because the stock
#      reload reads /run/nginx.pid, which `nginx -t` truncates to zero bytes
#      (the reload then fails and the OLD config silently stays live).
#      Applied to pre-existing installs too.
#   5. Installs certbot (Let's Encrypt client; renewal via ssl-renew.sh standalone)
#      and pins the distro's certbot.timer to a quiet 03:00 slot, clear of the
#      06:00-07:00 apt-daily-upgrade window (its stock randomized delay of up to
#      12h regularly drifts into it, and standalone renewals stop nginx)
#   6. Installs UFW (firewall — installed but NOT enabled, see below)
#   7. Installs fail2ban (baseline SSH brute-force protection)
#   8. Installs unattended-upgrades (automatic security updates)
#   9. Installs Python module deps the project's root-run scripts import
#      (python3-yaml, python3-dotenv) — via apt, NOT pip (PEP 668 compliant)
#  10. Clones the myodoo-docker repository and runs getScripts.py
#
# Security note: steps 6-8 provide a safe baseline immediately. UFW is installed
# but deliberately left DISABLED — enabling it with a default-deny policy before
# the SSH port + allowed IPs are known would lock you out. Full hardening (UFW
# enable + rules, custom SSH port, sysctl, auditd, ...) is applied later via
# `server_hardening.py --apply` once /root/.config/myodoo-docker/.env is filled in.
#
# Designed to be idempotent: safe to re-run. Existing installs are detected and
# skipped; no destructive operations (no `rm -rf`).
#
# Usage (on a fresh server, as root or via sudo):
#   # One-liner fetch + run (requires curl OR wget):
#   curl -fsSL https://raw.githubusercontent.com/equitania/myodoo-docker/2026/scripts/bootstrap.sh \
#     -o /opt/myodoo-bootstrap.sh && chmod +x /opt/myodoo-bootstrap.sh && /opt/myodoo-bootstrap.sh
#
#   # Or, if the repo is already cloned:
#   ./scripts/bootstrap.sh
#
# Environment overrides:
#   REPO_BRANCH=2026          Branch of myodoo-docker to clone
#   REPO_URL=...              Repository URL
#   INSTALL_NGINX=1           Install host nginx (set 0 to skip)
#   INSTALL_CERTBOT=1         Install certbot Let's Encrypt client (set 0 to skip)
#   INSTALL_DOCKER=1          Install Docker CE   (set 0 to skip)
#   INSTALL_UFW=1             Install UFW firewall, disabled (set 0 to skip)
#   INSTALL_FAIL2BAN=1        Install fail2ban baseline (set 0 to skip)
#   INSTALL_UNATTENDED=1      Install unattended-upgrades (set 0 to skip)
#   INSTALL_PYTHON_DEPS=1     Install python3-yaml + python3-dotenv (set 0 to skip)
#   RUN_GETSCRIPTS=1          Run getScripts.py at the end (set 0 to skip)
#   SELF_INSTALL=1            Copy this script to /opt (set 0 to skip)
##############################################################################

# -E so the ERR trap fires inside functions; -e -u -o pipefail for strictness.
set -Eeuo pipefail

# ──────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────

SCRIPT_VERSION="1.14.0"
SCRIPT_DATE="15.08.2026"

REPO_URL="${REPO_URL:-https://github.com/equitania/myodoo-docker.git}"
REPO_BRANCH="${REPO_BRANCH:-2026}"

INSTALL_DOCKER="${INSTALL_DOCKER:-1}"
INSTALL_NGINX="${INSTALL_NGINX:-1}"
INSTALL_CERTBOT="${INSTALL_CERTBOT:-1}"
INSTALL_UFW="${INSTALL_UFW:-1}"
INSTALL_FAIL2BAN="${INSTALL_FAIL2BAN:-1}"
INSTALL_UNATTENDED="${INSTALL_UNATTENDED:-1}"
INSTALL_PYTHON_DEPS="${INSTALL_PYTHON_DEPS:-1}"
# Build a two-line image and run it, to prove the daemon produces images that
# actually contain files. Costs one busybox pull. Set to 0 on a host without a
# route to a registry, where the test can only report a network fault.
DOCKER_SMOKE_TEST="${DOCKER_SMOKE_TEST:-1}"
# overlay2, for speed — measured on 15.08.2026, see the header. Set to an empty
# string to leave Docker's own default (the containerd image store) alone.
DOCKER_STORAGE_DRIVER="${DOCKER_STORAGE_DRIVER-overlay2}"
RUN_GETSCRIPTS="${RUN_GETSCRIPTS:-1}"
SELF_INSTALL="${SELF_INSTALL:-1}"

INSTALL_PATH="/opt/myodoo-bootstrap.sh"

export DEBIAN_FRONTEND=noninteractive

SEPARATOR="────────────────────────────────────────────────────────"

# Colors (disabled when stdout is not a terminal)
if [ -t 1 ]; then
    C_RED="$(printf '\033[0;31m')"
    C_GREEN="$(printf '\033[0;32m')"
    C_YELLOW="$(printf '\033[1;33m')"
    C_BLUE="$(printf '\033[0;34m')"
    C_NC="$(printf '\033[0m')"
else
    C_RED="" ; C_GREEN="" ; C_YELLOW="" ; C_BLUE="" ; C_NC=""
fi

# ──────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────

log()      { echo "${C_GREEN}$(date '+%Y-%m-%d %H:%M:%S')${C_NC} | $*"; }
warn()     { echo "${C_YELLOW}$(date '+%Y-%m-%d %H:%M:%S') | WARN:${C_NC} $*" >&2; }
err()      { echo "${C_RED}$(date '+%Y-%m-%d %H:%M:%S') | ERROR:${C_NC} $*" >&2; }
die()      { err "$*"; exit 1; }

section() {
    echo ""
    echo "${C_BLUE}${SEPARATOR}${C_NC}"
    log "$*"
    echo "${C_BLUE}${SEPARATOR}${C_NC}"
}

# Report the failing command + line on any unexpected error (set -e).
on_error() {
    local exit_code=$?
    err "Aborted at line ${BASH_LINENO[0]} (exit ${exit_code}): ${BASH_COMMAND}"
    exit "${exit_code}"
}
trap on_error ERR

# ──────────────────────────────────────────
# Privilege handling
# ──────────────────────────────────────────

# Resolve a privilege-escalation prefix. Empty when already root.
SUDO=""
resolve_privilege() {
    if [ "$(id -u)" -eq 0 ]; then
        SUDO=""
    elif command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
        log "Not running as root — using sudo for privileged operations."
    else
        die "This script needs root privileges, but neither root nor sudo is available. Re-run as root."
    fi
}

# Write stdin to a (possibly root-owned) file via tee.
write_file() {
    local path="$1"
    $SUDO tee "$path" >/dev/null
}

# Resolve the target user/home that will own the cloned repo and run getScripts.py.
# When invoked via sudo we target the original (non-root) user where possible.
TARGET_USER=""
TARGET_HOME=""
resolve_target_user() {
    if [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
        TARGET_USER="${SUDO_USER}"
        TARGET_HOME="$(getent passwd "${SUDO_USER}" | cut -d: -f6)"
    else
        TARGET_USER="$(id -un)"
        TARGET_HOME="${HOME}"
    fi
    [ -n "${TARGET_HOME}" ] || TARGET_HOME="/root"
    log "Target user: ${TARGET_USER} (home: ${TARGET_HOME})"
}

# Run a command as the target user (handles both root and sudo invocations).
run_as_target() {
    if [ "$(id -un)" = "${TARGET_USER}" ]; then
        "$@"
    else
        $SUDO -u "${TARGET_USER}" -H "$@"
    fi
}

# ──────────────────────────────────────────
# Steps
# ──────────────────────────────────────────

self_install() {
    [ "${SELF_INSTALL}" = "1" ] || { log "Self-install disabled — skipping."; return 0; }

    local source_path
    source_path="$(readlink -f "$0" 2>/dev/null || echo "$0")"

    if [ "${source_path}" = "${INSTALL_PATH}" ]; then
        log "Already running from ${INSTALL_PATH}."
        return 0
    fi

    section "Self-installing bootstrap script to ${INSTALL_PATH}"
    $SUDO install -m 0755 "${source_path}" "${INSTALL_PATH}"
    log "Installed: ${INSTALL_PATH} (executable). Re-run any time with: ${INSTALL_PATH}"
}

detect_os() {
    [ -r /etc/os-release ] || die "/etc/os-release not found — unsupported system."
    # shellcheck disable=SC1091
    . /etc/os-release
    OS_ID="${ID:-unknown}"
    OS_CODENAME="${VERSION_CODENAME:-}"
    ARCH="$(dpkg --print-architecture)"

    case "${OS_ID}" in
        debian|ubuntu) : ;;  # supported — Docker & nginx.org serve both
        *) warn "Detected '${OS_ID}', not debian/ubuntu. Continuing, but only debian/ubuntu are supported." ;;
    esac
    [ -n "${OS_CODENAME}" ] || die "Could not determine OS codename (VERSION_CODENAME)."
    log "OS: ${OS_ID} ${OS_CODENAME} (${ARCH})"
}

# Return 0 if the given apt repo base URL serves a Release file for the current
# codename — used to skip/fallback gracefully on codenames an upstream lacks.
repo_serves_codename() {
    local base_url="$1"
    curl -fsSL -o /dev/null "${base_url}/dists/${OS_CODENAME}/Release" 2>/dev/null
}

apt_update() {
    log "Running apt-get update..."
    $SUDO apt-get update -qq
}

# Resolve a pre-existing Docker apt conflict BEFORE the first apt-get update.
# A failed earlier run (or a manual mix) can leave BOTH the legacy one-line
# docker.list (Signed-By=docker.gpg) AND a deb822 docker.sources (docker.asc)
# on disk → 'E: Conflicting values set for option Signed-By' breaks every
# apt-get update. The legacy .list is what the working Docker was installed
# with, so drop the deb822 file we (previously) added and keep the .list.
reconcile_docker_repo() {
    local sources="/etc/apt/sources.list.d/docker.sources"
    local legacy="/etc/apt/sources.list.d/docker.list"
    if [ -f "${sources}" ] && [ -f "${legacy}" ]; then
        warn "Both docker.sources and docker.list present (Signed-By conflict)."
        warn "Removing docker.sources, keeping the pre-existing docker.list."
        $SUDO rm -f "${sources}"
    fi
}

install_base_packages() {
    section "Installing base packages (ca-certificates, curl, gnupg, git)"
    apt_update
    $SUDO apt-get install -y ca-certificates curl gnupg git
    log "Base packages installed. git: $(git --version 2>/dev/null || echo 'n/a')"
}

setup_locale() {
    section "Ensuring UTF-8 locale (en_US.UTF-8)"
    # Minimal cloud images (e.g. IONOS) ship without generated locales while
    # SSH forwards LANG/LC_ALL=en_US.UTF-8 — perl/apt then warn on every call.
    if locale -a 2>/dev/null | grep -qiE '^en_US\.utf-?8$'; then
        log "Locale en_US.UTF-8 already available — skipping."
        return 0
    fi
    $SUDO apt-get install -y locales
    if [ -f /etc/locale.gen ]; then
        $SUDO sed -i 's/^# *en_US\.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen
        grep -q '^en_US\.UTF-8 UTF-8' /etc/locale.gen || \
            echo "en_US.UTF-8 UTF-8" | $SUDO tee -a /etc/locale.gen > /dev/null
    fi
    $SUDO locale-gen
    $SUDO update-locale LANG=en_US.UTF-8
    log "Locale en_US.UTF-8 generated and set as default."
}

# Pin a storage driver in /etc/docker/daemon.json, whatever else the file may
# already contain. Only called when DOCKER_STORAGE_DRIVER is set — the default
# is to leave Docker's own choice alone (see the 14.08.2026 A/B test).
#
# Why it merges rather than skipping: daemon.json exists on plenty of hosts for
# reasons that have nothing to do with the storage driver — log-opts, a registry
# mirror, a DNS list. Writing only when the file is absent meant every one of
# those hosts silently kept whatever driver it had while the install log said
# nothing. One server behaving unlike all the others is exactly the shape of
# fault that costs a day to find.
#
# Only the storage-driver key is touched. A file that already names a DIFFERENT
# driver is left alone and reported: overriding a deliberate choice unattended
# is worse than any bug this could be guarding against.
ensure_storage_driver_pin() {
    local wanted="${1:?driver name}"
    # Overridable so the merge logic can be tested against a temp file rather
    # than against the machine running the suite. Never set in normal use.
    local file="${DOCKER_DAEMON_JSON:-/etc/docker/daemon.json}"

    if [ ! -f "${file}" ]; then
        $SUDO install -m 0755 -d "$(dirname "${file}")"
        printf '{\n  "storage-driver": "%s"\n}\n' "${wanted}" | write_file "${file}"
        log "Pinned storage-driver ${wanted} in ${file}."
        return 0
    fi

    local current
    current="$(python3 - "${file}" <<'PY' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        print(json.load(handle).get("storage-driver", ""))
except Exception:
    sys.exit(1)
PY
)" || {
        warn "${file} exists but could not be read as JSON — leaving it untouched."
        warn "Add '\"storage-driver\": \"${wanted}\"' by hand once the file parses again."
        return 0
    }

    if [ "${current}" = "${wanted}" ]; then
        log "${file} already pins storage-driver ${wanted}."
        return 0
    fi
    if [ -n "${current}" ]; then
        warn "${file} pins storage-driver '${current}', not '${wanted}' — left untouched."
        warn "That is a deliberate choice this script will not override unattended."
        return 0
    fi

    # Present, valid, and says nothing about the storage driver: add the key and
    # keep every other setting byte for byte. Written to a temp file first so a
    # failure leaves the original in place rather than a half-written daemon.json,
    # which would stop docker from starting at all.
    local merged
    merged="$(python3 - "${file}" "${wanted}" <<'PY' 2>/dev/null
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
data["storage-driver"] = sys.argv[2]
print(json.dumps(data, indent=2))
PY
)" || {
        warn "Could not merge the storage-driver pin into ${file} — add"
        warn "'\"storage-driver\": \"${wanted}\"' by hand."
        return 0
    }
    printf '%s\n' "${merged}" | write_file "${file}"
    log "Added storage-driver ${wanted} to the existing ${file}, other settings kept."
}

# Report the driver that is actually in effect, and say so when a requested pin
# did not take. "We wrote the file" is not "it is in effect": a daemon.json that
# lands after the daemon's first start, a typo in it, or a hand-edit never
# followed by a restart all leave the pin inert.
report_storage_driver() {
    command -v docker >/dev/null 2>&1 || return 0
    local driver
    driver="$($SUDO docker info --format '{{.Driver}}' 2>/dev/null || echo "")"
    if [ -z "${driver}" ]; then
        warn "Could not read the storage driver from 'docker info' — verify by hand."
        return 0
    fi
    log "Storage driver in effect: ${driver}."
    if [ "${driver}" = "overlayfs" ]; then
        warn "This host uses the containerd image store. Measured on 15.08.2026 for a"
        warn "real Odoo build: 2.6x slower cold (37s vs 14s), and the build cache does"
        warn "not survive the 'docker system prune -f' that doup runs, so every update"
        warn "is a full rebuild (35s vs 1s). Switching is not done here because it"
        warn "hides existing images until a restart and a reboot. To switch by hand:"
        warn "  /etc/docker/daemon.json -> {\"storage-driver\": \"overlay2\"}"
        warn "  docker builder prune -af · systemctl restart docker · REBOOT"
        warn "  then re-pull images and recreate containers (volumes survive)."
    fi
    if [ -n "${DOCKER_STORAGE_DRIVER}" ] && [ "${driver}" != "${DOCKER_STORAGE_DRIVER}" ]; then
        warn "You asked for '${DOCKER_STORAGE_DRIVER}' but the LIVE driver is '${driver}'."
        warn "The pin has not taken effect. Restart docker, then REBOOT the server"
        warn "(orphaned mounts of the previous store otherwise cause non-deterministic"
        warn "image exports), then re-pull images and recreate containers."
    fi
}

# Prove the daemon can produce an image that contains files.
#
# This exists because a Docker host can build, tag and report success for an
# image with no filesystem at all — not even /bin/sh. Every other check in this
# script passes on such a host; the fault surfaces days later as an Odoo
# container restart-looping on `exec /app/bin/boot: no such file or directory`,
# which reads like a Dockerfile bug. Sixty seconds here against an afternoon
# there. Observed on one customer server on 16.07.2026 and 14.08.2026; the cause is NOT
# established — the A/B test of 14.08.2026 cleared the containerd image store,
# so this check makes no claim about why, only that it happened.
#
# KNOWN LIMIT: a two-line image is a coarse probe. The July observation on
# one customer server was that a 1-layer image built fine while the 22-layer Odoo image did
# not, so a size- or layer-dependent fault would pass here. It catches a
# comprehensively broken daemon, not a selectively broken one.
#
# Never fatal: an unreachable registry is not a broken daemon, and the wording
# says so. The only thing removed is the tag built three lines above, by a name
# chosen here — nothing pre-existing is touched.
verify_docker_can_build() {
    [ "${DOCKER_SMOKE_TEST}" = "1" ] || { log "Docker smoke test disabled — skipping."; return 0; }
    command -v docker >/dev/null 2>&1 || return 0

    local tag="ownerp-bootstrap-check"
    local dir
    dir="$(mktemp -d)" || return 0
    printf 'FROM busybox\nRUN touch /ownerp-marker\n' > "${dir}/Dockerfile"

    if ! $SUDO docker build -q -t "${tag}" "${dir}" >/dev/null 2>&1; then
        warn "Smoke test: docker could not build a two-line image. Either this host has"
        warn "no route to a registry, or the daemon is broken — check with:"
        warn "  docker build -t ${tag} ${dir}"
    elif ! $SUDO docker run --rm --entrypoint /bin/sh "${tag}" -c 'test -f /ownerp-marker' >/dev/null 2>&1; then
        warn "Smoke test: the image built here has NO FILESYSTEM. Every build on this"
        warn "host will produce a container that dies with 'no such file or directory'."
        warn "First step:"
        warn "  docker builder prune -af   then rebuild; if it recurs, reboot the server"
        warn "  (dmesg -T | grep -i overlayfs shows overlapping mounts)."
    else
        log "Smoke test: docker builds a usable image."
    fi

    $SUDO docker rmi -f "${tag}" >/dev/null 2>&1 || true
    rm -rf "${dir}"
}

install_docker() {
    [ "${INSTALL_DOCKER}" = "1" ] || { log "Docker install disabled — skipping."; return 0; }

    section "Installing Docker CE (official repository)"

    # If Docker is already installed, do NOT touch the apt repo/keyring. Existing
    # hosts often use the legacy one-line docker.list with Signed-By=docker.gpg;
    # adding our deb822 docker.sources with docker.asc on top triggers
    # 'E: Conflicting values set for option Signed-By' and breaks apt update.
    # Just make sure the service is enabled and move on.
    if command -v docker >/dev/null 2>&1; then
        log "Docker already present: $(docker --version). Leaving apt repo untouched."
        # Deliberately no storage-driver change on a running host: switching a
        # LIVE store makes existing images and containers invisible until a
        # restart and a reboot. report_storage_driver() points out what it
        # costs and leaves the decision, and the timing of it, to a human.
        if command -v systemctl >/dev/null 2>&1; then
            $SUDO systemctl enable --now docker 2>/dev/null || true
        fi
        report_storage_driver
        # Run the smoke test here too. This branch is what `--harden` takes on an
        # existing server, and an existing server is precisely where a daemon
        # that exports hollow images has had time to start doing so.
        verify_docker_can_build
        return 0
    fi

    local docker_base="https://download.docker.com/linux/${OS_ID}"
    if ! repo_serves_codename "${docker_base}"; then
        warn "Docker has no repo for ${OS_ID}/${OS_CODENAME} (yet) — skipping Docker install."
        return 0
    fi

    # Remove a stale legacy one-line repo to avoid a dual-definition conflict
    # with the deb822 file we are about to write.
    if [ -f /etc/apt/sources.list.d/docker.list ]; then
        warn "Removing stale /etc/apt/sources.list.d/docker.list (replaced by docker.sources)."
        $SUDO rm -f /etc/apt/sources.list.d/docker.list
    fi

    # Add Docker's official GPG key (deb822 keyring).
    $SUDO install -m 0755 -d /etc/apt/keyrings
    $SUDO curl -fsSL "${docker_base}/gpg" -o /etc/apt/keyrings/docker.asc
    $SUDO chmod a+r /etc/apt/keyrings/docker.asc

    # Add the repository in deb822 format.
    write_file /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: ${docker_base}
Suites: ${OS_CODENAME}
Components: stable
Architectures: ${ARCH}
Signed-By: /etc/apt/keyrings/docker.asc
EOF

    # Docker's own default storage driver is used unless one is asked for. If a
    # driver IS requested, the pin has to land BEFORE the package postinst
    # starts dockerd for the first time — a pin applied afterwards needs a
    # restart and a reboot to take effect, and leaves orphaned mounts of the
    # previous store behind in the meantime.
    if [ -n "${DOCKER_STORAGE_DRIVER}" ]; then
        ensure_storage_driver_pin "${DOCKER_STORAGE_DRIVER}"
    fi

    apt_update
    $SUDO apt-get install -y \
        docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin

    # Enable + start the Docker service when systemd is available.
    if command -v systemctl >/dev/null 2>&1; then
        $SUDO systemctl enable --now docker
        log "Docker service enabled and started."
    fi

    report_storage_driver

    # Allow the (non-root) target user to use Docker without sudo.
    if [ "${TARGET_USER}" != "root" ]; then
        $SUDO usermod -aG docker "${TARGET_USER}" || warn "Could not add ${TARGET_USER} to docker group."
        warn "${TARGET_USER} added to 'docker' group — re-login required for it to take effect."
    fi

    log "Docker installed: $(docker --version 2>/dev/null || echo 'n/a')"
    verify_docker_can_build
}

# Install the two systemd drop-ins the nginx.org unit needs.
#
# (1) Restart=on-failure — restart nginx when a start FAILS.
#
# Background: the nginx.org unit ships `Restart=no`. Observed twice within two
# days on a release server (29./31.07.2026): apt-daily-upgrade replaced glibc
# resp. openssl, something restarted nginx mid-swap (needrestart in one case, the
# certbot pre-hook in the other), the start failed because the binary could not
# load the library being replaced — and nothing ever tried again. A three-second
# library swap became an outage lasting hours.
#
# StartLimitBurst/IntervalSec keep this bounded: a genuinely broken config still
# gives up after 5 attempts within 5 minutes and stays down visibly, instead of
# restart-looping forever and hiding the real error.
#
# (2) ExecReload via $MAINPID — make `systemctl reload nginx` reliable.
#
# The nginx.org unit reloads with `kill -s HUP $(cat /run/nginx.pid)`, but any
# preceding `nginx -t` truncates that pid file to zero bytes. The command then
# expands to a bare `kill -s HUP`, which exits with kill's usage text: the reload
# reports failure, and — far worse — the OLD config stays live while the new one
# looks deployed. Reading the pid from systemd instead removes the dependency on
# a file another command is free to clobber.
#
# The empty `ExecReload=` reset line is mandatory: without it systemd APPENDS
# this command to the unit's original one instead of replacing it, and the
# broken `kill` would still run first.
harden_nginx_service() {
    command -v systemctl >/dev/null 2>&1 || return 0

    $SUDO mkdir -p /etc/systemd/system/nginx.service.d
    printf '%s\n' \
        '# Managed by bootstrap.sh — nginx must survive a transient failed start.' \
        '[Unit]' \
        'StartLimitIntervalSec=300' \
        'StartLimitBurst=5' \
        '' \
        '[Service]' \
        'Restart=on-failure' \
        'RestartSec=10' \
        | write_file /etc/systemd/system/nginx.service.d/10-restart.conf

    printf '%s\n' \
        '# Managed by bootstrap.sh — reload from systemd MainPID, not /run/nginx.pid,' \
        '# which `nginx -t` truncates to zero bytes.' \
        '[Service]' \
        'ExecReload=' \
        'ExecReload=/bin/kill -s HUP $MAINPID' \
        | write_file /etc/systemd/system/nginx.service.d/10-reload-mainpid.conf

    $SUDO systemctl daemon-reload
    log "nginx: Restart=on-failure drop-in installed (recovers from a failed start in 10s)."
    log "nginx: ExecReload pinned to \$MAINPID (reload no longer breaks after 'nginx -t')."
}

# Pin the distro certbot.timer to a quiet slot.
#
# The Debian/Ubuntu certbot package ships an ENABLED certbot.timer whose
# RandomizedDelaySec spans up to 12h — which is how it ended up firing at 06:51,
# right inside the apt-daily-upgrade window. Since renewals authenticate via
# standalone, every renewal stops nginx; colliding with a library swap is exactly
# what took nginx down. A fixed 03:00-03:30 slot keeps the two apart.
#
# The empty `OnCalendar=` line is REQUIRED: without it systemd ADDS this schedule
# to the unit's original one rather than replacing it, and the timer would keep
# firing in the apt window as well.
harden_certbot_timer() {
    command -v systemctl >/dev/null 2>&1 || return 0
    # Only the distro package provides certbot.timer; a snap install uses a
    # different unit name and is left alone.
    $SUDO systemctl list-unit-files certbot.timer >/dev/null 2>&1 || {
        log "certbot.timer not present — leaving renewal scheduling untouched."
        return 0
    }

    $SUDO mkdir -p /etc/systemd/system/certbot.timer.d
    printf '%s\n' \
        '# Managed by bootstrap.sh — keep renewals out of the apt-upgrade window.' \
        '[Timer]' \
        'OnCalendar=' \
        'OnCalendar=*-*-* 03:00:00' \
        'RandomizedDelaySec=1800' \
        | write_file /etc/systemd/system/certbot.timer.d/10-offpeak.conf

    $SUDO systemctl daemon-reload
    $SUDO systemctl restart certbot.timer 2>/dev/null || true
    log "certbot.timer pinned to 03:00-03:30 (clear of the 06:00-07:00 apt window)."
}

install_nginx() {
    [ "${INSTALL_NGINX}" = "1" ] || { log "nginx install disabled — skipping."; return 0; }

    section "Installing nginx (official nginx.org repository)"

    # Like Docker: if nginx is already installed, leave the apt repo alone to
    # avoid a Signed-By conflict with a pre-existing nginx.list. Just ensure the
    # service is up.
    if command -v nginx >/dev/null 2>&1; then
        log "nginx already present: $(nginx -v 2>&1). Leaving apt repo untouched."
        if command -v systemctl >/dev/null 2>&1; then
            $SUDO systemctl enable --now nginx 2>/dev/null || true
        fi
        # Pre-existing installs need the hardening just as much — arguably more,
        # since they are the ones already carrying production traffic.
        harden_nginx_service
        return 0
    fi

    local nginx_base="https://nginx.org/packages/${OS_ID}"
    if repo_serves_codename "${nginx_base}"; then
        # Import the nginx signing key into a dedicated keyring (gpg comes from
        # the base 'gnupg' package installed earlier).
        local tmp_key
        tmp_key="$(mktemp)"
        curl -fsSL https://nginx.org/keys/nginx_signing.key | gpg --dearmor --yes -o "${tmp_key}"
        $SUDO install -m 0644 "${tmp_key}" /usr/share/keyrings/nginx-archive-keyring.gpg
        rm -f "${tmp_key}"

        echo "deb [signed-by=/usr/share/keyrings/nginx-archive-keyring.gpg] ${nginx_base} ${OS_CODENAME} nginx" \
            | write_file /etc/apt/sources.list.d/nginx.list
        log "Using official nginx.org repo (${OS_ID}/${OS_CODENAME})."
    else
        warn "nginx.org has no repo for ${OS_ID}/${OS_CODENAME} — falling back to the distro nginx package."
        $SUDO rm -f /etc/apt/sources.list.d/nginx.list
    fi

    apt_update
    $SUDO apt-get install -y nginx

    if command -v systemctl >/dev/null 2>&1; then
        $SUDO systemctl enable --now nginx
        log "nginx service enabled and started."
    fi

    harden_nginx_service

    log "nginx installed: $(nginx -v 2>&1 || echo 'n/a')"
}

install_certbot() {
    [ "${INSTALL_CERTBOT}" = "1" ] || { log "certbot install disabled — skipping."; return 0; }

    section "Installing certbot (Let's Encrypt client)"

    if command -v certbot >/dev/null 2>&1; then
        log "certbot already present: $(certbot --version 2>&1 || echo 'n/a'). Skipping install."
        # An existing certbot still has the stock timer schedule — pin it.
        harden_certbot_timer
        return 0
    fi

    # The distro 'certbot' package lands at /usr/bin/certbot, which the project's
    # ssl-renew.sh already looks for. Renewal here is STANDALONE (ssl-renew.sh
    # stops nginx, runs `certbot renew`, restarts nginx), so the nginx plugin is
    # intentionally NOT installed — it would only add an unused authenticator.
    $SUDO apt-get install -y certbot

    harden_certbot_timer

    log "certbot installed: $(certbot --version 2>&1 || echo 'n/a')"
    log "  Issue certs with: certbot certonly --standalone -d <domain> (stop nginx first)."
    log "  Automatic renewal is handled by scripts/ssl-renew.sh (cron, standalone mode)."
    log "  The package's own certbot.timer is pinned to 03:00 to avoid the apt window."
}

install_ufw() {
    [ "${INSTALL_UFW}" = "1" ] || { log "UFW install disabled — skipping."; return 0; }

    section "Installing UFW firewall (installed, left DISABLED)"

    $SUDO apt-get install -y ufw

    # IMPORTANT: do NOT enable UFW here. Enabling with a default-deny incoming
    # policy before SSH is allowed would lock out the current session. UFW is
    # enabled (with the correct SSH port + allowed IPs) later by:
    #   server_hardening.py --apply --module ufw
    if command -v ufw >/dev/null 2>&1; then
        local ufw_state
        ufw_state="$($SUDO ufw status 2>/dev/null | head -n1 || true)"
        log "UFW installed (${ufw_state:-status unknown}). Left DISABLED on purpose —"
        log "  enable it via: server_hardening.py --apply --module ufw"
    fi
}

install_fail2ban() {
    [ "${INSTALL_FAIL2BAN}" = "1" ] || { log "fail2ban install disabled — skipping."; return 0; }

    section "Installing fail2ban (baseline SSH protection)"

    # python3-systemd is required for the systemd journal backend used below.
    $SUDO apt-get install -y fail2ban python3-systemd

    # Write a SAFE baseline jail.local ONLY when none exists yet, so we never
    # clobber the authoritative config that server_hardening.py writes later.
    # Baseline uses port 'ssh' (fresh server still on 22) and the Debian default
    # banaction (nftables) so it works before UFW is configured.
    local jail_local="/etc/fail2ban/jail.local"
    if [ -e "${jail_local}" ]; then
        log "${jail_local} already exists — leaving it untouched (managed elsewhere)."
    else
        log "Writing baseline ${jail_local}..."
        write_file "${jail_local}" <<'EOF'
# Managed by bootstrap.sh (baseline) — replaced by server_hardening.py --apply
[DEFAULT]
ignoreip = 127.0.0.1/8 ::1
bantime  = 3600
findtime = 600
maxretry = 5

[sshd]
enabled  = true
port     = ssh
backend  = systemd
maxretry = 5
bantime  = 86400
EOF
    fi

    if command -v systemctl >/dev/null 2>&1; then
        $SUDO systemctl enable --now fail2ban
        log "fail2ban service enabled and started."
    fi

    log "fail2ban baseline active. Full config later via: server_hardening.py --apply"
}

install_unattended_upgrades() {
    [ "${INSTALL_UNATTENDED}" = "1" ] || { log "unattended-upgrades disabled — skipping."; return 0; }

    section "Installing unattended-upgrades (automatic security updates)"

    $SUDO apt-get install -y unattended-upgrades apt-listchanges

    # Enable periodic update + unattended upgrade runs. Origins default to the
    # Debian security suite (no extra config needed for security-only updates).
    write_file /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "7";
EOF

    if command -v systemctl >/dev/null 2>&1; then
        $SUDO systemctl enable --now unattended-upgrades 2>/dev/null \
            || warn "Could not enable unattended-upgrades service (timer may still run)."
    fi

    log "unattended-upgrades configured for automatic security updates."
}

install_python_deps() {
    [ "${INSTALL_PYTHON_DEPS}" = "1" ] || { log "Python deps install disabled — skipping."; return 0; }

    section "Installing Python module deps (python3-yaml, python3-dotenv)"

    # The project's root-run scripts import these third-party modules:
    #   server_hardening.py  -> yaml, dotenv
    #   nginx-cert-guard.py  -> dotenv
    #   container2backup.py  -> yaml, dotenv
    # Install them via apt (system python3), NOT pip: modern Debian/Ubuntu mark
    # the system interpreter externally-managed (PEP 668), so `pip install` as
    # root fails. apt is the supported, conflict-free path. Without dotenv the
    # hardening script silently ignores /root/.config/myodoo-docker/.env and
    # builds wrong UFW/SSH rules.
    $SUDO apt-get install -y python3-yaml python3-dotenv

    # Verify the modules import in the system interpreter that runs the scripts.
    if python3 -c "import yaml, dotenv" 2>/dev/null; then
        log "Python deps OK: yaml + dotenv importable by system python3."
    else
        warn "python3-yaml / python3-dotenv installed but import check failed — verify python3."
    fi
}

clone_repo_and_run_getscripts() {
    [ "${RUN_GETSCRIPTS}" = "1" ] || { log "getScripts.py step disabled — skipping."; return 0; }

    section "Cloning myodoo-docker and running getScripts.py"

    local repo_dir="${TARGET_HOME}/myodoo-docker"

    if [ -d "${repo_dir}/.git" ]; then
        log "Repository already present at ${repo_dir} — updating (branch ${REPO_BRANCH})."
        run_as_target git -C "${repo_dir}" fetch --quiet origin "${REPO_BRANCH}"
        run_as_target git -C "${repo_dir}" checkout "${REPO_BRANCH}"
        run_as_target git -C "${repo_dir}" pull --quiet --ff-only origin "${REPO_BRANCH}"
    else
        log "Cloning ${REPO_URL} (branch ${REPO_BRANCH}) into ${repo_dir}..."
        run_as_target git clone -b "${REPO_BRANCH}" "${REPO_URL}" "${repo_dir}"
    fi

    # Stage getScripts.py in the target user's home, mirroring the documented flow.
    run_as_target cp "${repo_dir}/getScripts.py" "${TARGET_HOME}/getScripts.py"
    run_as_target chmod +x "${TARGET_HOME}/getScripts.py"

    log "Running getScripts.py as ${TARGET_USER}..."
    run_as_target python3 "${TARGET_HOME}/getScripts.py"
}

print_summary() {
    section "Bootstrap complete"
    echo "${C_GREEN}System prepared successfully.${C_NC}"
    echo ""
    echo "  • Bootstrap script parked at : ${INSTALL_PATH}"
    [ "${INSTALL_DOCKER}" = "1" ]    && echo "  • Docker                     : $(docker --version 2>/dev/null || echo 'see logs')"
    [ "${INSTALL_NGINX}" = "1" ]     && echo "  • nginx                      : $(nginx -v 2>&1 || echo 'see logs')"
    [ "${INSTALL_CERTBOT}" = "1" ]   && echo "  • certbot                    : $(certbot --version 2>&1 || echo 'see logs') (renew via ssl-renew.sh)"
    [ "${INSTALL_UFW}" = "1" ]       && echo "  • UFW                        : installed, DISABLED (enable via server_hardening.py)"
    [ "${INSTALL_FAIL2BAN}" = "1" ]  && echo "  • fail2ban                   : baseline sshd jail active"
    [ "${INSTALL_UNATTENDED}" = "1" ] && echo "  • unattended-upgrades        : automatic security updates enabled"
    [ "${INSTALL_PYTHON_DEPS}" = "1" ] && echo "  • Python module deps         : python3-yaml + python3-dotenv (apt)"
    echo "  • Repository                 : ${TARGET_HOME}/myodoo-docker (branch ${REPO_BRANCH})"
    echo ""
    echo "${C_YELLOW}Next steps:${C_NC}"
    echo "  • Start the Fish shell:  exec fish"
    echo "    (Do NOT 'source' the Fish config from bash — it uses Fish syntax.)"
    echo "  • getScripts.py has configured Fish and offered to set it as your default shell."
    echo "  • Apply full hardening: fill /root/.config/myodoo-docker/.env, then run"
    echo "    'sudo python3 ${TARGET_HOME}/myodoo-docker/scripts/server_hardening.py' (audit),"
    echo "    then add --apply.  See --help for what each module changes."
    echo "  • Set up maintenance cron (after configuring container2backup.yaml):"
    echo "    'sudo ${TARGET_HOME}/setup-maintenance-cron.sh' (backup + cert renewal + DSGVO weblog purge)."
    echo "  • Deploy the nginx base files BEFORE creating vhosts (so 'include nginxconfig.io/...'"
    echo "    never fails): 'sudo ${TARGET_HOME}/deploy-nginx-base.sh'."
    echo "  • Re-run this bootstrap any time with: ${INSTALL_PATH}"
    echo ""
}

# ──────────────────────────────────────────
# Main
# ──────────────────────────────────────────

main() {
    # --harden runs only the two systemd hardening steps. It exists so a report
    # like server-readiness.py can name ONE short command instead of printing a
    # multi-line printf that has to survive copy & paste through a terminal.
    case "${1:-}" in
        --harden)
            section "myodoo-docker Bootstrap v${SCRIPT_VERSION} — hardening only"
            resolve_privilege
            harden_nginx_service
            harden_certbot_timer
            log "Hardening applied. Nothing else was touched."
            return 0
            ;;
        --help|-h)
            echo "Usage: $0 [--harden]"
            echo "  (no option)  full bootstrap: packages, Docker, nginx, certbot, hardening"
            echo "  --harden     only the nginx unit drop-ins and the certbot.timer pin"
            return 0
            ;;
        "") : ;;
        *)  die "Unknown option: $1 (use --harden or --help)" ;;
    esac

    section "myodoo-docker Bootstrap v${SCRIPT_VERSION} (${SCRIPT_DATE})"

    resolve_privilege
    resolve_target_user
    self_install
    detect_os
    reconcile_docker_repo
    install_base_packages
    setup_locale
    install_docker
    install_nginx
    install_certbot
    install_ufw
    install_fail2ban
    install_unattended_upgrades
    install_python_deps
    clone_repo_and_run_getscripts
    print_summary
}

# The guard exists so tests can source this file and exercise a single function
# without provisioning the machine they run on. It is never set in normal use.
if [ "${BOOTSTRAP_NO_MAIN:-0}" != "1" ]; then
    main "$@"
fi
