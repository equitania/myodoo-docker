# Release Notes

## Repository Security Review & Hardening (14.07.2026)

Full-repository security review (Python, Shell/Fish, Docker/config) with fixes applied across all severities.

### Added
- pg-local-deploy.sh / fr-local-deploy.sh: password input now shows one `*` per typed character (with backspace), so the number of entered characters is visible while the secret itself stays hidden (`_read_masked`). Same masking added to fr-local-deploy.sh registry-token input and restore-zip.sh password fallback.

### Changed
- fr-local-deploy.sh **[CRITICAL]**: removed the shared "baked default" secrets (JWT signing key, MD5 admin hash, bcrypt superuser hash) — they were identical across all deployments and would be an auth-bypass if the repo is readable. When no override and no existing appsettings.json is present, admin/superuser passwords and the JWT key are now generated **randomly per deployment** (`secrets`) and shown once in the final banner. When the superuser hash is needed and `bcrypt` is missing from the system Python, the script now provisions it automatically in a cached **uv venv** (`~/.cache/fr-local-deploy/venv`) instead of aborting.
- update_docker_odoo.py v5.3.1 **[HIGH]**: `db_password_via_env` now defaults to **true** — the DB password goes via `-e PGPASSWORD` instead of the `docker run` argv (previously visible in `ps aux`). Example YAMLs document the flag.
- bin/boot v2.2.0/v2.3.0 (v16/v18/v19): container entrypoint now whitelists `start|update|neutralize`; arbitrary arguments are no longer executed as root.
- build_odoo.py v2.3.0 (v16/v18/v19): `unzip` runs without `shell=True` (+ CSV filename validation); TLS downloads enforce `cert_reqs=CERT_REQUIRED` with certifi.
- odoo.conf (v16/v18/v19): `db_sslmode = require`; v19 gains a `proxy_access_token` placeholder. Dockerfiles: `ADD` → `COPY`.
- syspatch.fish v1.3.0: dropped the unconfirmed `docker volume prune -f` (could irreversibly delete data volumes of stopped containers); prunes only dangling images now.

### Fixed
- fr-local-deploy.sh **[CRITICAL/HIGH]**: appsettings.json (contains the JWT key in cleartext) now `chmod 0600`; `docker login --password-stdin` and stdin/WGETRC-based basic auth instead of credentials in argv; whitelist validation for container name and image tag (Compose-YAML injection).
- pg-local-deploy.sh v1.1.0 **[MEDIUM]**: whitelist validation for DB user/name; compose file created via `umask 077` (no world-readable TOCTOU window); docker-run fallback uses `--env-file` instead of `-e` for the password.
- container2backup.py v4.7.1 **[HIGH]**: the backup password is masked in log output — the gpg-less 7z fallback no longer writes the cleartext password into the cron log.
- restore-zip.sh v2.1.0: DB password resolved from `PGPASSWORD` env → positional arg (warns) → masked prompt, instead of a plain positional argument visible in `ps aux`; GPG-decrypted dump written with `umask 077`.
- getScripts.py v9.7.2 / proxy_config.py: `no_proxy` is validated before being written into the sourced fish startup file (command-injection); missing `requests.get` timeouts added; predictable `/tmp` download paths replaced with `tempfile.mkstemp`; jammy APT repo over HTTPS.

## Live Version Checks & Fail2Ban Audit Polish (11.06.2026)

### Changed
- getScripts.py v9.5.0: all GitHub/PyPI latest-version lookups (ctop, fastfetch, zoxide, bat, 7zip, pypi_*) now query the live API first; the 24h cache is only used as a fallback when the API is unreachable. Previously `ups` was blind to releases published within a day (e.g. ctop 0.8.7 was ignored while 0.8.6 was still cached). Resilience preserved, freshness restored; GitHub calls without a timeout now use `timeout=15`.
- server_hardening.py v1.8.0: Fail2Ban UFW bans (banaction=ufw, rules commented `by Fail2Ban`) are now reported as **info** with banned IP and jail name instead of "Unbekannte Regel" warnings — the per-ban noise was hiding real configuration drift. All other unexpected UFW rules keep warning as before.

### Fixed
- hardening_config: the four nginx Fail2Ban jails pointed at `/var/log/fail2ban_nginx-*.log` — files nothing ever writes. `--apply` therefore auto-disabled them on every run while the audit kept counting them as errors (unfixable loop). They now parse the real host-nginx logs (`error.log` / `access.log` for bad-request). security_headers: dropped deprecated `X-XSS-Protection` (removed from security.conf v1.3), added `Content-Security-Policy` + `Permissions-Policy` so the audit matches the deployed header policy.

## nightly-cleanup in Standard-Cron (11.06.2026)

