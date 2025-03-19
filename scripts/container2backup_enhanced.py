#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
Enhanced Odoo Docker Backup Script
Version 1.0.0
Date: 10.03.2025

This script performs backup of Odoo databases including FileStore under Docker with the following features:
- YAML-based configuration
- Support for multiple compression formats (ZSTD, 7-Zip)
- Comprehensive logging
- Automatic cleanup of old backups
- Disk space management
- Custom retention policies
- Backup verification
"""

import argparse
import csv
import datetime
import io
import logging
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import yaml
from logging.handlers import RotatingFileHandler
from os.path import expanduser
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union

# Configure logging
logger = logging.getLogger("odoo_backup")

# Terminal colors for progress bar (if supported)
TERMINAL_COLORS = {
    'green': '\033[92m',
    'yellow': '\033[93m',
    'red': '\033[91m',
    'end': '\033[0m',
    'bold': '\033[1m'
}

class ProgressTracker:
    """Tracks and displays backup progress"""
    
    def __init__(self, total_tasks: int, console_width: int = 80):
        self.total_tasks = total_tasks
        self.completed_tasks = 0
        self.current_task = ""
        self.console_width = min(console_width, 120)  # Limit width to avoid too wide displays
        self.start_time = time.time()
        self.task_start_time = time.time()
        
        # Check if terminal supports colors
        self.colors_supported = sys.stdout.isatty()
        
        logger.info(f"Starting backup with {total_tasks} total tasks")
    
    def start_task(self, task_description: str) -> None:
        """
        Start a new task and display it
        
        Args:
            task_description: Description of the current task
        """
        self.current_task = task_description
        self.task_start_time = time.time()
        self._display_progress()
        
        logger.info(f"Starting task: {task_description}")
    
    def complete_task(self, success: bool = True) -> None:
        """
        Mark current task as completed
        
        Args:
            success: Whether the task completed successfully
        """
        task_duration = time.time() - self.task_start_time
        self.completed_tasks += 1
        
        result = "completed" if success else "failed"
        logger.info(f"Task {result}: {self.current_task} ({task_duration:.1f}s)")
        
        self._display_progress()
    
    def _display_progress(self) -> None:
        """Display progress bar in console"""
        if not sys.stdout.isatty():
            return  # Skip visual progress display if not in a terminal
        
        # Calculate progress
        progress = self.completed_tasks / self.total_tasks if self.total_tasks > 0 else 0
        percent = int(progress * 100)
        
        # Calculate elapsed time and estimated time remaining
        elapsed = time.time() - self.start_time
        if progress > 0:
            remaining = (elapsed / progress) * (1 - progress)
        else:
            remaining = 0
        
        # Prepare progress bar
        bar_width = self.console_width - 40  # Leave space for text
        filled_length = int(bar_width * progress)
        
        # Select color based on progress
        if self.colors_supported:
            if percent < 30:
                color = TERMINAL_COLORS['red']
            elif percent < 70:
                color = TERMINAL_COLORS['yellow']
            else:
                color = TERMINAL_COLORS['green']
            end_color = TERMINAL_COLORS['end']
            bold = TERMINAL_COLORS['bold']
        else:
            color = ""
            end_color = ""
            bold = ""
        
        # Build progress bar
        bar = '█' * filled_length + '░' * (bar_width - filled_length)
        
        # Print progress
        sys.stdout.write('\r')
        sys.stdout.write(
            f"{bold}Progress: {color}{percent:3d}%{end_color} [{color}{bar}{end_color}] "
            f"{self.completed_tasks}/{self.total_tasks} "
            f"({elapsed:.0f}s/{remaining:.0f}s)"
        )
        sys.stdout.flush()
        
        # If completed, add newline
        if progress >= 1:
            sys.stdout.write('\n')
            sys.stdout.flush()
    
    def summary(self) -> None:
        """Display summary of backup operation"""
        total_duration = time.time() - self.start_time
        
        sys.stdout.write('\n')
        logger.info(f"Backup completed: {self.completed_tasks}/{self.total_tasks} tasks in {total_duration:.1f} seconds")
        
        if self.colors_supported:
            color = TERMINAL_COLORS['green'] if self.completed_tasks == self.total_tasks else TERMINAL_COLORS['yellow']
            bold = TERMINAL_COLORS['bold']
            end_color = TERMINAL_COLORS['end']
            
            print(f"\n{bold}Backup Summary:{end_color}")
            print(f"  {bold}Tasks:{end_color} {color}{self.completed_tasks}/{self.total_tasks}{end_color}")
            print(f"  {bold}Time:{end_color} {color}{total_duration:.1f}s{end_color}")
            
            if self.completed_tasks == self.total_tasks:
                print(f"  {bold}Status:{end_color} {color}All tasks completed successfully{end_color}")
            else:
                print(f"  {bold}Status:{end_color} {TERMINAL_COLORS['yellow']}Some tasks failed - check logs{end_color}")
        else:
            print(f"\nBackup Summary:")
            print(f"  Tasks: {self.completed_tasks}/{self.total_tasks}")
            print(f"  Time: {total_duration:.1f}s")
            
            if self.completed_tasks == self.total_tasks:
                print(f"  Status: All tasks completed successfully")
            else:
                print(f"  Status: Some tasks failed - check logs")

# Default configuration values
DEFAULT_CONFIG = {
    'backup_root': '/opt/backups',
    'min_disk_space_gb': 5.0,
    'min_disk_space_percentage': 10,
    'compression': {
        'type': 'zstd',  # Options: 'zstd', '7zip'
        'level': 3,
        'threads': 0
    },
    'logging': {
        'level': 'INFO',
        'file': 'backup.log',
        'max_size_mb': 10,
        'backup_count': 5,
        'console': True
    },
    'default_retention_days': 14,
    'rsync': {
        'enabled': False,
        'targets': []
    },
    'additional_backups': {
        'nginx': {
            'enabled': True,
            'source_path': '/etc/nginx',
            'retention_days': 14
        },
        'letsencrypt': {
            'enabled': True,
            'source_path': '/etc/letsencrypt/live',
            'retention_days': 30
        },
        'docker_builds': {
            'enabled': True,
            'source_path': '/root/docker-builds',
            'retention_days': 14
        },
        'fastreport': {
            'enabled': True,
            'source_path': '/opt/fastreport',
            'retention_days': 14
        }
    }
}

class BackupConfiguration:
    """Manages the backup configuration"""
    
    def __init__(self, config_file: Optional[str] = None):
        self.config = DEFAULT_CONFIG.copy()
        self.odoo_instances = []
        
        # Try to find config file if not specified
        if not config_file:
            config_file = self._find_config_file()
        
        if config_file and os.path.exists(config_file):
            self._load_yaml_config(config_file)
        else:
            # Fallback to old CSV-based config for backward compatibility
            self._load_legacy_config()
            
        # Setup directories
        self._setup_directories()
    
    def _find_config_file(self) -> Optional[str]:
        """Find configuration file in standard locations"""
        search_paths = [
            './backup_config.yaml',
            './backup_config.yml',
            os.path.expanduser('~/.config/odoo_backup/config.yaml'),
            '/etc/odoo/backup_config.yaml',
            '/etc/myodoo/backup_config.yaml'
        ]
        
        for path in search_paths:
            if os.path.exists(path):
                return path
        return None
    
    def _load_yaml_config(self, config_file: str) -> None:
        """Load configuration from YAML file"""
        try:
            with open(config_file, 'r') as f:
                yaml_config = yaml.safe_load(f)
            
            # Update global configuration (first level)
            for key, value in yaml_config.items():
                if key != 'odoo_instances':
                    # Merge nested dictionaries
                    if isinstance(value, dict) and key in self.config and isinstance(self.config[key], dict):
                        self.config[key].update(value)
                    else:
                        self.config[key] = value
            
            # Load Odoo instance configurations
            self.odoo_instances = yaml_config.get('odoo_instances', [])
            
            logger.info(f"Loaded configuration from {config_file}")
        except Exception as e:
            logger.error(f"Failed to load YAML configuration: {str(e)}")
            raise
    
    def _load_legacy_config(self) -> None:
        """Load configuration from legacy CSV files for backward compatibility"""
        try:
            # Get backup path from container2backup_path.csv
            home_path = expanduser("~")
            path_file = os.path.join(home_path, 'container2backup_path.csv')
            
            if os.path.exists(path_file):
                with open(path_file, 'r', encoding='utf8') as f:
                    self.config['backup_root'] = f.readline().strip()
            
            # Load database information from container2backup.csv
            db_file = os.path.join(home_path, 'container2backup.csv')
            if os.path.exists(db_file):
                with io.open(db_file, 'r', encoding='utf8') as csvfile:
                    reader = csv.reader(csvfile, delimiter=",")
                    for row in reader:
                        if not row or row[0].startswith('#'):
                            continue
                        
                        # Try to extract database info from CSV
                        try:
                            db_name = row[0]
                            db_user = row[1]
                            db_container = row[2]
                            odoo_container = row[3]
                            retention_days = int(row[4]) if len(row) > 4 else 14
                            
                            self.odoo_instances.append({
                                'name': 'legacy',
                                'enabled': True,
                                'databases': [
                                    {
                                        'name': db_name,
                                        'user': db_user,
                                        'containers': {
                                            'database': db_container,
                                            'odoo': odoo_container
                                        },
                                        'retention_days': retention_days
                                    }
                                ]
                            })
                        except Exception as db_error:
                            logger.warning(f"Error parsing database entry: {str(row)}: {str(db_error)}")
                
            # Try to load rsync targets
            rsync_file = os.path.join(home_path, 'rsync_targets.csv')
            if os.path.exists(rsync_file):
                self.config['rsync']['enabled'] = True
                self.config['rsync']['targets'] = []
                
                with io.open(rsync_file, 'r', encoding='utf8') as csvfile:
                    reader = csv.reader(csvfile, delimiter=",")
                    for row in reader:
                        if not row or row[0].startswith('#'):
                            continue
                        self.config['rsync']['targets'].append(row[0])
            
            logger.info("Loaded configuration from legacy CSV files")
        except Exception as e:
            logger.error(f"Failed to load legacy configuration: {str(e)}")
            raise
    
    def _setup_directories(self) -> None:
        """Setup backup directory structure"""
        # Create main backup directory
        backup_root = Path(self.config['backup_root'])
        if not backup_root.exists():
            backup_root.mkdir(parents=True)
        
        # Create docker backups directory
        docker_path = backup_root / 'docker'
        if not docker_path.exists():
            docker_path.mkdir()
        
        # Create directories for additional backups
        for backup_name in self.config['additional_backups']:
            backup_config = self.config['additional_backups'][backup_name]
            if backup_config.get('enabled', True):
                backup_dir = backup_root / backup_name
                if not backup_dir.exists():
                    backup_dir.mkdir()
        
        # Create logs directory
        logs_dir = backup_root / 'logs'
        if not logs_dir.exists():
            logs_dir.mkdir()

class BackupManager:
    """Manages the backup process"""
    
    def __init__(self, config: BackupConfiguration):
        self.config = config
        self.setup_logging()
        
        # Check disk space before starting
        self.check_disk_space(Path(config.config['backup_root']), critical=True)
    
    def setup_logging(self) -> None:
        """Setup logging configuration"""
        log_config = self.config.config['logging']
        log_level = getattr(logging, log_config['level'].upper(), logging.INFO)
        
        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(log_level)
        
        # Clear existing handlers
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Add file handler with rotation
        log_path = Path(self.config.config['backup_root']) / 'logs' / log_config['file']
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=log_config['max_size_mb'] * 1024 * 1024,
            backupCount=log_config['backup_count']
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        
        # Add console handler if enabled
        if log_config.get('console', True):
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)
        
        logger.info("Logging configured")
    
    def check_disk_space(self, path: Path, critical: bool = False) -> bool:
        """
        Check if there's enough disk space available
        
        Args:
            path: Path to check
            critical: If True, exit the program if disk space is low
            
        Returns:
            bool: True if enough disk space is available, False otherwise
        """
        try:
            total, used, free = shutil.disk_usage(path)
            free_gb = free / (1024**3)
            free_percent = (free / total) * 100
            
            min_gb = self.config.config['min_disk_space_gb']
            min_percent = self.config.config['min_disk_space_percentage']
            
            logger.info(f"Disk space check: {free_gb:.2f} GB free ({free_percent:.1f}%)")
            
            if free_gb < min_gb or free_percent < min_percent:
                message = (
                    f"Low disk space: {free_gb:.2f} GB ({free_percent:.1f}%) available. "
                    f"Minimum requirements: {min_gb:.1f} GB or {min_percent}%"
                )
                
                if critical:
                    # Try to free up space by deleting oldest backups
                    logger.warning(message + " Attempting to free up space...")
                    if self.cleanup_oldest_backup():
                        # Re-check disk space after cleanup
                        return self.check_disk_space(path, critical)
                    else:
                        logger.error("Could not free up disk space. Exiting.")
                        if critical:
                            sys.exit(1)
                else:
                    logger.warning(message)
                
                return False
            
            return True
        
        except Exception as e:
            logger.error(f"Error checking disk space: {str(e)}")
            if critical:
                sys.exit(1)
            return False
    
    def cleanup_oldest_backup(self) -> bool:
        """
        Delete the oldest backup to free up space
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            backup_root = Path(self.config.config['backup_root'])
            
            # Get all zip/zst files in backup directories
            backup_files = []
            
            # Check docker backups
            docker_dir = backup_root / 'docker'
            if docker_dir.exists():
                backup_files.extend(list(docker_dir.glob("*.zip")))
                backup_files.extend(list(docker_dir.glob("*.zst")))
                backup_files.extend(list(docker_dir.glob("*.7z")))
            
            # Check additional backup directories
            for backup_name in self.config.config['additional_backups']:
                backup_dir = backup_root / backup_name
                if backup_dir.exists():
                    backup_files.extend(list(backup_dir.glob("*.zip")))
                    backup_files.extend(list(backup_dir.glob("*.zst")))
                    backup_files.extend(list(backup_dir.glob("*.7z")))
            
            if not backup_files:
                logger.warning("No backup files found to clean up")
                return False
            
            # Sort by modification time (oldest first)
            backup_files.sort(key=lambda f: f.stat().st_mtime)
            
            # Delete the oldest backup
            oldest_file = backup_files[0]
            oldest_size = oldest_file.stat().st_size / (1024**2)  # Size in MB
            
            logger.info(f"Removing oldest backup to free up space: {oldest_file} ({oldest_size:.2f} MB)")
            oldest_file.unlink()
            
            return True
        
        except Exception as e:
            logger.error(f"Failed to clean up oldest backup: {str(e)}")
            return False
    
    def cleanup_old_backups(self, directory: Path, days: int) -> None:
        """
        Remove backups older than specified days
        
        Args:
            directory: Directory to clean up
            days: Number of days to keep
        """
        try:
            if not directory.exists():
                return
            
            cutoff_time = time.time() - (days * 86400)
            count = 0
            size_freed = 0
            
            for item in directory.glob("*"):
                if not item.is_file():
                    continue
                    
                # Only remove backup files
                if not any(item.name.endswith(ext) for ext in ['.zip', '.zst', '.7z']):
                    continue
                
                if item.stat().st_mtime < cutoff_time:
                    size = item.stat().st_size / (1024**2)  # Size in MB
                    logger.info(f"Removing old backup: {item} ({size:.2f} MB)")
                    item.unlink()
                    count += 1
                    size_freed += size
            
            if count > 0:
                logger.info(f"Cleaned up {count} old backup files, freed {size_freed:.2f} MB")
        
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
    
    def compress_directory(self, source_path: Path, output_path: Path) -> Optional[Path]:
        """
        Compress a directory using the configured compression method
        
        Args:
            source_path: Directory to compress
            output_path: Output file path (without extension)
            
        Returns:
            Path: Path to the compressed file or None if compression failed
        """
        try:
            compression = self.config.config['compression']
            compression_type = compression.get('type', 'zstd').lower()
            level = compression.get('level', 3)
            
            # Check if the required compression tool is installed
            tool_availability = check_compression_dependencies()
            if compression_type == 'zstd' and not tool_availability.get('zstd', False):
                missing_tools = ['zstd']
                instructions = get_installation_instructions(missing_tools)
                logger.error(f"Required compression tool 'zstd' is not installed.{instructions}")
                return None
            elif compression_type == '7zip' and not tool_availability.get('7zip', False):
                missing_tools = ['7zip']
                instructions = get_installation_instructions(missing_tools)
                logger.error(f"Required compression tool '7-Zip' is not installed.{instructions}")
                return None
            elif compression_type == 'zip' and not tool_availability.get('zip', False):
                missing_tools = ['zip']
                instructions = get_installation_instructions(missing_tools)
                logger.error(f"Required compression tool 'zip' is not installed.{instructions}")
                return None
            
            if compression_type == 'zstd':
                # Compression with zstd
                final_path = output_path.with_suffix('.zst')
                
                # First create tar file
                tar_path = output_path.with_suffix('.tar')
                logger.info(f"Creating tar archive: {tar_path}")
                subprocess.run(
                    ['tar', '-cf', str(tar_path), '-C', str(source_path.parent), source_path.name],
                    check=True,
                    capture_output=True,
                    text=True
                )
                
                # Then compress with zstd
                logger.info(f"Compressing with zstd (level {level}): {final_path}")
                subprocess.run(
                    ['zstd', f"-{level}", '-f', str(tar_path), '-o', str(final_path)],
                    check=True,
                    capture_output=True,
                    text=True
                )
                
                # Remove the temporary tar file
                tar_path.unlink()
                
            elif compression_type == '7zip':
                # Compression with 7-Zip
                final_path = output_path.with_suffix('.7z')
                logger.info(f"Compressing with 7-Zip (level {level}): {final_path}")
                
                # Build 7z command
                threads = compression.get('threads', 0)
                thread_param = f"-mmt={threads}" if threads > 0 else ""
                
                # Use 7z command
                subprocess.run(
                    f"7z a -t7z -mx={level} {thread_param} {final_path} {source_path}/*",
                    shell=True,
                    check=True,
                    capture_output=True,
                    text=True
                )
            
            elif compression_type == 'zip':
                # Kompression mit ZIP
                final_path = output_path.with_suffix('.zip')
                logger.info(f"Komprimierung mit ZIP (Stufe {level}): {final_path}")
                
                # ZIP-Befehl zusammenstellen
                compress_cmd = f"cd {source_path.parent} && zip -r -q -{level} {final_path} {source_path.name}"
                
                # ZIP-Befehl ausführen
                subprocess.run(
                    compress_cmd,
                    shell=True,
                    check=True,
                    capture_output=True,
                    text=True
                )
            
            else:
                logger.error(f"Unsupported compression type: {compression_type}")
                return None
            
            # Verify the compressed file exists and has size
            if not final_path.exists() or final_path.stat().st_size == 0:
                raise RuntimeError("Compressed file is empty or does not exist")
            
            logger.info(f"Successfully compressed directory to {final_path}")
            return final_path
        
        except Exception as e:
            logger.error(f"Compression failed: {str(e)}")
            return None
    
    def verify_backup(self, backup_path: Path) -> bool:
        """
        Verify the integrity of the backup file
        
        Args:
            backup_path: Path to the backup file
            
        Returns:
            bool: True if backup is valid, False otherwise
        """
        try:
            if not backup_path.exists():
                logger.error(f"Backup file does not exist: {backup_path}")
                return False
            
            suffix = backup_path.suffix.lower()
            
            # Check if the required tool is installed before verification
            tool_availability = check_compression_dependencies()
            
            if suffix == '.zst':
                # Check if zstd is installed
                if not tool_availability.get('zstd', False):
                    logger.error("Cannot verify .zst file: zstd is not installed")
                    return False
                
                # Verify zstd file
                result = subprocess.run(
                    ['zstd', '-t', str(backup_path)],
                    capture_output=True,
                    text=True
                )
                return result.returncode == 0
            
            elif suffix == '.7z':
                # Check if 7-Zip is installed
                if not tool_availability.get('7zip', False):
                    logger.error("Cannot verify .7z file: 7-Zip is not installed")
                    return False
                
                # Verify 7z file
                result = subprocess.run(
                    ['7z', 't', str(backup_path)],
                    capture_output=True,
                    text=True
                )
                return result.returncode == 0
            
            elif suffix == '.zip':
                # Check if unzip is installed
                if not tool_availability.get('zip', False):
                    logger.error("Cannot verify .zip file: zip/unzip is not installed")
                    return False
                
                # Verify zip file
                result = subprocess.run(
                    ['unzip', '-t', str(backup_path)],
                    capture_output=True,
                    text=True
                )
                return result.returncode == 0
            
            else:
                logger.error(f"Unsupported backup format: {suffix}")
                return False
        
        except Exception as e:
            logger.error(f"Backup verification failed: {str(e)}")
            return False
    
    def backup_database(self, db_config: Dict[str, Any], progress: Optional['ProgressTracker'] = None) -> bool:
        """
        Perform backup of an Odoo database
        
        Args:
            db_config: Database configuration
            progress: Progress tracker instance
            
        Returns:
            bool: True if backup was successful, False otherwise
        """
        start_time = time.time()
        db_name = db_config['name']
        db_user = db_config['user']
        db_container = db_config['containers']['database']
        odoo_container = db_config['containers']['odoo']
        retention_days = db_config.get('retention_days', self.config.config['default_retention_days'])
        
        logger.info(f"Starting backup of database: {db_name} (Container: {odoo_container})")
        
        try:
            # Create temporary directory for backup
            with tempfile.TemporaryDirectory(prefix=f"backup_{db_name}_") as temp_dir:
                temp_path = Path(temp_dir)
                logger.info(f"Created temporary directory: {temp_path}")
                
                # Dump database
                if progress:
                    progress.start_task(f"Dumping database {db_name}")
                
                logger.info(f"Dumping database {db_name} from container {db_container}")
                dump_result = subprocess.run(
                    f"docker exec -i {db_container} pg_dump -U {db_user} {db_name} > {temp_path}/dump.sql",
                    shell=True,
                    capture_output=True,
                    text=True
                )
                
                if dump_result.returncode != 0:
                    logger.error(f"Database dump failed: {dump_result.stderr}")
                    if progress:
                        progress.complete_task(False)
                    return False
                
                if progress:
                    progress.complete_task(True)
                
                # Backup FileStore
                if progress:
                    progress.start_task(f"Backing up FileStore for {db_name}")
                
                logger.info(f"Backing up FileStore from container {odoo_container}")
                fs_result = subprocess.run(
                    f"docker cp {odoo_container}:/opt/odoo/data/filestore/{db_name} {temp_path}/",
                    shell=True,
                    capture_output=True,
                    text=True
                )
                
                if fs_result.returncode != 0:
                    logger.error(f"FileStore backup failed: {fs_result.stderr}")
                    if progress:
                        progress.complete_task(False)
                    return False
                
                if progress:
                    progress.complete_task(True)
                
                # Create timestamp and prepare output path
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                backup_dir = Path(self.config.config['backup_root']) / 'docker'
                output_path = backup_dir / f"{db_name}_{odoo_container}_backup_{timestamp}"
                
                # Compress directory
                if progress:
                    progress.start_task(f"Compressing backup for {db_name}")
                
                compressed_path = self.compress_directory(temp_path, output_path)
                if not compressed_path:
                    logger.error("Compression failed")
                    if progress:
                        progress.complete_task(False)
                    return False
                
                if progress:
                    progress.complete_task(True)
                
                # Verify backup
                if progress:
                    progress.start_task(f"Verifying backup for {db_name}")
                
                if not self.verify_backup(compressed_path):
                    logger.error("Backup verification failed")
                    if progress:
                        progress.complete_task(False)
                    return False
                
                if progress:
                    progress.complete_task(True)
                
                # Calculate duration and size
                duration = time.time() - start_time
                size_mb = compressed_path.stat().st_size / (1024 * 1024)
                
                logger.info(
                    f"Backup completed successfully: {compressed_path.name} "
                    f"({size_mb:.2f} MB, {duration:.1f} seconds)"
                )
                
                # Check disk space after backup
                self.check_disk_space(backup_dir)
                
                # Clean up old backups
                self.cleanup_old_backups(backup_dir, retention_days)
                
                return True
        
        except Exception as e:
            logger.error(f"Backup failed for {db_name}: {str(e)}")
            if progress:
                progress.complete_task(False)
            return False
    
    def backup_additional_path(self, name: str, config: Dict[str, Any], progress: Optional['ProgressTracker'] = None) -> bool:
        """
        Backup an additional path specified in the configuration
        
        Args:
            name: Name of the backup
            config: Backup configuration
            progress: Progress tracker instance
            
        Returns:
            bool: True if backup was successful, False otherwise
        """
        if not config.get('enabled', True):
            logger.info(f"Skipping disabled backup: {name}")
            return True
        
        source_path = Path(config['source_path'])
        if not source_path.exists():
            logger.warning(f"Skipping {name} backup: source path does not exist: {source_path}")
            if progress:
                progress.complete_task(False)
            return False
        
        retention_days = config.get('retention_days', self.config.config['default_retention_days'])
        
        logger.info(f"Starting backup of {name}: {source_path}")
        
        try:
            # Create timestamp and prepare output path
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            backup_dir = Path(self.config.config['backup_root']) / name
            output_path = backup_dir / f"{name}_backup_{timestamp}"
            
            # Compress directory
            if progress:
                progress.start_task(f"Compressing {name}")
                
            compressed_path = self.compress_directory(source_path, output_path)
            if not compressed_path:
                logger.error(f"Compression failed for {name}")
                if progress:
                    progress.complete_task(False)
                return False
            
            if progress:
                progress.complete_task(True)
            
            # Verify backup
            if progress:
                progress.start_task(f"Verifying {name} backup")
                
            if not self.verify_backup(compressed_path):
                logger.error(f"Backup verification failed for {name}")
                if progress:
                    progress.complete_task(False)
                return False
            
            if progress:
                progress.complete_task(True)
            
            # Calculate size
            size_mb = compressed_path.stat().st_size / (1024 * 1024)
            logger.info(f"Backup of {name} completed successfully: {compressed_path.name} ({size_mb:.2f} MB)")
            
            # Check disk space after backup
            self.check_disk_space(backup_dir)
            
            # Clean up old backups
            self.cleanup_old_backups(backup_dir, retention_days)
            
            return True
        
        except Exception as e:
            logger.error(f"Backup failed for {name}: {str(e)}")
            if progress:
                progress.complete_task(False)
            return False
    
    def run_rsync_backup(self, progress: Optional['ProgressTracker'] = None) -> None:
        """
        Run rsync backup according to configuration
        
        Args:
            progress: Progress tracker instance
        """
        if not self.config.config['rsync']['enabled']:
            return
        
        rsync_targets = self.config.config['rsync']['targets']
        if not rsync_targets:
            logger.info("No rsync targets configured")
            return
        
        logger.info(f"Running {len(rsync_targets)} rsync backup tasks")
        
        for idx, rsync_cmd in enumerate(rsync_targets):
            try:
                if progress:
                    progress.start_task(f"Running rsync task {idx+1}/{len(rsync_targets)}")
                    
                logger.info(f"Running rsync task {idx+1}/{len(rsync_targets)}")
                result = subprocess.run(
                    rsync_cmd,
                    shell=True,
                    capture_output=True,
                    text=True
                )
                
                success = result.returncode == 0
                if not success:
                    logger.error(f"Rsync task failed: {result.stderr}")
                else:
                    logger.info("Rsync task completed successfully")
                
                if progress:
                    progress.complete_task(success)
            
            except Exception as e:
                logger.error(f"Error executing rsync task: {str(e)}")
                if progress:
                    progress.complete_task(False)
    
    def run_backup(self) -> bool:
        """
        Run the complete backup process
        
        Returns:
            bool: True if all backups were successful, False otherwise
        """
        logger.info("Starting backup process")
        start_time = time.time()
        all_successful = True
        
        # Count total tasks for progress tracking
        total_tasks = 0
        # Database backups (each has dump, filestore, compression, verification tasks)
        total_tasks += sum(len(instance['databases']) * 4 for instance in self.config.odoo_instances)
        # Additional path backups (each has compression and verification tasks)
        total_tasks += len([b for b in self.config.config['additional_backups'].values() 
                           if b.get('enabled', True) and os.path.exists(b['source_path'])]) * 2
        # Rsync tasks
        if self.config.config['rsync']['enabled']:
            total_tasks += len(self.config.config['rsync']['targets'])
        
        # Initialize progress tracker
        progress = ProgressTracker(total_tasks)
        
        # Backup databases
        for instance in self.config.odoo_instances:
            if not instance.get('enabled', True):
                continue
            
            for db_config in instance['databases']:
                try:
                    db_name = db_config['name']
                    progress.start_task(f"Backing up database {db_name}")
                    success = self.backup_database(db_config, progress)
                    if not success:
                        progress.complete_task(False)
                    # Note: We don't call complete_task here because backup_database will call it
                    # for each step in the database backup process
                    all_successful = all_successful and success
                except Exception as db_error:
                    logger.error(f"Error processing database {db_config['name']}: {str(db_error)}")
                    progress.complete_task(False)
                    all_successful = False
        
        # Backup additional paths
        for name, config in self.config.config['additional_backups'].items():
            try:
                if not config.get('enabled', True):
                    continue
                    
                source_path = Path(config['source_path'])
                if not source_path.exists():
                    logger.warning(f"Skipping {name} backup: source path does not exist: {source_path}")
                    continue
                
                progress.start_task(f"Backing up {name}")
                success = self.backup_additional_path(name, config, progress)
                # Note: backup_additional_path will call complete_task for each step
                all_successful = all_successful and success
            except Exception as path_error:
                logger.error(f"Error processing additional path {name}: {str(path_error)}")
                progress.complete_task(False)
                all_successful = False
        
        # Run rsync backup
        if self.config.config['rsync']['enabled']:
            try:
                self.run_rsync_backup(progress)
            except Exception as rsync_error:
                logger.error(f"Error running rsync backup: {str(rsync_error)}")
                all_successful = False
        
        # Display summary
        progress.summary()
        
        # Log completion
        duration = time.time() - start_time
        if all_successful:
            logger.info(f"Backup process completed successfully in {duration:.1f} seconds")
        else:
            logger.warning(f"Backup process completed with errors in {duration:.1f} seconds")
        
        return all_successful

