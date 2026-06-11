# -*- coding: utf-8 -*-
"""
Fish shell setup and configuration for getScripts.py

Handles Fish installation, Fisher plugin manager, and configuration.
"""

import os
import shutil
from typing import Tuple

from .logging_config import get_logger
from .system_utils import run_command, get_os_info, is_root_or_has_sudo, ensure_directory_exists
from .shell_detection import (
    is_fish_installed,
    is_fish_repo_configured,
    is_fish_repo_key_present,
    cleanup_duplicate_fish_repo,
)


def install_fish_if_needed() -> Tuple[bool, bool]:
    """
    Install or upgrade Fish shell from official repository.

    Uses official Fish shell repositories:
    - Debian: OpenSUSE Build Service (shells:fish:release:4)
    - Ubuntu: Launchpad PPA (ppa:fish-shell/release-4)

    Returns:
        Tuple[bool, bool]: (is_available, needs_migration)
            - is_available: True if Fish 4.0+ is available
            - needs_migration: True if fresh install or migration from system packages
    """
    logger = get_logger()

    installed, current_version = is_fish_installed()
    needs_migration = False

    if not is_root_or_has_sudo():
        logger.warning("Cannot install/upgrade Fish without sudo privileges")
        return installed, False

    # Clean up duplicate repository entries (.list + .sources)
    cleanup_duplicate_fish_repo()

    os_id, os_version = get_os_info()

    # =========================================================================
    # UBUNTU: Use Launchpad PPA
    # =========================================================================
    if os_id == "ubuntu":
        try:
            if not is_fish_repo_configured():
                logger.info("Adding official Fish shell PPA repository...")
                run_command("sudo apt-add-repository -y ppa:fish-shell/release-4", check=True)
                needs_migration = True

            run_command("sudo apt update", check=True)

            if installed:
                logger.info(f"Fish {current_version} installed, checking for updates...")
                run_command("sudo apt install -y --only-upgrade fish", check=True)
            else:
                logger.info("Installing Fish shell from official PPA...")
                run_command("sudo apt install -y fish", check=True)
                needs_migration = True

            installed, new_version = is_fish_installed()
            if installed:
                if new_version != current_version:
                    logger.info(f"Fish shell upgraded: {current_version or 'not installed'} → {new_version}")
                else:
                    logger.info(f"Fish shell {new_version} is already the latest version")
                return True, needs_migration
        except Exception as e:
            logger.error(f"Failed to install/upgrade Fish from PPA: {e}")
            return installed, False

    # =========================================================================
    # DEBIAN: Use OpenSUSE Build Service repository
    # =========================================================================
    elif os_id == "debian":
        debian_repos = {
            "12": "Debian_12",
            "13": "Debian_13",
        }

        if os_version not in debian_repos:
            try:
                with open("/etc/os-release") as f:
                    content = f.read()
                if "bookworm" in content.lower():
                    os_version = "12"
                elif "trixie" in content.lower():
                    os_version = "13"
                else:
                    logger.warning(f"Unknown Debian version '{os_version}', defaulting to Debian 13")
                    os_version = "13"
            except:
                os_version = "13"

        debian_version = debian_repos.get(os_version, "Debian_13")
        repo_url = f"http://download.opensuse.org/repositories/shells:/fish:/release:/4/{debian_version}/"
        key_url = f"https://download.opensuse.org/repositories/shells:fish:release:4/{debian_version}/Release.key"

        repo_list_path = "/etc/apt/sources.list.d/shells:fish:release:4.list"

        try:
            # Repair half-configured state: .list present but signing key missing
            # (e.g. earlier run failed during key import) - breaks every 'apt update'
            key_repair_needed = os.path.exists(repo_list_path) and not is_fish_repo_key_present()

            if not is_fish_repo_configured() or key_repair_needed:
                logger.info(f"Adding official Fish shell repository for {debian_version}...")

                repo_list_content = f"deb {repo_url} /"
                run_command(
                    f"echo '{repo_list_content}' | sudo tee {repo_list_path}",
                    shell=True, check=True
                )

                # Import signing key as ASCII-armored .asc (supported since apt 1.4,
                # Debian 9+) - avoids dependency on gnupg, which minimal images lack.
                # Download to temp file first so a failed download propagates as error
                # instead of leaving an empty key file behind (no pipefail in /bin/sh).
                logger.info("Importing Fish shell repository signing key...")
                run_command(
                    f"curl -fsSL {key_url} -o /tmp/shells_fish_release_4.asc && "
                    "sudo mv /tmp/shells_fish_release_4.asc /etc/apt/trusted.gpg.d/shells_fish_release_4.asc",
                    shell=True, check=True
                )

                needs_migration = True

            run_command("sudo apt update", check=True)

            if installed:
                logger.info(f"Fish {current_version} installed, checking for updates...")
                run_command("sudo apt install -y --only-upgrade fish", check=True)
            else:
                logger.info("Installing Fish shell from official repository...")
                run_command("sudo apt install -y fish", check=True)
                needs_migration = True

            installed, new_version = is_fish_installed()
            if installed:
                if new_version != current_version:
                    logger.info(f"Fish shell upgraded: {current_version or 'not installed'} → {new_version}")
                else:
                    logger.info(f"Fish shell {new_version} is already the latest version")
                return True, needs_migration
        except Exception as e:
            logger.error(f"Failed to install/upgrade Fish from official repository: {e}")

            # Remove the half-configured repo so apt keeps working system-wide
            logger.info("Removing Fish OBS repository files to keep apt functional...")
            run_command(
                f"sudo rm -f {repo_list_path} "
                "/etc/apt/trusted.gpg.d/shells_fish_release_4.asc "
                "/etc/apt/trusted.gpg.d/shells_fish_release_4.gpg",
                shell=True
            )

            # Fallback: install Fish from Debian repos (frozen version, better than
            # none). The OBS repo setup is retried on the next script run.
            try:
                run_command("sudo apt update", check=True)
                if not installed:
                    logger.info("Installing Fish shell from Debian repositories (fallback)...")
                    run_command("sudo apt install -y fish", check=True)
                    needs_migration = True
                installed, new_version = is_fish_installed()
                if installed:
                    logger.warning(
                        f"Fish {new_version} available from Debian repos only - "
                        "official OBS repo setup failed, will retry on next run"
                    )
                    return True, needs_migration
            except Exception as fallback_error:
                logger.error(f"Fallback installation from Debian repositories also failed: {fallback_error}")
            return installed, False

    else:
        logger.warning(f"Unsupported OS: {os_id}. Cannot install Fish shell automatically.")
        return installed, False

    return False, False


