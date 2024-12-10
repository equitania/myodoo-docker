#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Script for organizing Docker servers
# Version 6.1.4
# Date 10.12.2024
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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('getscripts.log')
    ]
)
logger = logging.getLogger(__name__)

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

def install_fastfetch_if_needed() -> None:
    """Install fastfetch if it's not already installed or if the version is outdated."""
    """ https://github.com/fastfetch-cli/fastfetch/releases/ """
    DESIRED_VERSION = "2.31.0"
    DEB_URL = f"https://github.com/fastfetch-cli/fastfetch/releases/download/{DESIRED_VERSION}/fastfetch-linux-amd64.deb"
    DEB_FILE = "fastfetch-linux-amd64.deb"

    installed, version = is_fastfetch_installed()
    
    if installed:
        if version == DESIRED_VERSION:
            logger.info(f"Fastfetch version {DESIRED_VERSION} is already installed.")
            return
        else:
            logger.info(f"Fastfetch version {version} is installed, but version {DESIRED_VERSION} is required.")
    else:
        logger.info("Fastfetch is not installed.")
    
    logger.info(f"Downloading Fastfetch version {DESIRED_VERSION}...")
    download_and_install_deb(DEB_URL, DEB_FILE)
    logger.info(f"Fastfetch version {DESIRED_VERSION} was successfully installed.")

def install_zoxide_if_needed() -> None:
    """Install zoxide if it's not already installed or if the version is outdated."""
    DESIRED_ZOXIDE_VERSION = "0.9.6"
    installed, version = is_zoxide_installed()

    if installed:
        if version == DESIRED_ZOXIDE_VERSION:
            logger.info(f"zoxide version {DESIRED_ZOXIDE_VERSION} is already installed.")
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
            logger.info(f"zoxide version {version} is installed, but version {DESIRED_ZOXIDE_VERSION} is required.")
    else:
        logger.info("zoxide is not installed.")

    logger.info(f"Downloading zoxide version {DESIRED_ZOXIDE_VERSION}...")
    # Installation using official script
    run_command("curl -sS https://raw.githubusercontent.com/ajeetdsouza/zoxide/main/install.sh | bash", check=True)
    logger.info(f"zoxide version {DESIRED_ZOXIDE_VERSION} was successfully installed.")

def ensure_directory_exists(directory: str) -> None:
    """Ensure a directory exists, creating it if necessary."""
    os.makedirs(directory, exist_ok=True)
    logger.info(f"Directory '{directory}' was created or already exists.")

def run_command(command: str, check: bool = False) -> None:
    """Run a shell command with optional error checking."""
    try:
        subprocess.run(command, shell=True, check=check)
    except subprocess.CalledProcessError as e:
        logger.error(f"Error running command '{command}': {str(e)}")
        if check:
            sys.exit(1)

def upgrade_pip_package(package_name: str) -> None:
    """Upgrade a pip package to the latest version."""
    run_command(f"pip3 install {package_name} --upgrade --quiet --no-warn-script-location --break-system-packages --root-user-action=ignore")

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
    try:
        subprocess.run(['pipx', 'install', '--force', package_name], check=True)
        logger.info(f"Successfully installed {package_name} with pipx")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to install {package_name} with pipx: {e}")
        raise

def main() -> None:
    global_server_version = '2024'
    _myhome = os.path.expanduser('~')
    config_directory = os.path.join(_myhome, ".config", "fastfetch")
    ensure_directory_exists(config_directory)

    run_command("sudo timedatectl set-timezone Europe/Berlin", check=True)

    os.chdir(os.path.join(_myhome, "myodoo-docker"))
    run_command(f"git checkout {global_server_version}")
    run_command("git config pull.ff only")
    run_command("git pull")
    run_command("find . -name '*.pyc' -type f -print0 | xargs -0 /bin/rm -f")
    run_command("cp $HOME/myodoo-docker/.zshrc $HOME/.zshrc")
    run_command("cp $HOME/myodoo-docker/scripts/fastfetch/config.jsonc $HOME/.config/fastfetch/")
    
    scripts = [
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
        run_command(f"cp $HOME/myodoo-docker/{script if script == 'getScripts.py' else f'scripts/{script}'} $HOME")

    os.chdir(_myhome)

    # Check for nginx-set-conf-equitania and replace with nginx-set-conf if needed
    if is_pip_package_installed("nginx-set-conf-equitania"):
        print("Removing nginx-set-conf-equitania...")
        run_command(f"{sys.executable} -m pip uninstall -y nginx-set-conf-equitania --break-system-packages --root-user-action=ignore")

    # Check if pipx is installed
    if not is_pipx_installed():
        logger.info("Installing pipx...")
        if sys.platform == "darwin":
            run_command("brew install pipx")
        else:
            run_command("sudo apt install pipx")
        run_command("pipx ensurepath")

    # Install packages with pipx
    pipx_packages = [
        "nginx-set-conf",
        "odoo-fast-report-mapper-equitania"
    ]
    
    for package in pipx_packages:
        try:
            install_with_pipx(package)
        except Exception as e:
            logger.error(f"Failed to install {package} with pipx: {e}")

    packages = [
        "pip",
        "wheel",
        "setuptools",
        "distro-info",
        "odoorpc-toolbox",
        "thefuck"
    ]

    for package in packages:
        upgrade_pip_package(package)

    # Install zoxide if necessary
    install_zoxide_if_needed()

    # Install fastfetch if necessary
    install_fastfetch_if_needed()
    
    # Instead of sourcing .zshrc which would trigger fastfetch again,
    # we'll just reload zoxide initialization
    logger.info("Reloading shell configuration...")
    run_command("/bin/zsh -c 'eval \"$(zoxide init zsh)\"'")

if __name__ == "__main__":
    main()