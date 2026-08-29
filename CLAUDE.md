# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Central Development Instructions

### Core Development Principles

**IMPORTANT: Always respond in German and start with "Aye, Aye Captain". All code documentation and commands must be written in English only.**

### Git Push Strategy

**Dual-remote — always push to both:**

```bash
git push origin 2026      # GitLab: gitlab.ownerp.io
git push upstream 2026    # GitHub: github.com/equitania/myodoo-docker.git
```

Both repositories must be kept in sync for all commits. Replace `2026` with the
current working branch — `git branch --show-current` is authoritative; a branch
name hardcoded in documentation goes stale (this rule previously lived in
`gitbase/CLAUDE.md` and still said `2025` in August 2026).

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

**CRITICAL DATE HANDLING**: Never hardcode a date. Take today's date from the
environment information and write it as DD.MM.YYYY.

**UTF-8 ENCODING REQUIREMENT**:
1. **Always use UTF-8 encoding** for all strings, file operations, and text processing
2. **International character support**: Handle German umlauts (ä, ö, ü), special quotes („“, ‚‘), and other Unicode characters correctly
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

# Add an entry or change a field, guided (the only writing tool here)
wiz    # ~/ownerp_wizard.py — asks which configuration; wizup/wizbk go straight
       # there. Validates before it replaces anything; refuses without a
       # terminal; never removes an entry

# Maintenance cron: what runs when, and when it last ran
docron # ~/ownerp_cron.py — bare call only reports; editing via `konsole` or
       # --set/--schedule, --enable, --disable

# The whole server on one page
dostat  # ~/ownerp_state.py — instances, backup ages, cron, readiness checks.
        # Exit 0 clean / 1 attention / 2 broken; --json for monitoring
konsole # ~/ownerp_console.py — the same, full screen, and editable. Starts
        # nothing: no updates, no backups, no container operations
```

### Docker Management Aliases

```bash
# Container management
dps       # Containers as a table: name, image, status, ports
dpsall    # The same plus ID, command and creation time
          # Both are fish functions over docker_table.py; ports are shortened
          # (127.0.0.1:11600->8069/tcp becomes 11600→8069) and a bind that is
          # NOT loopback keeps a visible, coloured marker (*:8080→80)
dk        # Docker shortcut
dkstop    # Stop all containers
dkrm      # Remove all containers

# Image management
dpi       # Images as a table: repository:tag, ID, size, age. Ages are
          # shortened (4mo) and marked once an image passes 90 days;
          # dangling images are greyed and counted
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
cleandlog # Truncate container logs (--dry-run reports without writing).
          # Reads the data-root from `docker info`; never deletes a log file
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

The scripts and their feature lists are documented in
**`docs/COMPONENTS.md`** — read it when changing a component or when you need an
exact version or feature set. Main entry points: `getScripts.py` (installation
and update), `container2backup.py` (backups), `update_docker_myodoo.py`
(container updates), `restore-zip.sh`, `ssl-renew.sh`.
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