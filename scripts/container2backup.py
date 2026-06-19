#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Title:            container2backup.py
# Description:      Script to backup Odoo database including FileStore under Docker
# Version:          4.7.0
# Date:             19.06.2026
# Author:           Equitania Software GmbH
# ==============================================================================
# Feature Overview:
#   - Database backup (SQL + Filestore) for multiple Odoo instances
#   - Support for SQL-only backups (--sql-only parameter)
#   - FastReport backup integration
#   - Service backups (nginx, letsencrypt, docker builds)
#   - Multiple compression formats (7z, zip, gzip, zstd)
#   - Streaming full backup (opt-in via 'stream: true'): pipes pg_dump + the
#     filestore (read in-place from the host volume) straight into a single
#     .tar.zst on the target, so the backup medium no longer needs room for an
#     uncompressed staging copy of the filestore. Restore-compatible (.tar.zst).
#   - Disk pre-flight check before full backups (aborts cleanly when the
#     temp/target mount cannot hold the backup)
#   - Optional AES-256 encryption via GPG (7z format only, output: .7z.gpg;
#     falls back to 7z -p AES when gnupg is not installed)
#   - Automatic cleanup of old backups
# ==============================================================================
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
import sys
import csv
import json
import datetime, time
import os.path
import re
import subprocess
from os.path import expanduser
import yaml  # Add this import at the top
from dotenv import load_dotenv
import tempfile
import shutil
import platform
import argparse  # Add argparse for command line parameters
import signal  # Decode negative subprocess returncodes (signal kills) for diagnostics

# Single source of truth for the version banner printed at runtime. Keep these
# in sync with the header comment above. The __main__ banner is derived from
# these constants so it cannot silently drift out of date again.
SCRIPT_VERSION = "4.7.0"
SCRIPT_DATE = "19.06.2026"

# Whitelist for database names and Docker container names. Both propagate
# into filesystem paths and subprocess argv, so restrict to shell-inert chars.
# Rationale: db_name flows into docker exec paths; container names flow into
# docker CLI arguments. PostgreSQL identifiers and Docker names both match.
_IDENT_RE = re.compile(r'^[A-Za-z0-9_.\-]+$')


def _validate_identifier(value, field_name):
    """Raise ValueError if value contains characters that would be unsafe in
    a filesystem path or Docker argument.
    """
    if not isinstance(value, str) or not _IDENT_RE.match(value):
        raise ValueError(
            f"Invalid {field_name} {value!r}: must match [A-Za-z0-9_.-]+"
        )
    return value

def check_compression_tools():
    """
    Checks which compression tools are available

    Returns:
        dict: Dictionary containing availability of compression tools
    """
    tools = {
        '7zz': False,
        'zip': False,
        'gzip': False,
        'zstd': False
    }

    # Check 7zz (newer 7-Zip) - use shutil.which for robust binary detection
    if shutil.which('7zz') is not None:
        tools['7zz'] = True

    # Check zip
    if shutil.which('zip') is not None:
        tools['zip'] = True

    # Check gzip
    if shutil.which('gzip') is not None:
        tools['gzip'] = True

    # Check zstd
    if shutil.which('zstd') is not None:
        tools['zstd'] = True

    return tools

