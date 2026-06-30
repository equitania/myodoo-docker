#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Script for organizing Docker servers

##############################################################################
#
#    Shell Script for devops
#    Copyright 2014-now Equitania Software GmbH.
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program. If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
import os
import subprocess
import requests
import sys
import logging
from typing import Tuple, Optional, Dict, List, Any
from functools import wraps, lru_cache
import time
import platform
import re
import socket
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import json

# Configure logging - always log to home directory to avoid polluting system dirs
_log_file = os.path.join(os.path.expanduser("~"), "getscripts.log")
logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_log_file)
    ]
)
logger = logging.getLogger(__name__)

# Enable debug logging if environment variable is set
if os.environ.get('GETSCRIPTS_DEBUG', '').lower() in ('1', 'true', 'yes'):
    logger.setLevel(logging.DEBUG)
    logger.debug("Debug logging enabled")

# Script version and date
SCRIPT_VERSION = "9.5.1"
SCRIPT_DATE = "30.06.2026"

# ─────────────────────────────────────────────────────────────────────────────
# Install report
# ─────────────────────────────────────────────────────────────────────────────
# Records the outcome of key tool installs so a visible summary can be printed
# at the end of the run. Logger errors go to stderr and easily scroll past in a
# long provisioning run — this surfaces failures (e.g. nginx-set-conf not
# installing) where the operator will actually see them.
# Status values: "installed", "updated", "ok", "skipped", "failed".
_install_report: List[Tuple[str, str, str]] = []


def record_install(name: str, status: str, detail: str = "") -> None:
    """Record a tool install outcome for the end-of-run summary."""
    _install_report.append((name, status, detail))


def print_install_report() -> None:
    """Print a visible summary of recorded install outcomes to the console.

    Highlights failures so they are not lost in the scrollback. Colors are used
    only on a TTY.
    """
    if not _install_report:
        return

    use_color = sys.stdout.isatty()
    green = "\033[0;32m" if use_color else ""
    red = "\033[0;31m" if use_color else ""
    yellow = "\033[1;33m" if use_color else ""
    reset = "\033[0m" if use_color else ""

    symbols = {
        "installed": (green, "✓"),
        "updated": (green, "✓"),
        "ok": (green, "✓"),
        "skipped": (yellow, "•"),
        "failed": (red, "✗"),
    }

    print("")
    print("=" * 60)
    print("Install summary")
    print("=" * 60)
    failed = 0
    for name, status, detail in _install_report:
        color, sym = symbols.get(status, ("", "-"))
        if status == "failed":
            failed += 1
        suffix = f" — {detail}" if detail else ""
        print(f"  {color}{sym}{reset} {name}: {status}{suffix}")
    print("=" * 60)
    if failed:
        print(f"{red}{failed} item(s) FAILED — see above and ~/getscripts.log.{reset}")
    print("")

# Pinned fallback 7-Zip version used when the GitHub API is unreachable.
# GitHub keeps release assets permanently, so this fallback cannot 404
# (unlike www.7-zip.org/a/, which only serves the current release).
FALLBACK_7ZIP_VERSION = "26.01"

# Cache settings
CACHE_DIR = os.path.expanduser("~/.cache/getscripts")
CACHE_EXPIRY_HOURS = 24  # Cache version info for 24 hours
_CACHE_KEY_RE = re.compile(r'^[A-Za-z0-9._\-]+$')

# Global cache for version information
version_cache: Dict[str, Dict[str, Any]] = {}

def ensure_cache_dir() -> None:
    """Ensure cache directory exists."""
    os.makedirs(CACHE_DIR, exist_ok=True)

def get_cache_file_path(key: str) -> str:
    """Get the cache file path for a given key.

    Raises:
        ValueError: If the key could escape CACHE_DIR (path-traversal defense).
    """
    if not _CACHE_KEY_RE.match(key):
        raise ValueError(f"Invalid cache key: {key!r}")
    return os.path.join(CACHE_DIR, f"{key}.cache")

def get_cached_version(key: str, allow_stale: bool = False) -> Optional[Dict[str, Any]]:
    """Get cached version information.

    Args:
        key: Cache key
        allow_stale: Return the cached data even when it is older than
            CACHE_EXPIRY_HOURS - used as fallback when the live API query
            fails (a stale version beats aborting the install).

    Returns:
        Optional[Dict[str, Any]]: Cached data if valid, None otherwise
    """
    # Check if caching is disabled
    if getattr(get_cached_version, 'disabled', False):
        return None

    ensure_cache_dir()
    try:
        cache_file = get_cache_file_path(key)
    except ValueError as e:
        logger.error(f"Refusing to read cache: {e}")
        return None

    if not os.path.exists(cache_file):
        return None

    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            cached_data = json.load(f)

        # Check if cache is expired
        cache_time = datetime.fromtimestamp(os.path.getmtime(cache_file))
        if not allow_stale and datetime.now() - cache_time > timedelta(hours=CACHE_EXPIRY_HOURS):
            logger.debug(f"Cache for {key} is expired")
            os.remove(cache_file)
            return None

        logger.debug(f"Using cached data for {key}")
        return cached_data
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        logger.error(f"Error reading cache for {key}: {e}")
        if os.path.exists(cache_file):
            os.remove(cache_file)
        return None

def cache_version_info(key: str, data: Dict[str, Any]) -> None:
    """Cache version information.

    Args:
        key: Cache key
        data: Data to cache (must be JSON-serializable)
    """
    ensure_cache_dir()
    try:
        cache_file = get_cache_file_path(key)
    except ValueError as e:
        logger.error(f"Refusing to write cache: {e}")
        return

    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        logger.debug(f"Cached data for {key}")
    except (TypeError, OSError) as e:
        logger.error(f"Error caching data for {key}: {e}")

def clear_cache() -> None:
    """Clear all cached data."""
    if os.path.exists(CACHE_DIR):
        import shutil
        shutil.rmtree(CACHE_DIR)
        logger.info("Cache cleared")

def print_header() -> None:
    """Print a nicely formatted header with script version and date."""
    header = f"""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║    ██████╗ ██╗    ██╗███╗   ██╗███████╗██████╗ ██████╗       ║
║   ██╔═══██╗██║    ██║████╗  ██║██╔════╝██╔══██╗██╔══██╗      ║
║   ██║   ██║██║ █╗ ██║██╔██╗ ██║█████╗  ██████╔╝██████╔╝      ║
║   ██║   ██║██║███╗██║██║╚██╗██║██╔══╝  ██╔══██╗██╔═══╝       ║
║   ╚██████╔╝╚███╔███╔╝██║ ╚████║███████╗██║  ██║██║           ║
║    ╚═════╝  ╚══╝╚══╝ ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝╚═╝           ║
║                                                              ║
║                      Docker Server Utility                   ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║    Version: {SCRIPT_VERSION:<12}              Date: {SCRIPT_DATE:<12}     ║
╚══════════════════════════════════════════════════════════════╝
"""
    print(header)
    logger.info(f"Running getScripts.py version {SCRIPT_VERSION} ({SCRIPT_DATE})")

