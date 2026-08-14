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

#### 1. getScripts.py (v9.12.0)
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

#### 2. container2backup.py (v4.8.0)
- **Purpose**: Automated backup system for Odoo deployments
- **Features**:
  - SQL + Filestore backup
  - Multiple compression formats (7z, zip, gzip, zstd)
  - Optional AES-256 encryption
  - Automatic retention management
  - Service backups (nginx, letsencrypt)
  - FastReport integration
  - `--validate` delegates to `ownerp_validate.py` (exit 2 when it is not
    installed — a backup tool must never report "cannot check" as success)

#### 3. update_docker_myodoo.py (v4.0.6)
- **Purpose**: Automated Docker container updates
- **Features**:
  - YAML/CSV configuration support
  - Container health checks
  - Automated restart management
  - Module updates for Odoo

#### 4. update_docker_odoo.py (v5.12.0)
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

#### 5. odoo_build_cache.py (v1.5.0)
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

#### 6. ownerp_validate.py (v1.0.0)
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

#### 7. ownerp_wizard.py (v1.2.0)
- **Purpose**: Guided editing of `docker2update.yaml` **and**
  `container2backup.yaml` — add an entry, or change one field of an existing
  one. `wiz` asks which file, `wizup`/`wizbk` go straight there
- **The only tool in this set that writes to a customer's configuration**, so
  the write path is the substance: timestamped backup → build in memory →
  temporary file **in the same directory** → `ownerp_validate.py` runs against
  that file → **error: temp file and backup removed, original byte-identical**
  → **clean: `os.replace()`**, backup kept. Warnings never block (a build
  folder that does not exist yet is the normal state for a new instance)
- **Suggests from the file itself**: the next free host port across both port
  fields of every entry (active or not), a unanimous `db_user`/`db_host`, the
  shared build-folder pattern with the new name substituted, the shared image
  prefix. Enter takes the value in brackets; a disagreement suggests nothing
  rather than guessing
- **Field edits address the line the positioned loader recorded** — not a
  forward text search like `save_updated_config()`, which can land in the
  following entry. Indentation and any trailing comment on that line survive
- **Refuses** instead of guessing: no TTY (naming `edup`), no
  `ownerp_validate.py` beside it (naming `ups`), an unparseable configuration
  (pointing at `doval`). A duplicate container/database name is rejected at the
  prompt, not at validation
- **Scalars only** (`pre_build_files` and `proxy` are shown, never edited),
  **never removes an entry**, and `db_password` is never suggested, never
  echoed, and masked in every summary
- **Its one write outside the YAML** is the empty build folder it offers to
  create — nothing is copied into it; populating a build folder belongs to
  `odoo_build_cache.py`
- **The backup side (v1.1.0)**: `container2backup.yaml` had no editor at all
  before this. `safe_write()` picks the schema from the kind — validating a
  backup config against the update schema would reject every field it has and
  accept none it lacks, so the wrong one there is a tool that can never write
  that file
- **The backup form suggests from `docker2update.yaml`**: which Postgres
  container holds a database and which Odoo container holds its filestore are
  already recorded as `db_host` and `container_name`. Naming the database fills
  in the rest. Two update entries on one database suggest nothing — that is an
  error the validator reports, and a guess in front of someone fixing it is
  worse than a blank field
- **A write API with no terminal in it** (v1.1.0): `load_config()`,
  `add_entry()`, `set_field()`, each returning a `WriteResult`. The console of
  stage 3 consumes it and the interactive wizard runs on it, so the path used
  less often cannot rot unnoticed. Duplicate names and a port's localhost bind
  address are handled there rather than in the prompts
- **`set_fields()` — a whole form in one write** (v1.2.0). A form edits an
  entry, not a field: one write per changed field would leave a `.bak-*` per
  keystroke-session and, worse, a half-applied entry when the third of five is
  rejected. The whole set is validated once and the file replaced once.
  `set_field()` is now that call with one entry in the dict
- **The order inside it is the substance, not tidiness**: a recorded line
  number describes the file as it was *read*. Replacing a line keeps every
  other number valid; inserting one shifts everything below it. So fields that
  already have a line are patched first, and only then are absent ones
  appended — each recomputing the entry's end against the lines as they now
  stand. Two absent fields in one call is the case that catches a regression
  here; one absent field passes either way
