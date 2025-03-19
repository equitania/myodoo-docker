#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Script to backup Odoo database including FileStore under Docker
# Version 4.0.0
# Date 19.03.2025
################################################################################
#    Shell Script for Odoo, Open Source Management Solution
#    Copyright (C) 2014-now Equitania Software GmbH(<http://www.equitania.de>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################

import os
import io
import csv
import datetime, time
import os.path
import subprocess
from os.path import expanduser
import yaml  # Add this import at the top
from dotenv import load_dotenv

def compress_with_7zip(source_dir, output_file):
    """
    Compresses a directory using 7-Zip
    """
    try:
        # Check if 7z is installed
        subprocess.run(['7z', '--help'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        
        # Compress with 7-Zip
        cmd = ['7z', 'a', '-tzip', output_file, source_dir]
        subprocess.run(cmd, check=True)
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        print("Error: 7-Zip is not installed or command failed.")
        print("Please install 7-Zip with: sudo apt-get install p7zip-full")
        return False

def cleanup_backups(cleanup_path, cutoff_days):
    """
    Deletes files older than cutoff_days
    """
    if not os.path.exists(cleanup_path):
        print(f"Directory {cleanup_path} does not exist.")
        return
        
    files = os.listdir(cleanup_path)
    for file in files:
        file_path = os.path.join(cleanup_path, file)
        if os.path.isfile(file_path):
            t = os.stat(file_path)
            c = t.st_ctime
            # Delete file if older than cutoff_days
            if c < cutoff_days:
                print("Deleting: " + file_path)
                os.remove(file_path)

def get_encryption_settings():
    """
    Gets encryption settings from .env file
    """
    load_dotenv()
    enabled = os.getenv('BACKUP_ENCRYPTION_ENABLED', 'false').lower() == 'true'
    password = os.getenv('BACKUP_PASSWORD', '')
    
    if enabled and not password:
        print("WARNING: Encryption enabled but no password set in .env file")
        enabled = False
    
    return enabled, password

def create_backup(db_name, db_user, sql_container, data_container, backup_path, timestamp, additional_paths=None):
    """
    Creates a backup directly to 7zip archive without temporary storage
    """
    # Check if container exists and is running
    try:
        container_check = subprocess.run(
            ['docker', 'container', 'inspect', sql_container],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True
        )
    except subprocess.CalledProcessError:
        print(f"Error: Container {sql_container} does not exist or is not running")
        return False

    output_file = f'{backup_path}/{db_name}_{data_container}_dockerbackup_{timestamp}.7z'
    encryption_enabled, password = get_encryption_settings()
    
    try:
        # Test database connection first
        test_connection = subprocess.run(
            ['docker', 'exec', '-i', sql_container, 'psql', '-U', db_user, '-d', db_name, '-c', 'SELECT 1'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True
        )
        
        # Base 7zip command with compression level
        compression_level = config.get('defaults', {}).get('compression', {}).get('level', 5)
        zip_args = ['7z', 'a', '-si', f'-mx={compression_level}', '-t7z']
        if encryption_enabled:
            zip_args.extend(['-p' + password, '-mhe=on'])
        zip_args.extend([output_file, f'dump.sql'])
        
        # Create new 7zip archive with database dump
        with subprocess.Popen(zip_args, stdin=subprocess.PIPE) as zip_proc:
            dump_proc = subprocess.Popen(
                ['docker', 'exec', '-i', sql_container, 'pg_dump', '-U', db_user, db_name],
                stdout=zip_proc.stdin,
                stderr=subprocess.PIPE
            )
            _, stderr = dump_proc.communicate()
            if dump_proc.returncode != 0:
                print(f"Error creating database dump for {db_name}")
                if stderr:
                    print(f"pg_dump error: {stderr.decode()}")
                return False
        
        # Add filestore with encryption if enabled
        filestore_proc = subprocess.Popen(
            ['docker', 'exec', sql_container, 'tar', 'c', '-C', f'/opt/odoo/data/filestore', db_name],
            stdout=subprocess.PIPE
        )
        
        zip_args = ['7z', 'a', '-si', '-t7z']
        if encryption_enabled:
            zip_args.extend(['-p' + password, '-mhe=on'])
        zip_args.extend([output_file, f'filestore/{db_name}'])
        
        zip_proc = subprocess.Popen(zip_args, stdin=filestore_proc.stdout)
        zip_proc.communicate()
        
        # Add additional paths if configured
        if additional_paths:
            for path_name, path_config in additional_paths.items():
                if not path_config.get('enabled', True):
                    continue
                    
                source_path = path_config['source_path']
                if not os.path.exists(source_path):
                    print(f"Additional path {source_path} for {db_name} does not exist, skipping.")
                    continue
                
                backup_subdir = path_config.get('backup_subdir', path_name)
                result = subprocess.run(
                    ['7z', 'a', '-tzip', output_file, source_path, f'-w{backup_subdir}'],
                    check=False
                )
                if result.returncode == 0:
                    print(f"Added {path_name} to backup for {db_name}")
                else:
                    print(f"Error adding {path_name} to backup for {db_name}")
        
        if zip_proc.returncode == 0:
            print(f'Backup completed for {data_container}')
            return True
        else:
            print(f'Error creating backup for {data_container}')
            return False
            
    except subprocess.CalledProcessError as e:
        print(f"Error during backup process for {db_name}:")
        print(f"Command '{e.cmd}' failed with error: {e.stderr.decode()}")
        return False
    except Exception as e:
        print(f"Unexpected error during backup of {db_name}: {str(e)}")
        return False

def backup_additional_service(service_config, base_backup_path, timestamp):
    """
    Creates backup for additional services like nginx, letsencrypt, etc.
    """
    if not service_config.get('enabled', True):
        return

    # Expand environment variables in source path
    source_path = os.path.expandvars(os.path.expanduser(service_config['source_path']))
    if not os.path.exists(source_path):
        print(f"Source path {source_path} does not exist, skipping backup.")
        return

    backup_subdir = service_config['backup_path']
    backup_path = os.path.join(base_backup_path, backup_subdir)
    encryption_enabled, password = get_encryption_settings()
    
    if not os.path.exists(backup_path):
        os.makedirs(backup_path, exist_ok=True)

    output_zip = f'{backup_path}/{backup_subdir}_{timestamp}.zip'
    
    # Build 7zip command with compression level
    compression_level = config.get('defaults', {}).get('compression', {}).get('level', 5)
    zip_args = ['7z', 'a', f'-mx={compression_level}', '-tzip']
    if encryption_enabled:
        zip_args.extend(['-p' + password, '-mhe=on'])
    zip_args.extend([output_zip, source_path])
    
    result = subprocess.run(zip_args, check=False)
    
    if result.returncode == 0:
        print(f"Backup created for {backup_subdir}" + (" (encrypted)" if encryption_enabled else ""))
    else:
        print(f"Error creating backup for {backup_subdir}")

def check_paths(config):
    """
    Validates all configured paths and returns list of issues
    """
    issues = []
    
    # Expand environment variables in paths
    def expand_path(path):
        """Helper function to expand environment variables and user home in paths"""
        expanded = os.path.expandvars(os.path.expanduser(path))
        return expanded
    
    # Check service paths (nginx, letsencrypt, docker-builds)
    for service, service_config in config.get('services', {}).items():
        if not service_config.get('enabled', True):
            continue
            
        source_path = service_config.get('source_path')
        if not source_path:
            issues.append(f"No source_path configured for service {service}")
        else:
            # Expand the path before checking
            expanded_path = expand_path(source_path)
            if not os.path.exists(expanded_path):
                issues.append(f"Source path {expanded_path} for service {service} does not exist")
    
    # Check database fast-report paths
    for db in config.get('databases', []):
        db_name = db.get('name', 'unknown')
        fast_report = db.get('fast_report', {})
        
        if fast_report.get('enabled', False):
            report_path = fast_report.get('path')
            if not report_path:
                issues.append(f"No fast-report path configured for database {db_name}")
            else:
                # Expand the path before checking
                expanded_path = expand_path(report_path)
                if not os.path.exists(expanded_path):
                    issues.append(f"Fast-report path {expanded_path} for database {db_name} does not exist")
    
    return issues

# Main script
base_path = expanduser("~")
backup_config = base_path + '/container2backup.yaml'

# Read YAML config file and create backups
if not os.path.exists(backup_config):
    print(f"Backup configuration file {backup_config} not found!")
    exit(1)

try:
    with open(backup_config, 'r', encoding="utf8") as config_file:
        config = yaml.safe_load(config_file)
    
    # Get backup path from config or use default
    backup_path = os.path.expandvars(os.path.expanduser(
        config.get('defaults', {}).get('backup_path', '/opt/backups')
    ))
    
    # Create directories if they don't exist
    if not os.path.exists(backup_path):
        try:
            os.makedirs(backup_path, exist_ok=True)
        except PermissionError:
            print(f"Error: No permission to create {backup_path}")
            exit(1)

    # Create service-specific backup directories
    for service_dir in ['nginx', 'docker-builds', 'docker']:
        service_path = os.path.join(backup_path, service_dir)
        if not os.path.exists(service_path):
            os.makedirs(service_path, exist_ok=True)

    print("Backup path: " + backup_path)

    # Validate paths before starting backup
    path_issues = check_paths(config)
    if path_issues:
        print("WARNING: The following issues were found:")
        for issue in path_issues:
            print(f"- {issue}")
        
        # Optional: Ask for confirmation to continue
        response = input("Do you want to continue anyway? (y/N): ")
        if response.lower() != 'y':
            print("Backup aborted.")
            exit(1)
    
    # Get default settings
    defaults = config.get('defaults', {})
    default_retention = defaults.get('retention_days', 14)
    default_db_user = defaults.get('db_user', 'ownerp')
    
    # Get default additional paths
    default_additional_paths = defaults.get('additional_paths', {})
    
    # Process each database
    for db in config.get('databases', []):
        db_name = db['name']
        db_user = db.get('db_user', default_db_user)
        sql_container = db['sql_container']
        data_container = db['data_container']
        retention_days = db.get('retention_days', default_retention)
        
        print(f"\nProcessing backup for database {db_name}")
        print(f"Using container: {sql_container}")
        
        # Merge default and database-specific additional paths
        additional_paths = {}
        for path_name, default_path_config in default_additional_paths.items():
            additional_paths[path_name] = default_path_config.copy()
            
        db_additional_paths = db.get('additional_paths', {})
        for path_name, path_config in db_additional_paths.items():
            if path_name in additional_paths:
                additional_paths[path_name].update(path_config)
            else:
                additional_paths[path_name] = path_config
        
        # Create timestamp for backup
        ts = time.time()
        timestamp = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H-%M-%S')
        
        # Create backup
        create_backup(
            db_name, 
            db_user, 
            sql_container, 
            data_container, 
            backup_path, 
            timestamp,
            additional_paths
        )
        
    # Process additional backups
    timestamp = datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d_%H-%M-%S')
    additional_backups = config.get('additional_backups', {})

    for service_name, service_config in additional_backups.items():
        backup_additional_service(service_config, backup_path, timestamp)
        
        # Clean up old backups for this service
        service_backup_path = os.path.join(backup_path, service_config['backup_path'])
        service_retention = service_config.get('retention_days', default_retention)
        service_cutoff = now - (float(service_retention) * 86400)
        cleanup_backups(service_backup_path, service_cutoff)
        
except yaml.YAMLError as e:
    print(f"Error reading YAML configuration: {str(e)}")
    exit(1)
except KeyError as e:
    print(f"Missing required configuration field: {str(e)}")
    exit(1)

# Process rsync targets
fname_rsync = base_path + '/rsync_targets.csv'
print('Starting Rsync: ' + fname_rsync)
if os.path.isfile(fname_rsync):
    with io.open(fname_rsync, 'r', encoding="utf8") as csvfile:
        _reader_sync = csv.reader(csvfile, delimiter=",")
        for row in _reader_sync:
            if not row or row[0].startswith('#'):
                continue
            else:
                os.system(row[0])

print('Backup completed!')
