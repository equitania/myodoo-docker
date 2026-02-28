# -*- coding: utf-8 -*-
"""
Tool installation utilities for getScripts.py

Handles installation of 7zip, zoxide, starship, fastfetch, ctop.
"""

import os
import subprocess
import re
import tempfile
from typing import Optional, Tuple

from .logging_config import get_logger
from .system_utils import run_command, get_system_architecture, is_root_or_has_sudo
from .cache import get_cached_version, cache_version_info


def is_fastfetch_installed() -> Tuple[bool, Optional[str]]:
    """
    Check if fastfetch is installed and get its version.

    Returns:
        Tuple[bool, Optional[str]]: (is_installed, version)
    """
    logger = get_logger()

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


def install_fastfetch_if_needed() -> bool:
    """
    Install fastfetch if not installed.

    Returns:
        bool: True if fastfetch is available
    """
    logger = get_logger()

    installed, version = is_fastfetch_installed()
    if installed:
        logger.info(f"Fastfetch {version} is already installed")
        return True

    if not is_root_or_has_sudo():
        logger.warning("Cannot install fastfetch without sudo privileges")
        return False

    logger.info("Installing fastfetch...")
    try:
        run_command("sudo apt install -y fastfetch", check=True)
        installed, new_version = is_fastfetch_installed()
        if installed:
            logger.info(f"Fastfetch {new_version} installed successfully")
            return True
    except Exception as e:
        logger.error(f"Failed to install fastfetch: {e}")

    return False


def is_starship_installed() -> Tuple[bool, Optional[str]]:
    """
    Check if Starship prompt is installed and get its version.

    Returns:
        Tuple[bool, Optional[str]]: (is_installed, version)
    """
    logger = get_logger()

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
    """
    Install Starship prompt if not installed.

    Returns:
        bool: True if Starship is available
    """
    logger = get_logger()

    installed, current_version = is_starship_installed()

    if installed:
        logger.info(f"Starship {current_version} is already installed")
        return True

    logger.info("Installing Starship prompt...")
    try:
        run_command("curl -sS https://starship.rs/install.sh | sh -s -- -y", shell=True, check=True)

        installed, new_version = is_starship_installed()
        if installed:
            logger.info(f"Starship {new_version} installed successfully")
            return True
    except Exception as e:
        logger.error(f"Failed to install Starship: {e}")

    return False


def copy_starship_configuration(home_dir: str, myodoo_docker: str) -> bool:
    """
    Copy Starship configuration from repository.

    Args:
        home_dir: User's home directory
        myodoo_docker: Path to myodoo-docker repository

    Returns:
        bool: True if configuration copied successfully
    """
    logger = get_logger()
    import shutil

    try:
        source_starship = os.path.join(myodoo_docker, "scripts", "starship", "starship.toml")
        target_dir = os.path.join(home_dir, ".config")
        target_starship = os.path.join(target_dir, "starship.toml")

        if not os.path.exists(source_starship):
            logger.warning(f"Starship configuration not found: {source_starship}")
            return False

        os.makedirs(target_dir, exist_ok=True)

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


def normalize_zoxide_version(version: str) -> str:
    """
    Normalize zoxide version string for comparison.

    Args:
        version: Raw version string

    Returns:
        str: Normalized version (e.g., '0.4.3')
    """
    if not version:
        return ""
    clean_version = version.lstrip('v')
    if '-' in clean_version:
        clean_version = clean_version.split('-')[0]
    return clean_version


