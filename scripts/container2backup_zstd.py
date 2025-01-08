#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
Odoo Database Backup Script with Docker Support
Version 5.0.2
Date 2025-01-08

This script performs backup of Odoo databases including FileStore under Docker with the following features:
- YAML-based configuration
- Proper logging and documentation
- Error handling and retry mechanisms
- Progress tracking
- Backup verification
- Disk space checking
- Metadata collection
- Memory-efficient file handling
- Enhanced cleanup process
- Configuration via environment variables (with YAML override)
"""

import csv
import datetime
import io
import logging
import os
import shutil
import subprocess
import sys
import time
import yaml
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from os.path import expanduser
from pathlib import Path
from typing import Optional, Dict, List, Any

# Configure logging at module level
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Default configuration that can be overridden by YAML
DEFAULT_CONFIG = {
    'backup_root': '/opt/backups',
    'min_disk_space_gb': 5.0,
    'max_retry_attempts': 3,
    'retry_delay_seconds': 5,
    'log_level': 'INFO',
    'default_retention_days': 14,
    'compression': {
        'type': 'zstd',
        'level': 10
    },
    'logging': {
        'max_size_mb': 10,
        'backup_count': 5
    },
    'credentials': {
        'config_file': '/etc/myodoo/credentials.yaml',
        'fallback_locations': ['/etc/credentials.yaml', '~/.credentials.yaml'],
        'key_directory': '/etc/myodoo/keys'
    }
}

@dataclass
class BackupMetadata:
    """Stores metadata about the backup process"""
    database_name: str
    container_name: str
    timestamp: str
    size_bytes: int
    duration_seconds: float
    success: bool
    error_message: Optional[str] = None

class ConfigurationManager:
    """Manages configuration loading and validation"""
    
    CONFIG_FILE_PATHS = [
        'backup_config.yaml',  # Current directory
        'config/backup_config.yaml',  # Config subdirectory
        os.path.expanduser('~/.config/backup_config.yaml'),  # User's config
        '/etc/odoo/backup_config.yaml',  # System-wide config
    ]
    
    CREDENTIALS_FILE_PATHS = [
        'backup_credentials.yaml',  # Current directory
        'config/backup_credentials.yaml',  # Config subdirectory
        os.path.expanduser('~/.config/backup_credentials.yaml'),  # User's config
        '/etc/odoo/backup_credentials.yaml',  # System-wide config
    ]

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.config = {}
        self.credentials = {}
        self.databases = []
        self.additional_backups = {}
        
        # Load configuration
        config_file = self._find_config_file(self.CONFIG_FILE_PATHS)
        if not config_file:
            available_paths = '\n  - '.join([''] + self.CONFIG_FILE_PATHS)
            raise FileNotFoundError(
                f"No backup_config.yaml found in any of these locations:{available_paths}\n"
                f"Please create a configuration file in one of these locations."
            )
        
        self.logger.info(f"Using configuration file: {config_file}")
        self._load_config(config_file)
        
        # Load credentials if they exist
        creds_file = self._find_config_file(self.CREDENTIALS_FILE_PATHS)
        if creds_file:
            self.logger.info(f"Using credentials file: {creds_file}")
            self._load_credentials(creds_file)
        else:
            self.logger.warning("No credentials file found. Using default settings.")

    def _find_config_file(self, paths: List[str]) -> Optional[str]:
        """Find the first existing configuration file from the given paths."""
        for path in paths:
            if os.path.isfile(path):
                return path
        return None

    def _load_config(self, config_path: Path) -> None:
        """Load configuration from YAML file"""
        try:
            with open(config_path, 'r') as f:
                yaml_config = yaml.safe_load(f)

            # Update global configuration
            self.config.update(yaml_config.get('global', {}))
            
            # Load database configurations
            self.databases = yaml_config.get('databases', [])
            
            # Load additional backup configurations
            self.additional_backups = yaml_config.get('additional_backups', {})

        except Exception as e:
            raise RuntimeError(f"Failed to load configuration: {str(e)}")

    def _load_credentials(self, creds_path: Path) -> None:
        """Load credentials from YAML file"""
        try:
            with open(creds_path, 'r') as f:
                self.credentials = yaml.safe_load(f)
        except Exception as e:
            raise RuntimeError(f"Failed to load credentials: {str(e)}")

    def validate_config(self) -> None:
        """Validate the loaded configuration"""
        required_global = ['backup_root', 'min_disk_space_gb', 'max_retry_attempts']
        for key in required_global:
            if key not in self.config:
                raise ValueError(f"Missing required global configuration: {key}")

        if not self.databases:
            raise ValueError("No database configurations found")

        for db in self.databases:
            required_db = ['name', 'user', 'containers']
            for key in required_db:
                if key not in db:
                    raise ValueError(f"Missing required database configuration: {key}")
            
            if 'database' not in db['containers'] or 'odoo' not in db['containers']:
                raise ValueError(f"Missing container configuration for database: {db['name']}")

class CredentialsManager:
    """Manages secure access to backup encryption credentials"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.credentials = {}
        self.logger = logging.getLogger('credentials_manager')
        self._load_credentials()

    def _load_credentials(self):
        """Load credentials from configuration file"""
        # Check all possible credential file locations
        cred_locations = [
            Path(self.config['credentials']['config_file']),
            *[Path(p) for p in self.config['credentials']['fallback_locations']]
        ]
        
        cred_file = next((p for p in cred_locations if p.exists()), None)
        if not cred_file:
            self.logger.warning("No credentials file found.")
            return

        try:
            # Check file permissions
            stat = cred_file.stat()
            if stat.st_mode & 0o077:  # Check if group or others have any permissions
                self.logger.warning(f"Warning: Insecure permissions on credentials file: {cred_file}")

            with open(cred_file, 'r') as f:
                self.credentials = yaml.safe_load(f)
        except Exception as e:
            self.logger.error(f"Failed to load credentials file: {str(e)}")

    def get_encryption_key(self, backup_type: str, name: str) -> Optional[str]:
        """Get encryption key for a specific backup"""
        try:
            # First try environment variable
            env_key = os.getenv('BACKUP_ENCRYPT_KEY')
            if env_key:
                return env_key

            # Then try the global key from credentials file
            return self.credentials.get('credentials', {}).get('global_key')

        except Exception as e:
            self.logger.error(f"Error retrieving encryption key: {str(e)}")
        
        return None

