# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Central Development Instructions

### Core Development Principles

**IMPORTANT: Always respond in German and start with "Aye, Aye Captain". All code documentation and commands must be written in English only. Always use context7.**

### Docker Resource Management (CRITICAL SAFETY RULE)

**NEVER delete Docker resources (images, volumes, containers, networks) without explicit verification that they belong to the current project.**

When cleaning Docker resources:
1. **Always list and verify first**: Show what will be deleted and ask for confirmation
2. **Use project-specific filters**: Only target resources with project-related names/labels
3. **Never use global cleanup commands** like:
   - `docker system prune -a`
   - `docker volume prune`
   - `docker image prune -a`
   Without project-specific filters

**Safe Docker cleanup pattern**:
```bash
# List project-specific containers
docker ps -a | grep -E "(myodoo|odoo)"

# Remove only specific, verified containers
docker rm container_name_1 container_name_2

# List project-specific volumes
docker volume ls | grep -E "(myodoo|odoo)"

# Remove only specific, verified volumes  
docker volume rm volume_name_1 volume_name_2

# For images, always use specific image names
docker rmi myodoo:16 myodoo:18
```

### Git Commit Prefix Rules
- **[ADD]**: Use for new features or extensions
- **[CHG]**: Use for modifications or changes in existing code  
- **[FIX]**: Use for bug fixes

**Version Management**: If the header of the respective program contains a version number and a date, the version number should be incremented, and the date should be updated to today's date.

**CRITICAL DATE HANDLING**: 
1. **NEVER use hardcoded dates from previous years** - Today is June 24, 2025, not 2024!
2. **Always query current date**: Check environment information for today's date
3. **Use DD.MM.YYYY format**: (e.g., 24.06.2025)
4. **Double-check month and year**: Verify against environment date information

