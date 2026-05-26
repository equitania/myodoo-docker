<!-- refreshed: 2026-05-26 -->
# Architecture

**Analysis Date:** 2026-05-26

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────┐
│                    Server Administrator (CLI / Cron)                 │
└──────┬─────────────────┬────────────────────┬────────────────────────┘
       │                 │                    │
       ▼                 ▼                    ▼
┌─────────────┐  ┌────────────────┐  ┌───────────────────┐
│getScripts.py│  │container2      │  │update_docker_     │
│(Setup/Init) │  │backup.py       │  │odoo.py            │
│`getScripts  │  │`scripts/       │  │`scripts/          │
│  .py`       │  │container2      │  │update_docker_     │
│             │  │backup.py`      │  │odoo.py`           │
└──────┬──────┘  └───────┬────────┘  └────────┬──────────┘
       │                 │                    │
       ▼                 ▼                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    YAML Configuration Layer                          │
│  `scripts/container2backup.yaml`   `scripts/docker2update.yaml`     │
│  `scripts/hardening_config.yaml`   `scripts/.env`                   │
└──────┬──────────────────────────────────────────┬───────────────────┘
       │                                          │
       ▼                                          ▼
┌──────────────────────┐              ┌───────────────────────────────┐
│  Docker Engine       │              │  Odoo Dockerfiles             │
│  (containers, vols,  │              │  `Dockerfiles/v16-odoo/`      │
│   networks)          │              │  `Dockerfiles/v18-odoo/`      │
└──────────────────────┘              │  `Dockerfiles/v19-odoo/`      │
                                      │  `Dockerfiles/prepare-18/`    │
                                      │  `Dockerfiles/prepare-19/`    │
                                      └───────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| getScripts.py | Bootstrap: install tools, clone repo, configure Fish shell, deploy scripts | `getScripts.py` |
| scripts/lib/ | Modular library supporting getScripts.py | `scripts/lib/` |
| container2backup.py | YAML-driven backup of Odoo DB + filestore + services | `scripts/container2backup.py` |
| update_docker_odoo.py | YAML-driven Odoo container stop/rebuild/update/restart | `scripts/update_docker_odoo.py` |
| nightly-cleanup.sh | Memory-threshold-based container restart (cron) | `scripts/nightly-cleanup.sh` |
| restore-zip.sh | Restore backup archive into running containers | `scripts/restore-zip.sh` |
| ssl-renew.sh | Stop nginx → certbot renew → restart nginx | `scripts/ssl-renew.sh` |
| server_hardening.py | Audit and apply UFW/fail2ban/SSH/Docker hardening | `scripts/server_hardening.py` |
| cleanup-weblogs.py | Nginx access log rotation/cleanup | `scripts/cleanup-weblogs.py` |
| Dockerfiles/prepare-N | Multi-stage base image with all Python/system deps | `Dockerfiles/prepare-18/`, `Dockerfiles/prepare-19/` |
| Dockerfiles/vN-odoo | Odoo runtime image built on top of prepare image | `Dockerfiles/v16-odoo/`, `Dockerfiles/v18-odoo/`, `Dockerfiles/v19-odoo/` |
| fish/ | Fish shell configuration deployed to servers | `fish/` |
| config/ | Legacy YAML config templates for backup system | `config/` |

## Pattern Overview

**Overall:** Configuration-driven operations scripting with YAML as the control plane.

**Key Characteristics:**
- All operational scripts read YAML for configuration; no hardcoded infrastructure values in code.
- Scripts are deployed from this repo to the server home directory (`~/`) via `getScripts.py` — the repo is the source of truth, `~/*.py` are the deployed copies.
- Docker is the exclusive runtime for Odoo and PostgreSQL; scripts orchestrate Docker CLI calls (never Docker SDK).
- Two-stage Docker image build: `prepare-N` (base image with all deps) → `vN-odoo` (Odoo source via release manifest).
- Fish shell with Starship prompt is the administrative interface; aliases in `fish/conf.d/` are the user-facing entry points to the operational scripts.