def retry_on_exception(retries: int = 3, delay: int = 1):
    """Decorator to retry functions on exception.
    
    Args:
        retries (int): Number of retry attempts
        delay (int): Delay between retries in seconds
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for i in range(retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if i == retries - 1:
                        logger.error(f"Failed after {retries} attempts: {str(e)}")
                        raise
                    logger.warning(f"Attempt {i + 1} failed: {str(e)}")
                    time.sleep(delay)
        return wrapper
    return decorator

def is_fastfetch_installed() -> Tuple[bool, Optional[str]]:
    """Check if fastfetch is installed and get its version.
    
    Returns:
        Tuple[bool, Optional[str]]: Installation status and version if installed
    """
    try:
        result = subprocess.run(
            ["fastfetch", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )
        if result.returncode == 0:
            output = result.stdout.strip() or result.stderr.strip()
            parts = output.split()
            if len(parts) >= 2:
                version = parts[1]
                logger.info(f"Fastfetch version {version} found")
                return True, version
            logger.warning("Could not parse Fastfetch version")
            return False, None
        logger.error(f"Fastfetch error: {result.stderr.strip()}")
        return False, None
    except FileNotFoundError:
        logger.info("Fastfetch not found")
        return False, None


def normalize_zoxide_version(version: str) -> str:
    """Normalize zoxide version string for comparison.

    Handles version strings like 'v0.4.3-unknown', '0.9.7', 'v0.9.7' etc.
    Removes 'v' prefix and any suffixes like '-unknown', '-dirty'.

    Args:
        version: Raw version string from zoxide --version output

    Returns:
        Normalized version string (e.g., '0.4.3')
    """
    if not version:
        return ""
    # Strip 'v' prefix
    clean_version = version.lstrip('v')
    # Remove common suffixes like '-unknown', '-dirty', etc.
    # Take only the numeric version part (e.g., '0.4.3' from '0.4.3-unknown')
    if '-' in clean_version:
        clean_version = clean_version.split('-')[0]
    return clean_version


# =============================================================================
# FISH SHELL SUPPORT (New in v7.0.0)
# =============================================================================

def is_fish_installed() -> Tuple[bool, Optional[str]]:
    """Check if Fish shell is installed and get its version.

    Returns:
        Tuple[bool, Optional[str]]: Installation status and version if installed
    """
    try:
        result = subprocess.run(
            ["fish", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )
        if result.returncode == 0:
            output = result.stdout.strip() or result.stderr.strip()
            # Fish version output: "fish, version 4.0.0"
            version_match = re.search(r'version (\d+\.\d+\.\d+)', output)
            if version_match:
                version = version_match.group(1)
                logger.info(f"Fish shell version {version} found")
                return True, version
        return False, None
    except FileNotFoundError:
        logger.info("Fish shell not found")
        return False, None


def is_zsh_installed() -> Tuple[bool, Optional[str]]:
    """Check if ZSH is installed and get its version.

    Returns:
        Tuple[bool, Optional[str]]: Installation status and version if installed
    """
    try:
        result = subprocess.run(
            ["zsh", "--version"],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0:
            # Output: "zsh 5.9 (x86_64-debian-linux-gnu)"
            match = re.search(r'zsh (\d+\.\d+(?:\.\d+)?)', result.stdout)
            if match:
                version = match.group(1)
                logger.info(f"ZSH version {version} found")
                return True, version
        return False, None
    except FileNotFoundError:
        logger.info("ZSH not found")
        return False, None


def is_fish_repo_configured() -> bool:
    """Check if the official Fish shell repository is already configured.
    Checks both legacy .list format and modern DEB822 .sources format.

    Returns:
        bool: True if Fish repo is configured
    """
    repo_list = "/etc/apt/sources.list.d/shells:fish:release:4.list"
    # Alternative name (some systems replace : with _)
    repo_list_alt = "/etc/apt/sources.list.d/shells_fish_release_4.list"
    # DEB822 format used by modern Debian (Trixie/13+)
    repo_sources = "/etc/apt/sources.list.d/shells:fish:release:4.sources"
    repo_sources_alt = "/etc/apt/sources.list.d/shells_fish_release_4.sources"
    # PPA list for Ubuntu
    ppa_list = "/etc/apt/sources.list.d/fish-shell-ubuntu-release-4"

    # Check for Debian-style repo (.list or .sources)
    if (os.path.exists(repo_list) or os.path.exists(repo_list_alt) or
            os.path.exists(repo_sources) or os.path.exists(repo_sources_alt)):
        return True

    # Check for Ubuntu PPA (glob pattern for different Ubuntu versions)
    import glob as glob_module
    if glob_module.glob(f"{ppa_list}*.list") or glob_module.glob(f"{ppa_list}*.sources"):
        return True

    return False


def is_fish_repo_key_present() -> bool:
    """Check if the Fish OBS repository signing key is present.

    A .list file without its signing key leaves apt broken system-wide
    (signature verification fails on every 'apt update').

    Returns:
        bool: True if a signing key for the Fish OBS repo exists
    """
    key_files = [
        "/etc/apt/trusted.gpg.d/shells_fish_release_4.asc",
        "/etc/apt/trusted.gpg.d/shells_fish_release_4.gpg",
    ]
    # Empty key files (from failed downloads in earlier versions) count as missing
    return any(os.path.isfile(key) and os.path.getsize(key) > 0 for key in key_files)


def cleanup_duplicate_fish_repo() -> None:
    """Remove duplicate Fish repository entries.
    If both .list and .sources files exist, remove the .list file
    since .sources (DEB822 format) is the modern standard.
    """
    list_file = "/etc/apt/sources.list.d/shells:fish:release:4.list"
    sources_file = "/etc/apt/sources.list.d/shells:fish:release:4.sources"

    if os.path.exists(list_file) and os.path.exists(sources_file):
        logger.info("Duplicate Fish repository detected (.list + .sources), removing .list file...")
        try:
            run_command(f"sudo rm -f {list_file}")
            logger.info(f"Removed duplicate {list_file}")
        except Exception as e:
            logger.warning(f"Failed to remove duplicate Fish repo file: {e}")


def install_fish_if_needed() -> Tuple[bool, bool]:
    """Install or upgrade Fish shell from official repository.

    Uses official Fish shell repositories:
    - Debian: OpenSUSE Build Service (shells:fish:release:4)
    - Ubuntu: Launchpad PPA (ppa:fish-shell/release-4)

    Always ensures the official repository is configured and Fish is upgraded
    to the latest available version.

    Returns:
        Tuple[bool, bool]: (is_available, needs_migration)
            - is_available: True if Fish 4.0+ is available after this function
            - needs_migration: True if this is a fresh install or migration from system packages
              (triggers legacy cleanup and shell change prompt)
    """
    installed, current_version = is_fish_installed()
    needs_migration = False
    repo_was_added = False

    # Check if we have sudo privileges
    if not is_root_or_has_sudo():
        logger.warning("Cannot install/upgrade Fish without sudo privileges")
        return installed, False

    # Clean up duplicate repository entries (.list + .sources)
    cleanup_duplicate_fish_repo()

    os_id, os_version = get_os_info()

    # =========================================================================
    # UBUNTU: Use Launchpad PPA
    # =========================================================================
    if os_id == "ubuntu":
        try:
            # Check if PPA needs to be added
            if not is_fish_repo_configured():
                logger.info("Adding official Fish shell PPA repository...")
                run_command("sudo apt-add-repository -y ppa:fish-shell/release-4", check=True)
                repo_was_added = True
                needs_migration = True  # Migration from system packages

            # Always update and upgrade to get latest version
            run_command("sudo apt update", check=True)

            if installed:
                logger.info(f"Fish {current_version} installed, checking for updates...")
                run_command("sudo apt install -y --only-upgrade fish", check=True)
            else:
                logger.info("Installing Fish shell from official PPA...")
                run_command("sudo apt install -y fish", check=True)
                needs_migration = True  # Fresh install

            # Verify installation
            installed, new_version = is_fish_installed()
            if installed:
                if new_version != current_version:
                    logger.info(f"Fish shell upgraded: {current_version or 'not installed'} → {new_version}")
                else:
                    logger.info(f"Fish shell {new_version} is already the latest version")
                return True, needs_migration
        except Exception as e:
            logger.error(f"Failed to install/upgrade Fish from PPA: {e}")
            return installed, False

    # =========================================================================
    # DEBIAN: Use OpenSUSE Build Service repository
    # =========================================================================
    elif os_id == "debian":
        # Map Debian version to repository name
        # VERSION_ID: 12 = Bookworm, 13 = Trixie
        debian_repos = {
            "12": "Debian_12",
            "13": "Debian_13",
        }

        # Handle testing/unstable (no VERSION_ID or unusual values)
        if os_version not in debian_repos:
            # Try to detect from VERSION_CODENAME
            try:
                with open("/etc/os-release") as f:
                    content = f.read()
                if "bookworm" in content.lower():
                    os_version = "12"
                elif "trixie" in content.lower():
                    os_version = "13"
                else:
                    # Default to latest stable
                    logger.warning(f"Unknown Debian version '{os_version}', defaulting to Debian 13")
                    os_version = "13"
            except:
                os_version = "13"

        debian_version = debian_repos.get(os_version, "Debian_13")
        repo_url = f"https://download.opensuse.org/repositories/shells:/fish:/release:/4/{debian_version}/"
        key_url = f"https://download.opensuse.org/repositories/shells:fish:release:4/{debian_version}/Release.key"

        repo_list_path = "/etc/apt/sources.list.d/shells:fish:release:4.list"

        try:
            # Repair half-configured state: .list present but signing key missing
            # (e.g. earlier run failed during key import) - breaks every 'apt update'
            key_repair_needed = os.path.exists(repo_list_path) and not is_fish_repo_key_present()

            # Migrate legacy plain-http repo entries to https
            http_repair_needed = False
            if os.path.exists(repo_list_path):
                try:
                    with open(repo_list_path) as repo_file:
                        http_repair_needed = "http://" in repo_file.read()
                except OSError:
                    pass

            # Check if repository needs to be added or repaired
            if not is_fish_repo_configured() or key_repair_needed or http_repair_needed:
                logger.info(f"Adding official Fish shell repository for {debian_version}...")

                # Add repository
                repo_list_content = f"deb {repo_url} /"
                subprocess.run(
                    ["sudo", "tee", repo_list_path],
                    input=repo_list_content.encode(), check=True, stdout=subprocess.DEVNULL
                )

                # Import signing key as ASCII-armored .asc (supported since apt 1.4,
                # Debian 9+) - avoids dependency on gnupg, which minimal images lack.
                # Download to temp file first so a failed download propagates as error
                # instead of leaving an empty key file behind (no pipefail in /bin/sh).
                logger.info("Importing Fish shell repository signing key...")
                run_command(
                    f"curl -fsSL {key_url} -o /tmp/shells_fish_release_4.asc && "
                    "sudo mv /tmp/shells_fish_release_4.asc /etc/apt/trusted.gpg.d/shells_fish_release_4.asc",
                    shell=True, check=True
                )

                repo_was_added = True
                needs_migration = True  # Migration from system packages

            # Always update and upgrade to get latest version
            run_command("sudo apt update", check=True)

            if installed:
                logger.info(f"Fish {current_version} installed, checking for updates...")
                run_command("sudo apt install -y --only-upgrade fish", check=True)
            else:
                logger.info("Installing Fish shell from official repository...")
                run_command("sudo apt install -y fish", check=True)
                needs_migration = True  # Fresh install

            # Verify installation
            installed, new_version = is_fish_installed()
            if installed:
                if new_version != current_version:
                    logger.info(f"Fish shell upgraded: {current_version or 'not installed'} → {new_version}")
                else:
                    logger.info(f"Fish shell {new_version} is already the latest version")
                return True, needs_migration
        except Exception as e:
            logger.error(f"Failed to install/upgrade Fish from official repository: {e}")

            # Remove the half-configured repo so apt keeps working system-wide
            logger.info("Removing Fish OBS repository files to keep apt functional...")
            run_command(
                f"sudo rm -f {repo_list_path} "
                "/etc/apt/trusted.gpg.d/shells_fish_release_4.asc "
                "/etc/apt/trusted.gpg.d/shells_fish_release_4.gpg",
                shell=True
            )

            # Fallback: install Fish from Debian repos (frozen version, better than
            # none). The OBS repo setup is retried on the next script run.
            try:
                run_command("sudo apt update", check=True)
                if not installed:
                    logger.info("Installing Fish shell from Debian repositories (fallback)...")
                    run_command("sudo apt install -y fish", check=True)
                    needs_migration = True
                installed, new_version = is_fish_installed()
                if installed:
                    logger.warning(
                        f"Fish {new_version} available from Debian repos only - "
                        "official OBS repo setup failed, will retry on next run"
                    )
                    return True, needs_migration
            except Exception as fallback_error:
                logger.error(f"Fallback installation from Debian repositories also failed: {fallback_error}")
            return installed, False

    else:
        logger.warning(f"Unsupported OS: {os_id}. Cannot install Fish shell automatically.")
        return installed, False

    return False, False


def is_starship_installed() -> Tuple[bool, Optional[str]]:
    """Check if Starship prompt is installed and get its version.

    Returns:
        Tuple[bool, Optional[str]]: Installation status and version if installed
    """
    try:
        result = subprocess.run(
            ["starship", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )
        if result.returncode == 0:
            output = result.stdout.strip()
            # Starship version output: "starship 1.17.1"
            parts = output.split()
            if len(parts) >= 2:
                version = parts[1]
                logger.info(f"Starship version {version} found")
                return True, version
        return False, None
    except FileNotFoundError:
        logger.info("Starship not found")
        return False, None


def install_starship_if_needed() -> bool:
    """Install Starship prompt if not installed.

    Downloads the official release binary from GitHub instead of piping
    the remote install.sh into a root shell.

    Returns:
        bool: True if Starship is available
    """
    installed, current_version = is_starship_installed()

    if installed:
        logger.info(f"Starship {current_version} is already installed")
        return True

    logger.info("Installing Starship prompt...")
    try:
        machine = platform.machine().lower()
        target = "aarch64-unknown-linux-musl" if machine in ("aarch64", "arm64") else "x86_64-unknown-linux-musl"
        tarball_url = f"https://github.com/starship/starship/releases/latest/download/starship-{target}.tar.gz"
        tmp_tarball = "/tmp/starship.tar.gz"
        logger.info(f"Downloading Starship release binary ({target})...")
        run_command(f"curl -fsSL {tarball_url} -o {tmp_tarball}", shell=True, check=True)
        run_command(f"sudo tar -xzf {tmp_tarball} -C /usr/local/bin starship", shell=True, check=True)
        run_command("sudo chmod 755 /usr/local/bin/starship", shell=True, check=True)
        os.remove(tmp_tarball)

        installed, new_version = is_starship_installed()
        if installed:
            logger.info(f"Starship {new_version} installed successfully")
            return True
    except Exception as e:
        logger.error(f"Failed to install Starship: {e}")

    return False


def is_fisher_installed() -> bool:
    """Check if Fisher plugin manager is installed for Fish.

    Returns:
        bool: True if Fisher is installed
    """
    fisher_path = os.path.expanduser("~/.config/fish/functions/fisher.fish")
    return os.path.exists(fisher_path)


def install_fisher_if_needed() -> bool:
    """Install Fisher plugin manager for Fish if not installed.

    Returns:
        bool: True if Fisher is available
    """
    if is_fisher_installed():
        logger.info("Fisher is already installed")
        return True

    # Check if Fish is available
    installed, _ = is_fish_installed()
    if not installed:
        logger.warning("Cannot install Fisher without Fish shell")
        return False

    logger.info("Installing Fisher plugin manager...")
    try:
        # Bootstrap from the latest tagged release instead of the moving
        # main branch (reproducible, no unreviewed HEAD code)
        fisher_ref = "4.4.5"
        try:
            response = requests.get(
                "https://api.github.com/repos/jorgebucaran/fisher/releases/latest", timeout=15
            )
            if response.status_code == 200:
                fisher_ref = response.json().get("tag_name", fisher_ref).lstrip("v")
        except Exception:
            logger.warning(f"Could not resolve latest Fisher release, using {fisher_ref}")
        install_cmd = (
            f'fish -c "curl -sL https://raw.githubusercontent.com/jorgebucaran/fisher/{fisher_ref}/functions/fisher.fish'
            f' | source && fisher install jorgebucaran/fisher@{fisher_ref}"'
        )
        run_command(install_cmd, shell=True, check=True)

        if is_fisher_installed():
            logger.info("Fisher installed successfully")
            return True
    except Exception as e:
        logger.error(f"Failed to install Fisher: {e}")

    return False


def copy_fish_configuration(_myhome: str, myodoo_docker: str) -> bool:
    """Copy Fish shell configuration from repository to user's config directory.

    Args:
        _myhome: User's home directory
        myodoo_docker: Path to myodoo-docker repository

    Returns:
        bool: True if configuration was copied successfully
    """
    import shutil

    source_fish_dir = os.path.join(myodoo_docker, "fish")
    target_fish_dir = os.path.join(_myhome, ".config", "fish")

    if not os.path.exists(source_fish_dir):
        logger.warning(f"Fish configuration not found in repository: {source_fish_dir}")
        return False

    try:
        # Create target directory if it doesn't exist
        ensure_directory_exists(target_fish_dir)

        # Backup existing configuration
        if os.path.exists(os.path.join(target_fish_dir, "config.fish")):
            backup_path = os.path.join(target_fish_dir, "config.fish.bak")
            logger.info(f"Backing up existing Fish config to {backup_path}")
            shutil.copy2(os.path.join(target_fish_dir, "config.fish"), backup_path)

        # Copy config.fish
        source_config = os.path.join(source_fish_dir, "config.fish")
        if os.path.exists(source_config):
            shutil.copy2(source_config, os.path.join(target_fish_dir, "config.fish"))
            logger.info("Copied config.fish")

        # Copy conf.d directory
        source_confd = os.path.join(source_fish_dir, "conf.d")
        target_confd = os.path.join(target_fish_dir, "conf.d")
        if os.path.exists(source_confd):
            ensure_directory_exists(target_confd)
            for item in os.listdir(source_confd):
                source_item = os.path.join(source_confd, item)
                target_item = os.path.join(target_confd, item)
                if os.path.isfile(source_item):
                    shutil.copy2(source_item, target_item)
            logger.info("Copied conf.d/ modules")

        # Copy functions directory (Linux-specific)
        source_functions = os.path.join(source_fish_dir, "functions", "linux")
        target_functions = os.path.join(target_fish_dir, "functions")
        if os.path.exists(source_functions):
            ensure_directory_exists(target_functions)
            for item in os.listdir(source_functions):
                source_item = os.path.join(source_functions, item)
                target_item = os.path.join(target_functions, item)
                if os.path.isfile(source_item):
                    shutil.copy2(source_item, target_item)
            logger.info("Copied functions/")

        logger.info("Fish configuration copied successfully")
        return True

    except Exception as e:
        logger.error(f"Error copying Fish configuration: {e}")
        return False


def copy_starship_configuration(_myhome: str, myodoo_docker: str) -> bool:
    """Copy Starship configuration from repository.

    Args:
        _myhome: User's home directory
        myodoo_docker: Path to myodoo-docker repository

    Returns:
        bool: True if configuration was copied successfully
    """
    import shutil

    source_starship = os.path.join(myodoo_docker, "starship.toml")
    target_starship = os.path.join(_myhome, ".config", "starship.toml")

    if not os.path.exists(source_starship):
        logger.warning(f"Starship configuration not found: {source_starship}")
        return False

    try:
        target_dir = os.path.dirname(target_starship)
        ensure_directory_exists(target_dir)

        if os.path.exists(target_starship):
            backup_path = f"{target_starship}.bak"
            logger.info(f"Backing up existing Starship config to {backup_path}")
            shutil.copy2(target_starship, backup_path)

        shutil.copy2(source_starship, target_starship)
        logger.info("Starship configuration copied successfully")
        return True

    except Exception as e:
        logger.error(f"Error copying Starship configuration: {e}")
        return False



def cleanup_legacy_files(_myhome: str, myodoo_docker: str) -> int:
    """Remove legacy files listed in cleanup_legacy.txt.

    Args:
        _myhome: User's home directory
        myodoo_docker: Path to myodoo-docker repository

    Returns:
        int: Number of files/directories removed
    """
    import glob as glob_module

    cleanup_file = os.path.join(myodoo_docker, "cleanup_legacy.txt")

    if not os.path.exists(cleanup_file):
        logger.warning(f"Cleanup list not found: {cleanup_file}")
        return 0

    removed_count = 0
    skipped_count = 0

    try:
        with open(cleanup_file, 'r') as f:
            lines = f.readlines()

        logger.info("=" * 60)
        logger.info("Cleaning up legacy files...")
        logger.info("=" * 60)

        for line in lines:
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue

            # Expand wildcards
            pattern = os.path.join(_myhome, line)
            matches = glob_module.glob(pattern)

            if not matches:
                # No matches found, that's OK - file might already be removed
                continue

            for filepath in matches:
                try:
                    if os.path.isfile(filepath):
                        os.remove(filepath)
                        logger.info(f"  Removed: {os.path.basename(filepath)}")
                        removed_count += 1
                    elif os.path.isdir(filepath):
                        import shutil
                        shutil.rmtree(filepath)
                        logger.info(f"  Removed directory: {os.path.basename(filepath)}")
                        removed_count += 1
                except PermissionError:
                    logger.warning(f"  Permission denied: {filepath}")
                    skipped_count += 1
                except Exception as e:
                    logger.warning(f"  Could not remove {filepath}: {e}")
                    skipped_count += 1

        if removed_count > 0:
            logger.info(f"Cleanup complete: {removed_count} items removed")
        else:
            logger.info("Cleanup complete: No legacy files found")

        if skipped_count > 0:
            logger.warning(f"  {skipped_count} items could not be removed")

        return removed_count

    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        return 0


def prompt_shell_change(_myhome: str) -> bool:
    """Ask user if they want to change their default shell to Fish.

    Args:
        _myhome: User's home directory

    Returns:
        bool: True if shell was changed
    """
    installed, version = is_fish_installed()
    if not installed:
        return False

    try:
        # Check current shell
        current_shell = os.environ.get('SHELL', '')
        if 'fish' in current_shell:
            logger.info("Fish is already the default shell")
            return True

        # Ask user
        print()
        print("=" * 60)
        print(f"  Fish shell {version} has been installed and configured.")
        print("  Fish is now the recommended shell for this environment.")
        print("=" * 60)
        print()

        response = input("Do you want to set Fish as your default shell? (Y/n): ").strip().lower()

        if response == '' or response == 'y' or response == 'yes':
            # Find fish path
            result = subprocess.run(['which', 'fish'], capture_output=True, text=True)
            if result.returncode == 0:
                fish_path = result.stdout.strip()

                # Check if fish is in /etc/shells
                with open('/etc/shells', 'r') as f:
                    shells = f.read()
                if fish_path not in shells:
                    logger.info(f"Adding {fish_path} to /etc/shells")
                    subprocess.run(["sudo", "tee", "-a", "/etc/shells"], input=f"{fish_path}\n".encode(), stdout=subprocess.DEVNULL)

                # Change shell
                logger.info(f"Changing default shell to {fish_path}")
                run_command(f"chsh -s {fish_path}", check=True)
                logger.info("Default shell changed to Fish!")
                print()
                print("Please log out and log back in for the change to take effect.")
                print("Or start Fish now by typing: fish")
                print()
                return True
        else:
            logger.info("Keeping current shell. You can start Fish manually with: fish")
            return False

    except Exception as e:
        logger.error(f"Error changing shell: {e}")
        return False


def is_zoxide_installed() -> Tuple[bool, Optional[str]]:
    """Check if zoxide is installed and get its version.

    Returns:
        Tuple[bool, Optional[str]]: Installation status and normalized version if installed
    """
    # First try the normal PATH
    try:
        result = subprocess.run(
            ["zoxide", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )
        if result.returncode == 0:
            output = result.stdout.strip() or result.stderr.strip()
            parts = output.split()
            if len(parts) >= 2:
                raw_version = parts[1]
                version = normalize_zoxide_version(raw_version)
                logger.info(f"zoxide version {raw_version} found (normalized: {version})")
                return True, version
    except FileNotFoundError:
        # Try checking in ~/.local/bin directly
        local_zoxide = os.path.expanduser("~/.local/bin/zoxide")
        if os.path.exists(local_zoxide):
            try:
                result = subprocess.run(
                    [local_zoxide, "--version"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False
                )
                if result.returncode == 0:
                    output = result.stdout.strip() or result.stderr.strip()
                    parts = output.split()
                    if len(parts) >= 2:
                        raw_version = parts[1]
                        version = normalize_zoxide_version(raw_version)
                        logger.info(f"zoxide version {raw_version} found in ~/.local/bin (normalized: {version})")
                        return True, version
            except Exception:
                pass

    logger.info("zoxide not found")
    return False, None

@retry_on_exception(retries=3)
def download_and_install_deb(url: str, filename: str) -> None:
    """Download and install a .deb package with retry mechanism and checksum verification.
    
    Args:
        url (str): URL to download the .deb package from
        filename (str): Name to save the file as
    
    Raises:
        Exception: If download or installation fails
    """
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()

        # Download file in chunks
        block_size = 1024
        with open(filename, 'wb') as file:
            for data in response.iter_content(block_size):
                file.write(data)

        # Verify file exists and is not empty
        if not os.path.exists(filename) or os.path.getsize(filename) == 0:
            raise Exception("Downloaded file is empty or does not exist")

        logger.info(f"Successfully downloaded {filename}")

        # Install the package
        subprocess.run(
            ["sudo", "dpkg", "-i", filename],
            capture_output=True,
            text=True,
            check=True
        )
        logger.info(f"Successfully installed {filename}")
        
        # Cleanup
        os.remove(filename)
        logger.info(f"Cleaned up {filename}")
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Download failed: {str(e)}")
        raise
    except subprocess.CalledProcessError as e:
        logger.error(f"Installation failed: {str(e)}")
        if os.path.exists(filename):
            os.remove(filename)
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        if os.path.exists(filename):
            os.remove(filename)
        raise

def get_latest_fastfetch_version() -> Tuple[Optional[str], Optional[List[Dict]]]:
    """Get the latest version of fastfetch from GitHub releases.
    
    Returns:
        Tuple[Optional[str], Optional[List[Dict]]]: Version and assets if available
    """
    cache_key = "fastfetch_latest"
    try:
        response = requests.get("https://api.github.com/repos/fastfetch-cli/fastfetch/releases/latest", timeout=15)
        if response.status_code == 200:
            data = response.json()
            version = data["tag_name"].lstrip('v')
            assets = data["assets"]
            logger.info(f"Found latest FastFetch version: {version}")

            # Cache the result (fallback for future runs when GitHub is down)
            cache_version_info(cache_key, {"version": version, "assets": assets})
            return version, assets
        logger.error(f"Failed to get latest fastfetch version. Status code: {response.status_code}")
    except Exception as e:
        logger.error(f"Error fetching latest fastfetch version: {str(e)}")

    # Fallback: cached value (even stale) so a GitHub outage never blocks the run
    cached_data = get_cached_version(cache_key, allow_stale=True)
    if cached_data:
        logger.warning(f"GitHub not reachable - using cached FastFetch version {cached_data.get('version')}")
        return cached_data.get("version"), cached_data.get("assets")
    return None, None

def get_fastfetch_download_url(_version: str, os_id: str, assets: Optional[List[Dict]] = None) -> Optional[str]:
    """Get the appropriate download URL for fastfetch based on OS.

    Args:
        _version: Version string (currently unused, reserved for future use)
        os_id: Operating system ID
        assets: Optional list of release assets

    Returns:
        Optional[str]: Download URL if found
    """
    try:
        if not assets:
            # Try to get from cache or fetch again
            _, assets = get_latest_fastfetch_version()
            if not assets:
                logger.error("No release assets found")
                return None

        if os_id == "ubuntu" or os_id == "debian":
            arch = "amd64" if platform.machine() == "x86_64" else "arm64"
            target_package = f"fastfetch-linux-{arch}.deb"
            
            # Log available assets for debugging
            logger.info("Available FastFetch packages:")
            for asset in assets:
                logger.info(f"- {asset['name']}")
                if asset["name"] == target_package:
                    logger.info(f"Found matching package: {asset['name']}")
                    return asset["browser_download_url"]
            
            logger.error(f"Package {target_package} not found in release assets")
    except Exception as e:
        logger.error(f"Error getting fastfetch download URL: {str(e)}")
    return None

def install_fastfetch_if_needed() -> None:
    """Install or update fastfetch to the latest version."""
    try:
        os_id, _ = get_os_info()
        
        # Skip if not on Linux
        if os_id not in ["ubuntu", "debian"]:
            logger.info("Fastfetch auto-update only supported on Ubuntu/Debian")
            return

        # Get current version if installed
        installed, current_version = is_fastfetch_installed()
        logger.info(f"Current FastFetch version: {current_version if installed else 'not installed'}")
        
        # Get latest version from GitHub
        latest_version, assets = get_latest_fastfetch_version()
        if not latest_version:
            logger.error("Could not determine latest fastfetch version")
            return

        # Check if update is needed
        if installed and current_version == latest_version:
            logger.info(f"Fastfetch is already at the latest version ({latest_version})")
            return

        # Get download URL
        download_url = get_fastfetch_download_url(latest_version, os_id, assets)
        if not download_url:
            logger.error("Could not find appropriate fastfetch package")
            return

        # Download and install
        filename = f"fastfetch_{latest_version}.deb"
        logger.info(f"Installing fastfetch version {latest_version} from {download_url}...")
        download_and_install_deb(download_url, filename)
        logger.info("Fastfetch installation completed")

    except Exception as e:
        logger.error(f"Error installing fastfetch: {str(e)}")

def get_latest_zoxide_version() -> Optional[str]:
    """Get the latest version of zoxide from GitHub releases.

    Returns:
        Optional[str]: Version string if available
    """
    cache_key = "zoxide_latest"
    try:
        response = requests.get("https://api.github.com/repos/ajeetdsouza/zoxide/releases/latest", timeout=15)
        if response.status_code == 200:
            data = response.json()
            version = data["tag_name"].lstrip('v')
            logger.info(f"Found latest zoxide version: {version}")

            # Cache the result (fallback for future runs when GitHub is down)
            cache_version_info(cache_key, {"version": version})
            return version
        logger.error(f"Failed to get latest zoxide version. Status code: {response.status_code}")
    except Exception as e:
        logger.error(f"Error fetching latest zoxide version: {str(e)}")

    # Fallback: cached value (even stale) so a GitHub outage never blocks the run
    cached_data = get_cached_version(cache_key, allow_stale=True)
    if cached_data:
        logger.warning(f"GitHub not reachable - using cached zoxide version {cached_data.get('version')}")
        return cached_data.get("version")
    return None

def install_zoxide_if_needed(target_version: Optional[str] = None) -> None:
    """Install zoxide if it's not already installed or if the version is outdated."""
    installed, current_version = is_zoxide_installed()

    # Use target_version if provided, otherwise fetch from GitHub
    if target_version:
        latest_version = target_version
    else:
        latest_version = get_latest_zoxide_version()
    if not latest_version:
        logger.warning("Could not determine latest zoxide version, skipping update check")
        if installed:
            logger.info(f"zoxide version {current_version} is already installed.")
            return
        # Use a fallback version if we can't get the latest
        latest_version = "0.9.9"

    if installed:
        if current_version == latest_version:
            logger.info(f"zoxide version {latest_version} is already installed.")
            # Ensure PATH is set correctly
            local_bin = os.path.expanduser("~/.local/bin")
            if local_bin not in os.environ.get("PATH", ""):
                logger.info(f"Adding {local_bin} to PATH...")
                os.environ["PATH"] = f"{local_bin}:{os.environ.get('PATH', '')}"
            return
        else:
            # Compare versions to decide if update is needed
            try:
                from packaging import version as pkg_version
                if pkg_version.parse(current_version) >= pkg_version.parse(latest_version):
                    logger.info(f"zoxide version {current_version} is already up to date (latest: {latest_version}).")
                    return
            except ImportError:
                # Fallback to simple string comparison if packaging module not available
                logger.debug("packaging module not available, falling back to string comparison")
            except Exception as version_error:
                # Handle invalid version strings gracefully
                logger.warning(f"Could not parse zoxide version '{current_version}': {version_error}")
                logger.info("Proceeding with version update check using string comparison")
            logger.info(f"zoxide version {current_version} is installed, updating to version {latest_version}.")
    else:
        logger.info("zoxide is not installed.")

    logger.info(f"Installing zoxide version {latest_version}...")

    # Try system package manager first (apt for Debian/Ubuntu, apk for Alpine)
    os_id, _ = get_os_info()
    if os_id in ("debian", "ubuntu"):
        logger.info("Using apt to install/update zoxide...")
        try:
            run_command("apt-get update -qq", shell=True, check=True, capture_output=True)
            run_command("apt-get install -y -qq zoxide", shell=True, check=True, capture_output=True)
            logger.info("zoxide installed/updated successfully via apt.")
            return
        except Exception as e:
            logger.warning(f"apt install failed: {e}, trying curl installer as fallback...")
    elif os_id == "alpine" or is_musl_system():
        logger.info("Detected musl/Alpine system, using apk to install zoxide...")
        try:
            run_command("apk add --no-cache zoxide", shell=True, check=True, capture_output=True)
            logger.info("zoxide installed successfully via apk.")
            return
        except Exception as e:
            logger.warning(f"apk install failed: {e}")
            logger.warning("zoxide is optional - continuing without it.")
            return

    # Fallback: install the official .deb release from GitHub (replaces the
    # former `curl install.sh | sh` pipe - no remote shell execution as root)
    try:
        machine = platform.machine().lower()
        deb_arch = "arm64" if machine in ("aarch64", "arm64") else "amd64"
        deb_url = f"https://github.com/ajeetdsouza/zoxide/releases/download/v{latest_version}/zoxide_{latest_version}-1_{deb_arch}.deb"
        deb_file = f"/tmp/zoxide_{latest_version}_{deb_arch}.deb"
        logger.info(f"Downloading zoxide {latest_version} .deb package...")
        run_command(f"curl -fsSL {deb_url} -o {deb_file}", shell=True, check=True)
        run_command(f"sudo dpkg -i {deb_file}", shell=True, check=True, capture_output=True)
        os.remove(deb_file)
        logger.info(f"zoxide {latest_version} installed successfully.")
    except Exception as e:
        logger.warning(f"zoxide installation failed (this is not critical): {str(e)}")
        if hasattr(e, 'stderr') and e.stderr:
            logger.warning(f"zoxide install stderr: {e.stderr}")
        logger.warning("zoxide is optional - continuing without it. You can install it manually if needed.")