- **The prompt path now names the better route** (v1.2.0): one line saying the
  console edits the same file as a form. It stays because a terminal that
  cannot run Textual still needs it — but an operator who does not know about
  `konsole` keeps coming back to a field-at-a-time prompt

#### 8. ownerp_cron.py (v1.0.2)
- **Purpose**: Overview and guided editing of `/etc/cron.d/myodoo-maintenance` —
  the backup, cert-renewal, DNS-guard and cleanup jobs an ownERP server runs
- **Two consumers, one implementation**: `getScripts.py` prints `--brief` after
  the install summary (read-only and non-interactive, because `ups` also runs
  unattended), `ownerp_console.py` edits through this module's API, so the
  write path exists exactly once
- **Write path mirrors `ownerp_wizard.py`**: timestamped backup → build in
  memory → temp file **in the same directory** → re-parse and validate that
  file → `os.replace()`. Mode 0644 is set **before** the rename: cron silently
  ignores a group- or world-writable `cron.d` file
- **Only the named job's line is rewritten** — `_regression()` refuses the write
  if any other job would move, and untouched lines keep the template's column
  alignment byte for byte
- **Range validation is strict**: cron accepts `0 25 * * *` and then never fires
  it, so a field-count check alone would pass exactly the mistake this tool exists
  to prevent
- **A job switched off keeps its line** behind `#OWNERP-DISABLED#` rather than
  being deleted — the schedule survives for whoever switches it back on
- **Local edits are marked, not hidden**: an edit stamps `# ownerp-cron-edit:`
  into the header and `server-readiness.py` reads it, so a deliberate schedule
  change reports as "customised locally" instead of as drift. Re-running
  `setup-maintenance-cron.sh` restores the repository schedule and discards the
  customisation — that is its job, and the tool says so before it writes

#### 9. ownerp_migrate.py (v1.4.0)
- **Purpose**: One-way conversion of the legacy CSV configurations to YAML —
  `container2backup.csv` + `container2backup_path.csv` + `rsync_targets.csv` →
  `container2backup.yaml`, `docker2update.csv` → `docker2update.yaml`
- **Runs from every `ups`**, after `copy_scripts()` and **before**
  `cleanup_legacy_files()`, and is silent once there is nothing to convert
- **Why the ordering matters**: those four CSVs used to be listed in
  `cleanup_legacy.txt`, which deletes what it names on a fresh Fish install —
  the very run that lifts an old server onto the new stack. The configuration
  was destroyed by the upgrade that needed to read it. They are off that list;
  this script owns them
- **Never overwrites an existing YAML** — writes `<name>.yaml.from-csv` beside
  it instead and leaves the CSV in place for comparison
- **Never installs a config that fails validation** — `ownerp_validate.py` runs
  against the generated file first (with the matching `--backup`/`--update`
  flag). Errors block, warnings never do
- **Never deletes**: consumed CSVs move to `$HOME/legacy-csv/<timestamp>/`,
  created `0700`; generated YAML is written `0600` — `docker2update.csv` carries
  database passwords in clear text
- **A commented-out CSV row stays switched off**: `active: false` in
  `docker2update.yaml`; `container2backup.yaml` has no such key, so those rows
  become a commented-out block rather than vanishing or silently activating
- **`--from-docker` (v1.1.0)**: rebuilds both configs from the running
  containers, for servers whose CSVs were already deleted. `docker inspect`
  yields 12 of the 14 update columns exactly; the database name comes from
  `psql -l` in the paired Postgres container. What is unrecoverable (`type`,
  `delay_time`, `translate`, `retention_days`) gets a documented default **and**
  an entry in the `REVIEW BEFORE USE` block at the top of the file — a guess
  that looks like a fact would update the wrong database. **Opt-in only**;
  never runs from `ups`
- **Each review point knows which file it concerns** (v1.3.0). `type`,
  `delay_time`, `odoo_version` and the build folder do not exist in a backup
  configuration; `retention_days` does not exist in an update one. A `ReviewNote`
  carries `update`, `backup` or `both`, `_provenance()` filters on it, and the
  per-file count follows — a header stating seven points while listing three
  sends the reader hunting for four that were never printed