## Layers

**Bootstrap/Setup Layer:**
- Purpose: First-time and ongoing server provisioning
- Location: `getScripts.py` + `scripts/lib/`
- Contains: OS package installation, Fish shell setup, tool installation (uv, bat, 7z, zoxide, ctop, mcedit, starship, fisher), repo cloning, script deployment, DNS optimization
- Depends on: Network access (PyPI, GitHub, apt repos), sudo/root
- Used by: Server administrators running initial setup or updates

**Modular Library (`scripts/lib/`):**
- Purpose: Reusable components for getScripts.py
- Location: `scripts/lib/`
- Contains: `cache.py` (JSON cache for version checks), `constants.py` (version, paths, DNS, repo URLs), `dns_optimizer.py` (Hetzner/DigitalOcean DNS detection), `fish_setup.py` (Fish + Fisher installation), `package_manager.py` (uv/pip/apt orchestration), `proxy_config.py` (proxy detection), `repository.py` (git clone/update), `shell_detection.py`, `system_utils.py`, `tool_installers.py`, `logging_config.py`, `first_run.py`
- Depends on: Standard library + requests
- Used by: `getScripts.py` (the monolith still duplicates most of this logic internally)

**Operational Scripts Layer:**
- Purpose: Day-to-day server operations (backup, update, restore, cleanup)
- Location: `scripts/`
- Contains: `container2backup.py`, `update_docker_odoo.py`, `restore-zip.sh`, `ssl-renew.sh`, `nightly-cleanup.sh`, `server_hardening.py`, `cleanup-weblogs.py`
- Depends on: YAML config files in `~/` (deployed copies), Docker CLI, system tools (7z, pg_dump, rsync)
- Used by: Cron jobs and administrators via Fish aliases

**Configuration Layer:**
- Purpose: Infrastructure parameters (container names, DB credentials, paths, retention)
- Location: `scripts/container2backup.yaml`, `scripts/docker2update.yaml`, `scripts/hardening_config.yaml`, `scripts/.env`
- Contains: YAML-structured settings per Odoo instance and database
- Depends on: Nothing
- Used by: All operational scripts at runtime

**Docker Image Layer:**
- Purpose: Odoo container build pipeline
- Location: `Dockerfiles/`
- Contains: Multi-stage Dockerfiles, `build_odoo.py` (downloads Odoo source via release manifest), `check_dockerimage_odoo.py` (registry check), `odoo.conf` (template), `bin/boot` (entrypoint script)
- Depends on: `myodoo/prepare-v16` or `myodoo/prepare-v18` base images published to Docker Hub
- Used by: `update_docker_odoo.py` (triggers `docker build`) and CI/CD

**Shell Configuration Layer:**
- Purpose: Operator productivity — aliases, prompt, path, completions
- Location: `fish/`
- Contains: `conf.d/` numbered Fish config fragments (00-env, 10-path, 20-tools, 30-aliases-*, 50-prompt), `functions/linux/`
- Depends on: Fish 4.0+, Starship, zoxide
- Used by: Server operators after `getScripts.py` deploys them

## Data Flow

### Script Deployment Flow (getScripts.py)

1. Administrator runs `getScripts.py` from home dir — entry point: `main()` (`getScripts.py:3396`)
2. `setup_environment()` (`getScripts.py:3183`) — detects home dir, checks Debian/Ubuntu, checks sudo
3. `update_repository()` (`getScripts.py:3239`) — clones/pulls `github.com/equitania/myodoo-docker` branch `2026` into `~/myodoo-docker/`
4. Fish shell + Starship + Fisher installed via `install_fish_if_needed()`, `install_starship_if_needed()`, `install_fisher_if_needed()`
5. `copy_fish_configuration()` (`getScripts.py:596`) — deploys `fish/` tree to `~/.config/fish/`
6. `copy_scripts()` (`getScripts.py:3293`) — copies `scripts/*.py` and `scripts/*.sh` to `~/`
7. `install_packages()` (`getScripts.py:3314`) — installs uv, uv tools, pip packages, system tools (bat, 7z, zstd, zoxide, ctop, mcedit, fastfetch)
8. Result: server has `~/container2backup.py`, `~/update_docker_odoo.py`, etc. ready to run

