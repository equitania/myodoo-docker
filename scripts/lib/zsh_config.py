# -*- coding: utf-8 -*-
"""
ZSH configuration utilities for getScripts.py

Handles ZSH fallback configuration (Fish is primary shell).
"""

import os
import shutil
from typing import Tuple

from .logging_config import get_logger
from .shell_detection import is_zsh_installed


def create_simplified_zshrc(home_dir: str) -> bool:
    """
    Create a simplified .zshrc without Oh-My-Zsh dependency.

    This serves as a fallback for users who need to use ZSH.

    Args:
        home_dir: User's home directory

    Returns:
        bool: True if created successfully
    """
    logger = get_logger()

    # Check if ZSH is installed first
    zsh_installed, _ = is_zsh_installed()
    if not zsh_installed:
        logger.info("ZSH not installed - skipping .zshrc creation")
        return False

    zshrc_path = os.path.join(home_dir, ".zshrc")

    # Backup existing .zshrc if it has Oh-My-Zsh
    if os.path.exists(zshrc_path):
        try:
            with open(zshrc_path, 'r') as f:
                content = f.read()
            if 'oh-my-zsh' in content.lower():
                backup_path = f"{zshrc_path}.bak.ohmyzsh"
                logger.info(f"Backing up Oh-My-Zsh config to {backup_path}")
                shutil.copy2(zshrc_path, backup_path)
        except Exception as e:
            logger.warning(f"Could not check existing .zshrc: {e}")

    # Note: Using ONLY syntax that both Fish and ZSH can parse!
    simplified_zshrc = '''# ZSH Fallback Configuration (Fish is primary shell)
# Version 4.2.0 | 30.01.2026
# This is a minimal ZSH configuration without Oh-My-Zsh dependency
#
# IMPORTANT: If you are using Fish shell, do not source this file!
# Fish uses: ~/.config/fish/config.fish

# Guard: Silently exit if sourced from Fish shell (no warning, just return)
test -n "$FISH_VERSION" && return 0 2>/dev/null

# PATH configuration
export PATH="$HOME/bin:$HOME/.local/bin:/usr/local/bin:$PATH"

# Zoxide (if available) - using && instead of if/then/fi for Fish compatibility
command -v zoxide > /dev/null 2>&1 && eval "$(zoxide init zsh)"

# Starship prompt (if available)
command -v starship > /dev/null 2>&1 && eval "$(starship init zsh)"

# Minimal aliases
alias ls='ls -h --color --classify'
alias ll='ls -alh --color --classify'
alias lg='lazygit'
alias grep='grep --color=auto'
alias ff='fastfetch'
alias dk='docker'
alias dps='docker ps -a --format "table {{.Names}}\\t{{.ID}}\\t{{.Image}}\\t{{.Status}}\\t{{.Ports}}" | sort'

# Fastfetch on startup
command -v fastfetch > /dev/null 2>&1 && fastfetch

cd $HOME
'''

    try:
        with open(zshrc_path, 'w') as f:
            f.write(simplified_zshrc)
        logger.info("Created simplified .zshrc (Fish is now primary shell)")
        return True
    except Exception as e:
        logger.error(f"Error creating simplified .zshrc: {e}")
        return False


def ensure_path_in_zshrc() -> None:
    """Ensure ~/.local/bin is in PATH in .zshrc file."""
    logger = get_logger()

    # Check if ZSH is installed first
    zsh_installed, _ = is_zsh_installed()
    if not zsh_installed:
        logger.debug("ZSH not installed - skipping .zshrc PATH configuration")
        return

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
            logger.debug(f"{local_bin} is already in PATH in .zshrc")
            return

        # Add PATH to .zshrc
        logger.info(f"Adding {local_bin} to PATH in .zshrc")
        with open(zshrc_path, "a") as f:
            f.write(f'\n# Added by getScripts.py\nexport PATH="{local_bin}:$PATH"\n')

        logger.info(".zshrc updated, PATH will be available in new shells")
    except Exception as e:
        logger.error(f"Error updating .zshrc: {e}")


def ensure_path_in_shell_rc() -> None:
    """
    Ensure ~/.local/bin is in PATH for available shells.

    This function handles both ZSH (if installed) and Bash (always available).
    Fish configuration is handled separately by copy_fish_configuration().
    """
    logger = get_logger()

    home = os.path.expanduser("~")
    local_bin = os.path.join(home, ".local", "bin")

    # ZSH: ~/.zshrc (only if ZSH is installed)
    zsh_installed, _ = is_zsh_installed()
    if zsh_installed:
        ensure_path_in_zshrc()

    # Bash: ~/.bashrc (as fallback, since Bash is always available)
    bashrc_path = os.path.join(home, ".bashrc")
    if os.path.exists(bashrc_path):
        try:
            with open(bashrc_path, "r") as f:
                content = f.read()
            if local_bin not in content:
                with open(bashrc_path, "a") as f:
                    f.write(f'\n# Added by getScripts.py\nexport PATH="{local_bin}:$PATH"\n')
                logger.info(f"Added {local_bin} to PATH in .bashrc")
        except Exception as e:
            logger.error(f"Error updating .bashrc: {e}")


def should_replace_zshrc(home_dir: str, fish_is_fresh_install: bool) -> Tuple[bool, str]:
    """
    Determine if .zshrc should be replaced.

    Args:
        home_dir: User's home directory
        fish_is_fresh_install: Whether Fish was freshly installed

    Returns:
        Tuple[bool, str]: (should_replace, reason)
    """
    logger = get_logger()

    # Check if ZSH is installed first
    zsh_installed, _ = is_zsh_installed()
    if not zsh_installed:
        return False, "ZSH not installed"

    zshrc_path = os.path.join(home_dir, ".zshrc")

    if not os.path.exists(zshrc_path):
        return True, ".zshrc not found"

    if fish_is_fresh_install:
        return True, "Fresh Fish installation"

    # Check if existing .zshrc needs to be replaced
    try:
        with open(zshrc_path, 'r') as f:
            zshrc_content = f.read()
        if 'oh-my-zsh' in zshrc_content.lower():
            return True, "Contains Oh-My-Zsh"
        if 'source ~/.zshrc' in zshrc_content:
            return True, "Contains legacy ups alias"
    except Exception as e:
        logger.warning(f"Could not read .zshrc: {e}")

    return False, "Already simplified"
