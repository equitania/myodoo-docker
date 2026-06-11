#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Title:            nginx-cert-guard.py
# Description:      Keep nginx up when a single customer vhost breaks, and warn
#                   early when a (sub)domain stops pointing at this server.
# Version:          1.1.0
# Date:             11.06.2026
# Author:           Equitania Software GmbH
# ==============================================================================
# Why this exists:
#   nginx is "all or nothing": one broken server block (missing ssl_certificate
#   file, or an old `listen <domain>:443` whose hostname no longer resolves) makes
#   `nginx -t` fail and blocks the WHOLE server from starting. A customer changing
#   their DNS away from us could therefore take every site on the host offline.
#
# What it does:
#   --reconcile [--start]  Reactive safety net (the must-have): if `nginx -t` fails,
#                          quarantine the offending vhost file(s) until nginx tests
#                          clean, then start. Mass-failure guard with rollback so a
#                          global fault (e.g. /etc/letsencrypt gone) never causes a
#                          blind shutdown of every customer.
#   --check [--apply]      Proactive early warning: resolve each active vhost's
#                          domain via DNS; if it no longer points at this server for
#                          GUARD_FAIL_THRESHOLD consecutive runs, quarantine it
#                          (only with --apply) and alert. Confirmation counter guards
#                          against DNS glitches / Cloudflare-fronted domains.
#   --list                 Show active and quarantined vhosts.
#   --restore <domain>     Re-enable a quarantined vhost after the cause is fixed.
#   --dry-run              Report only; make no changes (reconcile + check).
#
# Quarantine mechanism: rename `<domain>.conf` -> `<domain>.conf.disabled`. nginx
# includes only `*.conf`, so the vhost stops loading; fully reversible.
#
# Configuration (read from /root/.config/myodoo-docker/.env; see .env.example):
#   ALERT_EMAIL_TO/FROM, ALERT_SMTP_HOST/PORT/USER/PASS/TLS  (smtplib alert mail)
#   GUARD_SERVER_IPS       comma list of this host's public IPs (empty = autodetect)
#   GUARD_IGNORE_DOMAINS   comma list never auto-disabled (e.g. Cloudflare-fronted)
#   GUARD_FAIL_THRESHOLD   confirmed failing runs before disabling (default 3)
#   GUARD_MAX_DISABLE      mass-failure guard: max vhosts to disable per run (default 5)
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
###############################################################################

import argparse
import ipaddress
import json
import logging
import os
import re
import shutil
import smtplib
import socket
import subprocess
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is optional
    load_dotenv = None

# ─── Defaults ────────────────────────────────────────────────
DEFAULT_CONF_DIR = "/etc/nginx/conf.d"
DEFAULT_STATE_FILE = "/var/lib/nginx-cert-guard/state.json"
# Never touch the SNI catch-all or other non-customer infrastructure vhosts.
SKIP_FILES = {"00-default.conf"}

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("nginx-cert-guard")


# ─── Configuration / .env ────────────────────────────────────
def load_environment():
    """Load .env from the standard locations (mirrors container2backup.py)."""
    if load_dotenv is None:
        logger.warning("python-dotenv not installed — only shell env vars are seen.")
        return
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in ("/root/.config/myodoo-docker/.env",
                      os.path.join(here, ".env")):
        if os.path.exists(candidate):
            load_dotenv(candidate)
            return
    load_dotenv()  # CWD fallback


def cfg(key, default=""):
    return os.getenv(key, default)


def cfg_int(key, default):
    try:
        return int(os.getenv(key, "") or default)
    except (TypeError, ValueError):
        return default


def cfg_list(key):
    return [v.strip() for v in (os.getenv(key, "") or "").split(",") if v.strip()]


