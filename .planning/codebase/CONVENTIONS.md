# Coding Conventions

**Analysis Date:** 2026-05-26

## Script Header Convention (Mandatory)

Every script file must carry a version header. Two documented formats are in use:

**Python block-comment style** (`scripts/container2backup.py`, `scripts/update_docker_odoo.py`):
```python
#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Title:            container2backup.py
# Description:      Script to backup Odoo database including FileStore under Docker
# Version:          4.5.0
# Date:             21.04.2026
# Author:           Equitania Software GmbH
# ==============================================================================
```

**Python module docstring style** (`scripts/cleanup-weblogs.py`, `scripts/server_hardening.py`):
```python
#!/usr/bin/env python3
"""
Nginx Log Rotation for Odoo Docker Environment
...
Version: 2.0.0
Date: 2026-04-21
"""
```

**Bash inline comment style** (`scripts/restore-zip.sh`, `scripts/nightly-cleanup.sh`):
```bash
#!/bin/bash
# Version 1.3.0 - Stand 17.03.2026
```

**Rules:**
- Version format: `X.Y.Z` (semantic versioning)
- Date format: `DD.MM.YYYY` (German format) in Python and Bash scripts
- ISO date (`YYYY-MM-DD`) also appears in newer Python docstring-style headers
- When modifying a script, **always increment the version and update the date**
- Module-level constants in Python use `SCRIPT_VERSION = "X.Y.Z"` and `SCRIPT_DATE = "DD.MM.YYYY"` (`getScripts.py`, `scripts/lib/constants.py`)

## Git Commit Prefix Rules

All commits must use one of three prefixes:
- `[ADD]` — new features or extensions
- `[CHG]` — modifications/changes to existing code
- `[FIX]` — bug fixes

Example from git log: `[FIX] getScripts.py: catch UnicodeDecodeError when reading stale cache files`

## Encoding

**All Python files declare UTF-8 encoding:**
```python
# -*- coding: utf-8 -*-
```

All file I/O operations explicitly specify `encoding='utf-8'`:
```python
with open(cache_file, 'r', encoding='utf-8') as f:
    cached_data = json.load(f)
```

This is a project-wide **mandatory** requirement to support German umlauts and special Unicode characters.

## Naming Patterns

**Files:**
- Python scripts: `snake_case.py` (e.g., `container2backup.py`, `update_docker_odoo.py`, `server_hardening.py`)
- Shell scripts: `kebab-case.sh` (e.g., `nightly-cleanup.sh`, `restore-zip.sh`, `ssl-renew.sh`)
- Config files: `kebab-case.yaml` (e.g., `container2backup.yaml`, `docker2update.yaml`)
- Lib modules: `snake_case.py` (e.g., `scripts/lib/logging_config.py`, `scripts/lib/system_utils.py`)

**Functions:**
- Python: `snake_case` for all functions and methods
- Private/internal helpers: prefixed with `_` (e.g., `_validate_identifier`, `_CACHE_KEY_RE`)

**Constants:**
- Module-level constants: `UPPER_SNAKE_CASE` (e.g., `SCRIPT_VERSION`, `CACHE_DIR`, `RETENTION_DAYS`)

**Variables:**
- `snake_case` throughout Python code
- Bash: `lowercase_with_underscores` for local vars (e.g., `log_file`, `dry_run`), `UPPER_CASE` for env-overridable config (e.g., `MEMORY_THRESHOLD`, `DRY_RUN`)

## Code Style

**Formatting:**
- No automated formatter configured (no `.prettierrc`, `pyproject.toml`, `black` config found)
- Line length: approximately 80-120 characters in practice
- Indentation: 4 spaces (Python standard)

**Linting:**
- No `.flake8`, `.pylintrc`, or `ruff.toml` found in this repo
- Code quality enforced by code review conventions, not tooling

## Import Organization

Python imports follow stdlib-then-third-party order (informal):
```python
# stdlib
import os
import subprocess
import sys
import logging
from typing import Tuple, Optional, Dict, List, Any

# third-party
import yaml
from dotenv import load_dotenv
```

Internal lib imports use relative imports within `scripts/lib/`:
```python
from .constants import CACHE_DIR, CACHE_EXPIRY_HOURS
from .logging_config import get_logger
```

## Logging

**Framework:** Python `logging` module (stdlib)

**Setup pattern** — each main script sets up logging at module level:
```python
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_log_file)
    ]
)
logger = logging.getLogger(__name__)
```

**Centralized log config** for the `getScripts.py` ecosystem lives in `scripts/lib/logging_config.py` with `setup_logging()` and `get_logger()` functions.