- **Silent on an empty run** (v1.4.0). `print_results()` always was; `main()`
  printed "Nothing to migrate" underneath it anyway, on every `ups`. A server
  whose CSVs were converted long ago is then told forever, which is how the
  block stops being read on the one server where it says something. `--quiet`
  (what `ups` passes) suppresses only the empty case
- **An instance missing from the backup file is named, not omitted quietly**
  (v1.3.0). A backup entry needs a database name; without one no row is written.
  Saying so is the point — the file otherwise looks complete while one
  production database is not backed up, which surfaces only when a restore is
  needed

#### 10. ownerp_state.py (v1.0.0)
- **Purpose**: The whole server on one page — instances, backup ages,
  maintenance jobs, readiness checks. Started with `dostat`; stage 1 of the
  console design in `docs/superpowers/specs/2026-08-13-ownerp-console-design.md`
- **Two consumers, one collector**: `dostat` is this file's own `main()`, and
  `ownerp_console.py` is the second. It therefore carries **no
  interface import** — a data layer that knew about its UI could not be tested
  without it, and `dostat` could not exist
- **Every source is optional**, because a status tool is read on a broken
  server. Docker down, PyYAML absent, a YAML that does not parse, `/etc`
  unreadable — each costs exactly one section, states its reason, and leaves
  the rest of the page standing
- **"Not asked" is not "down"**: skipping the Docker query used to leave an
  empty status string that rendered as a stopped container. Container state is
  three-valued (`True`/`False`/`None`) and `worst()` never counts an unknown as
  a fault
- **Never writes** — no `os.replace`, no `chmod`, no `remove`. Configuration
  changes stay with `ownerp_wizard.py`, cron changes with `ownerp_cron.py`; the
  test suite fails if a write call or a UI import appears here
- **Does not reimplement the readiness checks**: `collect_health()` runs
  `server-readiness.py`'s own `run_checks()`. A second opinion that drifted
  from the first would be worse than none
- **Exit code** `0` clean / `1` needs attention / `2` broken, plus `--json`, so
  cron and monitoring never parse the text

#### 11. ownerp_console.py (v1.1.0)
- **Purpose**: The ownERP console — server state and configuration editing in
  a full-screen interface. Started with `konsole`; stage 3 (last) of
  `docs/superpowers/specs/2026-08-13-ownerp-console-design.md`
- **Owns no data and no write path**: facts from `ownerp_state.py`,
  configuration changes through `ownerp_wizard.py`, cron changes through
  `ownerp_cron.py`. The suite fails if a write call appears here — a second
  implementation of backup/validate/replace is a second place for it to drift
- **Starts nothing**: no updates, no backups, no container operations. That is
  what lets it skip process supervision, a cancel path and a log pane
  entirely; every action finishes in under a second or fails with a message
- **Never the only route**: `dostat`, `wiz`, `docron`, `doval` cover the same
  ground without Textual. Missing library → one re-exec through
  `uv run --with`, then a message naming those four
- **Installing it is `ups`'s job, and it has to be checked there** (v1.1.1,
  14.08.2026). A server ran `konsole` after many updates and got "Textual is
  not available". `warm_console_cache()` existed, but ran `python3 -c pass` —
  which proves an environment can be built and imports nothing the console
  needs, so it could not fail. It imports `textual` and `yaml` now, installs a
  missing uv instead of skipping silently, and writes the outcome to the
  **install report**: every failure path used to be a `logger` call, and under
  the lean output policy those are invisible on screen
- **The message names `ups`, never `pip install --user`** — Debian 12+ refuses
  that outright (externally-managed-environment). It also separates a missing
  uv (an update fixes it) from an unreachable PyPI (nothing typed there will),
  and a non-zero `uv run` falls through to it rather than exiting on uv's own
  error
- **`uv run --with` is an ISOLATED environment** — the system site-packages
  are not on its path. PyYAML is therefore declared next to Textual; without
  it every section reported "unknown", which looks exactly like a broken
  server. `getScripts.py` warms that cache at install time and parses the
  specs out of this file rather than duplicating them