### Changed
- nightly-cleanup.sh is now part of the standard maintenance setup: deployed to `/root` by getScripts.py (v9.4.0) and scheduled daily at **04:30** in `/etc/cron.d/myodoo-maintenance` (setup-maintenance-cron.sh v1.2.0) — deliberately after the 02:00 backup window so a container restart can never hit a running backup. Log rotation was already in place. The installer now also warns when the legacy standalone `/etc/cron.d/nightly-cleanup` (old manual instructions, 03:00) is present, which would cause duplicate runs. NIGHTLY_CLEANUP.md (DE+EN) rewritten for the standard path; the manual `/usr/local/bin` install remains documented as an alternative.

## Script Review Follow-up (11.06.2026)

### Added
- restore-zip.sh v2.0.0: Multi-format restore with automatic detection — supports every format container2backup.py produces: `.zip`, `.7z`, `.7z.gpg` (GPG decrypt with passphrase prompt), `.tar.gz`, `.tar.zst`. Previously only `.zip` was supported although `7z` is the backup default. New guards: required inputs are rejected when empty (an empty DB name could previously expand `rm -rf` to the backup root), and the cleanup step can no longer delete `/opt/backups/docker/` itself.

### Fixed
- nginx-cert-guard.py v1.1.0: bracketed IPv6 listeners (`[::1]:443`) are no longer misreported as unresolvable (would have quarantined healthy vhosts); rollback now matches quarantined files by exact path instead of `server_name` (a duplicate server_name could restore vhosts quarantined manually before the run); quarantine report now reads the domain from the renamed file (was read from the no-longer-existing pre-rename path).
- server_hardening.py v1.7.0: banner printed v1.5.0 while the header said v1.6.0 (now a single `SCRIPT_VERSION` constant); defective/empty YAML config now exits with a clear message instead of an `AttributeError` traceback; changing the SSH port now warns loudly when the new port is missing from the UFW rules (lockout guard).
- ssl-renew.sh v1.3.0: if even the final nginx fallback start fails, the script now exits 2 with a clear error instead of exiting 0 with nginx down.
- nightly-cleanup.sh v1.1.0: `POSTGRES_PATTERN` anchors the `db` tokens (`^db-`, `-db$`) — bare `-db`/`db-` also matched containers like `redis-db-cache`; `/var/log/nightly-cleanup.log` added to myodoo-maintenance.logrotate (grew unbounded).
- getScripts.py v9.3.1: removed ghost entry `container2backup_zstd.py` from `copy_scripts()` (file no longer exists).

### Removed (orphaned)
- `config/backup_config.yaml`, `config/backup_credentials.yaml`(+`.example`): leftovers of a pre-`.env` architecture, read by no script; the credentials file was tracked despite its own "NEVER commit" notice (placeholder only, no leak). `.gitignore` now blocks `config/backup_credentials.yaml` permanently.
- `scripts/docker-clean-logs.sh`: unversioned 4-liner with unquoted `rm $(...)`; the `cleandlog` alias never used it (truncates log files directly).

### Docs
- README_BackUp.md, ReadMe.md, .env.example: encryption sections rewritten for GPG/`.7z.gpg` (incl. `gpg -d` restore steps and gnupg dependency), version references refreshed, `db_password_via_env` documented, `pip3 install` replaced with PEP-668-compliant apt packages.

## Security Hardening & IONOS Compatibility (11.06.2026)

### Fixed
- getScripts.py v9.2.0: Fish OBS repo setup no longer requires gnupg (minimal images like IONOS Debian 13 ship without it). The signing key is written as ASCII-armored `.asc`; a failed key download no longer leaves apt broken system-wide (rollback + self-healing of half-configured repos + fallback to the Debian fish package).
- bootstrap.sh v1.6.0: Generates the `en_US.UTF-8` locale on minimal images (IONOS) — eliminates the perl/apt `setlocale` warnings on every command.
- Dockerfiles/v18-odoo: `FROM` pointed at `myodoo/prepare-v16:25.02.24-3.11.11` (copy-paste error). Now `myodoo/prepare-v18:26.05.19-3.13.13`; v19 raised to `myodoo/prepare-v19:26.05.19-3.13.13`.

### Security (project audit follow-up)
- getScripts.py v9.3.0 + scripts/lib: starship, zoxide and uv are no longer installed via `curl … | sh` pipes running unreviewed remote code as root — they now use official GitHub release binaries/.deb packages (same pattern as ctop/fastfetch/7zz). Fisher bootstrap is pinned to the latest tagged release instead of the moving main branch. Fish OBS repo URL switched to https (existing http `.list` files are migrated on the next run).
- container2backup.py v4.6.0: Encrypted backups now use GPG (AES-256, passphrase via fd) producing `.7z.gpg` — the former `7zz -p<password>` exposed the backup password in the process list. Decrypt: `gpg -d backup.7z.gpg > backup.7z`. Falls back to 7z AES (with a loud warning) when gnupg is missing. The `rsync.commands` YAML list now only accepts the rsync binary (no generic root command runner).
- update_docker_odoo.py v5.2.0: New per-container option `db_password_via_env: true` passes the DB password via `PGPASSWORD` environment (docker `-e` forwarding) instead of `--db_password=` in argv (visible in `ps`). Requires images built from 11.06.2026 (boot scripts now whitelist PGPASSWORD across `su`); default remains the legacy argv mode for older images.
- restore-zip.sh v1.4.0: `PGPASSWORD` is forwarded via the environment instead of appearing in the `docker exec` argv.
- requirements: CVE-affected pins raised in prepare-18/prepare-19 (Jinja2 3.1.6, Werkzeug 3.0.6, Pillow 10.4.0/11.3.0, requests 2.32.5, urllib3 1.26.20/2.5.0) and custom libs modernized (pycryptodome 3.23.0, oauthlib 3.3.1, bleach 6.4.0, pandas 2.2.3, numpy 1.26.4, holidays 0.69, xmltodict 0.15.1, pypandoc 1.17, python-docx 1.2.0, pdfminer.six 20260107, msal 1.37.0). Root requirements.txt: requests>=2.32.0, PyYAML>=6.0.2.

