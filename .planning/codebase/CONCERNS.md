# Codebase Concerns

**Analysis Date:** 2026-05-26

---

## Security Considerations

### S1 — 7z Encryption Password Printed in Plaintext to stdout

**Risk:** AES-256 backup encryption password exposed in process output and logs.
**Files:** `scripts/container2backup.py:558`, `scripts/container2backup.py:561`, `scripts/container2backup.py:577`, `scripts/container2backup.py:581`
**Current mitigation:** Password stored in `.env` env var (`BACKUP_PASSWORD`), not in YAML config. Password appended to argv list as `-p<password>` (not shell-interpolated).
**Problem:** The `print(f"7z command for SQL-only mode: {' '.join(zip_args)}")` and `print(f"7z command for full backup: {zip_args}")` statements at those lines unconditionally dump the full command including `-p<password>` to stdout. Any log aggregator, cron email, or terminal scroll-back captures the plaintext password.
**Recommendations:**
- Gate those debug prints behind `if logger.level <= logging.DEBUG:` or replace with a redacted representation: `zip_args_display = [a if not a.startswith('-p') else '-p***' for a in zip_args]`.
- Alternatively, use `7zz`'s stdin password mode (`-p` read from stdin) to keep the password out of argv entirely.

---

### S2 — `config/backup_credentials.yaml` Committed to Git

**Risk:** Credential file committed to version control exposes encryption key in git history.
**Files:** `config/backup_credentials.yaml`
**Evidence:** `git ls-files config/backup_credentials.yaml` confirms it is tracked. Git log shows commits `363c2b1` and `ea7417f` include this file. Current content uses placeholder `"your-secure-password-here"` but the file is tracked and `.gitignore` does NOT exclude it (only `*.env` and `!*.env.example` are listed).
**Current mitigation:** File currently contains only a placeholder value.
**Recommendations:**
- Add `config/backup_credentials.yaml` to `.gitignore` immediately.
- Run `git rm --cached config/backup_credentials.yaml` to untrack it without deleting from disk.
- Consider BFG Repo Cleaner to remove from full git history if actual secrets were ever committed.

---

### S3 — `scripts/.env` Committed to Git (Working Tree Tracked)

**Risk:** `.env` file containing sensitive values is tracked by git.
**Files:** `scripts/.env`
**Evidence:** `git ls-files scripts/.env` confirms it is tracked. Git log shows commit `07402a8` explicitly moved sensitive values into this file. `.gitignore` pattern `*.env` would match but `scripts/.env` may have been force-added.
**Current mitigation:** File contents unknown (not read per forbidden-files policy), but the commit message states it holds sensitive values.
**Recommendations:**
- Run `git rm --cached scripts/.env` to untrack.
- Add `scripts/.env` (or tighten the `*.env` gitignore rule) to prevent re-tracking.
- Rotate all secrets that may have appeared in this file.

---

### S4 — `shell=True` Remaining in `update_docker_odoo.py` with Unvalidated Interpolation

**Risk:** Shell injection via YAML config values — container names, image names, paths, and db passwords are interpolated into f-string commands executed with `shell=True`.
**Files:** `scripts/update_docker_odoo.py:272` (the `run_command` function), `scripts/update_docker_odoo.py:725`, `scripts/update_docker_odoo.py:756`, `scripts/update_docker_odoo.py:786`, `scripts/update_docker_odoo.py:817`
**Problem:** The `run_command` function uses `shell=True` for all commands. Values like `container_name`, `image`, `db_password`, `volume`, and `path` are read from YAML and inserted via f-strings into shell strings: `f"docker run -it --rm -p {port}:8069 ... --db_password={db_password} ..."`. Unlike `container2backup.py`, this script has NO `_validate_identifier` calls. The `validate_container_config()` function only checks for field presence and path existence, not character safety.
**Contrast:** `scripts/container2backup.py` received `_validate_identifier` and `_IDENT_RE` as part of commit `20df817`. `update_docker_odoo.py` was NOT similarly hardened.
**Recommendations:**
- Add `_IDENT_RE = re.compile(r'^[A-Za-z0-9_.\-]+$')` and `_validate_identifier()` mirror from `container2backup.py`.
- Validate `container_name`, `database_name`, `docker_image_name`, `db_user`, `db_host` at config load time.
- Replace f-string commands with list-based `subprocess.run([...], shell=False)` for the Docker commands.
- `db_password` should be passed via environment variable (`PGPASSWORD`-style) rather than inline in the command string.

