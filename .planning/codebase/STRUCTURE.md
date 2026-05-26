# Codebase Structure

**Analysis Date:** 2026-05-26

## Directory Layout

```
myodoo-docker/                        # Repo root — source of truth
├── getScripts.py                     # Main bootstrap/provisioning script (v9.x)
├── packages.txt                      # Package manifest read by getScripts.py
├── requirements.txt                  # Minimal pip deps for getScripts.py itself
├── ReadMe.md                         # Bilingual (DE/EN) repository overview
├── RELEASE_NOTES.md                  # Changelog
├── starship.toml                     # Starship prompt config (deployed to ~/.config/starship.toml)
├── cleanup_legacy.txt                # Notes on removed legacy files
│
├── scripts/                          # Operational scripts (deployed to ~/ by getScripts.py)
│   ├── container2backup.py           # Backup system (v4.5.0) — main backup entry point
│   ├── container2backup.yaml         # Backup config template (deployed to ~/container2backup.yaml)
│   ├── update_docker_odoo.py         # Container update orchestrator (v5.1.x)
│   ├── docker2update.yaml            # Update config template (deployed to ~/docker2update.yaml)
│   ├── restore-zip.sh                # Restore from backup archive (v1.3.0)
│   ├── ssl-renew.sh                  # SSL certificate renewal via certbot
│   ├── nightly-cleanup.sh            # Memory-based container restart (v1.0.0)
│   ├── server_hardening.py           # Security audit/apply (v1.1.0)
│   ├── cleanup-weblogs.py            # Nginx log cleanup
│   ├── docker-clean-logs.sh          # Docker log rotation
│   ├── check_docker_volumes.sh       # Docker volume health check
│   ├── hardening_config.yaml         # Security hardening rules
│   ├── .env                          # Runtime secrets (git-ignored)
│   ├── .env.example                  # Secrets template
│   │
│   ├── lib/                          # Modular library for getScripts.py (v8.0.0+)
│   │   ├── __init__.py               # Package init, exports SCRIPT_VERSION
│   │   ├── constants.py              # Version, paths, DNS servers, repo URLs
│   │   ├── logging_config.py         # Shared logger factory
│   │   ├── cache.py                  # JSON file cache for version checks
│   │   ├── system_utils.py           # run_command(), ensure_directory_exists(), OS detection
│   │   ├── shell_detection.py        # Fish/ZSH detection, repo config checks
│   │   ├── fish_setup.py             # Fish + Fisher installation
│   │   ├── package_manager.py        # uv/pip/apt package management
│   │   ├── tool_installers.py        # bat, 7zip, zstd, ctop, mcedit, zoxide, fastfetch
│   │   ├── dns_optimizer.py          # DNS detection/optimization (Hetzner/DigitalOcean)
│   │   ├── proxy_config.py           # HTTP proxy detection and configuration
│   │   ├── repository.py             # git clone/update operations
│   │   └── first_run.py              # First-run marker, initial setup wizard
│   │
│   ├── nginx/                        # Nginx configuration fragments
│   │   ├── nginx.conf                # Base nginx config
│   │   ├── nginxconfig.io/           # nginxconfig.io-generated include files
│   │   │   ├── general.conf          # General nginx settings
│   │   │   └── security.conf         # Security headers
│   │   └── html/                     # Static error pages
│   │
│   ├── fastfetch/                    # fastfetch system info config
│   │   └── config.jsonc              # Deployed to ~/.config/fastfetch/config.jsonc
│   │
│   └── README_BackUp.md              # Backup system documentation
│       NIGHTLY_CLEANUP.md            # Nightly cleanup documentation
│
├── Dockerfiles/                      # Docker image build definitions
│   ├── prepare-18/                   # Base image for Odoo 18 (multi-stage, AMD64 only)
│   │   ├── Dockerfile                # python:3.12-bookworm multi-stage build
│   │   └── requirements.txt          # 120+ Python packages for Odoo 18
│   │
│   ├── prepare-19/                   # Base image for Odoo 19 (multi-stage, AMD64 only)
│   │   ├── Dockerfile                # python:3.12-bookworm multi-stage build
│   │   └── requirements.txt          # Python packages for Odoo 19
│   │
│   ├── v16-odoo/                     # Odoo 16 runtime image
│   │   ├── Dockerfile                # FROM myodoo/prepare-v16:...
│   │   ├── build_odoo.py             # Downloads Odoo source via release.file manifest
│   │   ├── check_dockerimage_odoo.py # Checks Docker registry for latest image
│   │   ├── odoo.conf                 # Odoo configuration template (passwords as placeholders)
│   │   ├── release.txt               # Release access credentials (git-ignored on production)
│   │   ├── odoo-bin                  # Symlink/wrapper for odoo-bin
│   │   ├── ReadMe.md                 # Version-specific notes
│   │   └── bin/
│   │       └── boot                  # Container entrypoint: start|update|neutralize dispatcher
│   │
│   ├── v18-odoo/                     # Odoo 18 runtime image (same structure as v16-odoo)
│   │   ├── Dockerfile                # FROM myodoo/prepare-v16:25.02.24-3.11.11
│   │   ├── build_odoo.py
│   │   ├── check_dockerimage_odoo.py
│   │   ├── odoo.conf                 # Template: db_host=live-db, workers=3, ports 8069/8072
│   │   ├── release.txt
│   │   └── bin/
│   │       └── boot                  # Entrypoint v2.1.0
│   │
│   └── v19-odoo/                     # Odoo 19 runtime image (same structure as v18-odoo)
│
├── fish/                             # Fish shell configuration (deployed to ~/.config/fish/)
│   ├── config.fish                   # Entry point — sources conf.d/ automatically
│   ├── conf.d/                       # Numbered Fish config fragments (loaded in order)
│   │   ├── 00-env.fish               # Environment variables
│   │   ├── 10-path.fish              # PATH additions (cross-platform)
│   │   ├── 10-path.linux.fish        # PATH additions (Linux-specific)
│   │   ├── 20-tools.fish             # Zoxide init, Starship init
│   │   ├── 30-aliases-system.fish    # System aliases (syspatch, dusort, f2b, cleandlog)
│   │   ├── 30-aliases-system.linux.fish  # Linux-specific system aliases
│   │   ├── 31-aliases-git.fish       # Git aliases (gst, gco, gcmsg, gp, gl)
│   │   ├── 32-aliases-docker.fish    # Docker aliases (dps, dpi, dkvol, dkstop, dco*)
│   │   ├── 33-aliases-backup.fish    # Backup/update aliases (dobk, doup, edbk, edup)
│   │   ├── 34-aliases-nginx.fish     # Nginx aliases (cdngx, ngx+, ngx-, ngx#, ngxr, ngx!)
│   │   ├── 35-aliases-odoo.fish      # Odoo aliases (odoo-shell, odoo-logs, pg-shell)
│   │   ├── 40-completions.fish       # Shell completions
│   │   └── 50-prompt.fish            # Startup message / prompt behaviour
│   └── functions/
│       └── linux/                    # Linux-specific Fish functions
│
├── config/                           # Legacy config templates (pre-scripts/ era)
│   ├── backup_config.yaml            # Alternative backup config (zstd-based, encryption)
│   ├── backup_credentials.yaml       # Credentials file (git-ignored on production)
│   └── backup_credentials.yaml.example  # Credentials template
│
├── docs/                             # Documentation directory
│
├── worktrees/                        # Git worktree support directory
│
├── .planning/                        # GSD planning documents
│   └── codebase/                     # Codebase analysis (this directory)
│
├── .claude/                          # Claude Code project instructions
│   └── CLAUDE.md
│
└── .gitignore                        # Excludes __pycache__/, *.pyc
```