# ─── Shell helpers (list-form, never shell=True) ─────────────
def run(cmd, timeout=30):
    """Run a command list; return (returncode, stdout+stderr)."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, check=False)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError:
        return 127, f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"timeout: {' '.join(cmd)}"


def have(binary):
    return shutil.which(binary) is not None


def nginx_test():
    """Return (ok, output) of `nginx -t`."""
    rc, out = run(["nginx", "-t"])
    return rc == 0, out.strip()


def nginx_running():
    rc, _ = run(["systemctl", "is-active", "--quiet", "nginx"])
    return rc == 0


def nginx_start_or_reload():
    if nginx_running():
        rc, out = run(["systemctl", "reload", "nginx"])
        action = "reload"
    else:
        rc, out = run(["systemctl", "start", "nginx"])
        action = "start"
    if rc == 0:
        logger.info("nginx %s succeeded.", action)
    else:
        logger.error("nginx %s failed: %s", action, out.strip())
    return rc == 0


# ─── vhost parsing ───────────────────────────────────────────
_CERT_RE = re.compile(r"^\s*ssl_certificate(?:_key)?\s+([^;]+);", re.MULTILINE)
_LISTEN_RE = re.compile(r"^\s*listen\s+([^;]+);", re.MULTILINE)
_SERVER_NAME_RE = re.compile(r"^\s*server_name\s+([^;]+);", re.MULTILINE)


def active_vhosts(conf_dir):
    """Active customer vhost .conf files (skipping infrastructure files)."""
    d = Path(conf_dir)
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("*.conf") if p.name not in SKIP_FILES)


def quarantined_vhosts(conf_dir):
    d = Path(conf_dir)
    if not d.is_dir():
        return []
    return sorted(d.glob("*.conf.disabled"))


def domain_of(conf_path):
    """Domain for a vhost: prefer server_name, fall back to the filename."""
    name = conf_path.name
    for suffix in (".conf.disabled", ".conf"):
        if name.endswith(suffix):
            fname_domain = name[: -len(suffix)]
            break
    else:
        fname_domain = name
    try:
        text = conf_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return fname_domain
    m = _SERVER_NAME_RE.search(text)
    if m:
        first = m.group(1).split()[0].strip()
        if first and first != "_":
            return first
    return fname_domain


def missing_cert_files(conf_path):
    """Return the list of referenced ssl_certificate paths that do not exist."""
    try:
        text = conf_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    missing = []
    for raw in _CERT_RE.findall(text):
        path = raw.strip().strip('"').strip("'")
        if path and not os.path.exists(path):
            missing.append(path)
    return missing


def unresolvable_listen_host(conf_path):
    """Pattern-A guard: `listen <hostname>:port` whose hostname no longer resolves.

    A hostname in a listen directive must resolve at nginx start or the socket
    bind fails and takes down the whole server. IP-bound listens are fine.
    """
    try:
        text = conf_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for raw in _LISTEN_RE.findall(text):
        token = raw.strip().split()[0]  # e.g. "1.2.3.4:443" / "example.de:443" / "443"
        host = token.rsplit(":", 1)[0] if ":" in token else ""
        if not host or host in ("[::]", "*"):
            continue
        # IPv6 literals are bracketed ([::1]:443) - strip for parsing, else
        # a healthy local IPv6 listener would be flagged as unresolvable
        host = host.strip("[]")
        if not host:
            continue
        # Skip plain IP literals (those always "resolve").
        try:
            ipaddress.ip_address(host)
            continue
        except ValueError:
            pass
        try:
            socket.getaddrinfo(host, None)
        except socket.gaierror:
            return host  # hostname no longer resolves
    return None


def detect_broken(conf_dir):
    """Deterministic, file-based detection of vhosts that will break nginx start.

    Returns list of (path, reason). Pure (no nginx needed) — used by --dry-run too.
    """
    broken = []
    for vh in active_vhosts(conf_dir):
        missing = missing_cert_files(vh)
        if missing:
            broken.append((vh, f"missing cert file(s): {', '.join(missing)}"))
            continue
        bad_host = unresolvable_listen_host(vh)
        if bad_host:
            broken.append((vh, f"listen hostname does not resolve: {bad_host}"))
    return broken


# ─── quarantine / restore ────────────────────────────────────
def disable_vhost(conf_path, dry_run=False):
    target = conf_path.with_name(conf_path.name + ".disabled")
    if dry_run:
        logger.info("[dry-run] would disable %s -> %s", conf_path.name, target.name)
        return target
    conf_path.rename(target)
    logger.info("Disabled %s -> %s", conf_path.name, target.name)
    return target


def restore_vhost(disabled_path, dry_run=False):
    if disabled_path.name.endswith(".conf.disabled"):
        target = disabled_path.with_name(disabled_path.name[: -len(".disabled")])
    else:
        target = disabled_path.with_suffix("")
    if dry_run:
        logger.info("[dry-run] would restore %s -> %s", disabled_path.name, target.name)
        return target
    disabled_path.rename(target)
    logger.info("Restored %s -> %s", disabled_path.name, target.name)
    return target


# ─── server IPs & DNS ────────────────────────────────────────
def server_ips():
    """This host's public IPs: explicit GUARD_SERVER_IPS, else autodetect."""
    explicit = cfg_list("GUARD_SERVER_IPS")
    if explicit:
        return set(explicit)
    ips = set()
    rc, out = run(["ip", "-o", "addr", "show", "scope", "global"])
    if rc == 0:
        for tok in re.findall(r"inet6?\s+([0-9a-fA-F:.]+)/\d+", out):
            ips.add(tok)
    # Public IP via OpenDNS (uses dig, same pattern as dns_optimizer.py).
    if have("dig"):
        rc, out = run(["dig", "+short", "+time=3", "myip.opendns.com",
                      "@resolver1.opendns.com"])
        if rc == 0:
            for line in out.split():
                line = line.strip()
                try:
                    ipaddress.ip_address(line)
                    ips.add(line)
                except ValueError:
                    pass
    return ips