---

### S5 — `curl | sh` Install Pattern (Supply Chain Risk)

**Risk:** Remote shell scripts fetched over HTTPS and piped directly to `sh` without verification.
**Files:** `scripts/lib/tool_installers.py:130`, `scripts/lib/tool_installers.py:246`, `getScripts.py:544`, `getScripts.py:1143`, `getScripts.py:1496`
**Commands:**
- `curl -sS https://starship.rs/install.sh | sh -s -- -y`
- `curl -sSfL https://raw.githubusercontent.com/ajeetdsouza/zoxide/main/install.sh | sh`
- `curl -LsSf https://astral.sh/uv/install.sh | sh`
**Current mitigation:** All use HTTPS. No integrity verification (checksum/signature).
**Recommendations:** Download script to temp file, verify SHA256 checksum against published hashes, then execute. Or use distro package manager where available (partially done for zoxide on apt).

---

### S6 — `server_hardening.py` Uses `shell=True` for All Commands

**Risk:** Commands from `hardening_config.yaml` executed with `shell=True`.
**Files:** `scripts/server_hardening.py:64`
**Partial justification:** Comment says "all commands originate from the trusted YAML configuration, never from user input." However, `hardening_config.yaml` uses `${SSH_PORT}` env var substitution — if `SSH_PORT` contains shell metacharacters, injection is possible.
**Recommendations:** Expand env vars explicitly with `os.environ.get()` and validate port values are numeric before constructing UFW commands. For known-static command patterns (UFW rules), use list-based subprocess calls.

---

### S7 — `restore-zip.sh`: Backup Zip Filename Not Validated

**Risk:** The `mybackupzip` parameter (positional arg `$5`) is used in `unzip "$mybackuppath/$mybackupzip"` but is NOT passed through `validate_name()`.
**Files:** `scripts/restore-zip.sh:84-87`, `scripts/restore-zip.sh:154-156`
**Evidence:** `validate_name` is called for `mydb`, `myorgdb`, `myodoocontainer`, `myodoovol`, `mydbcontainer`, `mydbuser`, `mydbserver` (lines 121–127) but not for `mybackupzip`.
**Risk:** Crafted zip filename with path traversal (`../../etc/passwd`) or shell special chars could escape the backup path.
**Recommendations:** Add `validate_name "$mybackupzip" "backup zip filename"` at line 127.

---

### S8 — Dockerfiles: `prepare-18` and `prepare-19` Run as Root

**Risk:** Base image containers (`myodoo/prepare-v18`, `myodoo/prepare-v19`) finalize as root with no HEALTHCHECK.
**Files:** `Dockerfiles/prepare-18/Dockerfile`, `Dockerfiles/prepare-19/Dockerfile`
**Evidence:** Neither file has a `USER` directive in the final stage — last instruction is `SHELL ["/bin/bash", "-lc"]`, with no switch away from root. No `HEALTHCHECK` directive present.
**Context:** The derived `v18-odoo` and `v19-odoo` Dockerfiles correctly switch to `USER odoo` for the build phase and add HEALTHCHECK. The prepare base images themselves do not.
**Recommendations:** Add `USER nobody` or a named non-root user at the end of prepare Dockerfiles. Add `HEALTHCHECK NONE` at minimum (signals intentional decision).

---

### S9 — Prepare Dockerfiles Use `curl | bash` for Node.js Setup

**Risk:** `curl -fsSL https://deb.nodesource.com/setup_current.x | bash -` fetches and executes a remote script as root.
**Files:** `Dockerfiles/prepare-18/Dockerfile`, `Dockerfiles/prepare-19/Dockerfile`
**Current mitigation:** Uses `https://`. No checksum verification.
**Recommendations:** Pin to a specific NodeSource script version (e.g., `setup_22.x`) and verify GPG signature, or use the official Node.js Debian package from `nodejs.org/en/download/package-manager` with pinned key.

---

## Tech Debt

### T1 — Massive Code Duplication: `getScripts.py` vs `scripts/lib/`

