# -*- coding: utf-8 -*-
"""
Repository management utilities for getScripts.py

Handles git repository operations and file copying.
"""

import os
import subprocess
import glob as glob_module
from typing import List

from .logging_config import get_logger
from .system_utils import run_command, ensure_directory_exists


def clone_or_update_repo(
    repo_url: str,
    target_dir: str,
    branch: str = "2026"
) -> bool:
    """
    Clone or update a git repository.

    Args:
        repo_url: Repository URL
        target_dir: Target directory
        branch: Branch to checkout

    Returns:
        bool: True if successful
    """
    logger = get_logger()

    parent_dir = os.path.dirname(target_dir)
    ensure_directory_exists(parent_dir)

    if not os.path.exists(target_dir):
        logger.info(f"Cloning {repo_url} to {target_dir}")
        try:
            run_command(f"git clone -b {branch} {repo_url} {target_dir}", check=True)
            return True
        except Exception as e:
            logger.error(f"Failed to clone repository: {e}")
            return False

    # Repository exists, update it
    original_dir = os.getcwd()
    try:
        os.chdir(target_dir)

        # Check current branch
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True
        )
        current_branch = result.stdout.strip()

        if current_branch != branch:
            logger.info(f"Switching from {current_branch} to {branch}")
            run_command(f"git checkout {branch}", check=True)

        # Configure and pull
        run_command("git config pull.ff only", capture_output=True)

        before_pull = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()

        run_command("git pull", capture_output=True)

        after_pull = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()

        if before_pull != after_pull:
            logger.info("Repository updated with new changes")
            run_command("git --no-pager log --oneline --no-decorate HEAD@{1}..HEAD")

        # Clean pyc files
        run_command("find . -name '*.pyc' -type f -delete")

        return True
    except Exception as e:
        logger.error(f"Failed to update repository: {e}")
        return False
    finally:
        os.chdir(original_dir)


def copy_scripts(home_dir: str, myodoo_docker: str) -> None:
    """
    Copy utility scripts to home directory.

    Args:
        home_dir: User's home directory
        myodoo_docker: Path to myodoo-docker repository
    """
    logger = get_logger()

    scripts = [
        "update_docker_odoo.py",
        "docker-clean-logs.sh",
        "cleanup-weblogs.py",
        "container2backup.py",
        "container2backup_zstd.py",
        "restore-zip.sh",
        "ssl-renew.sh",
        "getScripts.py"
    ]

    for script in scripts:
        if script == "getScripts.py":
            source = os.path.join(myodoo_docker, script)
        else:
            source = os.path.join(myodoo_docker, "scripts", script)

        target = os.path.join(home_dir, script)

        if os.path.exists(source):
            try:
                run_command(f"cp {source} {target}")
                logger.debug(f"Copied {script}")
            except Exception as e:
                logger.warning(f"Failed to copy {script}: {e}")


def cleanup_legacy_files(home_dir: str, myodoo_docker: str) -> int:
    """
    Remove legacy files listed in cleanup_legacy.txt.

    Args:
        home_dir: User's home directory
        myodoo_docker: Path to myodoo-docker repository

    Returns:
        int: Number of files/directories removed
    """
    logger = get_logger()

    cleanup_file = os.path.join(myodoo_docker, "cleanup_legacy.txt")

    if not os.path.exists(cleanup_file):
        logger.info("No cleanup_legacy.txt found")
        return 0

    removed_count = 0

    try:
        with open(cleanup_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                # Replace ~ with home directory
                path = line.replace('~', home_dir)

                # Handle glob patterns
                if '*' in path:
                    matches = glob_module.glob(path)
                    for match in matches:
                        if _remove_path(match):
                            removed_count += 1
                else:
                    if _remove_path(path):
                        removed_count += 1

        logger.info(f"Removed {removed_count} legacy files/directories")
        return removed_count
    except Exception as e:
        logger.error(f"Error during legacy cleanup: {e}")
        return removed_count


def _remove_path(path: str) -> bool:
    """
    Remove a file or directory.

    Args:
        path: Path to remove

    Returns:
        bool: True if removed
    """
    logger = get_logger()

    if not os.path.exists(path):
        return False

    try:
        if os.path.isdir(path):
            import shutil
            shutil.rmtree(path)
        else:
            os.remove(path)
        logger.info(f"Removed: {path}")
        return True
    except Exception as e:
        logger.warning(f"Failed to remove {path}: {e}")
        return False
