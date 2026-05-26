# External Integrations

**Analysis Date:** 2026-05-26

## APIs & External Services

**GitHub API:**
- GitHub Releases API — used by `getScripts.py` to fetch latest versions of tools
  - Endpoints: `https://api.github.com/repos/fastfetch-cli/fastfetch/releases/latest`, `https://api.github.com/repos/ajeetdsouza/zoxide/releases/latest`, `https://api.github.com/repos/sharkdp/bat/releases/latest`, `https://api.github.com/repos/eqms/ctop/releases/latest`
  - Auth: None (unauthenticated, rate-limit risk)
  - SDK/Client: `requests` library

**PyPI API:**
- Used by `getScripts.py` to check latest package versions before installation
  - Endpoint: `https://pypi.org/pypi/{package_name}/json`
  - Auth: None

**GitHub Repository:**
- `https://github.com/equitania/myodoo-docker.git` — cloned/updated on target servers during `getScripts.py` runs
  - Branch: `2026` (default, set in `scripts/lib/constants.py`)

**Astral UV Installer:**
- `https://astral.sh/uv/install.sh` — UV package manager bootstrap installer
  - Called via `curl -LsSf https://astral.sh/uv/install.sh | sh` in `getScripts.py`

**Starship Prompt:**
- `https://starship.rs/install.sh` — Starship shell prompt installer
  - Called via `curl -sS https://starship.rs/install.sh | sh -s -- -y` in `getScripts.py`

**Fisher (Fish plugin manager):**
- `https://raw.githubusercontent.com/jorgebucaran/fisher/main/functions/fisher.fish` — Fish plugin manager bootstrap
  - Called in `getScripts.py` during Fish shell setup

**OpenAI API:**
- `openai` Python package included in Odoo container requirements (`Dockerfiles/prepare-18/requirements.txt`, `Dockerfiles/prepare-19/requirements.txt`)
  - Used within Odoo custom modules (no direct script-level integration)
  - Auth: API key (configured in Odoo settings)

**DeepL API:**
- `deepl` Python package included in Odoo container requirements
  - Used within Odoo custom modules for translation
  - Auth: API key (configured in Odoo settings)

**Microsoft Authentication (MSAL):**
- `msal==1.31.1` Python package in Odoo container requirements
  - Used within Odoo custom modules for Microsoft 365 / Azure AD integration
  - Auth: Azure AD credentials (configured in Odoo settings)

**Equitania ownerp.io asset server:**
- `https://rm.ownerp.io/staff/wkhtmltox_0.12.6.1-3.bookworm_amd64.deb` — custom wkhtmltopdf build (amd64)
  - Used in `Dockerfiles/prepare-18/Dockerfile` and `Dockerfiles/prepare-19/Dockerfile`
  - No auth — public download URL

**ctop (Equitania fork):**
- `https://github.com/eqms/ctop/releases/download/v{version}/{binary_name}` — custom ctop binary
  - Downloaded by `getScripts.py` during server setup

## Data Storage

**Databases:**
- PostgreSQL 16
  - Runs in dedicated Docker containers (e.g., `live-db`, `test-db`)
  - Accessed from Odoo containers via Docker network (`--network live-db-net`)
  - Client: `psycopg2` (Python adapter in Odoo containers)
  - pg_dump via `docker exec {sql_container} pg_dump -U {db_user} {db_name}` in `scripts/container2backup.py`
  - Default user: `ownerp` (configured in YAML configs)
  - Port: 5432

**File Storage:**
- Odoo filestore: `/opt/odoo/data/filestore/` inside Odoo containers
  - Backed up via `docker exec {container} tar c -C {src_path} .` piped into local compression
  - Mounted via Docker volume: `-v /opt/odoo/live:/opt/odoo/data`
- Backup destination: `/opt/backups/` (configurable via `backup_path` in YAML)
- FastReport file storage: `/opt/fast-report/fr-{instance}/` — backed up separately
- Docker builds: `$HOME/docker-builds/` — included in service backups

**Caching:**
- Local filesystem cache: `~/.cache/getscripts/` — version info cached for 24 hours (JSON files)
  - Prevents repeated API calls to GitHub and PyPI
  - Cache key validated against `^[A-Za-z0-9._\-]+$` regex (path-traversal defense)

## Authentication & Identity

**Backup Encryption:**
- Implementation: AES-256 via 7-Zip (`7zz`) — optional, 7z format only
  - Config: `BACKUP_ENCRYPTION_ENABLED=true`, `BACKUP_PASSWORD=...` in `/root/.config/myodoo-docker/.env`
  - Alternative: zstd encryption via `config/backup_credentials.yaml` (key files in `/etc/myodoo/keys/`)

**Odoo Admin:**
- `admin_passwd` in `Dockerfiles/v*/odoo.conf` — template placeholder `CHANGE_ME_ADMIN_PASSWORD`

**PostgreSQL:**
- Username/password in `scripts/docker2update.yaml` and `scripts/container2backup.yaml`
  - Template placeholder: `CHANGE_ME_BEFORE_PRODUCTION`
  - Loaded at runtime; not committed with real values

