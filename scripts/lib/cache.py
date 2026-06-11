# -*- coding: utf-8 -*-
"""
Cache management for getScripts.py

JSON-based caching for version information. Keys are restricted to
alphanumerics, underscore, and hyphen to prevent path traversal via
crafted cache keys.
"""

import json
import os
import re
import shutil
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from .constants import CACHE_DIR, CACHE_EXPIRY_HOURS
from .logging_config import get_logger

_CACHE_KEY_RE = re.compile(r'^[A-Za-z0-9._\-]+$')


def ensure_cache_dir() -> None:
    """Ensure cache directory exists."""
    os.makedirs(CACHE_DIR, exist_ok=True)


def get_cache_file_path(key: str) -> str:
    """
    Get the cache file path for a given key.

    Args:
        key: Cache key identifier (must match [A-Za-z0-9_-]+)

    Returns:
        str: Full path to cache file

    Raises:
        ValueError: If the key contains characters that could escape CACHE_DIR.
    """
    if not _CACHE_KEY_RE.match(key):
        raise ValueError(f"Invalid cache key: {key!r}")
    return os.path.join(CACHE_DIR, f"{key}.cache")


def get_cached_version(key: str, disabled: bool = False, allow_stale: bool = False) -> Optional[Dict[str, Any]]:
    """
    Get cached version information.

    Args:
        key: Cache key
        disabled: If True, always return None (cache disabled)
        allow_stale: Return the cached data even when it is older than
            CACHE_EXPIRY_HOURS - used as fallback when the live API query
            fails (a stale version beats aborting the install)

    Returns:
        Optional[Dict[str, Any]]: Cached data if valid, None otherwise
    """
    logger = get_logger()

    if disabled:
        return None

    ensure_cache_dir()
    try:
        cache_file = get_cache_file_path(key)
    except ValueError as e:
        logger.error(f"Refusing to read cache: {e}")
        return None

    if not os.path.exists(cache_file):
        return None

    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            cached_data = json.load(f)

        # Check if cache is expired
        cache_time = datetime.fromtimestamp(os.path.getmtime(cache_file))
        if not allow_stale and datetime.now() - cache_time > timedelta(hours=CACHE_EXPIRY_HOURS):
            logger.debug(f"Cache for {key} is expired")
            os.remove(cache_file)
            return None

        logger.debug(f"Using cached data for {key}")
        return cached_data
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Error reading cache for {key}: {e}")
        if os.path.exists(cache_file):
            os.remove(cache_file)
        return None


def cache_version_info(key: str, data: Dict[str, Any]) -> None:
    """
    Cache version information.

    Args:
        key: Cache key
        data: Data to cache (must be JSON-serializable)
    """
    logger = get_logger()
    ensure_cache_dir()
    try:
        cache_file = get_cache_file_path(key)
    except ValueError as e:
        logger.error(f"Refusing to write cache: {e}")
        return

    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        logger.debug(f"Cached data for {key}")
    except (TypeError, OSError) as e:
        logger.error(f"Error caching data for {key}: {e}")


def clear_cache() -> None:
    """Clear all cached data."""
    logger = get_logger()

    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)
        logger.info("Cache cleared")
