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

def create_backup(db_name, db_user, sql_container, data_container, backup_path, timestamp):
    """
    Creates a backup directly to 7zip archive without temporary storage
    """
    output_zip = f'{backup_path}/{db_name}_{data_container}_dockerbackup_{timestamp}.zip'
    
    try:
        # Create new 7zip archive
        with subprocess.Popen(['7z', 'a', '-si', '-tzip', output_zip, f'dump.sql'], 
                            stdin=subprocess.PIPE) as zip_proc:
            # Pipe database dump directly to 7zip
            dump_proc = subprocess.Popen(
                ['docker', 'exec', '-i', sql_container, 'pg_dump', '-U', db_user, db_name],
                stdout=zip_proc.stdin,
                stderr=subprocess.PIPE
            )
            dump_proc.communicate()
            if dump_proc.returncode != 0:
                print(f"Error creating database dump for {db_name}")
                return False
        
        # Add filestore directly from docker to zip
        filestore_proc = subprocess.Popen(
            ['docker', 'exec', sql_container, 'tar', 'c', '-C', f'/opt/odoo/data/filestore', db_name],
            stdout=subprocess.PIPE
        )
        zip_proc = subprocess.Popen(
            ['7z', 'a', '-si', '-tzip', output_zip, f'filestore/{db_name}'],
            stdin=filestore_proc.stdout
        )
        zip_proc.communicate()
        
        if zip_proc.returncode == 0:
            print(f'Backup completed for {data_container}')
            return True
        else:
            print(f'Error creating backup for {data_container}')
            return False
            
    except subprocess.SubprocessError as e:
        print(f"Error during backup process: {str(e)}")
        return False

# Main script
base_path = expanduser("~")
backup_config = base_path + '/container2backup.csv'
backup_path_config = base_path + '/container2backup_path.csv'

# Determine backup path
if os.path.exists(backup_path_config):
    with open(backup_path_config, 'r', encoding="utf8") as backup_file:
        backup_path = backup_file.readline().strip('\n')
else:
    print("No " + backup_path_config + " found!")
    backup_path = "/opt/backups"

# Create directories if they don't exist
if not os.path.exists(backup_path):
    try:
        os.makedirs(backup_path, exist_ok=True)
    except PermissionError:
        print(f"Error: No permission to create {backup_path}")
        exit(1)

nginx_path = os.path.join(backup_path, "nginx")
if not os.path.exists(nginx_path):
    os.makedirs(nginx_path, exist_ok=True)

docker_build_path = os.path.join(backup_path, "docker-builds")
if not os.path.exists(docker_build_path):
    os.makedirs(docker_build_path, exist_ok=True)

backup_path = os.path.join(backup_path, "docker")
if not os.path.exists(backup_path):
    os.makedirs(backup_path, exist_ok=True)

print("Backup path: " + backup_path)

# Retention time variable
retention_days = 14  # Default value if no CSV file found

# Read CSV file and create backups
if not os.path.exists(backup_config):
    print(f"Backup configuration file {backup_config} not found!")
else:
    with io.open(backup_config, 'r', encoding="utf8") as csvfile:
        reader = csv.reader(csvfile, delimiter=",")
        for row in reader:
            if not row or row[0].startswith('#'):
                continue  # Skip empty line or comment
                
            db_name = row[0]
            db_user = row[1]
            sql_container = row[2]
            data_container = row[3]
            
            try:
                retention_days = int(row[4])
            except (IndexError, ValueError):
                retention_days = 14  # Default: 14 days
                
            print(f'Database: {db_name}\nDatabase Container: {sql_container}\n'
                  f'Odoo Container: {data_container}\nRetention Period: {retention_days} days')
                  
            # Create backup directory
            backup_folder = os.path.join(backup_path, db_name)
            if not os.path.exists(backup_folder):
                os.makedirs(backup_folder, exist_ok=True)
                
            # Create database dump
            os.system(f'docker exec -i {sql_container} pg_dump -U {db_user} {db_name} > {backup_folder}/dump.sql')
            
            # Copy filestore
            os.system(f'docker cp {data_container}:/opt/odoo/data/filestore/{db_name} {backup_folder}/')
            
            # Timestamp for filenames
            ts = time.time()
            timestamp = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H-%M-%S')
            
            create_backup(db_name, db_user, sql_container, data_container, backup_path, timestamp)

# Backup Nginx configuration
if os.path.exists('/etc/nginx/conf.d/'):
    ts = time.time()
    mytime = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H-%M-%S')
    output_zip = f'{nginx_path}/nginx-confs_{mytime}.zip'
    subprocess.run(['7z', 'a', '-tzip', output_zip, '/etc/nginx/'], check=False)

# Backup Let's Encrypt certificates
if os.path.exists('/etc/letsencrypt/live/'):
    ts = time.time()
    mytime = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H-%M-%S')
    output_zip = f'{nginx_path}/letsencrypt_{mytime}.zip'
    subprocess.run(['7z', 'a', '-tzip', output_zip, '/etc/letsencrypt/live/'], check=False)

# Backup Docker builds
if os.path.exists('/root/docker-builds'):
    ts = time.time()
    mytime = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d_%H-%M-%S')
    output_zip = f'{docker_build_path}/docker-builds_{mytime}.zip'
    subprocess.run(['7z', 'a', '-tzip', output_zip, '/root/docker-builds/'], check=False)

# Delete old backups (based on retention period)
now = time.time()
_cutoff = now - (float(retention_days) * 86400)

# Clean up Docker backups
cleanup_backups(backup_path, _cutoff)

# Clean up Nginx backups
cleanup_backups(nginx_path, _cutoff)

# Clean up Docker build backups
cleanup_backups(docker_build_path, _cutoff)

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