def compress_with_7zip(source_dir, output_file):
    """
    DEPRECATED: This function is kept for backward compatibility only.
    Please use the compress_directory function instead.
    """
    print("WARNING: Using deprecated function compress_with_7zip.")
    print("This function will be removed in a future version.")
    
    try:
        # Check if 7zz is installed
        subprocess.run(['7zz', '--help'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        
        # Compress with 7zz
        cmd = ['7zz', 'a', '-tzip', output_file, source_dir]
        subprocess.run(cmd, check=True)
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        print("Error: 7zz is not installed or command failed.")
        print("Please install 7-Zip with a package that provides 7zz.")
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
    Gets encryption settings from .env file.
    Primary: /root/.config/myodoo-docker/.env
    Fallback: .env in script directory (legacy)
    """
    env_candidates = [
        os.path.join("/root/.config/myodoo-docker", ".env"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
    ]
    for env_path in env_candidates:
        if os.path.exists(env_path):
            load_dotenv(env_path)
            break
    else:
        load_dotenv()  # fallback: search CWD
    enabled = os.getenv('BACKUP_ENCRYPTION_ENABLED', 'false').lower() == 'true'
    password = os.getenv('BACKUP_PASSWORD', '')
    
    if enabled and not password:
        print("WARNING: Encryption enabled but no password set in .env file")
        enabled = False

    return enabled, password

def encrypt_file_with_gpg(file_path, password):
    """
    Encrypts a file with GPG symmetric AES-256 encryption.
    The passphrase is passed via file descriptor, never via argv,
    so it is not visible in the process list (ps aux).

    Decrypt with: gpg -d backup.7z.gpg > backup.7z

    Returns the encrypted file path, or None on failure.
    """
    encrypted_path = file_path + '.gpg'
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, password.encode('utf-8'))
    finally:
        os.close(write_fd)
    try:
        result = subprocess.run(
            ['gpg', '--batch', '--yes', '--symmetric', '--cipher-algo', 'AES256',
             '--passphrase-fd', str(read_fd), '--output', encrypted_path, file_path],
            pass_fds=(read_fd,), stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    finally:
        os.close(read_fd)

    if result.returncode != 0:
        if result.stderr:
            print(f"GPG error: {result.stderr.decode(errors='replace')}")
        return None
    if not os.path.exists(encrypted_path) or os.path.getsize(encrypted_path) == 0:
        return None
    os.remove(file_path)  # remove the unencrypted archive
    return encrypted_path


def _free_bytes(path):
    """Free bytes on the filesystem that holds ``path``.

    Walks up to the nearest existing parent so it works even when ``path``
    itself does not exist yet (e.g. the target archive). Returns None if it
    cannot be determined.
    """
    probe = path
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    try:
        return shutil.disk_usage(probe or '/').free
    except OSError:
        return None


def _human(num_bytes):
    """Render a byte count as a human-readable string (or 'unknown')."""
    if num_bytes is None:
        return "unknown"
    value = float(num_bytes)
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if abs(value) < 1024.0 or unit == 'TiB':
            return f"{value:.1f} {unit}"
        value /= 1024.0


def _report_failure_context(label, cmd, returncode, stdout, stderr, related_paths):
    """Print everything needed to diagnose a failed compression/stream step.

    The previous behaviour swallowed the real cause: it printed only a generic
    "Error creating archive" line and the stderr *only if* it was non-empty,
    never the return code, the signal, the stdout, or the free disk space.
    """
    print(f"Error: {label} failed")
    if cmd is not None:
        printable = ' '.join(cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
        print(f"  Command: {printable}")
    if returncode is not None:
        if returncode < 0:
            try:
                sig_name = signal.Signals(-returncode).name
            except (ValueError, KeyError):
                sig_name = f"signal {-returncode}"
            print(f"  Return code: {returncode} (killed by {sig_name} - "
                  f"often the OOM killer or a manual kill)")
        else:
            print(f"  Return code: {returncode}")

    def _decode(blob):
        if not blob:
            return ''
        return blob.decode(errors='replace') if hasattr(blob, 'decode') else str(blob)

    err_text = _decode(stderr).strip()
    out_text = _decode(stdout).strip()
    if err_text:
        print(f"  stderr: {err_text}")
    if out_text:
        print(f"  stdout: {out_text}")
    if not err_text and not out_text:
        print("  (no stderr/stdout captured - empty output usually means the "
              "process was killed by a signal before it could report)")
    for p in related_paths or []:
        print(f"  Free space on mount for {p}: {_human(_free_bytes(p))}")


def _remove_partial_archive(output_file):
    """Delete a half-written archive after a failure.

    Without this a truncated file is left behind and an external monitor that
    only checks for file existence would treat it as a valid backup.
    """
    if output_file and os.path.exists(output_file):
        try:
            os.remove(output_file)
            print(f"  Removed partial/incomplete archive: {output_file}")
        except OSError as exc:
            print(f"  Could not remove partial archive {output_file}: {exc}")


def get_database_size_bytes(sql_container, db_user, db_name):
    """Return the on-disk size of the database in bytes via pg_database_size,
    or None if it cannot be determined."""
    try:
        proc = subprocess.run(
            ['docker', 'exec', sql_container, 'psql', '-U', db_user, '-d', db_name,
             '-tAc', f"SELECT pg_database_size('{db_name}')"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if proc.returncode == 0:
            return int(proc.stdout.decode(errors='replace').strip())
    except (ValueError, OSError):
        pass
    return None


def get_filestore_size_bytes(data_container, db_name):
    """Return the size of the container filestore in bytes via ``du -sb``,
    or None if it cannot be determined."""
    src_path = f"/opt/odoo/data/filestore/{db_name}"
    try:
        proc = subprocess.run(
            ['docker', 'exec', data_container, 'du', '-sb', src_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if proc.returncode == 0:
            return int(proc.stdout.decode(errors='replace').split()[0])
    except (ValueError, IndexError, OSError):
        pass
    return None


def resolve_filestore_host_path(data_container, db_name):
    """Resolve the host filesystem path of the container's filestore directory.

    The filestore lives at the container path /opt/odoo/data/filestore/<db>.
    We inspect the container's mounts and find the one whose Destination is the
    longest prefix of that container path, then map it onto the host Source.
    This lets us read the filestore IN-PLACE (no uncompressed staging copy).

    Returns the host path (str) only if it exists as a directory, else None.
    """
    container_path = f"/opt/odoo/data/filestore/{db_name}"
    # Parse the raw JSON from `docker inspect` rather than a Go --format template:
    # a template like {{"\n"}} is fragile (Python turns \n into a real newline,
    # which Go then rejects as an invalid string literal). JSON is unambiguous.
    try:
        proc = subprocess.run(
            ['docker', 'inspect', data_container],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    try:
        info = json.loads(proc.stdout.decode(errors='replace'))
    except ValueError:
        return None
    if not isinstance(info, list) or not info:
        return None
    mounts = info[0].get('Mounts') or []

    best_dest = None
    best_source = None
    for mount in mounts:
        dest = (mount.get('Destination') or '').strip()
        source = (mount.get('Source') or '').strip()
        if not dest or not source:
            continue
        # dest must be container_path itself or a parent directory of it.
        if container_path == dest or container_path.startswith(dest.rstrip('/') + '/'):
            if best_dest is None or len(dest) > len(best_dest):
                best_dest, best_source = dest, source

    if not best_dest:
        return None
    remainder = container_path[len(best_dest.rstrip('/')):]
    host_path = best_source.rstrip('/') + remainder
    return host_path if os.path.isdir(host_path) else None


def disk_preflight(temp_dir, dest_dir, db_size, filestore_size, streaming):
    """Check there is enough free space before a full backup starts.

    Streaming (Design A) only stages the SQL dump in temp; the filestore is
    streamed compressed straight to the target. Legacy staging needs room for
    the uncompressed dump AND the uncompressed filestore in temp, plus the
    archive in the target.

    Returns (ok: bool, message: str). Unknown sizes -> ok=True (log only); we
    do not refuse a backup just because a size probe failed.
    """
    free_temp = _free_bytes(temp_dir)
    free_dest = _free_bytes(dest_dir)
    print(f"Disk pre-flight: db_size={_human(db_size)}, "
          f"filestore_size={_human(filestore_size)}, "
          f"free(temp)={_human(free_temp)}, free(target)={_human(free_dest)}, "
          f"mode={'streaming' if streaming else 'staging'}")

    if db_size is None:
        return True, "size unknown - skipping space check"

    same_mount = (free_temp is not None and free_dest is not None
                  and os.stat(_existing_parent(temp_dir)).st_dev
                  == os.stat(_existing_parent(dest_dir)).st_dev)

    if streaming:
        # temp holds only the uncompressed dump; the archive is written to the
        # target. Odoo filestores are mostly already-compressed media, so the
        # archive barely shrinks - estimate it at 0.9x the filestore size.
        fs = filestore_size or 0
        archive_est = int(fs * 0.9)
        need_temp = int(db_size * 1.2)
        if same_mount:
            # dump (temp) and archive (target) share the same free space.
            need = need_temp + archive_est
            if free_temp is not None and free_temp < need:
                return False, (f"backup mount needs ~{_human(need)} (SQL dump + "
                               f"~{_human(archive_est)} archive) but only "
                               f"{_human(free_temp)} is free")
        else:
            if free_temp is not None and free_temp < need_temp:
                return False, (f"temp mount needs ~{_human(need_temp)} for the SQL "
                               f"dump but only {_human(free_temp)} is free")
            if free_dest is not None and free_dest < archive_est:
                return False, (f"target mount needs ~{_human(archive_est)} for the "
                               f"archive but only {_human(free_dest)} is free")
        return True, "ok"

    # Legacy staging: dump + filestore uncompressed in temp, plus archive in dest.
    # Archive estimate: SQL compresses well (~0.3x), but an Odoo filestore is
    # mostly already-compressed media (~0.9x) - the previous 0.4x guess was far
    # too optimistic and would wrongly pass a media-heavy DB that then fails.
    fs = filestore_size or 0
    staging = int((db_size + fs) * 1.05)
    archive_est = int(db_size * 0.3 + fs * 0.9)
    if same_mount:
        # staging (temp) and archive (target) compete for the same free space.
        need = staging + archive_est
        if free_temp is not None and free_temp < need:
            return False, (f"backup mount needs ~{_human(need)} (~{_human(staging)} "
                           f"uncompressed staging + ~{_human(archive_est)} archive) "
                           f"but only {_human(free_temp)} is free")
    else:
        if free_temp is not None and free_temp < staging:
            return False, (f"temp mount needs ~{_human(staging)} for uncompressed "
                           f"staging but only {_human(free_temp)} is free")
        if free_dest is not None and free_dest < archive_est:
            return False, (f"target mount needs ~{_human(archive_est)} for the "
                           f"archive but only {_human(free_dest)} is free")
    return True, "ok"


def _existing_parent(path):
    """Nearest existing ancestor of path (for stat/dev comparisons)."""
    probe = path
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    return probe or '/'


def stream_full_backup(temp_dir, output_file_base, host_filestore_path,
                       db_name, compression_level):
    """Design A: stream dump.sql + the in-place filestore into one .tar.zst.

    Pre-condition: ``temp_dir/dump.sql`` already exists (plain-text dump).
    A symlink ``temp_dir/filestore`` -> ``host_filestore_path`` is created so a
    single ``tar -h`` run archives the dump plus the filestore (dereferenced)
    as ``filestore/...`` - the exact layout restore-zip.sh expects. The tar
    stream is piped through zstd straight to the target; the filestore is never
    copied to disk.

    Returns the output file path on success, else None.
    """
    output_file = f"{output_file_base}.tar.zst"
    symlink_path = os.path.join(temp_dir, "filestore")
    dest_dir = os.path.dirname(output_file)

    # (Re)create the symlink that points tar at the in-place filestore.
    try:
        if os.path.islink(symlink_path) or os.path.exists(symlink_path):
            os.remove(symlink_path)
        os.symlink(host_filestore_path, symlink_path)
    except OSError as exc:
        print(f"Error: could not create filestore symlink for streaming: {exc}")
        return None

    print(f"Streaming full backup to {output_file}")
    print(f"  Filestore read in-place from host: {host_filestore_path}")

    # tar dereferences the 'filestore' symlink (-h) so its target is archived
    # as a real directory named 'filestore'. dump.sql is a regular file.
    tar_cmd = ['tar', '-C', temp_dir, '-h', '-cf', '-', 'dump.sql', 'filestore']
    # -T0: use all cores. -f overwrite a stale partial. Level reused from config.
    zstd_cmd = ['zstd', '-T0', f'-{compression_level}', '-f', '-o', output_file]

    producer = subprocess.Popen(
        tar_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    consumer = subprocess.Popen(
        zstd_cmd, stdin=producer.stdout,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if producer.stdout is not None:
        producer.stdout.close()  # let producer get SIGPIPE if consumer dies
    cons_out, cons_err = consumer.communicate()
    prod_out, prod_err = producer.communicate()

    if producer.returncode != 0:
        _report_failure_context(
            "filestore/dump tar stream", tar_cmd, producer.returncode,
            prod_out, prod_err, [temp_dir, dest_dir])
        _remove_partial_archive(output_file)
        return None
    if consumer.returncode != 0:
        _report_failure_context(
            "zstd compression", zstd_cmd, consumer.returncode,
            cons_out, cons_err, [dest_dir])
        _remove_partial_archive(output_file)
        return None

    if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
        print(f"Error: streamed archive {output_file} is missing or empty")
        _remove_partial_archive(output_file)
        return None

    print(f"Archive created successfully: {output_file} "
          f"(size: {os.path.getsize(output_file)} bytes)")
    return output_file

def create_backup(db_name, db_user, sql_container, data_container, backup_path, timestamp, additional_paths=None, only_sql_dump=False, stream=False):
    """
    Creates a backup with proper file structure

    Args:
        db_name: Name of the database
        db_user: Database user
        sql_container: SQL container name
        data_container: Data container name
        backup_path: Backup path
        timestamp: Timestamp for the backup
        additional_paths: Additional paths to include in the backup
        only_sql_dump: If True, only back up the SQL dump, skip filestore
        stream: If True, stream a full backup straight into a single .tar.zst
                (Design A) instead of staging an uncompressed copy first.

    Returns:
        bool: Success status
    """
    docker_backup_path = os.path.join(backup_path, 'docker')
    # Set output_file_base without extension as the extension will be determined by the compression format
    output_file_base = f'{docker_backup_path}/{db_name}_{data_container}_dockerbackup_{timestamp}'
    
    # For SQL-only backups, add indicator to filename
    if only_sql_dump:
        output_file_base += '_sql_only'
    
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
        if only_sql_dump:
            print(f"SQL dump only mode: filestore will be skipped")

        # Decide whether to use the streaming full-backup path (Design A).
        # Streaming is opt-in and only applies to full backups. It requires
        # zstd, must not run with encryption (the .tar.zst path is unencrypted),
        # and needs the filestore to be resolvable on the host so tar can read
        # it in-place. Any unmet condition -> fall back to legacy staging.
        host_filestore = None
        use_stream = False
        if stream and not only_sql_dump:
            tools = check_compression_tools()
            enc_enabled, _ = get_encryption_settings()
            if not tools.get('zstd'):
                print("Streaming requested but zstd is not installed - "
                      "falling back to staged backup.")
            elif enc_enabled:
                print("Streaming requested but encryption is enabled - "
                      "streaming .tar.zst is unencrypted, falling back to "
                      "staged (encryptable) 7z backup.")
            else:
                host_filestore = resolve_filestore_host_path(data_container, db_name)
                if host_filestore:
                    use_stream = True
                else:
                    print("Streaming requested but the filestore host path could "
                          "not be resolved (no matching volume mount) - "
                          "falling back to staged backup.")

        # Disk pre-flight for full backups: refuse cleanly instead of failing
        # halfway with a swallowed error.
        if not only_sql_dump:
            db_size = get_database_size_bytes(sql_container, db_user, db_name)
            fs_size = get_filestore_size_bytes(data_container, db_name)
            ok, msg = disk_preflight(temp_dir, docker_backup_path, db_size,
                                     fs_size, use_stream)
            if not ok:
                print(f"ABORTING backup for {db_name}: insufficient disk space - {msg}")
                print("  Hint: enable streaming ('stream: true') to avoid the "
                      "uncompressed staging copy, free space, or point "
                      "'temp_path' at a larger mount.")
                return False

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
            
        # 2. Streaming path (Design A): pipe dump + in-place filestore into a
        #    single .tar.zst on the target. No uncompressed staging copy.
        if use_stream:
            level = config.get('defaults', {}).get('compression', {}).get('level', 5)
            output_file = stream_full_backup(
                temp_dir, output_file_base, host_filestore, db_name, level)
            if not output_file:
                return False
            print(f"Backup for {db_name} completed successfully")
            return True

        # 2b. Legacy staging path: extract filestore only if not SQL-only mode
        if not only_sql_dump:
            # Export filestore directly with database name as root
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
                # Extract filestore to temp directory with Odoo-standard name "filestore"
                filestore_dir = os.path.join(temp_dir, "filestore")
                os.makedirs(filestore_dir)

                # Extract filestore contents directly into "filestore" directory (Odoo-native format).
                # Uses a Python-side pipe (docker exec stdout -> local tar stdin) instead of
                # a shell pipeline to keep container/db names out of the shell.
                print(f"Extracting filestore for {db_name} using streaming")
                src_path = f"/opt/odoo/data/filestore/{db_name}"
                producer = subprocess.Popen(
                    ['docker', 'exec', data_container, 'tar', 'c', '-C', src_path, '.'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                consumer = subprocess.Popen(
                    ['tar', 'x', '-C', filestore_dir],
                    stdin=producer.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                # Allow producer to receive SIGPIPE if consumer exits early.
                if producer.stdout is not None:
                    producer.stdout.close()
                _, consumer_err = consumer.communicate()
                _, producer_err = producer.communicate()

                if producer.returncode != 0 or consumer.returncode != 0:
                    # A partial/empty filestore must NOT be silently compressed
                    # into a "successful" backup - treat it as fatal.
                    print(f"Error extracting filestore for {db_name}")
                    extract_error = (
                        (producer_err or b'').decode(errors='replace')
                        + (consumer_err or b'').decode(errors='replace')
                    )
                    if extract_error:
                        print(f"Extract error: {extract_error}")
                        if "Killed" in extract_error or "Cannot allocate memory" in extract_error:
                            print("The process was killed due to memory constraints.")
                            print("Consider running the backup with nohup or in a screen/tmux session with lower priority.")
                    print(f"Aborting backup for {db_name}: filestore extraction "
                          "failed - refusing to create a backup with an "
                          "incomplete filestore.")
                    return False

        # 3. Compress directory with configured format - now pass the only_sql_dump parameter
        output_file = compress_directory(temp_dir, output_file_base, config, only_sql_dump)

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
    # Service backups are not affected by SQL-only mode
    output_file = compress_directory(source_path, output_file_base, config, only_sql_dump=False)
    
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
    
    # FastReport is never affected by SQL-only mode
    output_file = compress_directory(report_path, output_file_base, config, only_sql_dump=False)
    
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

def compress_directory(source_dir, output_file_base, config, only_sql_dump=False):
    """
    Compresses a directory using the configured compression format
    
    Args:
        source_dir: Directory to compress
        output_file_base: Output file path without extension
        config: Configuration dictionary
        only_sql_dump: If True, only include the SQL dump file, not the entire directory
        
    Returns:
        str: Path to the compressed file
    """
    print(f"Starting compression process for {source_dir}")
    print(f"SQL-only mode: {only_sql_dump}")
    
    compression_config = config.get('defaults', {}).get('compression', {})
    compression_format = compression_config.get('format', '7z').lower()
    compression_level = compression_config.get('level', 5)
    
    print(f"Using compression format: {compression_format}, level: {compression_level}")
    
    # Check available compression tools
    tools = check_compression_tools()
    print(f"Available compression tools: {', '.join([tool for tool, available in tools.items() if available])}")
    
    encryption_enabled, password = get_encryption_settings()
    output_file = None
    
    # Wenn Verschlüsselung aktiviert ist, aber nicht 7z-Format, Warnung ausgeben
    # Aber das Format NICHT ändern, sondern die Verschlüsselung ignorieren
    if encryption_enabled and compression_format != '7z':
        print(f"WARNING: Encryption is only supported with 7z format. Your selected format is '{compression_format}'.")
        print("Encryption will be ignored for this backup.")
        encryption_enabled = False
    
    try:
        # SQL-only mode: determine files to include
        if only_sql_dump:
            print("SQL-only mode: Compressing only the SQL dump file")
            sql_dump_file = os.path.join(source_dir, "dump.sql")
            if not os.path.exists(sql_dump_file):
                print(f"Error: SQL dump file not found at {sql_dump_file}")
                # Check directory contents
                print(f"Directory contents of {source_dir}:")
                try:
                    for item in os.listdir(source_dir):
                        print(f"  - {item}")
                except Exception as e:
                    print(f"  Could not list directory: {str(e)}")
                return None
            else:
                print(f"Found SQL dump file: {sql_dump_file}, size: {os.path.getsize(sql_dump_file)} bytes")
                
        gpg_encrypt_pending = False
        if compression_format == '7z':
            # Überprüfen, ob 7zz verfügbar ist
            if not tools['7zz']:
                print("Error: 7zz command is not installed.")
                print("Please install a newer version of 7-Zip that provides the 7zz command.")
                return None
                
            output_file = f"{output_file_base}.7z"
            zip_args = ['7zz', 'a', f'-mx={compression_level}', '-t7z']
            if encryption_enabled:
                if shutil.which('gpg'):
                    # Encrypt with GPG after archiving: 7z's -p switch exposes
                    # the password in the process list (ps aux) for the whole
                    # compression run - GPG takes the passphrase via fd instead.
                    gpg_encrypt_pending = True
                else:
                    print("WARNING: gpg not found - falling back to 7z AES encryption.")
                    print("WARNING: The backup password is visible in the process list while 7zz runs.")
                    print("Install gnupg (apt-get install gnupg) for secure encryption.")
                    zip_args.extend(['-p' + password, '-mhe=on'])
                
            # Run 7zz with cwd=source_dir and relative inputs (like the zip
            # path). The previous code passed a literal '<source_dir>/*' argument
            # which 7zz does not reliably expand - depending on the build it
            # could archive nothing or behave inconsistently.
            if only_sql_dump:
                zip_args.extend([output_file, 'dump.sql'])
                print(f"7z command for SQL-only mode: {' '.join(zip_args)}")
            else:
                zip_args.extend([output_file, '.'])
                print(f"7z command for full backup: {' '.join(zip_args)}")

            print(f"Creating 7z archive with 7zz: {output_file}")
            result = subprocess.run(zip_args, cwd=source_dir,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
        elif compression_format == 'zip':
            if not tools['zip']:
                print("Error: zip command is not installed.")
                print("Please install zip with: sudo apt-get install zip")
                return None
                
            output_file = f"{output_file_base}.zip"

            # In SQL-only mode, only include dump.sql file
            if only_sql_dump:
                zip_args = ['zip', f'-{compression_level}', output_file, 'dump.sql']
                print(f"Zip command for SQL-only mode: {zip_args}")
            else:
                # Standard zip: cwd=source_dir, zip everything with '.'
                zip_args = ['zip', '-r', f'-{compression_level}', output_file, '.']
                print(f"Zip command for full backup: {zip_args}")

            print(f"Creating ZIP archive: {output_file}")
            result = subprocess.run(
                zip_args, cwd=source_dir,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        
        elif compression_format == 'gzip':
            if not tools['gzip']:
                print("Error: gzip command is not installed.")
                print("Please install gzip with: sudo apt-get install gzip")
                return None
                
            # SQL-only mode handled differently for gzip
            if only_sql_dump:
                output_file = f"{output_file_base}.sql.gz"
                dump_sql = os.path.join(source_dir, 'dump.sql')
                print(f"Creating gzipped SQL file: {output_file}")
                with open(output_file, 'wb') as out_fh:
                    result = subprocess.run(
                        ['gzip', f'-{compression_level}', '-c', dump_sql],
                        stdout=out_fh, stderr=subprocess.PIPE,
                    )
            else:
                # gzip requires tar to archive directory first
                output_file = f"{output_file_base}.tar.gz"
                parent_dir = os.path.dirname(source_dir)
                base_name = os.path.basename(source_dir)

                if platform.system() == 'Darwin':
                    # macOS tar has no -z support in older builds: two-stage tar + gzip
                    temp_tar = f"{output_file_base}.tar"
                    print(f"Creating tar archive: {temp_tar}")
                    tar_result = subprocess.run(
                        ['tar', '-cf', temp_tar, '-C', parent_dir, base_name],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    )

                    if tar_result.returncode == 0:
                        print(f"Compressing with gzip (level {compression_level}): {output_file}")
                        result = subprocess.run(
                            ['gzip', f'-{compression_level}', '-f', temp_tar],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        )
                    else:
                        print(f"Error creating tar archive: {temp_tar}")
                        if tar_result.stderr:
                            print(f"Error details: {tar_result.stderr.decode(errors='replace')}")
                        return None
                else:
                    # Linux tar supports direct gzip compression
                    print(f"Creating tar.gz archive: {output_file}")
                    result = subprocess.run(
                        ['tar', '-czf', output_file, '-C', parent_dir, base_name],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    )
            
        elif compression_format == 'zstd':
            if not tools['zstd']:
                print("Error: zstd command is not installed.")
                print("Please install zstd with: sudo apt-get install zstd")
                return None
                
            # SQL-only mode handled differently for zstd
            if only_sql_dump:
                output_file = f"{output_file_base}.sql.zst"
                dump_sql = os.path.join(source_dir, 'dump.sql')
                print(f"Creating zstd compressed SQL file: {output_file}")
                with open(output_file, 'wb') as out_fh:
                    result = subprocess.run(
                        ['zstd', f'-{compression_level}', '-c', dump_sql],
                        stdout=out_fh, stderr=subprocess.PIPE,
                    )
            else:
                # zstd: tar | zstd via Python-side pipe (no shell)
                output_file = f"{output_file_base}.tar.zst"
                parent_dir = os.path.dirname(source_dir)
                base_name = os.path.basename(source_dir)
                print(f"Creating tar.zst archive: {output_file}")

                producer = subprocess.Popen(
                    ['tar', '-C', parent_dir, '-cf', '-', base_name],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                consumer = subprocess.Popen(
                    ['zstd', f'-{compression_level}', '-o', output_file],
                    stdin=producer.stdout,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                if producer.stdout is not None:
                    producer.stdout.close()
                _, consumer_err = consumer.communicate()
                _, producer_err = producer.communicate()

                # Synthesize a result object matching the shape used below.
                class _Result:
                    pass
                result = _Result()
                result.returncode = producer.returncode or consumer.returncode
                result.stderr = (producer_err or b'') + (consumer_err or b'')
                result.stdout = b''
        
        else:
            print(f"Error: Unsupported compression format: {compression_format}")
            print("Supported formats: 7z, zip, gzip, zstd")
            return None
        
        if result.returncode != 0:
            # Surface the FULL context (command, return code/signal, stderr AND
            # stdout, free disk space). The old code printed only stderr and
            # only if it was non-empty - a signal kill (e.g. OOM) leaves stderr
            # empty, which is exactly why this failure was invisible before.
            _report_failure_context(
                "archive creation", locals().get('zip_args'),
                result.returncode, getattr(result, 'stdout', None),
                getattr(result, 'stderr', None),
                [output_file, source_dir])
            _remove_partial_archive(output_file)
            return None

        # Check if output file was created and get its size
        if os.path.exists(output_file):
            file_size = os.path.getsize(output_file)
            print(f"Archive created successfully: {output_file} (size: {file_size} bytes)")
            if gpg_encrypt_pending:
                print(f"Encrypting archive with GPG (AES-256): {output_file}.gpg")
                encrypted_file = encrypt_file_with_gpg(output_file, password)
                if encrypted_file is None:
                    # Keep the unencrypted backup rather than losing it -
                    # a plaintext backup beats no backup, but warn loudly.
                    print("WARNING: GPG encryption FAILED - keeping UNENCRYPTED archive!")
                    print(f"WARNING: {output_file} is NOT encrypted.")
                    return output_file
                encrypted_size = os.path.getsize(encrypted_file)
                print(f"Archive encrypted successfully: {encrypted_file} (size: {encrypted_size} bytes)")
                print("Decrypt with: gpg -d <file>.7z.gpg > <file>.7z")
                return encrypted_file
            return output_file
        else:
            print(f"Error: Output file {output_file} was not created")
            return None
        
    except Exception as e:
        print(f"Unexpected error during compression: {str(e)}")
        # Print detailed traceback
        import traceback
        print(traceback.format_exc())
        _remove_partial_archive(output_file)
        return None

# Main script
if __name__ == "__main__":
    # Display version information
    print("===================================================")
    print("Odoo Docker Backup System")
    print(f"Version: {SCRIPT_VERSION}")
    print(f"Date: {SCRIPT_DATE}")
    print("===================================================")
    
    # Display system information
    print(f"Operating System: {platform.system()} {platform.release()}")
    print(f"Python Version: {platform.python_version()}")
    try:
        # Try to get more detailed OS information
        if platform.system() == 'Linux':
            with open('/etc/os-release', 'r') as f:
                os_info = f.read()
            print(f"OS Release: \n{os_info}")
        print(f"Machine: {platform.machine()}")
    except Exception as e:
        print(f"Could not get detailed system information: {str(e)}")
    print("===================================================")
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Backup Odoo databases with Docker')
    parser.add_argument('--sql-only', action='store_true', 
                        help='Force SQL dump only mode for all databases (overrides YAML settings)')
    args = parser.parse_args()
    
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

            # Only prompt when attached to a terminal. Under cron stdin is not a
            # TTY, so input() would raise EOFError (or hang); abort cleanly instead
            # — consistent with the interactive default (Enter = N = abort).
            if sys.stdin.isatty():
                response = input("Do you want to continue anyway? (y/N): ")
                if response.lower() != 'y':
                    print("Backup aborted.")
                    exit(1)
            else:
                print("Non-interactive run with path issues — aborting backup "
                      "(run interactively to override).")
                exit(1)
        
        # Get default settings
        defaults = config.get('defaults', {})
        default_retention = defaults.get('retention_days', 14)
        default_db_user = defaults.get('db_user', 'ownerp')
        
        # Get default additional paths
        default_additional_paths = defaults.get('additional_paths', {})
        
        # Process each database
        for db in config.get('databases', []):
            # Validate identifiers before any subprocess/filesystem use.
            # Invalid config entries are skipped rather than aborting the run.
            try:
                db_name = _validate_identifier(db['name'], 'database name')
                db_user = _validate_identifier(
                    db.get('db_user', default_db_user), 'db_user'
                )
                sql_container = _validate_identifier(
                    db['sql_container'], 'sql_container'
                )
                data_container = _validate_identifier(
                    db['data_container'], 'data_container'
                )
            except ValueError as exc:
                print(f"Skipping invalid database entry: {exc}")
                continue
            retention_days = db.get('retention_days', default_retention)
            
            # Get only_sql_dump setting for this database (default to False if not specified)
            # Override with command line argument if --sql-only is provided
            only_sql_dump = args.sql_only or db.get('only_sql_dump', False)

            # Streaming full backup (Design A): per-db override, else defaults.
            stream = db.get('stream', defaults.get('stream', False))
            
            print(f"\nProcessing backup for database {db_name}")
            print(f"Using container: {sql_container}")
            if only_sql_dump:
                print(f"SQL dump only mode: filestore will be skipped")
                if args.sql_only:
                    print("(SQL-only mode forced by command line parameter)")
            
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
                additional_paths,
                only_sql_dump,
                stream=stream
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
            import shlex
            rsync_commands = rsync_config.get('commands', [])
            for cmd in rsync_commands:
                # Parse into an argument list (no shell) and only allow the
                # rsync binary - the YAML config must not become a generic
                # root command runner.
                cmd_args = shlex.split(cmd)
                if not cmd_args or os.path.basename(cmd_args[0]) != 'rsync':
                    print(f"SECURITY: Skipping non-rsync command from config: {cmd}")
                    continue
                print(f"Running: {cmd}")
                subprocess.run(cmd_args, check=False)
            
    except yaml.YAMLError as e:
        print(f"Error reading YAML configuration: {str(e)}")
        exit(1)
    except KeyError as e:
        print(f"Missing required configuration field: {str(e)}")
        exit(1)

    print('Backup completed!')