**Issue:** `getScripts.py` (3965 lines, 105 functions) contains full re-implementations of `install_fish_if_needed`, `install_starship_if_needed`, `install_uv`, `run_command`, `check_dns_configuration`, etc. A parallel `scripts/lib/` module tree (2843 lines across 12 files) provides the same functionality. The two implementations diverge silently.
**Files:** `getScripts.py`, `scripts/lib/tool_installers.py`, `scripts/lib/system_utils.py`, `scripts/lib/dns_optimizer.py`, `scripts/lib/fish_setup.py`, `scripts/lib/package_manager.py`
**Impact:** Bug fixes applied to one copy do not propagate to the other. The security fixes in commit `8f199b7` updated `getScripts.py` but the `scripts/lib/` modules carry their own versions that may diverge.
**Fix approach:** Make `getScripts.py` import from `scripts/lib/` (adjust `sys.path` if needed). Remove duplicate implementations from `getScripts.py`.

---

### T2 — `update_docker_odoo.py`: `run_command` Uses Monolithic `shell=True` with Output Parsing

**Issue:** The `run_command` function (line 263, 268 lines long) uses `shell=True`, `subprocess.Popen`, manual stdout/stderr line buffering, regex-based log filtering, warning/error counting, and progress reporting — all in one function. This makes it hard to test and maintain.
**Files:** `scripts/update_docker_odoo.py:263-468`
**Impact:** Adding validation or splitting shell from non-shell execution paths requires refactoring the entire function.
**Fix approach:** Split into: `_run_subprocess(cmd_list, ...)` (no shell, list args), `_run_shell(cmd_str, ...)` (shell=True, only for commands with pipes), and `parse_docker_log_line(line)` (separate log filter).

---

### T3 — `requirements.txt` at Repo Root (Violates CLAUDE.md Rules)

**Issue:** `requirements.txt` exists at `/requirements.txt` containing `requests>=2.31.0` and `PyYAML>=6.0.1`. CLAUDE.md mandates `pyproject.toml` as the single source of truth.
**Files:** `requirements.txt`
**Impact:** Dependency management is split. UV users must know to ignore this file.
**Fix approach:** Remove `requirements.txt`. Add dependencies to `pyproject.toml`. If `pyproject.toml` does not exist at root, create it.

---

### T4 — `config/backup_credentials.yaml` Tracked by Git (see also S2)

**Issue:** Credential file is committed to version control. Even with placeholder content, the pattern of committing this file means operators may accidentally commit real credentials.
**Files:** `config/backup_credentials.yaml`
**Fix approach:** Add to `.gitignore`, untrack with `git rm --cached`, document in README that operators must create this file manually.

---

## Performance Bottlenecks

### P1 — `getScripts.py` Version Checks Run Sequentially Despite `check_versions_parallel`

**Issue:** A `check_versions_parallel` function exists (line 3146) using `ThreadPoolExecutor`, but the main setup flow in `setup_environment` / `install_packages` calls many individual tool check functions sequentially. The parallel function is a dead-end optimization that is not wired into the main execution path.
**Files:** `getScripts.py:3146-3182`
**Impact:** `getScripts.py` takes significantly longer than necessary on first run due to sequential subprocess calls for version checks.
**Improvement path:** Wire `check_versions_parallel` into `setup_environment()` for the initial version audit.

---

### P2 — `update_docker_odoo.py` Calls `docker system prune -f` During Every Update Run

**Issue:** `clean_docker_system()` calls `docker system prune -f` unconditionally as part of the normal update flow (line 528). This removes dangling images from ALL Docker projects on the host, not just the containers being updated.
**Files:** `scripts/update_docker_odoo.py:522-534`
**Impact:** On multi-project servers, this destroys build cache and images belonging to unrelated projects, causing much slower rebuilds.
**Improvement path:** Make the prune step opt-in via a `--prune` CLI flag, and scope it with `docker image prune -f --filter label=project=myodoo` if possible.

---

## Fragile Areas

### F1 — `nightly-cleanup.sh` Runs Unscoped `docker image prune -f`

**What makes it fragile:** Lines 243–244 call `docker image prune -f` and `docker builder prune -f` without any label filter. On multi-tenant servers running multiple Docker projects, this prunes images from all projects.
**Files:** `scripts/nightly-cleanup.sh:243-244`
**Safe modification:** Add `--filter label=maintainer=info@ownerp.com` or document explicitly that this script is for single-project servers only.
**Test coverage:** None — no tests exist for any shell scripts.

---

### F2 — `restore-zip.sh` Runs `DROP DATABASE` Without Transaction Safety