## Directory Purposes

**`scripts/`:**
- Purpose: All operational scripts that are deployed to server home directories
- Contains: Python scripts, Bash scripts, YAML config templates, `.env` secrets template
- Key files: `container2backup.py`, `update_docker_odoo.py`, `nightly-cleanup.sh`, `restore-zip.sh`, `server_hardening.py`
- Note: Files here are the *source*; `getScripts.py` copies them to `~/` on the target server

**`scripts/lib/`:**
- Purpose: Reusable Python modules supporting `getScripts.py`
- Contains: 12 module files covering: caching, constants, DNS, Fish setup, logging, package management, proxy, repository management, shell detection, system utilities, tool installation, first-run wizard
- Key files: `constants.py` (repo URL, branch, DNS servers), `repository.py` (git clone/update)

**`Dockerfiles/`:**
- Purpose: Docker image build definitions for all supported Odoo versions
- Contains: Two image tiers — `prepare-N` (base system image), `vN-odoo` (Odoo runtime image)
- Key files: `Dockerfile`, `build_odoo.py`, `odoo.conf`, `bin/boot`

**`fish/`:**
- Purpose: Fish shell environment deployed to operators
- Contains: Numbered config fragments in `conf.d/`, entry point `config.fish`
- Loaded order: 00 (env) → 10 (path) → 20 (tools) → 30-35 (aliases) → 40 (completions) → 50 (prompt)