def create_sample_config(config_path: str) -> None:
    """
    Create a sample YAML configuration file
    
    Args:
        config_path: Path where to write the sample configuration
    """
    sample_config = {
        'backup_root': '/opt/backups',
        'min_disk_space_gb': 5.0,
        'min_disk_space_percentage': 10,
        # Compression settings with detailed explanation
        'compression': {
            # Available compression types:
            # - 'zstd': Best balance of speed and compression (default)
            # - '7zip': Best compression ratio but slower
            # - 'zip': Best compatibility with other systems
            'type': 'zstd',
            
            # Compression level settings:
            # - zstd: 1-19 (default: 3, higher = better compression but slower)
            # - 7zip: 0-9 (default: 5, higher = better compression but slower)
            # - zip: 1-9 (default: 6, higher = better compression but slower)
            'level': 3,
            
            # Number of threads to use for compression (0 = auto)
            # Only effective with 7zip compression
            'threads': 0
        },
        'logging': {
            'level': 'INFO',  # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
            'file': 'backup.log',
            'max_size_mb': 10,
            'backup_count': 5,
            'console': True  # Set to False to disable console output
        },
        'default_retention_days': 14,  # Default number of days to keep backups
        'rsync': {
            'enabled': False,
            'targets': [
                # Example rsync command
                'rsync --delete -avzre "ssh" /sourcepath/ user@servername:/targetpath/'
            ]
        },
        # Multiple Odoo instances configuration
        'odoo_instances': [
            {
                'name': 'production',  # Descriptive name for the instance
                'enabled': True,  # Set to False to temporarily disable backups for this instance
                'databases': [
                    {
                        'name': 'odoo_prod',  # Database name
                        'user': 'odoo',  # PostgreSQL user
                        'containers': {
                            'database': 'prod-postgres',  # PostgreSQL container name
                            'odoo': 'prod-odoo'  # Odoo container name
                        },
                        'retention_days': 30  # Overrides default_retention_days for this database
                    }
                ]
            },
            {
                'name': 'staging',
                'enabled': True,
                'databases': [
                    {
                        'name': 'odoo_staging',
                        'user': 'odoo',
                        'containers': {
                            'database': 'staging-postgres',
                            'odoo': 'staging-odoo'
                        },
                        'retention_days': 14
                    }
                ]
            },
            {
                'name': 'development',
                'enabled': True,  # Can be set to False to skip backups for development
                'databases': [
                    {
                        'name': 'odoo_dev',
                        'user': 'odoo',
                        'containers': {
                            'database': 'dev-postgres',
                            'odoo': 'dev-odoo'
                        },
                        'retention_days': 7  # Shorter retention for development databases
                    }
                ]
            }
        ],
        # Additional paths to backup besides Odoo databases
        'additional_backups': {
            'nginx': {
                'enabled': True,
                'source_path': '/etc/nginx',
                'retention_days': 14,
                # You can override compression settings for specific backups
                # 'compression': {
                #     'type': 'zip',
                #     'level': 9
                # }
            },
            'letsencrypt': {
                'enabled': True,
                'source_path': '/etc/letsencrypt/live',
                'retention_days': 30  # Keep SSL certificates longer
            },
            'docker_builds': {
                'enabled': True,
                'source_path': '/root/docker-builds',
                'retention_days': 14
            },
            'fastreport': {
                'enabled': True,
                'source_path': '/opt/fastreport',
                'retention_days': 14
            }
        }
    }
    
    with open(config_path, 'w') as f:
        yaml.dump(sample_config, f, default_flow_style=False, sort_keys=False)
    
    print(f"Sample configuration created at: {config_path}")
    print("\nAvailable compression formats:")
    print("1. zstd (default): Levels 1-19, default=3")
    print("   - Fast compression with good ratio")
    print("   - Requires zstd to be installed")
    print("2. 7zip: Levels 0-9, default=5")
    print("   - Best compression ratio, but slower")
    print("   - Requires 7z to be installed")
    print("3. zip: Levels 1-9, default=6")
    print("   - Most compatible format")
    print("   - Requires zip/unzip to be installed")
    print("\nTo use the configuration file:")
    print(f"python3 {sys.argv[0]} --config {config_path}")

