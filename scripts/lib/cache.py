# -*- coding: utf-8 -*-
"""
Cache management for getScripts.py

Provides pickle-based caching for version information and other data.
"""

import os
import pickle
import shutil
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from .constants import CACHE_DIR, CACHE_EXPIRY_HOURS
from .logging_config import get_logger


def ensure_cache_dir() -> None:
    """Ensure cache directory exists."""
    os.makedirs(CACHE_DIR, exist_ok=True)


def get_cache_file_path(key: str) -> str:
    """
    Get the cache file path for a given key.

    Args:
        key: Cache key identifier

    Returns:
        str: Full path to cache file
    """
    return os.path.join(CACHE_DIR, f"{key}.cache")


def get_cached_version(key: str, disabled: bool = False) -> Optional[Dict[str, Any]]:
    """
    Get cached version information.

    Args:
        key: Cache key
        disabled: If True, always return None (cache disabled)

    Returns:
        Optional[Dict[str, Any]]: Cached data if valid, None otherwise
    """
    logger = get_logger()

    if disabled:
        return None

    ensure_cache_dir()
    cache_file = get_cache_file_path(key)

    if not os.path.exists(cache_file):
        return None

    try:
        with open(cache_file, 'rb') as f:
            cached_data = pickle.load(f)

        # Check if cache is expired
        cache_time = datetime.fromtimestamp(os.path.getmtime(cache_file))
        if datetime.now() - cache_time > timedelta(hours=CACHE_EXPIRY_HOURS):
            logger.debug(f"Cache for {key} is expired")
            os.remove(cache_file)
            return None

        logger.debug(f"Using cached data for {key}")
        return cached_data
    except Exception as e:
        logger.error(f"Error reading cache for {key}: {e}")
        if os.path.exists(cache_file):
            os.remove(cache_file)
        return None


def cache_version_info(key: str, data: Dict[str, Any]) -> None:
    """
    Cache version information.

    Args:
        key: Cache key
        data: Data to cache
    """
    logger = get_logger()
    ensure_cache_dir()
    cache_file = get_cache_file_path(key)

    try:
        with open(cache_file, 'wb') as f:
            pickle.dump(data, f)
        logger.debug(f"Cached data for {key}")
    except Exception as e:
        logger.error(f"Error caching data for {key}: {e}")


def clear_cache() -> None:
    """Clear all cached data."""
    logger = get_logger()

    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)
        logger.info("Cache cleared")
