#!/usr/bin/env python3
# -*- coding: utf-8 -*-
############################################################################
# Filename:    blacklist_update.py
# Purpose:     Update NGINX blacklist with IP addresses from various sources
#
# Author:      Equitania Software GmbH
# Copyright:   (c) 2024 Equitania Software GmbH
# License:     LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)
#
# Created:     2024-01-09
############################################################################

import os
import sys
import subprocess
import json
import requests
import re
import logging
import argparse
from pathlib import Path
from typing import Set, List, Optional
from datetime import datetime

def parse_arguments():
    """
    Parse command line arguments
    
    Returns:
        argparse.Namespace: Parsed command line arguments
    """
    parser = argparse.ArgumentParser(
        description='Update NGINX blacklist with IP addresses from various sources',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
    %(prog)s                     # Update blacklist using all available sources
    %(prog)s --no-emerging       # Skip Emerging Threats source
    %(prog)s --no-spamhaus      # Skip Spamhaus source
    %(prog)s --api-key KEY      # Set AbuseIPDB API key
    
Sources:
    - AbuseIPDB (requires API key)
    - Emerging Threats
    - Spamhaus DROP list
        
For more information, visit:
https://github.com/equitania/myodoo-docker
'''
    )
    
    parser.add_argument('--api-key', 
                       help='AbuseIPDB API key (overrides the default)')
    parser.add_argument('--no-emerging', 
                       action='store_true',
                       help='Skip Emerging Threats source')
    parser.add_argument('--no-spamhaus', 
                       action='store_true',
                       help='Skip Spamhaus source')
    parser.add_argument('--verbose', '-v',
                       action='store_true',
                       help='Enable verbose output')
    parser.add_argument('--version',
                       action='version',
                       version='%(prog)s 1.0.0')
    
    return parser.parse_args()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/var/log/blacklist_update.log')
    ]
)
logger = logging.getLogger(__name__)

# Configuration
BLACKLIST_FILE = "/etc/nginx/blacklist.conf"
TEMP_DIR = "/tmp/blacklists"
Path(TEMP_DIR).mkdir(parents=True, exist_ok=True)

# Source URLs
ABUSEIPDB_URL = "https://api.abuseipdb.com/api/v2/blacklist"
EMERGING_THREATS_URL = "https://rules.emergingthreats.net/blockrules/emerging-botcc.rules"
SPAMHAUS_URL = "https://www.spamhaus.org/drop/drop.txt"

# AbuseIPDB API Key (replace with your key!)
ABUSEIPDB_API_KEY = "YOUR_API_KEY"

def is_valid_api_key() -> bool:
    """
    Check if the AbuseIPDB API key has been changed from default.
    
    Returns:
        bool: True if API key has been changed, False otherwise
    """
    return ABUSEIPDB_API_KEY not in ["YOUR_API_KEY", "DEIN_API_KEY", ""]

def fetch_abuseipdb() -> bool:
    """
    Fetch IP addresses from AbuseIPDB API.
    
    Returns:
        bool: True if successful or skipped, False if failed
    """
    if not is_valid_api_key():
        logger.info("Skipping AbuseIPDB: No valid API key provided")
        return True
        
    logger.info("Fetching data from AbuseIPDB...")
    headers = {
        "Key": ABUSEIPDB_API_KEY,
        "Accept": "application/json"
    }
    params = {"confidenceMinimum": 90}
    
    try:
        response = requests.get(ABUSEIPDB_URL, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        ips = [ip["ipAddress"] for ip in response.json()["data"]]
        with open(f"{TEMP_DIR}/abuseipdb.txt", "w") as f:
            f.write("\n".join(ips))
        logger.info(f"Successfully fetched {len(ips)} IPs from AbuseIPDB")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching from AbuseIPDB: {e}")
        return False

def fetch_emerging_threats() -> bool:
    """
    Fetch IP addresses from Emerging Threats.
    
    Returns:
        bool: True if successful, False otherwise
    """
    logger.info("Fetching data from Emerging Threats...")
    try:
        response = requests.get(EMERGING_THREATS_URL, timeout=30)
        response.raise_for_status()
        ip_pattern = r'[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+(?:/(?:[0-9]{1,2}))?'
        ips = re.findall(ip_pattern, response.text)
        with open(f"{TEMP_DIR}/emerging_threats_parsed.txt", "w") as f:
            f.write("\n".join(ips))
        logger.info(f"Successfully fetched {len(ips)} IPs from Emerging Threats")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching from Emerging Threats: {e}")
        return False

def fetch_spamhaus() -> bool:
    """
    Fetch IP addresses from Spamhaus DROP list.
    
    Returns:
        bool: True if successful, False otherwise
    """
    logger.info("Fetching data from Spamhaus DROP list...")
    try:
        response = requests.get(SPAMHAUS_URL, timeout=30)
        response.raise_for_status()
        ip_pattern = r'[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+(?:/(?:[0-9]{1,2}))?'
        ips = re.findall(ip_pattern, response.text)
        with open(f"{TEMP_DIR}/spamhaus_parsed.txt", "w") as f:
            f.write("\n".join(ips))
        logger.info(f"Successfully fetched {len(ips)} IPs from Spamhaus")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching from Spamhaus: {e}")
        return False

def combine_blacklists() -> Optional[Set[str]]:
    """
    Combine all blacklists and convert to NGINX format.
    
    Returns:
        Optional[Set[str]]: Set of unique IPs if successful, None if failed
    """
    logger.info("Combining all sources...")
    all_ips = set()
    
    source_files = {
        "abuseipdb.txt": "AbuseIPDB",
        "emerging_threats_parsed.txt": "Emerging Threats",
        "spamhaus_parsed.txt": "Spamhaus"
    }
    
    for filename, source_name in source_files.items():
        try:
            with open(f"{TEMP_DIR}/{filename}", "r") as f:
                ips = {line.strip() for line in f if line.strip()}
                all_ips.update(ips)
                logger.info(f"Added {len(ips)} IPs from {source_name}")
        except FileNotFoundError:
            logger.warning(f"Warning: {filename} not found")
    
    if not all_ips:
        logger.error("No IP addresses found in any source")
        return None

    try:
        with open(BLACKLIST_FILE, "w") as f:
            f.write(f"# Combined Blacklist (automatically generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')})\n")
            for ip in sorted(all_ips):
                f.write(f"deny {ip};\n")
        logger.info(f"Successfully wrote {len(all_ips)} IPs to blacklist")
        return all_ips
    except IOError as e:
        logger.error(f"Error writing to blacklist file: {e}")
        return None

def reload_nginx() -> bool:
    """
    Test and reload NGINX configuration.
    
    Returns:
        bool: True if successful, False otherwise
    """
    logger.info("Testing and reloading NGINX...")
    try:
        # Test nginx configuration
        subprocess.run(["nginx", "-t"], check=True, capture_output=True, text=True)
        # Reload nginx
        subprocess.run(["systemctl", "reload", "nginx"], check=True, capture_output=True, text=True)
        logger.info("Successfully reloaded NGINX")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Error reloading NGINX: {e.stderr}")
        return False

def cleanup() -> None:
    """Remove temporary files and directory."""
    try:
        import shutil
        shutil.rmtree(TEMP_DIR)
        logger.info("Cleaned up temporary files")
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

def main() -> int:
    """
    Main function to coordinate the blacklist update process.
    
    Returns:
        int: 0 for success, 1 for failure
    """
    args = parse_arguments()
    
    # Set logging level based on verbose flag
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    # Override API key if provided
    global ABUSEIPDB_API_KEY
    if args.api_key:
        ABUSEIPDB_API_KEY = args.api_key
    
    success = True
    try:
        # Fetch data from all sources
        sources = []
        
        if is_valid_api_key():
            sources.append(fetch_abuseipdb())
        
        if not args.no_emerging:
            sources.append(fetch_emerging_threats())
            
        if not args.no_spamhaus:
            sources.append(fetch_spamhaus())
        
        if not sources:
            logger.error("No sources enabled. Please enable at least one source.")
            return 1
            
        if not any(sources):
            logger.error("All sources failed to fetch data")
            return 1
            
        if not all(sources):
            logger.warning("Some sources failed to fetch, continuing with available data")
        
        # Combine blacklists
        if combine_blacklists() is None:
            logger.error("Failed to combine blacklists")
            return 1
        
        # Reload nginx
        if not reload_nginx():
            return 1
        
        cleanup()
        logger.info("Blacklist update completed successfully")
        return 0
    
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    exit(main())