def ensure_directory_exists(directory: str) -> None:
    """Ensure a directory exists, creating it if necessary."""
    os.makedirs(directory, exist_ok=True)
    logger.info(f"Directory '{directory}' was created or already exists.")

class CommandError(Exception):
    """Custom exception for command execution errors."""
    pass

class InstallationError(Exception):
    """Custom exception for installation errors."""
    pass

def run_command(command: str, check: bool = False, shell: bool = False, capture_output: bool = False, retries: int = 0) -> subprocess.CompletedProcess:
    """Run a shell command with optional error checking and retry logic.
    
    Args:
        command: Command to run
        check: Whether to raise exception on non-zero exit
        shell: Whether to run through shell
        capture_output: Whether to capture stdout/stderr
        retries: Number of retry attempts for transient failures
        
    Returns:
        subprocess.CompletedProcess: Result of the command
        
    Raises:
        CommandError: If command fails and check=True
    """
    # If the command contains shell operators like |, &&, ||, >, <, etc., force shell=True
    if any(op in command for op in ['|', '&&', '||', '>', '<', '>>', '<<']):
        shell = True
    
    # Check if we're in a valid directory before running command
    try:
        os.getcwd()
    except FileNotFoundError:
        # If current directory doesn't exist, move to home directory
        logger.warning("Current directory doesn't exist, moving to home directory")
        os.chdir(os.path.expanduser("~"))

    for attempt in range(retries + 1):
        try:
            if shell:
                logger.debug(f"Running shell command (attempt {attempt + 1}): {command}")
                result = subprocess.run(command, shell=True, check=False, capture_output=capture_output)
            else:
                logger.debug(f"Running command (attempt {attempt + 1}): {command}")
                result = subprocess.run(command.split(), check=False, capture_output=capture_output)

            if result.returncode != 0:
                error_msg = f"Command returned non-zero exit code: {result.returncode}"
                if capture_output and result.stderr:
                    error_msg += f"\nError output: {result.stderr.decode('utf-8', errors='replace')}"

                if check:
                    raise CommandError(error_msg)
                else:
                    logger.warning(error_msg)

            return result

        except Exception as e:
            if attempt < retries:
                logger.warning(f"Command failed on attempt {attempt + 1}, retrying...")
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                logger.error(f"Command failed after {retries + 1} attempts: {e}")
                if check:
                    raise CommandError(f"Command failed: {command}") from e
    
    return subprocess.CompletedProcess(command, -1, '', '')  # Return failed result

def is_root_or_has_sudo() -> bool:
    """Check if running as root or has sudo privileges"""
    # Check if running as root
    if os.geteuid() == 0:
        return True

    # Check if sudo is available
    try:
        result = subprocess.run(['sudo', '-n', 'true'],
                              capture_output=True,
                              stderr=subprocess.DEVNULL)
        return result.returncode == 0
    except Exception:
        return False

def is_debian_or_ubuntu() -> bool:
    """Check if the system is Debian or Ubuntu"""
    try:
        with open("/etc/os-release") as f:
            content = f.read().lower()
            return any(os_name in content for os_name in ["debian", "ubuntu"])
    except Exception as e:
        logger.error(f"Error checking OS: {str(e)}")
        return False

def get_os_info():
    """Get operating system information."""
    try:
        with open("/etc/os-release") as f:
            lines = f.readlines()
            info = dict(line.strip().split('=', 1) for line in lines if '=' in line)
            return info.get('ID', '').strip('"'), info.get('VERSION_ID', '').strip('"')
    except:
        return "unknown", ""

def is_musl_system() -> bool:
    """Check if the system uses musl libc (e.g., Alpine Linux).

    Returns:
        bool: True if musl libc is detected, False otherwise
    """
    # Check /etc/os-release for Alpine
    os_id, _ = get_os_info()
    if os_id == "alpine":
        return True
    # Check for musl libc binary
    try:
        result = subprocess.run(
            ["ldd", "--version"],
            capture_output=True, text=True, timeout=5
        )
        output = (result.stdout + result.stderr).lower()
        return "musl" in output
    except Exception:
        return False

def get_pip_version():
    """Get pip version as a tuple of integers."""
    try:
        result = subprocess.run([sys.executable, "-m", "pip", "--version"],
                              capture_output=True, text=True)
        if result.returncode != 0:
            return (0, 0)
        version_str = result.stdout.split()[1]
        return tuple(map(int, version_str.split('.')))
    except:
        return (0, 0)


def is_pip_installed() -> bool:
    """Check if pip module is available for Python."""
    try:
        result = subprocess.run([sys.executable, "-m", "pip", "--version"],
                              capture_output=True, text=True)
        return result.returncode == 0
    except:
        return False


def ensure_pip_installed() -> None:
    """Ensure pip is installed, install via apt if missing."""
    if is_pip_installed():
        logger.info("pip is already installed")
        return

    logger.info("pip is not installed, installing python3-pip via apt...")

    try:
        # Check if we have sudo privileges
        if not is_root_or_has_sudo():
            logger.error("Cannot install python3-pip: no sudo privileges")
            raise RuntimeError("pip is not installed and cannot be installed without sudo")

        # Install python3-pip via apt
        run_command("sudo apt update")
        run_command("sudo apt install -y python3-pip")

        # Verify installation
        if not is_pip_installed():
            raise RuntimeError("Failed to install python3-pip")

        # Show installed version
        version = get_pip_version()
        logger.info(f"pip installed successfully, version: {'.'.join(map(str, version))}")

    except Exception as e:
        logger.error(f"Error installing pip: {str(e)}")
        raise


def get_pip_install_command(package_name: str, upgrade: bool = True) -> str:
    """Generate appropriate pip install command based on system version."""
    os_id, os_version = get_os_info()
    pip_version = get_pip_version()
    
    # Base command
    cmd = [sys.executable, "-m", "pip", "install"]
    
    if upgrade:
        cmd.append("--upgrade")
    
    cmd.extend(["--quiet", "--no-warn-script-location"])
    
    # Add flags based on OS and pip version
    if pip_version >= (23, 1):
        # Newer versions of pip support --break-system-packages
        cmd.append("--break-system-packages")
    elif os_id == "ubuntu" and os_version == "22.04":
        # For Ubuntu 22.04 with older pip, use --user
        cmd.append("--user")
    
    # Only add root-user-action for newer pip versions
    if pip_version >= (21, 3):
        cmd.append("--root-user-action=ignore")
    
    # Add the package name last
    cmd.append(package_name)
    
    return " ".join(cmd)

