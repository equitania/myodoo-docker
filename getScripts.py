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
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import pickle

# Configure logging
logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('getscripts.log')
    ]
)
logger = logging.getLogger(__name__)

# Enable debug logging if environment variable is set
if os.environ.get('GETSCRIPTS_DEBUG', '').lower() in ('1', 'true', 'yes'):
    logger.setLevel(logging.DEBUG)
    logger.debug("Debug logging enabled")

# Script version and date
SCRIPT_VERSION = "6.8.11"
SCRIPT_DATE = "12.12.2025"

# Cache settings
CACHE_DIR = os.path.expanduser("~/.cache/getscripts")
CACHE_EXPIRY_HOURS = 24  # Cache version info for 24 hours

# Global cache for version information
version_cache: Dict[str, Dict[str, Any]] = {}

def ensure_cache_dir() -> None:
    """Ensure cache directory exists."""
    os.makedirs(CACHE_DIR, exist_ok=True)

def get_cache_file_path(key: str) -> str:
    """Get the cache file path for a given key."""
    return os.path.join(CACHE_DIR, f"{key}.cache")

def get_cached_version(key: str) -> Optional[Dict[str, Any]]:
    """Get cached version information.
    
    Args:
        key: Cache key
        
    Returns:
        Optional[Dict[str, Any]]: Cached data if valid, None otherwise
    """
    # Check if caching is disabled
    if getattr(get_cached_version, 'disabled', False):
        return None
        
    ensure_cache_dir()
    cache_file = get_cache_file_path(key)
    
    if not os.path.exists(cache_file):
        return None
    
    try:
        with open(cache_file, 'rb') as f:
            cached_data = pickle.load(f)
            
        # Check if cache is expired
        cache_time = datetime.fromtimestamp(os.path.getmtime(cache_file))
        if datetime.now() - cache_time > timedelta(hours=CACHE_EXPIRY_HOURS):
            logger.debug(f"Cache for {key} is expired")
            os.remove(cache_file)
            return None
            
        logger.debug(f"Using cached data for {key}")
        return cached_data
    except Exception as e:
        logger.error(f"Error reading cache for {key}: {e}")
        if os.path.exists(cache_file):
            os.remove(cache_file)
        return None

def cache_version_info(key: str, data: Dict[str, Any]) -> None:
    """Cache version information.
    
    Args:
        key: Cache key
        data: Data to cache
    """
    ensure_cache_dir()
    cache_file = get_cache_file_path(key)
    
    try:
        with open(cache_file, 'wb') as f:
            pickle.dump(data, f)
        logger.debug(f"Cached data for {key}")
    except Exception as e:
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
    cached_data = get_cached_version(cache_key)
    
    if cached_data:
        return cached_data.get("version"), cached_data.get("assets")
    
    try:
        response = requests.get("https://api.github.com/repos/fastfetch-cli/fastfetch/releases/latest")
        if response.status_code == 200:
            data = response.json()
            version = data["tag_name"].lstrip('v')
            assets = data["assets"]
            logger.info(f"Found latest FastFetch version: {version}")
            
            # Cache the result
            cache_version_info(cache_key, {"version": version, "assets": assets})
            return version, assets
        logger.error(f"Failed to get latest fastfetch version. Status code: {response.status_code}")
    except Exception as e:
        logger.error(f"Error fetching latest fastfetch version: {str(e)}")
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
    cached_data = get_cached_version(cache_key)

    if cached_data:
        return cached_data.get("version")

    try:
        response = requests.get("https://api.github.com/repos/ajeetdsouza/zoxide/releases/latest")
        if response.status_code == 200:
            data = response.json()
            version = data["tag_name"].lstrip('v')
            logger.info(f"Found latest zoxide version: {version}")

            # Cache the result
            cache_version_info(cache_key, {"version": version})
            return version
        logger.error(f"Failed to get latest zoxide version. Status code: {response.status_code}")
    except Exception as e:
        logger.error(f"Error fetching latest zoxide version: {str(e)}")
    return None