**SSH Hardening:**
- Port, allowed IPs managed via `scripts/server_hardening.py` + `scripts/hardening_config.yaml`
  - Actual IPs loaded from `.env` via `${ENV_VAR}` substitution

## Monitoring & Observability

**Error Tracking:**
- None detected — no Sentry, Rollbar, or similar

**Logs:**
- `getScripts.py`: logs to `~/getscripts.log` and stdout (`logging.FileHandler` + `StreamHandler`)
- `scripts/cleanup-weblogs.py`: rotates `/var/log/nginx/*.log` with 7-day retention (DSGVO)
- `scripts/nightly-cleanup.sh`: logs to `/var/log/nightly-cleanup.log`
- Odoo: `logfile` config in `odoo.conf` (empty = stdout); log level `warn` by default
- Container logs: accessible via `docker logs {container}`

**Health Checks:**
- All Odoo containers include Docker HEALTHCHECK: `wget -q --spider http://localhost:8069/web/health`
  - Interval: 60s, timeout: 10s, start-period: 60s, retries: 3
  - Defined in all `Dockerfiles/v*/Dockerfile`

**GeoIP:**
- MaxMind GeoIP databases installed in containers: `/usr/share/GeoIP/GeoLite2-City.mmdb`, `/usr/share/GeoIP/GeoLite2-Country.mmdb`
  - Referenced in `Dockerfiles/v*/odoo.conf`

## CI/CD & Deployment

**Hosting:**
- Linux VPS/dedicated servers (Hetzner and DigitalOcean mentioned in DNS optimizer code)
- Containers managed manually via `scripts/update_docker_odoo.py`

**CI Pipeline:**
- GitLab CI — referenced in `Dockerfiles/prepare-18/CLAUDE.md` and `Dockerfiles/prepare-19/CLAUDE.md`
  - Registry: `registry.gitlab.ownerp.io` (GitLab Container Registry)
  - CI variables: `CI_REGISTRY_*` auto-populated by GitLab

**Git Remotes:**
- GitHub: `https://github.com/equitania/myodoo-docker.git` (upstream/public)
- GitLab: `gitlab.ownerp.io` (origin/internal CI)

## Package Repositories

**Node.js:**
- `https://deb.nodesource.com/setup_current.sh` — NodeSource APT repository
  - Used in `Dockerfiles/prepare-18/Dockerfile` and `Dockerfiles/prepare-19/Dockerfile`
  - Installs current Node.js LTS for Odoo frontend build tools

**PostgreSQL:**
- `http://apt.postgresql.org/pub/repos/apt/` (pgdg) — official PostgreSQL APT repository
  - GPG key: `B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8`
  - Used in prepare-18 and prepare-19 Dockerfiles; installs `postgresql-client-16`

**Fish Shell:**
- Ubuntu: `ppa:fish-shell/release-4` (Launchpad PPA)
- Debian: `http://download.opensuse.org/repositories/shells:/fish:/release:/4` (OpenSUSE OBS)
  - Managed by `getScripts.py`; minimum version: 4.0.0

**npm global packages (inside containers):**
- `less`, `less-plugin-clean-css`, `rtlcss` — installed for Odoo CSS compilation

## Webhooks & Callbacks

**Incoming:**
- None detected at script/infrastructure level
- Odoo itself supports webhooks internally (framework feature)

**Outgoing:**
- rsync to remote servers — optional, configured via `scripts/container2backup.yaml` rsync section
  - Config: `rsync.enabled: true` and `rsync.commands` list
  - Example: `rsync -avz /opt/backups/ user@remote-server:/backup/`
- SMTP — Odoo email sending configured in `odoo.conf` (`smtp_server`, `smtp_port`, `smtp_user`)
  - Default: localhost:25 (no auth, plain SMTP)

## SSL/TLS

**Let's Encrypt / Certbot:**
- `scripts/ssl-renew.sh` — cron-driven renewal (every Wednesday at midnight)
  - Stops nginx → runs `certbot renew` → clears nginx cache → restarts nginx
  - Certbot paths: `/usr/local/bin/certbot` or `/usr/bin/certbot`

## Server Security

**UFW (Uncomplicated Firewall):**
- Managed by `scripts/server_hardening.py` with rules from `scripts/hardening_config.yaml`

**Fail2ban:**
- Managed by `scripts/server_hardening.py`
- SSH jail configuration, ignoreip loaded from `.env`

## Environment Configuration

**Required env vars (from `scripts/.env.example`):**
- `BACKUP_ENCRYPTION_ENABLED` — enable/disable AES-256 backup encryption
- `BACKUP_PASSWORD` — encryption password for 7z backups
- `SSH_PORT` — SSH port for firewall rules
- `ALLOWED_IP_1` through `ALLOWED_IP_5` — whitelisted IPs for SSH/firewall

**Secrets location:**
- Production: `/root/.config/myodoo-docker/.env` (mode 600)
- Fallback: `~/.myodoo/backup_credentials.yaml`, `config/backup_credentials.yaml`
- Encryption keys: `/etc/myodoo/keys/` directory
- Never committed: `.env` and `backup_credentials.yaml` are in `.gitignore`

---

*Integration audit: 2026-05-26*