def get_pip_package_version(package_name: str) -> Optional[str]:
    """Get the installed version of a pip package.
    
    Args:
        package_name: Name of the package
        
    Returns:
        Optional[str]: Version string if installed, None otherwise
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", package_name],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if line.startswith('Version:'):
                    return line.split(':', 1)[1].strip()
    except Exception as e:
        logger.error(f"Error getting pip package version for {package_name}: {e}")
    return None

def upgrade_pip_package(package_name: str) -> None:
    """Upgrade a pip package to the latest version only if needed."""
    # Skip packages that should not be upgraded through pip (system-managed)
    system_managed_packages = ["zstd", "pip", "wheel", "setuptools"]

    if package_name in system_managed_packages:
        logger.info(f"Skipping {package_name} upgrade - managed by system package manager.")
        return

    # Check current version
    current_version = get_pip_package_version(package_name)
    
    # Get latest version from PyPI
    latest_version = get_latest_pypi_version(package_name)
    
    if not latest_version:
        logger.warning(f"Could not determine latest version for {package_name}")
        # Install anyway if not installed
        if not current_version:
            cmd = get_pip_install_command(package_name, upgrade=True)
            run_command(cmd)
        return
    
    # Check if update is needed
    if current_version and current_version == latest_version:
        logger.info(f"{package_name} is already at the latest version ({latest_version})")
        return
    
    # Update needed
    logger.info(f"Updating {package_name} from {current_version or 'not installed'} to {latest_version}")
    cmd = get_pip_install_command(package_name, upgrade=True)
    run_command(cmd)

def uninstall_pip_package(package_name: str) -> None:
    """Uninstall a pip package."""
    os_id, os_version = get_os_info()
    pip_version = get_pip_version()
    
    # Base command
    cmd = [sys.executable, "-m", "pip", "uninstall", "-y"]
    
    # Add flags based on OS and pip version
    if pip_version >= (23, 1):
        cmd.append("--break-system-packages")
    elif os_id == "ubuntu" and os_version == "22.04":
        cmd.append("--user")
    
    # Only add root-user-action for newer pip versions
    if pip_version >= (21, 3):
        cmd.append("--root-user-action=ignore")
    
    # Add the package name last
    cmd.append(package_name)
    
    run_command(" ".join(cmd))

def is_pip_package_installed(package_name: str) -> bool:
    """Check if a pip package is installed.
    
    Args:
        package_name (str): Name of the package to check
        
    Returns:
        bool: True if package is installed, False otherwise
    """
    try:
        subprocess.run([sys.executable, "-m", "pip", "show", package_name], 
                      check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError:
        return False

def is_uv_installed() -> bool:
    """Check if uv is installed.

    Checks PATH first, then common installation directories
    (~/.local/bin, ~/.cargo/bin) and adds them to PATH if found.

    Returns:
        bool: True if uv is installed, False otherwise
    """
    # First try uv in current PATH
    try:
        result = subprocess.run(['uv', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            return True
    except FileNotFoundError:
        pass

    # Check common installation directories
    for bin_dir in [os.path.expanduser("~/.local/bin"), os.path.expanduser("~/.cargo/bin")]:
        uv_path = os.path.join(bin_dir, "uv")
        if os.path.isfile(uv_path) and os.access(uv_path, os.X_OK):
            logger.info(f"Found uv at {uv_path}, adding {bin_dir} to PATH")
            os.environ["PATH"] = f"{bin_dir}:{os.environ.get('PATH', '')}"
            return True

    logger.info("uv is not installed")
    return False

def install_uv() -> bool:
    """Install uv from the official GitHub release tarball.

    Replaces the former `curl https://astral.sh/uv/install.sh | sh` pipe -
    no remote shell execution.

    Returns:
        bool: True if uv is available after installation
    """
    logger.info("Installing uv...")
    try:
        machine = platform.machine().lower()
        target = "aarch64-unknown-linux-gnu" if machine in ("aarch64", "arm64") else "x86_64-unknown-linux-gnu"
        tarball_url = f"https://github.com/astral-sh/uv/releases/latest/download/uv-{target}.tar.gz"
        tmp_tarball = "/tmp/uv.tar.gz"
        local_bin = os.path.expanduser("~/.local/bin")
        os.makedirs(local_bin, exist_ok=True)
        logger.info(f"Downloading uv release tarball ({target})...")
        run_command(f"curl -fsSL {tarball_url} -o {tmp_tarball}", shell=True, check=True)
        run_command(
            f"tar -xzf {tmp_tarball} -C {local_bin} --strip-components=1 uv-{target}/uv uv-{target}/uvx",
            shell=True, check=True
        )
        run_command(f"chmod 755 {local_bin}/uv {local_bin}/uvx", shell=True, check=True)
        os.remove(tmp_tarball)
        # Ensure ~/.local/bin and ~/.cargo/bin are in PATH for current session
        local_bin = os.path.expanduser("~/.local/bin")
        if local_bin not in os.environ.get("PATH", ""):
            os.environ["PATH"] = f"{local_bin}:{os.environ.get('PATH', '')}"
        cargo_bin = os.path.expanduser("~/.cargo/bin")
        if cargo_bin not in os.environ.get("PATH", ""):
            os.environ["PATH"] = f"{cargo_bin}:{os.environ.get('PATH', '')}"
        logger.info("Successfully installed uv")
        return True
    except Exception as e:
        logger.error(f"Failed to install uv: {e}")
        return False

def install_with_uv_tool(package_name: str) -> None:
    """Install a package using uv tool.

    Args:
        package_name (str): Name of the package to install
    """
    if not is_uv_installed():
        if not install_uv():
            raise RuntimeError("uv is not installed. Installation failed.")

    try:
        subprocess.run(['uv', 'tool', 'install', '--force', package_name], check=True)
        logger.info(f"Successfully installed {package_name} with uv tool")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to install {package_name} with uv tool: {e}")
        raise

def install_specific_uv_tool_package(package_name: str, version: str) -> None:
    """
    Install a specific version of a package using uv tool if it's not already installed.

    Args:
        package_name (str): Name of the package to install
        version (str): Specific version to install
    """
    try:
        # Check if package is installed and get its version
        current_version = get_installed_uv_tool_version(package_name)

        if current_version:
            if current_version == version:
                logger.info(f"{package_name} version {version} is already installed")
                return
            else:
                logger.info(f"Updating {package_name} from version {current_version} to {version}")
                run_command(f"uv tool install --force {package_name}=={version}")
        else:
            logger.info(f"Installing {package_name} version {version}")
            run_command(f"uv tool install {package_name}=={version}")
    except Exception as e:
        logger.error(f"Unexpected error installing {package_name}: {str(e)}")

def is_pipx_installed_legacy() -> bool:
    """Check if pipx is still installed (for migration purposes).

    Returns:
        bool: True if pipx is still present
    """
    try:
        result = subprocess.run(['which', 'pipx'], capture_output=True, text=True)
        return result.returncode == 0
    except Exception:
        return False

def migrate_from_pipx() -> None:
    """Migrate from pipx to uv: uninstall pipx tools and remove pipx.
    Non-critical - logs warnings on failure.
    """
    if not is_pipx_installed_legacy():
        return

    logger.info("Migrating from pipx to uv: cleaning up pipx installation...")

    # Uninstall all pipx packages first
    try:
        result = subprocess.run(
            ['pipx', 'list', '--short'],
            capture_output=True, text=True, check=False
        )
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().split('\n'):
                pkg = line.strip().split()[0] if line.strip() else None
                if pkg:
                    logger.info(f"Uninstalling pipx package: {pkg}")
                    try:
                        subprocess.run(['pipx', 'uninstall', pkg], check=False, capture_output=True)
                    except Exception as e:
                        logger.warning(f"Failed to uninstall pipx package {pkg}: {e}")
    except Exception as e:
        logger.warning(f"Failed to list pipx packages: {e}")

    # Remove pipx via apt
    try:
        run_command("sudo apt remove -y pipx")
        logger.info("Successfully removed pipx")
    except Exception as e:
        logger.warning(f"Failed to remove pipx via apt: {e}")

def read_package_versions(filename: str = "packages.txt") -> dict:
    """Read package versions from packages.txt file.
    Supports both '# UV tool packages' and legacy '# PIPX packages' section headers.

    Returns:
        dict: Dictionary containing package types and their versions
    """
    packages = {
        "uv_tools": {},
        "pip": [
            # NOTE: python-dotenv is intentionally NOT here. It is installed via
            # apt (python3-dotenv, see packages.txt # System packages) because
            # modern Debian/Ubuntu mark system python3 externally-managed
            # (PEP 668) and `pip install` as root fails.
        ],
        "system": []
    }

    try:
        with open(filename, 'r') as f:
            current_section = None
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    if "UV tool packages" in line or "PIPX packages" in line:
                        current_section = "uv_tools"
                    elif "PIP packages" in line:
                        current_section = "pip"
                    elif "System packages" in line:
                        current_section = "system"
                    continue

                if current_section == "uv_tools":
                    if "==" in line:
                        name, version = line.split("==")
                        packages["uv_tools"][name.strip()] = version.strip()
                    else:
                        packages["uv_tools"][line.strip()] = None
                elif current_section == "pip":
                    packages["pip"].append(line.strip())
                elif current_section == "system":
                    packages["system"].append(line.strip())

        return packages
    except FileNotFoundError:
        logger.error(f"Package file {filename} not found")
        return packages

def is_package_installed(package_name: str) -> bool:
    """Check if a system package is installed using dpkg."""
    try:
        result = subprocess.run(['dpkg', '-l', package_name], 
                              capture_output=True, 
                              text=True)
        return f"ii  {package_name}" in result.stdout
    except Exception:
        return False

def get_system_package_version(package_name: str) -> Optional[str]:
    """Get the installed version of a system package."""
    try:
        result = subprocess.run(["dpkg-query", "-W", "-f=${Version}", package_name], 
                             capture_output=True, text=True)
        if result.returncode == 0 and result.stdout:
            # Remove Ubuntu/Debian specific version info (e.g., -1ubuntu1)
            version = result.stdout.split('-')[0]
            return version
    except Exception as e:
        logger.error(f"Error getting version for {package_name}: {str(e)}")
    return None

def compare_versions(version1: str, version2: str) -> int:
    """Compare two version strings.
    Returns:
        -1 if version1 < version2
         0 if version1 == version2
         1 if version1 > version2
    """
    def normalize(v):
        return [int(x) for x in v.split('.')]

    try:
        v1 = normalize(version1)
        v2 = normalize(version2)
        
        for i in range(max(len(v1), len(v2))):
            n1 = v1[i] if i < len(v1) else 0
            n2 = v2[i] if i < len(v2) else 0
            if n1 < n2:
                return -1
            elif n1 > n2:
                return 1
        return 0
    except Exception:
        # If version comparison fails, assume versions are different
        return -1

def install_system_package(package: str, version: Optional[str] = None) -> None:
    """Install a system package with version checking and error recovery.

    Args:
        package: Package name
        version: Optional specific version to install

    Raises:
        InstallationError: If installation fails after retries
    """
    # Check if we have sudo privileges
    if not is_root_or_has_sudo():
        logger.warning(f"Skipping system package installation for {package} (no sudo privileges)")
        return

    try:
        current_version = get_system_package_version(package)

        if current_version:
            if version:
                # If specific version is requested, compare versions
                if compare_versions(current_version, version) >= 0:
                    logger.info(f"{package} version {current_version} is already installed (requested: {version})")
                    return
            else:
                # If no specific version requested, just log current version
                logger.info(f"{package} is already installed (version {current_version})")
                return

        # Update package list before installation
        logger.info("Updating package list...")
        try:
            run_command("sudo apt update", check=True, retries=2)
        except CommandError:
            logger.warning("Failed to update package list, continuing anyway...")

        # Install package
        logger.info(f"Installing {package}{f' version {version}' if version else ''}")
        install_cmd = f"sudo apt install -y {package}" + (f"={version}" if version else "")

        try:
            run_command(install_cmd, check=True, retries=1)
        except CommandError as e:
            # Try to fix broken packages
            logger.warning("Installation failed, attempting to fix broken packages...")
            run_command("sudo apt-get -f install -y", check=False)

            # Retry installation
            run_command(install_cmd, check=True)

    except Exception as e:
        raise InstallationError(f"Failed to install {package}: {str(e)}") from e

def get_bat_version() -> Optional[tuple]:
    """Get installed bat version as tuple (major, minor, patch)"""
    try:
        # On Debian/Ubuntu systems, bat is installed as batcat
        result = subprocess.run(['batcat', '--version'], capture_output=True, text=True)
            
        if result.returncode == 0:
            # bat output format: "bat 0.22.1"
            version_str = result.stdout.split()[1]
            return tuple(map(int, version_str.split('.')))
    except Exception as e:
        logger.error(f"Error getting bat version: {str(e)}")
    return None

def check_bat_version() -> bool:
    """Check if bat is installed and up to date"""
    current_version = get_bat_version()
    if not current_version:
        logger.error("bat is not installed")
        return False

    logger.info(f"Current bat version: {'.'.join(map(str, current_version))}")
    return True

@lru_cache(maxsize=128)
def get_latest_bat_version() -> Optional[str]:
    """Get the latest version of bat from GitHub releases with caching.
    
    Returns:
        Optional[str]: Latest version string if available, None otherwise
    """
    cache_key = "bat_latest"
    try:
        response = requests.get("https://api.github.com/repos/sharkdp/bat/releases/latest", timeout=15)
        if response.status_code == 200:
            data = response.json()
            version = data["tag_name"].lstrip('v')
            logger.info(f"Found latest bat version: {version}")

            # Cache the result (fallback for future runs when GitHub is down)
            cache_version_info(cache_key, {"version": version})
            return version
        logger.error(f"Failed to get latest bat version. Status code: {response.status_code}")
    except Exception as e:
        logger.error(f"Error fetching latest bat version: {str(e)}")

    # Fallback: cached value (even stale) so a GitHub outage never blocks the run
    cached_data = get_cached_version(cache_key, allow_stale=True)
    if cached_data:
        logger.warning(f"GitHub not reachable - using cached bat version {cached_data.get('version')}")
        return cached_data.get("version")
    return None

def install_or_update_bat():
    """Install or update bat package with upstream version checking"""
    try:
        current_version = get_bat_version()
        latest_version = get_latest_bat_version()
        
        if current_version:
            current_str = '.'.join(map(str, current_version))
            logger.info(f"Current bat version: {current_str}")
            
            if latest_version:
                logger.info(f"Latest bat version available: {latest_version}")
                if compare_versions(current_str, latest_version) >= 0:
                    logger.info(f"bat is already at or newer than the latest version ({current_str} >= {latest_version})")
                    return
                else:
                    logger.info(f"bat update available: {current_str} -> {latest_version}")
        
        if not check_bat_version():
            logger.info("Installing/updating bat...")
            run_command("sudo apt update")
            run_command("sudo apt install -y bat")
            
            # Verify installation
            if not check_bat_version():
                raise RuntimeError("Failed to install/update bat")
            
            new_version = get_bat_version()
            if new_version:
                new_str = '.'.join(map(str, new_version))
                logger.info(f"bat installation/update completed: {new_str}")
                
                # Check if this is the latest available
                if latest_version and compare_versions(new_str, latest_version) < 0:
                    logger.warning(f"Installed bat {new_str} is older than latest {latest_version}. Consider manual update from source.")
    except Exception as e:
        logger.error(f"Error installing/updating bat: {str(e)}")
        raise RuntimeError("Failed to install/update bat")

def get_zstd_version() -> Optional[tuple]:
    """Get installed zstd version as tuple (major, minor, patch)"""
    try:
        result = subprocess.run(['zstd', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            # zstd output format: "*** Zstandard CLI (64-bit) v1.5.5, by Yann Collet ***"
            version_str = result.stdout.strip()
            # Find the version number after 'v' and before the comma
            version_match = re.search(r'v(\d+\.\d+\.\d+)', version_str)
            if version_match:
                return tuple(map(int, version_match.group(1).split('.')))
    except Exception as e:
        logger.error(f"Error getting zstd version: {str(e)}")
    return None

def check_zstd_version() -> bool:
    """Check if zstd is installed and meets minimum version requirements"""
    try:
        version = get_zstd_version()
        if not version:
            logger.error("zstd is not installed")
            return False
            
        version_str = '.'.join(map(str, version))
        logger.info(f"Current zstd version: {version_str}")
        
        # For Ubuntu, accept version 1.4.8
        if is_debian_or_ubuntu():
            min_version = "1.4.8"
        else:
            min_version = "1.5.0"
            
        min_version_tuple = tuple(map(int, min_version.split('.')))
        if version < min_version_tuple:
            logger.warning(f"zstd version {version_str} is outdated. Minimum required version is {min_version}")
            return False
        return True
    except Exception as e:
        logger.error(f"Error checking zstd version: {str(e)}")
        return False

def install_or_update_zstd():
    """Install or update zstd package"""
    os_id, os_version = get_os_info()
    
    try:
        if not check_zstd_version():
            logger.info("Installing/updating zstd...")
            if os_id in ["ubuntu", "debian"]:
                # First install python3-dev which is required for building the zstd Python package
                logger.info("Installing python3-dev which is required for building zstd Python package")
                run_command("sudo apt update")
                run_command("sudo apt install -y python3-dev")
                
                # Check OS version to determine installation method
                if os_id == "ubuntu" and os_version.startswith("20.04"):
                    # Ubuntu 20.04 has outdated zstd in repos, need to install from newer source
                    logger.info("Ubuntu 20.04 detected, installing newer zstd version")
                    # Add Ubuntu 22.04 repository for newer zstd
                    run_command("sudo add-apt-repository -y 'deb http://archive.ubuntu.com/ubuntu jammy main universe'")
                    run_command("sudo apt update")
                    # Install specific version that meets requirements
                    run_command("sudo apt install -y -t jammy zstd")
                else:
                    # Standard installation for other versions
                    run_command("sudo apt install -y zstd")
                
                # Try to install zstd with PEP 517 build to avoid deprecation warning
                logger.info("Installing zstd Python package with PEP 517 build")
                run_command(f"{sys.executable} -m pip install --upgrade zstd --use-pep517")
            
            # Verify installation
            if not check_zstd_version():
                raise RuntimeError("Failed to install/update zstd")
            
            logger.info("zstd installation/update completed")
    except Exception as e:
        logger.error(f"Error installing/updating zstd: {str(e)}")
        raise

def upgrade_pip() -> None:
    """Upgrade pip to the latest version. Installs pip first if not available."""
    try:
        # First ensure pip is installed
        ensure_pip_installed()

        logger.info("Checking pip version...")
        current_version = get_pip_version()
        logger.info(f"Current pip version: {'.'.join(map(str, current_version))}")

        if current_version < (23, 0):
            logger.info("Upgrading pip to latest version...")
            # Use a basic command for old pip versions
            run_command(f"{sys.executable} -m pip install --upgrade pip --user")

            # Verify upgrade
            new_version = get_pip_version()
            logger.info(f"Upgraded pip to version {'.'.join(map(str, new_version))}")
    except Exception as e:
        logger.error(f"Error upgrading pip: {str(e)}")

def _extract_7zip_version_line(output: str) -> str:
    """Return the first output line that contains a version-like token.

    Newer 7-Zip releases (e.g. 26.01) emit a leading blank line for
    `7zz --help`, so parsing line 0 unconditionally yields an empty string.
    Scanning for the first line containing a `\\d+.\\d+` token is robust
    against that and future formatting changes.
    """
    for line in output.splitlines():
        if re.search(r'\d+\.\d+', line):
            return line.strip()
    return ""

def get_7zip_version() -> Optional[tuple]:
    """Get installed 7-Zip version as tuple (major, minor, patch).

    Checks multiple locations for the 7zz binary and parses its version output.
    """
    import shutil

    # Try to find 7zz in common locations
    seven_zz_paths = [
        shutil.which('7zz'),
        '/usr/local/bin/7zz',
        os.path.expanduser('~/.local/bin/7zz')
    ]

    seven_zz_cmd = None
    for path in seven_zz_paths:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            seven_zz_cmd = path
            break

    # Try 7zz (new version) using the found path
    if seven_zz_cmd:
        try:
            result = subprocess.run([seven_zz_cmd, '--help'],
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                # 7zz output format: "7-Zip (z) [64] 24.08 : Copyright (c) 1999-2024 Igor Pavlov"
                version_line = _extract_7zip_version_line(result.stdout)
                version_match = re.search(r'(\d+)\.(\d+)', version_line)
                if version_match:
                    major = int(version_match.group(1))
                    minor = int(version_match.group(2))
                    return (major, minor, 0)
        except subprocess.TimeoutExpired:
            logger.debug(f"Timeout running {seven_zz_cmd}")
        except Exception as e:
            logger.debug(f"Error running {seven_zz_cmd}: {str(e)}")

    # Fall back to checking old 7z command (p7zip-full)
    try:
        result = subprocess.run(['7z', '--help'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            # 7-Zip output format: "7-Zip [64] 16.02"
            lines = result.stdout.split('\n')
            version_line = lines[1].strip() if len(lines) > 1 else lines[0].strip()
            version_match = re.search(r'(\d+)\.(\d+)', version_line)
            if version_match:
                major = int(version_match.group(1))
                minor = int(version_match.group(2))
                return (major, minor, 0)
    except Exception:
        pass  # Old 7z not available, continue

    # Check using dpkg if we're on Debian/Ubuntu
    try:
        if is_debian_or_ubuntu():
            result = subprocess.run(['dpkg', '-s', '7zip'], capture_output=True, text=True)
            if result.returncode == 0:
                version_match = re.search(r'Version: (\d+)\.(\d+)', result.stdout)
                if version_match:
                    major = int(version_match.group(1))
                    minor = int(version_match.group(2))
                    return (major, minor, 0)
    except Exception:
        pass

    return None

def check_7zip_version() -> bool:
    """Check if 7-Zip is installed and meets minimum version requirements.

    Supports both apt-installed and manually installed 7zz binaries.
    """
    import shutil

    min_version = (21, 0, 0)  # 21.x is newer and preferred

    try:
        # Check common installation paths for 7zz binary
        seven_zz_paths = [
            shutil.which('7zz'),  # Check PATH
            '/usr/local/bin/7zz',  # System-wide installation
            os.path.expanduser('~/.local/bin/7zz')  # User installation
        ]

        seven_zz_path = None
        for path in seven_zz_paths:
            if path and os.path.isfile(path) and os.access(path, os.X_OK):
                seven_zz_path = path
                break

        if not seven_zz_path:
            logger.warning("7zz command not found. Need to install newer 7-Zip version.")
            return False

        # Binary found - get version directly from it
        try:
            result = subprocess.run([seven_zz_path, '--help'], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                # 7zz output format: "7-Zip (z) [64] 24.08 : Copyright (c) 1999-2024 Igor Pavlov"
                version_line = _extract_7zip_version_line(result.stdout)
                version_match = re.search(r'(\d+)\.(\d+)', version_line)
                if version_match:
                    major = int(version_match.group(1))
                    minor = int(version_match.group(2))
                    version = (major, minor, 0)
                    version_str = f"{major}.{minor}"
                    logger.info(f"Current 7-Zip version: {version_str} (found at {seven_zz_path})")

                    if version < min_version:
                        logger.warning(f"7-Zip version {version_str} is outdated. "
                                     f"Minimum required: {min_version[0]}.{min_version[1]}")
                        return False
                    return True
                else:
                    # Version not parseable but binary works
                    logger.info(f"7-Zip found at {seven_zz_path} but version not parseable. Assuming valid.")
                    return True
            else:
                logger.warning(f"7zz at {seven_zz_path} returned error code {result.returncode}")
                return False
        except subprocess.TimeoutExpired:
            logger.warning(f"7zz at {seven_zz_path} timed out")
            return False
        except Exception as e:
            logger.warning(f"Error running 7zz at {seven_zz_path}: {str(e)}")
            return False

    except Exception as e:
        logger.error(f"Error checking 7-Zip version: {str(e)}")
        return False

@lru_cache(maxsize=128)
def get_latest_7zip_version() -> Tuple[Optional[str], Optional[List[Dict]]]:
    """Get latest 7-Zip version + assets from the official ip7z/7zip GitHub mirror.

    7-Zip's own server (www.7-zip.org/a/) only keeps the current release, so old
    pinned URLs return 404. The GitHub mirror keeps all release assets permanently.

    Returns:
        Tuple[Optional[str], Optional[List[Dict]]]: (version, assets) on success,
        (None, None) otherwise.
    """
    cache_key = "7zip_latest"
    try:
        response = requests.get("https://api.github.com/repos/ip7z/7zip/releases/latest", timeout=15)
        if response.status_code == 200:
            data = response.json()
            version = data["tag_name"].lstrip("v")  # e.g. "26.01"
            assets = data.get("assets", [])
            logger.info(f"Found latest 7-Zip version: {version}")
            cache_version_info(cache_key, {"version": version, "assets": assets})
            return version, assets
        logger.error(f"Failed to get latest 7-Zip version. Status code: {response.status_code}")
    except Exception as e:
        logger.error(f"Error fetching latest 7-Zip version: {str(e)}")

    # Fallback: cached value (even stale) so a GitHub outage never blocks the run
    cached_data = get_cached_version(cache_key, allow_stale=True)
    if cached_data:
        logger.warning(f"GitHub not reachable - using cached 7-Zip version {cached_data.get('version')}")
        return cached_data.get("version"), cached_data.get("assets")
    return None, None

def install_or_update_7zip():
    """Install or update 7-Zip package with official version that provides 7zz command"""
    try:
        # Check if we have sudo privileges
        has_sudo = is_root_or_has_sudo()

        # First check if p7zip-full is installed and remove it if needed
        if has_sudo and is_package_installed("p7zip-full"):
            logger.info("Removing old p7zip-full package...")
            run_command("sudo apt remove -y p7zip-full")

        # Now check if the new 7zip needs to be installed or updated
        if not check_7zip_version():
            logger.info("Installing/updating 7-Zip to version with 7zz command...")

            # Check if apt package 7zip is available (only if we have sudo)
            apt_install_successful = False
            if has_sudo:
                run_command("sudo apt update")
                result = subprocess.run(['apt-cache', 'show', '7zip'],
                                      capture_output=True, text=True)

                if result.returncode == 0 and '7zip' in result.stdout:
                    # Try to install via apt first (Ubuntu 24.04+)
                    logger.info("Installing 7zip package from repository...")
                    run_command("sudo apt install -y 7zip")

                    # Verify installation - check if 7zz command is now available
                    if check_7zip_version():
                        logger.info("7-Zip installation/update completed successfully via apt")

                        # Show installed version
                        try:
                            result = subprocess.run(['7zz', '--help'], capture_output=True, text=True)
                            version_line = _extract_7zip_version_line(result.stdout)
                            logger.info(f"Installed: {version_line}")
                        except:
                            pass
                        return
                    else:
                        # Debian/Ubuntu apt package doesn't provide 7zz, continue to manual install
                        logger.warning("Repository 7zip package does not provide 7zz command, falling back to official source...")
                        apt_install_successful = False

                        # Remove the repository package to avoid conflicts
                        if is_package_installed("7zip"):
                            logger.info("Removing repository 7zip package to install official version...")
                            run_command("sudo apt remove -y 7zip")

            # Install from official 7-Zip source (works without sudo for user installation)
            if not has_sudo:
                logger.info("No sudo privileges, installing 7-Zip to ~/.local/bin...")
            elif not apt_install_successful:
                logger.info("Installing 7-Zip from official source to get 7zz command...")
            else:
                logger.info("7zip package not available in repository, installing from official source...")

            # Resolve the download URL dynamically from the official ip7z/7zip
            # GitHub mirror. Exact suffix matching avoids confusing linux-x64 with
            # linux-x86 and linux-arm64 with linux-arm.
            arch = platform.machine()
            arch_suffix = {
                "x86_64": "-linux-x64.tar.xz",
                "aarch64": "-linux-arm64.tar.xz",
            }.get(arch)
            if not arch_suffix:
                raise RuntimeError(f"Unsupported architecture for 7-Zip: {arch}")

            download_url = None
            filename = None
            version, assets = get_latest_7zip_version()
            if assets:
                for asset in assets:
                    if asset.get("name", "").endswith(arch_suffix):
                        download_url = asset["browser_download_url"]
                        filename = asset["name"]
                        break

            # Fallback: construct a permanent GitHub asset URL from the pinned
            # version when the API is unreachable or no matching asset was found.
            if not download_url:
                ver = version or FALLBACK_7ZIP_VERSION
                filename = f"7z{ver.replace('.', '')}{arch_suffix}"
                download_url = f"https://github.com/ip7z/7zip/releases/download/{ver}/{filename}"
                logger.warning(f"Using fallback 7-Zip download URL: {download_url}")

            # Download and install - save original working directory
            original_cwd = os.getcwd()
            install_path = '/usr/local/bin/7zz' if has_sudo else os.path.expanduser('~/.local/bin/7zz')

            with tempfile.TemporaryDirectory() as temp_dir:
                os.chdir(temp_dir)

                logger.info(f"Downloading 7-Zip from {download_url}...")
                response = requests.get(download_url, stream=True)
                response.raise_for_status()

                with open(filename, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

                # Extract the archive
                logger.info("Extracting 7-Zip archive...")
                run_command(f"tar xJf {filename}")

                # Verify extraction produced 7zz
                if not os.path.isfile('7zz'):
                    raise RuntimeError("7zz binary not found after extraction")

                # Install based on privileges
                if has_sudo:
                    # Install to /usr/local/bin (system-wide)
                    logger.info("Installing 7zz to /usr/local/bin...")
                    run_command("sudo install -Dm 755 7zz -t /usr/local/bin")

                    # Create symlink for 7z if it doesn't exist
                    try:
                        run_command("sudo ln -sf /usr/local/bin/7zz /usr/local/bin/7z")
                    except:
                        pass
                else:
                    # Install to ~/.local/bin (user-specific)
                    local_bin = os.path.expanduser("~/.local/bin")
                    ensure_directory_exists(local_bin)
                    logger.info(f"Installing 7zz to {local_bin}...")
                    run_command(f"install -Dm 755 7zz -t {local_bin}")

                    # Create symlink for 7z
                    try:
                        run_command(f"ln -sf {local_bin}/7zz {local_bin}/7z")
                    except:
                        pass


            # Restore original working directory
            try:
                os.chdir(original_cwd)
            except:
                os.chdir(os.path.expanduser("~"))

            # Verify installation - check the installed binary directly
            if not os.path.isfile(install_path) or not os.access(install_path, os.X_OK):
                raise RuntimeError(f"7zz not found at {install_path} after installation")

            # Run version check
            if not check_7zip_version():
                raise RuntimeError("7-Zip version check failed after installation")

            logger.info("7-Zip installation/update completed successfully")

            # Show installed version using absolute path
            try:
                result = subprocess.run([install_path, '--help'], capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    version_line = _extract_7zip_version_line(result.stdout)
                    logger.info(f"Installed: {version_line}")
            except:
                pass

    except Exception as e:
        logger.error(f"Error installing/updating 7-Zip: {str(e)}")
        raise

def remove_oxker() -> None:
    """Remove oxker if installed (replaced by ctop)."""
    local_bin = os.path.expanduser("~/.local/bin")
    oxker_path = os.path.join(local_bin, "oxker")

    # Remove from ~/.local/bin
    if os.path.exists(oxker_path):
        os.remove(oxker_path)
        logger.info(f"Removed legacy oxker from {oxker_path}")

    # Warn if oxker is still found elsewhere in PATH
    try:
        result = subprocess.run(['which', 'oxker'], capture_output=True, text=True)
        if result.returncode == 0:
            found_path = result.stdout.strip()
            logger.warning(f"oxker still found at {found_path} — please remove manually")
    except Exception:
        pass


def check_ctop_installed() -> bool:
    """Check if ctop is installed.

    Returns:
        bool: True if ctop is installed, False otherwise
    """
    # First check if it exists in ~/.local/bin
    try:
        local_bin = os.path.expanduser("~/.local/bin")
        ctop_path = os.path.join(local_bin, "ctop")
        if os.path.exists(ctop_path) and os.access(ctop_path, os.X_OK):
            return True
    except Exception as e:
        logger.debug(f"Error checking ctop in local bin: {e}")

    # Then check if it's in the PATH
    try:
        result = subprocess.run(['which', 'ctop'], capture_output=True, text=True)
        if result.returncode == 0:
            return True
    except Exception as e:
        logger.debug(f"Error checking ctop in PATH: {e}")

    return False

def get_ctop_version() -> Optional[str]:
    """Get installed ctop version.

    Returns:
        Optional[str]: Version string if installed, None otherwise
    """
    try:
        # First try with full path
        local_bin = os.path.expanduser("~/.local/bin")
        ctop_path = os.path.join(local_bin, "ctop")

        if os.path.exists(ctop_path):
            try:
                # ctop -v → "ctop version 0.8.0, build abc123 go1.23"
                result = subprocess.run([ctop_path, '-v'],
                                     capture_output=True, text=True)
                if result.returncode == 0:
                    return result.stdout.strip().split()[2].rstrip(',')
            except Exception as e:
                logger.debug(f"Error running ctop with full path: {e}")

        # Then try regular PATH
        try:
            result = subprocess.run(['ctop', '-v'],
                                 capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip().split()[2].rstrip(',')
        except FileNotFoundError:
            # Not found in PATH, which is expected if not installed
            pass
        except Exception as e:
            logger.debug(f"Error running ctop from PATH: {e}")

        # If we got here, ctop is not installed or not working
        return None
    except Exception as e:
        logger.debug(f"Error in get_ctop_version: {e}")
        return None

@lru_cache(maxsize=128)
def get_latest_ctop_version() -> Optional[str]:
    """Get the latest version of ctop from GitHub releases with caching.

    Returns:
        Optional[str]: Latest version string if available, None otherwise
    """
    cache_key = "ctop_latest"
    try:
        response = requests.get("https://api.github.com/repos/eqms/ctop/releases/latest", timeout=15)
        if response.status_code == 200:
            data = response.json()
            version = data["tag_name"].lstrip('v')
            logger.info(f"Found latest ctop version: {version}")

            # Cache the result (fallback for future runs when GitHub is down)
            cache_version_info(cache_key, {"version": version})
            return version
        logger.error(f"Failed to get latest ctop version. Status code: {response.status_code}")
    except Exception as e:
        logger.error(f"Error fetching latest ctop version: {str(e)}")

    # Fallback: cached value (even stale) so a GitHub outage never blocks the run
    cached_data = get_cached_version(cache_key, allow_stale=True)
    if cached_data:
        logger.warning(f"GitHub not reachable - using cached ctop version {cached_data.get('version')}")
        return cached_data.get("version")
    return None

def install_or_update_ctop() -> None:
    """Install or update ctop (eqms/ctop) to the latest version."""
    try:
        import shutil

        # Remove legacy oxker first
        remove_oxker()

        # Save current working directory
        original_dir = os.getcwd()

        # Check current version if installed
        installed = check_ctop_installed()
        current_version = get_ctop_version() if installed else None

        if installed:
            logger.info(f"Current ctop version: {current_version}")
        else:
            logger.info("ctop is not installed")

        # Get latest version from GitHub
        latest_version = get_latest_ctop_version()
        if not latest_version:
            logger.error("Could not determine latest ctop version")
            return

        # Check if update is needed
        if installed and current_version == latest_version:
            logger.info(f"ctop is already at the latest version ({latest_version})")
            return

        # Install or update
        logger.info(f"{'Updating' if installed else 'Installing'} ctop to version {latest_version}...")

        # Determine OS and architecture
        os_name = platform.system().lower()  # linux or darwin
        if os_name not in ("linux", "darwin"):
            logger.error(f"Unsupported OS for ctop: {os_name}")
            return

        arch = platform.machine()
        if arch in ("x86_64", "amd64"):
            arch_name = "amd64"
        elif arch in ("aarch64", "arm64"):
            arch_name = "arm64"
        else:
            logger.error(f"Unsupported architecture for ctop: {arch}")
            return

        # Create temporary directory for download
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                # Direct binary download (no tar.gz extraction needed)
                binary_name = f"ctop-{latest_version}-{os_name}-{arch_name}"
                download_url = f"https://github.com/eqms/ctop/releases/download/v{latest_version}/{binary_name}"

                logger.info(f"Downloading ctop from {download_url}")
                response = requests.get(download_url, stream=True)
                response.raise_for_status()

                temp_binary = os.path.join(temp_dir, "ctop")
                with open(temp_binary, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

                # Install to ~/.local/bin (using shutil.copy2 for macOS compatibility)
                local_bin = os.path.expanduser("~/.local/bin")
                ensure_directory_exists(local_bin)

                dest_path = os.path.join(local_bin, "ctop")
                shutil.copy2(temp_binary, dest_path)
                os.chmod(dest_path, 0o755)

                # Try to set PATH for current process
                if local_bin not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = f"{local_bin}:{os.environ.get('PATH', '')}"
                    logger.info(f"Added {local_bin} to PATH for current process")

                # Verify installation using full path
                ctop_path = os.path.join(local_bin, "ctop")
                if os.path.exists(ctop_path):
                    try:
                        result = subprocess.run([ctop_path, '-v'],
                                            capture_output=True, text=True)
                        if result.returncode == 0:
                            new_version = result.stdout.strip().split()[2].rstrip(',')
                            logger.info(f"ctop {new_version} has been successfully installed to {ctop_path}")
                            return
                    except Exception as e:
                        logger.error(f"Error running {ctop_path}: {str(e)}")

                logger.error(f"Failed to verify ctop installation at {ctop_path}")
                raise RuntimeError(f"Failed to verify ctop installation at {ctop_path}")

            finally:
                # Always try to return to original directory
                try:
                    os.chdir(original_dir)
                except FileNotFoundError:
                    os.chdir(os.path.expanduser("~"))

    except Exception as e:
        logger.error(f"Error installing/updating ctop: {str(e)}")
        # Make sure we're in a valid directory before raising
        try:
            os.getcwd()
        except FileNotFoundError:
            os.chdir(os.path.expanduser("~"))
        raise

def check_mcedit_installed() -> bool:
    """Check if mcedit (Midnight Commander editor) is installed.

    Returns:
        bool: True if mcedit is installed, False otherwise
    """
    try:
        result = subprocess.run(['which', 'mcedit'], capture_output=True, text=True)
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Error checking mcedit installation: {e}")
        return False

def get_mcedit_version() -> Optional[str]:
    """Get installed mcedit/mc version.

    Returns:
        Optional[str]: Version string if installed, None otherwise
    """
    try:
        result = subprocess.run(['mcedit', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            # The output might be like: "GNU Midnight Commander X.Y.Z"
            version_line = result.stdout.strip()
            match = re.search(r'(\d+\.\d+\.\d+)', version_line)
            if match:
                return match.group(1)
    except Exception as e:
        logger.error(f"Error getting mcedit version: {e}")
    return None

def is_mcedit_update_available() -> Tuple[bool, Optional[str], Optional[str]]:
    """Check if an update for mc/mcedit is available.

    Returns:
        Tuple[bool, Optional[str], Optional[str]]: (update_available, current_version, available_version)
    """
    try:
        # Get current installed version
        current_version = get_mcedit_version()
        if not current_version:
            return (True, None, None)  # Not installed, so "update" needed (install)

        # Check available version via apt-cache policy
        result = subprocess.run(
            ['apt-cache', 'policy', 'mc'],
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode == 0:
            # Parse output to find installed and candidate versions
            installed_line = None
            candidate_line = None

            for line in result.stdout.split('\n'):
                line = line.strip()
                if line.startswith('Installed:'):
                    installed_line = line.split(':', 1)[1].strip()
                elif line.startswith('Candidate:'):
                    candidate_line = line.split(':', 1)[1].strip()

            # Compare versions
            if candidate_line and installed_line:
                # If candidate is different from installed, update is available
                if candidate_line != installed_line and candidate_line != '(none)':
                    return (True, installed_line, candidate_line)

        return (False, current_version, current_version)

    except Exception as e:
        logger.debug(f"Error checking mcedit update availability: {e}")
        return (False, None, None)

def install_or_update_mcedit() -> None:
    """Install or update mcedit (Midnight Commander) using package manager."""
    try:
        # Check if installed
        installed = check_mcedit_installed()

        # Install if not present
        if not installed:
            logger.info("Installing mc (Midnight Commander with mcedit)...")
            run_command("sudo apt update")
            run_command("sudo apt install -y mc")

            # Verify installation
            new_version = get_mcedit_version()
            if new_version:
                logger.info(f"mcedit {new_version} has been successfully installed")
            else:
                raise RuntimeError("Failed to verify mcedit installation")
            return

        # Check if update is available (silent check)
        update_available, current_version, available_version = is_mcedit_update_available()

        if update_available and available_version:
            logger.info(f"mc/mcedit update available: {current_version} → {available_version}")
            logger.info("Updating mc (Midnight Commander with mcedit)...")
            run_command("sudo apt update")
            run_command("sudo apt install --only-upgrade -y mc")

            # Verify update
            new_version = get_mcedit_version()
            if new_version != current_version:
                logger.info(f"mcedit updated from {current_version} to {new_version}")
            else:
                logger.info(f"mcedit update completed")
        else:
            # Already up to date - no message needed
            logger.debug(f"mcedit is up to date ({current_version})")

    except Exception as e:
        logger.error(f"Error installing/updating mcedit: {str(e)}")
        raise

def is_dns_already_optimized() -> bool:
    """Check if DNS has already been optimized by getScripts.py

    Also validates actual DNS state: even if a marker exists, DNS is NOT
    considered optimized if resolv.conf has >3 nameservers (MAXNS violation).

    Returns:
        bool: True if DNS appears to be already optimized
    """
    try:
        marker_found = False

        # Check if resolvconf head file exists with our marker
        head_file = "/etc/resolvconf/resolv.conf.d/head"
        if os.path.exists(head_file):
            with open(head_file, "r") as f:
                content = f.read()
                if "managed by getScripts.py" in content:
                    marker_found = True

        # Check if systemd-resolved config exists with our marker
        if not marker_found:
            resolved_config = "/etc/systemd/resolved.conf.d/dns-optimization.conf"
            if os.path.exists(resolved_config):
                marker_found = True

        # Check if direct resolv.conf has our marker
        if not marker_found:
            if os.path.exists("/etc/resolv.conf"):
                with open("/etc/resolv.conf", "r") as f:
                    content = f.read()
                    if "managed by getScripts.py" in content:
                        marker_found = True

        if marker_found:
            # Validate actual DNS state: MAXNS compliance (max 3 nameservers)
            try:
                if os.path.exists("/etc/resolv.conf"):
                    with open("/etc/resolv.conf", "r") as f:
                        ns_count = sum(1 for line in f if line.strip().startswith('nameserver'))
                    if ns_count > 3:
                        logger.debug(f"DNS marker exists but {ns_count} nameservers found (max 3), re-optimization needed")
                        return False
            except Exception:
                pass
            return True

        return False
    except Exception:
        return False

def is_dns_optimization_declined() -> bool:
    """Check if DNS optimization was previously declined by the user.

    Returns:
        bool: True if optimization was declined
    """
    ensure_cache_dir()
    decline_marker = os.path.join(CACHE_DIR, "dns-optimization-declined")
    return os.path.exists(decline_marker)

def mark_dns_optimization_declined() -> None:
    """Mark DNS optimization as declined by the user."""
    ensure_cache_dir()
    decline_marker = os.path.join(CACHE_DIR, "dns-optimization-declined")
    try:
        with open(decline_marker, "w") as f:
            f.write(f"DNS optimization declined on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("To reset this decision, delete this file or run: ./getScripts.py --dns-check\n")
        logger.debug(f"Created DNS optimization decline marker: {decline_marker}")
    except Exception as e:
        logger.error(f"Could not create DNS decline marker: {e}")

def clear_dns_optimization_declined() -> None:
    """Clear the DNS optimization declined marker (when explicitly requested)."""
    ensure_cache_dir()
    decline_marker = os.path.join(CACHE_DIR, "dns-optimization-declined")
    try:
        if os.path.exists(decline_marker):
            os.remove(decline_marker)
            logger.debug("Cleared DNS optimization decline marker")
    except Exception as e:
        logger.error(f"Could not remove DNS decline marker: {e}")

def is_hetzner_server() -> bool:
    """Check if the server is running on Hetzner infrastructure.

    Detection methods:
    1. Hostname patterns (hetzner, your-server, static.hetzner)
    2. Legacy Hetzner DNS in resolv.conf (213.133.x)
    3. Known Hetzner IP ranges

    Returns:
        bool: True if on Hetzner infrastructure
    """
    # Check via hostname patterns
    try:
        hostname = socket.gethostname()
        if any(pattern in hostname.lower() for pattern in ['hetzner', 'your-server', 'static.hetzner']):
            logger.info("🏢 Detected Hetzner server via hostname")
            return True
    except Exception:
        pass

    # Check via /etc/resolv.conf for Hetzner DNS (legacy AND current)
    try:
        if os.path.exists("/etc/resolv.conf"):
            with open("/etc/resolv.conf", "r") as f:
                content = f.read()
            hetzner_dns_patterns = [
                '213.133.100', '213.133.98', '213.133.99',  # legacy Hetzner DNS
                '185.12.64.',                                 # current Hetzner DNS IPv4
                '2a01:4ff:ff00::add:',                       # current Hetzner DNS IPv6
            ]
            if any(pattern in content for pattern in hetzner_dns_patterns):
                logger.info("🏢 Detected Hetzner server via DNS configuration")
                return True
    except Exception:
        pass

    # Check via network configuration for known Hetzner IP ranges
    try:
        result = subprocess.run(['ip', 'addr'], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            hetzner_patterns = ['159.69.', '116.203.', '135.181.', '65.108.', '5.75.']
            for pattern in hetzner_patterns:
                if pattern in result.stdout:
                    logger.info(f"🏢 Detected Hetzner server via IP range {pattern}*")
                    return True
    except Exception:
        pass

    return False


def check_dns_configuration() -> Dict[str, Any]:
    """Check the current DNS configuration on the system.

    Returns:
        Dict[str, Any]: DNS configuration information
    """
    dns_info = {
        "resolv_conf": [],
        "systemd_resolved": False,
        "systemd_resolved_status": None,
        "resolvconf": False,
        "networkmanager": False,
        "dns_performance": {}
    }
    
    try:
        # Check /etc/resolv.conf
        if os.path.exists("/etc/resolv.conf"):
            with open("/etc/resolv.conf", "r") as f:
                content = f.read()
                # Extract nameservers
                for line in content.split('\n'):
                    if line.strip().startswith('nameserver'):
                        nameserver = line.split()[1] if len(line.split()) > 1 else None
                        if nameserver:
                            dns_info["resolv_conf"].append(nameserver)
        
        # Check if systemd-resolved is active
        try:
            result = subprocess.run(["systemctl", "is-active", "systemd-resolved"], 
                                  capture_output=True, text=True)
            dns_info["systemd_resolved"] = result.returncode == 0
            if dns_info["systemd_resolved"]:
                # Get systemd-resolved status
                status_result = subprocess.run(["resolvectl", "status"], 
                                             capture_output=True, text=True)
                if status_result.returncode == 0:
                    dns_info["systemd_resolved_status"] = status_result.stdout
        except Exception:
            pass
        
        # Check if resolvconf is managing DNS
        if os.path.islink("/etc/resolv.conf"):
            link_target = os.readlink("/etc/resolv.conf")
            if "resolvconf" in link_target:
                dns_info["resolvconf"] = True
        
        # Check if NetworkManager is active
        try:
            result = subprocess.run(["systemctl", "is-active", "NetworkManager"], 
                                  capture_output=True, text=True)
            dns_info["networkmanager"] = result.returncode == 0
        except Exception:
            pass
            
        # Test DNS performance
        test_domains = ["google.com", "cloudflare.com", "github.com"]
        test_dns_servers = {
            "current": dns_info["resolv_conf"][0] if dns_info["resolv_conf"] else None,
            "cloudflare": "1.1.1.1",
            "google": "8.8.8.8",
            "quad9": "9.9.9.9"
        }
        
        for server_name, server_ip in test_dns_servers.items():
            if server_ip:
                total_time = 0
                successful_queries = 0
                
                for domain in test_domains:
                    try:
                        start_time = time.time()
                        result = subprocess.run(
                            ["dig", f"@{server_ip}", domain, "+short", "+stats"],
                            capture_output=True, text=True, timeout=5
                        )
                        end_time = time.time()
                        
                        if result.returncode == 0:
                            query_time = (end_time - start_time) * 1000  # Convert to ms
                            total_time += query_time
                            successful_queries += 1
                    except Exception:
                        pass
                
                if successful_queries > 0:
                    avg_time = total_time / successful_queries
                    dns_info["dns_performance"][server_name] = {
                        "server": server_ip,
                        "avg_query_time_ms": round(avg_time, 2),
                        "successful_queries": successful_queries
                    }
        
    except Exception as e:
        logger.error(f"Error checking DNS configuration: {e}")
    
    return dns_info

def optimize_dns_configuration(explicit_request: bool = False) -> bool:
    """Optimize DNS configuration based on detected setup.

    Detects Hetzner infrastructure and prioritizes Hetzner DNS (185.12.64.2)
    for lowest latency on Hetzner servers. Enforces Linux 3-nameserver limit.

    Args:
        explicit_request: True if called with --dns-check flag (always ask user)

    Returns:
        bool: True if optimization was applied, False otherwise
    """
    logger.info("\n" + "="*60)
    logger.info("DNS Configuration Check and Optimization")
    logger.info("="*60)

    # If explicitly requested via --dns-check, clear any previous decline marker
    if explicit_request:
        clear_dns_optimization_declined()

    # Check if optimization was previously declined (unless explicitly requested)
    if not explicit_request and is_dns_optimization_declined():
        logger.info("\n✅ DNS optimization was previously declined")
        logger.info("To reconsider, run: ./getScripts.py --dns-check")
        return False

    # Get current DNS configuration
    dns_info = check_dns_configuration()

    # Detect Hetzner infrastructure and select recommended DNS servers
    on_hetzner = is_hetzner_server()
    if on_hetzner:
        recommended_dns = ["185.12.64.2", "1.1.1.1", "9.9.9.9"]
        logger.info("🏢 Hetzner server detected — using Hetzner DNS as primary (lowest latency)")
    else:
        recommended_dns = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]

    # Display current configuration
    logger.info("\nCurrent DNS Configuration:")
    logger.info(f"- Nameservers: {', '.join(dns_info['resolv_conf']) if dns_info['resolv_conf'] else 'None'}")
    logger.info(f"- systemd-resolved: {'Active' if dns_info['systemd_resolved'] else 'Inactive'}")
    logger.info(f"- resolvconf: {'Active' if dns_info['resolvconf'] else 'Inactive'}")
    logger.info(f"- NetworkManager: {'Active' if dns_info['networkmanager'] else 'Inactive'}")

    # Display DNS performance results
    if dns_info["dns_performance"]:
        logger.info("\nDNS Performance Test Results:")
        for server_name, perf_data in dns_info["dns_performance"].items():
            logger.info(f"- {server_name} ({perf_data['server']}): "
                       f"{perf_data['avg_query_time_ms']}ms avg query time")

    # Check if optimization is needed
    needs_optimization = False

    hetzner_dns = ["185.12.64.1", "185.12.64.2", "2a01:4ff:ff00::add:1", "2a01:4ff:ff00::add:2"]
    current_dns = dns_info['resolv_conf']
    primary_dns = current_dns[0] if current_dns else None

    # Check if DNS was already optimized by our script
    already_optimized = is_dns_already_optimized()

    # Check Linux 3-nameserver limit (MAXNS)
    if len(current_dns) > 3:
        logger.warning(f"\n⚠️  {len(current_dns)} nameservers configured, but Linux uses max 3 (MAXNS limit)")
        needs_optimization = True

    # Hetzner-aware DNS evaluation (only if no optimization needed yet from MAXNS check)
    if not needs_optimization:
        if on_hetzner:
            # On Hetzner: Hetzner DNS as primary is OPTIMAL
            if primary_dns in hetzner_dns and already_optimized:
                logger.info(f"\n✅ DNS is already optimized with Hetzner DNS ({primary_dns}) as primary")
            elif primary_dns in hetzner_dns and not already_optimized:
                logger.info(f"\n✅ Hetzner DNS ({primary_dns}) is already primary (good for Hetzner servers)")
                # Check if secondary/tertiary are public DNS for redundancy
                public_dns_present = any(dns in ["1.1.1.1", "8.8.8.8", "9.9.9.9"] for dns in current_dns[1:3])
                if not public_dns_present:
                    logger.info("ℹ️  Consider adding public DNS (Cloudflare/Quad9) as fallback for redundancy")
                    needs_optimization = True
            elif primary_dns in recommended_dns and already_optimized:
                logger.info(f"\n✅ DNS is already optimized with {primary_dns} as primary")
            elif primary_dns in ["1.1.1.1", "8.8.8.8", "9.9.9.9"]:
                # Public DNS is primary on Hetzner — recommend Hetzner as primary for better latency
                logger.info(f"\nℹ️  Public DNS ({primary_dns}) is primary, but Hetzner DNS would be faster")
                logger.info("   Hetzner DNS (185.12.64.2) has lowest latency on Hetzner infrastructure")
                needs_optimization = True
            else:
                logger.warning("\n⚠️  Non-optimal DNS configuration detected on Hetzner server")
                needs_optimization = True
        else:
            # Not on Hetzner: Hetzner DNS is a problem (e.g. DigitalOcean)
            if primary_dns in recommended_dns and already_optimized:
                logger.info(f"\n✅ DNS is already optimized with {primary_dns} as primary DNS server")
            elif primary_dns in recommended_dns and not already_optimized:
                logger.info(f"\n✅ DNS appears to be manually optimized with {primary_dns} as primary DNS server")
                if any(dns in hetzner_dns for dns in current_dns[:2]):
                    logger.warning("\n⚠️  Detected Hetzner DNS servers in primary/secondary positions")
                    needs_optimization = True
            else:
                if any(dns in hetzner_dns for dns in current_dns):
                    logger.warning("\n⚠️  Detected Hetzner DNS servers which may cause issues with some providers")
                    needs_optimization = True
    else:
        # needs_optimization already True (e.g. MAXNS violation)
        # Provide additional context but skip "already optimized" messages
        if on_hetzner and primary_dns not in ["185.12.64.2"]:
            logger.info("ℹ️  Hetzner DNS (185.12.64.2) would provide lowest latency as primary")

    # Check if current DNS is slow
    if dns_info["dns_performance"]:
        current_perf = dns_info["dns_performance"].get("current", {})
        if current_perf and current_perf.get("avg_query_time_ms", 0) > 50:
            logger.warning(f"\n⚠️  Current DNS response time ({current_perf['avg_query_time_ms']}ms) is slow")
            needs_optimization = True

    # Check if Docker DNS (127.0.0.11) is being used
    if "127.0.0.11" in current_dns:
        logger.info("\n📦 Detected Docker container environment (DNS: 127.0.0.11)")
        logger.info("For Docker containers, DNS should be configured in docker-compose.yml or docker run command")

    if not needs_optimization and "127.0.0.11" not in current_dns:
        logger.info("\n✅ DNS configuration appears to be optimal")
        return False

    # Build DNS description strings for display
    dns_descriptions = {
        "185.12.64.2": "Hetzner (local network, lowest latency)",
        "1.1.1.1": "Cloudflare",
        "8.8.8.8": "Google",
        "9.9.9.9": "Quad9",
    }
    dns_labels = ["Primary", "Secondary", "Tertiary"]

    # Ask user if they want to optimize
    logger.info("\n" + "-"*60)
    logger.info("DNS Optimization Recommended")
    logger.info("-"*60)
    logger.info("\nRecommended DNS servers for better performance:")
    for i, dns in enumerate(recommended_dns[:3]):
        desc = dns_descriptions.get(dns, dns)
        logger.info(f"- {dns_labels[i]}: {dns} ({desc})")

    # Build FallbackDNS based on context
    fallback_dns = "8.8.4.4 1.0.0.1"

    # Build dynamic DNS strings for shell commands
    dns_list = ' '.join(recommended_dns[:3])
    dns_nameservers = '\n'.join([f"nameserver {dns}" for dns in recommended_dns[:3]])

    # Different optimization based on DNS management system
    if dns_info["systemd_resolved"]:
        logger.info("\nOptimization method: systemd-resolved configuration")
        optimization_commands = [
            "sudo mkdir -p /etc/systemd/resolved.conf.d",
            f'''sudo tee /etc/systemd/resolved.conf.d/dns-optimization.conf > /dev/null << EOF
[Resolve]
DNS={dns_list}
FallbackDNS={fallback_dns}
DNSOverTLS=opportunistic
DNSSEC=allow-downgrade
Cache=yes
CacheFromLocalhost=yes
EOF''',
            "sudo systemctl restart systemd-resolved"
        ]
    elif dns_info["resolvconf"]:
        logger.info("\nOptimization method: resolvconf configuration")
        optimization_commands = [
            f'''sudo tee /etc/resolvconf/resolv.conf.d/head > /dev/null << EOF
# Optimized DNS servers - managed by getScripts.py
{dns_nameservers}
EOF''',
            "sudo resolvconf -u"
        ]
    else:
        logger.info("\nOptimization method: direct resolv.conf modification")
        logger.info("\nNote: /etc/resolv.conf will be made immutable to prevent automatic changes")
        logger.info("To manually edit later, first run: sudo chattr -i /etc/resolv.conf")
        optimization_commands = [
            # Backup existing resolv.conf
            "sudo cp /etc/resolv.conf /etc/resolv.conf.backup.$(date +%Y%m%d_%H%M%S)",
            # Remove immutable attribute if present
            "sudo chattr -i /etc/resolv.conf 2>/dev/null || true",
            # Check if resolv.conf is a symlink and remove it
            "sudo test -L /etc/resolv.conf && sudo rm /etc/resolv.conf || true",
            # Create new resolv.conf with optimized DNS (max 3 nameservers)
            f'''sudo tee /etc/resolv.conf > /dev/null << EOF
# Optimized DNS configuration - managed by getScripts.py
# Date: $(date +%Y-%m-%d)
# To modify this file, first run: sudo chattr -i /etc/resolv.conf
{dns_nameservers}
options timeout:2 attempts:3 rotate
EOF''',
            # Make the file immutable to prevent automatic changes
            "sudo chattr +i /etc/resolv.conf"
        ]

    # Docker-specific instructions
    if "127.0.0.11" in current_dns:
        docker_dns_flags = ' '.join([f"--dns {dns}" for dns in recommended_dns[:3]])
        docker_dns_yaml = '\n'.join([f"      - {dns}" for dns in recommended_dns[:3]])
        logger.info("\n📋 For Docker containers, add this to your docker-compose.yml:")
        logger.info(f"""
