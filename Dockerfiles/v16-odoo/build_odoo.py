#!/usr/bin/python3
# -*- coding: utf-8 -*-
# This script builds a new server using the Release Manager
# Version 2.1.1
# Date 08.04.2025
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
from pathlib import Path
import subprocess

_build_path = '/opt/odoo'
_release_file = 'release.file'

# Check if we are running on macOS or Linux
is_macos = platform.system() == 'Darwin'

def download_file(url, filename, current_progress=None):
    """Download a file from URL and save it to the given filename."""
    try:
        # Create an urllib3.PoolManager instance
        http = urllib3.PoolManager()
        
        # Send an HTTP GET request to the URL
        response = http.request('GET', url)
        
        # Check if the request was successful (status code 200)
        if response.status == 200:
            # Open the local file in binary write mode and write the downloaded content to it
            with open(filename, 'wb') as f:
                f.write(response.data)
            if current_progress:
                print(f"File downloaded successfully to {filename} - Progress: {current_progress}")
            else:
                print(f"File downloaded successfully to {filename}")
            return True
        else:
            print(f"Failed to download file from {url}. Status code: {response.status}")
            return False
    except Exception as e:
        print(f"Error downloading file: {e}")
        return False

def run_command(command):
    """Run a shell command with proper error handling."""
    try:
        result = subprocess.run(command, shell=True, check=True, 
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                               universal_newlines=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {command}")
        print(f"Error: {e.stderr}")
        return False

def extract_zip(zipfile, destination=".", current_progress=None):
    """Extract a zip file to the specified destination."""
    if is_macos:
        # macOS unzip command
        command = f"unzip -q -o {zipfile} -d {destination}"
    else:
        # Linux unzip command
        command = f"unzip -q -o {zipfile} -d {destination}"
    
    if run_command(command):
        if current_progress:
            print(f"File: {zipfile} extracted to {destination} - Progress: {current_progress}")
        else:
            print(f"File: {zipfile} extracted to {destination}")
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

def format_progress(current, total, downloaded_files=None, total_files=None):
    """Format the progress as a percentage with a progress bar."""
    percent = 100 * (current / total)
    bar_length = 30
    filled_length = int(bar_length * current // total)
    bar = '█' * filled_length + '░' * (bar_length - filled_length)
    progress_text = f"[{bar}] {percent:.1f}% ({current}/{total})"
    
    # Add file download progress if available
    if downloaded_files is not None and total_files is not None:
        file_percent = 100 * (downloaded_files / total_files) if total_files > 0 else 0
        progress_text += f" | Files: {downloaded_files}/{total_files} ({file_percent:.1f}%)"
    
    return progress_text

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

# Count total rows for progress tracking
total_rows = count_csv_rows(_release_file)
# Count the total number of ZIP files to download
total_zip_files = count_zip_files_in_csv(_release_file)
downloaded_files = 0

print(f"Release file contains {total_rows} entries with {total_zip_files} files to download.")

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
        
        # Calculate and display progress
        progress = format_progress(_count, total_rows, downloaded_files, total_zip_files)
        print(f"\nProcessing entry {_count}/{total_rows} - {progress}")
            
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
                current_progress = format_progress(_count, total_rows, downloaded_files, total_zip_files)
                if download_file(_zip_url, _column, current_progress):
                    # Extract kernel
                    if extract_zip(_column, 'odoo-server', current_progress):
                        print(f'kernel: {_column} loaded and installed..')
                    else:
                        print(f'Failed to extract kernel: {_column}')
                        sys.exit(1)
                else:
                    print(f'Failed to download kernel: {_column}')
                    sys.exit(1)
                    
        else:  # Modules
            if _column.find('.zip') != -1:
                _zip_url = f"{_url}/{_column}"
                downloaded_files += 1
                current_progress = format_progress(_count, total_rows, downloaded_files, total_zip_files)
                if download_file(_zip_url, _column, current_progress):
                    if extract_zip(_column, 'odoo-server/addons', current_progress):
                        print(f'file: {_column} loaded and installed..')
                    else:
                        print(f'Failed to extract module: {_column}')
        
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