def install_zoxide_if_needed() -> None:
    """Install zoxide if it's not already installed or if the version is outdated."""
    installed, current_version = is_zoxide_installed()

    # Get latest version from GitHub
    latest_version = get_latest_zoxide_version()
    if not latest_version:
        logger.warning("Could not determine latest zoxide version, skipping update check")
        if installed:
            logger.info(f"zoxide version {current_version} is already installed.")
            return
        # Use a fallback version if we can't get the latest
        latest_version = "0.9.7"

    if installed:
        if current_version == latest_version:
            logger.info(f"zoxide version {latest_version} is already installed.")
            # Ensure PATH is set correctly
            local_bin = os.path.expanduser("~/.local/bin")
            if local_bin not in os.environ.get("PATH", ""):
                logger.info(f"Adding {local_bin} to PATH...")
                os.environ["PATH"] = f"{local_bin}:{os.environ.get('PATH', '')}"
                # Add to .zshrc if it exists
                zshrc = os.path.expanduser("~/.zshrc")
                if os.path.exists(zshrc):
                    with open(zshrc, "a") as f:
                        f.write(f'\nexport PATH="{local_bin}:$PATH"\n')
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

    logger.info(f"Downloading zoxide version {latest_version}...")

    # Installation using curl and bash with proper shell execution
    try:
        install_cmd = "curl -sS https://raw.githubusercontent.com/ajeetdsouza/zoxide/main/install.sh | bash"
        run_command(install_cmd, shell=True, check=True)
        logger.info(f"zoxide version {latest_version} was successfully installed.")
    except Exception as e:
        logger.warning(f"zoxide installation failed (this is not critical): {str(e)}")
        logger.warning("zoxide is optional - continuing without it. You can install it manually if needed.")
        logger.warning("For Alpine Linux (musl), try: apk add zoxide")

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

def get_pip_version():
    """Get pip version as a tuple of integers."""
    try:
        result = subprocess.run([sys.executable, "-m", "pip", "--version"], 
                              capture_output=True, text=True)
        version_str = result.stdout.split()[1]
        return tuple(map(int, version_str.split('.')))
    except:
        return (0, 0)

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
    # Skip packages that should not be upgraded through pip
    if package_name == "zstd":
        logger.info("Skipping zstd upgrade through pip. It will be handled separately.")
        return

    if package_name == "pip":
        logger.info("Skipping pip self-upgrade. System pip managed by package manager.")
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

def is_pipx_installed() -> bool:
    """Check if pipx is installed.
    
    Returns:
        bool: True if pipx is installed, False otherwise
    """
    try:
        result = subprocess.run(['which', 'pipx'], capture_output=True, text=True)
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Error checking pipx installation: {e}")
        return False