services:
  your-service:
    dns:
{docker_dns_yaml}
""")
        logger.info("\n📋 Or use these flags with docker run:")
        logger.info(f"docker run {docker_dns_flags} ...")
        return False

    # Ask for confirmation
    try:
        response = input("\nDo you want to apply DNS optimization? (y/N): ").strip().lower()
        if response != 'y':
            logger.info("DNS optimization skipped")
            # Remember this decision (unless explicitly requested with --dns-check)
            if not explicit_request:
                mark_dns_optimization_declined()
                logger.info("This decision has been saved. To reconsider, run: ./getScripts.py --dns-check")
            return False
    except KeyboardInterrupt:
        logger.info("\nDNS optimization cancelled")
        # Remember this decision (unless explicitly requested with --dns-check)
        if not explicit_request:
            mark_dns_optimization_declined()
            logger.info("\nThis decision has been saved. To reconsider, run: ./getScripts.py --dns-check")
        return False

    # Apply optimization
    logger.info("\nApplying DNS optimization...")
    try:
        for cmd in optimization_commands:
            logger.info(f"Running: {cmd[:50]}...")
            run_command(cmd, shell=True, check=True)

        # Test new configuration
        logger.info("\nTesting new DNS configuration...")
        time.sleep(2)  # Wait for changes to take effect

        new_dns_info = check_dns_configuration()
        if new_dns_info["dns_performance"]:
            new_perf = new_dns_info["dns_performance"].get("current", {})
            if new_perf:
                logger.info(f"New DNS query time: {new_perf['avg_query_time_ms']}ms")

        logger.info("\n✅ DNS optimization completed successfully!")
        logger.info("Note: For containers, remember to add DNS configuration to docker-compose.yml")
        return True

    except Exception as e:
        logger.error(f"Error applying DNS optimization: {e}")
        logger.info("You can manually optimize DNS by editing the appropriate configuration files")
        return False


@lru_cache(maxsize=128)
def get_latest_pypi_version(package_name: str) -> Optional[str]:
    """Get the latest version of a package from PyPI with caching.
    
    Args:
        package_name (str): Name of the package
        
    Returns:
        Optional[str]: Latest version string if available, None otherwise
    """
    cache_key = f"pypi_{package_name}"
    try:
        url = f"https://pypi.org/pypi/{package_name}/json"
        logger.info(f"Checking latest version of {package_name} from PyPI")
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            latest_version = data["info"]["version"]
            logger.info(f"Latest {package_name} version on PyPI: {latest_version}")

            # Cache the result (fallback for future runs when PyPI is down)
            cache_version_info(cache_key, {"version": latest_version})
            return latest_version
        logger.error(f"Failed to get latest {package_name} version. Status code: {response.status_code}")
    except Exception as e:
        logger.error(f"Error fetching latest {package_name} version from PyPI: {str(e)}")

    # Fallback: cached value (even stale) so a PyPI outage never blocks the run
    cached_data = get_cached_version(cache_key, allow_stale=True)
    if cached_data:
        logger.warning(f"PyPI not reachable - using cached {package_name} version {cached_data.get('version')}")
        return cached_data.get("version")
    return None

def get_installed_uv_tool_version(package_name: str) -> Optional[str]:
    """Get the installed version of a uv tool package.

    Args:
        package_name (str): Name of the package

    Returns:
        Optional[str]: Installed version string if available, None otherwise
    """
    try:
        result = subprocess.run(['uv', 'tool', 'list'], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                # uv tool list format: "package-name v1.2.3" or "package-name 1.2.3"
                if package_name in line:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        version = parts[1]
                        if version.startswith('v'):
                            version = version[1:]
                        logger.info(f"Installed {package_name} version: {version}")
                        return version
            logger.info(f"{package_name} is not installed with uv tool")
        return None
    except Exception as e:
        logger.error(f"Error getting installed {package_name} version: {str(e)}")
        return None

def install_or_update_nginx_set_conf() -> None:
    """Install or update nginx-set-conf to the latest version using uv tool.

    Every exit path records its outcome via record_install() so the end-of-run
    summary makes failures visible — previously failures only hit the logger and
    scrolled past unnoticed, leaving the tool silently uninstalled.
    """
    package_name = "nginx-set-conf"

    # Hard guard: without uv there is nothing to install with. Make it loud.
    if not is_uv_installed():
        logger.error(
            f"Cannot install {package_name}: uv is not available. "
            f"Install uv first (see install_uv) and re-run."
        )
        record_install(package_name, "failed", "uv not available")
        return

    try:
        # Check if already installed with uv tool
        current_version = get_installed_uv_tool_version(package_name)

        # Get latest version from PyPI (best-effort — used only for the up-to-date
        # short-circuit and log messages). A failed PyPI lookup must NOT abort the
        # install when the tool isn't present yet: uv resolves the latest version
        # itself, so we still attempt the install.
        latest_version = get_latest_pypi_version(package_name)

        if not latest_version:
            if current_version:
                logger.warning(
                    f"Could not determine latest {package_name} version from PyPI; "
                    f"{package_name} is installed ({current_version}), keeping it."
                )
                record_install(package_name, "ok", f"v{current_version} (PyPI check skipped)")
                return
            logger.warning(
                f"Could not determine latest {package_name} version from PyPI; "
                f"attempting install of the latest available version anyway."
            )

        # Already up to date?
        if current_version and latest_version and current_version == latest_version:
            logger.info(f"{package_name} is already at the latest version ({latest_version})")
            record_install(package_name, "ok", f"v{current_version}")
            return

        # Install/update with uv tool
        target = f"version {latest_version}" if latest_version else "latest version"
        if current_version:
            logger.info(f"Upgrading {package_name} from {current_version} to {target}")
        else:
            logger.info(f"Installing {package_name} {target}")

        result = run_command(f"uv tool install {package_name}", capture_output=True)

        # If installation fails, retry once with --force.
        if result.returncode != 0:
            logger.warning(
                f"uv tool install {package_name} failed (rc={result.returncode}); "
                f"retrying with --force"
            )
            result = run_command(f"uv tool install --force {package_name}", capture_output=True)

        # Verify installation
        new_version = get_installed_uv_tool_version(package_name)
        if new_version:
            status = "updated" if current_version else "installed"
            logger.info(f"Successfully {status} {package_name} version {new_version}")
            record_install(package_name, status, f"v{new_version}")
        else:
            logger.error(
                f"Failed to install/verify {package_name} "
                f"(rc={getattr(result, 'returncode', 'n/a')}). "
                f"Check that uv's tool bin dir is on PATH."
            )
            record_install(package_name, "failed", "install/verify failed")
    except Exception as e:
        logger.error(f"Error installing/updating {package_name}: {str(e)}")
        record_install(package_name, "failed", str(e))

def check_versions_parallel(packages: List[Tuple[str, str]]) -> Dict[str, Dict[str, Any]]:
    """Check package versions in parallel.
    
    Args:
        packages: List of (package_name, package_type) tuples
        
    Returns:
        Dict[str, Dict[str, Any]]: Version information for each package
    """
    results = {}
    
    def check_version(package_name: str, package_type: str) -> Tuple[str, Dict[str, Any]]:
        """Check version for a single package."""
        try:
            if package_type == "pypi":
                latest = get_latest_pypi_version(package_name)
                current = get_pip_package_version(package_name)
                return package_name, {"type": "pypi", "current": current, "latest": latest}
            elif package_type == "system":
                current = get_system_package_version(package_name)
                return package_name, {"type": "system", "current": current}
            elif package_type == "uv_tool":
                current = get_installed_uv_tool_version(package_name)
                latest = get_latest_pypi_version(package_name)
                return package_name, {"type": "uv_tool", "current": current, "latest": latest}
        except Exception as e:
            logger.error(f"Error checking version for {package_name}: {e}")
            return package_name, {"type": package_type, "error": str(e)}
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(check_version, name, ptype) for name, ptype in packages]
        for future in as_completed(futures):
            name, info = future.result()
            results[name] = info
    
    return results

def setup_environment() -> Tuple[str, str]:
    """Setup initial environment and return home and local bin paths."""
    print_header()

    # Check if running on Debian/Ubuntu
    if not is_debian_or_ubuntu():
        logger.error("This script is only supported on Debian and Ubuntu systems")
        sys.exit(1)

    # Check for sudo privileges
    if not is_root_or_has_sudo():
        logger.warning("⚠️  This script requires sudo privileges for system package installation.")
        logger.warning("⚠️  Some features (system packages, 7-Zip, bat, zstd) will be skipped.")
        logger.warning("⚠️  User-level installations (uv tools, pip packages) will still work.")
        logger.warning("")
        try:
            response = input("Do you want to continue without sudo? (y/N): ").strip().lower()
            if response != 'y':
                logger.info("Exiting. Please run with sudo or configure passwordless sudo.")
                sys.exit(0)
        except KeyboardInterrupt:
            logger.info("\nExiting.")
            sys.exit(0)

    # Get appropriate home directory based on execution context
    # Priority: SUDO_USER (if running with sudo) > current user home
    if os.environ.get('SUDO_USER'):
        # Running with sudo - use the real user's home directory
        import pwd
        sudo_user = os.environ['SUDO_USER']
        try:
            _myhome = pwd.getpwnam(sudo_user).pw_dir
            logger.info(f"Running with sudo as user '{sudo_user}', using home: {_myhome}")
        except KeyError:
            # Fallback if user lookup fails
            logger.warning(f"Could not find home for SUDO_USER '{sudo_user}', using current home")
            _myhome = os.path.expanduser('~')
    else:
        # Running as root or normal user without sudo
        _myhome = os.path.expanduser('~')
        current_user = os.environ.get('USER', 'unknown')
        logger.info(f"Running as user '{current_user}', using home: {_myhome}")

    local_bin = os.path.join(_myhome, ".local", "bin")
    
    # Ensure .local/bin is in PATH
    ensure_directory_exists(local_bin)
    
    # Set timezone
    try:
        run_command("sudo timedatectl set-timezone Europe/Berlin", check=True)
    except CommandError:
        logger.warning("Failed to set timezone")
    
    return _myhome, local_bin

def update_repository(myodoo_docker: str, server_version: str) -> None:
    """Update or clone the myodoo-docker repository."""
    parent_dir = os.path.dirname(myodoo_docker)

    # Clone repository if it doesn't exist
    if not os.path.exists(myodoo_docker):
        logger.info(f"Repository directory {myodoo_docker} does not exist, cloning...")
        os.chdir(parent_dir)
        clone_url = "https://github.com/equitania/myodoo-docker.git"
        logger.info(f"Cloning {clone_url} into {myodoo_docker}")
        run_command(f"git clone -b {server_version} {clone_url}")
        logger.info("Repository cloned successfully")

        # Clean pyc files after initial clone
        os.chdir(myodoo_docker)
        run_command("find . -name '*.pyc' -type f -delete")
        return

    # Repository exists, update it
    os.chdir(myodoo_docker)

    # Check current branch and switch if needed
    current_branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
    if current_branch != server_version:
        logger.info(f"Switching to branch {server_version}")
        run_command(f"git checkout {server_version}")

    # Configure git pull
    run_command("git config pull.ff only", capture_output=True)

    # Check for updates
    before_pull = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    run_command("git pull", capture_output=True)
    after_pull = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()

    if before_pull != after_pull:
        logger.info("Repository updated, new changes downloaded")
        run_command("git --no-pager log --oneline --no-decorate HEAD@{1}..HEAD")

    # Clean pyc files
    run_command("find . -name '*.pyc' -type f -delete")

def copy_configuration_files(_myhome: str, myodoo_docker: str) -> None:
    """Copy configuration files from repository to home directory."""

    # Copy fastfetch config
    config_directory = os.path.join(_myhome, ".config", "fastfetch")
    ensure_directory_exists(config_directory)

    source_fastfetch = os.path.join(myodoo_docker, "scripts", "fastfetch", "config.jsonc")
    target_fastfetch = os.path.join(config_directory, "config.jsonc")
    if os.path.exists(source_fastfetch):
        run_command(f"cp {source_fastfetch} {target_fastfetch}")

def copy_scripts(_myhome: str, myodoo_docker: str) -> None:
    """Copy utility scripts to home directory."""
    scripts = [
        "update_docker_odoo.py",
        "cleanup-weblogs.py",
        "container2backup.py",
        "restore-zip.sh",
        "ssl-renew.sh",
        "nginx-cert-guard.py",
        "nightly-cleanup.sh",
        "deploy-nginx-base.sh",
        "setup-maintenance-cron.sh",
        "myodoo-maintenance.cron",
        "myodoo-maintenance.logrotate",
        "getScripts.py"
    ]
    
    for script in scripts:
        source = os.path.join(myodoo_docker, 
                            "scripts" if script != "getScripts.py" else "", 
                            script)
        target = os.path.join(_myhome, script)
        if os.path.exists(source):
            run_command(f"cp {source} {target}")

def install_packages(package_info: Dict[str, Any]) -> None:
    """Install all required packages."""
    # Install required system packages for Python virtual environments
    if not is_package_installed("python3-venv"):
        logger.info("Installing python3-venv...")
        install_system_package("python3-venv")

    # 1. Ensure uv is installed and up to date
    if not is_uv_installed():
        if not install_uv():
            logger.warning("uv installation failed, skipping uv tool installations")

    # 2. Update uv to latest version
    if is_uv_installed():
        logger.info("Updating uv to latest version...")
        try:
            run_command("uv self update")
        except Exception as e:
            logger.warning(f"Failed to update uv: {e}")

        # 3. Upgrade all existing uv tools
        logger.info("Upgrading all existing uv tools...")
        try:
            run_command("uv tool upgrade --all")
        except Exception as e:
            logger.warning(f"Failed to upgrade uv tools: {e}")

    # 4. Install or update nginx-set-conf
    # Called unconditionally on purpose: the function guards on is_uv_installed()
    # itself and records a visible "failed — uv not available" entry rather than
    # being silently skipped when uv is missing.
    install_or_update_nginx_set_conf()

    # 5. Install specific versions of packages with uv tool
    if is_uv_installed():
        for package, version in package_info.get("uv_tools", {}).items():
            if package != "nginx-set-conf":
                install_specific_uv_tool_package(package, version)

    # 6. Migrate from pipx if still present (AFTER uv tools are installed)
    migrate_from_pipx()
    
    # Collect all packages for parallel version checking
    all_packages = []
    for package in package_info["pip"]:
        all_packages.append((package, "pypi"))
    
    # Check versions in parallel
    logger.info("Checking package versions...")
    version_info = check_versions_parallel(all_packages)
    
    # Upgrade pip packages based on version check
    for package in package_info["pip"]:
        info = version_info.get(package, {})
        if "error" not in info:
            upgrade_pip_package(package)
    
    # Install specific tools
    install_or_update_zstd()
    install_or_update_bat()
    install_or_update_7zip()
    
    # Install system packages
    for package in package_info["system"]:
        if "==" in package:
            name, version = package.split("==")
            if name == "zoxide":
                install_zoxide_if_needed(version)
            elif name == "fastfetch":
                install_fastfetch_if_needed()
            else:
                install_system_package(name, version)
        else:
            # Handle special packages without version
            if package == "zoxide":
                install_zoxide_if_needed()
            elif package == "fastfetch":
                install_fastfetch_if_needed()
            else:
                install_system_package(package)
    
    # Install additional tools
    install_or_update_ctop()
    install_or_update_mcedit()

def main() -> None:
    """Main function to execute the script."""
    original_dir = os.getcwd()

    try:
        # Setup environment
        _myhome, local_bin = setup_environment()

        # First, upgrade pip if needed
        upgrade_pip()

        # Note: DNS configuration is handled in first-run setup
        # For explicit DNS optimization, use: ./getScripts.py --dns-check

        global_server_version = '2026'
        myodoo_docker = os.path.join(_myhome, "myodoo-docker")

        # Update or clone repository
        try:
            update_repository(myodoo_docker, global_server_version)
        except Exception as e:
            logger.error(f"Failed to update or clone repository: {e}")
            logger.error(f"Please check network connectivity and permissions")
            sys.exit(1)

        # =====================================================================
        # FISH SHELL SETUP (New in v7.0.0)
        # =====================================================================
        logger.info("=" * 60)
        logger.info("Setting up Fish shell environment...")
        logger.info("=" * 60)

        # Install Fish shell 4.0+ from official repository
        # Returns (is_available, is_fresh_install)
        fish_installed, fish_is_fresh_install = install_fish_if_needed()

        # Install Starship prompt
        starship_installed = install_starship_if_needed()

        # Install Fisher plugin manager (if Fish is available)
        if fish_installed:
            install_fisher_if_needed()

        # Copy Fish configuration (always update to get latest changes)
        if fish_installed:
            copy_fish_configuration(_myhome, myodoo_docker)

        # Copy Starship configuration (always update to get latest changes)
        if starship_installed:
            copy_starship_configuration(_myhome, myodoo_docker)

        # Log ZSH detection (Fish is now the only supported shell)
        zsh_installed, _ = is_zsh_installed()
        if zsh_installed:
            logger.info("ZSH detected — Fish is now the primary shell, ZSH configuration skipped")

        # Copy scripts (without update_docker_myodoo.py - deprecated)
        copy_scripts(_myhome, myodoo_docker)

        # Clean up legacy files ONLY on fresh Fish installation
        # This prevents running cleanup on every script execution
        if fish_is_fresh_install:
            logger.info("Fresh Fish installation detected - cleaning up legacy files...")
            cleanup_legacy_files(_myhome, myodoo_docker)

            # Clean up misplaced log file from earlier versions
            misplaced_log = "/etc/apt/sources.list.d/getscripts.log"
            if os.path.exists(misplaced_log):
                logger.info(f"Removing misplaced log file: {misplaced_log}")
                run_command(f"rm -f {misplaced_log}")
        elif fish_installed:
            logger.info("Fish already installed - skipping legacy cleanup")
        else:
            logger.warning("Fish is not installed - skipping legacy cleanup")

        # Copy fastfetch config
        config_directory = os.path.join(_myhome, ".config", "fastfetch")
        ensure_directory_exists(config_directory)
        source_fastfetch = os.path.join(myodoo_docker, "scripts", "fastfetch", "config.jsonc")
        target_fastfetch = os.path.join(config_directory, "config.jsonc")
        if os.path.exists(source_fastfetch):
            run_command(f"cp {source_fastfetch} {target_fastfetch}")

        os.chdir(_myhome)

        # Clean up old packages
        if is_pip_package_installed("nginx-set-conf-equitania"):
            logger.info("Removing nginx-set-conf-equitania...")
            uninstall_pip_package("nginx-set-conf-equitania")

        if is_pip_package_installed("odoo-fast-report-mapper-equitania"):
            logger.info("Removing odoo-fast-report-mapper-equitania...")
            uninstall_pip_package("odoo-fast-report-mapper-equitania")

        # Read package versions from packages.txt
        package_info = read_package_versions(os.path.join(myodoo_docker, "packages.txt"))

        # Install all packages
        install_packages(package_info)

        # =====================================================================
        # SHELL SETUP COMPLETION
        # =====================================================================
        logger.info("Setting up shell environment...")
        try:
            if local_bin not in os.environ.get("PATH", ""):
                os.environ["PATH"] = f"{local_bin}:{os.environ.get('PATH', '')}"

            # zoxide is initialized per-shell via fish/conf.d/20-tools.fish on every
            # interactive start; no throwaway `fish -c` priming needed here (it would
            # persist nothing and only emit fish's cd.fish redirect warning).
        except Exception as e:
            logger.error(f"Error setting up shell environment: {e}")

        # Offer to set Fish as the default shell whenever it isn't already.
        # NOT gated on fresh-install: a prior partial run (e.g. aborted mid-setup)
        # can leave Fish installed without ever prompting, so the user would never
        # be asked again. prompt_shell_change() itself skips when Fish is already
        # the default. Require an interactive TTY so non-interactive/CI runs that
        # cannot answer input() do not break.
        if fish_installed and sys.stdin.isatty():
            prompt_shell_change(_myhome)
        elif fish_installed and not fish_is_fresh_install:
            logger.info("Fish is installed. Run this script in an interactive "
                        "terminal to set Fish as your default shell, or run: chsh -s (which fish)")

        # Return to original directory
        try:
            os.chdir(original_dir)
        except FileNotFoundError:
            os.chdir(_myhome)

        # Visible install summary (surfaces failures that only hit the logger).
        print_install_report()

        logger.info("")
        logger.info("=" * 60)
        logger.info("Script completed successfully!")
        logger.info("=" * 60)
        if fish_installed:
            logger.info("Fish shell is now configured. Start it with: fish")
            logger.info("Or log out and back in if you changed your default shell.")
        logger.info("")

    except Exception as e:
        logger.error(f"An error occurred in main: {str(e)}")
        try:
            os.getcwd()
        except FileNotFoundError:
            os.chdir(os.path.expanduser("~"))
        sys.exit(1)

# =============================================================================
# FIRST-RUN AND PROXY CONFIGURATION (New in v8.0.0)
# =============================================================================

# First-run marker file
FIRST_RUN_MARKER = os.path.expanduser("~/.getscripts_configured")
PROXY_CONFIG_FILE = os.path.expanduser("~/.getscripts_proxy")


def is_first_run() -> bool:
    """Check if this is the first run of getScripts.py on this system."""
    return not os.path.exists(FIRST_RUN_MARKER)


def mark_configured() -> None:
    """Mark the system as configured after first run."""
    try:
        with open(FIRST_RUN_MARKER, 'w') as f:
            f.write(f"Configured on {datetime.now().isoformat()}\n")
            f.write(f"Version: {SCRIPT_VERSION}\n")
        logger.info("System marked as configured")
    except Exception as e:
        logger.error(f"Failed to mark system as configured: {e}")


def reset_configuration() -> None:
    """Reset configuration marker to trigger first-run setup again."""
    if os.path.exists(FIRST_RUN_MARKER):
        try:
            os.remove(FIRST_RUN_MARKER)
            logger.info("Configuration marker removed")
        except Exception as e:
            logger.error(f"Failed to remove configuration marker: {e}")


def validate_proxy_url(url: str) -> bool:
    """Validate a proxy URL format."""
    pattern = r'^https?://[a-zA-Z0-9.-]+(?::\d+)?/?$'
    return bool(re.match(pattern, url))


def configure_proxy_settings() -> bool:
    """Interactive proxy configuration."""
    print("\n" + "=" * 60)
    print("Proxy-Konfiguration")
    print("=" * 60)

    try:
        response = input("\nVerwendet dieses Netzwerk einen Proxy? (j/N): ").strip().lower()

        if response not in ('j', 'ja', 'y', 'yes'):
            logger.info("No proxy configuration needed")
            return False

        print("\nProxy-Einstellungen:")
        http_proxy = input("HTTP Proxy (z.B. http://proxy.firma.de:8080): ").strip()

        if not http_proxy:
            logger.info("No proxy URL provided")
            return False

        if not validate_proxy_url(http_proxy):
            print(f"Ungültiges Proxy-URL-Format: {http_proxy}")
            return False

        https_proxy = input("HTTPS Proxy (Enter = wie HTTP): ").strip() or http_proxy
        no_proxy = input("Ausnahmen (kommagetrennt, z.B. localhost,127.0.0.1,.local): ").strip()

        if not no_proxy:
            no_proxy = "localhost,127.0.0.1,::1,.local"

        proxy_config = {
            'http_proxy': http_proxy,
            'https_proxy': https_proxy,
            'no_proxy': no_proxy
        }

        return apply_proxy_settings(proxy_config)

    except (EOFError, KeyboardInterrupt):
        print("\nProxy-Konfiguration abgebrochen")
        return False


def apply_proxy_settings(config: dict) -> bool:
    """Apply proxy settings to system and shells."""
    http_proxy = config.get('http_proxy', '')
    https_proxy = config.get('https_proxy', '')
    no_proxy = config.get('no_proxy', 'localhost,127.0.0.1,::1,.local')

    success = True

    # Save proxy configuration to marker file
    try:
        with open(PROXY_CONFIG_FILE, 'w') as f:
            f.write(f"# Proxy configuration - managed by getScripts.py\n")
            f.write(f"http_proxy={http_proxy}\n")
            f.write(f"https_proxy={https_proxy}\n")
            f.write(f"no_proxy={no_proxy}\n")
        logger.info("Proxy configuration saved")
    except Exception as e:
        logger.error(f"Failed to save proxy configuration: {e}")
        success = False

    # Apply to Fish shell
    fish_conf_dir = os.path.expanduser("~/.config/fish/conf.d")
    ensure_directory_exists(fish_conf_dir)

    proxy_fish = os.path.join(fish_conf_dir, "99-proxy.fish")
    fish_content = f'''# Proxy Configuration - managed by getScripts.py
# Remove or edit this file to change proxy settings

set -gx http_proxy "{http_proxy}"
set -gx https_proxy "{https_proxy}"
set -gx HTTP_PROXY "{http_proxy}"
set -gx HTTPS_PROXY "{https_proxy}"
set -gx no_proxy "{no_proxy}"
set -gx NO_PROXY "{no_proxy}"
'''

    try:
        with open(proxy_fish, 'w') as f:
            f.write(fish_content)
        logger.info("Fish proxy configuration applied")
    except Exception as e:
        logger.error(f"Failed to apply Fish proxy configuration: {e}")
        success = False

    # Apply to /etc/environment (system-wide, requires sudo)
    if is_root_or_has_sudo():
        try:
            env_file = "/etc/environment"
            current_content = ""
            if os.path.exists(env_file):
                with open(env_file, 'r') as f:
                    current_content = f.read()

            # Remove existing proxy settings
            lines = []
            for line in current_content.split('\n'):
                if not any(key in line.lower() for key in ['http_proxy', 'https_proxy', 'no_proxy']):
                    lines.append(line)

            # Add new proxy settings
            lines.append(f'http_proxy="{http_proxy}"')
            lines.append(f'https_proxy="{https_proxy}"')
            lines.append(f'HTTP_PROXY="{http_proxy}"')
            lines.append(f'HTTPS_PROXY="{https_proxy}"')
            lines.append(f'no_proxy="{no_proxy}"')
            lines.append(f'NO_PROXY="{no_proxy}"')

            new_content = '\n'.join(line for line in lines if line.strip())

            subprocess.run(["sudo", "tee", env_file], input=new_content.encode(), check=True, stdout=subprocess.DEVNULL)
            logger.info("System environment proxy configuration applied")
        except Exception as e:
            logger.warning(f"Could not apply system-wide proxy: {e}")

    return success


def get_dns_preference() -> List[str]:
    """Interactive DNS server selection with Hetzner awareness.

    Detects Hetzner infrastructure and offers Hetzner-optimized DNS as
    recommended option. Enforces Linux 3-nameserver limit (MAXNS).

    Returns:
        List[str]: Selected DNS servers, empty list if skipped,
                   or ["SKIP"] marker if user chose to skip
    """
    on_hetzner = is_hetzner_server()

    print("\n" + "=" * 60)
    print("DNS Server Konfiguration")
    print("=" * 60)

    if on_hetzner:
        print("\n🏢 Hetzner-Server erkannt!")
        print("\n1. Hetzner-optimiert (Hetzner 185.12.64.2, Cloudflare, Quad9) [empfohlen]")
        print("2. Öffentliche DNS-Server (Cloudflare, Google, Quad9)")
        print("3. Interne DNS-Server verwenden (z.B. Firmen-DNS)")
        print("4. Keine Änderung (DNS-Konfiguration beibehalten)")
        prompt = "\nAuswahl [1/2/3/4]: "
    else:
        print("\n1. Öffentliche DNS-Server optimieren (Cloudflare, Google, Quad9)")
        print("2. Interne DNS-Server verwenden (z.B. Firmen-DNS)")
        print("3. Keine Änderung (DNS-Konfiguration beibehalten)")
        prompt = "\nAuswahl [1/2/3]: "

    try:
        choice = input(prompt).strip()

        if on_hetzner:
            if choice == "1":
                return ["185.12.64.2", "1.1.1.1", "9.9.9.9"]
            elif choice == "2":
                return ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
            elif choice == "3":
                return _get_custom_dns_servers()
            else:
                return ["SKIP"]
        else:
            if choice == "1":
                return ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
            elif choice == "2":
                return _get_custom_dns_servers()
            else:
                return ["SKIP"]

    except (EOFError, KeyboardInterrupt):
        print("\nAbgebrochen.")
        return ["SKIP"]


def _get_custom_dns_servers() -> List[str]:
    """Prompt user for custom DNS servers with 3-server limit enforcement.

    Returns:
        List[str]: Custom DNS servers or ["SKIP"] if cancelled
    """
    print("\nInterne DNS-Server eingeben (max. 3 — Linux MAXNS Limit):")
    dns_servers = []
    primary = input("Primärer DNS-Server (z.B. 192.168.1.1): ").strip()
    if primary:
        dns_servers.append(primary)
    else:
        print("Kein primärer DNS-Server angegeben, Abbruch.")
        return ["SKIP"]

    secondary = input("Sekundärer DNS-Server (optional, Enter für keinen): ").strip()
    if secondary:
        dns_servers.append(secondary)

    tertiary = input("Tertiärer DNS-Server (optional, Enter für keinen): ").strip()
    if tertiary:
        dns_servers.append(tertiary)

    if len(dns_servers) > 3:
        logger.warning("Linux unterstützt max. 3 Nameserver, verwende die ersten 3")
        dns_servers = dns_servers[:3]

    return dns_servers


def apply_dns_servers(dns_servers: List[str]) -> bool:
    """Apply specified DNS servers to the system.

    Enforces Linux 3-nameserver limit (MAXNS) by truncating excess entries.

    Args:
        dns_servers: List of DNS server IPs to configure

    Returns:
        bool: True if successful
    """
    if not dns_servers:
        return False

    # Enforce Linux MAXNS limit of 3 nameservers
    if len(dns_servers) > 3:
        logger.warning(f"Truncating {len(dns_servers)} DNS servers to max 3 (Linux MAXNS limit)")
        dns_servers = dns_servers[:3]

    logger.info(f"\nKonfiguriere DNS-Server: {', '.join(dns_servers)}")

    # Get current DNS configuration to determine method
    dns_info = check_dns_configuration()

    # Build DNS server strings
    dns_list = ' '.join(dns_servers)
    dns_nameservers = '\n'.join([f"nameserver {dns}" for dns in dns_servers])

    try:
        if dns_info["systemd_resolved"]:
            logger.info("Methode: systemd-resolved")
            config_content = f"""[Resolve]