### Backup Flow (container2backup.py)

1. Cron or alias `dobk` → `~/container2backup.py` (`scripts/container2backup.py:713`)
2. Reads `~/container2backup.yaml` — container names, DB credentials, retention, compression format, temp path
3. For each database entry: validates identifiers (`_validate_identifier()`) → `create_backup()` (`scripts/container2backup.py:192`)
4. Inside `create_backup()`:
   - `docker exec <sql_container> pg_dump -U <db_user> <db_name>` → `dump.sql` in temp dir
   - `docker exec <data_container> tar c /opt/odoo/data/filestore/<db>` piped to local `tar x` → `filestore/` in temp dir
   - `compress_directory()` → 7z/zip/gzip/zstd archive at `/opt/backups/docker/<db>_<container>_dockerbackup_<timestamp>.<ext>`
5. Optional FastReport backup: `backup_fast_report()` — tarballs `/opt/fast-report/fr-<db>/`
6. Service backups: nginx (`/etc/nginx`), letsencrypt (`/etc/letsencrypt`), docker-builds (`$HOME/docker-builds`)
7. Retention cleanup: `cleanup_backups_by_pattern()` removes archives older than `retention_days`
8. Optional rsync commands from `rsync:` section of YAML

### Container Update Flow (update_docker_odoo.py)

1. Alias `doup` → `~/update_docker_odoo.py` (`scripts/update_docker_odoo.py:896`)
2. Reads `~/docker2update.yaml` — list of containers with `active: true`
3. For each active container: `process_container()` (`scripts/update_docker_odoo.py:535`)
4. Inside `process_container()`:
   - Downloads `build_odoo.py` and `check_dockerimage_odoo.py` from `rm.ownerp.io` via wget
   - Runs `check_dockerimage_odoo.py` — checks registry for latest image
   - `docker stop <container>` → `docker rm <container>` → `docker rmi <image>:latest`
   - `docker build -t <image> .` from `dockerfile_path` (contains `build_odoo.py` + `release.file`)
   - Type `F`: `docker run ... <image> update --database=...` (full module update, up to 30 min)
   - Type `M`: copies new modules only without full update
   - Type `N`: `docker run ... neutralize` then `update`
   - `docker run -d --restart=always ... <image> start` — final restart
   - `docker system prune` — cleanup dangling images

### Odoo Image Build Flow (Dockerfiles)

1. `prepare-18/Dockerfile` — multi-stage: builder installs all Python deps + wkhtmltopdf + Node.js; production stage copies only built artifacts
2. Published to Docker Hub as `myodoo/prepare-v18:<date>-<python_version>`
3. `v18-odoo/Dockerfile` — `FROM myodoo/prepare-v16:...`; runs `build_odoo.py` which reads `release.file` (CSV with module URLs) and downloads Odoo source at build time
4. Container entrypoint: `bin/boot` bash script — dispatches to `start`, `update`, or `neutralize` functions which call `odoo-bin`

### Nightly Cleanup Flow (nightly-cleanup.sh)

1. Cron `0 3 * * *` → `nightly-cleanup.sh` (`scripts/nightly-cleanup.sh`)
2. Pattern-matches running containers by type (odoo, postgres, fastreport)
3. `docker stats --no-stream` — reads memory % per container
4. If memory > `MEMORY_THRESHOLD` (default 80%): restart sequence
   - FastReport: restart independently
   - Odoo: stop → PostgreSQL restart → `pg_isready` poll → Odoo start
5. Reports before/after memory to log file