def create_systemd_service():
    """Print instructions for creating a systemd service for the backup script"""
    service_content = """[Unit]
Description=Odoo Docker Backup Service
After=docker.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /path/to/container2backup_enhanced.py
User=root
Group=root

[Install]
WantedBy=multi-user.target
"""

    timer_content = """[Unit]
Description=Run Odoo Docker Backup daily

[Timer]
OnCalendar=*-*-* 01:00:00
Persistent=true

[Install]
WantedBy=timers.target
"""

    print("\nTo set up a systemd service for scheduled backups:")
    print("1. Create the service file:")
    print("   sudo nano /etc/systemd/system/odoo-backup.service")
    print("2. Paste the following content:")
    print(service_content)
    print("3. Create the timer file:")
    print("   sudo nano /etc/systemd/system/odoo-backup.timer")
    print("4. Paste the following content:")
    print(timer_content)
    print("5. Enable and start the timer:")
    print("   sudo systemctl daemon-reload")
    print("   sudo systemctl enable odoo-backup.timer")
    print("   sudo systemctl start odoo-backup.timer")
    print("6. Verify the timer is active:")
    print("   sudo systemctl list-timers | grep odoo-backup")

def check_compression_dependencies() -> Dict[str, bool]:
    """
    Check if required compression tools are installed on the system.
    
    Returns:
        Dict[str, bool]: Dictionary with compression tools as keys and availability as boolean values
    """
    # Define commands to check for each compression tool
    tools_to_check = {
        'zstd': 'zstd --version',
        '7zip': '7z --help',
        'zip': 'zip --version'
    }
    
    # Check each tool
    tool_availability = {}
    for tool, check_cmd in tools_to_check.items():
        try:
            process = subprocess.run(
                check_cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            tool_availability[tool] = process.returncode == 0
        except Exception:
            tool_availability[tool] = False
    
    return tool_availability

def get_installation_instructions(missing_tools: List[str]) -> str:
    """
    Generate platform-specific installation instructions for missing compression tools.
    
    Args:
        missing_tools: List of missing compression tools
        
    Returns:
        str: Installation instructions
    """
    if not missing_tools:
        return ""
    
    # Detect OS
    system = platform.system().lower()
    # For Linux, try to detect distribution
    distro = ""
    if system == "linux":
        try:
            # Try to get distribution info
            if os.path.exists('/etc/os-release'):
                with open('/etc/os-release', 'r') as f:
                    for line in f:
                        if line.startswith('ID='):
                            distro = line.split('=')[1].strip().strip('"').lower()
                            break
        except Exception:
            pass
    
    # Build instructions
    instructions = ["Installation instructions for missing tools:"]
    
    # Debian/Ubuntu
    if system == "linux" and distro in ["debian", "ubuntu", "linuxmint", "pop"]:
        apt_packages = []
        for tool in missing_tools:
            if tool == 'zstd':
                apt_packages.append('zstd')
            elif tool == '7zip':
                apt_packages.append('p7zip-full')
            elif tool == 'zip':
                apt_packages.append('zip unzip')
        
        if apt_packages:
            instructions.append("\nFor Debian/Ubuntu based systems:")
            instructions.append(f"sudo apt-get update && sudo apt-get install -y {' '.join(apt_packages)}")
    
    # Red Hat/CentOS/Fedora
    elif system == "linux" and distro in ["rhel", "centos", "fedora", "rocky", "almalinux"]:
        dnf_packages = []
        for tool in missing_tools:
            if tool == 'zstd':
                dnf_packages.append('zstd')
            elif tool == '7zip':
                dnf_packages.append('p7zip p7zip-plugins')
            elif tool == 'zip':
                dnf_packages.append('zip unzip')
        
        if dnf_packages:
            instructions.append("\nFor Red Hat/CentOS/Fedora based systems:")
            instructions.append(f"sudo dnf install -y {' '.join(dnf_packages)}")
    
    # SUSE/openSUSE
    elif system == "linux" and distro in ["suse", "opensuse", "sles"]:
        zypper_packages = []
        for tool in missing_tools:
            if tool == 'zstd':
                zypper_packages.append('zstd')
            elif tool == '7zip':
                zypper_packages.append('p7zip')
            elif tool == 'zip':
                zypper_packages.append('zip unzip')
        
        if zypper_packages:
            instructions.append("\nFor SUSE/openSUSE based systems:")
            instructions.append(f"sudo zypper install -y {' '.join(zypper_packages)}")
    
    # Arch Linux
    elif system == "linux" and distro in ["arch", "manjaro"]:
        pacman_packages = []
        for tool in missing_tools:
            if tool == 'zstd':
                pacman_packages.append('zstd')
            elif tool == '7zip':
                pacman_packages.append('p7zip')
            elif tool == 'zip':
                pacman_packages.append('zip unzip')
        
        if pacman_packages:
            instructions.append("\nFor Arch Linux based systems:")
            instructions.append(f"sudo pacman -S --noconfirm {' '.join(pacman_packages)}")
    
    # macOS
    elif system == "darwin":
        brew_packages = []
        for tool in missing_tools:
            if tool == 'zstd':
                brew_packages.append('zstd')
            elif tool == '7zip':
                brew_packages.append('p7zip')
            elif tool == 'zip':
                brew_packages.append('zip')  # Usually pre-installed
        
        if brew_packages:
            instructions.append("\nFor macOS (using Homebrew):")
            instructions.append(f"brew install {' '.join(brew_packages)}")
    
    # Generic Linux fallback
    elif system == "linux":
        instructions.append("\nFor your Linux distribution, please install the following packages:")
        for tool in missing_tools:
            if tool == 'zstd':
                instructions.append("- zstd package")
            elif tool == '7zip':
                instructions.append("- p7zip or p7zip-full package")
            elif tool == 'zip':
                instructions.append("- zip and unzip packages")
    
    # Windows (less common for Docker, but possible)
    elif system == "windows":
        instructions.append("\nFor Windows:")
        for tool in missing_tools:
            if tool == 'zstd':
                instructions.append("- Download and install zstd from https://github.com/facebook/zstd/releases")
            elif tool == '7zip':
                instructions.append("- Download and install 7-Zip from https://www.7-zip.org/")
            elif tool == 'zip':
                instructions.append("- Install Git for Windows which includes zip/unzip utilities")
                instructions.append("  or download UnZip for Windows from http://gnuwin32.sourceforge.net/packages/unzip.htm")
    
    # Unknown system fallback
    else:
        instructions.append("\nFor your operating system, please install the following tools:")
        for tool in missing_tools:
            instructions.append(f"- {tool}")
    
    instructions.append("\nAfter installing the required tools, run the backup script again.")
    
    return "\n".join(instructions)

def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description='Enhanced Odoo Docker Backup Script'
    )
    
    parser.add_argument(
        '--config', '-c',
        help='Path to YAML configuration file'
    )
    
    parser.add_argument(
        '--create-config',
        help='Create a sample configuration file at the specified path',
        metavar='PATH'
    )
    
    parser.add_argument(
        '--create-service',
        help='Print instructions for creating a systemd service',
        action='store_true'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        help='Enable verbose output',
        action='store_true'
    )
    
    parser.add_argument(
        '--check-tools', 
        help='Check if required compression tools are installed',
        action='store_true'
    )
    
    args = parser.parse_args()
    
    # Check compression tools if explicitly requested
    if args.check_tools:
        print("Checking compression tools availability...")
        tool_availability = check_compression_dependencies()
        
        # Print status of each tool
        for tool, available in tool_availability.items():
            status = "✓ Installed" if available else "✗ Missing"
            print(f"{tool}: {status}")
        
        # If any tool is missing, print installation instructions
        missing_tools = [tool for tool, available in tool_availability.items() if not available]
        if missing_tools:
            print("\n" + get_installation_instructions(missing_tools))
        else:
            print("\nAll compression tools are installed. The backup script is ready to use.")
        
        return
    
    # Create sample configuration if requested
    if args.create_config:
        create_sample_config(args.create_config)
        return
    
    # Print service creation instructions if requested
    if args.create_service:
        create_systemd_service()
        return
    
    # Set log level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        # Check required compression tools before starting
        tool_availability = check_compression_dependencies()
        missing_tools = [tool for tool, available in tool_availability.items() if not available]
        
        if missing_tools:
            print("Warning: Some compression tools are not installed:")
            for tool in missing_tools:
                print(f" - {tool}")
            print("\nThe backup will proceed, but will fail if it needs to use a missing tool.")
            print(get_installation_instructions(missing_tools))
            print("\nPress Enter to continue anyway, or Ctrl+C to abort...")
            try:
                input()
            except KeyboardInterrupt:
                print("\nBackup aborted.")
                sys.exit(1)
        
        # Load configuration
        config = BackupConfiguration(args.config)
        
        # Run backup
        backup_manager = BackupManager(config)
        success = backup_manager.run_backup()
        
        sys.exit(0 if success else 1)
    
    except Exception as e:
        logger.error(f"Critical error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main() 