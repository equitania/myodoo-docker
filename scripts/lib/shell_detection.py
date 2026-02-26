# -*- coding: utf-8 -*-
"""
Shell detection utilities for getScripts.py

Provides detection functions for Fish, ZSH, and Bash shells.
"""

import os
import subprocess
import re
from typing import Optional, Tuple, List, Dict

from .logging_config import get_logger


def is_fish_installed() -> Tuple[bool, Optional[str]]:
    """
    Check if Fish shell is installed and get its version.

    Returns:
        Tuple[bool, Optional[str]]: (is_installed, version)
    """
    logger = get_logger()

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
    """
    Check if ZSH is installed and get its version.

    Returns:
        Tuple[bool, Optional[str]]: (is_installed, version)
    """
    logger = get_logger()

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


def is_bash_installed() -> Tuple[bool, Optional[str]]:
    """
    Check if Bash is installed and get its version.

    Returns:
        Tuple[bool, Optional[str]]: (is_installed, version)
    """
    logger = get_logger()

    try:
        result = subprocess.run(
            ["bash", "--version"],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0:
            # Output: "GNU bash, version 5.2.15(1)-release..."
            match = re.search(r'version (\d+\.\d+(?:\.\d+)?)', result.stdout)
            if match:
                version = match.group(1)
                logger.info(f"Bash version {version} found")
                return True, version
        return False, None
    except FileNotFoundError:
        logger.info("Bash not found")
        return False, None


def get_current_shell() -> str:
    """
    Get the current user's default shell.

    Returns:
        str: Shell name (e.g., 'fish', 'zsh', 'bash')
    """
    shell = os.environ.get('SHELL', '/bin/bash')
    return os.path.basename(shell)


def get_available_shells() -> Dict[str, Optional[str]]:
    """
    Get all available shells and their versions.

    Returns:
        Dict[str, Optional[str]]: {shell_name: version or None}
    """
    shells = {}

    fish_installed, fish_version = is_fish_installed()
    if fish_installed:
        shells['fish'] = fish_version

    zsh_installed, zsh_version = is_zsh_installed()
    if zsh_installed:
        shells['zsh'] = zsh_version

    bash_installed, bash_version = is_bash_installed()
    if bash_installed:
        shells['bash'] = bash_version

    return shells


def is_fish_repo_configured() -> bool:
    """
    Check if the official Fish shell repository is already configured.
    Checks both legacy .list format and modern DEB822 .sources format.

    Returns:
        bool: True if Fish repo is configured
    """
    repo_list = "/etc/apt/sources.list.d/shells:fish:release:4.list"
    repo_list_alt = "/etc/apt/sources.list.d/shells_fish_release_4.list"
    # DEB822 format used by modern Debian (Trixie/13+)
    repo_sources = "/etc/apt/sources.list.d/shells:fish:release:4.sources"
    repo_sources_alt = "/etc/apt/sources.list.d/shells_fish_release_4.sources"
    ppa_list = "/etc/apt/sources.list.d/fish-shell-ubuntu-release-4"

    # Check for Debian-style repo (.list or .sources)
    if (os.path.exists(repo_list) or os.path.exists(repo_list_alt) or
            os.path.exists(repo_sources) or os.path.exists(repo_sources_alt)):
        return True

    # Check for Ubuntu PPA (.list or .sources)
    import glob as glob_module
    if glob_module.glob(f"{ppa_list}*.list") or glob_module.glob(f"{ppa_list}*.sources"):
        return True

    return False


def cleanup_duplicate_fish_repo() -> None:
    """
    Remove duplicate Fish repository entries.
    If both .list and .sources files exist, remove the .list file
    since .sources (DEB822 format) is the modern standard.
    """
    logger = get_logger()

    list_file = "/etc/apt/sources.list.d/shells:fish:release:4.list"
    sources_file = "/etc/apt/sources.list.d/shells:fish:release:4.sources"

    if os.path.exists(list_file) and os.path.exists(sources_file):
        logger.info("Duplicate Fish repository detected (.list + .sources), removing .list file...")
        try:
            import subprocess
            subprocess.run(["sudo", "rm", "-f", list_file], check=True)
            logger.info(f"Removed duplicate {list_file}")
        except Exception as e:
            logger.warning(f"Failed to remove duplicate Fish repo file: {e}")