### SSL Renewal Flow (ssl-renew.sh)

1. Cron `0 0 * * 3` → `ssl-renew.sh` (`scripts/ssl-renew.sh`)
2. `systemctl stop nginx`
3. `certbot renew` (finds certbot at `/usr/local/bin/certbot` or `/usr/bin/certbot`)
4. Clears nginx cache, `systemctl start nginx`

## Key Abstractions

**YAML Configuration Contract:**
- Purpose: Decouples infrastructure topology from script logic
- Examples: `scripts/container2backup.yaml`, `scripts/docker2update.yaml`, `scripts/hardening_config.yaml`
- Pattern: Scripts read `~/config.yaml` at runtime; template files live in `scripts/` and are copied to `~/` by deployment

**Release Manifest (`release.file`):**
- Purpose: Declarative list of Odoo module URLs to download at Docker build time
- Examples: `Dockerfiles/v18-odoo/release.file` (not present in repo; downloaded per deployment)
- Pattern: CSV file listing module name + download URL; `build_odoo.py` iterates and downloads each

**Fish Alias Entry Points:**
- Purpose: Short operator commands that proxy to the operational scripts
- Examples: `dobk` → `~/container2backup.py`, `doup` → `~/update_docker_odoo.py`, `dps` → `docker ps` formatted
- Pattern: Aliases defined in `fish/conf.d/33-aliases-backup.fish`, `32-aliases-docker.fish`, `34-aliases-nginx.fish`, `35-aliases-odoo.fish`

**`boot` Entrypoint Script:**
- Purpose: Unified container entrypoint supporting start/update/neutralize modes
- Location: `Dockerfiles/v18-odoo/bin/boot`, `Dockerfiles/v16-odoo/bin/boot`, `Dockerfiles/v19-odoo/bin/boot`
- Pattern: Shell dispatcher that calls `odoo-bin` with mode-appropriate flags; handles user switching (root → odoo)

## Entry Points

**`getScripts.py` (main):**
- Location: `getScripts.py:3396` (`main()`) / `getScripts.py:3906` (`__main__` block)
- Triggers: Manual run `./getScripts.py` or `./getScripts.py --dns-check`
- Responsibilities: Full server provisioning bootstrap

**`container2backup.py` (main):**
- Location: `scripts/container2backup.py:713` (`__main__` block)
- Triggers: Cron job or `dobk` alias; `--sql-only` flag for DB-only mode
- Responsibilities: Full backup cycle for all configured databases + services

**`update_docker_odoo.py` (main):**
- Location: `scripts/update_docker_odoo.py:896` (`main()`)
- Triggers: Manual `doup` alias; `--container`, `--verbose`, `--dry-run` CLI flags
- Responsibilities: Rebuilds and updates all active Odoo containers

**`nightly-cleanup.sh`:**
- Location: `scripts/nightly-cleanup.sh` (top-level)
- Triggers: Cron `0 3 * * *`; `DRY_RUN=1`, `MEMORY_THRESHOLD=90` env var overrides
- Responsibilities: Memory-based container restarts

**`server_hardening.py`:**
- Location: `scripts/server_hardening.py:849` (`main()`)
- Triggers: Manual `sudo python3 server_hardening.py [--apply] [--module ufw|fail2ban|ssh|sysctl|docker|nginx]`
- Responsibilities: Security audit and enforcement

**`bin/boot` (Docker entrypoint):**
- Location: `Dockerfiles/v18-odoo/bin/boot` (shared pattern across versions)
- Triggers: `docker run ... <image> start|update|neutralize`
- Responsibilities: Dispatch to correct odoo-bin invocation; handle odoo user permissions

## Architectural Constraints

