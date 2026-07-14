#!/usr/bin/python3
# -*- coding: utf-8 -*-
# This script builds a new server using the Release Manager
# Version 2.2.0
# Date 14.07.2026
##############################################################################
#
#    Shell Script for Odoo, Open Source Management Solution
#    Copyright (C) 2018-now Equitania Software GmbH(<http://www.equitania.de>).
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
##############################################################################

import os
import csv
import urllib3
import platform
import sys
import subprocess

_build_path = '/opt/odoo'
_release_file = 'release.file'

# Check if we are running on macOS or Linux
is_macos = platform.system() == 'Darwin'

def _create_http_pool():
    """Create the HTTP pool; use a ProxyManager when proxy env vars are set.

    urllib3 does NOT honor http_proxy/https_proxy implicitly (unlike wget or
    requests). Inside 'docker build' the proxy env vars arrive via the
    predefined --build-arg proxy args passed by update_docker_odoo.py.
    """
    proxy_url = (os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')
                 or os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY'))
    pool_kwargs = dict(maxsize=10, block=True,
                       timeout=urllib3.Timeout(connect=30, read=300))
    if proxy_url:
        print(f"Using proxy for downloads: {proxy_url}")
        return urllib3.ProxyManager(proxy_url, **pool_kwargs)
    return urllib3.PoolManager(**pool_kwargs)

# Global connection pool for efficient HTTP requests
http_pool = _create_http_pool()

def download_file(url, filename):
    """Download a file from URL and save it to the given filename."""
    try:
        # Use global connection pool for efficient HTTP requests
        response = http_pool.request('GET', url)
        
        # Check if the request was successful (status code 200)
        if response.status == 200:
            # Open the local file in binary write mode and write the downloaded content to it
            with open(filename, 'wb') as f:
                f.write(response.data)
            print(f"Downloaded: {filename}")
            return True
        else:
            print(f"Failed to download {filename}. Status code: {response.status}")
            return False
    except Exception as e:
        print(f"Error downloading {filename}: {e}")
        return False

def run_command(command):
    """Run a shell command with proper error handling."""
    try:
        subprocess.run(command, shell=True, check=True, 
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                       universal_newlines=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {command}")
        print(f"Error: {e.stderr}")
        return False

def extract_zip(zipfile, destination="."):
    """Extract a zip file to the specified destination."""
    if is_macos:
        # macOS unzip command
        command = f"unzip -q -o {zipfile} -d {destination}"
    else:
        # Linux unzip command
        command = f"unzip -q -o {zipfile} -d {destination}"
    
    if run_command(command):
        print(f"Extracted: {zipfile} to {destination}")
        return True
    else:
        print(f"Failed to extract {zipfile}")
        return False

def count_csv_rows(file_path):
    """Count the number of rows in a CSV file."""
    count = 0
    with open(file_path, 'r', encoding="utf8") as f:
        reader = csv.reader(f)
        for _ in reader:
            count += 1
    return count

def count_zip_files_in_csv(file_path):
    """Count the number of zip files in the CSV file."""
    zip_count = 0
    with open(file_path, 'r', encoding="utf8") as f:
        reader = csv.reader(f)
        row_count = 0
        for row in reader:
            row_count += 1
            if row_count > 2 and row:  # Skip URL and Docker image rows
                column = row[0].replace(' ', '')
                if column.find('.zip') != -1:
                    zip_count += 1
    return zip_count

def download_and_extract(url, filename, destination):
    """Download and extract a file in one operation."""
    if download_file(url, filename):
        if extract_zip(filename, destination):
            return True
        else:
            print(f"Failed to extract {filename}")
            return False
    else:
        print(f"Failed to download {filename}")
        return False

# Main script execution
if not os.path.isfile(_release_file):
    print('*********************************************')
    print('*               E R R O R                   *')
    print('*    NO file named release.file found!!     *')
    print('*********************************************')
    sys.exit(1)

# Ensure the release file has content
if os.stat(_release_file).st_size == 0:
    print('No valid release file :(')
    sys.exit(1)

print('Starting with build at ' + _build_path)

# Count the total number of ZIP files to download
total_zip_files = count_zip_files_in_csv(_release_file)
downloaded_files = 0

print(f"Release file contains {total_zip_files} files to download.")

# Change to the build directory
try:
    os.chdir(_build_path)
except FileNotFoundError:
    print(f"Build directory {_build_path} does not exist. Creating it...")
    os.makedirs(_build_path, exist_ok=True)
    os.chdir(_build_path)
except PermissionError:
    print(f"Permission denied: Cannot access {_build_path}")
    sys.exit(1)

# Process the release file
with open(_release_file, encoding="utf8") as csvfile:
    _reader = csv.reader(csvfile, delimiter=",")
    _count = 1
    _url = None
    
    for _row in _reader:
        if not _row:  # Skip empty rows
            continue
        
        print(f"\nProcessing entry {_count}...")
            
        _column = _row[0].replace(' ', '')
        
        if _count == 1:  # URL
            print('url: ' + _column)
            _url = _column
            if _url == 'False':
                print('url is missing .. stop!')
                sys.exit(1)
                
        elif _count == 2:  # Docker image
            print('dockerimage: ' + _column)
            
        elif _count == 3:  # Kernel
            if _column == 'False':
                print('kernel is missing .. stop!')
                sys.exit(1)
            else:
                # Create directories if they don't exist
                os.makedirs('odoo-server/addons', exist_ok=True)
                
                # Download kernel
                _zip_url = f"{_url}/{_column}"
                downloaded_files += 1
                if download_and_extract(_zip_url, _column, 'odoo-server'):
                    print(f'kernel: {_column} loaded and installed..')
                else:
                    print(f'Failed to process kernel: {_column}')
                    sys.exit(1)
                    
        else:  # Modules
            if _column.find('.zip') != -1:
                _zip_url = f"{_url}/{_column}"
                downloaded_files += 1
                if download_and_extract(_zip_url, _column, 'odoo-server/addons'):
                    print(f'file: {_column} loaded and installed..')
                else:
                    print(f'Failed to process module: {_column}')
        
        _count += 1

print(f"\nAll entries from release file processed! Files downloaded: {downloaded_files}/{total_zip_files}")

# Check for custom modules
custom_modules = 'custom_modules.zip'
if os.path.exists(custom_modules):
    print("\nProcessing custom modules...")
    if extract_zip(custom_modules, 'odoo-server/addons'):
        print(f'file: {custom_modules} loaded and installed..')
    else:
        print(f'Failed to extract custom modules')

print('\nBuild finished! [100%]')

# Cleanup
print("\nPerforming cleanup...")
files_to_remove = ['*.zip', 'build_myodoo.py', 'release.file']
for file_pattern in files_to_remove:
    if is_macos:
        cmd = f"find . -name '{file_pattern}' -type f -delete"
    else:
        cmd = f"rm -f {file_pattern}"
    run_command(cmd)

print('Cleanup and finished!')