def is_zoxide_installed() -> Tuple[bool, Optional[str]]:
    """
    Check if zoxide is installed and get its version.

    Returns:
        Tuple[bool, Optional[str]]: (is_installed, version)
    """
    logger = get_logger()

    try:
        result = subprocess.run(
            ["zoxide", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )
        if result.returncode == 0:
            output = result.stdout.strip()
            # Output: "zoxide 0.9.7"
            parts = output.split()
            if len(parts) >= 2:
                version = normalize_zoxide_version(parts[1])
                logger.info(f"Zoxide version {version} found")
                return True, version
        return False, None
    except FileNotFoundError:
        logger.info("Zoxide not found")
        return False, None


def install_zoxide_if_needed() -> bool:
    """
    Install zoxide if not installed.

    Returns:
        bool: True if zoxide is available
    """
    logger = get_logger()

    installed, version = is_zoxide_installed()
    if installed:
        logger.info(f"Zoxide {version} is already installed")
        return True

    logger.info("Installing zoxide...")
    try:
        run_command("curl -sSfL https://raw.githubusercontent.com/ajeetdsouza/zoxide/main/install.sh | sh", shell=True, check=True)

        installed, new_version = is_zoxide_installed()
        if installed:
            logger.info(f"Zoxide {new_version} installed successfully")
            return True
    except Exception as e:
        logger.error(f"Failed to install zoxide: {e}")

    return False


def check_7zip_version() -> Optional[str]:
    """
    Check if 7-Zip is installed and get its version.

    Returns:
        Optional[str]: Version string if installed, None otherwise
    """
    logger = get_logger()

    try:
        result = subprocess.run(
            ["7zz", "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )
        if result.returncode == 0:
            # Extract version from output
            match = re.search(r'7-Zip.*?(\d+\.\d+)', result.stdout)
            if match:
                version = match.group(1)
                logger.info(f"7-Zip version {version} found")
                return version
        return None
    except FileNotFoundError:
        logger.info("7-Zip not found")
        return None


def install_update_7zip() -> bool:
    """
    Install or update 7-Zip to latest version.

    Returns:
        bool: True if 7-Zip is available
    """
    logger = get_logger()

    current_version = check_7zip_version()
    if current_version:
        logger.info(f"7-Zip {current_version} is already installed")
        return True

    if not is_root_or_has_sudo():
        logger.warning("Cannot install 7-Zip without sudo privileges")
        return False

    logger.info("Installing 7-Zip...")
    try:
        run_command("sudo apt install -y 7zip", check=True)
        new_version = check_7zip_version()
        if new_version:
            logger.info(f"7-Zip {new_version} installed successfully")
            return True
    except Exception as e:
        logger.error(f"Failed to install 7-Zip: {e}")

    return False


def check_ctop_installed() -> bool:
    """
    Check if ctop (eqms/ctop) is installed.

    Returns:
        bool: True if ctop is installed
    """
    try:
        result = subprocess.run(
            ["ctop", "-v"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def get_ctop_version() -> Optional[str]:
    """
    Get ctop version.

    Returns:
        Optional[str]: Version string if installed
    """
    try:
        result = subprocess.run(
            ["ctop", "-v"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )
        if result.returncode == 0:
            # Output: "ctop version 0.8.0, build abc123 go1.23"
            parts = result.stdout.strip().split()
            if len(parts) >= 3:
                return parts[2].rstrip(',')
        return None
    except FileNotFoundError:
        return None


def install_ctop() -> bool:
    """
    Install ctop (Docker TUI) from eqms/ctop.

    Returns:
        bool: True if installation successful
    """
    import shutil
    import platform as plat

    logger = get_logger()

    if check_ctop_installed():
        version = get_ctop_version()
        logger.info(f"ctop {version} is already installed")
        return True

    logger.info("Installing ctop...")
    try:
        home_dir = os.path.expanduser("~")
        local_bin = os.path.join(home_dir, ".local", "bin")
        os.makedirs(local_bin, exist_ok=True)

        os_name = plat.system().lower()  # linux or darwin
        if os_name not in ("linux", "darwin"):
            logger.warning(f"Unsupported OS for ctop: {os_name}")
            return False

        arch = get_system_architecture()
        if arch in ("x86_64", "amd64"):
            arch_name = "amd64"
        elif arch in ("aarch64", "arm64"):
            arch_name = "arm64"
        else:
            logger.warning(f"Unsupported architecture for ctop: {arch}")
            return False

        # Get latest version from GitHub API
        import requests
        resp = requests.get("https://api.github.com/repos/eqms/ctop/releases/latest")
        if resp.status_code != 200:
            logger.error(f"Failed to get latest ctop version: HTTP {resp.status_code}")
            return False
        version = resp.json()["tag_name"].lstrip('v')

        # Direct binary download (no tar.gz)
        binary_name = f"ctop-{version}-{os_name}-{arch_name}"
        download_url = f"https://github.com/eqms/ctop/releases/download/v{version}/{binary_name}"

        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name
            run_command(
                f"curl -sL -o {tmp_path} {download_url}",
                shell=True, check=True
            )

        dest_path = os.path.join(local_bin, "ctop")
        shutil.copy2(tmp_path, dest_path)
        os.chmod(dest_path, 0o755)
        os.unlink(tmp_path)

        if check_ctop_installed():
            version = get_ctop_version()
            logger.info(f"ctop {version} installed successfully")
            return True
    except Exception as e:
        logger.error(f"Failed to install ctop: {e}")

    return False