DNS={dns_list}
FallbackDNS=8.8.4.4 1.0.0.1
DNSOverTLS=opportunistic
DNSSEC=allow-downgrade
Cache=yes
CacheFromLocalhost=yes
"""
            run_command("sudo mkdir -p /etc/systemd/resolved.conf.d", check=True)
            subprocess.run(["sudo", "tee", "/etc/systemd/resolved.conf.d/dns-optimization.conf"], input=config_content.encode(), check=True, stdout=subprocess.DEVNULL)
            run_command("sudo systemctl restart systemd-resolved", check=True)

        elif dns_info["resolvconf"]:
            logger.info("Methode: resolvconf")
            config_content = f"""# DNS servers - managed by getScripts.py
{dns_nameservers}
"""
            subprocess.run(["sudo", "tee", "/etc/resolvconf/resolv.conf.d/head"], input=config_content.encode(), check=True, stdout=subprocess.DEVNULL)
            run_command("sudo resolvconf -u", check=True)

        else:
            logger.info("Methode: direkte /etc/resolv.conf Modifikation")
            config_content = f"""# DNS configuration - managed by getScripts.py
# Date: {datetime.now().strftime('%Y-%m-%d')}
# To modify: sudo chattr -i /etc/resolv.conf
{dns_nameservers}
options timeout:2 attempts:3 rotate
"""
            run_command("sudo cp /etc/resolv.conf /etc/resolv.conf.backup.$(date +%Y%m%d_%H%M%S)", shell=True, check=True)
            run_command("sudo chattr -i /etc/resolv.conf 2>/dev/null || true", shell=True, check=True)
            run_command("sudo test -L /etc/resolv.conf && sudo rm /etc/resolv.conf || true", shell=True, check=True)
            subprocess.run(["sudo", "tee", "/etc/resolv.conf"], input=config_content.encode(), check=True, stdout=subprocess.DEVNULL)
            run_command("sudo chattr +i /etc/resolv.conf", check=True)

        # Mark as optimized
        marker_file = os.path.expanduser("~/.dns_optimized_by_getscripts")
        with open(marker_file, "w") as f:
            f.write(f"DNS optimized on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Servers: {', '.join(dns_servers)}\n")

        logger.info("✅ DNS-Konfiguration erfolgreich angewendet!")
        return True

    except Exception as e:
        logger.error(f"Fehler bei DNS-Konfiguration: {e}")
        return False


def run_first_time_setup() -> bool:
    """Run first-time setup prompts for DNS and proxy."""
    print("\n" + "=" * 60)
    print("Erste Konfiguration von getScripts.py")
    print("=" * 60)
    print("\nDieses Script wird einmalig einige Einstellungen abfragen.")
    print("Sie können diese später mit --reconfigure erneut aufrufen.\n")

    # Proxy Configuration first (network access might depend on it)
    configure_proxy_settings()

    # DNS Configuration
    dns_optimized = is_dns_already_optimized()
    if dns_optimized:
        # Double-check: validate actual MAXNS compliance
        dns_info = check_dns_configuration()
        if len(dns_info['resolv_conf']) > 3:
            logger.info(f"DNS marker found, but {len(dns_info['resolv_conf'])} nameservers configured (max 3)")
            dns_optimized = False

    if not dns_optimized:
        dns_servers = get_dns_preference()
        if dns_servers and dns_servers != ["SKIP"]:
            apply_dns_servers(dns_servers)
        else:
            mark_dns_optimization_declined()
            logger.info("DNS-Konfiguration übersprungen")
    else:
        logger.info("DNS bereits optimiert, überspringe Konfiguration")

    # Mark as configured
    mark_configured()

    print("\n" + "=" * 60)
    print("Erstkonfiguration abgeschlossen!")
    print("=" * 60)

    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Docker Server Utility Script")
    parser.add_argument("--clear-cache", action="store_true",
                       help="Clear all cached version information")
    parser.add_argument("--no-cache", action="store_true",
                       help="Disable cache for this run")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug logging")
    parser.add_argument("--dns-check", action="store_true",
                       help="Only check and optimize DNS configuration")
    parser.add_argument("--proxy-check", action="store_true",
                       help="Only configure proxy settings")
    parser.add_argument("--first-run", action="store_true",
                       help="Force first-run setup (DNS + proxy)")
    parser.add_argument("--reconfigure", action="store_true",
                       help="Reset and reconfigure DNS + proxy settings")

    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)

    if args.clear_cache:
        clear_cache()
        logger.info("Cache cleared successfully")

    if args.no_cache:
        # Disable cache by setting a flag on the function
        get_cached_version.disabled = True  # type: ignore[attr-defined]
        logger.info("Cache disabled for this run")

    if args.reconfigure:
        # Reset configuration and run first-time setup
        reset_configuration()
        clear_dns_optimization_declined()
        run_first_time_setup()
        sys.exit(0)

    if args.first_run:
        # Force first-run setup
        reset_configuration()
        run_first_time_setup()
        sys.exit(0)

    if args.dns_check:
        # Only run DNS optimization (explicitly requested, always ask user)
        optimize_dns_configuration(explicit_request=True)
        sys.exit(0)

    if args.proxy_check:
        # Only configure proxy settings
        configure_proxy_settings()
        sys.exit(0)

    # Run first-time setup if this is the first run
    if is_first_run():
        run_first_time_setup()

    main()