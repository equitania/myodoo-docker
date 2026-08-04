#!/usr/bin/python3
# -*- coding: utf-8 -*-
# This script builds a new server using the Release Manager
# Version 2.7.0
# Date 04.08.2026
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
import re
import ssl
import time
import urllib3
import platform
import sys
import subprocess
from urllib.parse import urlsplit

# certifi provides a maintained CA bundle; fall back to the system's default
# verify paths if it is not installed in the build environment.
try:
    import certifi
    _ca_certs = certifi.where()
except ImportError:
    _ca_certs = ssl.get_default_verify_paths().cafile

_build_path = '/opt/odoo'
_release_file = 'release.file'

# Archives pre-fetched on the host by odoo_build_cache.py and copied in by the
# Dockerfile. Absent on servers without the cache, where every archive is
# downloaded exactly as before.
_local_zip_dir = 'zips'

# Check if we are running on macOS or Linux
is_macos = platform.system() == 'Darwin'

# Filenames/paths sourced from the downloaded release CSV must match this
# conservative charset to prevent path traversal or command injection via a
# manipulated or compromised release file.
_SAFE_FILENAME_PATTERN = re.compile(r'^[A-Za-z0-9._/-]+$')

def _validate_csv_filename(value):
    """Validate a filename/path field sourced from the release CSV.

    The character class alone is not sufficient: it permits both '.' and '/',
    so '../../etc/passwd' matches it — and the value is used as the target of
    open() and as the argument of `unzip -d`, i.e. it can write outside the
    build directory. Traversal segments and absolute paths are therefore
    rejected explicitly.
    """
    if not value or not _SAFE_FILENAME_PATTERN.match(value):
        print(f"Invalid filename in release file: '{value}'")
        return False
    if value.startswith('/') or '..' in value.split('/'):
        print(f"Refused path traversal in release file: '{value}'")
        return False
    return True

