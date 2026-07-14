# -*- coding: utf-8 -*-
"""
Proxy configuration utilities for getScripts.py

Handles proxy configuration for customer networks.
"""

import os
import re
import subprocess
from typing import Optional, Dict

from .logging_config import get_logger
from .system_utils import run_command, is_root_or_has_sudo, ensure_directory_exists


# Marker file for proxy configuration
PROXY_CONFIG_FILE = os.path.expanduser("~/.getscripts_proxy")


def is_proxy_configured() -> bool:
    """
    Check if proxy is already configured.

    Returns:
        bool: True if proxy is configured
    """
    return os.path.exists(PROXY_CONFIG_FILE)


def get_proxy_settings() -> Optional[Dict[str, str]]:
    """
    Get current proxy settings from marker file.

    Returns:
        Optional[Dict[str, str]]: Proxy settings or None
    """
    if not is_proxy_configured():
        return None

    try:
        settings = {}
        with open(PROXY_CONFIG_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    settings[key.strip()] = value.strip()
        return settings if settings else None
    except Exception:
        return None


def validate_proxy_url(url: str) -> bool:
    """
    Validate a proxy URL format.

    Args:
        url: Proxy URL to validate

    Returns:
        bool: True if valid
    """
    # Basic URL validation for proxy
    pattern = r'^https?://[a-zA-Z0-9.-]+(?::\d+)?/?$'
    return bool(re.match(pattern, url))


def validate_no_proxy(no_proxy: str) -> bool:
    """
    Validate a no_proxy value before it gets embedded in a generated shell
    config (e.g. `set -gx no_proxy "{no_proxy}"` in Fish). Unlike
    validate_proxy_url() this value is a comma-separated list of hostnames,
    IPs, CIDR ranges and wildcards - not a URL - so it needs its own
    whitelist. Rejecting anything outside it prevents a stray quote from
    breaking out of the generated config (command injection on every shell
    start).

    Args:
        no_proxy: no_proxy value to validate

    Returns:
        bool: True if valid (empty string is allowed)
    """
    pattern = r'^[A-Za-z0-9.,:*_/-]*$'
    return bool(re.match(pattern, no_proxy))


def configure_proxy_settings() -> bool:
    """
    Interactive proxy configuration.

    Returns:
        bool: True if proxy was configured
    """
    logger = get_logger()

    print("\n" + "=" * 60)
    print("Proxy-Konfiguration")
    print("=" * 60)

    try:
        response = input("\nVerwendet dieses Netzwerk einen Proxy? (j/N): ").strip().lower()

        if response not in ('j', 'ja', 'y', 'yes'):
            logger.info("No proxy configuration needed")
            return False

        print("\nProxy-Einstellungen:")
        http_proxy = input("HTTP Proxy (z.B. http://proxy.firma.de:8080): ").strip()

        if not http_proxy:
            logger.info("No proxy URL provided")
            return False

        if not validate_proxy_url(http_proxy):
            print(f"Ungültiges Proxy-URL-Format: {http_proxy}")
            return False

        https_proxy = input("HTTPS Proxy (Enter = wie HTTP): ").strip() or http_proxy
        no_proxy = input("Ausnahmen (kommagetrennt, z.B. localhost,127.0.0.1,.local): ").strip()

        if not no_proxy:
            no_proxy = "localhost,127.0.0.1,::1,.local"

        proxy_config = {
            'http_proxy': http_proxy,
            'https_proxy': https_proxy,
            'no_proxy': no_proxy
        }

        return apply_proxy_settings(proxy_config)

    except (EOFError, KeyboardInterrupt):
        return False


def apply_proxy_settings(config: Dict[str, str]) -> bool:
    """
    Apply proxy settings to system and shells.

    Args:
        config: Proxy configuration dict

    Returns:
        bool: True if successful
    """
    logger = get_logger()

    http_proxy = config.get('http_proxy', '')
    https_proxy = config.get('https_proxy', '')
    no_proxy = config.get('no_proxy', 'localhost,127.0.0.1,::1,.local')

    success = True

    # 1. Save proxy configuration to marker file
    try:
        with open(PROXY_CONFIG_FILE, 'w') as f:
            f.write(f"# Proxy configuration - managed by getScripts.py\n")
            f.write(f"http_proxy={http_proxy}\n")
            f.write(f"https_proxy={https_proxy}\n")
            f.write(f"no_proxy={no_proxy}\n")
        logger.info("Proxy configuration saved")
    except Exception as e:
        logger.error(f"Failed to save proxy configuration: {e}")
        success = False

    # 2. Apply to Fish shell
    if not _apply_proxy_to_fish(config):
        success = False

    # 3. Apply to /etc/environment (system-wide, requires sudo)
    if is_root_or_has_sudo():
        if not _apply_proxy_to_environment(config):
            success = False
    else:
        logger.warning("Cannot apply system-wide proxy without sudo")

    # 4. Apply to Docker daemon (if available)
    if is_root_or_has_sudo():
        _apply_proxy_to_docker(config)

    return success


def _apply_proxy_to_fish(config: Dict[str, str]) -> bool:
    """Apply proxy settings to Fish shell."""
    logger = get_logger()

    fish_conf_dir = os.path.expanduser("~/.config/fish/conf.d")
    ensure_directory_exists(fish_conf_dir)

    proxy_fish = os.path.join(fish_conf_dir, "99-proxy.fish")

    # no_proxy is not URL-checked like http_proxy/https_proxy above - validate
    # it separately before embedding it in the generated Fish config, or a
    # stray '"' could break out of the `set -gx` string and inject commands
    # that run on every shell start.
    no_proxy = config.get('no_proxy', '')
    if not validate_no_proxy(no_proxy):
        logger.warning(f"Invalid no_proxy value rejected (unsafe characters): {no_proxy!r} - using empty no_proxy")
        no_proxy = ""

    content = f'''# Proxy Configuration - managed by getScripts.py
# Remove or edit this file to change proxy settings

set -gx http_proxy "{config['http_proxy']}"
set -gx https_proxy "{config['https_proxy']}"
set -gx HTTP_PROXY "{config['http_proxy']}"
set -gx HTTPS_PROXY "{config['https_proxy']}"
set -gx no_proxy "{no_proxy}"
set -gx NO_PROXY "{no_proxy}"
'''

    try:
        with open(proxy_fish, 'w') as f:
            f.write(content)
        logger.info("Fish proxy configuration applied")
        return True
    except Exception as e:
        logger.error(f"Failed to apply Fish proxy configuration: {e}")
        return False


def _apply_proxy_to_environment(config: Dict[str, str]) -> bool:
    """Apply proxy settings to /etc/environment."""
    logger = get_logger()

    env_file = "/etc/environment"

    try:
        # Read current content
        current_content = ""
        if os.path.exists(env_file):
            with open(env_file, 'r') as f:
                current_content = f.read()

        # Remove existing proxy settings
        lines = []
        for line in current_content.split('\n'):
            if not any(key in line.lower() for key in ['http_proxy', 'https_proxy', 'no_proxy']):
                lines.append(line)

        # Add new proxy settings
        lines.append(f'http_proxy="{config["http_proxy"]}"')
        lines.append(f'https_proxy="{config["https_proxy"]}"')
        lines.append(f'HTTP_PROXY="{config["http_proxy"]}"')
        lines.append(f'HTTPS_PROXY="{config["https_proxy"]}"')
        lines.append(f'no_proxy="{config["no_proxy"]}"')
        lines.append(f'NO_PROXY="{config["no_proxy"]}"')

        new_content = '\n'.join(line for line in lines if line.strip())

        subprocess.run(["sudo", "tee", env_file], input=new_content.encode(), check=True, stdout=subprocess.DEVNULL)
        logger.info("System environment proxy configuration applied")
        return True
    except Exception as e:
        logger.error(f"Failed to apply environment proxy configuration: {e}")
        return False


def _apply_proxy_to_docker(config: Dict[str, str]) -> bool:
    """Apply proxy settings to Docker daemon."""
    logger = get_logger()

    docker_dir = "/etc/systemd/system/docker.service.d"
    proxy_conf = os.path.join(docker_dir, "http-proxy.conf")

    content = f'''[Service]
Environment="HTTP_PROXY={config['http_proxy']}"
Environment="HTTPS_PROXY={config['https_proxy']}"
Environment="NO_PROXY={config['no_proxy']}"
'''

    try:
        run_command(f"sudo mkdir -p {docker_dir}", check=True)
        subprocess.run(["sudo", "tee", proxy_conf], input=content.encode(), check=True, stdout=subprocess.DEVNULL)
        run_command("sudo systemctl daemon-reload", check=True)
        logger.info("Docker proxy configuration applied")
        logger.info("Note: Docker service restart required for changes to take effect")
        return True
    except Exception as e:
        logger.warning(f"Could not apply Docker proxy configuration: {e}")
        return False


def remove_proxy_settings() -> bool:
    """
    Remove all proxy settings.

    Returns:
        bool: True if successful
    """
    logger = get_logger()

    success = True

    # Remove marker file
    if os.path.exists(PROXY_CONFIG_FILE):
        try:
            os.remove(PROXY_CONFIG_FILE)
        except Exception as e:
            logger.error(f"Failed to remove proxy marker: {e}")
            success = False

    # Remove Fish proxy configuration
    fish_proxy = os.path.expanduser("~/.config/fish/conf.d/99-proxy.fish")
    if os.path.exists(fish_proxy):
        try:
            os.remove(fish_proxy)
            logger.info("Removed Fish proxy configuration")
        except Exception as e:
            logger.error(f"Failed to remove Fish proxy: {e}")
            success = False

    logger.info("Proxy settings removed. System-wide settings in /etc/environment may need manual removal.")
    return success
