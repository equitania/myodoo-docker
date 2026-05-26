#!/usr/bin/env python3
"""
Server-Härtungs-Skript
=======================
Version: 1.3.0 / Date: 26.05.2026

Prüft und härtet: UFW, Fail2Ban, SSH, Kernel, Kernel-Module, Docker,
Auto-Updates, auditd, AIDE, Nginx
Sensitive values (IPs, ports) are loaded from .env via ${ENV_VAR} substitution.

Aufruf:
  sudo python3 server_hardening.py                          # Audit (Dry-Run)
  sudo python3 server_hardening.py --apply                  # Alles anwenden
  sudo python3 server_hardening.py --apply --module ufw     # Nur UFW
  sudo python3 server_hardening.py --apply --module fail2ban ssh sysctl
"""

import subprocess
import sys
import os
import re
import json
import shutil
import argparse
import ipaddress
from pathlib import Path
from datetime import datetime

try:
    import yaml
except ImportError:
    print("PyYAML fehlt. Installation: pip install pyyaml  oder  apt-get install python3-yaml")
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

# ─── Terminal-Farben ───────────────────────────────────────────
class C:
    OK   = "\033[92m"
    WARN = "\033[93m"
    FAIL = "\033[91m"
    INFO = "\033[94m"
    BOLD = "\033[1m"
    DIM  = "\033[2m"
    END  = "\033[0m"

def ok(msg):     print(f"  {C.OK}✓{C.END} {msg}")
def warn(msg):   print(f"  {C.WARN}⚠{C.END} {msg}")
def fail(msg):   print(f"  {C.FAIL}✗{C.END} {msg}")
def info(msg):   print(f"  {C.INFO}ℹ{C.END} {msg}")
def header(msg): print(f"\n{C.BOLD}{'─'*60}\n  {msg}\n{'─'*60}{C.END}")
def sub(msg):    print(f"\n  {C.BOLD}{msg}{C.END}")

# ─── Hilfsfunktionen ──────────────────────────────────────────
def run(cmd, check=False, timeout=30):
    """Execute a shell command and return stdout.

    Uses shell=True because all commands originate from the trusted
    YAML configuration, never from user input.
    """
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        warn(f"Timeout ({timeout}s) bei: {cmd}")
        return None
    if check and r.returncode != 0:
        return None
    return r.stdout.strip()

def backup_file(path):
    """Erstellt ein Backup mit Zeitstempel."""
    p = Path(path)
    if p.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = p.with_suffix(f".backup_{ts}{p.suffix}")
        shutil.copy2(p, backup)
        info(f"Backup: {backup}")
        return True
    return False

def confirm(msg, force=False):
    if force:
        return True
    answer = input(f"\n  {C.BOLD}{msg} (j/N): {C.END}")
    return answer.lower() in ("j", "ja", "y", "yes")

# ─── Globale Zähler ───────────────────────────────────────────
class Stats:
    ok_count = 0
    warn_count = 0
    fail_count = 0
    fix_count = 0

    @classmethod
    def reset(cls):
        cls.ok_count = cls.warn_count = cls.fail_count = cls.fix_count = 0

# ─── Environment-Variablen Substitution ─────────────────────
def resolve_env_vars(obj):
    """Recursively replace ${ENV_VAR} placeholders in a YAML data structure.

    Supports str, int, list, dict.  Auto-casts purely numeric results to int
    so that port numbers remain integers after substitution.
    """
    pattern = re.compile(r"\$\{([^}]+)\}")

    def _resolve_str(s):
        def _replacer(m):
            # Missing OR empty optional vars (e.g. unused ALLOWED_IP_N slots)
            # resolve to "" so they are filtered out downstream — the 5 IP slots
            # are optional by design (0-5 may be filled). Required values like
            # SSH_PORT that end up empty are caught by validate_config's
            # type/range checks instead of leaving a dangling placeholder.
            return os.environ.get(m.group(1), "")
        result = pattern.sub(_replacer, s)
        # Auto-cast to int if the result is purely numeric
        if result.isdigit():
            return int(result)
        return result

    if isinstance(obj, str):
        return _resolve_str(obj)
    if isinstance(obj, list):
        return [resolve_env_vars(item) for item in obj]
    if isinstance(obj, dict):
        return {k: resolve_env_vars(v) for k, v in obj.items()}
    return obj


def inject_allowed_ips(config):
    """Populate the admin-IP allowlist dynamically from ALLOWED_IP_<n> env vars.

    Any number of ALLOWED_IP_1, ALLOWED_IP_2, ... (each with an optional
    ALLOWED_IP_<n>_COMMENT) is supported — there is no fixed slot count, and
    gaps are tolerated. Empty/missing entries are ignored. The collected IPs are:
      - applied to every ufw.restricted_ports entry that has no static allowed_ips
      - appended to fail2ban.ignoreip (after the base loopback entries, de-duped)

    Returns the ordered list of {ip, comment} dicts.
    """
    pat = re.compile(r"^ALLOWED_IP_(\d+)$")
    entries = []
    for key, val in os.environ.items():
        m = pat.match(key)
        if not m:
            continue
        ip = (val or "").strip()
        if not ip:
            continue
        n = int(m.group(1))
        comment = (os.environ.get(f"ALLOWED_IP_{n}_COMMENT", "") or "").strip()
        entries.append((n, ip, comment))
    entries.sort(key=lambda e: e[0])
    allowed = [{"ip": ip, "comment": comment} for _, ip, comment in entries]

    # UFW: fill restricted_ports that do not define a static allowed_ips list.
    for rp in config.get("ufw", {}).get("restricted_ports", []):
        if not rp.get("allowed_ips"):
            rp["allowed_ips"] = [dict(a) for a in allowed]

    # fail2ban: base ignoreip entries + dynamic admin IPs (de-duplicated, order kept).
    f2b = config.setdefault("fail2ban", {})
    base = [ip for ip in f2b.get("ignoreip", []) if ip]
    seen = set()
    f2b["ignoreip"] = [x for x in base + [a["ip"] for a in allowed]
                       if not (x in seen or seen.add(x))]
    return allowed