def install_with_pipx(package_name: str) -> None:
    """Install a package using pipx.
    
    Args:
        package_name (str): Name of the package to install
    """
    # Check if pipx is installed
    try:
        subprocess.run(['pipx', '--version'], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.error("pipx is not installed")
        raise RuntimeError("pipx is not installed. Please install pipx first.")

    try:
        subprocess.run(['pipx', 'install', '--force', package_name], check=True)
        logger.info(f"Successfully installed {package_name} with pipx")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to install {package_name} with pipx: {e}")
        raise

def install_specific_pipx_package(package_name: str, version: str) -> None:
    """
    Install a specific version of a package using pipx if it's not already installed.
    
    Args:
        package_name (str): Name of the package to install
        version (str): Specific version to install
    """
    try:
        # Check if package is installed and get its version
        result = subprocess.run(['pipx', 'list', '--json'], capture_output=True, text=True)
        if result.returncode == 0:
            import json
            installed_packages = json.loads(result.stdout)
            
            if package_name in installed_packages['venvs']:
                installed_version = installed_packages['venvs'][package_name]['metadata']['main_package']['package_version']
                if installed_version == version:
                    logger.info(f"{package_name} version {version} is already installed")
                    return
                else:
                    logger.info(f"Updating {package_name} from version {installed_version} to {version}")
                    run_command(f"pipx install {package_name}=={version} --force")
            else:
                logger.info(f"Installing {package_name} version {version}")
                run_command(f"pipx install {package_name}=={version}")
    except Exception as e:
        logger.error(f"Unexpected error installing {package_name}: {str(e)}")

def read_package_versions(filename: str = "packages.txt") -> dict:
    """Read package versions from packages.txt file.
    
    Returns:
        dict: Dictionary containing package types and their versions
    """
    packages = {
        "pipx": {},
        "pip": [
            "python-dotenv",
            # ... other pip packages ...
        ],
        "system": []
    }
    
    try:
        with open(filename, 'r') as f:
            current_section = None
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    if "PIPX packages" in line:
                        current_section = "pipx"
                    elif "PIP packages" in line:
                        current_section = "pip"
                    elif "System packages" in line:
                        current_section = "system"
                    continue
                
                if current_section == "pipx":
                    if "==" in line:
                        name, version = line.split("==")
                        packages["pipx"][name.strip()] = version.strip()
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
    cached_data = get_cached_version(cache_key)
    
    if cached_data:
        return cached_data.get("version")
    
    try:
        response = requests.get("https://api.github.com/repos/sharkdp/bat/releases/latest")
        if response.status_code == 200:
            data = response.json()
            version = data["tag_name"].lstrip('v')
            logger.info(f"Found latest bat version: {version}")
            
            # Cache the result
            cache_version_info(cache_key, {"version": version})
            return version
        logger.error(f"Failed to get latest bat version. Status code: {response.status_code}")
    except Exception as e:
        logger.error(f"Error fetching latest bat version: {str(e)}")
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
    """Upgrade pip to the latest version."""
    try:
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

def get_7zip_version() -> Optional[tuple]:
    """Get installed 7-Zip version as tuple (major, minor, patch)"""
    import shutil

    # Try to find 7zz in common locations
    seven_zz_cmd = None
    for path in [shutil.which('7zz'), '/usr/local/bin/7zz', os.path.expanduser('~/.local/bin/7zz')]:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            seven_zz_cmd = path
            break

    try:
        # First try 7zz (new version) using the found path
        if seven_zz_cmd:
            result = subprocess.run([seven_zz_cmd, '--help'], capture_output=True, text=True)
            if result.returncode == 0:
                # 7zz output format: "7-Zip (z) [64] 21.07 : Copyright (c) 1999-2021 Igor Pavlov"
                version_line = result.stdout.split('\n')[0].strip()
                version_match = re.search(r'\d+\.\d+', version_line)
                if version_match:
                    version_str = version_match.group(0)
                    # Convert to tuple (major, minor, 0) as 7zip usually only has major.minor
                    major, minor = map(int, version_str.split('.'))
                    return (major, minor, 0)
    except FileNotFoundError:
        # Fall back to checking old 7z command, but we'll eventually remove/replace it
        try:
            result = subprocess.run(['7z', '--help'], capture_output=True, text=True)
            if result.returncode == 0:
                # 7-Zip output format: "7-Zip [64] 16.02"
                version_line = result.stdout.split('\n')[1].strip() if len(result.stdout.split('\n')) > 1 else result.stdout.strip()
                version_match = re.search(r'\d+\.\d+', version_line)
                if version_match:
                    version_str = version_match.group(0)
                    # Convert to tuple (major, minor, 0) as 7zip usually only has major.minor
                    major, minor = map(int, version_str.split('.'))
                    return (major, minor, 0)
        except Exception:
            # Ignore errors from the old version
            pass

    # Check using dpkg if we're on Debian/Ubuntu
    try:
        if is_debian_or_ubuntu():
            result = subprocess.run(['dpkg', '-s', '7zip'], capture_output=True, text=True)
            if result.returncode == 0:
                version_match = re.search(r'Version: (\d+\.\d+)', result.stdout)
                if version_match:
                    version_str = version_match.group(1)
                    # Convert to tuple (major, minor, 0)
                    major, minor = map(int, version_str.split('.'))
                    return (major, minor, 0)
    except Exception as e:
        logger.error(f"Error getting 7-Zip version: {str(e)}")
    return None

def check_7zip_version() -> bool:
    """Check if 7-Zip is installed and meets minimum version requirements"""
    try:
        # First try to find the 7zz command (new version)
        # Use shutil.which for more robust binary detection
        import shutil

        # Check common installation paths
        seven_zz_paths = [
            shutil.which('7zz'),  # Check PATH
            '/usr/local/bin/7zz',  # System-wide installation
            os.path.expanduser('~/.local/bin/7zz')  # User installation
        ]

        seven_zz_found = False
        for path in seven_zz_paths:
            if path and os.path.isfile(path) and os.access(path, os.X_OK):
                seven_zz_found = True
                break

        if not seven_zz_found:
            logger.warning("7zz command not found. Need to install newer 7-Zip version.")
            return False

        # Check if the package is installed via dpkg
        if is_package_installed("7zip"):
            version = get_7zip_version()
            if version:
                version_str = '.'.join(map(str, version[:2]))  # Only show major.minor
                logger.info(f"Current 7-Zip version: {version_str}")
                # Minimum required version for newer 7zip
                min_version = (21, 0, 0)  # 21.x is newer and preferred

                if version < min_version:
                    logger.warning(f"7-Zip version {version_str} is outdated. Minimum required version is {'.'.join(map(str, min_version[:2]))}")
                    return False
                return True
            else:
                # Package is installed but version detection failed
                logger.info("7-Zip package is installed, but version detection failed. Assuming it's valid.")
                return True

        # If we get here, check using the normal version detection
        version = get_7zip_version()
        if not version:
            logger.error("7-Zip is not installed")
            return False

        version_str = '.'.join(map(str, version[:2]))  # Only show major.minor
        logger.info(f"Current 7-Zip version: {version_str}")

        # Check if old p7zip-full is installed (which provides 7z command)
        try:
            old_result = subprocess.run(['which', '7z'], capture_output=True, text=True)
            if old_result.returncode == 0 and not subprocess.run(['which', '7zz'], capture_output=True).returncode == 0:
                logger.warning("Old p7zip-full package detected (7z command), but new 7zip (7zz) not found")
                return False
        except:
            pass

        # Minimum required version for newer 7zip
        min_version = (21, 0, 0)  # 21.x is newer and preferred

        if version < min_version:
            logger.warning(f"7-Zip version {version_str} is outdated. Minimum required version is {'.'.join(map(str, min_version[:2]))}")
            return False
        return True
    except Exception as e:
        logger.error(f"Error checking 7-Zip version: {str(e)}")
        return False

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
                            version_line = result.stdout.split('\n')[0].strip()
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

            arch = platform.machine()
            if arch == "x86_64":
                download_url = "https://www.7-zip.org/a/7z2408-linux-x64.tar.xz"
                filename = "7z2408-linux-x64.tar.xz"
            elif arch == "aarch64":
                download_url = "https://www.7-zip.org/a/7z2408-linux-arm64.tar.xz"
                filename = "7z2408-linux-arm64.tar.xz"
            else:
                raise RuntimeError(f"Unsupported architecture for 7-Zip: {arch}")

            # Download and install
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

                    # Ensure PATH is set
                    ensure_path_in_zshrc()

            # Verify installation
            if not check_7zip_version():
                raise RuntimeError("Failed to install/update 7-Zip")

            logger.info("7-Zip installation/update completed successfully")

            # Show installed version
            try:
                result = subprocess.run(['7zz', '--help'], capture_output=True, text=True)
                version_line = result.stdout.split('\n')[0].strip()
                logger.info(f"Installed: {version_line}")
            except:
                pass

    except Exception as e:
        logger.error(f"Error installing/updating 7-Zip: {str(e)}")
        raise

def check_oxker_installed() -> bool:
    """Check if oxker is installed.
    
    Returns:
        bool: True if oxker is installed, False otherwise
    """
    # First check if it exists in ~/.local/bin
    try:
        local_bin = os.path.expanduser("~/.local/bin")
        oxker_path = os.path.join(local_bin, "oxker")
        if os.path.exists(oxker_path) and os.access(oxker_path, os.X_OK):
            return True
    except Exception as e:
        logger.debug(f"Error checking oxker in local bin: {e}")
    
    # Then check if it's in the PATH
    try:
        result = subprocess.run(['which', 'oxker'], capture_output=True, text=True)
        if result.returncode == 0:
            return True
    except Exception as e:
        logger.debug(f"Error checking oxker in PATH: {e}")
        
    return False

def get_oxker_version() -> Optional[str]:
    """Get installed oxker version.
    
    Returns:
        Optional[str]: Version string if installed, None otherwise
    """
    try:
        # First try with full path
        local_bin = os.path.expanduser("~/.local/bin")
        oxker_path = os.path.join(local_bin, "oxker")
        
        if os.path.exists(oxker_path):
            try:
                result = subprocess.run([oxker_path, '--version'], 
                                     capture_output=True, text=True)
                if result.returncode == 0:
                    return result.stdout.strip().split(' ')[1].lstrip('v')
            except Exception as e:
                logger.debug(f"Error running oxker with full path: {e}")
        
        # Then try regular PATH
        try:
            result = subprocess.run(['oxker', '--version'], 
                                 capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip().split(' ')[1].lstrip('v')
        except FileNotFoundError:
            # Not found in PATH, which is expected if not installed
            pass
        except Exception as e:
            logger.debug(f"Error running oxker from PATH: {e}")
            
        # If we got here, oxker is not installed or not working
        return None
    except Exception as e:
        logger.debug(f"Error in get_oxker_version: {e}")
        return None

@lru_cache(maxsize=128)
def get_latest_oxker_version() -> Optional[str]:
    """Get the latest version of oxker from GitHub releases with caching.
    
    Returns:
        Optional[str]: Latest version string if available, None otherwise
    """
    cache_key = "oxker_latest"
    cached_data = get_cached_version(cache_key)
    
    if cached_data:
        return cached_data.get("version")
    
    try:
        response = requests.get("https://api.github.com/repos/mrjackwills/oxker/releases/latest")
        if response.status_code == 200:
            data = response.json()
            version = data["tag_name"].lstrip('v')
            logger.info(f"Found latest oxker version: {version}")
            
            # Cache the result
            cache_version_info(cache_key, {"version": version})
            return version
        logger.error(f"Failed to get latest oxker version. Status code: {response.status_code}")
    except Exception as e:
        logger.error(f"Error fetching latest oxker version: {str(e)}")
    return None

def install_or_update_oxker() -> None:
    """Install or update oxker to the latest version."""
    try:
        # Save current working directory
        original_dir = os.getcwd()
        
        # Check current version if installed
        installed = check_oxker_installed()
        current_version = get_oxker_version() if installed else None
        
        if installed:
            logger.info(f"Current oxker version: {current_version}")
        else:
            logger.info("oxker is not installed")
        
        # Get latest version from GitHub
        latest_version = get_latest_oxker_version()
        if not latest_version:
            logger.error("Could not determine latest oxker version")
            return

        # Check if update is needed
        if installed and current_version == latest_version:
            logger.info(f"oxker is already at the latest version ({latest_version})")
            return
        
        # Install or update
        logger.info(f"{'Updating' if installed else 'Installing'} oxker to version {latest_version}...")
        
        # Determine system architecture
        arch = platform.machine()
        if arch == "x86_64":
            suffix = "x86_64"
        elif arch == "aarch64":
            suffix = "aarch64"
        elif arch == "armv6l":
            suffix = "armv6"
        else:
            logger.error(f"Unsupported architecture for oxker: {arch}")
            return
        
        # Create temporary directory for download
        with tempfile.TemporaryDirectory() as temp_dir:
            os.chdir(temp_dir)
            
            try:
                # Download the latest release
                oxker_gz = f"oxker_linux_{suffix}.tar.gz"
                download_url = f"https://github.com/mrjackwills/oxker/releases/latest/download/{oxker_gz}"
                
                logger.info(f"Downloading oxker from {download_url}")
                response = requests.get(download_url, stream=True)
                response.raise_for_status()
                
                with open(oxker_gz, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                # Extract the binary
                run_command(f"tar xzvf {oxker_gz} oxker")
                
                # Install to ~/.local/bin
                local_bin = os.path.expanduser("~/.local/bin")
                ensure_directory_exists(local_bin)
                run_command(f"install -Dm 755 oxker -t {local_bin}")
                
                # Ensure PATH is set in .zshrc
                ensure_path_in_zshrc()
                
                # Try to set PATH for current process
                if local_bin not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = f"{local_bin}:{os.environ.get('PATH', '')}"
                    logger.info(f"Added {local_bin} to PATH for current process")
                
                # Test if oxker is now accessible
                run_command("hash -r", shell=True)  # Clear path cache
                
                # Full path to oxker executable
                oxker_path = os.path.join(local_bin, "oxker")
                
                # Show file permissions
                logger.info(f"Checking permissions for {oxker_path}")
                run_command(f"ls -la {oxker_path}", shell=True)
                
                # Verify installation using full path
                if os.path.exists(oxker_path):
                    # Try running oxker with full path
                    try:
                        result = subprocess.run([oxker_path, '--version'], 
                                            capture_output=True, text=True)
                        if result.returncode == 0:
                            new_version = result.stdout.strip().split(' ')[1].lstrip('v')
                            logger.info(f"oxker {new_version} has been successfully installed to {oxker_path}")
                            
                            # Make sure to return to original directory before returning
                            try:
                                os.chdir(original_dir)
                            except FileNotFoundError:
                                # If original directory is gone, go to home directory
                                os.chdir(os.path.expanduser("~"))
                            return
                    except Exception as e:
                        logger.error(f"Error running {oxker_path}: {str(e)}")
                
                logger.error(f"Failed to verify oxker installation at {oxker_path}")
                raise RuntimeError(f"Failed to verify oxker installation at {oxker_path}")
            
            finally:
                # Always try to return to original directory
                try:
                    os.chdir(original_dir)
                except FileNotFoundError:
                    # If original directory is gone, go to home directory
                    os.chdir(os.path.expanduser("~"))
        
    except Exception as e:
        logger.error(f"Error installing/updating oxker: {str(e)}")
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

    Returns:
        bool: True if DNS appears to be already optimized
    """
    try:
        # Check if resolvconf head file exists with our marker
        head_file = "/etc/resolvconf/resolv.conf.d/head"
        if os.path.exists(head_file):
            with open(head_file, "r") as f:
                content = f.read()
                if "managed by getScripts.py" in content:
                    return True

        # Check if systemd-resolved config exists with our marker
        resolved_config = "/etc/systemd/resolved.conf.d/dns-optimization.conf"
        if os.path.exists(resolved_config):
            return True

        # Check if direct resolv.conf has our marker
        if os.path.exists("/etc/resolv.conf"):
            with open("/etc/resolv.conf", "r") as f:
                content = f.read()
                if "managed by getScripts.py" in content:
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
    
    # Check if using Hetzner DNS (known to have issues with DigitalOcean)
    hetzner_dns = ["185.12.64.1", "185.12.64.2", "2a01:4ff:ff00::add:1", "2a01:4ff:ff00::add:2"]
    current_dns = dns_info['resolv_conf']
    
    # Check if already optimized with recommended DNS servers
    recommended_dns = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
    primary_dns = current_dns[0] if current_dns else None
    
    # Check if DNS was already optimized by our script
    already_optimized = is_dns_already_optimized()
    
    # Check if the primary DNS is already optimized
    if primary_dns in recommended_dns and already_optimized:
        logger.info(f"\n✅ DNS is already optimized with {primary_dns} as primary DNS server")
        # Still check for Hetzner DNS in fallback positions for information
        if any(dns in hetzner_dns for dns in current_dns[3:]):  # Check fallback servers only
            logger.info("ℹ️  Note: Hetzner DNS servers are present as fallback servers (positions 4+)")
    elif primary_dns in recommended_dns and not already_optimized:
        # DNS servers are good but not set by our script - might be manually configured
        logger.info(f"\n✅ DNS appears to be manually optimized with {primary_dns} as primary DNS server")
        # Check if Hetzner DNS is in primary positions
        if any(dns in hetzner_dns for dns in current_dns[:2]):
            logger.warning("\n⚠️  Detected Hetzner DNS servers in primary/secondary positions")
            needs_optimization = True
    else:
        # Not using recommended DNS servers
        if any(dns in hetzner_dns for dns in current_dns):
            logger.warning("\n⚠️  Detected Hetzner DNS servers which may cause issues with some providers")
            needs_optimization = True
    
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
    
    # Ask user if they want to optimize
    logger.info("\n" + "-"*60)
    logger.info("DNS Optimization Recommended")
    logger.info("-"*60)
    logger.info("\nRecommended DNS servers for better performance:")
    logger.info("- Primary: 1.1.1.1 (Cloudflare)")
    logger.info("- Secondary: 8.8.8.8 (Google)")
    logger.info("- Tertiary: 9.9.9.9 (Quad9)")
    
    # Different optimization based on DNS management system
    if dns_info["systemd_resolved"]:
        logger.info("\nOptimization method: systemd-resolved configuration")
        optimization_commands = [
            "sudo mkdir -p /etc/systemd/resolved.conf.d",
            '''sudo tee /etc/systemd/resolved.conf.d/dns-optimization.conf > /dev/null << EOF
[Resolve]
DNS=1.1.1.1 8.8.8.8 9.9.9.9
FallbackDNS=8.8.4.4 1.0.0.1
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
            '''sudo tee /etc/resolvconf/resolv.conf.d/head > /dev/null << EOF
# Optimized DNS servers - managed by getScripts.py
nameserver 1.1.1.1
nameserver 8.8.8.8
nameserver 9.9.9.9
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
            # Create new resolv.conf with optimized DNS
            '''sudo tee /etc/resolv.conf > /dev/null << EOF
# Optimized DNS configuration - managed by getScripts.py
# Date: $(date +%Y-%m-%d)
# To modify this file, first run: sudo chattr -i /etc/resolv.conf
nameserver 1.1.1.1
nameserver 8.8.8.8
nameserver 9.9.9.9
options timeout:2 attempts:3 rotate
EOF''',
            # Make the file immutable to prevent automatic changes
            "sudo chattr +i /etc/resolv.conf"
        ]
    
    # Docker-specific instructions
    if "127.0.0.11" in current_dns:
        logger.info("\n📋 For Docker containers, add this to your docker-compose.yml:")
        logger.info("""
services:
  your-service:
    dns:
      - 1.1.1.1
      - 8.8.8.8
      - 9.9.9.9
""")
        logger.info("\n📋 Or use these flags with docker run:")
        logger.info("docker run --dns 1.1.1.1 --dns 8.8.8.8 --dns 9.9.9.9 ...")
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

def ensure_path_in_zshrc() -> None:
    """Ensure ~/.local/bin is in PATH in .zshrc file."""
    try:
        home = os.path.expanduser("~")
        zshrc_path = os.path.join(home, ".zshrc")
        local_bin = os.path.join(home, ".local", "bin")
        
        # Check if .zshrc exists
        if not os.path.exists(zshrc_path):
            logger.info(".zshrc not found, creating it")
            with open(zshrc_path, "w") as f:
                f.write(f'# Created by getScripts.py\nexport PATH="{local_bin}:$PATH"\n')
            return
            
        # Read current .zshrc
        with open(zshrc_path, "r") as f:
            content = f.read()
            
        # Check if PATH is already set correctly
        if f'export PATH="{local_bin}:$PATH"' in content or f"export PATH={local_bin}:$PATH" in content:
            logger.info(f"{local_bin} is already in PATH in .zshrc")
            return
            
        # Add PATH to .zshrc
        logger.info(f"Adding {local_bin} to PATH in .zshrc")
        with open(zshrc_path, "a") as f:
            f.write(f'\n# Added by getScripts.py\nexport PATH="{local_bin}:$PATH"\n')
            
        logger.info(".zshrc updated, PATH will be available in new shells")
    except Exception as e:
        logger.error(f"Error updating .zshrc: {e}")

@lru_cache(maxsize=128)
def get_latest_pypi_version(package_name: str) -> Optional[str]:
    """Get the latest version of a package from PyPI with caching.
    
    Args:
        package_name (str): Name of the package
        
    Returns:
        Optional[str]: Latest version string if available, None otherwise
    """
    cache_key = f"pypi_{package_name}"
    cached_data = get_cached_version(cache_key)
    
    if cached_data:
        return cached_data.get("version")
    
    try:
        url = f"https://pypi.org/pypi/{package_name}/json"
        logger.info(f"Checking latest version of {package_name} from PyPI")
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            latest_version = data["info"]["version"]
            logger.info(f"Latest {package_name} version on PyPI: {latest_version}")
            
            # Cache the result
            cache_version_info(cache_key, {"version": latest_version})
            return latest_version
        logger.error(f"Failed to get latest {package_name} version. Status code: {response.status_code}")
    except Exception as e:
        logger.error(f"Error fetching latest {package_name} version from PyPI: {str(e)}")
    return None

def get_installed_pipx_version(package_name: str) -> Optional[str]:
    """Get the installed version of a pipx package.
    
    Args:
        package_name (str): Name of the package
        
    Returns:
        Optional[str]: Installed version string if available, None otherwise
    """
    try:
        # Check if package is installed with pipx
        result = subprocess.run(['pipx', 'list', '--json'], capture_output=True, text=True)
        if result.returncode == 0:
            import json
            installed_packages = json.loads(result.stdout)
            
            if package_name in installed_packages['venvs']:
                version = installed_packages['venvs'][package_name]['metadata']['main_package']['package_version']
                logger.info(f"Installed {package_name} version: {version}")
                return version
            logger.info(f"{package_name} is not installed with pipx")
        return None
    except Exception as e:
        logger.error(f"Error getting installed {package_name} version: {str(e)}")
        return None

def install_or_update_nginx_set_conf() -> None:
    """Install or update nginx-set-conf to the latest version."""
    package_name = "nginx-set-conf"
    
    try:
        # Check if already installed with pipx
        current_version = get_installed_pipx_version(package_name)
        
        # Get latest version from PyPI
        latest_version = get_latest_pypi_version(package_name)
        if not latest_version:
            logger.error(f"Could not determine latest {package_name} version")
            return
            
        # Check if update is needed
        if current_version and current_version == latest_version:
            logger.info(f"{package_name} is already at the latest version ({latest_version})")
            return
            
        # Uninstall if already installed (to ensure a clean installation)
        if current_version:
            logger.info(f"Uninstalling {package_name} version {current_version} to update to {latest_version}")
            run_command(f"pipx uninstall {package_name}")
        
        # Install latest version with force flag to handle existing directory
        logger.info(f"Installing {package_name} version {latest_version}")
        result = run_command(f"pipx install {package_name}", capture_output=True)
        
        # If installation fails due to existing directory, use force flag
        if result.returncode != 0 and "existing directory" in result.stderr:
            logger.info(f"Directory exists, installing with --force flag")
            run_command(f"pipx install --force {package_name}")
        
        # Verify installation
        new_version = get_installed_pipx_version(package_name)
        if new_version:
            logger.info(f"Successfully installed {package_name} version {new_version}")
        else:
            logger.error(f"Failed to verify {package_name} installation")
    except Exception as e:
        logger.error(f"Error installing/updating {package_name}: {str(e)}")

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
            elif package_type == "pipx":
                current = get_installed_pipx_version(package_name)
                latest = get_latest_pypi_version(package_name)
                return package_name, {"type": "pipx", "current": current, "latest": latest}
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
        logger.warning("⚠️  User-level installations (pipx, pip packages) will still work.")
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
    ensure_path_in_zshrc()
    
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
    # Copy .zshrc
    source_zshrc = os.path.join(myodoo_docker, ".zshrc")
    target_zshrc = os.path.join(_myhome, ".zshrc")
    if os.path.exists(source_zshrc):
        if os.path.exists(target_zshrc):
            backup_path = f"{target_zshrc}.bak"
            logger.info(f"Backing up existing .zshrc to {backup_path}")
            run_command(f"cp {target_zshrc} {backup_path}")
        
        logger.info(f"Copying .zshrc from {source_zshrc} to {target_zshrc}")
        run_command(f"cp {source_zshrc} {target_zshrc}")
        ensure_path_in_zshrc()
    
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
        "update_docker_myodoo.py",
        "docker-clean-logs.sh",
        "cleanup-weblogs.py",
        "container2backup.py",
        "container2backup_zstd.py",
        "restore-zip.sh",
        "ssl-renew.sh",
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
    
    # Check if pipx is installed
    if not is_pipx_installed():
        logger.info("Installing pipx...")
        install_system_package("pipx")
        run_command("pipx ensurepath")
        ensure_path_in_zshrc()
    
    # Install or update nginx-set-conf
    install_or_update_nginx_set_conf()
    
    # Install specific versions of packages with pipx
    if is_pipx_installed():
        for package, version in package_info["pipx"].items():
            if package != "nginx-set-conf":
                install_specific_pipx_package(package, version)
    
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
    install_or_update_oxker()
    install_or_update_mcedit()

def main() -> None:
    """Main function to execute the script."""
    original_dir = os.getcwd()
    
    try:
        # Setup environment
        _myhome, local_bin = setup_environment()
        
        # First, upgrade pip if needed
        upgrade_pip()
        
        # Check and optimize DNS configuration
        optimize_dns_configuration()
        
        global_server_version = '2025'
        myodoo_docker = os.path.join(_myhome, "myodoo-docker")
        
        # Update or clone repository
        try:
            update_repository(myodoo_docker, global_server_version)
        except Exception as e:
            logger.error(f"Failed to update or clone repository: {e}")
            logger.error(f"Please check network connectivity and permissions")
            sys.exit(1)
        
        # Copy configuration files and scripts
        copy_configuration_files(_myhome, myodoo_docker)
        copy_scripts(_myhome, myodoo_docker)
        
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
        
        # Reload shell configuration
        logger.info("Reloading shell configuration...")
        try:
            if local_bin not in os.environ.get("PATH", ""):
                os.environ["PATH"] = f"{local_bin}:{os.environ.get('PATH', '')}"
            
            zoxide_path = os.path.join(_myhome, ".local", "bin", "zoxide")
            if os.path.exists(zoxide_path):
                run_command(f"/usr/bin/zsh -c 'source <({zoxide_path} init zsh)'", shell=True)
            else:
                run_command("/usr/bin/zsh -c 'hash -r && source <(zoxide init zsh)'", shell=True)
            
            logger.info("For the PATH changes to take effect in new shells, you may need to restart your terminal or run 'source ~/.zshrc'")
            
        except Exception as e:
            logger.error(f"Error reloading shell configuration: {e}")
        
        # Return to original directory
        try:
            os.chdir(original_dir)
        except FileNotFoundError:
            os.chdir(_myhome)
        
        logger.info("Script completed successfully!")
        
    except Exception as e:
        logger.error(f"An error occurred in main: {str(e)}")
        try:
            os.getcwd()
        except FileNotFoundError:
            os.chdir(os.path.expanduser("~"))
        sys.exit(1)

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
    
    args = parser.parse_args()
    
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    if args.clear_cache:
        clear_cache()
        logger.info("Cache cleared successfully")
    
    if args.no_cache:
        # Disable cache by setting a flag on the function
        get_cached_version.disabled = True
        logger.info("Cache disabled for this run")
    
    if args.dns_check:
        # Only run DNS optimization (explicitly requested, always ask user)
        optimize_dns_configuration(explicit_request=True)
        sys.exit(0)
    
    main()