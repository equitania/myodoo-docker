# -*- coding: utf-8 -*-
"""
DNS optimization utilities for getScripts.py

Handles DNS configuration, Hetzner detection, and DNS optimization.
"""

import os
import re
import socket
import subprocess
import time
from typing import Optional, List, Dict, Any, Tuple

from .logging_config import get_logger
from .system_utils import run_command, is_root_or_has_sudo
from .constants import DEFAULT_DNS_SERVERS


# Marker file for declined DNS optimization
DNS_DECLINED_MARKER = os.path.expanduser("~/.getscripts_dns_declined")


def is_hetzner_server() -> bool:
    """
    Check if the server is running on Hetzner infrastructure.

    Returns:
        bool: True if on Hetzner
    """
    logger = get_logger()

    # Check via hostname patterns
    try:
        hostname = socket.gethostname()
        if any(pattern in hostname.lower() for pattern in ['hetzner', 'your-server', 'static.hetzner']):
            logger.info("Detected Hetzner server via hostname")
            return True
    except Exception:
        pass

    # Check via /etc/resolv.conf for Hetzner DNS
    try:
        with open('/etc/resolv.conf', 'r') as f:
            content = f.read()
        if '213.133.100' in content or '213.133.98' in content or '213.133.99' in content:
            logger.info("Detected Hetzner server via DNS configuration")
            return True
    except Exception:
        pass

    # Check via network configuration
    try:
        result = subprocess.run(['ip', 'addr'], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            # Hetzner IP ranges
            hetzner_patterns = ['159.69.', '116.203.', '135.181.', '65.108.', '5.75.']
            for pattern in hetzner_patterns:
                if pattern in result.stdout:
                    logger.info(f"Detected Hetzner server via IP range {pattern}*")
                    return True
    except Exception:
        pass

    return False


def validate_dns_server(ip: str) -> bool:
    """
    Validate if a DNS server IP is valid and responds.

    Args:
        ip: IP address to validate

    Returns:
        bool: True if valid DNS server
    """
    logger = get_logger()

    # Validate IP format
    try:
        socket.inet_aton(ip)
    except socket.error:
        logger.warning(f"Invalid IP format: {ip}")
        return False

    # Test DNS response (quick check)
    try:
        result = subprocess.run(
            ['dig', '+short', '+time=2', '@' + ip, 'google.com'],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0 and result.stdout.strip()
    except Exception as e:
        logger.warning(f"DNS server {ip} did not respond: {e}")
        return False


def get_dns_preference() -> List[str]:
    """
    Interactive DNS server selection.

    Returns:
        List[str]: Selected DNS servers (empty list if skipped)
    """
    print("\n" + "=" * 60)
    print("DNS Server Konfiguration")
    print("=" * 60)
    print("\n1. Standard (Cloudflare 1.1.1.1, Google 8.8.8.8, Quad9 9.9.9.9)")
    print("2. Benutzerdefiniert (eigene DNS-Server eingeben)")
    print("3. Überspringen (keine Änderung)")

    try:
        choice = input("\nAuswahl [1/2/3]: ").strip()

        if choice == "2":
            dns_servers = []
            primary = input("Primärer DNS-Server (z.B. 192.168.1.1): ").strip()
            if primary and validate_dns_server(primary):
                dns_servers.append(primary)
            elif primary:
                print(f"Warnung: {primary} ist kein gültiger DNS-Server")
                return []

            secondary = input("Sekundärer DNS-Server (optional, Enter für keinen): ").strip()
            if secondary:
                if validate_dns_server(secondary):
                    dns_servers.append(secondary)
                else:
                    print(f"Warnung: {secondary} ist kein gültiger DNS-Server")

            tertiary = input("Tertiärer DNS-Server (optional, Enter für keinen): ").strip()
            if tertiary:
                if validate_dns_server(tertiary):
                    dns_servers.append(tertiary)
                else:
                    print(f"Warnung: {tertiary} ist kein gültiger DNS-Server")

            if dns_servers:
                return dns_servers
            else:
                print("Keine gültigen DNS-Server angegeben, verwende Standard")
                return DEFAULT_DNS_SERVERS

        elif choice == "1":
            return DEFAULT_DNS_SERVERS
        else:
            return []  # Skip
    except (EOFError, KeyboardInterrupt):
        return []


def check_dns_configuration() -> Dict[str, Any]:
    """
    Check current DNS configuration and detect issues.

    Returns:
        Dict[str, Any]: DNS configuration info and recommendations
    """
    logger = get_logger()

    info = {
        "is_hetzner": is_hetzner_server(),
        "current_dns": [],
        "method": None,
        "needs_optimization": False,
        "recommendation": None,
        "dns_performance": None
    }

    # Get current DNS servers
    try:
        with open('/etc/resolv.conf', 'r') as f:
            content = f.read()
        for line in content.split('\n'):
            if line.strip().startswith('nameserver'):
                dns = line.split()[1]
                info["current_dns"].append(dns)
    except Exception as e:
        logger.error(f"Could not read DNS configuration: {e}")
        return info

    # Detect configuration method
    if os.path.exists('/run/systemd/resolve/resolv.conf'):
        info["method"] = "systemd-resolved"
    elif os.path.exists('/etc/resolvconf/resolv.conf.d/'):
        info["method"] = "resolvconf"
    else:
        info["method"] = "direct"

    # Check if optimization is needed
    problematic_dns = ['127.0.0.53']  # systemd stub resolver
    hetzner_dns = ['213.133.100', '213.133.98', '213.133.99']

    for dns in info["current_dns"]:
        if dns in problematic_dns:
            info["needs_optimization"] = True
            info["recommendation"] = "systemd stub resolver detected, external DNS recommended"
            break
        if info["is_hetzner"] and any(hd in dns for hd in hetzner_dns):
            info["needs_optimization"] = True
            info["recommendation"] = "Hetzner DNS with potential DigitalOcean issues detected"
            break

    # Test DNS performance
    info["dns_performance"] = _test_dns_performance(info["current_dns"])

    return info


def _test_dns_performance(dns_servers: List[str]) -> Dict[str, Any]:
    """
    Test DNS query performance.

    Args:
        dns_servers: List of DNS servers to test

    Returns:
        Dict with performance metrics
    """
    results = {"current": {}, "proposed": {}}

    # Test current DNS
    if dns_servers:
        times = []
        for _ in range(3):
            start = time.time()
            try:
                socket.gethostbyname('google.com')
                times.append((time.time() - start) * 1000)
            except Exception:
                pass
        if times:
            results["current"] = {
                "avg_query_time_ms": round(sum(times) / len(times), 2),
                "dns_servers": dns_servers
            }

    # Test proposed DNS (1.1.1.1)
    try:
        result = subprocess.run(
            ['dig', '+short', '+time=2', '@1.1.1.1', 'google.com'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            # Parse query time from dig output
            full_result = subprocess.run(
                ['dig', '+stats', '@1.1.1.1', 'google.com'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if full_result.returncode == 0:
                match = re.search(r'Query time: (\d+) msec', full_result.stdout)
                if match:
                    results["proposed"] = {
                        "avg_query_time_ms": int(match.group(1)),
                        "dns_servers": ["1.1.1.1"]
                    }
    except Exception:
        pass

    return results


def optimize_dns_configuration(dns_servers: Optional[List[str]] = None) -> bool:
    """
    Apply DNS optimization based on detected configuration method.

    Args:
        dns_servers: List of DNS servers to use (default: DEFAULT_DNS_SERVERS)

    Returns:
        bool: True if optimization was successful
    """
    logger = get_logger()

    if dns_servers is None:
        dns_servers = DEFAULT_DNS_SERVERS

    if not dns_servers:
        logger.info("No DNS servers provided, skipping optimization")
        return False

    if not is_root_or_has_sudo():
        logger.warning("Cannot optimize DNS without sudo privileges")
        return False

    info = check_dns_configuration()
    method = info["method"]

    logger.info(f"Applying DNS optimization using method: {method}")
    logger.info(f"DNS servers: {', '.join(dns_servers)}")

    try:
        if method == "systemd-resolved":
            return _optimize_systemd_resolved(dns_servers)
        elif method == "resolvconf":
            return _optimize_resolvconf(dns_servers)
        else:
            return _optimize_direct(dns_servers)
    except Exception as e:
        logger.error(f"Error applying DNS optimization: {e}")
        return False


def _optimize_systemd_resolved(dns_servers: List[str]) -> bool:
    """Apply DNS optimization via systemd-resolved."""
    logger = get_logger()

    config_content = f"""[Resolve]
DNS={' '.join(dns_servers)}
FallbackDNS=9.9.9.9 149.112.112.112
DNSStubListener=yes
"""
    try:
        run_command(f"echo '{config_content}' | sudo tee /etc/systemd/resolved.conf.d/dns.conf", shell=True, check=True)
        run_command("sudo systemctl restart systemd-resolved", check=True)
        logger.info("systemd-resolved configuration updated")
        return True
    except Exception as e:
        logger.error(f"Failed to configure systemd-resolved: {e}")
        return False


def _optimize_resolvconf(dns_servers: List[str]) -> bool:
    """Apply DNS optimization via resolvconf."""
    logger = get_logger()

    nameservers = '\n'.join([f"nameserver {dns}" for dns in dns_servers])
    config_content = f"""# DNS servers configured by getScripts.py
{nameservers}
"""
    try:
        run_command(f"echo '{config_content}' | sudo tee /etc/resolvconf/resolv.conf.d/head", shell=True, check=True)
        run_command("sudo resolvconf -u", check=True)
        logger.info("resolvconf configuration updated")
        return True
    except Exception as e:
        logger.error(f"Failed to configure resolvconf: {e}")
        return False


def _optimize_direct(dns_servers: List[str]) -> bool:
    """Apply DNS optimization directly to /etc/resolv.conf."""
    logger = get_logger()

    nameservers = '\n'.join([f"nameserver {dns}" for dns in dns_servers])
    config_content = f"""# DNS servers configured by getScripts.py
{nameservers}
options edns0 trust-ad
"""
    try:
        # Backup current configuration
        run_command("sudo cp /etc/resolv.conf /etc/resolv.conf.bak", check=True)

        # Write new configuration
        run_command(f"echo '{config_content}' | sudo tee /etc/resolv.conf", shell=True, check=True)

        # Make immutable to prevent overwrite
        run_command("sudo chattr +i /etc/resolv.conf", check=True)

        logger.info("Direct DNS configuration applied")
        return True
    except Exception as e:
        logger.error(f"Failed to apply direct DNS configuration: {e}")
        return False


def is_dns_already_optimized() -> bool:
    """
    Check if DNS is already optimized with external DNS servers.

    Returns:
        bool: True if already optimized
    """
    try:
        with open('/etc/resolv.conf', 'r') as f:
            content = f.read()

        # Check for common public DNS servers
        public_dns = ['1.1.1.1', '8.8.8.8', '9.9.9.9', '1.0.0.1', '8.8.4.4']
        for dns in public_dns:
            if dns in content:
                return True
        return False
    except Exception:
        return False


def is_dns_optimization_declined() -> bool:
    """
    Check if user has previously declined DNS optimization.

    Returns:
        bool: True if declined
    """
    return os.path.exists(DNS_DECLINED_MARKER)


def mark_dns_optimization_declined() -> None:
    """Mark that user has declined DNS optimization."""
    try:
        with open(DNS_DECLINED_MARKER, 'w') as f:
            f.write("DNS optimization declined by user\n")
    except Exception:
        pass
