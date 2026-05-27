# Release Notes

## Server Provisioning & Hardening (27.05.2026)

### Added
- bootstrap.sh v1.4.x: Out-of-the-box initializer for fresh Debian 12/13 and Ubuntu 20.04/22.04/24.04/26.04 — installs Docker CE, nginx, certbot, UFW (disabled), fail2ban baseline, and unattended-upgrades; self-installs to `/opt`, idempotent, every stage toggleable via env var
- server_hardening.py v1.5.0: Config-driven audit/apply hardening tool (`hardening_config.yaml`) covering UFW, fail2ban, SSH, sysctl, sysctl_persist, kernel module blacklist, Docker daemon, auto-updates, auditd, AIDE, nginx, and port modules; lockout-safe SSH swap (atomic after `sshd -t`), dynamic `ALLOWED_IP_<n>` allowlist, detailed `--help`
- dist-upgrade-debian.sh v1.0.0: Guided, phased Debian major release upgrade (e.g. bookworm → trixie) with apt-source backup and reboot prompt; refuses to run on Ubuntu
- setup-maintenance-cron.sh v1.0.0 + myodoo-maintenance.cron/.logrotate: Declarative `/etc/cron.d/` maintenance jobs (backup 02:00/14:00, daily cert renewal, daily DSGVO weblog purge) plus weekly logrotate; idempotent with `--remove`
- bootstrap.sh: certbot (Let's Encrypt client) installation step

### Changed
- ssl-renew.sh v1.1.0: Renew via certbot `--pre-hook/--deploy-hook/--post-hook` — nginx is only bounced when a certificate is actually due (no more unconditional weekly downtime); own logging and an "nginx never left down" safety net
- syspatch.fish v1.2.0: Rebuild the AIDE baseline after a system update; pass `--config` explicitly (AIDE 0.18+ on Debian trixie ships no compiled-in default config)
- getScripts.py v9.0.8/v9.0.9: Switch the 7-Zip download to the `ip7z/7zip` GitHub mirror (fixes 404 on stale pinned URLs), robust 7zz version parsing, and restore the default-shell prompt
- getScripts.py: copy_scripts deploys the new maintenance scripts/templates to `/root`

### Fixed
- container2backup.py v4.5.1: Guard the path-issue confirmation prompt with `sys.stdin.isatty()` — under cron (no TTY) it now aborts cleanly instead of raising `EOFError`
- .gitignore: Remove a corrupted line so `scripts/.env` is reliably ignored
- dist-upgrade-debian.sh: Validate codenames against `^[a-z][a-z0-9]*$` before interpolating into the sed rewrite
- server_hardening.py v1.4.1: Apply AIDE excludes even when a database already exists (prevents the 30+ min Docker-host scan); literal numeric strings no longer int-cast into Docker daemon.json

## Security Hardening (21.04.2026)

### Added
- cleanup-weblogs.py v2.0.0: Atomic log rotation via `nginx -s reopen` (SIGUSR1), fcntl lock against concurrent runs, opt-in cache clearing via `--clear-cache`, backup cleanup restricted to `*.bak` files

### Changed
- container2backup.py v4.5.0: Validate `db_name`, `db_user`, `sql_container`, `data_container` against `[A-Za-z0-9_.-]+` at config-load time; skip invalid entries instead of aborting
- getScripts.py v9.0.7: Cache layer migrated from pickle to JSON

### Fixed
- [H1] container2backup.py: Eliminate all `shell=True` subprocess calls (filestore extract, zip/gzip/zstd compression) — replace with list-form arguments, `Popen` pipelines, and `cwd=` parameter. Closes command-injection vector via YAML-controlled identifiers.
- [H2] scripts/lib/cache.py + getScripts.py: Replace unsafe `pickle.load` with `json.load`; enforce cache-key allowlist (`[A-Za-z0-9._-]+`) to prevent path traversal from cache directory. Existing pickle caches self-heal on first read.

## Security Hardening (17.03.2026)

### Added
- HEALTHCHECK directive for all Odoo Dockerfiles (v16, v18, v19) using wget --spider on /web/health

### Fixed
- [H1] restore-zip.sh: Fix shell injection via unquoted variables, broken bash syntax on lines 205/233, add input validation and set -euo pipefail
- [H2] check_dockerimage_odoo.py: Replace os.system() with subprocess.run() argument lists, add regex validation for Docker image references
- [H3] container2backup.py: Replace shell=True rsync execution with shlex.split() argument parsing
- [H4] getScripts.py, proxy_config.py, dns_optimizer.py: Replace all `echo | sudo tee` shell injection patterns with subprocess.run(input=) (8 locations)

## Version 9.0.0 (26.02.2026)

### Changed
- Migrate CLI tool manager from pipx to uv (`uv tool install/upgrade`)
- Auto-update uv on every run (`uv self update`)
- Auto-upgrade all installed uv tools on every run (`uv tool upgrade --all`)
- Replace all pipx functions with uv equivalents in getScripts.py and package_manager.py
- Rename packages.txt section header from `# PIPX packages` to `# UV tool packages`
- Remove pipx from system packages (uv is installed via curl, not apt)

### Fixed
- Backward compatibility: parser still accepts legacy `# PIPX packages` section header

### Migration
- pipx is automatically uninstalled if still present (after uv tools are installed)
- All pipx-managed tools are migrated to uv tool management
