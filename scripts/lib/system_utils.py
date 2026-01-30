# -*- coding: utf-8 -*-
"""
System utilities for getScripts.py

Provides OS detection, command execution, and general helper functions.
"""

import os
import subprocess
import platform
import time
import re
from functools import wraps
from typing import Optional, Tuple, List, Any

from .logging_config import get_logger


class CommandError(Exception):
    """Exception raised when a command fails."""
    pass


def retry_on_exception(retries: int = 3, delay: int = 1):
    """
    Decorator to retry functions on exception.

    Args:
        retries: Number of retry attempts
        delay: Delay between retries in seconds
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger = get_logger()
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


def run_command(
    command: str,
    shell: bool = False,
    check: bool = False,
    capture_output: bool = False,
    timeout: int = 300
) -> subprocess.CompletedProcess:
    """
    Execute a shell command with proper error handling.

    Args:
        command: Command string or list
        shell: Run command through shell
        check: Raise exception on non-zero return
        capture_output: Capture stdout/stderr
        timeout: Command timeout in seconds

    Returns:
        subprocess.CompletedProcess: Result of command execution

    Raises:
        CommandError: If check=True and command fails
    """
    logger = get_logger()
    logger.debug(f"Running command: {command}")

    try:
        if shell:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=capture_output,
                text=True,
                timeout=timeout
            )
        else:
            cmd_list = command.split() if isinstance(command, str) else command
            result = subprocess.run(
                cmd_list,
                capture_output=capture_output,
                text=True,
                timeout=timeout
            )

        if check and result.returncode != 0:
            error_msg = result.stderr if capture_output else f"Return code: {result.returncode}"
            raise CommandError(f"Command failed: {command}\n{error_msg}")

        return result
    except subprocess.TimeoutExpired as e:
        raise CommandError(f"Command timed out after {timeout}s: {command}") from e
    except FileNotFoundError as e:
        raise CommandError(f"Command not found: {command}") from e


def get_os_info() -> Tuple[str, str]:
    """
    Get operating system identification.

    Returns:
        Tuple[str, str]: (os_id, os_version) e.g., ('debian', '12')
    """
    logger = get_logger()

    try:
        with open("/etc/os-release") as f:
            content = f.read()

        os_id = ""
        os_version = ""

        for line in content.split('\n'):
            if line.startswith('ID='):
                os_id = line.split('=')[1].strip('"').lower()
            elif line.startswith('VERSION_ID='):
                os_version = line.split('=')[1].strip('"')

        logger.debug(f"Detected OS: {os_id} {os_version}")
        return os_id, os_version
    except Exception as e:
        logger.warning(f"Could not read OS info: {e}")
        return platform.system().lower(), ""


def is_root_or_has_sudo() -> bool:
    """
    Check if running as root or has sudo privileges.

    Returns:
        bool: True if root or sudo available
    """
    # Running as root
    if os.geteuid() == 0:
        return True

    # Check for sudo
    try:
        result = subprocess.run(
            ["sudo", "-n", "true"],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def ensure_directory_exists(path: str) -> None:
    """
    Ensure a directory exists, creating it if necessary.

    Args:
        path: Directory path to create
    """
    os.makedirs(path, exist_ok=True)


def is_debian_based() -> bool:
    """
    Check if the system is Debian-based (Debian, Ubuntu, etc.).

    Returns:
        bool: True if Debian-based
    """
    os_id, _ = get_os_info()
    return os_id in ('debian', 'ubuntu', 'linuxmint', 'pop', 'elementary')


def get_system_architecture() -> str:
    """
    Get system architecture.

    Returns:
        str: Architecture string (e.g., 'x86_64', 'aarch64')
    """
    return platform.machine()


def is_package_installed(package_name: str) -> bool:
    """
    Check if a Debian package is installed.

    Args:
        package_name: Name of the package

    Returns:
        bool: True if installed
    """
    try:
        result = subprocess.run(
            ["dpkg", "-l", package_name],
            capture_output=True,
            text=True
        )
        return result.returncode == 0 and "ii" in result.stdout
    except Exception:
        return False


def install_system_package(package_name: str) -> bool:
    """
    Install a system package via apt.

    Args:
        package_name: Name of the package

    Returns:
        bool: True if installation successful
    """
    logger = get_logger()

    try:
        run_command(f"sudo apt install -y {package_name}", check=True)
        return True
    except CommandError as e:
        logger.error(f"Failed to install {package_name}: {e}")
        return False
