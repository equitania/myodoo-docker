# -*- coding: utf-8 -*-
"""
Package management utilities for getScripts.py

Handles pip/uv tool package management.
"""

import os
import subprocess
import requests
from typing import Optional, Dict, Any

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


def is_uv_installed() -> bool:
    """
    Check if uv is installed.

    Returns:
        bool: True if uv is installed
    """
    try:
        result = subprocess.run(
            ["uv", "--version"],
            capture_output=True,
            check=False
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def ensure_uv() -> bool:
    """
    Ensure uv is installed and up to date.
    Installs via curl if not present, then runs uv self update.

    Returns:
        bool: True if uv is available
    """
    logger = get_logger()

    if is_uv_installed():
        # Always update uv to latest version
        logger.info("Updating uv to latest version...")
        try:
            run_command("uv self update", check=True)
        except Exception as e:
            logger.warning(f"Failed to update uv: {e}")
        return True

    logger.info("Installing uv...")
    try:
        # Install from the official GitHub release tarball (replaces the
        # former `curl https://astral.sh/uv/install.sh | sh` pipe)
        import platform
        machine = platform.machine().lower()
        target = "aarch64-unknown-linux-gnu" if machine in ("aarch64", "arm64") else "x86_64-unknown-linux-gnu"
        tarball_url = f"https://github.com/astral-sh/uv/releases/latest/download/uv-{target}.tar.gz"
        tmp_tarball = "/tmp/uv.tar.gz"
        local_bin = os.path.expanduser("~/.local/bin")
        os.makedirs(local_bin, exist_ok=True)
        run_command(f"curl -fsSL {tarball_url} -o {tmp_tarball}", shell=True, check=True)
        run_command(
            f"tar -xzf {tmp_tarball} -C {local_bin} --strip-components=1 uv-{target}/uv uv-{target}/uvx",
            shell=True, check=True
        )
        run_command(f"chmod 755 {local_bin}/uv {local_bin}/uvx", shell=True, check=True)
        os.remove(tmp_tarball)
        # Ensure ~/.local/bin is in PATH for current session
        local_bin = os.path.expanduser("~/.local/bin")
        if local_bin not in os.environ.get("PATH", ""):
            os.environ["PATH"] = f"{local_bin}:{os.environ.get('PATH', '')}"
        # Also check ~/.cargo/bin (alternative uv install location)
        cargo_bin = os.path.expanduser("~/.cargo/bin")
        if cargo_bin not in os.environ.get("PATH", ""):
            os.environ["PATH"] = f"{cargo_bin}:{os.environ.get('PATH', '')}"
        return True
    except Exception as e:
        logger.error(f"Failed to install uv: {e}")
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


def get_installed_uv_tool_version(package_name: str) -> Optional[str]:
    """
    Get the installed version of a uv tool package.

    Args:
        package_name: Name of the package

    Returns:
        Optional[str]: Installed version if available
    """
    try:
        result = subprocess.run(
            ["uv", "tool", "list"],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                # uv tool list format: "package-name v1.2.3" or "package-name 1.2.3"
                if package_name in line:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        version = parts[1]
                        # Strip leading 'v' if present
                        if version.startswith('v'):
                            version = version[1:]
                        return version
        return None
    except Exception:
        return None


def install_or_update_uv_tool(package_name: str, version: Optional[str] = None) -> bool:
    """
    Install or update a uv tool package.

    Args:
        package_name: Name of the package
        version: Specific version to install (optional)

    Returns:
        bool: True if successful
    """
    logger = get_logger()

    if not is_uv_installed():
        if not ensure_uv():
            return False

    installed_version = get_installed_uv_tool_version(package_name)
    pkg_spec = f"{package_name}=={version}" if version else package_name

    try:
        if installed_version:
            if version and installed_version != version:
                logger.info(f"Reinstalling {package_name} from {installed_version} to {version}")
                run_command(f"uv tool install --force {pkg_spec}", check=True)
            elif not version:
                # Upgrade to latest
                logger.info(f"Upgrading {package_name}...")
                try:
                    run_command(f"uv tool upgrade {package_name}", check=True)
                except Exception:
                    # If upgrade fails (e.g., not installed via uv), force install
                    logger.info(f"Upgrade failed, force installing {package_name}...")
                    run_command(f"uv tool install --force {package_name}", check=True)
            else:
                logger.info(f"{package_name} {installed_version} is already installed")
        else:
            logger.info(f"Installing {package_name}...")
            run_command(f"uv tool install {pkg_spec}", check=True)
        return True
    except Exception as e:
        logger.error(f"Failed to install/update {package_name}: {e}")
        return False


def upgrade_all_uv_tools() -> bool:
    """
    Upgrade all installed uv tools to their latest versions.

    Returns:
        bool: True if successful
    """
    logger = get_logger()

    if not is_uv_installed():
        logger.warning("uv is not installed, skipping tool upgrade")
        return False

    try:
        logger.info("Upgrading all uv tools...")
        run_command("uv tool upgrade --all", check=True)
        return True
    except Exception as e:
        logger.warning(f"Failed to upgrade all uv tools: {e}")
        return False


def migrate_pipx_to_uv() -> bool:
    """
    Migrate from pipx to uv: uninstall pipx tools and remove pipx.
    Non-critical - logs warnings on failure.

    Returns:
        bool: True if migration completed (or pipx not present)
    """
    logger = get_logger()

    # Check if pipx is still installed
    try:
        result = subprocess.run(
            ["which", "pipx"],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode != 0:
            # pipx not installed, nothing to migrate
            return True
    except FileNotFoundError:
        return True

    logger.info("Migrating from pipx to uv: cleaning up pipx installation...")

    # Uninstall all pipx packages first
    try:
        result = subprocess.run(
            ["pipx", "list", "--short"],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().split('\n'):
                pkg = line.strip().split()[0] if line.strip() else None
                if pkg:
                    logger.info(f"Uninstalling pipx package: {pkg}")
                    try:
                        subprocess.run(["pipx", "uninstall", pkg], check=False, capture_output=True)
                    except Exception as e:
                        logger.warning(f"Failed to uninstall pipx package {pkg}: {e}")
    except Exception as e:
        logger.warning(f"Failed to list pipx packages: {e}")

    # Remove pipx via apt
    try:
        run_command("sudo apt remove -y pipx", check=True)
        logger.info("Successfully removed pipx")
    except Exception as e:
        logger.warning(f"Failed to remove pipx via apt: {e}")

    return True


def install_or_update_nginx_set_conf() -> bool:
    """
    Install or update nginx-set-conf package.

    Returns:
        bool: True if successful
    """
    return install_or_update_uv_tool("nginx-set-conf")


def install_or_update_odoo_fast_report_mapper() -> bool:
    """
    Install or update odoo-fast-report-mapper package.

    Returns:
        bool: True if successful
    """
    return install_or_update_uv_tool("odoo-fast-report-mapper")


def read_package_versions(packages_file: str) -> Dict[str, Any]:
    """
    Read package versions from packages.txt file.
    Supports both "# UV tool packages" and legacy "# PIPX packages" section headers.

    Args:
        packages_file: Path to packages.txt

    Returns:
        Dict[str, Any]: Package configuration
    """
    logger = get_logger()

    package_info = {
        "pip": [],
        "uv_tools": {},
        "apt": []
    }

    try:
        with open(packages_file, 'r') as f:
            current_section = None
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    # Detect section headers from comments
                    if "UV tool packages" in line or "PIPX packages" in line:
                        current_section = "uv_tools"
                    elif "PIP packages" in line:
                        current_section = "pip"
                    elif "System packages" in line:
                        current_section = "apt"
                    continue

                if line.startswith('[') and line.endswith(']'):
                    section_name = line[1:-1].lower()
                    if section_name in ('uv_tools', 'pipx'):
                        current_section = 'uv_tools'
                    else:
                        current_section = section_name
                    continue

                if current_section == 'pip':
                    package_info['pip'].append(line)
                elif current_section == 'uv_tools':
                    if '==' in line:
                        name, version = line.split('==')
                        package_info['uv_tools'][name.strip()] = version.strip()
                    else:
                        package_info['uv_tools'][line] = None
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

    # 1. Ensure uv is installed and up to date
    if not ensure_uv():
        logger.warning("uv installation failed, skipping uv tool installations")
    else:
        # 2. Upgrade all existing uv tools
        upgrade_all_uv_tools()

        # 3. Install or update nginx-set-conf
        install_or_update_nginx_set_conf()

        # 4. Install other uv tools from packages.txt
        for package, version in package_info.get("uv_tools", {}).items():
            if package != "nginx-set-conf":
                install_or_update_uv_tool(package, version)

        # 5. Migrate from pipx if still present
        migrate_pipx_to_uv()
