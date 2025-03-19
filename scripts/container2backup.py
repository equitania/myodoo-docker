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
import tempfile
import shutil

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
    Creates a backup with proper file structure
    """
    docker_backup_path = os.path.join(backup_path, 'docker')
    output_file = f'{docker_backup_path}/{db_name}_{data_container}_dockerbackup_{timestamp}.7z'
    encryption_enabled, password = get_encryption_settings()
    compression_level = config.get('defaults', {}).get('compression', {}).get('level', 5)
    
    # Create temp directory for backup preparation
    temp_dir = tempfile.mkdtemp()
    try:
        print(f"Creating backup for {db_name} in {data_container}")
        
        # 1. Export SQL dump to file
        dump_file = os.path.join(temp_dir, "dump.sql")
        print(f"Creating database dump for {db_name}")
        dump_proc = subprocess.run(
            ['docker', 'exec', sql_container, 'pg_dump', '-U', db_user, db_name],
            stdout=open(dump_file, 'wb'),
            stderr=subprocess.PIPE,
            check=False
        )
        
        if dump_proc.returncode != 0:
            print(f"Error creating database dump for {db_name}")
            if dump_proc.stderr:
                print(f"pg_dump error: {dump_proc.stderr.decode()}")
            return False
            
        # 2. Export filestore directly with database name as root
        # No "filestore" parent directory
        print(f"Backing up filestore for {db_name}")
        
        # First check if filestore exists in container
        check_proc = subprocess.run(
            ['docker', 'exec', data_container, 'ls', '-la', f'/opt/odoo/data/filestore/{db_name}'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False
        )
        
        if check_proc.returncode != 0:
            print(f"Warning: Filestore for {db_name} not found in container")
            print(check_proc.stderr.decode())
        else:
            # Extract filestore to temp directory - directly using db_name without filestore prefix
            filestore_dir = os.path.join(temp_dir, db_name)
            os.makedirs(filestore_dir)
            
            filestore_proc = subprocess.run(
                ['docker', 'exec', data_container, 'tar', 'c', '-C', '/opt/odoo/data/filestore', db_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False
            )
            
            if filestore_proc.returncode != 0:
                print(f"Error accessing filestore for {db_name}")
                if filestore_proc.stderr:
                    print(f"Filestore error: {filestore_proc.stderr.decode()}")
            else:
                # Extract tar to root of temp directory (not to filestore subdirectory)
                extract_proc = subprocess.run(
                    ['tar', 'x', '-C', temp_dir],
                    input=filestore_proc.stdout,
                    stderr=subprocess.PIPE,
                    check=False
                )
                
                if extract_proc.returncode != 0:
                    print(f"Error extracting filestore for {db_name}")
                    if extract_proc.stderr:
                        print(f"Extract error: {extract_proc.stderr.decode()}")
        
        # 3. Create 7z archive from temp directory
        print(f"Creating final archive {output_file}")
        zip_args = ['7z', 'a', f'-mx={compression_level}', '-t7z']
        if encryption_enabled:
            zip_args.extend(['-p' + password, '-mhe=on'])
        zip_args.extend([output_file, temp_dir + "/*"])
        
        result = subprocess.run(zip_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        if result.returncode != 0:
            print(f"Error creating archive for {db_name}")
            if result.stderr:
                print(f"7z error: {result.stderr.decode()}")
            return False
            
        print(f"Backup for {db_name} completed successfully")
        return True
        
    except Exception as e:
        print(f"Unexpected error during backup of {db_name}: {str(e)}")
        return False
    finally:
        # Clean up temp directory
        shutil.rmtree(temp_dir)

def backup_additional_service(service_config, base_backup_path, timestamp):
    """
    Creates backup for additional services like nginx, letsencrypt, etc.
    """
    if not service_config.get('enabled', True):
        return

    source_path = os.path.expandvars(os.path.expanduser(service_config['source_path']))
    if not os.path.exists(source_path):
        print(f"Source path {source_path} does not exist, skipping backup.")
        return

    backup_subdir = service_config['backup_path']
    backup_path = os.path.join(base_backup_path, backup_subdir)
    encryption_enabled, password = get_encryption_settings()
    
    if not os.path.exists(backup_path):
        os.makedirs(backup_path, exist_ok=True)

    output_file = f'{backup_path}/{backup_subdir}_{timestamp}.7z'
    
    # Build 7zip command with compression level
    compression_level = config.get('defaults', {}).get('compression', {}).get('level', 5)
    zip_args = ['7z', 'a', f'-mx={compression_level}', '-t7z']
    if encryption_enabled:
        zip_args.extend(['-p' + password, '-mhe=on'])
    zip_args.extend([output_file, source_path])
    
    print(f"Creating backup for {backup_subdir}")
    result = subprocess.run(zip_args, capture_output=True, text=True)
    
    if result.returncode == 0:
        print(f"Backup created for {backup_subdir}" + (" (encrypted)" if encryption_enabled else ""))
    else:
        print(f"Error creating backup for {backup_subdir}")
        if result.stderr:
            print(f"Error details: {result.stderr}")

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

def backup_fast_report(db_name, fast_report_config, backup_path, timestamp):
    """
    Creates a separate backup for FastReport files
    """
    if not fast_report_config.get('enabled', False):
        return False
        
    report_path = fast_report_config.get('path')
    if not report_path:
        print(f"Warning: FastReport enabled for {db_name} but no path specified")
        return False
        
    report_path = os.path.expandvars(os.path.expanduser(report_path))
    if not os.path.exists(report_path):
        print(f"Warning: FastReport path {report_path} does not exist")
        return False
        
    docker_backup_path = os.path.join(backup_path, 'docker')
    output_file = f'{docker_backup_path}/{db_name}_FastReport_{timestamp}.7z'
    encryption_enabled, password = get_encryption_settings()
    compression_level = config.get('defaults', {}).get('compression', {}).get('level', 5)
    
    print(f"Creating FastReport backup for {db_name} from {report_path}")
    zip_args = ['7z', 'a', f'-mx={compression_level}', '-t7z']
    if encryption_enabled:
        zip_args.extend(['-p' + password, '-mhe=on'])
    zip_args.extend([output_file, report_path])
    
    result = subprocess.run(zip_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    if result.returncode != 0:
        print(f"Error creating FastReport backup for {db_name}")
        if result.stderr:
            print(f"7z error: {result.stderr.decode()}")
        return False
        
    print(f"FastReport backup for {db_name} completed successfully")
    return True

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
        
        # Create database backup
        create_backup(
            db_name, 
            db_user, 
            sql_container, 
            data_container, 
            backup_path, 
            timestamp,
            additional_paths
        )
        
        # Create FastReport backup if configured
        fast_report = db.get('fast_report', {})
        if fast_report:
            backup_fast_report(db_name, fast_report, backup_path, timestamp)
        
    # Process additional backups
    timestamp = datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d_%H-%M-%S')
    additional_backups = config.get('services', {})

    for service_name, service_config in additional_backups.items():
        backup_additional_service(service_config, backup_path, timestamp)
        
        # Clean up old backups for this service
        service_backup_path = os.path.join(backup_path, service_config['backup_path'])
        service_retention = service_config.get('retention_days', default_retention)
        service_cutoff = time.time() - (float(service_retention) * 86400)
        cleanup_backups(service_backup_path, service_cutoff)
    
    # Process rsync commands from YAML config
    rsync_config = config.get('rsync', {})
    if rsync_config.get('enabled', False):
        print("Executing rsync commands...")
        rsync_commands = rsync_config.get('commands', [])
        for cmd in rsync_commands:
            print(f"Running: {cmd}")
            subprocess.run(cmd, shell=True, check=False)
            
except yaml.YAMLError as e:
    print(f"Error reading YAML configuration: {str(e)}")
    exit(1)
except KeyError as e:
    print(f"Missing required configuration field: {str(e)}")
    exit(1)

print('Backup completed!')