**`config/`:**
- Purpose: Alternative/legacy configuration templates
- Contains: `backup_config.yaml` (zstd + encryption variant), credentials template
- Status: Supplementary to `scripts/container2backup.yaml`; kept for server deployments using the legacy backup path

## Key File Locations

**Entry Points:**
- `getScripts.py`: Server provisioning bootstrap — run once at install, re-run for updates
- `scripts/container2backup.py`: Backup system — invoked by cron or `dobk` alias
- `scripts/update_docker_odoo.py`: Container update orchestrator — invoked by `doup` alias
- `scripts/nightly-cleanup.sh`: Memory-based cleanup — invoked by cron at 3:00 AM
- `scripts/restore-zip.sh`: Restore tool — invoked manually with positional arguments

**Configuration Templates (copy to `~/` before use):**
- `scripts/container2backup.yaml`: Backup config — databases, retention, compression, rsync
- `scripts/docker2update.yaml`: Update config — containers, update type (F/M/N), ports, credentials
- `scripts/hardening_config.yaml`: Security hardening rules
- `scripts/.env.example`: Runtime secrets template

**Docker Build:**
- `Dockerfiles/prepare-18/Dockerfile`: Base image — all Python/system deps, multi-stage
- `Dockerfiles/v18-odoo/Dockerfile`: Odoo 18 runtime image — FROM prepare base
- `Dockerfiles/v18-odoo/build_odoo.py`: Odoo source downloader — reads `release.file` CSV
- `Dockerfiles/v18-odoo/bin/boot`: Container entrypoint dispatcher
- `Dockerfiles/v18-odoo/odoo.conf`: Odoo config template

**Shell Aliases:**
- `fish/conf.d/32-aliases-docker.fish`: Docker management aliases
- `fish/conf.d/33-aliases-backup.fish`: Backup/update shortcut aliases
- `fish/conf.d/34-aliases-nginx.fish`: Nginx management aliases
- `fish/conf.d/35-aliases-odoo.fish`: Odoo container aliases

**Library:**
- `scripts/lib/constants.py`: Version number, default branch (`2026`), DNS servers, repo URL
- `scripts/lib/repository.py`: `clone_or_update_repo()` — git operations
- `scripts/lib/package_manager.py`: uv/pip/apt package lifecycle

## Naming Conventions

**Files:**
- Python scripts: `snake_case.py` (e.g., `container2backup.py`, `update_docker_odoo.py`)
- Shell scripts: `kebab-case.sh` (e.g., `nightly-cleanup.sh`, `restore-zip.sh`, `ssl-renew.sh`)
- Fish config fragments: `NN-category-subcategory.fish` where NN is a two-digit load-order prefix
- YAML configs: `component2action.yaml` or `component_config.yaml`
- Dockerfiles: directory named `vN-odoo/` for runtime images, `prepare-N/` for base images

