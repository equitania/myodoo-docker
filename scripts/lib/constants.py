# -*- coding: utf-8 -*-
"""
Constants and configuration values for getScripts.py
"""

import os

# Script version and metadata
SCRIPT_VERSION = "9.5.0"
SCRIPT_DATE = "11.06.2026"

# Cache settings
CACHE_DIR = os.path.expanduser("~/.cache/getscripts")
CACHE_EXPIRY_HOURS = 24

# Default paths
LOCAL_BIN = os.path.expanduser("~/.local/bin")
MYODOO_DOCKER_DIR = os.path.expanduser("~/myodoo-docker")

# First-run marker
FIRST_RUN_MARKER = os.path.expanduser("~/.getscripts_configured")

# Default DNS servers
DEFAULT_DNS_SERVERS = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]

# Hetzner-optimized DNS servers (Hetzner primary for lowest latency on Hetzner servers)
HETZNER_DNS_SERVERS = ["185.12.64.2", "1.1.1.1", "9.9.9.9"]

# Repository URLs
MYODOO_DOCKER_REPO = "https://github.com/equitania/myodoo-docker.git"
DEFAULT_BRANCH = "2026"

# Fish shell repository settings
FISH_PPA_URL = "ppa:fish-shell/release-4"
FISH_OBS_REPO_BASE = "https://download.opensuse.org/repositories/shells:/fish:/release:/4"

# Minimum versions
MIN_FISH_VERSION = "4.0.0"
MIN_STARSHIP_VERSION = "1.0.0"
