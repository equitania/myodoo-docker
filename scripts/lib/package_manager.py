# -*- coding: utf-8 -*-
"""
Package management utilities for getScripts.py

Handles pip/pipx package management.
"""

import os
import subprocess
import requests
from typing import Optional, Dict, Any, List

from .logging_config import get_logger
from .system_utils import run_command, is_package_installed, install_system_package
from .cache import get_cached_version, cache_version_info


def ensure_pip() -> bool:
    """
    Ensure pip is installed and available.

    Returns:
        bool: True if pip is available
    """
    logger = get_logger()

    try:
        result = subprocess.run(
            ["pip3", "--version"],
            capture_output=True,
            check=False
        )
        if result.returncode == 0:
            return True

        logger.info("pip not found, installing...")
        install_system_package("python3-pip")
        return True
    except Exception as e:
        logger.error(f"Failed to ensure pip: {e}")
        return False


def is_pipx_installed() -> bool:
    """
    Check if pipx is installed.

    Returns:
        bool: True if pipx is installed
    """
    try:
        result = subprocess.run(
            ["pipx", "--version"],
            capture_output=True,
            check=False
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def ensure_pipx() -> bool:
    """
    Ensure pipx is installed and available.

    Returns:
        bool: True if pipx is available
    """
    logger = get_logger()

    if is_pipx_installed():
        return True

    logger.info("Installing pipx...")
    try:
        install_system_package("pipx")
        run_command("pipx ensurepath", check=True)
        return True
    except Exception as e:
        logger.error(f"Failed to install pipx: {e}")
        return False


def is_pip_package_installed(package_name: str) -> bool:
    """
    Check if a pip package is installed.

    Args:
        package_name: Name of the package

    Returns:
        bool: True if installed
    """
    try:
        result = subprocess.run(
            ["pip3", "show", package_name],
            capture_output=True,
            check=False
        )
        return result.returncode == 0
    except Exception:
        return False


def uninstall_pip_package(package_name: str) -> bool:
    """
    Uninstall a pip package.

    Args:
        package_name: Name of the package

    Returns:
        bool: True if uninstalled successfully
    """
    logger = get_logger()

    try:
        run_command(f"pip3 uninstall -y {package_name}", check=True)
        logger.info(f"Uninstalled {package_name}")
        return True
    except Exception as e:
        logger.error(f"Failed to uninstall {package_name}: {e}")
        return False


def get_latest_pypi_version(package_name: str) -> Optional[str]:
    """
    Get the latest version of a package from PyPI.

    Args:
        package_name: Name of the package

    Returns:
        Optional[str]: Latest version if available
    """
    logger = get_logger()

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

            cache_version_info(cache_key, {"version": latest_version})
            return latest_version
        logger.error(f"Failed to get latest {package_name} version. Status code: {response.status_code}")
    except Exception as e:
        logger.error(f"Error fetching latest {package_name} version from PyPI: {str(e)}")
    return None


def get_installed_pipx_version(package_name: str) -> Optional[str]:
    """
    Get the installed version of a pipx package.

    Args:
        package_name: Name of the package

    Returns:
        Optional[str]: Installed version if available
    """
    try:
        result = subprocess.run(
            ["pipx", "list", "--short"],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if package_name in line:
                    # Format: "package-name 1.2.3"
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        return parts[1]
        return None
    except Exception:
        return None


def install_or_update_pipx_package(package_name: str, version: Optional[str] = None) -> bool:
    """
    Install or update a pipx package.

    Args:
        package_name: Name of the package
        version: Specific version to install (optional)

    Returns:
        bool: True if successful
    """
    logger = get_logger()

    if not is_pipx_installed():
        if not ensure_pipx():
            return False

    installed_version = get_installed_pipx_version(package_name)
    pkg_spec = f"{package_name}=={version}" if version else package_name

    try:
        if installed_version:
            if version and installed_version != version:
                logger.info(f"Upgrading {package_name} from {installed_version} to {version}")
                run_command(f"pipx upgrade {package_name}", check=True)
            else:
                logger.info(f"{package_name} {installed_version} is already installed")
        else:
            logger.info(f"Installing {package_name}...")
            run_command(f"pipx install {pkg_spec}", check=True)
        return True
    except Exception as e:
        logger.error(f"Failed to install/update {package_name}: {e}")
        return False


def install_or_update_nginx_set_conf() -> bool:
    """
    Install or update nginx-set-conf package.

    Returns:
        bool: True if successful
    """
    return install_or_update_pipx_package("nginx-set-conf")


def install_or_update_odoo_fast_report_mapper() -> bool:
    """
    Install or update odoo-fast-report-mapper package.

    Returns:
        bool: True if successful
    """
    return install_or_update_pipx_package("odoo-fast-report-mapper")


def read_package_versions(packages_file: str) -> Dict[str, Any]:
    """
    Read package versions from packages.txt file.

    Args:
        packages_file: Path to packages.txt

    Returns:
        Dict[str, Any]: Package configuration
    """
    logger = get_logger()

    package_info = {
        "pip": [],
        "pipx": {},
        "apt": []
    }

    try:
        with open(packages_file, 'r') as f:
            current_section = None
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                if line.startswith('[') and line.endswith(']'):
                    current_section = line[1:-1].lower()
                    continue

                if current_section == 'pip':
                    package_info['pip'].append(line)
                elif current_section == 'pipx':
                    if '==' in line:
                        name, version = line.split('==')
                        package_info['pipx'][name.strip()] = version.strip()
                    else:
                        package_info['pipx'][line] = None
                elif current_section == 'apt':
                    package_info['apt'].append(line)

        return package_info
    except Exception as e:
        logger.error(f"Error reading packages.txt: {e}")
        return package_info


def install_packages(package_info: Dict[str, Any]) -> None:
    """
    Install all required packages.

    Args:
        package_info: Package configuration from read_package_versions()
    """
    logger = get_logger()

    # Install required system packages for Python virtual environments
    if not is_package_installed("python3-venv"):
        logger.info("Installing python3-venv...")
        install_system_package("python3-venv")

    # Check if pipx is installed
    if not is_pipx_installed():
        logger.info("Installing pipx...")
        install_system_package("pipx")
        run_command("pipx ensurepath")

    # Install or update nginx-set-conf
    install_or_update_nginx_set_conf()

    # Install specific versions of packages with pipx
    if is_pipx_installed():
        for package, version in package_info.get("pipx", {}).items():
            if package != "nginx-set-conf":
                install_or_update_pipx_package(package, version)