def resolve_domain(domain):
    """Resolve A + AAAA for domain. Returns (resolved_ok, set_of_ips)."""
    ips = set()
    resolved = False
    if have("dig"):
        for rtype in ("A", "AAAA"):
            rc, out = run(["dig", "+short", "+time=3", rtype, domain])
            if rc == 0:
                for line in out.split():
                    line = line.strip()
                    try:
                        ipaddress.ip_address(line)
                        ips.add(line)
                        resolved = True
                    except ValueError:
                        pass
        return resolved, ips
    # Fallback without dig.
    try:
        for res in socket.getaddrinfo(domain, None):
            ips.add(res[4][0])
        resolved = bool(ips)
    except socket.gaierror:
        resolved = False
    return resolved, ips


# ─── state file (for --check confirmation counter) ───────────
def load_state(state_file):
    try:
        return json.loads(Path(state_file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state_file, state, dry_run=False):
    if dry_run:
        return
    p = Path(state_file)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    except OSError as err:
        logger.warning("Could not write state file %s: %s", state_file, err)


# ─── email alert ─────────────────────────────────────────────
def send_alert(subject, body):
    to_addr = cfg("ALERT_EMAIL_TO")
    host = cfg("ALERT_SMTP_HOST")
    if not to_addr or not host:
        logger.warning("Alert email not configured (ALERT_EMAIL_TO/ALERT_SMTP_HOST) "
                       "— skipping mail. Subject was: %s", subject)
        return False
    from_addr = cfg("ALERT_EMAIL_FROM") or f"nginx-cert-guard@{socket.gethostname()}"
    port = cfg_int("ALERT_SMTP_PORT", 587)
    tls = (cfg("ALERT_SMTP_TLS", "starttls") or "starttls").lower()
    user = cfg("ALERT_SMTP_USER")
    password = cfg("ALERT_SMTP_PASS")

    msg = EmailMessage()
    msg["Subject"] = f"[nginx-cert-guard] {socket.gethostname()}: {subject}"
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)

    try:
        if tls == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
        with server:
            server.ehlo()
            if tls == "starttls":
                server.starttls()
                server.ehlo()
            if user:
                server.login(user, password)
            server.send_message(msg)
        logger.info("Alert mail sent to %s.", to_addr)
        return True
    except (smtplib.SMTPException, OSError) as err:
        logger.error("Failed to send alert mail: %s", err)
        return False


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ─── mode: reconcile ─────────────────────────────────────────
def mode_reconcile(args):
    """Bring nginx into a runnable state, quarantining broken vhosts if needed."""
    conf_dir = args.nginx_conf_dir
    dry = args.dry_run
    max_disable = cfg_int("GUARD_MAX_DISABLE", 5)

    if not have("nginx"):
        logger.error("nginx binary not found — cannot reconcile.")
        return 1

    ok, out = nginx_test()
    if ok:
        logger.info("nginx config is valid — nothing to isolate.")
        if args.start and not dry:
            nginx_start_or_reload()
        return 0

    logger.warning("nginx -t FAILED. Detecting broken vhosts...\n%s", out)

    # Phase 1: deterministic, file-based candidates.
    candidates = detect_broken(conf_dir)
    total_active = len(active_vhosts(conf_dir))

    if dry:
        if candidates:
            logger.info("[dry-run] would quarantine %d vhost(s):", len(candidates))
            for path, reason in candidates:
                logger.info("[dry-run]   %s — %s", path.name, reason)
        else:
            logger.info("[dry-run] no file-based candidates found; iterative "
                        "isolation would be needed (requires a real run).")
        return 0

    # Mass-failure guard up front: too many candidates means a global fault
    # (letsencrypt gone, nginx.conf error) — do NOT shut down half the host.
    if len(candidates) > max_disable:
        body = (f"nginx -t failed and {len(candidates)} vhosts look broken "
                f"(limit GUARD_MAX_DISABLE={max_disable}). This points at a global "
                f"fault, not individual customers. NOTHING was disabled.\n\n"
                f"nginx -t output:\n{out}\n\nCandidates:\n"
                + "\n".join(f"  {p.name}: {r}" for p, r in candidates))
        logger.error("Mass failure (%d candidates > limit %d) — escalating, no changes.",
                     len(candidates), max_disable)
        send_alert("MASS FAILURE — manual intervention required", body)
        return 2

    disabled = []  # (quarantined_path, domain, reason)
    for path, reason in candidates:
        qpath = disable_vhost(path, dry_run=False)
        disabled.append((qpath, domain_of(qpath), reason))

    ok, out = nginx_test()

    # Phase 2: iterative isolation for faults not detectable from files (syntax).
    while not ok and len(disabled) < max_disable:
        remaining = active_vhosts(conf_dir)
        if not remaining:
            break
        victim = remaining[-1]
        qpath = disable_vhost(victim, dry_run=False)
        disabled.append((qpath, domain_of(qpath), "nginx -t failure (isolated iteratively)"))
        ok, out = nginx_test()

    # Still broken (incl. having hit the safety limit) → roll back, escalate.
    if not ok:
        logger.error("Could not reach a clean config within the safety limit — "
                     "rolling back this run's changes.")
        # Match by exact path - matching by domain could restore vhosts that
        # were quarantined manually before this run (duplicate server_name).
        rollback_paths = {qp for qp, _, _ in disabled}
        for path in quarantined_vhosts(conf_dir):
            # Only roll back files we just disabled this run.
            if path in rollback_paths:
                restore_vhost(path, dry_run=False)
        body = (f"nginx could not be brought up safely. Rolled back {len(disabled)} "
                f"change(s) to avoid a partial outage. Manual intervention required.\n\n"
                f"Last nginx -t output:\n{out}")
        send_alert("UNRECOVERABLE — rolled back, manual intervention required", body)
        return 3

    # Success.
    if args.start:
        nginx_start_or_reload()
    report = "\n".join(f"  {dom}: {reason}" for _, dom, reason in disabled)
    logger.info("nginx is valid again. Quarantined %d vhost(s):\n%s",
                len(disabled), report)
    if disabled:
        body = (f"To keep nginx running, {len(disabled)} vhost(s) were quarantined "
                f"on {socket.gethostname()} at {_now()}:\n\n{report}\n\n"
                f"They were renamed to <domain>.conf.disabled in {conf_dir}.\n"
                f"After fixing the cause (DNS/cert), re-enable with:\n"
                f"  nginx-cert-guard.py --restore <domain>")
        send_alert(f"{len(disabled)} vhost(s) quarantined to keep nginx up", body)
    return 0