class BackupManager:
    def __init__(self, config: ConfigurationManager):
        self.config = config
        self._setup_logging()
        self.logger = logging.getLogger('backup_manager')
        self.backup_root = Path(config.config['backup_root'])
        self.metadata_list: List[BackupMetadata] = []
        self.credentials = CredentialsManager(config.config)

    def _setup_logging(self):
        """Configure logging with rotation"""
        log_dir = Path(self.config.config['backup_root']) / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = log_dir / 'backup.log'
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=self.config.config['logging']['max_size_mb'] * 1024 * 1024,
            backupCount=self.config.config['logging']['backup_count']
        )
        file_handler.setFormatter(formatter)
        
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        
        root_logger = logging.getLogger()
        root_logger.setLevel(self.config.config['log_level'])
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)

    def check_disk_space(self, path: Path) -> bool:
        """Check if there's enough disk space available"""
        try:
            total, used, free = shutil.disk_usage(path)
            free_gb = free / (1024**3)
            self.logger.info(f"Free disk space: {free_gb:.2f} GB")
            if free_gb < self.config.config['min_disk_space_gb']:
                self.logger.error(
                    f"Insufficient disk space. Required: {self.config.config['min_disk_space_gb']} GB, "
                    f"Available: {free_gb:.2f} GB"
                )
                return False
            return True
        except Exception as e:
            self.logger.error(f"Error checking disk space: {str(e)}")
            return False

    def verify_backup(self, backup_path: Path) -> bool:
        """Verify the integrity of the backup file"""
        try:
            if backup_path.suffix == '.zst':
                result = subprocess.run(
                    ['zstd', '-t', str(backup_path)],
                    capture_output=True,
                    text=True
                )
                return result.returncode == 0
            elif backup_path.suffix == '.gpg':
                result = subprocess.run(
                    ['gpg', '--list-packets', str(backup_path)],
                    capture_output=True,
                    text=True
                )
                return result.returncode == 0
            return False
        except Exception as e:
            self.logger.error(f"Backup verification failed: {str(e)}")
            return False

    def compress_and_encrypt(self, source_path: Path, output_path: Path, password: str = '', compression_config: Optional[Dict] = None) -> bool:
        """Compress directory with zstd and optionally encrypt"""
        try:
            start_time = time.time()
            
            # Use provided compression config or fall back to global config
            if compression_config is None:
                compression_config = self.config.config['compression']
            
            # Create temporary tar file
            tar_path = output_path.with_suffix('.tar')
            
            # Create tar archive
            self.logger.info(f"Creating tar archive for {source_path}")
            subprocess.run(
                ["tar", "-cf", str(tar_path), "-C", str(source_path.parent), source_path.name],
                check=True
            )

            # Compress with zstd
            self.logger.info("Compressing with zstd")
            zstd_path = output_path.with_suffix('.zst')
            subprocess.run(
                ["zstd", f"-{compression_config['level']}", "-f", str(tar_path), "-o", str(zstd_path)],
                check=True
            )

            # Remove temporary tar file
            tar_path.unlink()

            # Encrypt if password provided
            if password:
                self.logger.info("Encrypting backup")
                final_path = output_path.with_suffix('.gpg')
                subprocess.run(
                    ['gpg', '--symmetric', '--batch', '--passphrase', password, '-o', str(final_path), str(zstd_path)],
                    check=True
                )
                zstd_path.unlink()

            duration = time.time() - start_time
            self.logger.info(f"Compression completed in {duration:.2f} seconds")
            return True

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Compression failed: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error during compression: {str(e)}")
            return False

    def cleanup_old_backups(self, backup_dir: Path, days: int):
        """Remove backups older than specified days"""
        try:
            cutoff_time = time.time() - (days * 86400)
            count = 0
            
            for item in backup_dir.glob("*"):
                if item.is_file() and item.stat().st_mtime < cutoff_time:
                    self.logger.info(f"Removing old backup: {item}")
                    item.unlink()
                    count += 1
            
            self.logger.info(f"Cleaned up {count} old backup files")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {str(e)}")

    def backup_database(self, db_config: Dict[str, Any]) -> bool:
        """Perform database backup with progress tracking and error handling"""
        try:
            start_time = time.time()
            db_name = db_config['name']
            backup_dir = self.backup_root / 'docker' / db_name
            backup_dir.mkdir(parents=True, exist_ok=True)

            if not self.check_disk_space(backup_dir):
                raise Exception("Insufficient disk space")

            # Get encryption key if encryption is enabled
            encryption_key = None
            if db_config.get('encryption', {}).get('enabled', False):
                encryption_key = self.credentials.get_encryption_key('database', db_name)
                if not encryption_key:
                    self.logger.warning(f"Encryption enabled for {db_name} but no key found")

            # Backup PostgreSQL database
            dump_file = backup_dir / 'dump.sql'
            self.logger.info(f"Backing up database {db_name}")
            
            for attempt in range(self.config.config['max_retry_attempts']):
                try:
                    subprocess.run(
                        f"docker exec -i {db_config['containers']['database']} pg_dump -U {db_config['user']} {db_name} > {dump_file}",
                        shell=True, check=True
                    )
                    break
                except subprocess.CalledProcessError as e:
                    if attempt == self.config.config['max_retry_attempts'] - 1:
                        raise
                    self.logger.warning(f"Backup attempt {attempt + 1} failed, retrying...")
                    time.sleep(self.config.config['retry_delay_seconds'])

            # Backup FileStore
            self.logger.info("Backing up FileStore")
            subprocess.run(
                f"docker cp {db_config['containers']['odoo']}:/opt/odoo/data/filestore/{db_name} {backup_dir}/",
                shell=True, check=True
            )

            # Create timestamp and compress
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            final_backup_path = self.backup_root / 'docker' / f"{db_name}_{db_config['containers']['odoo']}_{timestamp}"
            
            if self.compress_and_encrypt(backup_dir, final_backup_path, encryption_key):
                # Verify backup
                if not self.verify_backup(final_backup_path.with_suffix('.gpg' if encryption_key else '.zst')):
                    raise Exception("Backup verification failed")

                # Record metadata
                duration = time.time() - start_time
                size = os.path.getsize(str(final_backup_path.with_suffix('.gpg' if encryption_key else '.zst')))
                
                metadata = BackupMetadata(
                    database_name=db_name,
                    container_name=db_config['containers']['odoo'],
                    timestamp=timestamp,
                    size_bytes=size,
                    duration_seconds=duration,
                    success=True
                )
                self.metadata_list.append(metadata)
                
                # Cleanup
                retention_days = db_config.get('retention_days', 
                                            self.config.config['default_retention_days'])
                self.cleanup_old_backups(self.backup_root / 'docker', retention_days)
                
                self.logger.info(f"Backup completed successfully: {final_backup_path}")
                return True
            
            return False

        except Exception as e:
            self.logger.error(f"Backup failed for {db_name}: {str(e)}")
            self.metadata_list.append(
                BackupMetadata(
                    database_name=db_name,
                    container_name=db_config['containers']['odoo'],
                    timestamp=datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S"),
                    size_bytes=0,
                    duration_seconds=time.time() - start_time,
                    success=False,
                    error_message=str(e)
                )
            )
            return False

    def backup_additional_paths(self):
        """Backup additional configured paths"""
        for name, config in self.config.additional_backups.items():
            if not config.get('enabled', True):
                continue

            try:
                source_path = Path(config['source_path'])
                if not source_path.exists():
                    self.logger.warning(f"Skipping {name} backup: path does not exist: {source_path}")
                    continue

                # Get encryption key if encryption is enabled
                encryption_key = None
                if config.get('encryption', {}).get('enabled', False):
                    encryption_key = self.credentials.get_encryption_key('additional', name)
                    if not encryption_key:
                        self.logger.warning(f"Encryption enabled for {name} but no key found")

                timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                backup_path = self.backup_root / name / f"{name}_{timestamp}"
                backup_path.parent.mkdir(parents=True, exist_ok=True)

                self.logger.info(f"Backing up {name} from {source_path}")
                compression_config = config.get('compression', self.config.config['compression'])
                self.compress_and_encrypt(source_path, backup_path, encryption_key, compression_config)
                
                retention_days = config.get('retention_days', self.config.config['default_retention_days'])
                self.cleanup_old_backups(backup_path.parent, retention_days)

            except Exception as e:
                self.logger.error(f"Failed to backup {name}: {str(e)}")

    def save_metadata(self):
        """Save backup metadata to a CSV file"""
        try:
            metadata_file = self.backup_root / 'backup_metadata.csv'
            with open(metadata_file, 'a', newline='') as f:
                writer = csv.writer(f)
                for metadata in self.metadata_list:
                    writer.writerow([
                        metadata.database_name,
                        metadata.container_name,
                        metadata.timestamp,
                        metadata.size_bytes,
                        metadata.duration_seconds,
                        metadata.success,
                        metadata.error_message or ''
                    ])
        except Exception as e:
            self.logger.error(f"Failed to save metadata: {str(e)}")

def main():
    """Main execution function"""
    try:
        # Initialize configuration
        config_manager = ConfigurationManager()
        
        # Load and validate configuration
        config_manager.validate_config()
        
        # Initialize backup manager
        backup_manager = BackupManager(config_manager)
        
        # Process database backups
        for db_config in config_manager.databases:
            logger.info(f"Processing backup for database: {db_config['name']}")
            try:
                backup_manager.backup_database(db_config)
            except Exception as db_error:
                logger.error(f"Error processing database {db_config['name']}: {str(db_error)}")
                continue
        
        # Process additional backups
        backup_manager.backup_additional_paths()
        
        # Save metadata
        backup_manager.save_metadata()

    except FileNotFoundError as e:
        logger.error(f"Configuration error: {str(e)}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Critical error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
