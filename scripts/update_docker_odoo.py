#!/usr/bin/python3
# -*- coding: utf-8 -*-
# This script performs an update of an Odoo database in a Docker container
# Version 5.9.0
# Date 06.08.2026
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
import re
import sys
import time
import yaml
import atexit
import shutil
import platform
import logging
import argparse
import subprocess
from os.path import expanduser, isdir, isfile, join
import threading

# On a terminal the date repeats on every line of a run that takes minutes,
# and this script's own messages should line up with the indented child
# output. A log file keeps the full timestamp - there the date matters.
IS_TTY = sys.stdout.isatty()

# A terminal left in raw mode by a child stops translating '\n' into CR+LF:
# every following line then starts in the column where the previous one ended,
# producing a staircase. 'docker run -t' does exactly this to the client's
# terminal, which is why the batch runs below no longer ask for a TTY. Leading
# every write with a carriage return repairs the damage should it happen
# anyway, and is a no-op in normal cooked mode. Never in a log file, where it
# would only leave stray ^M bytes.
CR = "\r" if IS_TTY else ""

# Set up logging - Default to WARNING level
logging.basicConfig(
    level=logging.WARNING,  # Default to WARNING level now
    format=(f'{CR}  %(asctime)s %(levelname)-5s %(message)s' if IS_TTY
            else '%(asctime)s - %(levelname)s - %(message)s'),
    datefmt='%H:%M:%S' if IS_TTY else None,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

##############################################################################
# Output formatting
#
# Two writers share stdout: this script's own messages (via logging) and the
# verbatim output of child processes (docker build, odoo update, helper
# scripts). Child lines already carry their own timestamp and log level, so
# they are passed through unchanged instead of being wrapped in a second
# '<date> - INFO - ' prefix. Progress spinners only run on a TTY - under cron
# their carriage returns would end up in the log file.
##############################################################################

# Kept in sync with the header comment above. Printed at the start of every run
# so a pasted log says which version produced it — the single most common
# question when a report comes back from a server.
SCRIPT_VERSION = "5.9.0"
SCRIPT_DATE = "06.08.2026"

# Column at which the dots of a compact step line end
STEP_WIDTH = 44

# Width of a section header line
SECTION_WIDTH = 64

# How many errors are repeated as a recap when a command fails
ERROR_RECAP_LIMIT = 10

# Every warning and error of the whole run, collected so the closing block can
# list them in one place. Without it the only way to find out whether a run of
# a dozen containers had problems is scrolling back through twenty minutes of
# build output — and with filtered output the lines are printed live but still
# sit between the step lines of every other container.
RUN_ISSUES = []                      # list of (context, level, text)

# Named so a collected line can say where it came from. Set by print_section
# (container) and run_step/run_stream (the individual step).
CURRENT_SECTION = ""
CURRENT_STEP = ""

# Cap for the closing block: a broken module update can emit hundreds of
# identical warnings, and a recap that scrolls is no better than no recap.
ISSUE_RECAP_LIMIT = 40

# Leading "HH:MM:SS <pid> LEVEL " columns of an already formatted line, stripped
# before comparing two messages for the recap — otherwise the same warning
# counts as new on every repetition purely because of its timestamp.
ISSUE_KEY_RE = re.compile(r'^\d{2}:\d{2}:\d{2}\s+\d+\s+\S+\s+|^\S+\s+')


# Minimum number of lines that must have scrolled past the last error before
# repeating it is worth anything - otherwise the recap sits directly below the
# line it repeats
ERROR_RECAP_DISTANCE = 20


##############################################################################
# Run log
#
# The console output is deliberately lossy: without -v every INFO line of a
# twenty-minute update is dropped, and what is left scrolls away. That is the
# right trade-off while watching a run and the wrong one afterwards, when the
# question is what a cron job did at three in the morning. The file written
# here keeps the whole run - steps, timings and every child line regardless of
# level - next to the instance it belongs to.
#
# It is a convenience, never a precondition: a folder that cannot be written to
# costs the log, not the update. Every function here swallows its own I/O
# errors for that reason.
##############################################################################

# Every log file written this run, listed once at exit.
RUN_LOG_FILES = []

_RUN_LOG_HANDLE = None

# The build folder is the build context, so a year of daily logs would be sent
# to the daemon on every build. The repository's .dockerignore has excluded
# them since the filestore backups made the context huge - but that file is the
# customer's and is distributed by nothing, so an installation may have none.
LOG_IGNORE_PATTERN = "*.log"


def ensure_log_ignored(build_dir):
    """Keep the run logs out of the build context."""
    path = join(build_dir, ".dockerignore")
    try:
        existing = ""
        if isfile(path):
            with open(path, encoding="utf8") as handle:
                existing = handle.read()
            # A commented-out pattern excludes nothing, so compare the whole
            # stripped line rather than searching for the text.
            if any(line.strip() == LOG_IGNORE_PATTERN
                   for line in existing.splitlines()):
                return
        with open(path, "a", encoding="utf8") as handle:
            if not existing:
                handle.write("# Run logs written by update_docker_odoo.py. This folder is the\n"
                             "# build context - without this line they would be sent to the\n"
                             "# daemon on every build.\n")
            elif not existing.endswith("\n"):
                handle.write("\n")
            handle.write(LOG_IGNORE_PATTERN + "\n")
    except OSError as exc:
        logger.warning(f"Could not update {path}: {exc}")


def open_run_log(build_dir, container_name, header_lines=()):
    """Start the run log for one container in its build folder.

    Returns:
        str: Path of the log file, or None when it could not be created.
    """
    global _RUN_LOG_HANDLE
    close_run_log()
    if not isdir(build_dir):
        logger.warning(f"No run log: build folder not found: {build_dir}")
        return None
    path = join(build_dir, time.strftime("update_%Y%m%d_%H%M%S.log"))
    try:
        _RUN_LOG_HANDLE = open(path, "w", encoding="utf8")
    except OSError as exc:
        logger.warning(f"No run log: {exc}")
        return None
    ensure_log_ignored(build_dir)
    run_log_write(f"update_docker_odoo.py {SCRIPT_VERSION} ({SCRIPT_DATE})")
    run_log_write(f"container: {container_name}")
    run_log_write(f"started:   {time.strftime('%d.%m.%Y %H:%M:%S')}")
    for line in header_lines:
        run_log_write(line)
    RUN_LOG_FILES.append(path)
    return path


def run_log_write(text):
    """Append one line to the run log. A no-op when no log is open.

    Flushes on every line: a run killed mid-build must still leave behind
    everything up to the moment it died - that is when the file matters most.
    """
    if _RUN_LOG_HANDLE is None:
        return
    try:
        # The carriage returns that repair a terminal left in raw mode would
        # only be stray ^M bytes here.
        _RUN_LOG_HANDLE.write(text.replace("\r", "") + "\n")
        _RUN_LOG_HANDLE.flush()
    except (OSError, ValueError):
        pass


def close_run_log():
    """Finish the current run log, if any."""
    global _RUN_LOG_HANDLE
    if _RUN_LOG_HANDLE is None:
        return
    try:
        _RUN_LOG_HANDLE.write(
            f"\nfinished:  {time.strftime('%d.%m.%Y %H:%M:%S')}\n")
        _RUN_LOG_HANDLE.close()
    except (OSError, ValueError):
        pass
    _RUN_LOG_HANDLE = None


def print_run_log_files():
    """Name the log files this run produced.

    Registered with atexit rather than printed from the summary block, so an
    interrupted or failed run - the case where the file is worth the most -
    still says where to look.
    """
    close_run_log()
    if not RUN_LOG_FILES:
        return
    print(f"\n{CR}run log{'s' if len(RUN_LOG_FILES) > 1 else ''}:")
    for path in RUN_LOG_FILES:
        print(f"{CR}  {path}")
    sys.stdout.flush()


atexit.register(print_run_log_files)


def note_issue(level, text):
    """Record a warning or error for the closing block."""
    context = " · ".join(part for part in (CURRENT_SECTION, CURRENT_STEP) if part)
    RUN_ISSUES.append((context, level, text))

# Odoo log line: "2026-08-03 17:25:26,102 12 WARNING ? odoo.tools.config: ..."
ODOO_LOG_RE = re.compile(
    r'^(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2}),\d+\s+'
    r'(?P<pid>\d+)\s+(?P<level>[A-Z]+)\s+(?P<db>\S+)\s+(?P<rest>.*)$'
)

# Log line of a nested python helper: "2026-08-03 19:25:26,103 - INFO - ..."
PY_LOG_RE = re.compile(
    r'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2},\d+\s+-\s+(?P<level>[A-Z]+)\s+-\s+'
    r'(?P<rest>.*)$'
)

# Shortened level names so the passthrough columns stay aligned
LEVEL_ALIASES = {'WARNING': 'WARN', 'CRITICAL': 'CRIT'}

ERROR_LEVELS = {'ERROR', 'CRITICAL', 'FATAL'}
WARNING_LEVELS = {'WARNING', 'WARN'}


def _level_bucket(level):
    """Map a raw log level name onto ERROR / WARNING / INFO."""
    level = level.upper()
    if level in ERROR_LEVELS:
        return 'ERROR'
    if level in WARNING_LEVELS:
        return 'WARNING'
    return 'INFO'


def classify_line(line):
    """Determine the log level of a child-process line and format it for display.

    The level is taken from the line's actual log-level field (Odoo format or
    the '<ts> - LEVEL - msg' python format) instead of scanning the whole line
    for substrings like ' ERROR '. A module name, a file path or a translated
    string containing that word must not turn an INFO line into an error.

    Only lines without any recognisable log format fall back to a conservative
    content check, and only an explicit 'error:'/'warning:' marker counts.

    Args:
        line: Raw line as read from the child process

    Returns:
        tuple: (level, display) - level is 'ERROR', 'WARNING' or 'INFO';
               display is the text to print (redundant date dropped, this
               script's own timestamp never added).
    """
    stripped = line.rstrip()

    match = ODOO_LOG_RE.match(stripped)
    if match:
        level = match.group('level')
        display = (f"{match.group('time')} {match.group('pid'):>5} "
                   f"{LEVEL_ALIASES.get(level, level):<5} "
                   f"{match.group('db')} {match.group('rest')}")
        return _level_bucket(level), display

    match = PY_LOG_RE.match(stripped)
    if match:
        level = match.group('level')
        display = f"{LEVEL_ALIASES.get(level, level):<5} {match.group('rest')}"
        return _level_bucket(level), display

    lower = stripped.lower()
    if lower.startswith('error') or lower.startswith('exception') or 'error: ' in lower:
        return 'ERROR', stripped
    if lower.startswith('warning') or 'warning: ' in lower:
        return 'WARNING', stripped
    return 'INFO', stripped


def format_duration(seconds):
    """Format a duration as '42s' or '3m12s'."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m{seconds % 60:02d}s"


def print_section(title, rune='─'):
    """Print a section header.

    Args:
        title: Section name, e.g. the container name
        rune: Line character - the closing summary uses a different one so it
              is distinguishable from a container section at a glance
    """
    global CURRENT_SECTION
    CURRENT_SECTION = title
    prefix = f"{rune * 2} {title} "
    padding = max(3, SECTION_WIDTH - len(prefix))
    print(f"\n{CR}{prefix}{rune * padding}")
    run_log_write(f"\n{prefix}{rune * padding}")
    sys.stdout.flush()


def print_step(label, status, duration=None):
    """Print a compact one-line step result: 'label ......... ok (94s)'."""
    dots = '.' * max(3, STEP_WIDTH - len(label))
    suffix = f" ({format_duration(duration)})" if duration is not None else ""
    print(f"{CR}  {label} {dots} {status}{suffix}")
    run_log_write(f"  {label} {dots} {status}{suffix}")
    sys.stdout.flush()


def print_issue_recap():
    """List every warning and error of the run in one closing block.

    Runs regardless of -v: without it, finding out whether a run had problems
    means scrolling back through the whole log. Identical lines from the same
    step are collapsed with a count — a single broken module update can emit
    the same warning hundreds of times, and a recap that scrolls is no better
    than none.
    """
    if not RUN_ISSUES:
        return

    # Collapse repeats of the same message. The key drops the leading
    # timestamp/pid/level columns: the same warning emitted a hundred times
    # differs only in its timestamp, and keeping them apart would defeat the
    # whole point of the block. The first occurrence is what gets shown, so
    # its timestamp still says when the problem started.
    collapsed = {}                       # key -> [context, level, text, count]
    for context, level, text in RUN_ISSUES:
        key = (context, level, ISSUE_KEY_RE.sub('', text))
        if key in collapsed:
            collapsed[key][3] += 1
        else:
            collapsed[key] = [context, level, text, 1]

    errors = [entry for entry in collapsed.values() if entry[1] == 'ERROR']
    warnings = [entry for entry in collapsed.values() if entry[1] == 'WARNING']

    total_errors = sum(entry[3] for entry in errors)
    total_warnings = sum(entry[3] for entry in warnings)
    print_section(f"warnings & errors: {total_errors} error(s), "
                  f"{total_warnings} warning(s)", rune='═')

    # One heading per step, errors before warnings within it. Listing all
    # errors first instead would repeat the heading for every step that has
    # both.
    context_order = {}
    for entry in collapsed.values():
        context_order.setdefault(entry[0], len(context_order))
    entries = sorted(collapsed.values(),
                     key=lambda e: (context_order[e[0]], e[1] != 'ERROR'))

    shown = 0
    last_context = None
    for context, level, text, count in entries:
        if shown >= ISSUE_RECAP_LIMIT:
            remaining = len(entries) - shown
            print(f"{CR}  ... and {remaining} more (run with -v for the full log)")
            break
        if context != last_context:
            print(f"{CR}  {context or 'run'}:")
            last_context = context
        suffix = f"  ({count}x)" if count > 1 else ""
        print(f"{CR}    {LEVEL_ALIASES.get(level, level):<5} {text}{suffix}")
        shown += 1
    sys.stdout.flush()


def print_section_summary(label, warnings, errors, duration):
    """Print the closing line of a container section."""
    print(f"{CR}  → {label}: {warnings} warning(s), {errors} error(s), "
          f"{format_duration(duration)}")
    sys.stdout.flush()

# Default configuration
home_path = expanduser("~")
# First check if config file exists in current directory, then fall back to home directory
current_dir_config = "docker2update.yaml"
home_config = join(home_path, "docker2update.yaml")
default_config_file = current_dir_config if isfile(current_dir_config) else home_config
git_path = "https://rm.ownerp.io/staff/v"
build_script = "-muster/build_odoo.py"
check_script = "-muster/check_dockerimage_odoo.py"

# Proxy support: recognised keys for the optional YAML proxy blocks and the
# marker file written by getScripts.py first-run setup (KEY=VALUE lines).
PROXY_KEYS = ('http_proxy', 'https_proxy', 'no_proxy')
PROXY_MARKER_FILE = join(home_path, '.getscripts_proxy')

# Local source for build_odoo.py / check_dockerimage_odoo.py / bin files:
# the myodoo-docker repository clone that getScripts.py keeps up to date.
# Overridable via 'defaults: dockerfiles_source:' in docker2update.yaml.
DEFAULT_DOCKERFILES_SOURCE = join(home_path, 'myodoo-docker', 'Dockerfiles')

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
      db_password_via_env: true                   # Pass password via PGPASSWORD env, not argv
                                                  # (hidden from ps; needs image >= 11.06.2026)
      db_host: "db-host"                          # Database hostname/IP
      volume: "--network net -v /path:/data"      # Docker volume config (DNS auto-optimized)
      odoo_version: "16"                          # Odoo version for scripts
      translate: "Y"                              # Load translations? Y/N
      proxy:                                      # Optional: per-container proxy override
        http_proxy: "http://proxy.local:3128"
      pre_build_files:                            # Optional: copied into dockerfile_path
        - source: "/opt/customer/eq_custom"       #   file OR directory
          target: "custom-addons/"                #   relative to dockerfile_path (default ".")

  defaults:                                       # Optional global section
    proxy:                                        # Used for wget downloads and docker build
      http_proxy: "http://proxy.local:3128"       #   (env + --build-arg). Fallback order without
      https_proxy: "http://proxy.local:3128"      #   this block: container proxy > defaults.proxy >
      no_proxy: "localhost,127.0.0.1"             #   environment vars > ~/.getscripts_proxy
    dockerfiles_source: "~/myodoo-docker/Dockerfiles"  # Local source for build_odoo.py /
                                                  #   check_dockerimage_odoo.py / bin files
                                                  #   (default shown; kept current via 'ups')

Note: DNS optimization is automatically applied to containers if host DNS is not optimal.
      This helps resolve DNS issues between different cloud providers (e.g., Hetzner <-> DigitalOcean).
      Build scripts are synced from the local myodoo-docker repository (newer
      version header wins); the release-manager wget only runs as fallback.
      Base image pulls are done by the Docker daemon itself - configure its proxy
      via getScripts.py --proxy-check (systemd drop-in), not in this file.
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

def run_command(command, show_output=True, filter_output=False, show_progress=False,
                progress_msg=None, timeout=None, env=None, output_indent="    "):
    """Run a shell command with proper error handling and output filtering.

    Child output is passed through verbatim (only reformatted by
    classify_line) instead of being re-wrapped in this script's log format,
    so every line carries exactly one timestamp - its own.

    Args:
        env: Optional dict of extra environment variables (merged over os.environ),
             e.g. proxy settings for commands that need internet access.
        output_indent: Prefix for passed-through child lines, so they sit
             visually underneath the step that produced them.
    """
    try:
        # Debug only - under -v this echoed the command in front of every
        # step, right above the step line that already names it
        if logger.getEffectiveLevel() <= logging.DEBUG:
            logger.debug(f"Running command: {command}")

        # Set up process with pipes
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1,  # Line buffered
            env={**os.environ, **env} if env else None
        )
        
        # Collected for the failure recap (warnings are printed live only)
        all_errors = []
        # Line bookkeeping, so the recap can tell whether the last error is
        # still on screen or has scrolled away in a long build log
        emitted_lines = 0
        last_error_line = None
        warnings_count = 0
        errors_count = 0
        info_count = 0  # Counter for INFO messages
        
        # Start progress indicator if requested
        progress_thread = None
        stop_progress = False
        progress_lock = threading.Lock()
        spinner_running = False

        def emit(text):
            """Print a child-process line verbatim, indented under its step.

            Deliberately bypasses the logger: the line already carries the
            child's own timestamp and level, and a second '<date> - INFO - '
            prefix only makes the output harder to read.
            """
            nonlocal emitted_lines, spinner_running, stop_progress
            with progress_lock:
                if spinner_running and filter_output:
                    # Filtered output produces a line only for a warning or an
                    # error, so here the output is NOT a progress indicator —
                    # a single warning must not leave the remaining twenty
                    # minutes of a build without any sign of life. Clear the
                    # spinner frame and let it keep drawing afterwards; both
                    # writers hold this lock, so they cannot interleave.
                    sys.stdout.write("\r\033[K")
                elif spinner_running:
                    # Once the child produces output, that output *is* the
                    # progress indicator. Running both means every emitted
                    # line races a half-drawn spinner frame for the cursor.
                    stop_progress = True
                    spinner_running = False
                    sys.stdout.write("\r\033[K")
                sys.stdout.write(f"{CR}{output_indent}{text}\n")
                sys.stdout.flush()
                emitted_lines += 1
        
        # A spinner only makes sense on a terminal - under cron its carriage
        # returns would be written into the log file.
        if show_progress and IS_TTY:
            spinner_running = True

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
                # Clear the line when done - unless emit() already took over,
                # in which case it has erased the last frame itself
                with progress_lock:
                    if spinner_running:
                        sys.stdout.write("\r\033[K")
                        sys.stdout.flush()
            
            progress_thread = threading.Thread(target=show_spinner)
            progress_thread.daemon = True
            progress_thread.start()
        
        # Read output line by line
        stdout_lines = []
        stderr_lines = []
        
        def read_pipe(pipe, line_list):
            """Read one child pipe to EOF, classifying and printing as we go.

            Plain blocking reads. The timeout is enforced by the caller's
            process.wait(timeout=...), which kills the process and thereby
            closes this pipe. The previous select()-based loop gave up as
            soon as process.poll() reported an exit - lines still sitting in
            the text buffer at that moment were silently dropped.
            """
            nonlocal warnings_count, errors_count, info_count, last_error_line
            for line in iter(pipe.readline, ''):
                line_list.append(line)
                stripped_line = line.strip()
                
                if not stripped_line:
                    continue
                
                # Level detection and display formatting live in classify_line();
                # see there for why substring matching on the raw line is wrong.
                level, display = classify_line(line)

                # Before any filtering: the console drops INFO without -v, the
                # file keeps everything. Reconstructing a build from a log that
                # was filtered the same way as the screen is impossible.
                run_log_write(f"    {display}")

                if level == 'ERROR':
                    errors_count += 1
                    all_errors.append(display)
                    note_issue(level, display)
                elif level == 'WARNING':
                    warnings_count += 1
                    note_issue(level, display)
                else:
                    info_count += 1
                    # INFO is noise unless the caller asked to see it
                    if filter_output or not (show_output or logger.getEffectiveLevel() <= logging.INFO):
                        continue

                # Errors and warnings always appear - exactly once, here
                emit(display)
                if level == 'ERROR':
                    last_error_line = emitted_lines
        
        # Start threads to read stdout and stderr
        stdout_thread = threading.Thread(
            target=read_pipe,
            args=(process.stdout, stdout_lines)
        )
        stderr_thread = threading.Thread(
            target=read_pipe,
            args=(process.stderr, stderr_lines)
        )

        stdout_thread.daemon = True
        stderr_thread.daemon = True
        stdout_thread.start()
        stderr_thread.start()

        # Wait for process to complete. The readers hit EOF when the process
        # closes its pipes; give them room to drain rather than cutting them
        # off mid-buffer.
        try:
            exit_code = process.wait(timeout=timeout)
            stdout_thread.join(5)
            stderr_thread.join(5)
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
        spinner_running = False

        stdout_output = "".join(stdout_lines)
        stderr_output = "".join(stderr_lines)
        
        # Errors and warnings have already been printed live, so there is no
        # blanket repeat here. Only a failure gets a short recap, so the cause
        # sits right above the failure message instead of scrolled far up in a
        # 20-minute build log.
        if exit_code != 0:
            logger.error(f"Command failed with exit code {exit_code}")
            scrolled_away = (last_error_line is not None and
                             emitted_lines - last_error_line >= ERROR_RECAP_DISTANCE)
            if all_errors and scrolled_away:
                recap = all_errors[-ERROR_RECAP_LIMIT:]
                omitted = len(all_errors) - len(recap)
                header = f"--- last {len(recap)} error(s)"
                if omitted:
                    header += f", {omitted} earlier one(s) above"
                emit(header + " ---")
                for msg in recap:
                    emit(msg)
            return False, stderr_output, info_count, warnings_count, errors_count
        
        # No success message here - the step line already reports 'ok'. Under
        # -v this used to print 'Command completed successfully with no
        # warnings or errors' in front of every single step.
        return True, stdout_output, info_count, warnings_count, errors_count
    except Exception as e:
        stop_progress = True
        if 'progress_thread' in locals() and progress_thread:
            progress_thread.join(1)
        logger.error(f"Exception running command: {e}")
        return False, str(e), 0, 0, 1  # Return counts with the error

def run_step(label, command, **kwargs):
    """Run a short command and report it as one compact line.

    Output is suppressed unless it contains warnings or errors - for a
    'docker stop' the interesting information is 'did it work and how long
    did it take', not its chatter.

    Returns:
        tuple: Same as run_command (success, output, info, warnings, errors)
    """
    global CURRENT_STEP
    started = time.time()
    kwargs.setdefault('show_output', False)
    kwargs.setdefault('filter_output', True)
    CURRENT_STEP = label
    try:
        result = run_command(command, **kwargs)
    finally:
        CURRENT_STEP = ""
    print_step(label, "ok" if result[0] else "FAILED", time.time() - started)
    return result


def run_stream(label, command, **kwargs):
    """Run a long command whose output is streamed verbatim under a heading.

    Used for docker build and the Odoo update runs, where watching progress
    is the whole point.

    Returns:
        tuple: Same as run_command (success, output, info, warnings, errors)
    """
    global CURRENT_STEP
    started = time.time()
    print(f"{CR}  {label}")
    run_log_write(f"  {label}")
    sys.stdout.flush()
    CURRENT_STEP = label
    try:
        result = run_command(command, **kwargs)
    finally:
        CURRENT_STEP = ""
    print_step(label, "ok" if result[0] else "FAILED", time.time() - started)
    return result


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

def resolve_proxy_settings(config, container):
    """Resolve proxy settings for a container.

    Precedence: per-container 'proxy' block > global 'defaults.proxy' block >
    environment variables > ~/.getscripts_proxy marker file (written by the
    getScripts.py first-run setup). Returns an empty dict when no proxy is
    configured anywhere, so callers behave exactly as before.
    """
    for source_name, block in (
        ('container config', container.get('proxy')),
        ('defaults config', (config.get('defaults') or {}).get('proxy')),
    ):
        if isinstance(block, dict):
            unknown_keys = [key for key in block if key not in PROXY_KEYS]
            if unknown_keys:
                logger.warning(f"Ignoring unknown proxy keys {unknown_keys} in {source_name}")
            proxy = {key: str(block[key]) for key in PROXY_KEYS if block.get(key)}
            if proxy:
                logger.info(f"Using proxy settings from {source_name}")
                return proxy

    proxy = {}
    for key in PROXY_KEYS:
        value = os.environ.get(key) or os.environ.get(key.upper())
        if value:
            proxy[key] = value
    if proxy:
        logger.info("Using proxy settings from environment variables")
        return proxy

    if isfile(PROXY_MARKER_FILE):
        try:
            with open(PROXY_MARKER_FILE, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    key, _, value = line.partition('=')
                    if key.strip().lower() in PROXY_KEYS and value.strip():
                        proxy[key.strip().lower()] = value.strip()
        except Exception as e:
            logger.warning(f"Failed to read proxy marker file {PROXY_MARKER_FILE}: {e}")
        if proxy:
            logger.info(f"Using proxy settings from {PROXY_MARKER_FILE}")
    return proxy

def build_proxy_env(proxy_settings):
    """Build extra environment variables (lower- and uppercase) for subprocesses
    like wget, or None when no proxy is configured."""
    if not proxy_settings:
        return None
    env = {}
    for key, value in proxy_settings.items():
        env[key] = value
        env[key.upper()] = value
    return env

def build_proxy_build_args(proxy_settings):
    """Build 'docker build' --build-arg options (trailing space included) so RUN
    steps inside the image build reach the internet through the proxy.
    Returns an empty string when no proxy is configured."""
    if not proxy_settings:
        return ""
    args = []
    for key, value in proxy_settings.items():
        args.append(f'--build-arg {key}="{value}"')
        args.append(f'--build-arg {key.upper()}="{value}"')
    return " ".join(args) + " "

def copy_pre_build_files(container, path):
    """Copy customer-specific files/directories into the build folder before docker build.

    Driven by the optional per-container 'pre_build_files' list of
    {source, target} entries; 'target' is relative to dockerfile_path
    (default "."). A missing source is a hard error: building without the
    customer's custom modules would produce a broken image.

    Returns:
        tuple: (success, info_count, warning_count, error_count)
    """
    entries = container.get('pre_build_files') or []
    info_count = 0
    base = os.path.realpath(path)
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get('source'):
            logger.error(f"Invalid pre_build_files entry (needs 'source'): {entry}")
            return False, info_count, 0, 1
        source = expand_path(str(entry['source']))
        target_rel = str(entry.get('target') or '.')
        target_dir = os.path.realpath(join(base, target_rel))
        if target_dir != base and not target_dir.startswith(base + os.sep):
            logger.error(f"pre_build_files target escapes the build folder: {target_rel}")
            return False, info_count, 0, 1
        if not os.path.exists(source):
            logger.error(f"pre_build_files source not found: {source}")
            return False, info_count, 0, 1
        try:
            os.makedirs(target_dir, exist_ok=True)
            destination = join(target_dir, os.path.basename(source.rstrip('/')))
            if isdir(source):
                shutil.copytree(source, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(source, destination)
            logger.info(f"Copied pre-build file: {source} -> {destination}")
            info_count += 1
        except Exception as e:
            logger.error(f"Failed to copy pre-build file {source}: {e}")
            return False, info_count, 0, 1
    return True, info_count, 0, 0

def get_script_version(file_path):
    """Parse '# Version X.Y.Z' from the first lines of a script file.

    Returns:
        tuple: Version numbers as int tuple, or None if not found/readable.
    """
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            for _ in range(10):
                line = f.readline()
                if not line:
                    break
                match = re.match(r'^#\s*Version\s+(\d+(?:\.\d+)*)\s*$', line.strip())
                if match:
                    return tuple(int(part) for part in match.group(1).split('.'))
    except Exception as e:
        logger.warning(f"Could not read version from {file_path}: {e}")
    return None

def sync_build_scripts(version, path, source_base):
    """Sync build_odoo.py, check_dockerimage_odoo.py and bin/ files from the
    local myodoo-docker repository into the build folder.

    A file is copied only when it is missing in the build folder or the
    repository copy has a NEWER '# Version X.Y.Z' header; files without a
    parsable header are copied when their content differs. Nothing is ever
    deleted from the build folder. The repository itself is kept up to date
    by getScripts.py ('ups'), not here.

    Args:
        version: Odoo version string (e.g. "18")
        path: Build folder of the container (dockerfile_path)
        source_base: Directory containing the v{version}-odoo folders

    Returns:
        tuple: (synced, info_count, warning_count, error_count) - synced is
               False when the source folder is unavailable and the caller
               should fall back to the legacy release-manager download.
    """
    source_dir = join(source_base, f"v{version}-odoo")
    if not isdir(source_dir):
        logger.warning(f"Local Dockerfiles source not found: {source_dir} - "
                       f"falling back to release-manager download")
        return False, 0, 1, 0

    sync_files = ['build_odoo.py', 'check_dockerimage_odoo.py']
    bin_dir = join(source_dir, 'bin')
    if isdir(bin_dir):
        for name in sorted(os.listdir(bin_dir)):
            if isfile(join(bin_dir, name)):
                sync_files.append(join('bin', name))

    info_count = 0
    warning_count = 0
    for rel_name in sync_files:
        source_file = join(source_dir, rel_name)
        target_file = join(path, rel_name)
        if not isfile(source_file):
            logger.warning(f"Missing in Dockerfiles source: {source_file}")
            warning_count += 1
            continue

        reason = None
        if not isfile(target_file):
            reason = "missing in build folder"
        else:
            source_version = get_script_version(source_file)
            target_version = get_script_version(target_file)
            if source_version and target_version:
                if source_version > target_version:
                    reason = ("version " +
                              ".".join(map(str, target_version)) + " -> " +
                              ".".join(map(str, source_version)))
            elif source_version and not target_version:
                reason = "no version header in build folder copy"
            else:
                # No comparable version headers: copy when content differs
                try:
                    with open(source_file, 'rb') as src, open(target_file, 'rb') as dst:
                        if src.read() != dst.read():
                            reason = "content differs"
                except Exception as e:
                    logger.warning(f"Could not compare {rel_name}: {e}")
                    warning_count += 1
                    continue
        if not reason:
            continue

        try:
            target_dir = os.path.dirname(target_file)
            if target_dir:
                os.makedirs(target_dir, exist_ok=True)
            # copy2 preserves the executable bit (bin/boot)
            shutil.copy2(source_file, target_file)
            logger.info(f"Synced {rel_name} from {source_dir} ({reason})")
            info_count += 1
        except Exception as e:
            logger.error(f"Failed to sync {rel_name}: {e}")
            return True, info_count, warning_count, 1

    if info_count == 0:
        logger.info("Build scripts are up to date (local Dockerfiles source)")
    return True, info_count, warning_count, 0

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

    # Validate optional pre_build_files block
    pre_build_files = container.get('pre_build_files')
    if pre_build_files is not None:
        if not isinstance(pre_build_files, list):
            logger.error("pre_build_files must be a list of {source, target} entries")
            return False
        for entry in pre_build_files:
            if not isinstance(entry, dict) or not entry.get('source'):
                logger.error(f"Invalid pre_build_files entry (needs 'source'): {entry}")
                return False
            if not os.path.exists(expand_path(str(entry['source']))):
                logger.warning(f"pre_build_files source does not exist (yet): {entry['source']}")

    # Validate optional proxy block
    proxy = container.get('proxy')
    if proxy is not None and not isinstance(proxy, dict):
        logger.error("proxy must be a mapping with http_proxy/https_proxy/no_proxy")
        return False

    return True

def clean_docker_system():
    """
    Run docker system prune -f to clean up the Docker system.
    Removes all stopped containers, networks not used by at least one container,
    all dangling images, and unused build cache.
    """
    started = time.time()
    success, output, info, warn, err = run_command(
        "docker system prune -f", show_output=False, filter_output=True)

    # The prune listing itself is noise; the reclaimed space is the one number
    # worth carrying into the step line.
    status = "ok" if success else "FAILED"
    reclaimed = re.search(r'Total reclaimed space:\s*(.+)', output or "")
    if success and reclaimed:
        status = f"ok, {reclaimed.group(1).strip()} reclaimed"
    print_step("docker system prune", status, time.time() - started)
    return info, warn, err

def process_container(container, proxy_settings=None, dockerfiles_source=None):
    """Process a single container update, with its run log closed on any exit.

    A thin wrapper around _process_container, which returns from a dozen
    different places - a try/finally around the call is the only way to close
    the log on all of them without touching every one.
    """
    try:
        return _process_container(container, proxy_settings, dockerfiles_source)
    finally:
        close_run_log()


def _process_container(container, proxy_settings=None, dockerfiles_source=None):
    """Process a single container update.

    Args:
        container: Container configuration dict
        proxy_settings: Optional resolved proxy dict (see resolve_proxy_settings)
        dockerfiles_source: Base directory with the v{version}-odoo script
            sources (default: DEFAULT_DOCKERFILES_SOURCE)
    """
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

    # Pass the DB password via environment (docker run -e PGPASSWORD) instead
    # of argv when enabled - argv is visible to every local user via ps.
    # Requires an image whose boot script whitelists PGPASSWORD across su
    # (myodoo images built from 11.06.2026 on). Default: secure env mode; set
    # db_password_via_env: false only for legacy images without PGPASSWORD
    # whitelist in bin/boot.
    password_via_env = bool(container.get('db_password_via_env', True))
    if password_via_env:
        os.environ['PGPASSWORD'] = db_password
        db_auth_args = f"--db_user={db_user} --db_host={db_host}"
        env_forward = "-e PGPASSWORD "
    else:
        db_auth_args = f"--db_user={db_user} --db_password={db_password} --db_host={db_host}"
        env_forward = ""
    volume = expand_path(container.get('volume', ""))  # Expand env vars in volume
    version = container['odoo_version']
    translation = container['translate']
    
    # Section header - one line of context, the rest stays behind -v
    container_started = time.time()
    update_label = ('Full update' if update_type == 'F'
                    else 'Module copy' if update_type == 'M'
                    else 'Neutralize and update')
    context_line = (f"  {update_label} · db {db_name} · ports {port}/{poll_port}"
                    + (f" · odoo {version}" if version else ""))
    # Opened before the header so the file holds the section from its first
    # line. The context that only -v puts on screen goes in unconditionally:
    # a log that does not say which image it built from which folder is half
    # a log.
    open_run_log(path, container_name,
                 header_lines=[f"image:     {image}", f"path:      {path}"]
                 + ([f"volume:    {volume}"] if volume else []))
    print_section(container_name)
    print(context_line)
    run_log_write(context_line)
    logger.info(f"Dockerfile path: {path}")
    logger.info(f"Docker image: {image}")
    if volume:
        logger.info(f"Volume: {volume}")
    
    # Change to Dockerfile directory - This is critical for docker build
    try:
        original_dir = os.getcwd()  # Remember original directory
        logger.info(f"Changing to directory: {path}")
        os.chdir(path)
    except Exception as e:
        logger.error(f"Failed to change to directory {path}: {e}")
        return False, total_info, total_warnings, total_errors

    # Copy customer-specific files into the build folder before anything else
    success, info, warn, err = copy_pre_build_files(container, path)
    total_info += info
    total_warnings += warn
    total_errors += err
    if not success:
        logger.error("Aborting container update: pre-build file copy failed")
        try:
            os.chdir(original_dir)
        except Exception:
            pass
        return False, total_info, total_warnings, total_errors

    # Proxy environment for commands that need internet access (wget, docker build)
    proxy_env = build_proxy_env(proxy_settings)
    if proxy_env:
        logger.info("Proxy settings active for downloads and docker build")

    # Backup filestore if no volume is specified
    if not volume:
        # Under a fixed folder name so .dockerignore can exclude it. Previously
        # this landed in the build folder root as <db_name>/, which is not
        # statically nameable — so both this copy and its .bak rotation were
        # shipped to the Docker daemon as build context on every build.
        filestore_root = join(path, "filestore-backup")
        filestore_path = join(filestore_root, db_name)
        logger.info(f"Backing up filestore to {filestore_path}")

        # Create directory for filestore backup
        success, _, info, warn, err = run_command(f"mkdir -p {filestore_root}")
        total_info += info
        total_warnings += warn
        total_errors += err
        if not success:
            logger.error("Failed to create directory for filestore backup")
            return False, total_info, total_warnings, total_errors

        # Copy filestore from container
        success, _, info, warn, err = run_command(f"docker cp {container_name}:/opt/odoo/data/filestore/{db_name} {filestore_root}")
        total_info += info
        total_warnings += warn
        total_errors += err
        if not success:
            logger.warning("Failed to copy filestore from container. This might be normal for a new setup.")
        else:
            logger.info("Filestore saved successfully")
    
    # Get new version of build scripts: prefer syncing from the local
    # myodoo-docker repository (kept current via 'ups'); the legacy wget from
    # the release manager only runs when no local source folder is available.
    if version:
        synced, info, warn, err = sync_build_scripts(
            version, path, dockerfiles_source or DEFAULT_DOCKERFILES_SOURCE)
        total_info += info
        total_warnings += warn
        total_errors += err

        if not synced:
            logger.info("Downloading build scripts...")
            # Use consistent script names
            download_build_script = f"{git_path}{version}{build_script}"
            download_check_script = f"{git_path}{version}{check_script}"

            logger.info(f"Downloading build script from: {download_build_script}")
            success, _, info, warn, err = run_command(f"wget -q -N --timeout=30 --tries=3 {download_build_script}", timeout=60, env=proxy_env)
            total_info += info
            total_warnings += warn
            total_errors += err
            if not success:
                logger.warning(f"Failed to download build script from {download_build_script} - continuing anyway")

            logger.info(f"Downloading check script from: {download_check_script}")
            success, _, info, warn, err = run_command(f"wget -q -N --timeout=30 --tries=3 {download_check_script}", timeout=60, env=proxy_env)
            total_info += info
            total_warnings += warn
            total_errors += err
            if not success:
                logger.warning(f"Failed to download check script from {download_check_script} - continuing anyway")
    

    # Run release manager to get latest Docker image if access file exists
    # Use the correct script name based on what we have in the directory
    check_script_name = "check_dockerimage_odoo.py"
    if not isfile(check_script_name):
        check_script_name = "check_dockerimage_myodoo.py"  # Try alternative name

    access_file_name = "release.txt"
    if not isfile(access_file_name):
        access_file_name = "access_myodoo.txt"  # Try alternative name
        
    if isfile(check_script_name) and isfile(access_file_name):
        # Forward proxy env: the check script downloads the release CSV via wget
        success, _, info, warn, err = run_step(
            "release manager", f"python3 {check_script_name}", env=proxy_env)
        total_info += info
        total_warnings += warn
        total_errors += err
        if not success:
            logger.warning("Failed to run release manager check script - continuing anyway")
    else:
        logger.warning(f"Skipping release manager check - files not found: {check_script_name} or {access_file_name}")
        total_warnings += 1

    # Pre-fetch the release archives on the host so the build only downloads
    # what actually changed. Never fatal: whatever is missing from the cache,
    # build_odoo.py fetches itself, exactly as it did before the cache existed.
    #
    # The same step brings the build folder's Dockerfile up to date against the
    # repository copy. sync_build_scripts() above deliberately never overwrites
    # that file - it is the customer's, and may carry its own COPY and RUN
    # steps - so image directives added to the repository later (HEALTHCHECK)
    # would otherwise never reach an existing installation. Only entirely
    # absent directives are inserted; anything else is reported.
    cache_script = join(home_path, "odoo_build_cache.py")
    if isfile(cache_script):
        reference_arg = ""
        if version:
            reference = join(dockerfiles_source or DEFAULT_DOCKERFILES_SOURCE,
                             f"v{version}-odoo", "Dockerfile")
            if isfile(reference):
                reference_arg = f' --reference "{reference}"'
        _, _, info, warn, err = run_step(
            "cache release archives",
            f'python3 {cache_script} sync "{path}"{reference_arg}', env=proxy_env)
        total_info += info
        total_warnings += warn
        total_errors += err
    else:
        logger.debug("odoo_build_cache.py not present - build downloads every archive")


    # Stop and remove the container plus its image
    for step_label, step_command in (
            (f"stop {container_name}", f"docker stop {container_name}"),
            (f"remove {container_name}", f"docker rm {container_name}"),
            (f"remove image {image}:latest", f"docker rmi {image}:latest")):
        _, _, info, warn, err = run_step(step_label, step_command)
        total_info += info
        total_warnings += warn
        total_errors += err
    
    # Verify Dockerfile exists
    if not isfile('Dockerfile'):
        logger.error(f"Dockerfile not found in {path}")
        total_errors += 1
        try:
            os.chdir(original_dir)  # Change back to original directory
        except:
            pass
        return False, total_info, total_warnings, total_errors
        
    # Build new image - a full build downloads every module and can easily
    # take 10-20 minutes. Under -v every line is streamed; without it only
    # warnings and errors appear and a spinner shows the build is alive — this
    # was the one long-running step that ignored the verbosity setting, so a
    # plain 'doup' drowned in several hundred 'Downloaded: ...' lines.
    should_filter = logger.getEffectiveLevel() > logging.INFO
    proxy_build_args = build_proxy_build_args(proxy_settings)

    # The Dockerfile bind-mounts zips/ during the build step, which needs
    # BuildKit and a source directory that exists. odoo_build_cache.py creates
    # it, but a server without the cache script must still be able to build.
    try:
        os.makedirs(join(path, "zips"), exist_ok=True)
    except OSError as e:
        logger.warning(f"Could not create the zips directory: {e}")

    build_env = dict(proxy_env or {})
    build_env["DOCKER_BUILDKIT"] = "1"

    success, _, info, warn, err = run_stream(
        f"build image {image}",
        f"docker build {proxy_build_args}-t {image} .",
        timeout=3600, env=build_env,
        filter_output=should_filter,
        show_progress=should_filter,
        progress_msg="  building image")
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
        update_command = f"docker run --rm {env_forward}-p {port}:8069 -p {poll_port}:8072 --name={container_name} {volume} {image} update --database={db_name} {db_auth_args}{load_translation}"

        # Debug only - the command line can contain database credentials
        if logger.getEffectiveLevel() <= logging.DEBUG:
            logger.info(f"Update command: {update_command}")

        # Without -v only warnings and errors are streamed, with -v every line
        should_filter = logger.getEffectiveLevel() > logging.INFO
        success, _, info, warn, err = run_stream(
            "update odoo",
            update_command,
            filter_output=should_filter,
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
        neutralize_command = f"docker run --rm {env_forward}-p {port}:8069 -p {poll_port}:8072 --name={container_name} {volume} {image} neutralize --database={db_name} {db_auth_args}"

        # Debug only - the command line can contain database credentials
        if logger.getEffectiveLevel() <= logging.DEBUG:
            logger.info(f"Neutralize command: {neutralize_command}")

        # Without -v only warnings and errors are streamed, with -v every line
        should_filter = logger.getEffectiveLevel() > logging.INFO
        success, _, info, warn, err = run_stream(
            "neutralize odoo",
            neutralize_command,
            filter_output=should_filter,
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
            
        update_command = f"docker run --rm {env_forward}-p {port}:8069 -p {poll_port}:8072 --name={container_name} {volume} {image} update --database={db_name} {db_auth_args}{load_translation}"

        # Debug only - the command line can contain database credentials
        if logger.getEffectiveLevel() <= logging.DEBUG:
            logger.info(f"Update command: {update_command}")

        # Without -v only warnings and errors are streamed, with -v every line
        should_filter = logger.getEffectiveLevel() > logging.INFO
        success, _, info, warn, err = run_stream(
            "update odoo",
            update_command,
            filter_output=should_filter,
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
    restart_command = f"docker run -d --restart=always -p {port}:8069 -p {poll_port}:8072 --name={container_name} {volume} {image} start"
    logger.info(f"Restart command: {restart_command}")
    success, _, info, warn, err = run_step(f"restart {container_name}", restart_command)
    total_info += info
    total_warnings += warn
    total_errors += err
    if not success:
        logger.error("Failed to restart container")
        return False, total_info, total_warnings, total_errors
    
    # Show countdown for delay time instead of silent sleep - the live
    # countdown needs a terminal, under cron it would only produce \r noise
    if delay_time > 0:
        try:
            if IS_TTY:
                for remaining in range(delay_time, 0, -1):
                    sys.stdout.write(f"\rWaiting: {remaining} seconds remaining... (Ctrl+C to skip) ")
                    sys.stdout.flush()
                    time.sleep(1)
                sys.stdout.write("\r\033[K")
            else:
                time.sleep(delay_time)
            print_step("wait for startup", "ok", delay_time)
        except KeyboardInterrupt:
            sys.stdout.write("\r\033[K")
            print_step("wait for startup", "skipped by user")
    
    # Run additional scripts if they exist
    remove_menus_script = join(path, "remove_website_menus.py")
    if isfile(remove_menus_script):
        success, _, info, warn, err = run_step(
            "remove website menus", f"python3 {remove_menus_script}")
        total_info += info
        total_warnings += warn
        total_errors += err
        if not success:
            logger.warning("Failed to run remove_website_menus.py script")
            total_warnings += 1
        
        cleanup_script = join(path, "cleanup_odoo.py")
        if isfile(cleanup_script):
            success, _, info, warn, err = run_step(
                "cleanup odoo", f"python3 {cleanup_script}")
            total_info += info
            total_warnings += warn
            total_errors += err
            if not success:
                logger.warning("Failed to run cleanup_odoo.py script")
                total_warnings += 1
    
    # Clean up old filestore backups. Both live under filestore-backup/ so a
    # single .dockerignore entry keeps them out of the build context.
    filestore_root = join(path, "filestore-backup")
    current_filestore = join(filestore_root, db_name)
    backup_path = join(filestore_root, f"{db_name}.bak")
    if isdir(backup_path):
        _, _, info, warn, err = run_step(
            "remove old filestore backup", f"rm -rf {backup_path}")
        total_info += info
        total_warnings += warn
        total_errors += err

    if isdir(current_filestore):
        logger.info(f"Moving current filestore to backup: {current_filestore} -> {backup_path}")
        _, _, info, warn, err = run_step(
            "move filestore to backup", f"mv {current_filestore} {backup_path}")
        total_info += info
        total_warnings += warn
        total_errors += err
    
    # Clean up Docker system
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
    
    print_section_summary(db_name, total_warnings, total_errors,
                          time.time() - container_started)
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

    # First line of every run: a pasted log should say which version produced it.
    mode = "verbose" if logger.getEffectiveLevel() <= logging.INFO else "quiet, -v for details"
    print(f"{CR}update_docker_odoo.py {SCRIPT_VERSION} ({SCRIPT_DATE}) · {mode}")
    sys.stdout.flush()
    
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
            defaults = config.get('defaults') or {}
            dockerfiles_source = expand_path(
                defaults.get('dockerfiles_source') or DEFAULT_DOCKERFILES_SOURCE)
            result = process_container(container, resolve_proxy_settings(config, container),
                                       dockerfiles_source)
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
    
    # Every warning and error of the run, collected in one place. Printed
    # before the summary so its counts refer to the block right above them.
    print_issue_recap()

    # Closing summary - same step schema as the container sections, marked
    # with a different rune so it stands out from them
    execution_time = time.time() - start_time
    print_section("summary", rune='═')
    if args.validate:
        print_step("configuration validation", "done", execution_time)
        print_step("valid configurations", str(validate_count))
        if failure_count > 0:
            print_step("invalid configurations", str(failure_count))
    elif args.dns_optimize:
        print_step("dns optimization", "done", execution_time)
        print_step("valid configurations", str(validate_count))
        print_step("dns configuration",
                   "updated" if config_modified else "already optimal")
        if failure_count > 0:
            print_step("invalid configurations", str(failure_count))
    else:
        print_step("update process", "done", execution_time)
        print_step("successful updates", str(success_count))
        if failure_count > 0:
            print_step("failed updates", str(failure_count))
        print_step("log statistics",
                   f"{total_info_count} info, {total_warning_count} warning, "
                   f"{total_error_count} error")

        # Final Docker system cleanup after all containers are processed.
        # It prints its own step line, including the space it reclaimed.
        clean_docker_system()
    print()

    # Ensure all output is flushed
    sys.stdout.flush()
    sys.stderr.flush()
    
    # Exit with appropriate code
    return 0 if failure_count == 0 else 1

if __name__ == "__main__":
    try:
        exit_code = main()
        if logger.getEffectiveLevel() <= logging.INFO:
            logger.info("Script execution completed. Exiting now.")
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.warning("Script interrupted by user. Exiting now.")
        sys.exit(130)  # Standard exit code for SIGINT
    except Exception as e:
        logger.error(f"Unhandled exception: {str(e)}")
        sys.exit(1)
