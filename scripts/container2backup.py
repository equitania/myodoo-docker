#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Script to backup Odoo database including FileStore under Docker
# Version 4.1.0
# Date 19.04.2025
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
import platform

def check_compression_tools():
    """
    Checks which compression tools are available
    
    Returns:
        dict: Dictionary containing availability of compression tools
    """
    tools = {
        '7z': False,
        '7zz': False,
        'zip': False,
        'gzip': False,
        'zstd': False
    }
    
    # Check 7z
    try:
        subprocess.run(['7z', '--help'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        tools['7z'] = True
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
        
    # Check 7zz (newer 7-Zip)
    try:
        subprocess.run(['7zz', '--help'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        tools['7zz'] = True
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
        
    # Check zip
    try:
        subprocess.run(['zip', '--help'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        tools['zip'] = True
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
        
    # Check gzip
    try:
        subprocess.run(['gzip', '--help'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        tools['gzip'] = True
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
        
    # Check zstd
    try:
        subprocess.run(['zstd', '--help'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        tools['zstd'] = True
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
        
    return tools

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

def cleanup_backups(cleanup_path, cutoff_timestamp):
    """
    Deletes files older than cutoff_timestamp
    """
    if not os.path.exists(cleanup_path):
        print(f"Directory {cleanup_path} does not exist.")
        return
    
    deleted_count = 0
    checked_count = 0
    
    print(f"Checking backups in {cleanup_path} with cutoff date: {datetime.datetime.fromtimestamp(cutoff_timestamp).strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Define supported extensions to check
    extensions = ['.7z', '.zip', '.tar.gz', '.tar.zst']
    
    files = os.listdir(cleanup_path)
    for file in files:
        file_path = os.path.join(cleanup_path, file)
        if os.path.isfile(file_path):
            # Check if file has any of the supported extensions
            has_supported_ext = False
            for ext in extensions:
                if file.endswith(ext):
                    has_supported_ext = True
                    break
                    
            if not has_supported_ext:
                continue
                
            checked_count += 1
            file_mtime = os.path.getmtime(file_path)  # Use modification time instead of creation time
            file_date = datetime.datetime.fromtimestamp(file_mtime).strftime('%Y-%m-%d %H:%M:%S')
            
            if file_mtime < cutoff_timestamp:
                print(f"Deleting: {file_path} (date: {file_date})")
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except Exception as e:
                    print(f"Error deleting {file_path}: {str(e)}")
            else:
                print(f"Keeping:  {file_path} (date: {file_date})")
    
    print(f"Cleanup completed: {deleted_count} files deleted out of {checked_count} checked")

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
    # Set output_file_base without extension as the extension will be determined by the compression format
    output_file_base = f'{docker_backup_path}/{db_name}_{data_container}_dockerbackup_{timestamp}'
    
    # Use configured temp path or fall back to system default
    temp_base = os.path.expandvars(os.path.expanduser(
        config.get('defaults', {}).get('temp_path', '')
    ))
    
    # Create temp directory for backup preparation
    if temp_base and os.path.exists(temp_base):
        # Create a unique subdirectory in the configured base temp path
        timestamp_dir = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        temp_dir = os.path.join(temp_base, f"{db_name}_{timestamp_dir}")
        os.makedirs(temp_dir, exist_ok=True)
        print(f"Using configured temporary directory: {temp_dir}")
        custom_temp = True
    else:
        # Use system default temp directory
        temp_dir = tempfile.mkdtemp()
        custom_temp = False
        print(f"Using system temporary directory: {temp_dir}")
    
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
            
            # GEÄNDERT: Verwenden eines direkten Pipes, um Speicher zu sparen
            print(f"Extracting filestore for {db_name} using streaming")
            extract_cmd = f"docker exec {data_container} tar c -C /opt/odoo/data/filestore {db_name} | tar x -C {temp_dir}"
            
            extract_result = subprocess.run(
                extract_cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False
            )
            
            if extract_result.returncode != 0:
                print(f"Error extracting filestore for {db_name}")
                if extract_result.stderr:
                    extract_error = extract_result.stderr.decode()
                    print(f"Extract error: {extract_error}")
                    # Prüfen, ob es sich um ein Speicherproblem handelt
                    if "Killed" in extract_error or "Cannot allocate memory" in extract_error:
                        print("The process was killed due to memory constraints.")
                        print("Consider running the backup with nohup or in a screen/tmux session with lower priority.")
        
        # 3. Compress directory with configured format
        output_file = compress_directory(temp_dir, output_file_base, config)
        
        if not output_file:
            return False
        
        print(f"Backup for {db_name} completed successfully")
        return True
        
    except Exception as e:
        print(f"Unexpected error during backup of {db_name}: {str(e)}")
        return False
    finally:
        # Clean up temp directory
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            print(f"Cleaned up temporary directory: {temp_dir}")

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
    
    if not os.path.exists(backup_path):
        os.makedirs(backup_path, exist_ok=True)

    # Create output file base (without extension)
    output_file_base = f'{backup_path}/{backup_subdir}_{timestamp}'
    
    print(f"Creating backup for {backup_subdir}")
    output_file = compress_directory(source_path, output_file_base, config)
    
    if output_file:
        print(f"Backup created for {backup_subdir}")
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
    # Create output file base (without extension)
    output_file_base = f'{docker_backup_path}/{db_name}_FastReport_{timestamp}'
    
    print(f"Creating FastReport backup for {db_name} from {report_path}")
    
    output_file = compress_directory(report_path, output_file_base, config)
    
    if not output_file:
        return False
        
    print(f"FastReport backup for {db_name} completed successfully")
    return True

def cleanup_backups_by_pattern(cleanup_path, cutoff_timestamp, pattern):
    """
    Deletes files matching the pattern and older than cutoff_timestamp
    """
    if not os.path.exists(cleanup_path):
        print(f"Directory {cleanup_path} does not exist.")
        return
    
    deleted_count = 0
    checked_count = 0
    
    print(f"Checking backups matching '{pattern}' in {cleanup_path}")
    print(f"Cutoff date: {datetime.datetime.fromtimestamp(cutoff_timestamp).strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Define supported extensions to check
    extensions = ['.7z', '.zip', '.tar.gz', '.tar.zst']
    
    # Get all files in directory
    all_files = os.listdir(cleanup_path)
    
    # Filter files that match the pattern and have one of the supported extensions
    files = []
    for file in all_files:
        if file.startswith(pattern):
            # Check if file has any of the supported extensions
            has_supported_ext = False
            for ext in extensions:
                if file.endswith(ext):
                    has_supported_ext = True
                    break
            
            if has_supported_ext:
                files.append(file)
    
    for file in files:
        file_path = os.path.join(cleanup_path, file)
        if os.path.isfile(file_path):
            checked_count += 1
            file_mtime = os.path.getmtime(file_path)
            file_date = datetime.datetime.fromtimestamp(file_mtime).strftime('%Y-%m-%d %H:%M:%S')
            
            if file_mtime < cutoff_timestamp:
                print(f"Deleting: {file} (date: {file_date})")
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except Exception as e:
                    print(f"Error deleting {file_path}: {str(e)}")
            else:
                print(f"Keeping:  {file} (date: {file_date})")
    
    print(f"Cleanup completed: {deleted_count} files deleted out of {checked_count} checked\n")

def compress_directory(source_dir, output_file_base, config):
    """
    Compresses a directory using the configured compression format
    
    Args:
        source_dir: Directory to compress
        output_file_base: Output file path without extension
        config: Configuration dictionary
        
    Returns:
        str: Path to the compressed file
    """
    compression_config = config.get('defaults', {}).get('compression', {})
    compression_format = compression_config.get('format', '7z').lower()
    compression_level = compression_config.get('level', 5)
    use_7zz = compression_config.get('use_7zz', False)
    
    # Check available compression tools
    tools = check_compression_tools()
    
    encryption_enabled, password = get_encryption_settings()
    output_file = None
    
    try:
        if compression_format == '7z':
            # Use 7zz if configured and available, otherwise fall back to 7z
            cmd_7z = '7zz' if use_7zz and tools['7zz'] else '7z'
            
            if not tools['7zz'] and not tools['7z']:
                print("Error: Neither 7z nor 7zz is installed.")
                print("Please install 7-Zip with: sudo apt-get install p7zip-full")
                return None
                
            output_file = f"{output_file_base}.7z"
            zip_args = [cmd_7z, 'a', f'-mx={compression_level}', '-t7z']
            if encryption_enabled:
                zip_args.extend(['-p' + password, '-mhe=on'])
            zip_args.extend([output_file, source_dir + "/*"])
            
            print(f"Creating 7z archive with {cmd_7z}: {output_file}")
            result = subprocess.run(zip_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
        elif compression_format == 'zip':
            if not tools['zip']:
                print("Error: zip command is not installed.")
                print("Please install zip with: sudo apt-get install zip")
                return None
                
            output_file = f"{output_file_base}.zip"
            
            # For ZIP with encryption, we use 7z if available because standard zip doesn't support strong encryption
            if encryption_enabled and (tools['7z'] or tools['7zz']):
                cmd_7z = '7zz' if use_7zz and tools['7zz'] else '7z'
                zip_args = [cmd_7z, 'a', f'-mx={compression_level}', '-tzip']
                if encryption_enabled:
                    zip_args.extend(['-p' + password, '-mem=AES256'])
                zip_args.extend([output_file, source_dir + "/*"])
                
                print(f"Creating encrypted ZIP archive with {cmd_7z}: {output_file}")
                result = subprocess.run(zip_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            else:
                # Standard zip command (no encryption or basic encryption)
                if encryption_enabled:
                    print("Warning: Standard ZIP encryption is weak. Consider using 7z format for strong encryption.")
                    # Create temporary password file for zip
                    pwd_file = tempfile.NamedTemporaryFile(delete=False)
                    pwd_file.write(password.encode())
                    pwd_file.close()
                    
                    zip_cmd = f"cd '{os.path.dirname(source_dir)}' && zip -r -{compression_level} '{output_file}' '{os.path.basename(source_dir)}/*' -P {password}"
                else:
                    zip_cmd = f"cd '{os.path.dirname(source_dir)}' && zip -r -{compression_level} '{output_file}' '{os.path.basename(source_dir)}/*'"
                
                print(f"Creating ZIP archive: {output_file}")
                result = subprocess.run(zip_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        elif compression_format == 'gzip':
            if not tools['gzip']:
                print("Error: gzip command is not installed.")
                print("Please install gzip with: sudo apt-get install gzip")
                return None
                
            # gzip requires tar to archive directory first
            output_file = f"{output_file_base}.tar.gz"
            
            if encryption_enabled:
                print("Warning: gzip format does not support encryption. The backup will not be encrypted.")
            
            # Create tar archive and pipe to gzip
            tar_gzip_cmd = f"tar -C '{os.path.dirname(source_dir)}' -c{compression_level}zf '{output_file}' '{os.path.basename(source_dir)}'"
            
            print(f"Creating tar.gz archive: {output_file}")
            result = subprocess.run(tar_gzip_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        elif compression_format == 'zstd':
            if not tools['zstd']:
                print("Error: zstd command is not installed.")
                print("Please install zstd with: sudo apt-get install zstd")
                return None
                
            # zstd requires tar to archive directory first
            output_file = f"{output_file_base}.tar.zst"
            
            if encryption_enabled:
                print("Warning: zstd format does not support encryption. The backup will not be encrypted.")
            
            # Create tar archive and pipe to zstd
            tar_zstd_cmd = f"tar -C '{os.path.dirname(source_dir)}' -cf - '{os.path.basename(source_dir)}' | zstd -{compression_level} -o '{output_file}'"
            
            print(f"Creating tar.zst archive: {output_file}")
            result = subprocess.run(tar_zstd_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        else:
            print(f"Error: Unsupported compression format: {compression_format}")
            print("Supported formats: 7z, zip, gzip, zstd")
            return None
        
        if result.returncode != 0:
            print(f"Error creating archive: {output_file}")
            if result.stderr:
                error_text = result.stderr.decode() if hasattr(result.stderr, 'decode') else str(result.stderr)
                print(f"Error details: {error_text}")
            return None
            
        print(f"Archive created successfully: {output_file}")
        return output_file
        
    except Exception as e:
        print(f"Unexpected error during compression: {str(e)}")
        return None

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
    
    # Check and create temp path if needed
    temp_path = os.path.expandvars(os.path.expanduser(
        config.get('defaults', {}).get('temp_path', '')
    ))
    if temp_path and not os.path.exists(temp_path):
        try:
            os.makedirs(temp_path, exist_ok=True)
            print(f"Created temporary directory: {temp_path}")
        except PermissionError:
            print(f"Warning: No permission to create temporary directory {temp_path}")
            print("Will use system default temporary directory instead.")
    
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
        
        # Clean up old backups for this database
        docker_backup_path = os.path.join(backup_path, 'docker')
        cutoff_timestamp = time.time() - (float(retention_days) * 86400)
        
        print(f"\nCleaning up old backups for {db_name}")
        print(f"Retention period: {retention_days} days")
        
        # Clean up database backups (both .zip and .7z)
        db_backup_pattern = f"{db_name}_{data_container}_dockerbackup_"
        cleanup_backups_by_pattern(docker_backup_path, cutoff_timestamp, db_backup_pattern)
        
        # Clean up FastReport backups
        fr_backup_pattern = f"{db_name}_FastReport_"
        cleanup_backups_by_pattern(docker_backup_path, cutoff_timestamp, fr_backup_pattern)
    
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
