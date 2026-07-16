#!/bin/bash
# bootstrap.sh — Out-of-the-box initializer for fresh Debian/Ubuntu servers
# Version 1.7.0 — 16.07.2026
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
#   3. Installs Docker CE from the official Docker repository (deb822 format);
#      pins the classic overlay2 storage driver via /etc/docker/daemon.json —
#      Docker >= 29 defaults fresh installs to the containerd image store whose
#      image export is broken for large builds (moby/moby#52431)
#   4. Installs nginx from the official nginx.org repository (reverse proxy)
#   5. Installs certbot (Let's Encrypt client; renewal via ssl-renew.sh standalone)
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

SCRIPT_VERSION="1.6.0"
SCRIPT_DATE="01.06.2026"

REPO_URL="${REPO_URL:-https://github.com/equitania/myodoo-docker.git}"
REPO_BRANCH="${REPO_BRANCH:-2026}"

INSTALL_DOCKER="${INSTALL_DOCKER:-1}"
INSTALL_NGINX="${INSTALL_NGINX:-1}"
INSTALL_CERTBOT="${INSTALL_CERTBOT:-1}"
INSTALL_UFW="${INSTALL_UFW:-1}"
INSTALL_FAIL2BAN="${INSTALL_FAIL2BAN:-1}"
INSTALL_UNATTENDED="${INSTALL_UNATTENDED:-1}"
INSTALL_PYTHON_DEPS="${INSTALL_PYTHON_DEPS:-1}"
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
        # Do NOT switch the store on a live install (images/containers would
        # become invisible) — but do surface the moby#52431 exposure.
        if [ "$(docker info --format '{{.Driver}}' 2>/dev/null)" = "overlayfs" ]; then
            warn "This Docker uses the containerd image store — image export of large builds"
            warn "is broken there (moby/moby#52431: 'ref locked: unavailable' / hollow images)."
            warn "Manual fix: /etc/docker/daemon.json {\"storage-driver\": \"overlay2\"},"
            warn "restart docker, re-pull images, then 'docker builder prune -af'."
        fi
        if command -v systemctl >/dev/null 2>&1; then
            $SUDO systemctl enable --now docker 2>/dev/null || true
        fi
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

    # Pin the classic overlay2 storage driver BEFORE the package postinst starts
    # dockerd for the first time. Docker >= 29 defaults FRESH installs to the
    # containerd image store, whose image export is broken for large builds
    # (moby/moby#52431: 'ref moby/1/... locked: unavailable', or hollow images
    # missing even /bin/sh). Seen live on RZ-OD02, 16.07.2026. Remove this pin
    # once the upstream issue is fixed. An existing daemon.json is respected.
    if [ ! -f /etc/docker/daemon.json ]; then
        $SUDO install -m 0755 -d /etc/docker
        write_file /etc/docker/daemon.json <<'EOF'
{
  "storage-driver": "overlay2"
}
EOF
        log "Pinned storage-driver overlay2 in /etc/docker/daemon.json (moby#52431 workaround)."
    else
        warn "/etc/docker/daemon.json already exists — leaving the storage driver untouched."
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

    # Like Docker: if nginx is already installed, leave the apt repo alone to
    # avoid a Signed-By conflict with a pre-existing nginx.list. Just ensure the
    # service is up.
    if command -v nginx >/dev/null 2>&1; then
        log "nginx already present: $(nginx -v 2>&1). Leaving apt repo untouched."
        if command -v systemctl >/dev/null 2>&1; then
            $SUDO systemctl enable --now nginx 2>/dev/null || true
        fi
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

    log "nginx installed: $(nginx -v 2>&1 || echo 'n/a')"
}

install_certbot() {
    [ "${INSTALL_CERTBOT}" = "1" ] || { log "certbot install disabled — skipping."; return 0; }

    section "Installing certbot (Let's Encrypt client)"

    if command -v certbot >/dev/null 2>&1; then
        log "certbot already present: $(certbot --version 2>&1 || echo 'n/a'). Skipping install."
        return 0
    fi

    # The distro 'certbot' package lands at /usr/bin/certbot, which the project's
    # ssl-renew.sh already looks for. Renewal here is STANDALONE (ssl-renew.sh
    # stops nginx, runs `certbot renew`, restarts nginx), so the nginx plugin is
    # intentionally NOT installed — it would only add an unused authenticator.
    $SUDO apt-get install -y certbot

    log "certbot installed: $(certbot --version 2>&1 || echo 'n/a')"
    log "  Issue certs with: certbot certonly --standalone -d <domain> (stop nginx first)."
    log "  Automatic renewal is handled by scripts/ssl-renew.sh (cron, standalone mode)."
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

main "$@"
