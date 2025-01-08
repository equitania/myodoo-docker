#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
Nginx Log and Cache Cleanup Script for Odoo Docker Environment

This script performs cleanup of:
1. Nginx log files
2. Nginx proxy cache
3. FastCGI cache
4. Removes old backup files based on retention period

Configuration:
    LOGS_PATH: Directory containing Nginx log files (default: '/var/log/nginx/')
    RETENTION_DAYS: Number of days to keep backup files (default: 7)
    CACHE_PATHS: Dictionary of cache paths to clean

Author: Equitania Software GmbH
License: GNU Affero General Public License v3
Version: 1.1.1
Date: 2025-01-08
"""

import os
import time
import shutil
import glob
from datetime import datetime, timedelta
import logging
import subprocess

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration constants
LOGS_PATH = '/var/log/nginx/'
RETENTION_DAYS = 7
SECONDS_PER_DAY = 86400

# Cache paths configuration
CACHE_PATHS = {
    'proxy_cache': '/var/cache/nginx',
    'fastcgi_cache': '/var/cache/nginx/fastcgi'
}

def cleanup_backups(cleanup_path, cutoff_timestamp):
    """
    Remove files older than the cutoff timestamp from the specified directory.
    
    Args:
        cleanup_path (str): Directory path containing files to clean
        cutoff_timestamp (float): Unix timestamp; files older than this will be removed
    """
    try:
        files = os.listdir(cleanup_path)
        for file in files:
            file_path = os.path.join(cleanup_path, file)
            if os.path.isfile(file_path):
                creation_time = os.stat(file_path).st_ctime
                if creation_time < cutoff_timestamp:
                    logger.info(f"Removing old file: {file_path}")
                    os.remove(file_path)
    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}")

def clear_cache_directory(cache_path):
    """
    Clear all contents of a cache directory while preserving the directory structure.
    Only attempts to clear if the directory exists.
    
    Args:
        cache_path (str): Path to the cache directory
    """
    if not os.path.exists(cache_path):
        logger.warning(f"Cache directory does not exist: {cache_path}")
        return

    try:
        logger.info(f"Clearing cache directory: {cache_path}")
        for root, dirs, files in os.walk(cache_path):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    os.remove(file_path)
                    logger.debug(f"Removed cache file: {file_path}")
                except Exception as e:
                    logger.error(f"Error removing cache file {file_path}: {str(e)}")
    except Exception as e:
        logger.error(f"Error clearing cache directory {cache_path}: {str(e)}")

def restart_nginx():
    """
    Restart Nginx service.
    Returns True if successful, False otherwise.
    """
    try:
        logger.info("Stopping Nginx service...")
        subprocess.run(['systemctl', 'stop', 'nginx'], check=True)
        
        # Clear only existing cache directories
        for cache_name, cache_path in CACHE_PATHS.items():
            if os.path.exists(cache_path):
                clear_cache_directory(cache_path)
        
        logger.info("Starting Nginx service...")
        subprocess.run(['systemctl', 'start', 'nginx'], check=True)
        
        # Verify Nginx status
        result = subprocess.run(['systemctl', 'status', 'nginx'], 
                              capture_output=True, 
                              text=True, 
                              check=True)
        if "active (running)" in result.stdout:
            logger.info("Nginx restarted successfully")
            return True
        else:
            logger.error("Nginx is not running after restart")
            return False
    except subprocess.CalledProcessError as e:
        logger.error(f"Error during Nginx restart: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during Nginx restart: {str(e)}")
        return False

def main():
    """Main execution function"""
    try:
        # Calculate yesterday's date for backup file suffix
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        
        # Move current log files to backup files
        log_files = glob.glob(os.path.join(LOGS_PATH, '*.log'))
        for log_file in log_files:
            backup_file = f"{log_file}{yesterday}.bak"
            logger.info(f"Moving {log_file} to {backup_file}")
            shutil.move(log_file, backup_file)

        # Calculate cutoff time for old backups
        cutoff_timestamp = time.time() - (float(RETENTION_DAYS) * SECONDS_PER_DAY)
        
        # Perform cleanup and restart Nginx
        cleanup_backups(LOGS_PATH, cutoff_timestamp)
        if restart_nginx():
            logger.info("Cleanup and cache optimization completed successfully!")
        else:
            logger.error("Cleanup completed but Nginx restart failed!")
            
    except Exception as e:
        logger.error(f"Script execution failed: {str(e)}")

if __name__ == "__main__":
    main()