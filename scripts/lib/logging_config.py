# -*- coding: utf-8 -*-
"""
Logging configuration for getScripts.py
"""

import os
import logging
from typing import Optional

# Module-level logger
_logger: Optional[logging.Logger] = None


def setup_logging(debug: bool = False) -> logging.Logger:
    """
    Configure and return the logger for getScripts.py.

    Args:
        debug: Enable debug logging if True

    Returns:
        logging.Logger: Configured logger instance
    """
    global _logger

    if _logger is not None:
        return _logger

    log_file = os.path.join(os.path.expanduser("~"), "getscripts.log")

    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file)
        ]
    )

    _logger = logging.getLogger("getscripts")

    # Check environment variable for debug mode
    if os.environ.get('GETSCRIPTS_DEBUG', '').lower() in ('1', 'true', 'yes'):
        _logger.setLevel(logging.DEBUG)
        _logger.debug("Debug logging enabled via environment variable")

    return _logger


def get_logger() -> logging.Logger:
    """
    Get the logger instance, creating it if necessary.

    Returns:
        logging.Logger: Logger instance
    """
    global _logger

    if _logger is None:
        return setup_logging()

    return _logger
