#!/usr/bin/python3
# -*- coding: utf-8 -*-
# System Preparation Script - Install essential tools and libraries

##############################################################################
#
#    Shell Script for system preparation
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
from datetime import datetime, timedelta
import pickle

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('prepare-system.log')
    ]
)
logger = logging.getLogger(__name__)

# Enable debug logging if environment variable is set
if os.environ.get('PREPARE_SYSTEM_DEBUG', '').lower() in ('1', 'true', 'yes'):
    logger.setLevel(logging.DEBUG)
    logger.debug("Debug logging enabled")

# Script version and date
SCRIPT_VERSION = "1.1.0"
SCRIPT_DATE = "19.11.2025"

# Cache settings
CACHE_DIR = os.path.expanduser("~/.cache/prepare-system")
CACHE_EXPIRY_HOURS = 24

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
    if getattr(get_cached_version, 'disabled', False):
        return None

    ensure_cache_dir()
    cache_file = get_cache_file_path(key)

    if not os.path.exists(cache_file):
        return None

    try:
        with open(cache_file, 'rb') as f:
            cached_data = pickle.load(f)

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
    """Cache version information."""
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
╔═════════════════════════════════════════════╗
║                                             ║
║   prepare-system.py - System Setup Utility  ║
║                                             ║
║      Version: {SCRIPT_VERSION}      Date: {SCRIPT_DATE}   ║
║                                             ║
╚═════════════════════════════════════════════╝
"""
    print(header)
    logger.info(f"Running prepare-system.py version {SCRIPT_VERSION} ({SCRIPT_DATE})")

def retry_on_exception(retries: int = 3, delay: int = 1):
    """Decorator to retry functions on exception."""
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

def run_command(command: str, capture_output: bool = False, shell: bool = False) -> Optional[str]:
    """Execute a shell command and return the output."""
    try:
        if capture_output:
            result = subprocess.run(
                command if shell else command.split(),
                capture_output=True,
                text=True,
                shell=shell,
                check=True
            )
            return result.stdout.strip()
        else:
            subprocess.run(
                command if shell else command.split(),
                shell=shell,
                check=True
            )
            return None
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {command}")
        logger.error(f"Error: {e}")
        return None

def get_current_shell() -> str:
    """Detect the current shell type.

    Returns:
        str: Shell type ('fish', 'zsh', 'bash', etc.)
    """
    try:
        shell_path = os.environ.get('SHELL', '')
        shell_name = os.path.basename(shell_path)

        if not shell_name:
            try:
                import psutil
                parent = psutil.Process(os.getppid())
                shell_name = parent.name()
            except ImportError:
                logger.warning("psutil not available, cannot detect shell from process")
                shell_name = 'zsh'

        logger.info(f"Detected shell: {shell_name}")
        return shell_name
    except Exception as e:
        logger.warning(f"Could not detect shell, defaulting to zsh: {e}")
        return 'zsh'

def ensure_path_in_shell_config() -> None:
    """Ensure ~/.local/bin is in PATH in shell configuration file."""
    try:
        home = os.path.expanduser("~")
        local_bin = os.path.join(home, ".local", "bin")
        shell = get_current_shell()

        if shell == 'fish':
            fish_config_dir = os.path.join(home, ".config", "fish")
            fish_config_path = os.path.join(fish_config_dir, "config.fish")

            os.makedirs(fish_config_dir, exist_ok=True)

            if not os.path.exists(fish_config_path):
                logger.info("config.fish not found, creating it")
                with open(fish_config_path, "w") as f:
                    f.write(f'# Created by prepare-system.py\nset -gx PATH {local_bin} $PATH\n')
                return

            with open(fish_config_path, "r") as f:
                content = f.read()

            if f'set -gx PATH {local_bin}' in content or f'set -x PATH {local_bin}' in content:
                logger.info(f"{local_bin} is already in PATH in config.fish")
                return

            logger.info(f"Adding {local_bin} to PATH in config.fish")
            with open(fish_config_path, "a") as f:
                f.write(f'\n# Added by prepare-system.py\nset -gx PATH {local_bin} $PATH\n')

            logger.info("config.fish updated, PATH will be available in new shells")
        else:
            zshrc_path = os.path.join(home, ".zshrc")

            if not os.path.exists(zshrc_path):
                logger.info(".zshrc not found, creating it")
                with open(zshrc_path, "w") as f:
                    f.write(f'# Created by prepare-system.py\nexport PATH="{local_bin}:$PATH"\n')
                return

            with open(zshrc_path, "r") as f:
                content = f.read()

            if f'export PATH="{local_bin}:$PATH"' in content or f"export PATH={local_bin}:$PATH" in content:
                logger.info(f"{local_bin} is already in PATH in .zshrc")
                return

            logger.info(f"Adding {local_bin} to PATH in .zshrc")
            with open(zshrc_path, "a") as f:
                f.write(f'\n# Added by prepare-system.py\nexport PATH="{local_bin}:$PATH"\n')

            logger.info(".zshrc updated, PATH will be available in new shells")
    except Exception as e:
        logger.error(f"Error updating shell configuration: {e}")

def is_package_installed(package_name: str) -> bool:
    """Check if a system package is installed."""
    try:
        result = subprocess.run(
            ["dpkg", "-s", package_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False
        )
        return result.returncode == 0
    except Exception:
        return False

def install_system_package(package: str, version: Optional[str] = None) -> None:
    """Install a system package using apt."""
    try:
        package_spec = f"{package}={version}" if version else package
        logger.info(f"Installing system package: {package_spec}")

        subprocess.run(
            ["sudo", "apt", "update"],
            capture_output=True,
            check=True
        )

        subprocess.run(
            ["sudo", "apt", "install", "-y", package_spec],
            check=True
        )

        logger.info(f"Successfully installed {package_spec}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to install {package}: {e}")
        raise

def is_fastfetch_installed() -> Tuple[bool, Optional[str]]:
    """Check if fastfetch is installed and get its version."""
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
        return False, None
    except FileNotFoundError:
        logger.info("Fastfetch not found")
        return False, None

def is_zoxide_installed() -> Tuple[bool, Optional[str]]:
    """Check if zoxide is installed and get its version."""
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
                version = parts[1]
                logger.info(f"zoxide version {version} found")
                return True, version
    except FileNotFoundError:
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
                        version = parts[1]
                        logger.info(f"zoxide version {version} found in ~/.local/bin")
                        return True, version
            except Exception:
                pass

    logger.info("zoxide not found")
    return False, None

@retry_on_exception(retries=3)
def download_and_install_deb(url: str, filename: str) -> None:
    """Download and install a .deb package with retry mechanism."""
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()

        block_size = 1024
        with open(filename, 'wb') as file:
            for data in response.iter_content(block_size):
                file.write(data)

        if not os.path.exists(filename) or os.path.getsize(filename) == 0:
            raise Exception("Downloaded file is empty or does not exist")

        logger.info(f"Successfully downloaded {filename}")

        subprocess.run(
            ["sudo", "dpkg", "-i", filename],
            capture_output=True,
            text=True,
            check=True
        )
        logger.info(f"Successfully installed {filename}")

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

@lru_cache(maxsize=128)
def get_latest_github_release(repo: str) -> Optional[Dict[str, Any]]:
    """Get the latest release information from GitHub."""
    cache_key = f"github_{repo.replace('/', '_')}"
    cached_data = get_cached_version(cache_key)

    if cached_data:
        return cached_data

    try:
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        cache_version_info(cache_key, data)
        return data
    except Exception as e:
        logger.error(f"Failed to get latest release for {repo}: {e}")
        return None

def get_fastfetch_download_url(_version: str, os_id: str, assets: Optional[List[Dict]] = None) -> Optional[str]:
    """Get the download URL for fastfetch based on OS and architecture."""
    if not assets:
        release_data = get_latest_github_release("fastfetch-cli/fastfetch")
        if not release_data:
            return None
        assets = release_data.get("assets", [])
        # Version from release_data is used if assets not provided
        _version = release_data.get("tag_name", "").lstrip("v")

    arch = platform.machine().lower()

    arch_mapping = {
        'x86_64': 'amd64',
        'amd64': 'amd64',
        'aarch64': 'arm64',
        'arm64': 'arm64',
        'armv7l': 'armhf',
        'armv6l': 'armel'
    }

    deb_arch = arch_mapping.get(arch)
    if not deb_arch:
        logger.error(f"Unsupported architecture: {arch}")
        return None

    pattern = f"fastfetch-linux-{deb_arch}.deb"

    for asset in assets:
        if pattern in asset.get("name", ""):
            return asset.get("browser_download_url")

    logger.warning(f"No suitable package found for {os_id} {deb_arch}")
    return None

def install_fastfetch_if_needed() -> None:
    """Install or update fastfetch if needed."""
    try:
        is_installed, current_version = is_fastfetch_installed()

        release_data = get_latest_github_release("fastfetch-cli/fastfetch")
        if not release_data:
            if is_installed:
                logger.info(f"fastfetch {current_version} is installed, cannot check for updates")
            else:
                logger.warning("Could not fetch fastfetch release information")
            return

        latest_version = release_data.get("tag_name", "").lstrip("v")

        if is_installed:
            if current_version == latest_version:
                logger.info(f"fastfetch {current_version} is up to date")
                return
            logger.info(f"Updating fastfetch from {current_version} to {latest_version}")
        else:
            logger.info(f"Installing fastfetch {latest_version}")

        os_id = "linux"
        assets = release_data.get("assets", [])
        download_url = get_fastfetch_download_url(latest_version, os_id, assets)

        if not download_url:
            logger.warning("Could not determine download URL for fastfetch")
            return

        filename = "fastfetch.deb"
        download_and_install_deb(download_url, filename)

        logger.info("fastfetch installation completed successfully")

    except Exception as e:
        logger.error(f"Error installing fastfetch: {e}")

def install_zoxide_if_needed() -> None:
    """Install or update zoxide if needed."""
    try:
        is_installed, current_version = is_zoxide_installed()

        release_data = get_latest_github_release("ajeetdsouza/zoxide")
        if not release_data:
            if is_installed:
                logger.info(f"zoxide {current_version} is installed, cannot check for updates")
            else:
                logger.warning("Could not fetch zoxide release information")
            return

        latest_version = release_data.get("tag_name", "").lstrip("v")

        if is_installed:
            if current_version == latest_version:
                logger.info(f"zoxide {current_version} is up to date")
                return
            logger.info(f"Updating zoxide from {current_version} to {latest_version}")
        else:
            logger.info(f"Installing zoxide {latest_version}")

        home = os.path.expanduser("~")
        local_bin = os.path.join(home, ".local", "bin")
        os.makedirs(local_bin, exist_ok=True)

        arch = platform.machine().lower()
        arch_mapping = {
            'x86_64': 'x86_64',
            'amd64': 'x86_64',
            'aarch64': 'aarch64',
            'arm64': 'aarch64',
            'armv7l': 'armv7',
        }

        target_arch = arch_mapping.get(arch)
        if not target_arch:
            logger.error(f"Unsupported architecture for zoxide: {arch}")
            return

        pattern = f"zoxide-{latest_version}-{target_arch}-unknown-linux-musl.tar.gz"

        download_url = None
        for asset in release_data.get("assets", []):
            if pattern in asset.get("name", ""):
                download_url = asset.get("browser_download_url")
                break

        if not download_url:
            logger.warning(f"No suitable zoxide package found for {target_arch}")
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            tar_file = os.path.join(tmpdir, "zoxide.tar.gz")

            response = requests.get(download_url, stream=True)
            response.raise_for_status()

            with open(tar_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info("Downloaded zoxide archive")

            import tarfile
            with tarfile.open(tar_file, 'r:gz') as tar:
                # Use data filter for Python 3.14+ compatibility
                # For older Python versions, extractall will ignore the filter parameter
                try:
                    tar.extractall(tmpdir, filter='data')
                except TypeError:
                    # Python < 3.12 doesn't support filter parameter
                    tar.extractall(tmpdir)

            zoxide_binary = os.path.join(tmpdir, "zoxide")
            if not os.path.exists(zoxide_binary):
                logger.error("zoxide binary not found in archive")
                return

            target_binary = os.path.join(local_bin, "zoxide")
            run_command(f"cp {zoxide_binary} {target_binary}")
            run_command(f"chmod +x {target_binary}")

            logger.info(f"zoxide installed to {target_binary}")

            shell = get_current_shell()
            if shell == 'fish':
                fish_config = os.path.join(home, ".config", "fish", "config.fish")
                if os.path.exists(fish_config):
                    with open(fish_config, "r") as f:
                        content = f.read()
                    if "zoxide init fish" not in content:
                        with open(fish_config, "a") as f:
                            f.write("\n# Initialize zoxide\nif type -q zoxide\n    zoxide init fish | source\nend\n")
                        logger.info("Added zoxide initialization to config.fish")
            else:
                zshrc = os.path.join(home, ".zshrc")
                if os.path.exists(zshrc):
                    with open(zshrc, "a") as f:
                        f.write('\n# Initialize zoxide\neval "$(zoxide init zsh)"\n')
                    logger.info("Added zoxide initialization to .zshrc")

            ensure_path_in_shell_config()

        logger.info("zoxide installation completed successfully")

    except Exception as e:
        logger.error(f"Error installing zoxide: {e}")

def is_lazygit_installed() -> Tuple[bool, Optional[str]]:
    """Check if lazygit is installed and get its version."""
    try:
        result = subprocess.run(
            ["lazygit", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )
        if result.returncode == 0:
            output = result.stdout.strip()
            # Extract version from output like "version=0.40.2"
            match = re.search(r'version=(\S+)', output)
            if match:
                version = match.group(1)
                logger.info(f"lazygit version {version} found")
                return True, version
        return False, None
    except FileNotFoundError:
        logger.info("lazygit not found")
        return False, None

def install_lazygit_if_needed() -> None:
    """Install or update lazygit if needed."""
    try:
        is_installed, current_version = is_lazygit_installed()

        release_data = get_latest_github_release("jesseduffield/lazygit")
        if not release_data:
            if is_installed:
                logger.info(f"lazygit {current_version} is installed, cannot check for updates")
            else:
                logger.warning("Could not fetch lazygit release information")
            return

        latest_version = release_data.get("tag_name", "").lstrip("v")

        if is_installed:
            if current_version == latest_version:
                logger.info(f"lazygit {current_version} is up to date")
                return
            logger.info(f"Updating lazygit from {current_version} to {latest_version}")
        else:
            logger.info(f"Installing lazygit {latest_version}")

        # Detect architecture
        arch = platform.machine().lower()
        arch_mapping = {
            'x86_64': 'x86_64',
            'amd64': 'x86_64',
            'aarch64': 'arm64',
            'arm64': 'arm64',
        }

        target_arch = arch_mapping.get(arch)
        if not target_arch:
            logger.error(f"Unsupported architecture for lazygit: {arch}")
            return

        pattern = f"lazygit_{latest_version}_Linux_{target_arch}.tar.gz"
        download_url = None
        for asset in release_data.get("assets", []):
            if pattern in asset.get("name", ""):
                download_url = asset.get("browser_download_url")
                break

        if not download_url:
            logger.warning(f"No suitable lazygit package found for {target_arch}")
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            tar_file = os.path.join(tmpdir, "lazygit.tar.gz")

            response = requests.get(download_url, stream=True)
            response.raise_for_status()

            with open(tar_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info("Downloaded lazygit archive")

            import tarfile
            with tarfile.open(tar_file, 'r:gz') as tar:
                try:
                    tar.extractall(tmpdir, filter='data')
                except TypeError:
                    tar.extractall(tmpdir)

            lazygit_binary = os.path.join(tmpdir, "lazygit")
            if not os.path.exists(lazygit_binary):
                logger.error("lazygit binary not found in archive")
                return

            # Install to /usr/local/bin (requires sudo) or ~/.local/bin
            try:
                run_command(f"sudo install {lazygit_binary} /usr/local/bin/lazygit")
                logger.info("lazygit installed to /usr/local/bin/lazygit")
            except Exception:
                # Fallback to ~/.local/bin if sudo fails
                home = os.path.expanduser("~")
                local_bin = os.path.join(home, ".local", "bin")
                os.makedirs(local_bin, exist_ok=True)

                target_binary = os.path.join(local_bin, "lazygit")
                run_command(f"cp {lazygit_binary} {target_binary}")
                run_command(f"chmod +x {target_binary}")
                logger.info(f"lazygit installed to {target_binary}")
                ensure_path_in_shell_config()

        logger.info("lazygit installation completed successfully")

    except Exception as e:
        logger.error(f"Error installing lazygit: {e}")

def is_nodejs_installed() -> Tuple[bool, Optional[str]]:
    """Check if Node.js is installed and get its version."""
    try:
        result = subprocess.run(
            ["node", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )
        if result.returncode == 0:
            version = result.stdout.strip().lstrip("v")
            logger.info(f"Node.js version {version} found")
            return True, version
        return False, None
    except FileNotFoundError:
        logger.info("Node.js not found")
        return False, None

def install_nodejs_if_needed(node_major: int = 20) -> None:
    """Install Node.js from NodeSource repository."""
    try:
        is_installed, current_version = is_nodejs_installed()

        if is_installed and current_version:
            major_version = int(current_version.split('.')[0])
            if major_version >= node_major:
                logger.info(f"Node.js {current_version} is already installed (>= {node_major}.x)")
                return
            logger.info(f"Updating Node.js from {current_version} to {node_major}.x")
        else:
            logger.info(f"Installing Node.js {node_major}.x from NodeSource")

        # Install required packages
        for package in ["ca-certificates", "curl", "gnupg"]:
            if not is_package_installed(package):
                install_system_package(package)

        # Setup NodeSource repository
        logger.info("Setting up NodeSource repository...")

        # Create keyrings directory
        run_command("sudo mkdir -p /etc/apt/keyrings")

        # Download and add GPG key
        gpg_key_url = "https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key"
        gpg_key_path = "/etc/apt/keyrings/nodesource.gpg"

        gpg_download = subprocess.run(
            f"curl -fsSL {gpg_key_url} | sudo gpg --dearmor -o {gpg_key_path}",
            shell=True,
            capture_output=True,
            text=True
        )

        if gpg_download.returncode != 0:
            logger.error("Failed to download NodeSource GPG key")
            return

        # Add NodeSource repository
        sources_list = f'deb [signed-by={gpg_key_path}] https://deb.nodesource.com/node_{node_major}.x nodistro main'

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.list') as f:
            f.write(sources_list + '\n')
            temp_file = f.name

        run_command(f"sudo mv {temp_file} /etc/apt/sources.list.d/nodesource.list")

        # Update and install Node.js
        logger.info("Installing Node.js from NodeSource...")
        run_command("sudo apt-get update")
        install_system_package("nodejs")

        # Verify installation
        is_installed, version = is_nodejs_installed()
        if is_installed:
            logger.info(f"Node.js {version} installed successfully")
        else:
            logger.error("Node.js installation verification failed")

    except Exception as e:
        logger.error(f"Error installing Node.js: {e}")

def is_claude_cli_installed() -> Tuple[bool, Optional[str]]:
    """Check if Claude Code CLI is installed and get its version."""
    try:
        result = subprocess.run(
            ["claude", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            logger.info(f"Claude Code CLI version {version} found")
            return True, version
        return False, None
    except FileNotFoundError:
        logger.info("Claude Code CLI not found")
        return False, None

def install_claude_cli_if_needed() -> None:
    """Install Claude Code CLI via npm."""
    try:
        # First check if Node.js is installed
        is_node_installed, _node_version = is_nodejs_installed()
        if not is_node_installed:
            logger.warning("Node.js is required for Claude Code CLI installation")
            logger.info("Installing Node.js first...")
            install_nodejs_if_needed()

        is_installed, current_version = is_claude_cli_installed()

        if is_installed:
            logger.info(f"Claude Code CLI {current_version} is already installed")
            logger.info("Use 'npm update -g @anthropic-ai/claude-code' to update")
            return

        logger.info("Installing Claude Code CLI globally via npm...")

        try:
            run_command("sudo npm install -g @anthropic-ai/claude-code")
            logger.info("Claude Code CLI installed globally")
        except Exception:
            # Fallback to user installation if sudo fails
            logger.info("Trying user-level installation...")
            run_command("npm install -g @anthropic-ai/claude-code")
            logger.info("Claude Code CLI installed for current user")

        # Create Claude directory with proper permissions
        home = os.path.expanduser("~")
        claude_dir = os.path.join(home, ".claude")
        os.makedirs(claude_dir, exist_ok=True)
        logger.info(f"Created Claude directory: {claude_dir}")

        # Verify installation
        is_installed, version = is_claude_cli_installed()
        if is_installed:
            logger.info(f"Claude Code CLI {version} installed successfully")
        else:
            logger.warning("Claude Code CLI installation could not be verified")

    except Exception as e:
        logger.error(f"Error installing Claude Code CLI: {e}")

def is_pipx_installed() -> bool:
    """Check if pipx is installed."""
    try:
        result = subprocess.run(
            ["pipx", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False

def upgrade_pip() -> None:
    """Upgrade pip to the latest version."""
    try:
        logger.info("Upgrading pip...")
        _result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "pip"],
            capture_output=True,
            text=True,
            check=True
        )
        logger.info("pip upgraded successfully")
    except subprocess.CalledProcessError as e:
        # Check if it's a permission error
        error_output = (e.stderr or "").lower()
        if any(keyword in error_output for keyword in ["permission denied", "access denied", "externally-managed-environment"]):
            logger.info("pip upgrade skipped (requires elevated privileges or is externally managed)")
            logger.debug(f"pip upgrade error details: {e.stderr}")
        else:
            logger.warning(f"Failed to upgrade pip: {e}")
            if e.stderr:
                logger.debug(f"Error details: {e.stderr}")

def setup_environment() -> Tuple[str, str]:
    """Setup the basic environment."""
    home = os.path.expanduser("~")
    local_bin = os.path.join(home, ".local", "bin")

    os.makedirs(local_bin, exist_ok=True)

    if local_bin not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{local_bin}:{os.environ.get('PATH', '')}"

    return home, local_bin

def install_essential_packages() -> None:
    """Install essential system packages."""
    # Required packages - installation will fail if these are missing
    required_packages = [
        "python3-venv",
        "python3-pip",
        "git",
        "curl",
        "wget",
        "ca-certificates",
    ]

    # Optional packages - nice to have but not critical
    optional_packages = [
        "gnupg",
        "lsb-release",
        "apt-transport-https",
        "software-properties-common",
    ]

    logger.info("Installing essential packages...")

    # Install required packages
    for package in required_packages:
        if not is_package_installed(package):
            try:
                install_system_package(package)
            except Exception as e:
                logger.error(f"Failed to install required package {package}: {e}")
                raise
        else:
            logger.info(f"{package} is already installed")

    # Install optional packages
    for package in optional_packages:
        if not is_package_installed(package):
            try:
                install_system_package(package)
            except Exception as e:
                logger.info(f"Skipping optional package {package} (not available on this system)")
        else:
            logger.info(f"{package} is already installed")

def main() -> None:
    """Main function to execute the script."""
    try:
        print_header()

        # Setup environment
        _myhome, _local_bin = setup_environment()

        logger.info("=" * 50)
        logger.info("Starting system preparation...")
        logger.info("=" * 50)

        # Upgrade pip first
        upgrade_pip()

        # Install essential packages
        install_essential_packages()

        # Install pipx if needed
        if not is_pipx_installed():
            logger.info("Installing pipx...")
            install_system_package("pipx")
            run_command("pipx ensurepath")
            ensure_path_in_shell_config()
        else:
            logger.info("pipx is already installed")

        # Install essential tools
        logger.info("Installing essential development tools...")

        # Install fastfetch
        install_fastfetch_if_needed()

        # Install zoxide
        install_zoxide_if_needed()

        # Install lazygit
        install_lazygit_if_needed()

        # Install Node.js and Claude Code CLI
        logger.info("Installing Node.js and Claude Code CLI...")
        install_nodejs_if_needed(node_major=20)
        install_claude_cli_if_needed()

        # Ensure PATH is correctly set
        ensure_path_in_shell_config()

        logger.info("=" * 50)
        logger.info("System preparation completed successfully!")
        logger.info("=" * 50)

        shell = get_current_shell()
        if shell == 'fish':
            logger.info("Please restart your terminal or run: source ~/.config/fish/config.fish")
        else:
            logger.info("Please restart your terminal or run: source ~/.zshrc")

    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="System Preparation Utility")
    parser.add_argument("--clear-cache", action="store_true",
                       help="Clear all cached version information")
    parser.add_argument("--no-cache", action="store_true",
                       help="Disable cache for this run")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)

    if args.clear_cache:
        clear_cache()
        logger.info("Cache cleared successfully")
        sys.exit(0)

    if args.no_cache:
        get_cached_version.disabled = True

    main()
