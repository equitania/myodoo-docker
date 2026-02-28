# -*- coding: utf-8 -*-
"""
getScripts.py Modular Library
Version 8.0.0 | 30.01.2026

This package contains modularized components of the getScripts.py utility.
"""

from .constants import SCRIPT_VERSION, SCRIPT_DATE

__version__ = SCRIPT_VERSION
__all__ = [
    'constants',
    'logging_config',
    'cache',
    'system_utils',
    'shell_detection',
    'fish_setup',
    'tool_installers',
    'package_manager',
    'dns_optimizer',
    'proxy_config',
    'first_run',
    'repository',
]
