#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
Nginx Log Rotation for Odoo Docker Environment

Rotates *.log files in /var/log/nginx to *.log<YESTERDAY>.bak, then signals
nginx to reopen its log file descriptors via `nginx -s reopen` (SIGUSR1).
Backups older than RETENTION_DAYS are removed; proxy/FastCGI cache clearing
is opt-in via --clear-cache.

Retention: 7 days (DSGVO).
Concurrency: protected by an fcntl lock on LOCK_FILE.

Author: Equitania Software GmbH
License: GNU Affero General Public License v3
Version: 2.0.0
Date: 2026-04-21
"""

import argparse
import fcntl
import glob
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

# Configuration constants
LOGS_PATH = '/var/log/nginx/'
RETENTION_DAYS = 7
SECONDS_PER_DAY = 86400
LOCK_FILE = '/var/run/cleanup-weblogs.lock'

# Cache paths (only cleared when --clear-cache is passed)
CACHE_PATHS = {
    'proxy_cache': '/var/cache/nginx',
    'fastcgi_cache': '/var/cache/nginx/fastcgi',
}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


def acquire_lock():
    """Acquire an exclusive file lock. Exit cleanly if another instance runs.

    This protects against two failure modes:
    - Accidental minute-paced cron (`* 3 * * *`) causing overlapping runs.
    - A slow run still active when the next cron tick fires.
    """
    lock_fd = open(LOCK_FILE, 'w')
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logger.warning("Another cleanup-weblogs instance is already running; exiting")
        sys.exit(0)
    lock_fd.write(str(os.getpid()))
    lock_fd.flush()
    return lock_fd


def rotate_log_files():
    """Rename *.log to *.log<YESTERDAY>.bak atomically.

    nginx keeps the original file descriptors open and continues writing to
    the renamed (.bak) file until `reopen_nginx_logs()` is called. This is
    the standard Unix log-rotation pattern used by logrotate.
    """
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    rotated = 0
    for log_file in glob.glob(os.path.join(LOGS_PATH, '*.log')):
        backup_file = f"{log_file}{yesterday}.bak"
        try:
            os.rename(log_file, backup_file)
            logger.info(f"Rotated {log_file} -> {backup_file}")
            rotated += 1
        except OSError as exc:
            logger.error(f"Could not rotate {log_file}: {exc}")
    logger.info(f"Rotated {rotated} log file(s)")
    return rotated


def reopen_nginx_logs():
    """Send SIGUSR1 to nginx master via `nginx -s reopen`.

    The nginx master closes all open log file descriptors and reopens the
    configured paths. Because the old files were renamed, the reopen
    creates fresh, empty log files at the original paths. Takes single-digit
    milliseconds and involves no DNS resolution.
    """
    try:
        subprocess.run(
            ['nginx', '-s', 'reopen'],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        logger.info("nginx reopened log file descriptors (SIGUSR1)")
        return True
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or '').strip()
        logger.error(f"nginx reopen failed: {stderr or exc}")
        return False
    except subprocess.TimeoutExpired:
        logger.error("nginx reopen timed out after 10s")
        return False
    except FileNotFoundError:
        logger.error("nginx binary not found in PATH")
        return False


def cleanup_old_backups(cutoff_timestamp):
    """Remove *.bak files older than the cutoff timestamp.

    Restricted to *.bak to prevent accidental deletion of anything else in
    LOGS_PATH (e.g. currently open *.log files, nginx sockets).
    """
    removed = 0
    try:
        for entry in os.scandir(LOGS_PATH):
            if not entry.is_file(follow_symlinks=False):
                continue
            if not entry.name.endswith('.bak'):
                continue
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff_timestamp:
                logger.info(f"Removing expired backup (>{RETENTION_DAYS}d): {entry.path}")
                try:
                    os.remove(entry.path)
                    removed += 1
                except OSError as exc:
                    logger.error(f"Could not remove {entry.path}: {exc}")
    except OSError as exc:
        logger.error(f"Could not scan {LOGS_PATH}: {exc}")
    logger.info(f"Removed {removed} expired backup file(s)")
    return removed


def clear_cache_directory(cache_path):
    """Remove files inside a cache directory while preserving structure."""
    if not os.path.exists(cache_path):
        logger.warning(f"Cache directory not present: {cache_path}")
        return 0
    removed = 0
    for root, _dirs, files in os.walk(cache_path):
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                os.remove(fpath)
                removed += 1
            except OSError as exc:
                logger.error(f"Could not remove {fpath}: {exc}")
    logger.info(f"Cleared {removed} file(s) from {cache_path}")
    return removed


def main():
    parser = argparse.ArgumentParser(
        description="Nginx log rotation with DSGVO-compliant 7-day retention",
    )
    parser.add_argument(
        '--clear-cache',
        action='store_true',
        help="Additionally clear nginx proxy and FastCGI caches (off by default; "
             "enabling this negates proxy_cache benefits and should only be used "
             "when cache invalidation is actually required)",
    )
    args = parser.parse_args()

    # Prevent concurrent runs (cron misconfig or slow previous run).
    _lock = acquire_lock()  # noqa: F841 - kept alive for the duration of main()

    rotate_log_files()

    if not reopen_nginx_logs():
        logger.error(
            "nginx reopen failed; skipping backup cleanup to preserve audit trail"
        )
        sys.exit(1)

    cutoff = time.time() - RETENTION_DAYS * SECONDS_PER_DAY
    cleanup_old_backups(cutoff)

    if args.clear_cache:
        for _name, path in CACHE_PATHS.items():
            clear_cache_directory(path)

    logger.info("Cleanup completed successfully")


if __name__ == '__main__':
    main()