**Debug toggle via environment variable:**
```python
if os.environ.get('GETSCRIPTS_DEBUG', '').lower() in ('1', 'true', 'yes'):
    logger.setLevel(logging.DEBUG)
```

**Mixed usage:** Older code uses `print()` for user-facing output; `logger.*` for structured logging. Newer code (lib modules) uses `logger` exclusively. `scripts/container2backup.py` mixes both — `print()` for progress and `logger` is not imported in that file at all; it relies purely on `print()`.

**Bash logging pattern** (`scripts/nightly-cleanup.sh`):
```bash
log_msg() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') | $*" >> "$LOG"
}
```

Log file locations:
- `getScripts.py` → `~/getscripts.log`
- `nightly-cleanup.sh` → `/var/log/nightly-cleanup.log` (configurable via `CLEANUP_LOG`)

## Error Handling

**Python — subprocess calls:**
```python
# Explicit list args (no shell=True) for security
result = subprocess.run(
    ['docker', 'exec', container, 'pg_dump', ...],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=True
)
```

Use `check=True` when failure should raise; use `check=False` with manual return-code inspection when caller handles errors.

**Specific exception types preferred over bare `except Exception`:**
```python
except (subprocess.SubprocessError, FileNotFoundError):
    ...
except yaml.YAMLError as e:
    ...
except ValueError as exc:
    ...
```

Bare `except Exception as e:` is used as a last-resort fallback with a print/log statement — not for control flow.

**Input validation** — identifier whitelist pattern for security-critical inputs:
```python
_IDENT_RE = re.compile(r'^[A-Za-z0-9_.\-]+$')

def _validate_identifier(value, field_name):
    if not isinstance(value, str) or not _IDENT_RE.match(value):
        raise ValueError(f"Invalid {field_name} {value!r}: must match [A-Za-z0-9_.-]+")
    return value
```

**Bash safety flags** — mandatory in newer scripts:
```bash
set -euo pipefail
```
Found in `scripts/nightly-cleanup.sh` and `scripts/restore-zip.sh`. Older scripts (`ssl-renew.sh`, `docker-clean-logs.sh`) do not use them.

## Function Design

**Docstring style:** Google-style docstrings with `Args:`, `Returns:`, `Raises:` sections (used consistently in `scripts/lib/` modules):
```python
def get_cache_file_path(key: str) -> str:
    """
    Get the cache file path for a given key.

    Args:
        key: Cache key identifier (must match [A-Za-z0-9_-]+)

    Returns:
        str: Full path to cache file

    Raises:
        ValueError: If the key contains characters that could escape CACHE_DIR.
    """
```

Older scripts (`container2backup.py`, `update_docker_odoo.py`) use one-line or minimal docstrings.

**Type hints:** Used in `scripts/lib/` modules and `getScripts.py`:
```python
from typing import Tuple, Optional, Dict, List, Any

def setup_logging(debug: bool = False) -> logging.Logger:
def get_cached_version(key: str, disabled: bool = False) -> Optional[Dict[str, Any]]:
```

Not used in older scripts like `container2backup.py`.

## YAML Configuration Style

Config files use flat, well-commented YAML. Top-level keys: `defaults`, `services`, `databases`, `rsync`. Inline comments explain each field:
```yaml
defaults:
  retention_days: 14  # Retention period in days
  db_user: ownerp
  compression:
    format: "7z"     # Compression format: 7z, zip, gzip, zstd
    level: 5         # Compression level (0-9, default: 5)
```

Environment variable substitution via `$HOME/...` syntax in path values is supported and documented.

## Subprocess Security Convention

**No `shell=True`** in security-sensitive calls — arguments passed as lists:
```python
# Correct
subprocess.run(['docker', 'exec', container, ...], check=True)

# Avoid
subprocess.run(f"docker exec {container} ...", shell=True)
```

The `server_hardening.py` documents an intentional `shell=True` exception with an explicit comment explaining the trusted source of the commands.

## Module/Library Pattern

The `scripts/lib/` package pattern separates concerns:
- `scripts/lib/__init__.py` — package marker
- `scripts/lib/constants.py` — all magic values and defaults
- `scripts/lib/logging_config.py` — singleton logger setup
- `scripts/lib/cache.py` — JSON-based caching with key validation
- `scripts/lib/system_utils.py` — OS detection, command execution, retry decorator
- Other modules: `dns_optimizer.py`, `fish_setup.py`, `package_manager.py`, etc.

Main `getScripts.py` imports from this lib package; standalone scripts (`container2backup.py`, `update_docker_odoo.py`) do not — they are self-contained.

---

*Convention analysis: 2026-05-26*
