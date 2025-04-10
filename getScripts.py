
# -*- coding: utf-8 -*-
# Script for organizing Docker servers
# Version 6.6.3
# Date 10.04.2025
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
from pathlib import Path
import sys
import logging
from typing import Tuple, Optional
from functools import wraps
import hashlib
import time
import platform
import re
import tempfile

latest_fastfetch_assets = None

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
SCRIPT_VERSION = "6.6.3"
SCRIPT_DATE = "10.04.2025"

def print_header() -> None:
    """Print a nicely formatted header with script version and date."""
    header = f"""
╔═════════════════════════════════════════════╗
║                                             ║
║      getScripts.py - Docker Server Utility  ║
║                                             ║
║      Version: {SCRIPT_VERSION}      Date: {SCRIPT_DATE}  ║
║                                             ║
╚═════════════════════════════════════════════╝
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

def is_zoxide_installed() -> Tuple[bool, Optional[str]]:
    """Check if zoxide is installed and get its version.
    
    Returns:
        Tuple[bool, Optional[str]]: Installation status and version if installed
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
                version = parts[1]
                logger.info(f"zoxide version {version} found")
                return True, version
    except FileNotFoundError:
        # Try checking in /root/.local/bin directly
        local_zoxide = "/root/.local/bin/zoxide"
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
                        logger.info(f"zoxide version {version} found in /root/.local/bin")
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
        
        # Download with progress tracking
        total_size = int(response.headers.get('content-length', 0))
        block_size = 1024
        
        with open(filename, 'wb') as file:
            for data in response.iter_content(block_size):
                file.write(data)
        
        # Verify file exists and is not empty
        if not os.path.exists(filename) or os.path.getsize(filename) == 0:
            raise Exception("Downloaded file is empty or does not exist")
            
        logger.info(f"Successfully downloaded {filename}")
        
        # Install the package
        result = subprocess.run(
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

def get_latest_fastfetch_version() -> Optional[str]:
    """Get the latest version of fastfetch from GitHub releases."""
    try:
        response = requests.get("https://api.github.com/repos/fastfetch-cli/fastfetch/releases/latest")
        if response.status_code == 200:
            data = response.json()
            version = data["tag_name"].lstrip('v')
            logger.info(f"Found latest FastFetch version: {version}")
            # Also store the assets for later use
            global latest_fastfetch_assets
            latest_fastfetch_assets = data["assets"]
            return version
        logger.error(f"Failed to get latest fastfetch version. Status code: {response.status_code}")
    except Exception as e:
        logger.error(f"Error fetching latest fastfetch version: {str(e)}")
    return None

def get_fastfetch_download_url(version: str, os_id: str) -> Optional[str]:
    """Get the appropriate download URL for fastfetch based on OS."""
    try:
        global latest_fastfetch_assets
        if not latest_fastfetch_assets:
            logger.error("No release assets found")
            return None

        if os_id == "ubuntu" or os_id == "debian":
            arch = "amd64" if platform.machine() == "x86_64" else "arm64"
            target_package = f"fastfetch-linux-{arch}.deb"
            
            # Log available assets for debugging
            logger.info("Available FastFetch packages:")
            for asset in latest_fastfetch_assets:
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
        latest_version = get_latest_fastfetch_version()
        if not latest_version:
            logger.error("Could not determine latest fastfetch version")
            return

        # Check if update is needed
        if installed and current_version == latest_version:
            logger.info(f"Fastfetch is already at the latest version ({latest_version})")
            return

        # Get download URL
        download_url = get_fastfetch_download_url(latest_version, os_id)
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

def install_zoxide_if_needed(desired_version: str = "0.9.6") -> None:
    """Install zoxide if it's not already installed or if the version is outdated."""
    installed, version = is_zoxide_installed()

    if installed:
        if version == desired_version:
            logger.info(f"zoxide version {desired_version} is already installed.")
            # Ensure PATH is set correctly
            local_bin = "/root/.local/bin"
            if local_bin not in os.environ.get("PATH", ""):
                logger.info(f"Adding {local_bin} to PATH...")
                os.environ["PATH"] = f"{local_bin}:{os.environ.get('PATH', '')}"
                # Add to .zshrc if it exists
                zshrc = "/root/.zshrc"
                if os.path.exists(zshrc):
                    with open(zshrc, "a") as f:
                        f.write(f'\nexport PATH="{local_bin}:$PATH"\n')
            return
        else:
            logger.info(f"zoxide version {version} is installed, but version {desired_version} is required.")
    else:
        logger.info("zoxide is not installed.")

    logger.info(f"Downloading zoxide version {desired_version}...")
    
    # Installation using curl and bash with proper shell execution
    install_cmd = "curl -sS https://raw.githubusercontent.com/ajeetdsouza/zoxide/main/install.sh | bash"
    run_command(install_cmd, shell=True, check=True)
    
    logger.info(f"zoxide version {desired_version} was successfully installed.")

def ensure_directory_exists(directory: str) -> None:
    """Ensure a directory exists, creating it if necessary."""
    os.makedirs(directory, exist_ok=True)
    logger.info(f"Directory '{directory}' was created or already exists.")

def run_command(command: str, check: bool = False, shell: bool = False, capture_output: bool = False) -> None:
    """Run a shell command with optional error checking."""
    try:
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
        
        if shell:
            logger.debug(f"Running shell command: {command}")
            result = subprocess.run(command, shell=True, check=check, capture_output=capture_output)
        else:
            logger.debug(f"Running command: {command}")
            result = subprocess.run(command.split(), check=check, capture_output=capture_output)
        
        if result.returncode != 0:
            logger.warning(f"Command returned non-zero exit code: {result.returncode}")
            if capture_output and result.stderr:
                logger.warning(f"Error output: {result.stderr.decode('utf-8', errors='replace')}")
        
        return result
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed with code {e.returncode}: {e}")
        if e.stderr:
            logger.error(f"Error output: {e.stderr.decode('utf-8', errors='replace')}")
        if check:
            raise
    except Exception as e:
        logger.error(f"Error running command {command}: {e}")
        if check:
            raise

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

def upgrade_pip_package(package_name: str) -> None:
    """Upgrade a pip package to the latest version."""
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
    """Install a system package with version checking."""
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

    # Install package
    logger.info(f"Installing {package}{f' version {version}' if version else ''}")
    if version:
        run_command(f"sudo apt install -y {package}={version}")
    else:
        run_command(f"sudo apt install -y {package}")

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

def install_or_update_bat():
    """Install or update bat package"""
    try:
        if not check_bat_version():
            logger.info("Installing/updating bat...")
            run_command("sudo apt update")
            run_command("sudo apt install -y bat")
            
            # Verify installation
            if not check_bat_version():
                raise RuntimeError("Failed to install/update bat")
            
            logger.info("bat installation/update completed")
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
                run_command("sudo apt update")
                run_command("sudo apt install -y zstd")
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
    try:
        # First try 7zz (new version)
        result = subprocess.run(['7zz', '--help'], capture_output=True, text=True)
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
        # First check if the package is installed via dpkg
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
    """Install or update 7-Zip package"""
    try:
        # First check if p7zip-full is installed and remove it if needed
        if is_package_installed("p7zip-full"):
            logger.info("Removing old p7zip-full package...")
            run_command("sudo apt remove -y p7zip-full")
            
        # Now check if the new 7zip needs to be installed or updated
        if not check_7zip_version():
            logger.info("Installing/updating 7-Zip...")
            run_command("sudo apt update")
            run_command("sudo apt install -y 7zip")
            
            # Verify installation
            if not check_7zip_version():
                raise RuntimeError("Failed to install/update 7-Zip")
            
            logger.info("7-Zip installation/update completed")
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

def get_latest_oxker_version() -> Optional[str]:
    """Get the latest version of oxker from GitHub releases.
    
    Returns:
        Optional[str]: Latest version string if available, None otherwise
    """
    try:
        response = requests.get("https://api.github.com/repos/mrjackwills/oxker/releases/latest")
        if response.status_code == 200:
            data = response.json()
            version = data["tag_name"].lstrip('v')
            logger.info(f"Found latest oxker version: {version}")
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

def check_tilde_installed() -> bool:
    """Check if tilde is installed.
    
    Returns:
        bool: True if tilde is installed, False otherwise
    """
    try:
        result = subprocess.run(['which', 'tilde'], capture_output=True, text=True)
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Error checking tilde installation: {e}")
        return False

def get_tilde_version() -> Optional[str]:
    """Get installed tilde version.
    
    Returns:
        Optional[str]: Version string if installed, None otherwise
    """
    try:
        result = subprocess.run(['tilde', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            # The output might be like: "tilde version X.Y.Z"
            version_line = result.stdout.strip()
            match = re.search(r'(\d+\.\d+\.\d+)', version_line)
            if match:
                return match.group(1)
    except Exception as e:
        logger.error(f"Error getting tilde version: {e}")
    return None

def install_or_update_tilde() -> None:
    """Install or update tilde using apt."""
    try:
        # Check current version if installed
        installed = check_tilde_installed()
        current_version = get_tilde_version() if installed else None
        logger.info(f"Current tilde version: {current_version if installed else 'not installed'}")
        
        # Install or update
        if not installed:
            logger.info("Installing tilde...")
            run_command("sudo apt update")
            run_command("sudo apt install -y tilde")
            
            # Verify installation
            new_version = get_tilde_version()
            if new_version:
                logger.info(f"tilde {new_version} has been successfully installed")
            else:
                raise RuntimeError("Failed to verify tilde installation")
        else:
            logger.info("Checking for tilde updates...")
            run_command("sudo apt update")
            run_command("sudo apt install --only-upgrade -y tilde")
            
            # Verify update
            new_version = get_tilde_version()
            if new_version != current_version:
                logger.info(f"tilde updated from {current_version} to {new_version}")
            else:
                logger.info(f"tilde is already at the latest version ({current_version})")
    except Exception as e:
        logger.error(f"Error installing/updating tilde: {str(e)}")
        raise

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

def main() -> None:
    """Main function to execute the script"""
    original_dir = os.getcwd()
    
    try:
        # Display header at start of execution
        print_header()
        
        # Check if running on Debian/Ubuntu
        if not is_debian_or_ubuntu():
            logger.error("This script is only supported on Debian and Ubuntu systems")
            sys.exit(1)

        # First, upgrade pip if needed
        upgrade_pip()

        global_server_version = '2025'
        _myhome = os.path.expanduser('~')
        
        # Ensure .local/bin is in PATH
        local_bin = os.path.join(_myhome, ".local", "bin")
        ensure_directory_exists(local_bin)
        ensure_path_in_zshrc()
        
        # Make sure we have a valid directory before continuing
        try:
            config_directory = os.path.join(_myhome, ".config", "fastfetch")
            ensure_directory_exists(config_directory)
        except Exception as e:
            logger.error(f"Error creating config directory: {e}")
            # Go to home directory as a safe fallback
            os.chdir(_myhome)

        run_command("sudo timedatectl set-timezone Europe/Berlin", check=True)

        # Use absolute paths to avoid directory issues
        myodoo_docker = os.path.join(_myhome, "myodoo-docker")
        
        # Make sure we can access the target directory
        if not os.path.exists(myodoo_docker):
            logger.error(f"Directory {myodoo_docker} does not exist")
            sys.exit(1)
            
        try:
            os.chdir(myodoo_docker)
        except Exception as e:
            logger.error(f"Cannot change to directory {myodoo_docker}: {e}")
            sys.exit(1)

        # Check current branch and switch if needed
        current_branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
        if current_branch != global_server_version:
            logger.info(f"Switching to branch {global_server_version}")
            run_command(f"git checkout {global_server_version}")

        # Configure git pull
        run_command("git config pull.ff only", capture_output=True)

        # Check for updates
        before_pull = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        run_command("git pull", capture_output=True)
        after_pull = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        
        if before_pull != after_pull:
            logger.info("Repository updated, new changes downloaded")
            # Show what changed
            run_command("git --no-pager log --oneline --no-decorate HEAD@{1}..HEAD")

        run_command("find . -name '*.pyc' -type f -delete")

        # Copy configuration files
        source_zshrc = os.path.join(myodoo_docker, ".zshrc")
        target_zshrc = os.path.join(_myhome, ".zshrc")
        if os.path.exists(source_zshrc):
            # Backup existing .zshrc if it exists
            if os.path.exists(target_zshrc):
                backup_path = f"{target_zshrc}.bak"
                logger.info(f"Backing up existing .zshrc to {backup_path}")
                run_command(f"cp {target_zshrc} {backup_path}")
            
            logger.info(f"Copying .zshrc from {source_zshrc} to {target_zshrc}")
            run_command(f"cp {source_zshrc} {target_zshrc}")
            
            # Make sure ~/.local/bin is in PATH in the new .zshrc
            ensure_path_in_zshrc()

        source_fastfetch = os.path.join(myodoo_docker, "scripts", "fastfetch", "config.jsonc")
        target_fastfetch = os.path.join(_myhome, ".config", "fastfetch", "config.jsonc")
        if os.path.exists(source_fastfetch):
            run_command(f"cp {source_fastfetch} {target_fastfetch}")
        
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
        
        # Copy scripts to home directory
        for script in scripts:
            source = os.path.join(myodoo_docker, 
                                "scripts" if script != "getScripts.py" else "", 
                                script)
            target = os.path.join(_myhome, script)
            if os.path.exists(source):
                run_command(f"cp {source} {target}")

        os.chdir(_myhome)

        # Check for nginx-set-conf-equitania and replace with nginx-set-conf if needed
        if is_pip_package_installed("nginx-set-conf-equitania"):
            print("Removing nginx-set-conf-equitania...")
            uninstall_pip_package("nginx-set-conf-equitania")

        # Check for odoo-fast-report-mapper-equitania 
        if is_pip_package_installed("odoo-fast-report-mapper-equitania"):
            print("Removing odoo-fast-report-mapper-equitania...")
            uninstall_pip_package("odoo-fast-report-mapper-equitania")

        # Read package versions from packages.txt
        package_info = read_package_versions(os.path.join(_myhome, "myodoo-docker", "packages.txt"))

        # Install required system packages for Python virtual environments
        if not is_package_installed("python3-venv"):
            logger.info("Installing python3-venv...")
            run_command("sudo apt update")
            run_command("sudo apt install -y python3-venv")
        else:
            logger.info("python3-venv is already installed")

        # Check if pipx is installed
        if not is_pipx_installed():
            logger.info("Installing pipx...")
            run_command("sudo apt install -y pipx")
            run_command("pipx ensurepath")
            
            # Add pipx to PATH and reload environment
            pipx_bin = "/root/.local/bin"
            os.environ["PATH"] = f"{pipx_bin}:{os.environ.get('PATH', '')}"
            # Ensure PATH is set in .zshrc
            ensure_path_in_zshrc()

        # Install specific versions of packages with pipx
        if is_pipx_installed():
            for package, version in package_info["pipx"].items():
                install_specific_pipx_package(package, version)
        else:
            logger.error("pipx is not installed. Please install pipx first.")
            
        # Upgrade pip packages
        for package in package_info["pip"]:
            upgrade_pip_package(package)

        install_or_update_zstd()
        install_or_update_bat()
        install_or_update_7zip()
        
        # Install system packages if they're not already installed
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
                install_system_package(package)
        
        # Install oxker if not already installed
        install_or_update_oxker()
        
        # Install tilde if not already installed
        install_or_update_tilde()

        # At the end, before reloading zsh configuration
        logger.info("Reloading shell configuration...")
        try:
            # Make sure PATH is updated in current process
            if local_bin not in os.environ.get("PATH", ""):
                os.environ["PATH"] = f"{local_bin}:{os.environ.get('PATH', '')}"
                
            # Use absolute paths in the command
            zoxide_path = os.path.join(_myhome, ".local", "bin", "zoxide")
            
            # First check if the file exists
            if os.path.exists(zoxide_path):
                run_command(f"/usr/bin/zsh -c 'source <({zoxide_path} init zsh)'", shell=True)
            else:
                # Try using PATH
                run_command("/usr/bin/zsh -c 'hash -r && source <(zoxide init zsh)'", shell=True)
                
            # Add a note about new sessions
            logger.info("For the PATH changes to take effect in new shells, you may need to restart your terminal or run 'source ~/.zshrc'")
            
        except Exception as e:
            logger.error(f"Error reloading shell configuration: {e}")
        
        # Return to original directory
        try:
            os.chdir(original_dir)
        except FileNotFoundError:
            # If original directory doesn't exist anymore, go to home
            os.chdir(_myhome)
            
    except Exception as e:
        logger.error(f"An error occurred in main: {str(e)}")
        # Make sure we're in a valid directory
        try:
            os.getcwd()
        except FileNotFoundError:
            os.chdir(os.path.expanduser("~"))
        sys.exit(1)

if __name__ == "__main__":
    main()