**Directories:**
- Odoo version dirs: `v16-odoo/`, `v18-odoo/`, `v19-odoo/` (runtime) and `prepare-18/`, `prepare-19/` (base)
- Library: `lib/` under `scripts/`
- Aliases by domain: `30-aliases-system`, `31-aliases-git`, `32-aliases-docker`, etc.

**Python:**
- Functions: `snake_case` (e.g., `create_backup`, `process_container`, `copy_scripts`)
- Classes: `PascalCase` (e.g., `CommandError`, `InstallationError`, `Stats`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `SCRIPT_VERSION`, `CACHE_DIR`, `DEFAULT_BRANCH`)
- Private helpers: `_snake_case` with leading underscore (e.g., `_validate_identifier`, `_IDENT_RE`)

**YAML keys:**
- `snake_case` for all keys (e.g., `retention_days`, `sql_container`, `only_sql_dump`)

## Where to Add New Code

**New operational script (backup, maintenance, monitoring):**
- Implementation: `scripts/<name>.py` or `scripts/<name>.sh`
- Add to `copy_scripts()` list in `getScripts.py:3293` so it gets deployed to `~/`
- Add Fish alias in `fish/conf.d/33-aliases-backup.fish` (or appropriate domain file)
- Document in `ReadMe.md`

**New Fish alias:**
- System/general: `fish/conf.d/30-aliases-system.fish`
- Git: `fish/conf.d/31-aliases-git.fish`
- Docker: `fish/conf.d/32-aliases-docker.fish`
- Backup/update: `fish/conf.d/33-aliases-backup.fish`
- Nginx: `fish/conf.d/34-aliases-nginx.fish`
- Odoo: `fish/conf.d/35-aliases-odoo.fish`

**New Odoo version support:**
- Base image: `Dockerfiles/prepare-N/Dockerfile` (copy `prepare-18/` and adjust Python version + packages)
- Runtime image: `Dockerfiles/vN-odoo/` (copy `v18-odoo/` and update `FROM` line + `odoo.conf`)
- No changes to `getScripts.py` needed — update scripts work via `docker2update.yaml`

**New library module for getScripts.py:**
- Implementation: `scripts/lib/<module_name>.py`
- Register in `scripts/lib/__init__.py` `__all__` list
- Import in `getScripts.py` where needed (currently most logic is duplicated inline)

**New package to install on servers:**
- UV tools: add to `packages.txt` under `# UV tool packages`
- pip packages: add to `packages.txt` under `# PIP packages`
- System packages: add to `packages.txt` under `# System packages`

**New backup config option:**
- Define in `scripts/container2backup.yaml` template
- Read it in `container2backup.py` `__main__` block or `create_backup()` with `config.get('section', {}).get('key', default)`

**New container update step:**
- Modify `process_container()` in `scripts/update_docker_odoo.py:535`
- Add new YAML field to `scripts/docker2update.yaml` with documentation comment

## Special Directories

**`scripts/__pycache__/`:**
- Purpose: Python bytecode cache
- Generated: Yes
- Committed: No (excluded via `.gitignore`)

**`__pycache__/` (root):**
- Purpose: Python bytecode cache for `getScripts.py` imports
- Generated: Yes
- Committed: No (excluded via `.gitignore`)

**`.planning/codebase/`:**
- Purpose: GSD (Get Stuff Done) codebase analysis documents
- Generated: By GSD map-codebase command
- Committed: Yes (planning artifacts)

**`.claude/`:**
- Purpose: Claude Code project-specific instructions (`CLAUDE.md`)
- Generated: No
- Committed: Yes

**`worktrees/`:**
- Purpose: Git worktree support for parallel branch work
- Generated: On demand
- Committed: Empty directory marker only

**`config/`:**
- Purpose: Legacy/alternative configuration templates (backup_config.yaml uses zstd+encryption path)
- Generated: No
- Committed: Yes (templates only; `backup_credentials.yaml` is git-ignored on production)

---

*Structure analysis: 2026-05-26*