- **Shell requirement:** getScripts.py requires Debian/Ubuntu; exits on other OS. Fish 4.0+ is the target shell — ZSH is skipped.
- **Root/sudo:** Most operational scripts and getScripts.py require root or passwordless sudo for apt, Docker, systemctl, and `/etc/` writes.
- **Deployed copies:** Scripts in `~/` are _copies_ of `scripts/*.py`; always edit the source in the repo and redeploy via `getScripts.py`.
- **Config location:** Operational scripts look for config in `~/` (home directory) first, then fallback to current directory (`scripts/` for testing).
- **Docker CLI only:** No Python Docker SDK; all container operations use `subprocess` calling `docker` CLI. This avoids SDK versioning but prevents structured error objects.
- **No global state in Python scripts:** Each script is standalone; no shared singletons between `container2backup.py` and `update_docker_odoo.py`.
- **`scripts/lib/` vs monolith:** `getScripts.py` contains a largely duplicated copy of the `scripts/lib/` logic. The library was extracted for modularization but the monolith was not fully refactored. Both are maintained in parallel.
- **Platform:** Dockerfiles target AMD64 (Intel/amd64) only; wkhtmltopdf is a prebuilt AMD64 binary from `rm.ownerp.io`.

## Anti-Patterns

### Deployed-copy drift

**What happens:** `getScripts.py` copies `scripts/*.py` to `~/`. If a script is edited directly in `~/` on the server, the next `getScripts.py` run overwrites the change.
**Why it's wrong:** Edits in `~/` are silently lost on the next provisioning run.
**Do this instead:** Always edit scripts under `scripts/` in the repo, commit, push, then re-run `getScripts.py` to redeploy.

### Hardcoded credentials in YAML templates

**What happens:** `scripts/docker2update.yaml` and `scripts/odoo.conf` contain `CHANGE_ME_BEFORE_PRODUCTION` placeholder passwords.
**Why it's wrong:** If deployed without substitution, containers expose default credentials.
**Do this instead:** Populate credentials from `scripts/.env` (which is git-ignored) and use `load_dotenv` pattern already present in `container2backup.py`.

### Duplicate logic: monolith vs lib

**What happens:** `getScripts.py` reimplements functions that exist in `scripts/lib/` (e.g., version checks, DNS optimization, Fish setup).
**Why it's wrong:** Bug fixes must be applied in two places.
**Do this instead:** Refactor `getScripts.py` to import from `scripts/lib/` via relative path (already exported in `scripts/lib/__init__.py`).

## Error Handling

**Strategy:** Print-based for backup/restore scripts; `logging` module for getScripts.py and update scripts. Scripts return boolean success/fail; callers decide whether to abort or continue.

**Patterns:**
- `container2backup.py`: `try/finally` around temp directory to guarantee cleanup; per-database errors skip the database but continue the run.
- `update_docker_odoo.py`: Returns `(success, info_count, warn_count, error_count)` tuples from `process_container()`; aggregates stats across containers.
- `getScripts.py`: Wraps `main()` in top-level `try/except`; exits with `sys.exit(1)` on critical failures.
- Shell scripts (`nightly-cleanup.sh`, `restore-zip.sh`): `set -euo pipefail` for immediate exit on error.
- Input validation: `_validate_identifier()` in `container2backup.py` rejects non-alphanumeric container/DB names before any subprocess call.

## Cross-Cutting Concerns

**Logging:** `getScripts.py` logs to `~/getscripts.log` + stdout via Python `logging`. Operational scripts use `print()` for operational output. `nightly-cleanup.sh` appends timestamped lines to `/var/log/nightly-cleanup.log`.
**Validation:** Container/database names validated against `^[A-Za-z0-9_.\-]+$` before use in subprocess args or filesystem paths.
**Security:** `shell=True` is avoided in `container2backup.py` (subprocess lists). `server_hardening.py` audits/applies UFW, fail2ban, SSH hardening, Docker daemon security, nginx TLS config.
**Encoding:** UTF-8 enforced via `# -*- coding: utf-8 -*-` headers and `encoding="utf8"` on all file opens.

---

*Architecture analysis: 2026-05-26*
