#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
Odoo Backup Manager Script
Version 1.0.0
Date 2025-01-08

This script provides utilities for managing Odoo backup files:
1. List available backups
2. Check backup integrity
3. Decrypt backup files
4. Decompress backup files
5. Extract and restore backup contents

Author: Equitania Software GmbH
License: GNU Affero General Public License v3
"""

import os
import sys
import yaml
import zstd
import argparse
import logging
from typing import Optional, Dict, List
from datetime import datetime
from pathlib import Path
from cryptography.fernet import Fernet
import tarfile
import csv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class BackupManager:
    def __init__(self, backup_root: str, config_file: Optional[str] = None):
        self.backup_root = Path(backup_root)
        self.config = self._load_config(config_file) if config_file else {}
        self.encryption_key = self._get_encryption_key()

    def _load_config(self, config_file: str) -> Dict:
        """Load configuration from YAML file"""
        try:
            with open(config_file, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to load config file: {str(e)}")
            return {}

    def _get_encryption_key(self) -> Optional[bytes]:
        """Get encryption key from environment or config"""
        key = os.getenv('BACKUP_ENCRYPT_KEY')
        if not key and self.config:
            key = self.config.get('encryption', {}).get('key')
        return key.encode() if key else None

    def list_backups(self, days: Optional[int] = None) -> List[Dict]:
        """List all available backups, optionally filtered by age"""
        backups = []
        try:
            metadata_file = self.backup_root / 'backup_metadata.csv'
            if metadata_file.exists():
                with open(metadata_file, 'r') as f:
                    reader = csv.reader(f)
                    for row in reader:
                        backup = {
                            'database': row[0],
                            'container': row[1],
                            'timestamp': row[2],
                            'path': row[3],
                            'size': row[4],
                            'duration': row[5],
                            'success': row[6]
                        }
                        if days:
                            backup_date = datetime.fromisoformat(backup['timestamp'])
                            age = (datetime.now() - backup_date).days
                            if age <= days:
                                backups.append(backup)
                        else:
                            backups.append(backup)
            return backups
        except Exception as e:
            logger.error(f"Error listing backups: {str(e)}")
            return []

    def check_backup(self, backup_path: str) -> bool:
        """Check if a backup file is valid and can be decrypted/decompressed"""
        try:
            path = Path(backup_path)
            if not path.exists():
                logger.error(f"Backup file not found: {backup_path}")
                return False

            # Try to read and decompress
            with open(path, 'rb') as f:
                data = f.read()

            if self.encryption_key:
                fernet = Fernet(self.encryption_key)
                data = fernet.decrypt(data)

            decompressed = zstd.decompress(data)
            logger.info(f"Backup file {backup_path} is valid")
            return True

        except Exception as e:
            logger.error(f"Backup file {backup_path} is invalid: {str(e)}")
            return False

    def decrypt_and_decompress(self, backup_path: str, output_path: Optional[str] = None) -> Optional[str]:
        """Decrypt and decompress a backup file"""
        try:
            input_path = Path(backup_path)
            if not input_path.exists():
                logger.error(f"Backup file not found: {backup_path}")
                return None

            if not output_path:
                output_path = input_path.with_suffix('.tar')
            output_path = Path(output_path)

            # Read and process the file
            with open(input_path, 'rb') as f:
                data = f.read()

            if self.encryption_key:
                logger.info("Decrypting backup...")
                fernet = Fernet(self.encryption_key)
                data = fernet.decrypt(data)

            logger.info("Decompressing backup...")
            decompressed = zstd.decompress(data)

            with open(output_path, 'wb') as f:
                f.write(decompressed)

            logger.info(f"Backup extracted to: {output_path}")
            return str(output_path)

        except Exception as e:
            logger.error(f"Failed to process backup: {str(e)}")
            return None

    def extract_backup(self, tar_path: str, extract_path: Optional[str] = None) -> Optional[str]:
        """Extract contents of a backup tar file"""
        try:
            input_path = Path(tar_path)
            if not input_path.exists():
                logger.error(f"Tar file not found: {tar_path}")
                return None

            if not extract_path:
                extract_path = input_path.parent / input_path.stem
            extract_path = Path(extract_path)
            extract_path.mkdir(parents=True, exist_ok=True)

            with tarfile.open(tar_path, 'r') as tar:
                tar.extractall(path=extract_path)

            logger.info(f"Backup contents extracted to: {extract_path}")
            return str(extract_path)

        except Exception as e:
            logger.error(f"Failed to extract backup: {str(e)}")
            return None

def print_readme():
    """Print detailed readme information"""
    readme = """
Odoo Backup Manager
==================
Version 1.0.0
Date: 2025-01-08

A utility for managing Odoo backup files created by container2backup_zstd.py.

Features
--------
1. List available backups with detailed information
2. Check backup integrity
3. Decrypt and decompress backup files
4. Extract backup contents