def validate_config(config):
    """Validate critical config values.  Returns list of error strings."""
    errors = []

    # SSH port
    ssh_port = config.get("ssh", {}).get("port")
    if ssh_port is not None:
        if not isinstance(ssh_port, int) or not 1 <= ssh_port <= 65535:
            errors.append(f"ssh.port invalid: {ssh_port!r} (must be 1-65535)")

    # Fail2ban sshd port
    f2b_port = config.get("fail2ban", {}).get("jails", {}).get("sshd", {}).get("port")
    if f2b_port is not None:
        if not isinstance(f2b_port, int) or not 1 <= f2b_port <= 65535:
            errors.append(f"fail2ban.jails.sshd.port invalid: {f2b_port!r}")

    # UFW restricted port
    for rp in config.get("ufw", {}).get("restricted_ports", []):
        port_val = rp.get("port")
        if port_val is not None:
            if not isinstance(port_val, int) or not 1 <= port_val <= 65535:
                errors.append(f"ufw.restricted_ports.port invalid: {port_val!r}")
        for ip_entry in rp.get("allowed_ips", []):
            ip_val = ip_entry.get("ip", "")
            if ip_val and not isinstance(ip_val, str):
                errors.append(f"IP must be a string: {ip_val!r}")
            elif ip_val:
                try:
                    ipaddress.ip_address(ip_val)
                except ValueError:
                    errors.append(f"Invalid IP address: {ip_val!r}")

    # Fail2ban ignoreip
    for ip_val in config.get("fail2ban", {}).get("ignoreip", []):
        if not isinstance(ip_val, str):
            continue
        # Skip empty (unused) entries — filtered out before use in main()
        if not ip_val:
            continue
        # Skip loopback entries
        if ip_val.startswith("127.") or ip_val == "::1":
            continue
        try:
            ipaddress.ip_network(ip_val, strict=False)
        except ValueError:
            errors.append(f"Invalid IP in fail2ban.ignoreip: {ip_val!r}")

    # UFW default policies
    valid_policies = {"allow", "deny", "reject", "limit"}
    for key in ["incoming", "outgoing", "routed"]:
        val = config.get("ufw", {}).get("defaults", {}).get(key)
        if val and val not in valid_policies:
            errors.append(f"ufw.defaults.{key} invalid: {val!r} (must be one of {valid_policies})")

    # Defense-in-depth: ports are already int-validated and IPs are parsed via
    # ipaddress, so neither can carry shell metacharacters. The remaining values
    # that reach a shell=True command are the UFW proto and the sysctl key/value
    # pairs (`sysctl -w {key}={value}`) — validate those explicitly.
    shell_meta = re.compile(r"[;&|`$<>(){}\[\]\\\n\r]")
    valid_protos = {"tcp", "udp", "any"}
    ufw_cfg = config.get("ufw", {})
    for rp in ufw_cfg.get("restricted_ports", []) + ufw_cfg.get("public_ports", []):
        proto = rp.get("proto")
        if proto is not None and proto not in valid_protos:
            errors.append(f"ufw proto invalid: {proto!r} (must be one of {valid_protos})")
    for key, value in config.get("sysctl", {}).get("parameters", {}).items():
        if shell_meta.search(str(key)) or shell_meta.search(str(value)):
            errors.append(f"sysctl entry contains unsafe characters: {key}={value!r}")

    # Check for unresolved ${...} placeholders
    def _check_unresolved(obj, path=""):
        if isinstance(obj, str) and "${" in obj:
            errors.append(f"Unresolved placeholder at {path}: {obj!r}")
        elif isinstance(obj, dict):
            for k, v in obj.items():
                _check_unresolved(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                _check_unresolved(v, f"{path}[{i}]")

    _check_unresolved(config)

    return errors


def check_prerequisites():
    """Check if required binaries are available.  Returns list of warnings."""
    warnings = []
    for binary in ["ufw", "fail2ban-client"]:
        if not shutil.which(binary):
            warnings.append(f"'{binary}' not found in PATH - module may be skipped")
    return warnings


# ─── MODUL: UFW ──────────────────────────────────────────────
def audit_ufw(config, apply=False, force=False):
    header("MODUL: UFW Firewall")
    cfg = config.get("ufw", {})
    if not cfg.get("enabled", True):
        info("UFW-Modul deaktiviert")
        return

    # 1. UFW installiert?
    if not shutil.which("ufw"):
        fail("UFW nicht installiert")
        if apply:
            info("Installiere UFW...")
            run("apt-get update -qq && apt-get install -y -qq ufw")
        else:
            return

    # 2. Status prüfen
    sub("UFW Status")
    status = run("ufw status verbose")
    if "Status: active" in status:
        ok("UFW ist aktiv")
    else:
        fail("UFW ist NICHT aktiv")
        if apply:
            run("echo 'y' | ufw enable")
            ok("UFW aktiviert")
            Stats.fix_count += 1

    # 3. Default Policies
    sub("Default Policies")
    defaults = cfg.get("defaults", {})
    for key in ["incoming", "outgoing", "routed"]:
        expected = defaults.get(key, "")
        if expected and f"{expected} ({key})" in status:
            ok(f"{key}: {expected}")
            Stats.ok_count += 1
        elif expected:
            fail(f"{key}: erwartet '{expected}'")
            Stats.fail_count += 1
            if apply:
                run(f"ufw default {expected} {key}")
                Stats.fix_count += 1

    # 4. IPv6
    sub("IPv6")
    ipv6_expected = cfg.get("ipv6", True)
    ufw_default_content = run("cat /etc/default/ufw")
    ipv6_current = "IPV6=yes" in ufw_default_content
    if ipv6_current == ipv6_expected:
        ok(f"IPv6: {'aktiviert' if ipv6_current else 'deaktiviert'}")
        Stats.ok_count += 1
    else:
        fail(f"IPv6: {'aktiviert' if ipv6_current else 'deaktiviert'} (erwartet: {'aktiviert' if ipv6_expected else 'deaktiviert'})")
        Stats.fail_count += 1
        if apply:
            new_val = "yes" if ipv6_expected else "no"
            p = Path("/etc/default/ufw")
            backup_file(p)
            content = p.read_text()
            content = re.sub(r"IPV6=\w+", f"IPV6={new_val}", content)
            p.write_text(content)
            Stats.fix_count += 1

    # 5. Regeln prüfen
    sub("Firewall-Regeln")
    ufw_rules = []
    in_rules = False
    for line in status.splitlines():
        if line.startswith("--"):
            in_rules = True
            continue
        if in_rules and line.strip():
            ufw_rules.append(line.strip())

    # Soll-Regeln sammeln
    expected_rules = []
    for p_cfg in cfg.get("public_ports", []):
        expected_rules.append({
            "port": p_cfg["port"], "proto": p_cfg.get("proto", "tcp"),
            "from": None, "comment": p_cfg.get("comment", "")
        })
    for r_cfg in cfg.get("restricted_ports", []):
        for ip_cfg in r_cfg.get("allowed_ips", []):
            expected_rules.append({
                "port": r_cfg["port"], "proto": r_cfg.get("proto", "tcp"),
                "from": ip_cfg["ip"], "comment": f"{r_cfg.get('comment', '')} - {ip_cfg.get('comment', '')}"
            })

    add_cmds = []
    for exp in expected_rules:
        port = exp["port"]
        proto = exp["proto"]
        from_ip = exp["from"]
        found = False

        for rule in ufw_rules:
            if from_ip:
                if re.search(rf"^{port}\s+ALLOW IN\s+{re.escape(from_ip)}", rule):
                    found = True
                    break
            else:
                if proto == "any":
                    if re.search(rf"^{port}\s+ALLOW IN\s+Anywhere\s*$", rule):
                        found = True
                        break
                elif re.search(rf"^{port}/{proto}\s+ALLOW IN\s+Anywhere\s*$", rule):
                    found = True
                    break

        if found:
            label = f"Port {port} von {from_ip or 'Anywhere'}"
            ok(f"{label} ({exp['comment']})")
            Stats.ok_count += 1
        else:
            label = f"Port {port} von {from_ip or 'Anywhere'}"
            fail(f"{label} FEHLT ({exp['comment']})")
            Stats.fail_count += 1
            if from_ip:
                if proto == "any":
                    add_cmds.append(f"ufw allow from {from_ip} to any port {port}")
                else:
                    add_cmds.append(f"ufw allow from {from_ip} to any port {port} proto {proto}")
            else:
                if proto == "any":
                    add_cmds.append(f"ufw allow {port}")
                else:
                    add_cmds.append(f"ufw allow {port}/{proto}")

    # Unerwartete Regeln finden
    sub("Unerwartete Regeln")
    unexpected = []
    for rule in ufw_rules:
        if "(v6)" in rule:
            continue
        found = False
        for exp in expected_rules:
            port = str(exp["port"])
            from_ip = exp["from"]
            if from_ip:
                if re.search(rf"^{port}\s+ALLOW IN\s+{re.escape(from_ip)}", rule):
                    found = True
                    break
            else:
                if re.search(rf"^{port}", rule) and "Anywhere" in rule:
                    found = True
                    break
        if not found:
            unexpected.append(rule)

    if unexpected:
        for rule in unexpected:
            warn(f"Unbekannte Regel: {rule}")
            Stats.warn_count += 1
    else:
        ok("Keine unerwarteten Regeln")

    if apply and add_cmds:
        sub("Regeln anwenden")
        for cmd in add_cmds:
            info(f"Ausführe: {cmd}")
            run(cmd)
            Stats.fix_count += 1


# ─── MODUL: Fail2Ban ─────────────────────────────────────────
def audit_fail2ban(config, apply=False, force=False):
    header("MODUL: Fail2Ban")
    cfg = config.get("fail2ban", {})
    if not cfg.get("enabled", True):
        info("Fail2Ban-Modul deaktiviert")
        return

    # 1. Installiert?
    if not shutil.which("fail2ban-client"):
        fail("Fail2Ban nicht installiert")
        if apply:
            info("Installiere Fail2Ban...")
            # python3-systemd is required for the 'backend = systemd' jails below.
            run("apt-get update -qq && apt-get install -y -qq fail2ban python3-systemd")
        else:
            return

    # 2. Status
    sub("Fail2Ban Status")
    status = run("fail2ban-client status")
    if status and "Number of jail" in status:
        ok("Fail2Ban läuft")
        Stats.ok_count += 1
    else:
        fail("Fail2Ban läuft NICHT")
        Stats.fail_count += 1
        if apply:
            run("systemctl enable fail2ban && systemctl start fail2ban")

    # 3. Aktuelle Jails prüfen
    sub("Jails prüfen")
    expected_jails = cfg.get("jails", {})
    if status:
        jail_match = re.search(r"Jail list:\s+(.*)", status)
        active_jails = [j.strip() for j in jail_match.group(1).split(",")] if jail_match else []
    else:
        active_jails = []

    for jail_name in expected_jails:
        if jail_name in active_jails:
            ok(f"Jail '{jail_name}' aktiv")
            Stats.ok_count += 1
        else:
            fail(f"Jail '{jail_name}' NICHT aktiv")
            Stats.fail_count += 1

    # Recidive
    if cfg.get("recidive", {}).get("enabled", False):
        if "recidive" in active_jails:
            ok("Jail 'recidive' aktiv")
        else:
            fail("Jail 'recidive' NICHT aktiv")
            Stats.fail_count += 1

    # 4. banaction prüfen
    sub("Banaction prüfen")
    defaults_conf = run("cat /etc/fail2ban/jail.d/defaults-debian.conf 2>/dev/null") or ""
    jail_local = run("cat /etc/fail2ban/jail.local 2>/dev/null") or ""
    expected_banaction = cfg.get("banaction", "ufw")

    if f"banaction = {expected_banaction}" in jail_local or f"banaction = {expected_banaction}" in defaults_conf:
        ok(f"banaction = {expected_banaction}")
        Stats.ok_count += 1
    else:
        fail(f"banaction ist NICHT '{expected_banaction}' (aktuell vermutlich 'nftables')")
        Stats.fail_count += 1

    # 5. jail.local generieren
    if apply:
        sub("jail.local generieren")
        backup_file("/etc/fail2ban/jail.local")

        lines = ["# Generiert von server_hardening.py"]
        lines.append(f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        # DEFAULT
        lines.append("[DEFAULT]")
        lines.append(f"banaction = {cfg.get('banaction', 'ufw')}")
        lines.append(f"banaction_allports = {cfg.get('banaction', 'ufw')}[type=allports]")

        ignoreip = " ".join(cfg.get("ignoreip", ["127.0.0.1/8"]))
        lines.append(f"ignoreip = {ignoreip}")

        defs = cfg.get("defaults", {})
        lines.append(f"bantime  = {defs.get('bantime', 3600)}")
        lines.append(f"findtime = {defs.get('findtime', 600)}")
        lines.append(f"maxretry = {defs.get('maxretry', 3)}")
        lines.append("")

        # Jails
        for jail_name, jail_cfg in expected_jails.items():
            # A jail pointing at a non-existent logpath makes fail2ban fail to
            # start. Disable such jails (commonly the nginx-* jails before the
            # nginx log pipeline exists) instead of breaking the whole service.
            jail_enabled = jail_cfg.get("enabled", True)
            logpath = jail_cfg.get("logpath")
            if jail_enabled and logpath and not os.path.exists(logpath):
                warn(f"Jail '{jail_name}': Logpath {logpath} fehlt — wird deaktiviert")
                Stats.warn_count += 1
                jail_enabled = False

            lines.append(f"[{jail_name}]")
            lines.append(f"enabled  = {str(jail_enabled).lower()}")
            if "port" in jail_cfg:
                lines.append(f"port     = {jail_cfg['port']}")
            if "backend" in jail_cfg:
                lines.append(f"backend  = {jail_cfg['backend']}")
            if "journalmatch" in jail_cfg:
                lines.append(f"journalmatch = {jail_cfg['journalmatch']}")
            if "logpath" in jail_cfg:
                lines.append(f"logpath  = {jail_cfg['logpath']}")
            if "mode" in jail_cfg:
                lines.append(f"mode     = {jail_cfg['mode']}")
            if "maxretry" in jail_cfg:
                lines.append(f"maxretry = {jail_cfg['maxretry']}")
            if "bantime" in jail_cfg:
                lines.append(f"bantime  = {jail_cfg['bantime']}")
            lines.append("")

        # Recidive
        recidive = cfg.get("recidive", {})
        if recidive.get("enabled", False):
            lines.append("[recidive]")
            lines.append("enabled  = true")
            lines.append(f"bantime  = {recidive.get('bantime', 604800)}")
            lines.append(f"findtime = {recidive.get('findtime', 86400)}")
            lines.append(f"maxretry = {recidive.get('maxretry', 3)}")
            lines.append("")

        jail_local_content = "\n".join(lines)
        Path("/etc/fail2ban/jail.local").write_text(jail_local_content + "\n")
        ok("jail.local geschrieben")
        Stats.fix_count += 1

        info("Fail2Ban wird neugestartet...")
        run("systemctl restart fail2ban")


# ─── MODUL: SSH ──────────────────────────────────────────────
def audit_ssh(config, apply=False, force=False):
    header("MODUL: SSH-Härtung")
    cfg = config.get("ssh", {})
    if not cfg.get("enabled", True):
        info("SSH-Modul deaktiviert")
        return

    sshd_config = Path("/etc/ssh/sshd_config")
    if not sshd_config.exists():
        fail("/etc/ssh/sshd_config nicht gefunden")
        return

    # Read main config + all drop-in files (sshd_config.d/*.conf)
    content = sshd_config.read_text()
    dropin_dir = Path("/etc/ssh/sshd_config.d")
    dropin_content = ""
    if dropin_dir.is_dir():
        for dropin in sorted(dropin_dir.glob("*.conf")):
            dropin_content += dropin.read_text() + "\n"

    # Effective config: drop-ins override main config (first match wins in sshd)
    # For checking, we search drop-ins first, then main config
    effective_content = dropin_content + content

    settings = cfg.get("settings", {})
    changes_needed = []

    sub("SSH-Einstellungen prüfen")
    if dropin_content:
        info(f"Drop-in Verzeichnis: {dropin_dir} ({len(list(dropin_dir.glob('*.conf')))} Dateien)")

    # Port prüfen
    port = cfg.get("port", 22)
    port_match = re.search(r"^\s*Port\s+(\d+)", effective_content, re.MULTILINE)
    current_port = int(port_match.group(1)) if port_match else 22
    if current_port == port:
        ok(f"Port: {port}")
        Stats.ok_count += 1
    else:
        fail(f"Port: {current_port} (erwartet: {port})")
        Stats.fail_count += 1
        changes_needed.append(("Port", str(port)))

    # Einstellungen prüfen
    for key, expected in settings.items():
        expected_str = str(expected)
        # Suche nach aktiver Einstellung (nicht auskommentiert)
        pattern = rf"^\s*{key}\s+(.+)"
        match = re.search(pattern, effective_content, re.MULTILINE)

        if match:
            current = match.group(1).strip()
            if current.lower() == expected_str.lower():
                ok(f"{key}: {current}")
                Stats.ok_count += 1
            else:
                fail(f"{key}: {current} (erwartet: {expected_str})")
                Stats.fail_count += 1
                changes_needed.append((key, expected_str))
        else:
            warn(f"{key}: nicht gesetzt (erwartet: {expected_str})")
            Stats.warn_count += 1
            changes_needed.append((key, expected_str))

    if apply and changes_needed:
        sub("SSH-Konfiguration anpassen")

        # Build the candidate config in memory.
        content = sshd_config.read_text()
        for key, value in changes_needed:
            pattern = rf"^\s*#?\s*{key}\s+.*"
            replacement = f"{key} {value}"
            if re.search(pattern, content, re.MULTILINE):
                content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
            else:
                content += f"\n{replacement}"
            info(f"Setze: {key} {value}")

        # Lockout-safe: validate a TEMP file first (same directory for an atomic
        # replace) and only swap in the new sshd_config after `sshd -t` passes.
        # On failure the live config stays untouched — no risk of a broken file
        # on disk and no chance of being locked out by a botched reload.
        tmp_path = sshd_config.with_name(".sshd_config.hardening_tmp")
        tmp_path.write_text(content)
        os.chmod(tmp_path, 0o600)

        result = run(f"sshd -t -f {tmp_path} 2>&1")
        if result:
            fail(f"SSH-Config Syntaxfehler: {result}")
            warn("Original-Config bleibt UNVERÄNDERT, SSH NICHT neugestartet!")
            tmp_path.unlink(missing_ok=True)
        else:
            ok("SSH-Config Syntax OK")
            backup_file(sshd_config)
            os.replace(tmp_path, sshd_config)  # atomic
            Stats.fix_count += len(changes_needed)
            info("SSH wird neugestartet...")
            run("systemctl reload sshd")


# ─── MODUL: Kernel/Sysctl ────────────────────────────────────
def audit_sysctl(config, apply=False, force=False):
    header("MODUL: Kernel-Parameter (sysctl)")
    cfg = config.get("sysctl", {})
    if not cfg.get("enabled", True):
        info("Sysctl-Modul deaktiviert")
        return

    params = cfg.get("parameters", {})
    changes_needed = {}

    sub("Parameter prüfen")
    for key, expected in params.items():
        current = run(f"sysctl -n {key} 2>/dev/null")
        if current is None:
            warn(f"{key}: nicht verfügbar")
            Stats.warn_count += 1
            continue

        try:
            current_val = int(current.strip())
        except ValueError:
            current_val = current.strip()

        if str(current_val) == str(expected):
            ok(f"{key} = {current_val}")
            Stats.ok_count += 1
        else:
            fail(f"{key} = {current_val} (erwartet: {expected})")
            Stats.fail_count += 1
            changes_needed[key] = expected

    if apply and changes_needed:
        sub("Kernel-Parameter anwenden")
        sysctl_file = Path("/etc/sysctl.d/99-hardening.conf")
        backup_file(sysctl_file)

        lines = [
            "# Server-Härtung - Kernel-Parameter",
            f"# Generiert: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            ""
        ]

        # Alle Parameter schreiben (nicht nur geänderte)
        for key, value in params.items():
            lines.append(f"{key} = {value}")

        sysctl_file.write_text("\n".join(lines) + "\n")
        ok(f"Geschrieben: {sysctl_file}")

        # Sofort anwenden
        for key, value in changes_needed.items():
            run(f"sysctl -w {key}={value}")
            info(f"Gesetzt: {key} = {value}")

        Stats.fix_count += len(changes_needed)


# ─── MODUL: Docker ───────────────────────────────────────────
def audit_docker(config, apply=False, force=False):
    header("MODUL: Docker-Härtung")
    cfg = config.get("docker", {})
    if not cfg.get("enabled", True):
        info("Docker-Modul deaktiviert")
        return

    if not shutil.which("docker"):
        info("Docker nicht installiert - überspringe")
        return

    daemon_json_path = Path("/etc/docker/daemon.json")
    expected = cfg.get("daemon_json", {})

    sub("daemon.json prüfen")
    parse_failed = False
    if daemon_json_path.exists():
        try:
            current = json.loads(daemon_json_path.read_text())
        except json.JSONDecodeError:
            fail("daemon.json ist kein gültiges JSON")
            Stats.fail_count += 1
            current = {}
            parse_failed = True
    else:
        warn("daemon.json existiert nicht")
        current = {}
        Stats.warn_count += 1

    changes_needed = False
    for key, value in expected.items():
        if key in current:
            if current[key] == value:
                ok(f"{key}: {value}")
                Stats.ok_count += 1
            else:
                fail(f"{key}: {current[key]} (erwartet: {value})")
                Stats.fail_count += 1
                changes_needed = True
        else:
            fail(f"{key}: nicht gesetzt (erwartet: {value})")
            Stats.fail_count += 1
            changes_needed = True

    # Container-Bindings prüfen
    sub("Container-Bindings prüfen")
    containers = run("docker ps --format '{{.Names}}\t{{.Ports}}' 2>/dev/null")
    if containers:
        for line in containers.splitlines():
            parts = line.split("\t", 1)
            name = parts[0]
            ports = parts[1] if len(parts) > 1 else ""

            if not ports:
                ok(f"{name}: keine exponierten Ports")
                Stats.ok_count += 1
                continue

            # Prüfe ob alle Bindings auf 127.0.0.1
            exposed = re.findall(r"([\d.]+):(\d+)->(\d+)", ports)
            all_local = True
            for bind_ip, host_port, container_port in exposed:
                if bind_ip != "127.0.0.1":
                    fail(f"{name}: Port {host_port} auf {bind_ip} (nicht 127.0.0.1!)")
                    Stats.fail_count += 1
                    all_local = False

            if all_local and exposed:
                ok(f"{name}: alle Ports auf 127.0.0.1")
                Stats.ok_count += 1

    if apply and changes_needed:
        if parse_failed:
            # Existing file is present but unparseable. Merging into {} would
            # silently wipe every existing setting — refuse and let the admin fix it.
            backup_file(daemon_json_path)
            fail("daemon.json ist defekt — Apply übersprungen (Backup angelegt). "
                 "Bitte manuell reparieren, dann erneut ausführen.")
        else:
            sub("daemon.json schreiben")
            if daemon_json_path.exists():
                backup_file(daemon_json_path)

            merged = {**current, **expected}
            daemon_json_path.write_text(json.dumps(merged, indent=2) + "\n")
            ok("daemon.json geschrieben")
            Stats.fix_count += 1
            warn("Docker-Neustart erforderlich: systemctl restart docker")
            warn("ACHTUNG: Stoppt alle Container! Manuell ausführen.")


# ─── MODUL: Kernel-Module ────────────────────────────────────
_MODULE_NAME_RE = re.compile(r"^[a-z0-9_-]+$")


def audit_kernel_modules(config, apply=False, force=False):
    header("MODUL: Kernel-Modul-Blacklist")
    cfg = config.get("kernel_modules", {})
    if not cfg.get("enabled", True):
        info("Kernel-Modul-Modul deaktiviert")
        return

    # Only allow safe module names (defense-in-depth: names reach modprobe).
    blacklist = [m for m in cfg.get("blacklist", []) if _MODULE_NAME_RE.match(str(m))]
    if not blacklist:
        info("Keine (gültigen) Module konfiguriert")
        return

    blacklist_file = Path("/etc/modprobe.d/hardening-blacklist.conf")

    sub("Geladene Module prüfen")
    loaded = run("lsmod") or ""
    loaded_names = {line.split()[0] for line in loaded.splitlines()[1:] if line.split()}

    changes_needed = False
    for mod in blacklist:
        if mod in loaded_names:
            fail(f"Modul '{mod}' ist GELADEN")
            Stats.fail_count += 1
            changes_needed = True
        else:
            ok(f"Modul '{mod}' nicht geladen")
            Stats.ok_count += 1

    file_text = blacklist_file.read_text() if blacklist_file.exists() else ""
    file_complete = blacklist_file.exists() and all(
        f"install {mod} /bin/true" in file_text for mod in blacklist
    )
    if file_complete:
        ok(f"{blacklist_file} vollständig")
        Stats.ok_count += 1
    else:
        warn(f"{blacklist_file} fehlt oder unvollständig")
        Stats.warn_count += 1
        changes_needed = True

    if apply and changes_needed:
        sub("Blacklist schreiben")
        if blacklist_file.exists():
            backup_file(blacklist_file)
        lines = [
            "# Server-Härtung - Kernel-Modul-Blacklist",
            f"# Generiert: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]
        for mod in blacklist:
            lines.append(f"install {mod} /bin/true")
            lines.append(f"blacklist {mod}")
        blacklist_file.write_text("\n".join(lines) + "\n")
        ok(f"Geschrieben: {blacklist_file}")
        Stats.fix_count += 1

        for mod in blacklist:
            if mod in loaded_names:
                if run(f"modprobe -r {mod} 2>&1"):
                    warn(f"Modul '{mod}' konnte nicht entladen werden (in Benutzung?) — Reboot nötig")
                else:
                    info(f"Modul '{mod}' entladen")


# ─── MODUL: Automatische Updates ─────────────────────────────
def audit_auto_updates(config, apply=False, force=False):
    header("MODUL: Automatische Security-Updates")
    cfg = config.get("auto_updates", {})
    if not cfg.get("enabled", True):
        info("Auto-Update-Modul deaktiviert")
        return

    sub("unattended-upgrades prüfen")
    installed = Path("/usr/bin/unattended-upgrade").exists() or shutil.which("unattended-upgrade") is not None
    if installed:
        ok("unattended-upgrades installiert")
        Stats.ok_count += 1
    else:
        fail("unattended-upgrades NICHT installiert")
        Stats.fail_count += 1
        if apply:
            info("Installiere unattended-upgrades...")
            run("apt-get update -qq && apt-get install -y -qq unattended-upgrades apt-listchanges")

    auto_file = Path("/etc/apt/apt.conf.d/20auto-upgrades")
    periodic_ok = auto_file.exists() and 'Unattended-Upgrade "1"' in auto_file.read_text()
    if periodic_ok:
        ok("Periodische Upgrades aktiviert")
        Stats.ok_count += 1
    else:
        fail("Periodische Upgrades NICHT aktiviert")
        Stats.fail_count += 1

    if apply:
        sub("Konfiguration schreiben")
        if auto_file.exists():
            backup_file(auto_file)
        auto_file.write_text(
            'APT::Periodic::Update-Package-Lists "1";\n'
            'APT::Periodic::Unattended-Upgrade "1";\n'
            'APT::Periodic::Download-Upgradeable-Packages "1";\n'
            'APT::Periodic::AutocleanInterval "7";\n'
        )
        ok(f"Geschrieben: {auto_file}")

        # Auto-reboot overrides in a dedicated drop-in (later file wins in APT;
        # idempotent full rewrite of our own file).
        auto_reboot = bool(cfg.get("auto_reboot", False))
        reboot_time = str(cfg.get("reboot_time", "03:30"))
        if not re.match(r"^\d{1,2}:\d{2}$", reboot_time):
            warn(f"Ungültige reboot_time {reboot_time!r} — verwende 03:30")
            reboot_time = "03:30"
        reboot_val = "true" if auto_reboot else "false"
        override = Path("/etc/apt/apt.conf.d/52unattended-upgrades-hardening")
        override.write_text(
            "// Managed by server_hardening.py\n"
            f'Unattended-Upgrade::Automatic-Reboot "{reboot_val}";\n'
            f'Unattended-Upgrade::Automatic-Reboot-Time "{reboot_time}";\n'
        )
        ok(f"Auto-Reboot: {reboot_val} (Zeit: {reboot_time})")
        run("systemctl enable --now unattended-upgrades 2>&1")
        Stats.fix_count += 1


# ─── MODUL: auditd ───────────────────────────────────────────
AUDITD_RULES = """# Managed by server_hardening.py - baseline audit ruleset
-D
-b 8192
-f 1

# Account / identity changes
-w /etc/passwd -p wa -k identity
-w /etc/group -p wa -k identity
-w /etc/shadow -p wa -k identity
-w /etc/gshadow -p wa -k identity
-w /etc/sudoers -p wa -k scope
-w /etc/sudoers.d/ -p wa -k scope

# SSH daemon configuration
-w /etc/ssh/sshd_config -p wa -k sshd

# Login / authentication records
-w /var/log/lastlog -p wa -k logins
-w /var/log/faillog -p wa -k logins

# System time changes
-a always,exit -F arch=b64 -S adjtimex,settimeofday -k time-change
-w /etc/localtime -p wa -k time-change

# Kernel module (un)loading
-w /sbin/insmod -p x -k modules
-w /sbin/rmmod -p x -k modules
-w /sbin/modprobe -p x -k modules
-a always,exit -F arch=b64 -S init_module,delete_module -k modules
"""


def audit_auditd(config, apply=False, force=False):
    header("MODUL: auditd (Audit-Daemon)")
    cfg = config.get("auditd", {})
    if not cfg.get("enabled", True):
        info("auditd-Modul deaktiviert")
        return

    sub("auditd prüfen")
    if shutil.which("auditctl"):
        ok("auditd installiert")
        Stats.ok_count += 1
    else:
        fail("auditd NICHT installiert")
        Stats.fail_count += 1
        if apply:
            info("Installiere auditd...")
            run("apt-get update -qq && apt-get install -y -qq auditd audispd-plugins")

    rules_file = Path("/etc/audit/rules.d/hardening.rules")
    if rules_file.exists():
        ok(f"{rules_file} vorhanden")
        Stats.ok_count += 1
    else:
        warn(f"{rules_file} fehlt")
        Stats.warn_count += 1

    if apply:
        sub("Audit-Regeln schreiben")
        rules_file.parent.mkdir(parents=True, exist_ok=True)
        if rules_file.exists():
            backup_file(rules_file)
        rules_file.write_text(AUDITD_RULES)
        ok(f"Geschrieben: {rules_file}")
        run("augenrules --load 2>&1")
        run("systemctl enable --now auditd 2>&1")
        Stats.fix_count += 1
        warn("Einige Syscall-Regeln greifen ggf. erst nach einem Reboot.")


# ─── MODUL: AIDE ─────────────────────────────────────────────
def audit_aide(config, apply=False, force=False):
    header("MODUL: AIDE (File-Integrity)")
    cfg = config.get("aide", {})
    if not cfg.get("enabled", True):
        info("AIDE-Modul deaktiviert")
        return

    sub("AIDE prüfen")
    if shutil.which("aide"):
        ok("AIDE installiert")
        Stats.ok_count += 1
    else:
        fail("AIDE NICHT installiert")
        Stats.fail_count += 1
        if apply:
            info("Installiere AIDE...")
            run("apt-get update -qq && apt-get install -y -qq aide aide-common")

    db = Path("/var/lib/aide/aide.db")
    if db.exists():
        ok("AIDE-Datenbank vorhanden")
        Stats.ok_count += 1
    else:
        warn("AIDE-Datenbank nicht initialisiert")
        Stats.warn_count += 1

    if apply and not db.exists() and shutil.which("aide"):
        sub("AIDE initialisieren")
        warn("AIDE-Initialisierung kann mehrere Minuten dauern...")
        run("aideinit -y -f 2>&1", timeout=1800)
        new_db = Path("/var/lib/aide/aide.db.new")
        if new_db.exists():
            shutil.move(str(new_db), str(db))
            ok("AIDE-Datenbank initialisiert")
            Stats.fix_count += 1
        elif db.exists():
            ok("AIDE-Datenbank initialisiert")
            Stats.fix_count += 1
        else:
            fail("AIDE-Initialisierung fehlgeschlagen")
    info("Täglicher Check via /etc/cron.daily/aide (Paket aide-common).")


# ─── MODUL: Nginx ────────────────────────────────────────────
def audit_nginx(config, apply=False, force=False):
    header("MODUL: Nginx-Härtung (Audit)")
    cfg = config.get("nginx", {})
    if not cfg.get("enabled", True):
        info("Nginx-Modul deaktiviert")
        return

    if not shutil.which("nginx"):
        info("Nginx nicht installiert - überspringe")
        return

    nginx_conf = run("cat /etc/nginx/nginx.conf 2>/dev/null") or ""

    sub("Nginx Grundeinstellungen")
    expected = cfg.get("expected_settings", {})
    for key, value in expected.items():
        pattern = rf"^\s*{key}\s+(.+);"
        match = re.search(pattern, nginx_conf, re.MULTILINE)
        if match:
            current = match.group(1).strip()
            if current == value:
                ok(f"{key}: {current}")
                Stats.ok_count += 1
            else:
                warn(f"{key}: {current} (empfohlen: {value})")
                Stats.warn_count += 1
        else:
            fail(f"{key}: nicht gefunden")
            Stats.fail_count += 1

    # Security-Headers prüfen (nginx.conf + conf.d/*.conf + includes)
    sub("Security-Headers (Empfehlungen)")
    headers = cfg.get("security_headers", {})

    # Collect all nginx configuration content
    all_content = nginx_conf
    vhost_dir = Path("/etc/nginx/conf.d/")
    if vhost_dir.exists():
        for f in vhost_dir.glob("*.conf"):
            all_content += f.read_text()
    # Also check common include directories
    for include_dir in [Path("/etc/nginx/snippets/"), Path("/etc/nginx/nginxconfig.io/")]:
        if include_dir.exists():
            for f in include_dir.glob("*.conf"):
                all_content += f.read_text()

    if not all_content.strip():
        warn("Keine Nginx-Konfiguration gefunden")
    else:
        for header_name, header_value in headers.items():
            if header_name.lower() in all_content.lower():
                ok(f"Header '{header_name}' gefunden")
                Stats.ok_count += 1
            else:
                warn(f"Header '{header_name}' NICHT gefunden")
                Stats.warn_count += 1

    # Nginx bindet nicht auf 0.0.0.0?
    sub("Nginx Listen-Adressen")
    ss_output = run("ss -tlnp | grep nginx")
    if ss_output:
        for line in ss_output.splitlines():
            # Match IPv4 (1.2.3.4:80, 0.0.0.0:80, *:80) and IPv6 ([::1]:80, [::]:80)
            match = re.search(r"(?:\[([^\]]+)\]|(\d+\.\d+\.\d+\.\d+|\*)):(\d+)", line)
            if match:
                addr = match.group(1) or match.group(2)  # group(1)=IPv6, group(2)=IPv4
                port = match.group(3)
                if addr in ("0.0.0.0", "*", "::", "0.0.0.0%lo"):
                    warn(f"Nginx auf {addr}:{port} - besser auf spezifische IP binden")
                    Stats.warn_count += 1
                elif addr in ("::1", "127.0.0.1"):
                    ok(f"Nginx auf [{addr}]:{port} - nur lokal")
                    Stats.ok_count += 1
                else:
                    ok(f"Nginx auf {addr}:{port}")
                    Stats.ok_count += 1


# ─── MODUL: Offene Ports ─────────────────────────────────────
def audit_open_ports(config, apply=False, force=False):
    header("MODUL: Offene Ports Übersicht")

    sub("Auf allen Interfaces lauschende Ports")
    ss_output = run("ss -tlnp")
    if not ss_output:
        warn("Kann offene Ports nicht ermitteln")
        return

    for line in ss_output.splitlines()[1:]:  # Header überspringen
        # Match IPv4 (1.2.3.4:80, 0.0.0.0:80, *:80) and IPv6 ([::1]:80, [::]:80)
        match = re.search(r"(?:\[([^\]]+)\]|(\d+\.\d+\.\d+\.\d+|\*)):(\d+)", line)
        if match:
            addr = match.group(1) or match.group(2)  # group(1)=IPv6, group(2)=IPv4
            port = match.group(3)

            # Prozess
            proc_match = re.search(r'users:\(\("([^"]+)"', line)
            proc = proc_match.group(1) if proc_match else "unbekannt"

            if addr in ("0.0.0.0", "*", "::", "0.0.0.0%lo"):
                if port in ("80", "443"):
                    ok(f"0.0.0.0:{port} ({proc}) - öffentlich erwartet")
                elif port == str(config.get("ssh", {}).get("port", 22)):
                    ok(f"0.0.0.0:{port} ({proc}) - SSH (IP-beschränkt via UFW)")
                else:
                    warn(f"0.0.0.0:{port} ({proc}) - prüfen ob nötig")
                    Stats.warn_count += 1
            elif addr in ("::1", "127.0.0.1"):
                ok(f"{addr}:{port} ({proc}) - nur lokal")
                Stats.ok_count += 1
            else:
                # Specific IP binding (e.g. public IP for nginx)
                if port in ("80", "443"):
                    ok(f"{addr}:{port} ({proc}) - öffentlich erwartet")
                else:
                    ok(f"{addr}:{port} ({proc}) - spezifische IP")
                Stats.ok_count += 1


# ─── HAUPTPROGRAMM ───────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Server-Härtungs-Skript — prüft (Audit) und härtet (--apply) einen "
                    "Debian-Server. Alle Werte stammen aus hardening_config.yaml; "
                    "sensible Werte (IPs, SSH-Port) aus einer .env-Datei.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
AUDIT vs. APPLY
  Ohne --apply  : reiner Dry-Run, es wird NICHTS verändert (nur geprüft/berichtet).
  Mit  --apply  : Dateien werden geändert. Vor jeder Änderung wird ein Backup
                  angelegt: <datei>.backup_YYYYMMDD_HHMMSS

WAS JEDES MODUL ÄNDERT (Datei, die mit --apply geschrieben wird)
  ufw            UFW-Firewall: Default-Policies + Regeln (public/restricted Ports).
  fail2ban       /etc/fail2ban/jail.local (Vollersetzung) + Service-Neustart.
                 Jails mit fehlendem logpath werden automatisch deaktiviert.
  ssh            /etc/ssh/sshd_config — lockout-sicher: Kandidat wird per
                 'sshd -t' geprüft und erst dann ATOMAR ersetzt + reload.
  sysctl         /etc/sysctl.d/99-hardening.conf (+ sofort via 'sysctl -w').
  kernel_modules /etc/modprobe.d/hardening-blacklist.conf (selten genutzte
                 Netzprotokolle/Dateisysteme); lädt sie nicht mehr.
  docker         /etc/docker/daemon.json (Merge, KEIN Auto-Neustart!).
                 Defektes daemon.json => Apply wird übersprungen (kein Datenverlust).
  auto_updates   unattended-upgrades + /etc/apt/apt.conf.d/{20auto-upgrades,
                 52unattended-upgrades-hardening} (Auto-Reboot-Fenster).
  auditd         /etc/audit/rules.d/hardening.rules + Service (auditd).
  aide           Installiert AIDE + initialisiert /var/lib/aide/aide.db (dauert lange).
  nginx          NUR Audit (schreibt nichts).
  ports          NUR Audit: listet offene Ports via 'ss -tlnp'.

WIE SICH DIE .env AUSWIRKT
  Fundorte (in dieser Reihenfolge):
    1. /root/.config/myodoo-docker/.env   (primär)
    2. <skriptverzeichnis>/.env            (Legacy-Fallback)
  Beim ersten Lauf wird .env.example ins zentrale Verzeichnis (Modus 0700) kopiert.

  Verwendete Variablen:
    SSH_PORT (Pflicht)        -> füllt ${SSH_PORT} (Modul ssh + sshd-Jail).
    ALLOWED_IP_<n> (dynamisch)-> beliebig viele: ALLOWED_IP_1, ALLOWED_IP_2, ...
                                 (+ optional ALLOWED_IP_<n>_COMMENT). Werden zur
                                 Laufzeit eingelesen und bestimmen:
                                   - die erlaubten Quell-IPs (UFW restricted_ports)
                                   - die fail2ban ignoreip-Liste
                                 KEIN fester Slot-Zähler; eine 6. IP = ALLOWED_IP_6.

  Sonderfälle:
    - .env fehlt / python-dotenv fehlt  -> Warnung; es werden nur bereits in der
      Shell exportierte Variablen gesehen.
    - nicht gesetzte/leere ALLOWED_IP_<n> -> werden ignoriert (Lücken erlaubt);
      0..N IPs möglich. ACHTUNG: keine IP gesetzt = KEINE IP-Beschränkung.
    - fehlendes/ungültiges SSH_PORT     -> Validierungsfehler => ABBRUCH (kein Apply).

SICHERHEITSHINWEISE
  - SSH-Reload erfolgt NUR nach erfolgreichem 'sshd -t' (kein Lockout durch Tippfehler).
  - Docker wird NIE automatisch neugestartet (würde alle Container stoppen).
  - Empfohlene Apply-Reihenfolge: erst unkritische Module, 'ssh' zuletzt mit einer
    zweiten offenen SSH-Sitzung als Sicherheitsnetz.

Beispiele:
  sudo python3 server_hardening.py                              # Audit (alles)
  sudo python3 server_hardening.py --apply                      # Alles härten
  sudo python3 server_hardening.py --apply -m sysctl kernel_modules auto_updates
  sudo python3 server_hardening.py --apply -m ssh               # SSH zuletzt
        """
    )
    parser.add_argument("-c", "--config", default="hardening_config.yaml",
                        help="YAML-Konfiguration (default: hardening_config.yaml)")
    parser.add_argument("-a", "--apply", action="store_true",
                        help="Änderungen anwenden")
    parser.add_argument("-f", "--force", action="store_true",
                        help="Keine Rückfragen")
    parser.add_argument("-m", "--module", nargs="+",
                        choices=["ufw", "fail2ban", "ssh", "sysctl", "kernel_modules",
                                 "docker", "auto_updates", "auditd", "aide", "nginx", "ports"],
                        help="Nur bestimmte Module ausführen")
    args = parser.parse_args()

    # Root-Check
    if os.geteuid() != 0:
        print(f"{C.FAIL}Fehler: Root-Rechte erforderlich.{C.END}")
        sys.exit(1)

    # Load .env (python-dotenv optional)
    # Primary: /root/.config/myodoo-docker/.env
    # Fallback: scripts/.env (legacy, same directory as this script)
    script_dir = Path(__file__).resolve().parent
    central_dir = Path("/root/.config/myodoo-docker")
    central_env = central_dir / ".env"
    example_env = script_dir / ".env.example"

    # Ensure central config directory exists and seed .env.example
    if not central_dir.exists():
        central_dir.mkdir(parents=True, mode=0o700)
        info(f"Verzeichnis erstellt: {central_dir}")
    if example_env.exists() and not (central_dir / ".env.example").exists():
        shutil.copy2(example_env, central_dir / ".env.example")
        info(f".env.example kopiert nach {central_dir}")
    if not central_env.exists():
        warn(f"Keine .env gefunden in {central_dir}")
        warn(f"Vorlage anpassen: cp {central_dir / '.env.example'} {central_env}")

    env_candidates = [central_env, script_dir / ".env"]
    env_loaded = False
    for env_path in env_candidates:
        if env_path.exists():
            if load_dotenv is not None:
                load_dotenv(env_path)
                info(f".env geladen: {env_path}")
                env_loaded = True
            else:
                warn("python-dotenv nicht installiert - .env wird ignoriert")
                warn("Installation: pip install python-dotenv")
            break
    if not env_loaded and load_dotenv is not None:
        warn("Keine .env gefunden. Erwartet: /root/.config/myodoo-docker/.env")

    # Prerequisites check
    prereq_warnings = check_prerequisites()
    for w in prereq_warnings:
        warn(w)

    # Config laden
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = script_dir / config_path
    config = yaml.safe_load(config_path.read_text())

    # Resolve ${ENV_VAR} placeholders (e.g. ${SSH_PORT})
    config = resolve_env_vars(config)

    # Build the admin-IP allowlist dynamically from ALLOWED_IP_<n> env vars
    # (any count) and inject it BEFORE validation so those IPs get validated too.
    allowed_ips = inject_allowed_ips(config)
    if allowed_ips:
        info(f"Allowlist: {len(allowed_ips)} IP(s) aus .env erkannt "
             f"({', '.join(a['ip'] for a in allowed_ips)})")
    else:
        warn("Keine ALLOWED_IP_<n> in .env gefunden — eine aktivierte UFW würde den "
             "SSH-Port für NIEMANDEN öffnen (Lockout-Gefahr)!")

    # Validate config
    validation_errors = validate_config(config)
    if validation_errors:
        print(f"\n{C.FAIL}Konfigurationsfehler:{C.END}")
        for err in validation_errors:
            fail(err)
        sys.exit(1)

    print(f"\n{C.BOLD}{'='*60}")
    print(f"  Server-Härtung v1.3.0 {'(APPLY)' if args.apply else '(AUDIT)'}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}{C.END}")

    if not args.apply:
        info("Dry-Run Modus - keine Änderungen")
        info("Mit --apply ausführen um zu härten\n")

    modules = {
        "ufw":            audit_ufw,
        "fail2ban":       audit_fail2ban,
        "ssh":            audit_ssh,
        "sysctl":         audit_sysctl,
        "kernel_modules": audit_kernel_modules,
        "docker":         audit_docker,
        "auto_updates":   audit_auto_updates,
        "auditd":         audit_auditd,
        "aide":           audit_aide,
        "nginx":          audit_nginx,
        "ports":          audit_open_ports,
    }

    selected = args.module or list(modules.keys())

    for mod_name in selected:
        if mod_name in modules:
            modules[mod_name](config, apply=args.apply, force=args.force)

    # Zusammenfassung
    header("ZUSAMMENFASSUNG")
    print(f"  {C.OK}✓ OK:        {Stats.ok_count}{C.END}")
    print(f"  {C.WARN}⚠ Warnungen: {Stats.warn_count}{C.END}")
    print(f"  {C.FAIL}✗ Fehler:    {Stats.fail_count}{C.END}")
    if args.apply:
        print(f"  {C.INFO}⚡ Fixes:     {Stats.fix_count}{C.END}")

    if Stats.fail_count > 0 and not args.apply:
        print(f"\n  {C.WARN}Starte mit --apply um die Fehler zu beheben.{C.END}")

    print()


if __name__ == "__main__":
    main()