# ─── mode: check (proactive DNS early warning) ───────────────
def mode_check(args):
    conf_dir = args.nginx_conf_dir
    dry = args.dry_run or not args.apply
    threshold = cfg_int("GUARD_FAIL_THRESHOLD", 3)
    max_disable = cfg_int("GUARD_MAX_DISABLE", 5)
    ignore = set(cfg_list("GUARD_IGNORE_DOMAINS"))
    ours = server_ips()
    if not ours:
        logger.error("Could not determine this server's IPs (set GUARD_SERVER_IPS). "
                     "Aborting check to avoid false positives.")
        return 1
    logger.info("Server IPs considered ours: %s", ", ".join(sorted(ours)))

    state = load_state(args.state_file)
    to_disable = []   # (path, domain, detail)
    report_lines = []

    for vh in active_vhosts(conf_dir):
        domain = domain_of(vh)
        if domain in ignore:
            logger.info("Skipping %s (in GUARD_IGNORE_DOMAINS).", domain)
            state.pop(domain, None)
            continue
        resolved, ips = resolve_domain(domain)
        points_here = bool(ips & ours)
        entry = state.get(domain, {"consecutive_failures": 0})
        if points_here:
            if entry.get("consecutive_failures"):
                logger.info("%s points here again — resetting counter.", domain)
            state[domain] = {"consecutive_failures": 0, "last_ok": _now()}
            continue
        # Not pointing here (NXDOMAIN or foreign IP).
        detail = ("does not resolve" if not resolved
                  else f"resolves to {', '.join(sorted(ips))} (not us)")
        fails = entry.get("consecutive_failures", 0) + 1
        state[domain] = {"consecutive_failures": fails, "last_fail": _now(),
                         "last_detail": detail}
        report_lines.append(f"  {domain}: {detail} [{fails}/{threshold}]")
        logger.warning("%s %s [%d/%d]", domain, detail, fails, threshold)
        if fails >= threshold:
            to_disable.append((vh, domain, detail))

    save_state(args.state_file, state, dry_run=dry)

    if not report_lines:
        logger.info("All active vhost domains point at this server.")
        return 0

    # Mass-failure guard (e.g. our own DNS/uplink hiccup affecting everything).
    if len(to_disable) > max_disable:
        body = (f"{len(to_disable)} domains crossed the failure threshold at once "
                f"(limit {max_disable}) — likely a local DNS/network issue, not many "
                f"customers leaving. NOTHING disabled.\n\n" + "\n".join(report_lines))
        logger.error("Mass DNS failure (%d > limit %d) — escalating, no changes.",
                     len(to_disable), max_disable)
        send_alert("MASS DNS FAILURE — manual check required", body)
        return 2

    if to_disable and not dry:
        disabled = []
        for path, domain, detail in to_disable:
            disable_vhost(path, dry_run=False)
            disabled.append(f"  {domain}: {detail}")
            state.pop(domain, None)  # disabled; stop counting
        save_state(args.state_file, state, dry_run=False)
        if have("nginx"):
            ok, _ = nginx_test()
            if ok:
                nginx_start_or_reload()
        body = (f"Proactively quarantined {len(disabled)} vhost(s) on "
                f"{socket.gethostname()} whose domains stopped pointing here for "
                f">= {threshold} runs:\n\n" + "\n".join(disabled)
                + f"\n\nRe-enable after the DNS is fixed:\n"
                f"  nginx-cert-guard.py --restore <domain>")
        send_alert(f"{len(disabled)} domain(s) no longer point here — quarantined", body)
    elif report_lines:
        # Below threshold or dry-run: warn only.
        body = ("Domains not pointing at this server (early warning, no action yet):\n\n"
                + "\n".join(report_lines))
        send_alert("Domain(s) drifting away from this server", body)
    return 0