**UTF-8 ENCODING REQUIREMENT**:
1. **Always use UTF-8 encoding** for all strings, file operations, and text processing
2. **International character support**: Handle German umlauts (ä, ö, ü), special quotes („", ‚'), and other Unicode characters correctly
3. **File I/O**: Ensure all file operations use UTF-8 encoding by default
4. **String parsing**: Use Unicode-aware string functions for international text processing

### Essential Development Workflow
1. **Python Version**: Python 3.x required for all scripts
2. **Configuration**: YAML-based configuration (container2backup.yaml, docker2update.yaml)
3. **Error Handling**: Always include proper error handling and logging
4. **Shell Aliases**: Extensive ZSH aliases available after running getScripts.py

## Repository Overview

This is a Docker-based infrastructure repository for Odoo deployments maintained by Equitania Software GmbH. The primary focus is on:
- **Docker management scripts** for automated backup and updates
- **Nginx configurations** for reverse proxy setups
- **SSL/TLS management** with Let's Encrypt integration
- **System administration tools** and shell aliases

## Key Commands and Usage

### Initial Setup

```bash
# First-time installation
git clone https://github.com/equitania/myodoo-docker.git
cp myodoo-docker/getScripts.py /root/
./getScripts.py

# Branch-specific installation (e.g., 2026 branch)
cd $HOME && rm -rf myodoo-docker && rm -rf nginx-conf && \
  git clone -b 2026 https://github.com/equitania/myodoo-docker.git && \
  cp myodoo-docker/getScripts.py $HOME && \
  $HOME/getScripts.py && source ~/.zshrc

# DNS optimization (standalone)
./getScripts.py --dns-check
```

### Backup Management

```bash
# Run backup (uses container2backup.py)
dobk

# Edit backup configuration
edbk  # Edit YAML configuration

# View backup directory
llbk

# Manual backup with specific options
python3 ~/container2backup.py                    # Full backup
python3 ~/container2backup.py --sql-only         # SQL-only backup
python3 ~/container2backup.py --odoo mycontainer # Specific container only
```

**Backup Configuration (container2backup.yaml)**:

The authoritative, commented template is `scripts/container2backup.yaml` — read that
file before writing anything that parses this config. The keys below are the ones
`container2backup.py` actually reads; there is no `odoo_instances`, no `backup_folder`
and no `db_pass` (encryption credentials come from a `.env` file, not from the YAML).

```yaml
defaults:
  retention_days: 14
  db_user: ownerp
  backup_path: /opt/backups     # base path; DB archives land in <backup_path>/docker
  temp_path: /tmp/odoo_backup
  stream: false                 # true: pipe straight into one .tar.zst (large filestores)
  compression:
    format: "7z"                # Options: 7z, zip, gzip, zstd
    level: 5                    # Compression level (0-9 for 7z/zip)

services:                       # system-wide backups, independent of databases
  nginx:
    enabled: true
    source_path: /etc/nginx
    backup_path: nginx          # subdirectory under defaults.backup_path
    retention_days: 7

databases:                      # NOT `odoo_instances`
  - name: equitania             # database name
    sql_container: equitania-db
    data_container: equitania-odoo
    retention_days: 5
    only_sql_dump: false        # true: skip the filestore
    stream: true                # overrides defaults.stream
    fast_report:
      enabled: false
      path: /opt/fast-report/live
```

### Container Updates

```bash
# Update Docker containers
doup

# Edit update configuration
edup  # Edit YAML configuration

# Manual update
python3 ~/update_docker_myodoo.py

# Validate both YAML configurations (read-only, never writes)
doval  # ~/ownerp_validate.py — exit 0 = no errors, 1 = at least one error,
       # 2 = file missing/unreadable/unparseable or PyYAML absent
```

### Docker Management Aliases

```bash
# Container management
dps       # List running containers
dpsall    # Extended container listing
dk        # Docker shortcut
dkstop    # Stop all containers
dkrm      # Remove all containers

# Image management
dpi       # Show Docker images
dkrmi     # Remove all images

# Volume management
dkvol     # Check Docker volumes
dkrmv     # Remove all volumes

# System cleanup (USE WITH CAUTION)
dkprs     # Docker system prune
dkprv     # Docker volume prune
dkprf     # Complete system cleanup
dkprfa    # Complete cleanup including volumes
```

### Nginx Management

```bash
# Navigation and control
cdngx     # Go to nginx config directory
ngx+      # Start nginx
ngx-      # Stop nginx
ngx#      # Restart nginx
ngxr      # Reload nginx configuration
ngxs      # Show nginx status

# Configuration management
ngx!      # Test nginx configuration
ngxset    # Set nginx configuration
showcerts # Show SSL certificates
```

### System Maintenance

```bash
# Updates and patches
syspatch  # Comprehensive system update (apt-based)
prepatch  # Prepare update in screen session
ups       # Update ownERP scripts

# Cleanup and monitoring
cleandlog # Clean Docker logs
dusort    # Show directory sizes sorted
f2b       # Fail2ban status

# DNS optimization
./getScripts.py --dns-check  # Check and optimize DNS configuration
```

## High-Level Architecture

### Directory Structure
```
myodoo-docker/
├── scripts/
│   ├── container2backup.py    # Automated backup system
│   ├── update_docker_myodoo.py # Container update management
│   ├── restore-zip.sh         # Backup restoration
│   └── ssl-renew.sh          # SSL certificate renewal
├── Dockerfiles/
│   ├── v12-myodoo/           # Odoo 12 Docker config
│   ├── v13-myodoo/           # Odoo 13 Docker config
│   ├── v14-myodoo/           # Odoo 14 Docker config
│   ├── v16-odoo/             # Odoo 16 Docker config
│   ├── v18-odoo/             # Odoo 18 Docker config
│   └── ngx-conf/             # Nginx configurations
├── config/
│   ├── container2backup.yaml  # Backup configuration
│   └── docker2update.yaml    # Update configuration
└── getScripts.py             # Main installation script
```

### Key Components

#### 1. getScripts.py (v9.11.0)
- **Purpose**: Main installation and update script
- **Features**:
  - Lean console output: without `-v` only server-optimization status,
    warnings and errors reach the screen; every INFO line and all child
    process output (apt, git, curl) go to `~/getscripts.log`. A failed command
    puts the tail of its output back on screen. `ups -v` forwards the flag
  - Installs all dependencies and tools
  - Configures ZSH with extensive aliases
  - Sets up Docker management environment
  - Supports branch-specific installations
  - Includes smart version checking and caching
  - DNS configuration check and optimization
  - Detects Hetzner DNS issues with DigitalOcean
  - Supports systemd-resolved, resolvconf, and direct DNS config

#### 2. container2backup.py (v4.3.0)
- **Purpose**: Automated backup system for Odoo deployments
- **Features**:
  - SQL + Filestore backup
  - Multiple compression formats (7z, zip, gzip, zstd)
  - Optional AES-256 encryption
  - Automatic retention management
  - Service backups (nginx, letsencrypt)
  - FastReport integration

#### 3. update_docker_myodoo.py (v4.0.6)
- **Purpose**: Automated Docker container updates
- **Features**:
  - YAML/CSV configuration support
  - Container health checks
  - Automated restart management
  - Module updates for Odoo

#### 4. update_docker_odoo.py (v5.11.0)
- **Purpose**: Automated Docker container updates for v16+ Odoo instances
  (image rebuild, container re-creation, module update), driven by
  `docker2update.yaml`
- **Features**:
  - Full run log per container in the build folder, with configurable
    retention (`log_retention_days`, default 90 days)
  - Run history in `~/update-history.jsonl` (one line per container run,
    `defaults.history_retention_days`, 365 default, 0 = forever)
  - `-s` repeatable/comma-separated and stronger than `active: false`
  - `--type M|F|N` overrides the YAML mode for one run, `--comment TEXT` is
    recorded in the history and the run log header
  - Proxy support (`defaults.proxy`, `pre_build_files`); calls
    `odoo_build_cache.py sync` before the build

#### 5. ownerp_tui.py (v1.0.0)
- **Purpose**: curses TUI for picking systems, mode and a run comment
- **Started with**: `tui`, or `doup` when `~/.ownerp_tui_default` exists
- **Never writes to the YAML** — `active:`/`type:` are read as the
  pre-selection, the run is passed as arguments (`-s`, `--type`, `--comment`)
- **One runner invocation per mode group**, sequential, worst exit code wins
- **Refuses without a TTY**, on `TERM=dumb`, or below 80×20 — cron always gets
  the classic runner

#### 6. odoo_build_cache.py (v1.5.0)
- **Purpose**: Host-side cache of Odoo release archives, shared by every instance
- **Why**: `build_odoo.py` runs inside the build container and re-downloads all
  several hundred archives on every build; the Docker layer holding them is
  removed by the `docker system prune -f` after each `doup`
- **Cache key is the file name** — release archives carry their version, so a
  name that is present is by definition the right content (no revalidation)
- **Commands**: `sync <build-dir> [--reference <repo Dockerfile>]` (called by
  update_docker_odoo.py before the build), `gc [--days 30]` (weekly via cron),
  `stats`
- **Location**: `/opt/odoo-build-cache`, partitioned by release URL
- **Never blocks a build**: anything the cache did not supply is downloaded by
  `build_odoo.py` exactly as before
- **Also maintains the build folder's Dockerfile**, because nothing else does:
  `sync_build_scripts()` distributes `build_odoo.py` and `bin/` but never the
  Dockerfile — it is the customer's file. Without this, a directive added to the
  repository later (the March 2026 `HEALTHCHECK`) never reaches an installation
  created before it. With `--reference` it inserts image directives that are
  **entirely absent** (`VOLUME`, `HEALTHCHECK`, `EXPOSE`) ahead of the
  `ENTRYPOINT`, aligns an `ADD` with the reference's `COPY` where the two are
  the same operation (v1.4.0, see below), and only reports anything else that
  differs. It never touches `FROM` (owned by `check_dockerimage_odoo.py`), takes
  a `.bak_<timestamp>` first, and refuses the write when the before/after
  instruction comparison shows an unintended change
- **The one content rewrite: `ADD` → `COPY`** (v1.4.0). The repository moved
  `bin/` from `ADD` to `COPY` in July 2026 (ADD auto-extracts tar archives), and
  every older installation reported that difference on every `doup` forever.
  Applied only when the source is a plain local path — **never** for a remote
  URL (ADD fetches it), a local archive (ADD unpacks it), a glob (may be
  either), or an unknown flag — **and** the reference carries exactly that
  `COPY`. The rewrite must be announced to `_dockerfile_regression()`, which
  accepts only that exact pair
- **Also maintains the build folder's `odoo.conf`** (v1.5.0), which is never
  distributed either — it holds `admin_passwd` and `db_password`. Only
  `MANAGED_CONF_KEYS` are filled in, only from the repository template beside
  the reference Dockerfile, and only where the customer set no value of their
  own (**an empty value counts as none** — Odoo's `config.py` deletes an empty
  entry and falls through to its default). `_conf_regression()` refuses the
  write if any other setting would change, vanish or appear.
  `http_interface` is the first managed key: Odoo 19 warns when it is unset and
  **Odoo 20 defaults it to `127.0.0.1`**, which would leave every container
  unreachable through its published port

#### 7. ownerp_validate.py (v1.0.0)
- **Purpose**: Read-only validation of `docker2update.yaml` and
  `container2backup.yaml` against their declared schemas — no other script
  writes as much unattended config as these two, so a typo surfaces at `doval`
  time, not mid-run
- **Checks**: structure, required fields, types, enums, port form (`11000`,
  `"11000"`, `"127.0.0.1:11000"`, `"[::1]:11000"`), duplicate container/database
  names and duplicate host ports **among active entries only**, whether
  configured paths exist (a warning, not an error), and unknown keys with a
  suggestion from the closest known name (also a warning)
- **`active: false` blocks are checked in full**, but their findings are
  downgraded to warnings prefixed `(inactive)` — a parked block never turns
  the exit code red
- **Exit codes**: `0` no errors (**warnings may be present and never affect the
  exit code**), `1` at least one error, `2` a file is missing, unreadable,
  unparseable, or PyYAML is absent
- **Never writes**, and never prints the value of a key whose name ends in
  `password`
- **`update_docker_odoo.py --validate` and `container2backup.py --validate`**
  both delegate to it

### Development Patterns

1. **Configuration Management**: All tools use YAML as primary configuration format
2. **Error Handling**: Comprehensive logging with proper error messages
3. **Version Control**: Version numbers in script headers (format: X.Y.Z)
4. **Date Format**: DD.MM.YYYY in German format
5. **Encoding**: UTF-8 for all file operations
6. **Shell Integration**: Extensive ZSH aliases for productivity

### Testing and Validation

```bash
# Test backup configuration
python3 ~/container2backup.py --dry-run

# Validate nginx configuration
ngx!

# Check Docker container health
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Test SSL certificate renewal
./ssl-renew.sh --dry-run
```

## Important Notes

1. **Docker Safety**: Always verify containers/volumes belong to project before deletion
2. **Backup Retention**: Default 14 days, configurable in YAML
3. **Encryption**: Available only with 7z format, uses AES-256
4. **Branch Management**: Use specific branches (e.g., 2026) for major versions
5. **Permissions**: Most scripts require root or sudo access
6. **Shell**: ZSH is the default shell after installation