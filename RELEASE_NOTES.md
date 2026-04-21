# Release Notes

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
