# Technology Stack

**Analysis Date:** 2026-05-26

## Languages

**Primary:**
- Python 3 (3.12+ recommended) - All management scripts, Docker build utilities, backup and update automation
- Bash/Shell - Operational scripts: `scripts/ssl-renew.sh`, `scripts/nightly-cleanup.sh`, `scripts/restore-zip.sh`, `scripts/docker-clean-logs.sh`, `scripts/check_docker_volumes.sh`
- Fish Shell - User shell configuration in `fish/` directory (conf.d, functions)

**Secondary:**
- Nginx config DSL - Reverse proxy configuration in `scripts/nginx/nginx.conf` and `scripts/nginx/nginxconfig.io/`
- YAML - Primary configuration format for all tools

## Runtime

**Environment:**
- Linux (Debian Bookworm) - Target production platform for all Docker images
- Python runtime: 3.12.x inside Odoo containers (`Dockerfiles/prepare-18/`, `Dockerfiles/prepare-19/`)
- Python runtime: 3.14+ on dev host (pyc cache shows cpython-314)

**Package Manager:**
- pip (system) — used inside Docker images via `requirements.txt`
- UV — used for host-side tool installation via `uv tool install`; installed automatically by `getScripts.py`
- apt — used for system-level packages in Docker images and on hosts
- Lockfile: `requirements.txt` files per Dockerfile subdirectory (pinned versions)

## Frameworks

**Core:**
- Odoo (v16, v18, v19) - ERP application deployed inside Docker containers
- Nginx 1.26+ - Reverse proxy / SSL termination in front of Odoo containers

**Build/Dev:**
- Docker + Docker Compose - Container runtime and orchestration
- Multi-stage Docker builds - Used in `Dockerfiles/prepare-18/Dockerfile` and `Dockerfiles/prepare-19/Dockerfile` (builder → production stage)

## Key Dependencies

**Management scripts (top-level `requirements.txt`):**
- `requests>=2.31.0` - HTTP calls to GitHub API, PyPI API, package downloads
- `PyYAML>=6.0.1` - YAML config parsing for all YAML-based configs

**container2backup.py additional imports:**
- `python-dotenv` (via `dotenv` import) - `.env` file loading for credentials
- `yaml` (PyYAML) - YAML backup config parsing
- `argparse`, `subprocess`, `shutil`, `tempfile` - stdlib only for backup execution

**server_hardening.py:**
- `PyYAML` - Config parsing
- `python-dotenv` - Env var loading from `.env`

**Odoo container requirements (prepare-18 + prepare-19):**
- `psycopg2==2.9.9` (Python 3.12) - PostgreSQL adapter
- `gevent==24.2.1` / `greenlet==3.0.3` - Async worker support
- `Werkzeug==3.0.1` - WSGI framework for Odoo
- `lxml==5.2.1` + `lxml-html-clean` - XML/HTML processing
- `Pillow==10.2.0` - Image processing
- `reportlab==4.1.0` - PDF generation
- `openai` - OpenAI API client (unpinned, custom extension)
- `msal==1.31.1` - Microsoft Authentication Library
- `deepl` - DeepL translation API client
- `paramiko` - SSH client (for remote operations in modules)
- `pandas==1.5.1`, `numpy==1.26.3` - Data processing
- `openupgradelib` - Odoo version migration helper
- `pyopenssl==26.0.0` + `cryptography==46.0.0` - CVE-2026-27459 fix
- `nextcloud-api-wrapper` (prepare-18 only, commented out in prepare-19)
- `python-gitlab` (prepare-18 only, commented out in prepare-19)

**packages.txt (UV tool packages installed on host):**
- `nginx-set-conf` - Nginx config management CLI
- `pip`, `wheel`, `setuptools`, `distro-info` - Pip ecosystem
- `odoorpc-toolbox` - Odoo RPC client
- `zstd` - Zstandard compression Python bindings
- `python-dotenv` - Env file loading
- `zoxide` - Smart directory navigation
- `fastfetch` - System info display

## Configuration

**Environment:**
- Primary: `/root/.config/myodoo-docker/.env` — credentials for backup encryption, SSH ports, firewall IPs
- Example template: `scripts/.env.example`
- Key vars: `BACKUP_ENCRYPTION_ENABLED`, `BACKUP_PASSWORD`, `SSH_PORT`, `ALLOWED_IP_1..5`
- `.env` files are NEVER committed (in `.gitignore`)

**Build:**
- `scripts/container2backup.yaml` - Backup job definitions (databases, services, rsync)
- `scripts/docker2update.yaml` - Container update definitions (live/test Odoo instances)
- `config/backup_config.yaml` - Alternative backup config with encryption key references
- `config/backup_credentials.yaml.example` - Credentials template (not committed)
- `scripts/hardening_config.yaml` - Server hardening rules (UFW, Fail2ban, SSH, sysctl)
- `Dockerfiles/v*/odoo.conf` - Odoo server configuration template (DB connection, workers, limits)

**Odoo container:**
- Base image: `myodoo/prepare-v16:25.02.24-3.11.11` (for v16/v18), `myodoo/prepare-v19:25.12.08-3.12.12` (for v19)
- Build controlled by: `Dockerfiles/v*/build_odoo.py` + `release.txt` (downloads Odoo from GitHub releases)
- Image validation: `Dockerfiles/v*/check_dockerimage_odoo.py`

## Platform Requirements

**Development:**
- Linux host with Docker daemon
- Python 3.x (any modern version for management scripts)
- UV package manager (auto-installed by `getScripts.py`)
- Fish shell 4.0+ (installed by `getScripts.py`)
- Starship prompt, zoxide, fastfetch, bat (installed by `getScripts.py`)

**Production:**
- Debian Bookworm (Bookworm) — required by Dockerfiles
- Docker Engine (no specific version pinned)
- Nginx 1.26+ (systemd-managed on host)
- Certbot — Let's Encrypt SSL certificate management
- UFW + Fail2ban — firewall and intrusion prevention
- PostgreSQL 16 client tools (inside containers)
- 7zz / zip / gzip / zstd — compression tools for backups
- Ports: 8069 (HTTP), 8072 (longpolling) — mapped to host via `docker run -p`

---

*Stack analysis: 2026-05-26*