- **Textual pinned `>=8,<9`**: a widget API is not stable across majors
- **Select a row → an action menu, ctop-style** (v1.1.0): a small box at the
  top left over the table it acts on, one letter per action. It is placed
  there rather than centred so the row it belongs to stays visible. `ACTIONS`
  says what each tab offers; the System tab has none, because readiness
  findings are facts, not settings
- **`[e]` in a `Label` is Rich markup for a style tag** and renders as
  nothing. Every menu line silently lost its key, which is the whole menu —
  `markup=False`, and a test that reads what is on screen rather than what is
  in `ACTIONS`
- **The menu clips, it does not wrap**: "database only, no filest" is not a
  shorter way of saying the same thing, it is a different sentence. Labels are
  held under `MENU_LABEL_WIDTH` by a test
- **`[e]` opens the whole entry as a form** (v1.1.0), replacing the
  pick-a-field/enter-a-value pair. What allows it is `wizard.set_fields()`: a
  form that wrote field by field could half-apply, which is exactly what the
  two modals were avoiding. A boolean is a `Switch`, typed from the
  validator's schema rather than inferred from a value that may be absent
- **The password field starts empty and means "unchanged"**: the stored value
  is never rendered, not even masked — a mask that round-trips is a mask that
  gets written back as the new password
- **The focused field's help is shown at the bottom.** The prompt wizard
  printed it per question; a form that dropped it would be prettier and less
  informative, which is not the trade being made here
- **Suggestions for a new entry run in two passes**: what can be known before
  the name is filled in at open time, and whatever the operator left blank is
  suggested once `container_name` exists — that is what turns an empty build
  folder into `$HOME/docker-builds/<name>/`. A form cannot do it in one pass
  the way a sequential prompt can
- **Still starts nothing.** "run backup now" is deliberately not in any menu:
  the console has no process supervision, no cancel path and no log pane
  precisely because it never starts anything, and a 20-minute backup behind a
  keystroke would need all three

#### 12. Login command overview (fish)
- **`fish/functions/linux/ownerp-help.fish`** prints the dozen commands an
  operator actually needs; `help` is aliased to it
- **Once per LOGIN shell**, not per interactive shell — `fastfetch` is four
  lines and can run every time, this panel is fifteen and a tmux session with
  six panes would print it six times. `status is-login` is that boundary
- **Curated, not generated** — but `tests/test_fish_help.py` asserts every
  advertised command still resolves to an alias or function, so a rename fails
  the suite instead of sending an operator to type something that is gone
- **No `odoodev` line** (14.08.2026): that CLI is workstation tooling and this
  panel is what an operator needs on a server

#### 13. docker_table.py (v1.0.0)
- **Purpose**: `docker ps` as a readable table — the renderer behind `dps` and
  `dpsall`
- **Why it exists**: the aliases piped `docker ps --format table` into `sort`,
  which sorted the **header line along with the containers**. Under a UTF-8
  locale `NAMES` collates after `ivy-odoo`, so the column titles arrived at
  the bottom of every listing. Sorting rows without the header is the whole
  reason for the file; the frame and the colours are what it does afterwards
- **The rule the port column is built around**: a shortened port must never
  hide that a port is reachable from outside. `127.0.0.1:11600->8069/tcp`
  becomes `11600→8069` because loopback is the norm here — every other bind
  keeps a visible marker (`*:8080→80`, or the literal address) and is coloured.
  A dual-stack publish that Docker prints twice is listed once
- **Degrades rather than fails**: no colour off a terminal, ASCII box
  characters when the output encoding cannot carry the frame, no truncation
  when the width is unknown (a pipe gets the full table). Docker's own error
  text and exit code are passed through — never a traceback
- **NAME and STATUS are protected, not sacred**: they are the last columns to
  be shrunk, but on a narrow terminal they *are* shrunk, because a frame three
  characters too wide wraps and the table stops being a table
- **The fish side keeps a fallback**: `__ownerp_docker_ps` falls back to
  `docker ps` + `awk` (header held back, rows sorted) when the renderer is not
  installed yet — `dps` is typed on servers where `ups` has not run
- **An alias would shadow the function.** `dps`, `dpsall` and `cleandlog` are
  functions now; nothing may reintroduce an alias under those names

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