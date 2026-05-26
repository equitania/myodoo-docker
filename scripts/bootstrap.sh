#!/bin/bash
# bootstrap.sh — Out-of-the-box initializer for freshly installed Debian servers
# Version 1.1.0 — 26.05.2026
#
# Prepares a clean Debian host so the myodoo-docker tooling can run:
#   1. Self-installs to /opt (so it stays available out-of-the-box)
#   2. Installs base packages (ca-certificates, curl, gnupg, git)
#   3. Installs Docker CE from the official Docker repository (deb822 format)
#   4. Installs nginx from the official nginx.org repository (reverse proxy)
#   5. Installs fail2ban (baseline SSH brute-force protection)
#   6. Installs unattended-upgrades (automatic security updates)
#   7. Clones the myodoo-docker repository and runs getScripts.py
#
# Security note: steps 5-6 provide a safe baseline immediately. Full hardening
# (custom SSH port, UFW IP-allowlists, sysctl, auditd, ...) is applied later via
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
#   INSTALL_DOCKER=1          Install Docker CE   (set 0 to skip)
#   INSTALL_FAIL2BAN=1        Install fail2ban baseline (set 0 to skip)
#   INSTALL_UNATTENDED=1      Install unattended-upgrades (set 0 to skip)
#   RUN_GETSCRIPTS=1          Run getScripts.py at the end (set 0 to skip)
#   SELF_INSTALL=1            Copy this script to /opt (set 0 to skip)
##############################################################################

# -E so the ERR trap fires inside functions; -e -u -o pipefail for strictness.
set -Eeuo pipefail

# ──────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────

SCRIPT_VERSION="1.1.0"
SCRIPT_DATE="26.05.2026"

REPO_URL="${REPO_URL:-https://github.com/equitania/myodoo-docker.git}"
REPO_BRANCH="${REPO_BRANCH:-2026}"

INSTALL_DOCKER="${INSTALL_DOCKER:-1}"
INSTALL_NGINX="${INSTALL_NGINX:-1}"
INSTALL_FAIL2BAN="${INSTALL_FAIL2BAN:-1}"
INSTALL_UNATTENDED="${INSTALL_UNATTENDED:-1}"
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

    if [ "${OS_ID}" != "debian" ]; then
        warn "Detected '${OS_ID}', not 'debian'. Continuing, but this script targets Debian."
    fi
    [ -n "${OS_CODENAME}" ] || die "Could not determine Debian codename (VERSION_CODENAME)."
    log "OS: ${OS_ID} ${OS_CODENAME} (${ARCH})"
}

apt_update() {
    log "Running apt-get update..."
    $SUDO apt-get update -qq
}

install_base_packages() {
    section "Installing base packages (ca-certificates, curl, gnupg, git)"
    apt_update
    $SUDO apt-get install -y ca-certificates curl gnupg git
    log "Base packages installed. git: $(git --version 2>/dev/null || echo 'n/a')"
}

install_docker() {
    [ "${INSTALL_DOCKER}" = "1" ] || { log "Docker install disabled — skipping."; return 0; }

    section "Installing Docker CE (official repository)"

    if command -v docker >/dev/null 2>&1; then
        log "Docker already present: $(docker --version). Ensuring repo + service only."
    fi

    # Add Docker's official GPG key (deb822 keyring).
    $SUDO install -m 0755 -d /etc/apt/keyrings
    $SUDO curl -fsSL "https://download.docker.com/linux/${OS_ID}/gpg" -o /etc/apt/keyrings/docker.asc
    $SUDO chmod a+r /etc/apt/keyrings/docker.asc

    # Add the repository in deb822 format (Debian 13 / trixie style).
    write_file /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/${OS_ID}
Suites: ${OS_CODENAME}
Components: stable
Architectures: ${ARCH}
Signed-By: /etc/apt/keyrings/docker.asc
EOF

    apt_update
    $SUDO apt-get install -y \
        docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin

    # Enable + start the Docker service when systemd is available.
    if command -v systemctl >/dev/null 2>&1; then
        $SUDO systemctl enable --now docker
        log "Docker service enabled and started."
    fi

    # Allow the (non-root) target user to use Docker without sudo.
    if [ "${TARGET_USER}" != "root" ]; then
        $SUDO usermod -aG docker "${TARGET_USER}" || warn "Could not add ${TARGET_USER} to docker group."
        warn "${TARGET_USER} added to 'docker' group — re-login required for it to take effect."
    fi

    log "Docker installed: $(docker --version 2>/dev/null || echo 'n/a')"
}

install_nginx() {
    [ "${INSTALL_NGINX}" = "1" ] || { log "nginx install disabled — skipping."; return 0; }

    section "Installing nginx (official nginx.org repository)"

    if command -v nginx >/dev/null 2>&1; then
        log "nginx already present: $(nginx -v 2>&1). Ensuring repo only."
    fi

    $SUDO apt-get install -y gnupg2 ca-certificates lsb-release debian-archive-keyring

    # Import the nginx signing key into a dedicated keyring.
    local tmp_key
    tmp_key="$(mktemp)"
    curl -fsSL https://nginx.org/keys/nginx_signing.key | gpg --dearmor --yes -o "${tmp_key}"
    $SUDO install -m 0644 "${tmp_key}" /usr/share/keyrings/nginx-archive-keyring.gpg
    rm -f "${tmp_key}"

    # Add the stable nginx repository for the detected Debian codename.
    echo "deb [signed-by=/usr/share/keyrings/nginx-archive-keyring.gpg] https://nginx.org/packages/debian ${OS_CODENAME} nginx" \
        | write_file /etc/apt/sources.list.d/nginx.list

    apt_update
    $SUDO apt-get install -y nginx

    if command -v systemctl >/dev/null 2>&1; then
        $SUDO systemctl enable --now nginx
        log "nginx service enabled and started."
    fi

    log "nginx installed: $(nginx -v 2>&1 || echo 'n/a')"
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
    [ "${INSTALL_FAIL2BAN}" = "1" ]  && echo "  • fail2ban                   : baseline sshd jail active"
    [ "${INSTALL_UNATTENDED}" = "1" ] && echo "  • unattended-upgrades        : automatic security updates enabled"
    echo "  • Repository                 : ${TARGET_HOME}/myodoo-docker (branch ${REPO_BRANCH})"
    echo ""
    echo "${C_YELLOW}Next steps:${C_NC}"
    echo "  • Start the Fish shell:  exec fish"
    echo "    (Do NOT 'source' the Fish config from bash — it uses Fish syntax.)"
    echo "  • getScripts.py has configured Fish and offered to set it as your default shell."
    echo "  • Apply full hardening: fill /root/.config/myodoo-docker/.env, then run"
    echo "    'sudo python3 ${TARGET_HOME}/myodoo-docker/scripts/server_hardening.py' (audit),"
    echo "    then add --apply.  See --help for what each module changes."
    echo "  • Re-run this bootstrap any time with: ${INSTALL_PATH}"
    echo ""
}

# ──────────────────────────────────────────
# Main
# ──────────────────────────────────────────

main() {
    section "myodoo-docker Bootstrap v${SCRIPT_VERSION} (${SCRIPT_DATE})"

    resolve_privilege
    resolve_target_user
    self_install
    detect_os
    install_base_packages
    install_docker
    install_nginx
    install_fail2ban
    install_unattended_upgrades
    clone_repo_and_run_getscripts
    print_summary
}

main "$@"