def _create_http_pool():
    """Create the HTTP pool; use a ProxyManager when proxy env vars are set.

    urllib3 does NOT honor http_proxy/https_proxy implicitly (unlike wget or
    requests). Inside 'docker build' the proxy env vars arrive via the
    predefined --build-arg proxy args passed by update_docker_odoo.py.
    """
    proxy_url = (os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')
                 or os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY'))
    pool_kwargs = dict(maxsize=10, block=True,
                       timeout=urllib3.Timeout(connect=30, read=300),
                       cert_reqs='CERT_REQUIRED', ca_certs=_ca_certs)
    if proxy_url:
        print(f"Using proxy for downloads: {proxy_url}")
        return urllib3.ProxyManager(proxy_url, **pool_kwargs)
    return urllib3.PoolManager(**pool_kwargs)

# Global connection pool for efficient HTTP requests
http_pool = _create_http_pool()

# Retry policy for downloads. A release server that is briefly unavailable
# (service restart after a package upgrade, proxy hiccup, transient DNS issue)
# must not abort an entire image build that pulls hundreds of archives.
# Defaults give ~45s of total wait across 5 attempts (3s, 6s, 12s, 24s), which
# comfortably covers a systemd restart of the web service on the release host.
# Override via environment for slower links or unattended CI runs.
_MAX_DOWNLOAD_ATTEMPTS = max(1, int(os.environ.get('BUILD_ODOO_RETRIES', '5')))
_RETRY_BACKOFF_BASE = max(0.5, float(os.environ.get('BUILD_ODOO_RETRY_BACKOFF', '3')))
_RETRY_BACKOFF_CAP = 60.0

# Server-side and rate-limit responses are worth retrying; client errors such as
# 404 (file genuinely absent from the release) or 403 are permanent, and
# retrying them only delays a build that is going to fail anyway.
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

# Module archives that fail to install are collected rather than aborting on the
# first one, so a single run reports every missing archive instead of revealing
# them one rerun at a time. But a *run* of consecutive failures means the release
# server went away mid-build: without a circuit breaker the remaining hundreds of
# archives would each burn the full retry budget (~45s), turning one outage into
# hours of pointless waiting.
_CONSECUTIVE_FAILURE_LIMIT = max(1, int(os.environ.get('BUILD_ODOO_FAILURE_LIMIT', '3')))

# Escape hatch: a build that knowingly tolerates missing modules (e.g. a stale
# entry in the release file that cannot be fixed right now) can opt out of the
# hard failure. Off by default — an incomplete image must never be the silent
# default outcome.
_ALLOW_PARTIAL = os.environ.get('BUILD_ODOO_ALLOW_PARTIAL', '').strip().lower() in ('1', 'true', 'yes')

def _retry_delay(attempt):
    """Return the exponential backoff delay before retry number `attempt` (1-based)."""
    return min(_RETRY_BACKOFF_BASE * (2 ** (attempt - 1)), _RETRY_BACKOFF_CAP)

def download_file(url, filename):
    """Download a file from URL and save it to the given filename.

    Transient failures (connection refused/reset, timeouts, 5xx responses) are
    retried with exponential backoff. Permanent failures return immediately.
    Every attempt is logged so a stalled build is diagnosable from the Docker
    build output instead of appearing to hang silently.
    """
    host = urlsplit(url).netloc or url
    last_error = None

    for attempt in range(1, _MAX_DOWNLOAD_ATTEMPTS + 1):
        try:
            # retries=False: this function owns the retry loop, so urllib3 must
            # not add its own (invisible) attempts on top and distort the log.
            response = http_pool.request('GET', url, retries=False)

            if response.status == 200:
                with open(filename, 'wb') as f:
                    f.write(response.data)
                if attempt > 1:
                    print(f"Downloaded: {filename} (succeeded on attempt {attempt})")
                else:
                    print(f"Downloaded: {filename}")
                return True

            last_error = f"HTTP status {response.status}"
            if response.status not in _RETRYABLE_STATUS:
                print(f"Failed to download {filename}. Status code: {response.status}")
                return False
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"

        if attempt < _MAX_DOWNLOAD_ATTEMPTS:
            delay = _retry_delay(attempt)
            print(f"Attempt {attempt}/{_MAX_DOWNLOAD_ATTEMPTS} for {filename} failed "
                  f"({last_error}) — retrying in {delay:.0f}s...")
            sys.stdout.flush()
            time.sleep(delay)

    print(f"Error downloading {filename} after {_MAX_DOWNLOAD_ATTEMPTS} attempts: {last_error}")
    print(f"Release server '{host}' could not be reached. Verify that the web "
          f"service on that host is running (e.g. 'systemctl status nginx'), "
          f"then rerun the build.")
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
    # Use list-form subprocess call (no shell=True) to avoid shell injection
    # via filenames sourced from the downloaded release CSV.
    try:
        subprocess.run(["unzip", "-q", "-o", zipfile, "-d", destination],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
        print(f"Extracted: {zipfile} to {destination}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to extract {zipfile}")
        print(f"Error: {e.stderr}")
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

def _local_zip(filename):
    """Path of a host-provided archive, or None when it has to be downloaded."""
    candidate = os.path.join(_local_zip_dir, os.path.basename(filename))
    return candidate if os.path.isfile(candidate) else None

def download_and_extract(url, filename, destination):
    """Extract an archive, downloading it first unless the host provided it.

    Returns (ok, from_cache). A missing local archive is not an error: the
    cache is an optimisation, and anything it did not supply is fetched here
    exactly as before.
    """
    local = _local_zip(filename)
    if local:
        if extract_zip(local, destination):
            return True, True
        print(f"Failed to extract cached {filename}")
        return False, True
    if download_file(url, filename):
        if extract_zip(filename, destination):
            return True, False
        print(f"Failed to extract {filename}")
        return False, False
    print(f"Failed to download {filename}")
    return False, False

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
cached_files = 0
failed_modules = []
consecutive_failures = 0
aborted_early = False

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
            elif not _validate_csv_filename(_column):
                sys.exit(1)
            else:
                # Create directories if they don't exist
                os.makedirs('odoo-server/addons', exist_ok=True)

                # Download kernel
                _zip_url = f"{_url}/{_column}"
                _ok, _from_cache = download_and_extract(_zip_url, _column, 'odoo-server')
                if _ok:
                    downloaded_files += 1
                    if _from_cache:
                        cached_files += 1
                    print(f"kernel: {_column} loaded and installed.."
                          f"{' (cached)' if _from_cache else ''}")
                else:
                    print(f'Failed to process kernel: {_column}')
                    sys.exit(1)

        else:  # Modules
            if _column.find('.zip') != -1:
                if not _validate_csv_filename(_column):
                    # A rejected filename means this module will be missing from
                    # the image just as surely as a failed download — track it.
                    failed_modules.append(f"{_column} (rejected: invalid filename)")
                    continue
                _zip_url = f"{_url}/{_column}"
                _ok, _from_cache = download_and_extract(_zip_url, _column, 'odoo-server/addons')
                if _ok:
                    downloaded_files += 1
                    if _from_cache:
                        cached_files += 1
                    consecutive_failures = 0
                    print(f"file: {_column} loaded and installed.."
                          f"{' (cached)' if _from_cache else ''}")
                else:
                    failed_modules.append(_column)
                    consecutive_failures += 1
                    print(f'Failed to process module: {_column}')
                    if consecutive_failures >= _CONSECUTIVE_FAILURE_LIMIT:
                        print(f"\nAborting run: {consecutive_failures} module downloads failed "
                              f"back to back — the release server is most likely unavailable. "
                              f"Remaining entries are not attempted.")
                        aborted_early = True
                        break
        
        _count += 1

if aborted_early:
    print(f"\nRun aborted before the end of the release file. "
          f"Files downloaded: {downloaded_files}/{total_zip_files}")
else:
    print(f"\nAll entries from release file processed! Files installed: "
          f"{downloaded_files}/{total_zip_files} "
          f"({cached_files} from cache, {downloaded_files - cached_files} downloaded)")

# A module archive that never made it into the image previously produced nothing
# but a log line: the build succeeded and shipped an image silently missing that
# module, which typically surfaces much later as a puzzling ImportError or a
# missing menu entry in Odoo. Fail loudly instead, listing every affected archive.
if failed_modules:
    print("\n" + "=" * 70)
    print(f"{len(failed_modules)} module archive(s) could NOT be installed:")
    for _failed in failed_modules:
        print(f"  - {_failed}")
    print("=" * 70)
    if _ALLOW_PARTIAL:
        print("BUILD_ODOO_ALLOW_PARTIAL is set — continuing with an INCOMPLETE image.")
    else:
        print("Refusing to build an incomplete image. Check the release server and the")
        print("release file, then rerun the build. To build anyway (not recommended),")
        print("set BUILD_ODOO_ALLOW_PARTIAL=1.")
        sys.exit(1)

# Check for custom modules: process every *custom_modules.zip in the build
# context (custom_modules.zip plus customer-specific archives like
# xy_custom_modules.zip). The generic archive is extracted first so
# customer-specific archives can override modules from it.
custom_zips = sorted(f for f in os.listdir('.') if f.endswith('custom_modules.zip'))
if 'custom_modules.zip' in custom_zips:
    custom_zips.remove('custom_modules.zip')
    custom_zips.insert(0, 'custom_modules.zip')
if custom_zips:
    print("\nProcessing custom modules...")
    for custom_modules in custom_zips:
        if extract_zip(custom_modules, 'odoo-server/addons'):
            print(f'file: {custom_modules} loaded and installed..')
        else:
            print(f'Failed to extract custom modules: {custom_modules}')

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

# The host-provided archives must not remain in the image either — they are
# already extracted, and they would roughly double its size.
run_command(f"rm -rf {_local_zip_dir}")

print('Cleanup and finished!')