Usage
-----
General syntax:
    backup_manager.py --backup-root BACKUP_DIR [--config CONFIG_FILE] COMMAND [options]

Required Arguments:
    --backup-root DIR    Root directory containing the backups
    --config FILE        (Optional) Path to configuration file

Commands:
    list                 List available backups
    check               Check backup integrity
    extract             Decrypt and extract backup contents

1. List Backups
--------------
Lists all available backups with their details.

Usage:
    backup_manager.py --backup-root DIR list [--days DAYS]

Options:
    --days N            Only show backups from the last N days

Example:
    backup_manager.py --backup-root /opt/backups list --days 7

2. Check Backup
--------------
Verify if a backup file is valid and can be decrypted/decompressed.

Usage:
    backup_manager.py --backup-root DIR check BACKUP_FILE

Example:
    backup_manager.py --backup-root /opt/backups check /opt/backups/mydb_2025-01-08.zst

3. Extract Backup
---------------
Decrypt, decompress, and extract a backup file.

Usage:
    backup_manager.py --backup-root DIR extract BACKUP_FILE [--output OUTPUT_DIR]

Options:
    --output DIR        Directory to extract the backup to (optional)

Example:
    backup_manager.py --backup-root /opt/backups extract /opt/backups/mydb_2025-01-08.zst --output /tmp/restore

Environment Variables
-------------------
BACKUP_ENCRYPT_KEY    Encryption key for encrypted backups
                     Required if backups are encrypted

Configuration File
----------------
The configuration file (if provided) should be in YAML format and can contain:
- Encryption settings
- Backup paths
- Other backup-related configurations

Example config.yaml:
    encryption:
        key: "your-encryption-key"
    backup_root: "/opt/backups"

Notes
-----
1. For encrypted backups, either set BACKUP_ENCRYPT_KEY environment variable
   or provide the key in the configuration file
2. Backup files are expected to be compressed with zstd
3. Extracted backups will contain:
   - Database dump (dump.sql)
   - FileStore contents
   - Additional backed up paths

For more information or bug reports, please contact:
Equitania Software GmbH
License: GNU Affero General Public License v3
"""
    print(readme)

def main():
    parser = argparse.ArgumentParser(
        description='Odoo Backup Manager - A utility for managing Odoo backup files',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    # Add --help-full option
    parser.add_argument('--help-full', action='store_true', 
                       help='Show detailed help information')
    
    parser.add_argument('--backup-root', required=True, help='Root directory for backups')
    parser.add_argument('--config', help='Path to configuration file')
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # List command
    list_parser = subparsers.add_parser('list', 
                                       help='List available backups',
                                       description='List all available backups with their details')
    list_parser.add_argument('--days', type=int, help='Filter backups by age in days')
    
    # Check command
    check_parser = subparsers.add_parser('check', 
                                        help='Check backup integrity',
                                        description='Verify if a backup file is valid and can be decrypted/decompressed')
    check_parser.add_argument('backup_path', help='Path to backup file')
    
    # Extract command
    extract_parser = subparsers.add_parser('extract', 
                                          help='Decrypt and extract backup',
                                          description='Decrypt, decompress, and extract a backup file')
    extract_parser.add_argument('backup_path', help='Path to backup file')
    extract_parser.add_argument('--output', help='Output directory (optional)')
    
    args = parser.parse_args()
    
    # Show full help if requested
    if args.help_full:
        print_readme()
        sys.exit(0)
    
    # Initialize backup manager
    manager = BackupManager(args.backup_root, args.config)
    
    try:
        if args.command == 'list':
            backups = manager.list_backups(args.days)
            if backups:
                print("\nAvailable backups:")
                for backup in backups:
                    print(f"\nDatabase: {backup['database']}")
                    print(f"Container: {backup['container']}")
                    print(f"Timestamp: {backup['timestamp']}")
                    print(f"Path: {backup['path']}")
                    print(f"Size: {backup['size']}")
                    print(f"Duration: {backup['duration']}s")
                    print(f"Success: {backup['success']}")
            else:
                print("No backups found")
                
        elif args.command == 'check':
            if manager.check_backup(args.backup_path):
                print("Backup file is valid")
            else:
                print("Backup file is invalid")
                sys.exit(1)
                
        elif args.command == 'extract':
            # First decrypt and decompress
            tar_path = manager.decrypt_and_decompress(args.backup_path)
            if tar_path:
                # Then extract the contents
                extract_path = manager.extract_backup(tar_path, args.output)
                if extract_path:
                    print(f"Backup extracted to: {extract_path}")
                else:
                    print("Failed to extract backup contents")
                    sys.exit(1)
            else:
                print("Failed to decrypt and decompress backup")
                sys.exit(1)
                
    except Exception as e:
        logger.error(f"Command failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