def is_fisher_installed() -> bool:
    """
    Check if Fisher plugin manager is installed for Fish.

    Returns:
        bool: True if Fisher is installed
    """
    fisher_path = os.path.expanduser("~/.config/fish/functions/fisher.fish")
    return os.path.exists(fisher_path)


def install_fisher_if_needed() -> bool:
    """
    Install Fisher plugin manager for Fish if not installed.

    Returns:
        bool: True if Fisher is available
    """
    logger = get_logger()

    if is_fisher_installed():
        logger.info("Fisher plugin manager is already installed")
        return True

    logger.info("Installing Fisher plugin manager...")
    try:
        run_command(
            'fish -c "curl -sL https://raw.githubusercontent.com/jorgebucaran/fisher/main/functions/fisher.fish | source && fisher install jorgebucaran/fisher"',
            shell=True, check=True
        )
        logger.info("Fisher installed successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to install Fisher: {e}")
        return False


def copy_fish_configuration(home_dir: str, myodoo_docker: str) -> bool:
    """
    Copy Fish shell configuration files from repository.

    Args:
        home_dir: User's home directory
        myodoo_docker: Path to myodoo-docker repository

    Returns:
        bool: True if configuration copied successfully
    """
    logger = get_logger()

    try:
        source_fish_dir = os.path.join(myodoo_docker, "scripts", "fish")
        target_fish_dir = os.path.join(home_dir, ".config", "fish")

        if not os.path.exists(source_fish_dir):
            logger.warning(f"Fish configuration directory not found: {source_fish_dir}")
            return False

        # Create target directories
        ensure_directory_exists(os.path.join(target_fish_dir, "conf.d"))
        ensure_directory_exists(os.path.join(target_fish_dir, "functions"))

        # Copy config.fish
        source_config = os.path.join(source_fish_dir, "config.fish")
        target_config = os.path.join(target_fish_dir, "config.fish")
        if os.path.exists(source_config):
            if os.path.exists(target_config):
                backup_path = f"{target_config}.bak"
                logger.info(f"Backing up existing Fish config to {backup_path}")
                shutil.copy2(target_config, backup_path)
            shutil.copy2(source_config, target_config)
            logger.info("Fish config.fish copied successfully")

        # Copy conf.d files
        source_confd = os.path.join(source_fish_dir, "conf.d")
        target_confd = os.path.join(target_fish_dir, "conf.d")
        if os.path.exists(source_confd):
            for filename in os.listdir(source_confd):
                source_file = os.path.join(source_confd, filename)
                target_file = os.path.join(target_confd, filename)
                if os.path.isfile(source_file):
                    shutil.copy2(source_file, target_file)
            logger.info("Fish conf.d files copied successfully")

        # Copy functions
        source_functions = os.path.join(source_fish_dir, "functions")
        target_functions = os.path.join(target_fish_dir, "functions")
        if os.path.exists(source_functions):
            for filename in os.listdir(source_functions):
                source_file = os.path.join(source_functions, filename)
                target_file = os.path.join(target_functions, filename)
                if os.path.isfile(source_file):
                    shutil.copy2(source_file, target_file)
            logger.info("Fish functions copied successfully")

        return True

    except Exception as e:
        logger.error(f"Error copying Fish configuration: {e}")
        return False


def prompt_shell_change(home_dir: str) -> bool:
    """
    Prompt user to change default shell to Fish.

    Args:
        home_dir: User's home directory

    Returns:
        bool: True if shell was changed
    """
    logger = get_logger()

    print("\n" + "=" * 60)
    print("Fish shell is now installed!")
    print("=" * 60)
    print("\nWould you like to set Fish as your default shell?")
    print("(You can always change back with: chsh -s /bin/bash)")
    print()

    try:
        response = input("Change default shell to Fish? (y/N): ").strip().lower()

        if response in ('y', 'yes', 'j', 'ja'):
            run_command("chsh -s /usr/bin/fish", check=True)
            logger.info("Default shell changed to Fish")
            print("\nDefault shell changed to Fish!")
            print("Please log out and log back in for the change to take effect.")
            return True
        else:
            logger.info("User declined shell change")
            print("\nKeeping current shell. You can start Fish anytime by typing: fish")
            return False
    except Exception as e:
        logger.error(f"Error changing shell: {e}")
        print(f"\nCould not change shell automatically: {e}")
        print("You can manually change it with: chsh -s /usr/bin/fish")
        return False