## nginx OCSP Stapling Removal (28.05.2026)

### Changed
- nginx/nginx.conf v1.4: Disabled `ssl_stapling` / `ssl_stapling_verify` (with explanatory comment). Let's Encrypt retired OCSP in May 2025; renewed LE certificates no longer carry an OCSP responder URL, so `nginx -t` started logging one warning per certificate at every startup/reload and stapling did nothing useful. Re-enable only if switching to a CA that still issues OCSP-bearing certificates. To apply on a server: `ups` + `sudo /root/deploy-nginx-base.sh` (which will back up the prior nginx.conf before installing the new one).

## Maintenance Cron Follow-up (28.05.2026)

### Changed
- setup-maintenance-cron.sh v1.1.0: After installing `/etc/cron.d/myodoo-maintenance` the script now scans root's user-crontab (`crontab -l -u root`) for legacy entries referencing the managed scripts (`container2backup.py`, `ssl-renew.sh`, `cleanup-weblogs.py`, `nginx-cert-guard.py`) and warns about them — these would otherwise run **in addition** to the cron.d jobs (e.g. backups firing twice a day). Read-only: the script never edits the user crontab (it may contain unrelated operator entries); removal is left to the operator via `sudo crontab -e -u root`. README_BackUp.md updated accordingly.

## nginx Base Rollout & Config Hygiene (27.05.2026)

### Added
- deploy-nginx-base.sh v1.0.0: Rolls out the shared nginx files every vhost depends on — `nginxconfig.io/security.conf`, `nginxconfig.io/general.conf`, `html/custom_50x.html` — to `/etc/nginx`, so a missing `include` can no longer make `nginx -t` fail and take the whole server down on rollout. Also replaces `nginx.conf` safely: backup + `nginx -t` + automatic rollback on failure. Idempotent; `--no-main-conf`, `--dry-run`, `--src`/`--dest`. Deployed to /root by getScripts.py; referenced as a next step in bootstrap.sh (v1.4.2).

### Changed
- nginx/nginxconfig.io/security.conf v1.3: removed deprecated `X-XSS-Protection`; activated an Odoo-tuned `Content-Security-Policy` (ws/wss for longpolling, `frame-ancestors 'self'`). This file is now the single source of truth for security headers.
- nginx/nginx.conf v1.3: removed the duplicate security-header block (headers are not inherited once a child block sets its own — the http-level copy was dead and divergent) and the dead `error_page /404.html` / `/50x.html` directives (vhosts set `/custom_50x.html` themselves).
- nginx/nginxconfig.io/general.conf v1.1: removed the redundant per-vhost `gzip` (it is configured globally in nginx.conf).

## nginx Outage Protection (27.05.2026)

### Added
- nginx-cert-guard.py v1.0.0: Prevents a full nginx outage when a customer's (sub)domain stops pointing at the server. `--reconcile [--start]` brings nginx up at renewal and quarantines only the broken vhost (missing `ssl_certificate` file, or an old `listen <domain>:443` whose host no longer resolves) instead of letting one bad vhost block the whole server; includes a mass-failure guard with rollback so a global fault never causes a blind shutdown. `--check [--apply]` proactively detects drifted domains via DNS and disables them after `GUARD_FAIL_THRESHOLD` confirmed runs (guards against DNS glitches / Cloudflare-fronted domains via a confirmation counter + `GUARD_IGNORE_DOMAINS`). `--list` / `--restore <domain>` for inspection and recovery. SMTP alert mail via `smtplib`.
- Maintenance cron: daily proactive `nginx-cert-guard.py --check --apply` at 23:50, just before the cert renewal; `/var/log/nginx-cert-guard.log` added to logrotate.
- `.env.example`: `ALERT_*` (SMTP relay) and `GUARD_*` (server IPs, ignore list, thresholds) keys.

### Changed
- ssl-renew.sh v1.2.0: nginx is restarted via `nginx-cert-guard.py --reconcile --start` (post-hook + safety net) instead of a bare `systemctl start nginx`, so a single broken vhost can no longer take the whole server down. Falls back to `systemctl start nginx` when the guard is absent.
- getScripts.py: deploys `nginx-cert-guard.py` to /root.

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