**What makes it fragile:** Line 152 executes `DROP DATABASE IF EXISTS "$mydb"` unconditionally before verifying the backup archive is valid. If the subsequent `unzip` or restore fails, the database is gone with no rollback path.
**Files:** `scripts/restore-zip.sh:152`, `scripts/restore-zip.sh:154-156`
**Why fragile:** Validation of `mybackupzip` existence (lines 84–90) checks for an empty string but does not verify file integrity. A corrupted or truncated archive triggers DROP then fails restore.
**Safe modification:** Verify archive integrity (`7zz t` or `unzip -t`) before executing DROP.

---

### F3 — `update_docker_odoo.py` f-string `rm -rf` with Unvalidated Path

**What makes it fragile:** Line 867: `run_command(f"rm -rf {backup_path}")` where `backup_path = f"{path}{db_name}.bak"`. Both `path` and `db_name` come from YAML config with no identifier validation (see S4). If `path` contains `../` or `db_name` is empty, `rm -rf` targets an unintended directory.
**Files:** `scripts/update_docker_odoo.py:867`, `scripts/update_docker_odoo.py:874`
**Safe modification:** Validate `path` is an absolute path under a known prefix (e.g., `/opt/odoo/`) and validate `db_name` with `_IDENT_RE` before constructing the delete command.

---

### F4 — `ssl-renew.sh`: Stops nginx Before Verifying certbot Presence

**What makes it fragile:** `systemctl stop nginx` is executed unconditionally before the certbot binary check (lines 13–22). If neither `/usr/local/bin/certbot` nor `/usr/bin/certbot` exists, nginx stays stopped permanently until manual intervention.
**Files:** `scripts/ssl-renew.sh:12-25`
**Safe modification:** Check certbot existence first; only stop nginx if certbot is found.

---

## Test Coverage Gaps

### TC1 — Zero Automated Test Coverage

**What's not tested:** All Python scripts (`container2backup.py`, `update_docker_odoo.py`, `getScripts.py`, `server_hardening.py`, `cleanup-weblogs.py`) and all shell scripts (`restore-zip.sh`, `ssl-renew.sh`, `nightly-cleanup.sh`) have zero unit or integration tests.
**Files:** Entire `scripts/` tree and `getScripts.py`
**Risk:** Security fixes (e.g., `_validate_identifier` in `container2backup.py`) cannot be regression-tested. The `update_docker_odoo.py` remains unvalidated after the divergence from `container2backup.py`'s hardening.
**Priority:** High — operational scripts with destructive side effects (DROP DATABASE, rm -rf, docker rm) must have test coverage for edge cases.
**Fix approach:** Use `pytest` with `unittest.mock.patch('subprocess.run')` to test command construction logic without executing Docker commands. Start with `container2backup.py` input validation functions.

---

### TC2 — `bare except:` Clauses Swallow All Exceptions Silently

**What's not tested / what fails unnoticed:** 15 bare `except:` clauses across `update_docker_odoo.py` (lines 691, 713, 749, 781, 811), `getScripts.py` (lines 442, 1257, 1290, 1300, 2106, 2169, 2181, 2188, 2207), and `scripts/lib/fish_setup.py` (line 95).
**Files:** Listed above.
**Risk:** `KeyboardInterrupt`, `SystemExit`, and unexpected exceptions during Docker operations are silently swallowed. A failed backup or update appears to succeed.
**Priority:** Medium — change all bare `except:` to `except Exception:` at minimum; add logging in each handler.

---

## Missing Critical Features

### M1 — No Backup Verification Step

**Problem:** After creating a backup archive, `container2backup.py` does not verify the archive is readable/valid (e.g., `7zz t archive.7z`).
**Files:** `scripts/container2backup.py:505-680`
**Blocks:** Confidence that backups are restorable. Backup encryption password mismatch is only discovered at restore time.
**Priority:** High for production backup reliability.

---

### M2 — No Alerting / Notification on Backup or Update Failure

**Problem:** `container2backup.py` and `update_docker_odoo.py` print to stdout but have no email, webhook, or monitoring notification on failure. When run from cron, failures are silent unless cron email is configured.
**Files:** `scripts/container2backup.py`, `scripts/update_docker_odoo.py`
**Blocks:** Operators discovering backup failures before data loss occurs.
**Priority:** Medium.

---

*Concerns audit: 2026-05-26*
