# -*- coding: utf-8 -*-
"""
First-run detection and configuration for getScripts.py

Manages first-run marker and initial configuration prompts.
"""

import os
from datetime import datetime
from typing import Optional, Dict

from .logging_config import get_logger
from .constants import FIRST_RUN_MARKER, SCRIPT_VERSION


def is_first_run() -> bool:
    """
    Check if this is the first run of getScripts.py on this system.

    Returns:
        bool: True if first run
    """
    return not os.path.exists(FIRST_RUN_MARKER)


def mark_configured() -> None:
    """Mark the system as configured after first run."""
    logger = get_logger()

    try:
        with open(FIRST_RUN_MARKER, 'w') as f:
            f.write(f"Configured on {datetime.now().isoformat()}\n")
            f.write(f"Version: {SCRIPT_VERSION}\n")
        logger.info("System marked as configured")
    except Exception as e:
        logger.error(f"Failed to mark system as configured: {e}")


def get_configuration_info() -> Optional[Dict[str, str]]:
    """
    Get information about when the system was configured.

    Returns:
        Optional[Dict[str, str]]: Configuration info or None
    """
    if is_first_run():
        return None

    try:
        info = {}
        with open(FIRST_RUN_MARKER, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith("Configured on"):
                    info["configured_date"] = line.replace("Configured on ", "")
                elif line.startswith("Version:"):
                    info["version"] = line.replace("Version: ", "")
        return info if info else None
    except Exception:
        return None


def run_first_time_setup() -> bool:
    """
    Run first-time setup prompts for DNS and proxy.

    This should be called only if is_first_run() returns True.

    Returns:
        bool: True if setup was completed
    """
    logger = get_logger()

    # Import here to avoid circular imports
    from .dns_optimizer import (
        get_dns_preference,
        optimize_dns_configuration,
        is_dns_already_optimized,
        mark_dns_optimization_declined
    )
    from .proxy_config import configure_proxy_settings

    print("\n" + "=" * 60)
    print("Erste Konfiguration von getScripts.py")
    print("=" * 60)
    print("\nDieses Script wird einmalig einige Einstellungen abfragen.")
    print("Sie können diese später mit --reconfigure erneut aufrufen.\n")

    # DNS Configuration
    if not is_dns_already_optimized():
        dns_servers = get_dns_preference()
        if dns_servers:
            optimize_dns_configuration(dns_servers)
        else:
            mark_dns_optimization_declined()
            logger.info("DNS optimization skipped by user")
    else:
        logger.info("DNS already optimized, skipping configuration")

    # Proxy Configuration
    configure_proxy_settings()

    # Mark as configured
    mark_configured()

    print("\n" + "=" * 60)
    print("Erstkonfiguration abgeschlossen!")
    print("=" * 60)

    return True


def reset_configuration() -> None:
    """
    Reset configuration marker to trigger first-run setup again.
    """
    logger = get_logger()

    if os.path.exists(FIRST_RUN_MARKER):
        try:
            os.remove(FIRST_RUN_MARKER)
            logger.info("Configuration marker removed")
        except Exception as e:
            logger.error(f"Failed to remove configuration marker: {e}")
