#!/usr/bin/python3
# -*- coding: utf-8 -*-
# This script performs an update of an Odoo database in a Docker container
# Version 5.1.6
# Date 15.07.2025
##############################################################################
#
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
##############################################################################
import os
import sys
import time
import yaml
import platform
import logging
import argparse
import subprocess
from os.path import expanduser, isdir, isfile, join
import threading
import select

# Set up logging - Default to WARNING level
logging.basicConfig(
    level=logging.WARNING,  # Default to WARNING level now
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Default configuration
home_path = expanduser("~")
# First check if config file exists in current directory, then fall back to home directory
current_dir_config = "docker2update.yaml"
home_config = join(home_path, "docker2update.yaml")
default_config_file = current_dir_config if isfile(current_dir_config) else home_config
git_path = "https://rm.ownerp.io/staff/v"
build_script = "-muster/build_odoo.py"
check_script = "-muster/check_dockerimage_odoo.py"

# Check if we are running on macOS or Linux
is_macos = platform.system() == 'Darwin'

def expand_path(path):
    """Expand environment variables and ~ in paths."""
    if not path:
        return path
    # First expand the standard HOME variable with ~
    expanded_path = os.path.expanduser(path)
    # Then expand any other environment variables
    expanded_path = os.path.expandvars(expanded_path)
    return expanded_path

def optimize_dns_for_container(volume_config):
    """
    Optimize DNS configuration for Docker containers.
    
    Args:
        volume_config (str): Current volume configuration string
        
    Returns:
        tuple: (optimized_volume_config, was_modified)
    """
    if not volume_config:
        volume_config = ""
    
    # Recommended DNS servers for optimal performance
    recommended_dns = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
    
    # Check if DNS is already configured in the container
    if "--dns" in volume_config:
        logger.info("DNS servers already configured in volume settings")
        return volume_config, False
    
    # IMPORTANT: Docker containers do NOT inherit host DNS configuration by default!
    # Docker uses its own DNS resolver (127.0.0.11) which may use different DNS servers
    # than the host system. Therefore, we should ALWAYS optimize container DNS unless
    # it's already explicitly configured.
    
    # Check host DNS for informational purposes only
    host_dns_info = []
    try:
        if os.path.exists("/etc/resolv.conf"):
            with open("/etc/resolv.conf", "r") as f:
                content = f.read()
                for line in content.split('\n'):
                    if line.strip().startswith('nameserver'):
                        nameserver = line.split()[1] if len(line.split()) > 1 else None
                        if nameserver:
                            host_dns_info.append(nameserver)
    except Exception as e:
        logger.warning(f"Could not check host DNS configuration: {e}")
    
    # Log host DNS information
    if host_dns_info:
        primary_dns = host_dns_info[0]
        if primary_dns in recommended_dns:
            logger.info(f"Host DNS is optimized with {primary_dns}, but containers need explicit DNS configuration")
        else:
            logger.info(f"Host DNS uses {primary_dns}, containers will be optimized with better DNS servers")
    else:
        logger.info("Could not determine host DNS configuration")
    
    # Always add DNS optimization to containers unless already configured
    logger.info("Adding DNS optimization to container for better performance and reliability")
    dns_args = " ".join([f"--dns {dns}" for dns in recommended_dns])
    
    # Add DNS configuration to volume string
    if volume_config.strip():
        volume_config = f"{volume_config} {dns_args}"
    else:
        volume_config = dns_args
    
    logger.info(f"Added DNS servers to container: {dns_args}")
    return volume_config, True

def save_updated_config(config, config_file):
    """
    SIMPLE and WORKING approach: Replace volume lines directly using string replacement.
    This avoids complex YAML parsing issues.
    
    Args:
        config (dict): Configuration dictionary
        config_file (str): Path to configuration file
    """
    try:
        # Create backup of original file
        backup_file = f"{config_file}.backup"
        if os.path.exists(config_file):
            import shutil
            shutil.copy2(config_file, backup_file)
            logger.info(f"Backup created: {backup_file}")
        
        # Read the file as text
        with open(config_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # For each container, find and replace its volume line
        for container in config['containers']:
            container_name = container.get('container_name', '')
            new_volume = container.get('volume', '')
            
            # Skip if no volume configuration
            if not new_volume or not container_name:
                continue
                
            # Find the old volume line for this container
            # Look for pattern: volume: "old_value" after container_name: "container_name"
            lines = content.split('\n')
            container_found = False
            
            for i, line in enumerate(lines):
                # Look for container name
                if f'container_name: "{container_name}"' in line:
                    container_found = True
                    continue
                    
                # If we found the container, look for the volume line
                if container_found and 'volume:' in line:
                    # Extract the indentation
                    indent = len(line) - len(line.lstrip())
                    indent_str = ' ' * indent
                    
                    # Replace the line with new volume configuration
                    lines[i] = f'{indent_str}volume: "{new_volume}"'
                    container_found = False  # Reset for next container
                    break
        
        # Write the modified content back
        modified_content = '\n'.join(lines)
        with open(config_file, 'w', encoding='utf-8') as f:
            f.write(modified_content)
        
        logger.info(f"Updated configuration saved to: {config_file} (preserving original format)")
        return True
        
    except Exception as e:
        logger.error(f"Failed to save updated configuration: {e}")
        # Fallback to restore backup
        try:
            if os.path.exists(backup_file):
                import shutil
                shutil.copy2(backup_file, config_file)
                logger.info("Restored original configuration from backup")
        except Exception as restore_error:
            logger.error(f"Failed to restore backup: {restore_error}")
        return False

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Update Odoo Docker containers based on YAML configuration.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python3 update_docker_odoo.py                       # Use default config file
  python3 update_docker_odoo.py -c my_config.yaml     # Use custom config file
  python3 update_docker_odoo.py -v                    # Verbose output
  python3 update_docker_odoo.py -s live-odoo          # Update only specified container
  python3 update_docker_odoo.py --validate            # Only validate config, don't update
  python3 update_docker_odoo.py --dns-optimize        # Only optimize DNS configuration
  
Configuration File Format (YAML):
  containers:
    - active: true
      type: "F"                                   # F=Full, M=Module, N=Neutralize
      delay_time: 30                              # Seconds to wait after restart
      container_name: "live-odoo"                 # Docker container name
      database_name: "live_db"                    # Odoo database name
      port: "127.0.0.1:11000"                     # HTTP port mapping
      longpolling_port: "127.0.0.1:12000"         # Longpolling port mapping
      dockerfile_path: "/path/to/dockerfile/dir/" # Where Dockerfile is located
      docker_image_name: "odoo/live"              # Image name to build
      db_user: "user"                             # Database username
      db_password: "password"                     # Database password
      db_host: "db-host"                          # Database hostname/IP
      volume: "--network net -v /path:/data"      # Docker volume config (DNS auto-optimized)
      odoo_version: "16"                          # Odoo version for scripts
      translate: "Y"                              # Load translations? Y/N
      
Note: DNS optimization is automatically applied to containers if host DNS is not optimal.
      This helps resolve DNS issues between different cloud providers (e.g., Hetzner <-> DigitalOcean).
'''
    )
    
    parser.add_argument('-c', '--config', 
                        default=default_config_file,
                        help=f'Path to configuration YAML file (default: {default_config_file})')
    
    parser.add_argument('-v', '--verbose', 
                        action='store_true',
                        help='Increase output verbosity')
    
    parser.add_argument('-s', '--specific-container',
                        help='Update only the specified container')
    
    parser.add_argument('--validate', 
                        action='store_true',
                        help='Only validate the configuration without performing updates')
    
    parser.add_argument('--dns-optimize', 
                        action='store_true',
                        help='Only optimize DNS configuration without performing updates')
    
    return parser.parse_args()

def run_command(command, show_output=True, filter_output=False, show_progress=False, progress_msg=None, timeout=None):
    """Run a shell command with proper error handling and output filtering."""
    try:
        if show_output and not filter_output and logger.level <= logging.INFO:
            logger.info(f"Running command: {command}")
        
        # Set up process with pipes
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1  # Line buffered
        )
        
        # Variables to store filtered output
        all_warnings = []
        all_errors = []
        warnings_count = 0
        errors_count = 0
        info_count = 0  # Counter for INFO messages
        
        # Start progress indicator if requested
        progress_thread = None
        stop_progress = False
        progress_lock = threading.Lock()
        
        if show_progress:
            def show_spinner():
                spinner = "|/-\\"
                idx = 0
                msg = progress_msg or "Processing"
                while not stop_progress:
                    with progress_lock:
                        sys.stdout.write(f"\r{msg} {spinner[idx % len(spinner)]} ")
                        sys.stdout.flush()
                    idx += 1
                    time.sleep(0.1)
                # Clear the line when done
                with progress_lock:
                    sys.stdout.write("\r" + " " * (len(msg) + 10) + "\r")
                    sys.stdout.flush()
            
            progress_thread = threading.Thread(target=show_spinner)
            progress_thread.daemon = True
            progress_thread.start()
        
        # Read output line by line
        stdout_lines = []
        stderr_lines = []
        
        # Function to read from a pipe with a timeout, collecting important messages
        def read_pipe(pipe, line_list, timeout):
            nonlocal warnings_count, errors_count, info_count  # Add info_count to nonlocal
            end_time = time.time() + timeout if timeout else None
            while True:
                if end_time and time.time() > end_time:
                    raise TimeoutError("Command timed out")
                
                # Wait for data with a small timeout
                readable, _, _ = select.select([pipe], [], [], 0.1)
                if not readable:
                    # Check if process is still running
                    if process.poll() is not None:
                        break
                    continue
                
                line = pipe.readline()
                if not line:
                    break
                
                line_list.append(line)
                stripped_line = line.strip()
                
                # Analyze output for warnings and errors
                lower_line = stripped_line.lower()
                is_error = False
                is_warning = False
                is_info = True  # Default to info unless determined otherwise
                
                # Check for actual log level indicators at the beginning
                # Typical Odoo log format: "2025-02-28 08:32:13,414 10 INFO live_odoo ..."
                # or standard log format: "2025-02-28 09:32:13,415 - ERROR - ..."
                if " ERROR " in stripped_line or stripped_line.startswith("ERROR:") or " - ERROR - " in stripped_line:
                    is_error = True
                    is_info = False
                elif " WARNING " in stripped_line or stripped_line.startswith("WARNING:") or " - WARNING - " in stripped_line:
                    is_warning = True
                    is_info = False
                # For Odoo format logs: only check the actual log level, not the content
                elif "INFO " in stripped_line and ("error" in lower_line or "exception" in lower_line):
                    # This is an INFO log that happens to contain the word "error" or "exception"
                    is_error = False
                    is_info = True
                elif "WARNING " in stripped_line:
                    is_warning = True
                    is_info = False
                elif "ERROR " in stripped_line or "CRITICAL " in stripped_line:
                    is_error = True
                    is_info = False
                # General case for non-odoo format where error appears in the line content
                elif "error: " in lower_line or "exception: " in lower_line or lower_line.startswith("error") or lower_line.startswith("exception"):
                    is_error = True
                    is_info = False
                elif "warning: " in lower_line or lower_line.startswith("warning"):
                    is_warning = True
                    is_info = False
                    
                if is_error:
                    errors_count += 1
                    all_errors.append(stripped_line)
                    # Always show errors
                    with progress_lock:
                        sys.stdout.write("\r" + " " * 80 + "\r")  # Clear spinner line
                        logger.error(stripped_line)
                elif is_warning:
                    warnings_count += 1
                    all_warnings.append(stripped_line)
                    # Always show warnings
                    with progress_lock:
                        sys.stdout.write("\r" + " " * 80 + "\r")  # Clear spinner line
                        logger.warning(stripped_line)
                elif is_info:
                    info_count += 1  # Count info messages
                    # Show info messages if not filtered or in verbose mode
                    if not filter_output and (show_output or logger.level <= logging.INFO):
                        with progress_lock:
                            sys.stdout.write("\r" + " " * 80 + "\r")  # Clear spinner line
                            logger.info(stripped_line)
        
        # Start threads to read stdout and stderr
        stdout_thread = threading.Thread(
            target=read_pipe, 
            args=(process.stdout, stdout_lines, timeout)
        )
        stderr_thread = threading.Thread(
            target=read_pipe, 
            args=(process.stderr, stderr_lines, timeout)
        )
        
        stdout_thread.daemon = True
        stderr_thread.daemon = True
        stdout_thread.start()
        stderr_thread.start()
        
        # Wait for process to complete
        try:
            exit_code = process.wait(timeout=timeout)
            stdout_thread.join(1)
            stderr_thread.join(1)
        except subprocess.TimeoutExpired:
            process.kill()
            stop_progress = True
            if progress_thread:
                progress_thread.join(1)
            logger.error(f"Command timed out after {timeout} seconds")
            return False, "Command timed out", 0, 0, 1  # Return counts with the error
        
        # Stop progress indicator
        stop_progress = True
        if progress_thread:
            progress_thread.join(1)
        
        stdout_output = "".join(stdout_lines)
        stderr_output = "".join(stderr_lines)
        
        # Show summary of warnings and errors
        if filter_output and (warnings_count > 0 or errors_count > 0):
            summary = []
            if warnings_count > 0:
                summary.append(f"{warnings_count} warning(s)")
            if errors_count > 0:
                summary.append(f"{errors_count} error(s)")
                
            if summary:
                logger.warning(f"Command completed with {' and '.join(summary)}")
                
                # Show errors first
                if errors_count > 0:
                    logger.warning("--- ERRORS ---")
                    for msg in all_errors:
                        logger.error(msg)
                
                # Then show warnings
                if warnings_count > 0:
                    logger.warning("--- WARNINGS ---")
                    for msg in all_warnings:
                        logger.warning(msg)
        
        if exit_code != 0:
            logger.error(f"Command failed with exit code {exit_code}")
            if stderr_output and not filter_output and logger.level <= logging.INFO:
                logger.error(stderr_output)
            return False, stderr_output, info_count, warnings_count, errors_count
        
        # Only show success message in verbose mode or if warnings/errors occurred
        if filter_output and errors_count == 0 and warnings_count == 0 and logger.level <= logging.INFO:
            logger.info("Command completed successfully with no warnings or errors")
            
        return True, stdout_output, info_count, warnings_count, errors_count
    except Exception as e:
        stop_progress = True
        if 'progress_thread' in locals() and progress_thread:
            progress_thread.join(1)
        logger.error(f"Exception running command: {e}")
        return False, str(e), 0, 0, 1  # Return counts with the error

def load_config(config_file):
    """Load configuration from YAML file."""
    try:
        if not isfile(config_file):
            logger.error(f"Configuration file not found: {config_file}")
            return None
            
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
            
        if not config or 'containers' not in config:
            logger.error("Invalid configuration file format. 'containers' section is missing.")
            return None
            
        return config
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML configuration: {e}")
        return None
    except Exception as e:
        logger.error(f"Error loading configuration: {e}")
        return None

def validate_container_config(container):
    """Validate container configuration."""
    required_fields = [
        'type', 'container_name', 'database_name', 'port', 'longpolling_port',
        'dockerfile_path', 'docker_image_name', 'db_user', 'db_password', 'db_host'
    ]
    
    for field in required_fields:
        if field not in container or not container[field]:
            logger.error(f"Missing required field in container configuration: {field}")
            return False
    
    # Expand and validate dockerfile path
    if 'dockerfile_path' in container:
        container['dockerfile_path'] = expand_path(container['dockerfile_path'])
    
    # Validate update type
    if container['type'] not in ['F', 'M', 'N']:
        logger.error(f"Invalid update type: {container['type']}. Must be 'F', 'M', or 'N'.")
        return False
        
    # Validate Dockerfile path
    if not isdir(container['dockerfile_path']):
        logger.error(f"Dockerfile path does not exist: {container['dockerfile_path']}")
        return False
        
    return True

def clean_docker_system():
    """
    Run docker system prune -f to clean up the Docker system.
    Removes all stopped containers, networks not used by at least one container,
    all dangling images, and unused build cache.
    """
    logger.info("Cleaning up Docker system...")
    success, _, info, warn, err = run_command("docker system prune -f", show_output=True)
    if success:
        logger.info("Docker system cleaned successfully")
    else:
        logger.warning("Failed to clean Docker system")
    return info, warn, err

def process_container(container):
    """Process a single container update."""
    # Set default values if missing
    container.setdefault('delay_time', 30)
    container.setdefault('volume', "")
    container.setdefault('odoo_version', "")
    container.setdefault('translate', "N")
    
    # Statistics counters
    total_info = 0
    total_warnings = 0
    total_errors = 0
    
    # Extract configuration values
    update_type = container['type']
    delay_time = int(container['delay_time'])
    container_name = container['container_name']
    db_name = container['database_name']
    port = container['port']
    poll_port = container['longpolling_port']
    path = expand_path(container['dockerfile_path'])  # Ensure path is expanded
    image = container['docker_image_name']
    db_user = container['db_user']
    db_password = container['db_password']
    db_host = container['db_host']
    volume = expand_path(container.get('volume', ""))  # Expand env vars in volume
    version = container['odoo_version']
    translation = container['translate']
    
    # Log container info
    logger.info(f"{'='*80}")
    logger.info(f"Processing container: {container_name}")
    logger.info(f"Update type: {'Full update' if update_type == 'F' else 'Module copy' if update_type == 'M' else 'Neutralize and update'}")
    logger.info(f"Database: {db_name}")
    logger.info(f"Ports: {port} (HTTP), {poll_port} (Longpolling)")
    logger.info(f"Dockerfile path: {path}")
    logger.info(f"Docker image: {image}")
    if version:
        logger.info(f"Odoo version: {version}")
    if volume:
        logger.info(f"Volume: {volume}")
    logger.info(f"{'='*80}")
    
    # Change to Dockerfile directory - This is critical for docker build
    try:
        original_dir = os.getcwd()  # Remember original directory
        logger.info(f"Changing to directory: {path}")
        os.chdir(path)
    except Exception as e:
        logger.error(f"Failed to change to directory {path}: {e}")
        return False, total_info, total_warnings, total_errors
    
    # Backup filestore if no volume is specified
    if not volume:
        filestore_path = join(path, db_name)
        logger.info(f"Backing up filestore to {filestore_path}")
        
        # Create directory for filestore backup
        success, _, info, warn, err = run_command(f"mkdir -p {filestore_path}")
        total_info += info
        total_warnings += warn
        total_errors += err
        if not success:
            logger.error("Failed to create directory for filestore backup")
            return False, total_info, total_warnings, total_errors
            
        # Copy filestore from container
        success, _, info, warn, err = run_command(f"docker cp {container_name}:/opt/odoo/data/filestore/{db_name} {path}")
        total_info += info
        total_warnings += warn
        total_errors += err
        if not success:
            logger.warning("Failed to copy filestore from container. This might be normal for a new setup.")
        else:
            logger.info("Filestore saved successfully")
    
    # Get new version of build scripts - Fix script name inconsistency
    if version:
        logger.info("Downloading build scripts...")
        # Use consistent script names
        download_build_script = f"{git_path}{version}{build_script}"
        download_check_script = f"{git_path}{version}{check_script}"
        
        logger.info(f"Downloading build script from: {download_build_script}")
        success, _, info, warn, err = run_command(f"wget -q -N --timeout=30 --tries=3 {download_build_script}", timeout=60)
        total_info += info
        total_warnings += warn
        total_errors += err
        if not success:
            logger.warning(f"Failed to download build script from {download_build_script} - continuing anyway")
        
        logger.info(f"Downloading check script from: {download_check_script}")
        success, _, info, warn, err = run_command(f"wget -q -N --timeout=30 --tries=3 {download_check_script}", timeout=60)
        total_info += info
        total_warnings += warn
        total_errors += err
        if not success:
            logger.warning(f"Failed to download check script from {download_check_script} - continuing anyway")
    
    # Override logging level for debugging critical sections
    original_level = logger.level

    # Run release manager to get latest Docker image if access file exists
    # Use the correct script name based on what we have in the directory
    check_script_name = "check_dockerimage_odoo.py"
    if not isfile(check_script_name):
        check_script_name = "check_dockerimage_myodoo.py"  # Try alternative name

    access_file_name = "release.txt"
    if not isfile(access_file_name):
        access_file_name = "access_myodoo.txt"  # Try alternative name
        
    if isfile(check_script_name) and isfile(access_file_name):
        logger.info(f"Running release manager using {check_script_name}...")
        # Temporarily increase log level for critical operations
        logger.setLevel(logging.INFO)
        success, _, info, warn, err = run_command(f"python3 {check_script_name}")
        total_info += info
        total_warnings += warn
        total_errors += err
        # Restore original log level
        logger.setLevel(original_level)
        if not success:
            logger.warning("Failed to run release manager check script - continuing anyway")
    else:
        logger.warning(f"Skipping release manager check - files not found: {check_script_name} or {access_file_name}")
        total_warnings += 1
    
    # Stop and remove container - Always show these critical operations
    logger.setLevel(logging.INFO)
    logger.info(f"Stopping container {container_name}...")
    _, _, info, warn, err = run_command(f"docker stop {container_name}", show_output=False)
    total_info += info
    total_warnings += warn
    total_errors += err
    logger.info(f"Removing container {container_name}...")
    _, _, info, warn, err = run_command(f"docker rm {container_name}", show_output=False)
    total_info += info
    total_warnings += warn
    total_errors += err

    # Remove image
    logger.info(f"Removing Docker image {image}:latest...")
    _, _, info, warn, err = run_command(f"docker rmi {image}:latest", show_output=False)
    total_info += info
    total_warnings += warn
    total_errors += err
    # Restore original log level
    logger.setLevel(original_level)
    
    # Verify Dockerfile exists
    if not isfile('Dockerfile'):
        logger.error(f"Dockerfile not found in {path}")
        total_errors += 1
        try:
            os.chdir(original_dir)  # Change back to original directory
        except:
            pass
        return False, total_info, total_warnings, total_errors
        
    # Build new image
    print(f"Building new Docker image {image} in {os.getcwd()}...")
    print("This process downloads 977 modules individually and may take 10-20 minutes")
    print("Progress will be shown below - please wait...")
    
    success, _, info, warn, err = run_command(f"docker build -t {image} .", timeout=3600)
    total_info += info
    total_warnings += warn
    total_errors += err
    if not success:
        print("ERROR: Failed to build Docker image")
        print("This may be due to:")
        print("- Network timeout while downloading modules")
        print("- Insufficient disk space")
        print("- Build process was interrupted")
        print("You can retry the build by running the script again")
        try:
            os.chdir(original_dir)  # Change back to original directory
        except:
            pass
        return False, total_info, total_warnings, total_errors
    
    # Set translation parameter
    load_translation = " --i18n-overwrite --load-language=all" if translation.upper() == "Y" else ""
    
    # Perform update based on type
    if update_type == "F":
        # Full update
        if logger.level <= logging.INFO:
            logger.info(f"Performing full update of {container_name}...")
        update_command = f"docker run -it --rm -p {port}:8069 -p {poll_port}:8072 --name={container_name} {volume} {image} update --database={db_name} --db_user={db_user} --db_password={db_password} --db_host={db_host}{load_translation}"
        
        # Only show full command in verbose mode
        if logger.level <= logging.DEBUG:
            logger.info(f"Update command: {update_command}")
        
        # Set filter_output based on verbose mode
        should_filter = logger.level > logging.INFO  # Only filter if NOT verbose
        show_full_output = logger.level <= logging.INFO
        success, _, info, warn, err = run_command(
            update_command, 
            show_output=True,  # Always show output
            filter_output=should_filter,  # Only filter if not verbose
            show_progress=True,
            progress_msg=f"Updating database {db_name}",
            timeout=1800  # 30 minute timeout
        )
        total_info += info
        total_warnings += warn
        total_errors += err
        if not success:
            logger.error("Update failed")
            try:
                os.chdir(original_dir)  # Change back to original directory
            except:
                pass
            return False, total_info, total_warnings, total_errors
            
    elif update_type == "N":
        # Neutralize and update
        logger.info(f"Neutralizing database in {container_name}...")
        neutralize_command = f"docker run -it --rm -p {port}:8069 -p {poll_port}:8072 --name={container_name} {volume} {image} neutralize --database={db_name} --db_user={db_user} --db_password={db_password} --db_host={db_host}"
        
        # Only show full command in verbose mode
        if logger.level <= logging.DEBUG:
            logger.info(f"Neutralize command: {neutralize_command}")
        
        # Set filter_output based on verbose mode
        should_filter = logger.level > logging.INFO  # Only filter if NOT verbose
        show_full_output = logger.level <= logging.INFO
        logger.info(f"Starting Odoo neutralization process (use -v for detailed output)...")
        success, _, info, warn, err = run_command(
            neutralize_command, 
            show_output=True,  # Always show output
            filter_output=should_filter,  # Only filter if not verbose
            show_progress=True,
            progress_msg=f"Neutralizing database {db_name}",
            timeout=900  # 15 minute timeout
        )
        total_info += info
        total_warnings += warn
        total_errors += err
        if not success:
            logger.error("Neutralize failed")
            try:
                os.chdir(original_dir)  # Change back to original directory
            except:
                pass
            return False, total_info, total_warnings, total_errors
            
        logger.info(f"Performing update after neutralization...")
        update_command = f"docker run -it --rm -p {port}:8069 -p {poll_port}:8072 --name={container_name} {volume} {image} update --database={db_name} --db_user={db_user} --db_password={db_password} --db_host={db_host}{load_translation}"
        
        # Only show full command in verbose mode
        if logger.level <= logging.DEBUG:
            logger.info(f"Update command: {update_command}")
        
        # Set filter_output based on verbose mode
        should_filter = logger.level > logging.INFO  # Only filter if NOT verbose
        show_full_output = logger.level <= logging.INFO
        logger.info(f"Starting Odoo update process (use -v for detailed output)...")
        success, _, info, warn, err = run_command(
            update_command, 
            show_output=True,  # Always show output
            filter_output=should_filter,  # Only filter if not verbose
            show_progress=True,
            progress_msg=f"Updating database {db_name}",
            timeout=1800  # 30 minute timeout
        )
        total_info += info
        total_warnings += warn
        total_errors += err
        if not success:
            logger.error("Update failed")
            try:
                os.chdir(original_dir)  # Change back to original directory
            except:
                pass
            return False, total_info, total_warnings, total_errors
    
    # Restart container
    logger.info(f"Restarting container {container_name}...")
    restart_command = f"docker run -d --restart=always -p {port}:8069 -p {poll_port}:8072 --name={container_name} {volume} {image} start"
    logger.info(f"Restart command: {restart_command}")
    success, _, info, warn, err = run_command(restart_command)
    total_info += info
    total_warnings += warn
    total_errors += err
    if not success:
        logger.error("Failed to restart container")
        return False, total_info, total_warnings, total_errors
    
    # Show countdown for delay time instead of silent sleep
    if delay_time > 0:
        logger.info(f"Waiting {delay_time} seconds for container to initialize...")
        try:
            for remaining in range(delay_time, 0, -1):
                sys.stdout.write(f"\rWaiting: {remaining} seconds remaining... (Ctrl+C to skip) ")
                sys.stdout.flush()
                time.sleep(1)
            sys.stdout.write("\rWait completed.                                           \n")
        except KeyboardInterrupt:
            sys.stdout.write("\rWait skipped by user.                                     \n")
            logger.info("Wait period skipped by user.")
    
    # Run additional scripts if they exist
    remove_menus_script = join(path, "remove_website_menus.py")
    if isfile(remove_menus_script):
        logger.info("Running script to remove website menus...")
        success, _, info, warn, err = run_command(f"python3 {remove_menus_script}")
        total_info += info
        total_warnings += warn
        total_errors += err
        if not success:
            logger.warning("Failed to run remove_website_menus.py script")
            total_warnings += 1
        
        cleanup_script = join(path, "cleanup_odoo.py")
        if isfile(cleanup_script):
            logger.info("Running cleanup script...")
            success, _, info, warn, err = run_command(f"python3 {cleanup_script}")
            total_info += info
            total_warnings += warn
            total_errors += err
            if not success:
                logger.warning("Failed to run cleanup_odoo.py script")
                total_warnings += 1
    
    # Clean up old filestore backups
    backup_path = f"{path}{db_name}.bak"
    if isdir(backup_path):
        logger.info(f"Removing old filestore backup: {backup_path}")
        _, _, info, warn, err = run_command(f"rm -rf {backup_path}")
        total_info += info
        total_warnings += warn
        total_errors += err
    
    if isdir(join(path, db_name)):
        logger.info(f"Moving current filestore to backup: {path}{db_name} -> {backup_path}")
        _, _, info, warn, err = run_command(f"mv {path}{db_name} {backup_path}")
        total_info += info
        total_warnings += warn
        total_errors += err
    
    # Clean up Docker system
    logger.info("Running Docker system cleanup...")
    info, warn, err = clean_docker_system()
    total_info += info
    total_warnings += warn
    total_errors += err
    
    # Change back to original directory at the end
    try:
        os.chdir(original_dir)
    except Exception as e:
        logger.warning(f"Failed to change back to original directory: {e}")
        total_warnings += 1
    
    logger.info(f"Update of {db_name} completed successfully")
    return True, total_info, total_warnings, total_errors

def main():
    """Main function."""
    # Set start time to measure total execution time
    start_time = time.time()
    
    # Parse command line arguments
    args = parse_arguments()
    
    # Set logging level based on verbosity
    if args.verbose:
        logger.setLevel(logging.INFO)
        logger.info("Verbose output enabled")
    
    if logger.level <= logging.INFO:
        logger.info("Starting Odoo Docker container update process")
    
    # Check if PyYAML is installed
    try:
        import yaml
    except ImportError:
        logger.error("PyYAML is not installed. Run 'pip install pyyaml' to install it.")
        return 1
    
    # Load configuration
    config = load_config(args.config)
    if not config:
        logger.error(f"Failed to load configuration from {args.config}. Exiting.")
        return 1
    
    # Optimize DNS configuration for containers (ALWAYS run, regardless of verbose mode)
    config_modified = False
    print("Checking DNS optimization for Docker containers...")
    
    for container in config['containers']:
        if not container.get('active', True):
            continue
        
        container_name = container.get('container_name', 'unknown')
        current_volume = container.get('volume', '')
        
        # Optimize DNS configuration
        optimized_volume, was_modified = optimize_dns_for_container(current_volume)
        
        if was_modified:
            container['volume'] = optimized_volume
            config_modified = True
            # Always show DNS optimization
            print(f"DNS optimization applied to container: {container_name}")
        else:
            print(f"DNS configuration already optimal for container: {container_name}")
    
    # Save updated configuration if modifications were made
    if config_modified:
        if save_updated_config(config, args.config):
            # Always show this message
            print("Configuration updated with DNS optimizations")
        else:
            print("ERROR: Failed to save DNS optimizations to configuration file")
            return 1
    else:
        print("No DNS optimization needed - configuration is already optimal")
    
    # Process active containers
    success_count = 0
    failure_count = 0
    validate_count = 0
    total_info_count = 0
    total_warning_count = 0
    total_error_count = 0
    
    for container in config['containers']:
        # Skip inactive containers
        if not container.get('active', True):
            logger.info(f"Skipping inactive container: {container.get('container_name', 'unknown')}")
            continue
        
        # Skip if specific container was specified and this isn't it
        if args.specific_container and args.specific_container != container.get('container_name'):
            logger.info(f"Skipping container {container.get('container_name')} (not specified in --specific-container)")
            continue
        
        # Validate container configuration
        if validate_container_config(container):
            validate_count += 1
            logger.info(f"Container configuration is valid: {container.get('container_name')}")
        else:
            logger.error(f"Invalid configuration for container: {container.get('container_name', 'unknown')}")
            failure_count += 1
            total_error_count += 1
            continue
        
        # If only validating or DNS optimizing, skip processing
        if args.validate or args.dns_optimize:
            continue
        
        # Process container
        try:
            result = process_container(container)
            if isinstance(result, tuple):
                success, info_count, warning_count, error_count = result
                total_info_count += info_count
                total_warning_count += warning_count
                total_error_count += error_count
            else:
                success = result
            
            if success:
                success_count += 1
            else:
                failure_count += 1
        except Exception as e:
            logger.error(f"Exception processing container {container.get('container_name', 'unknown')}: {e}")
            failure_count += 1
            total_error_count += 1
    
    # Summary - use a custom function to print without WARNING level
    def print_summary(message):
        # Print in a way that mimics logger but without the WARNING prefix
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        print(f"{timestamp} - INFO - {message}")
    
    print_summary(f"{'='*80}")
    execution_time = time.time() - start_time
    minutes, seconds = divmod(execution_time, 60)
    if args.validate:
        print_summary(f"Configuration validation completed in {int(minutes)}m {int(seconds)}s.")
        print_summary(f"Valid configurations: {validate_count}")
        if failure_count > 0:
            print_summary(f"Invalid configurations: {failure_count}")
    elif args.dns_optimize:
        print_summary(f"DNS optimization completed in {int(minutes)}m {int(seconds)}s.")
        print_summary(f"Valid configurations: {validate_count}")
        if config_modified:
            print_summary("DNS optimization applied to configuration file")
        else:
            print_summary("DNS configuration was already optimal")
        if failure_count > 0:
            print_summary(f"Invalid configurations: {failure_count}")
    else:
        print_summary(f"Update process completed in {int(minutes)}m {int(seconds)}s.")
        print_summary(f"Successful updates: {success_count}")
        if failure_count > 0:
            print_summary(f"Failed updates: {failure_count}")
        # Add the message counts to the summary
        print_summary(f"Log statistics: {total_info_count} INFO, {total_warning_count} WARNING, {total_error_count} ERROR messages")
        
        # Final Docker system cleanup after all containers are processed
        if not args.validate:
            print_summary("Performing final Docker system cleanup...")
            info, warn, err = clean_docker_system()
            print_summary(f"Final cleanup completed with {warn} warnings and {err} errors")
    
    print_summary(f"{'='*80}")
    
    # Ensure all output is flushed
    sys.stdout.flush()
    sys.stderr.flush()
    
    # Exit with appropriate code
    return 0 if failure_count == 0 else 1

if __name__ == "__main__":
    try:
        exit_code = main()
        if logger.level <= logging.INFO:
            logger.info("Script execution completed. Exiting now.")
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.warning("Script interrupted by user. Exiting now.")
        sys.exit(130)  # Standard exit code for SIGINT
    except Exception as e:
        logger.error(f"Unhandled exception: {str(e)}")
        sys.exit(1)