# ─── mode: list ──────────────────────────────────────────────
def mode_list(args):
    conf_dir = args.nginx_conf_dir
    active = active_vhosts(conf_dir)
    quarantined = quarantined_vhosts(conf_dir)
    print(f"Active vhosts ({len(active)}):")
    for vh in active:
        print(f"  {domain_of(vh)}  [{vh.name}]")
    print(f"\nQuarantined vhosts ({len(quarantined)}):")
    for vh in quarantined:
        print(f"  {domain_of(vh)}  [{vh.name}]")
    return 0


# ─── mode: restore ───────────────────────────────────────────
def mode_restore(args):
    conf_dir = args.nginx_conf_dir
    target = args.restore
    matches = [p for p in quarantined_vhosts(conf_dir)
               if domain_of(p) == target or p.name == f"{target}.conf.disabled"]
    if not matches:
        logger.error("No quarantined vhost found for '%s'.", target)
        return 1
    for path in matches:
        restore_vhost(path, dry_run=args.dry_run)
    if not args.dry_run and have("nginx"):
        ok, out = nginx_test()
        if ok:
            nginx_start_or_reload()
            logger.info("Restored and reloaded.")
        else:
            logger.error("Restored, but nginx -t still fails:\n%s", out)
            return 1
    return 0


# ─── CLI ─────────────────────────────────────────────────────
def build_parser():
    p = argparse.ArgumentParser(
        description="Keep nginx up when a single customer vhost breaks, and warn "
                    "early when a (sub)domain stops pointing at this server.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--reconcile", action="store_true",
                      help="Ensure nginx is runnable; quarantine broken vhost(s).")
    mode.add_argument("--check", action="store_true",
                      help="Proactively check vhost domains via DNS.")
    mode.add_argument("--list", action="store_true",
                      help="List active and quarantined vhosts.")
    mode.add_argument("--restore", metavar="DOMAIN",
                      help="Re-enable a quarantined vhost.")
    p.add_argument("--start", action="store_true",
                   help="With --reconcile: start/reload nginx after reconciling.")
    p.add_argument("--apply", action="store_true",
                   help="With --check: actually disable confirmed-bad vhosts "
                        "(default is warn-only).")
    p.add_argument("--dry-run", action="store_true",
                   help="Report only; make no changes.")
    p.add_argument("--nginx-conf-dir", default=DEFAULT_CONF_DIR,
                   help=f"vhost directory (default {DEFAULT_CONF_DIR}).")
    p.add_argument("--state-file", default=DEFAULT_STATE_FILE,
                   help=f"check-mode state file (default {DEFAULT_STATE_FILE}).")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    load_environment()
    if args.reconcile:
        return mode_reconcile(args)
    if args.check:
        return mode_check(args)
    if args.list:
        return mode_list(args)
    if args.restore:
        return mode_restore(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
