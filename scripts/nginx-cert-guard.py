#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Title:            nginx-cert-guard.py
# Description:      Keep nginx up when a single customer vhost breaks, and warn
#                   early when a (sub)domain stops pointing at this server.
# Version:          1.2.0
# Date:             13.08.2026
# Author:           Equitania Software GmbH
# ==============================================================================
# Why this exists:
#   nginx is "all or nothing": one broken server block (missing ssl_certificate
#   file, or an old `listen <domain>:443` whose hostname no longer resolves) makes
#   `nginx -t` fail and blocks the WHOLE server from starting. A customer changing
#   their DNS away from us could therefore take every site on the host offline.
#
#   v1.2.0 exists because that happened for real (13.08.2026): a customer moved
#   one A record to another provider, and all ten vhosts on the host went down
#   with it. The listen hostname still resolved perfectly — just to somebody
#   else's IP — so the "does it resolve" test saw nothing, and nginx died with
#   `bind() to <foreign-ip>:443 failed (99: Cannot assign requested address)`.
#   Resolvability was never the property that mattered; bindability is.
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
#                          EXCEPTION (v1.2.0): a domain that also appears in a
#                          `listen` directive is acted on at the FIRST failing run.
#                          Confirm-and-wait is right for a customer drifting away —
#                          it is wrong when the same DNS record decides whether
#                          nginx can bind at all, because then every day of waiting
#                          is a day the whole host is one reload from going dark.
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


def listen_hosts(conf_path):
    """Host part of every `listen` directive in a vhost, wildcards excluded.

    `listen 443 ssl;`, `listen 0.0.0.0:443;` and `listen [::]:443;` bind every
    interface and carry no host that could point at the wrong machine, so they
    are not returned. Order is preserved and duplicates are dropped.
    """
    try:
        text = conf_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    hosts = []
    for raw in _LISTEN_RE.findall(text):
        token = raw.strip().split()[0]  # "1.2.3.4:443" / "example.de:443" / "443"
        if ":" not in token:
            continue  # bare port -> wildcard bind
        # IPv6 literals are bracketed ([::1]:443) — strip for parsing, else a
        # healthy local IPv6 listener would look like a hostname.
        host = token.rsplit(":", 1)[0].strip("[]")
        if not host or host in ("*", "0.0.0.0", "::"):
            continue
        if host not in hosts:
            hosts.append(host)
    return hosts


def unbindable_listen_target(conf_path, local_ips):
    """Pattern-A guard: a `listen` target this host cannot bind().

    nginx resolves a hostname in `listen` at config-parse time and then binds
    the resulting address, so BOTH of these kill the whole server rather than
    just this vhost:

      * the hostname no longer resolves at all
            nginx: [emerg] host not found in "..." of the "listen" directive
      * the hostname — or a hardcoded IP — points at an address that is not
        assigned to this machine
            nginx: [emerg] bind() to <ip>:443 failed
                   (99: Cannot assign requested address)

    Until v1.2.0 only the first case was checked, and IP literals were skipped
    outright on the reasoning that "those always resolve". They do; resolving
    was simply never the property that mattered. The second case is what took a
    ten-vhost host offline on 13.08.2026 — the name resolved fine, just not to
    us — and it is invisible to a resolvability test by construction.

    Args:
        conf_path: The vhost file to inspect.
        local_ips: Addresses currently assigned to this host, from
            local_bound_ips(). An EMPTY set means "could not determine", and
            the bindability half is then skipped entirely — an unreadable
            `ip addr` must never make every vhost on the box look broken.

    Returns:
        (host, reason) for the first offending target, or None.
    """
    for host in listen_hosts(conf_path):
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            # IP literal: nothing to resolve, it is bindable or it is not.
            if local_ips and host not in local_ips:
                return host, (
                    f"listen IP {host} is not assigned to this host — nginx "
                    f"would fail with 'Cannot assign requested address'"
                )
            continue

        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return host, f"listen hostname does not resolve: {host}"

        if not local_ips:
            continue
        resolved = {info[4][0] for info in infos}
        if not resolved & local_ips:
            return host, (
                f"listen hostname {host} resolves to "
                f"{', '.join(sorted(resolved))} — not an address of this host"
            )
    return None


def detect_broken(conf_dir, local_ips=None):
    """Deterministic, file-based detection of vhosts that will break nginx start.

    Args:
        conf_dir: Directory holding the vhost files.
        local_ips: Pre-computed result of local_bound_ips(). Passed in by
            callers that check several vhosts so `ip addr` runs once; computed
            here when omitted.

    Returns list of (path, reason). Pure (no nginx needed) — used by --dry-run too.
    """
    if local_ips is None:
        local_ips = local_bound_ips()
    broken = []
    for vh in active_vhosts(conf_dir):
        missing = missing_cert_files(vh)
        if missing:
            broken.append((vh, f"missing cert file(s): {', '.join(missing)}"))
            continue
        bad = unbindable_listen_target(vh, local_ips)
        if bad:
            broken.append((vh, bad[1]))
    return broken


def shared_cause(candidates):
    """The single reason behind every candidate, or None if they differ.

    Ten vhosts failing for ten different reasons is ten problems; ten failing
    for one reason is one problem wearing ten hats, and the alert should say
    which it is.
    """
    reasons = {reason for _, reason in candidates}
    return reasons.pop() if len(reasons) == 1 else None


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
def local_bound_ips():
    """Addresses actually assigned to this host — the set nginx can bind() to.

    Deliberately NOT server_ips(). That one answers "is this domain still
    ours?" and therefore folds in the public address seen from the outside,
    which behind NAT is precisely the address that cannot be bound locally.
    Bindability is a purely local question, so only addresses present on an
    interface count here — including loopback and the docker bridges, which
    nginx may legitimately bind.

    GUARD_SERVER_IPS is intentionally ignored: it exists so an operator can
    declare which public IPs are "ours", not to override what the kernel
    reports about its own interfaces.

    Returns:
        Set of address strings; EMPTY when it could not be determined. Callers
        must treat empty as "unknown" and skip the check — never as "nothing
        is bindable", which would condemn every vhost on the host.
    """
    ips = set()
    rc, out = run(["ip", "-o", "addr", "show"])
    if rc == 0:
        for tok in re.findall(r"inet6?\s+([0-9a-fA-F:.]+)/\d+", out):
            ips.add(tok)
    if not ips:
        logger.warning("Could not determine this host's local addresses — "
                       "listen-bindability checks are skipped this run.")
    return ips


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
    #
    # "Every active vhost is a candidate" is treated the same way even when the
    # host has fewer vhosts than GUARD_MAX_DISABLE. A three-vhost server whose
    # own IP changed would otherwise slip under the numeric limit and get
    # emptied out one file at a time — the count was never the signal, the
    # scope is: a fault under ALL of them is one fault, not many customers.
    global_fault = bool(candidates) and len(candidates) == total_active
    if len(candidates) > max_disable or global_fault:
        cause = shared_cause(candidates)
        scope = ("EVERY active vhost" if global_fault
                 else f"{len(candidates)} of {total_active} vhosts")
        body = (f"nginx -t failed and {scope} looks broken "
                f"(limit GUARD_MAX_DISABLE={max_disable}). This points at a global "
                f"fault, not individual customers. NOTHING was disabled.\n\n"
                + (f"All candidates share one cause:\n  {cause}\n\n" if cause else "")
                + f"nginx -t output:\n{out}\n\nCandidates:\n"
                + "\n".join(f"  {p.name}: {r}" for p, r in candidates))
        logger.error("Mass failure (%d candidate(s), %d active, limit %d) — "
                     "escalating, no changes.",
                     len(candidates), total_active, max_disable)
        if cause:
            logger.error("Shared cause across all candidates: %s", cause)
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

        # A domain that also appears in a `listen` directive is not a soft
        # drift. nginx resolves listen targets at config-parse time, so from
        # the moment that record points elsewhere the host is one reload away
        # from total darkness — every other customer on the box included.
        # Confirm-and-wait is the right instinct for "is this customer leaving
        # us?", and the wrong one for "can nginx still start?": each extra day
        # of confirmation buys certainty about a departure while risking the
        # whole server. So listen-bound domains act on the first failing run.
        listen_bound = domain in listen_hosts(vh)
        effective_threshold = 1 if listen_bound else threshold
        if listen_bound:
            detail += " [listen-bound: whole-host outage risk]"

        fails = entry.get("consecutive_failures", 0) + 1
        state[domain] = {"consecutive_failures": fails, "last_fail": _now(),
                         "last_detail": detail}
        report_lines.append(f"  {domain}: {detail} [{fails}/{effective_threshold}]")
        logger.warning("%s %s [%d/%d]", domain, detail, fails, effective_threshold)
        if fails >= effective_threshold:
            to_disable.append((vh, domain, detail))

    save_state(args.state_file, state, dry_run=dry)

    if not report_lines:
        logger.info("All active vhost domains point at this server.")
        return 0

    # Mass-failure guard (e.g. our own DNS/uplink hiccup affecting everything).
    # As in mode_reconcile, "all of them" counts as a mass failure even on a
    # host with fewer vhosts than the numeric limit: emptying a server
    # completely is never the proportionate response to a DNS reading.
    total_active = len(active_vhosts(conf_dir))
    would_empty_host = bool(to_disable) and len(to_disable) == total_active
    if len(to_disable) > max_disable or would_empty_host:
        scope = ("EVERY active domain" if would_empty_host
                 else f"{len(to_disable)} domains")
        body = (f"{scope} crossed the failure threshold at once "
                f"(limit {max_disable}) — likely a local DNS/network issue, not many "
                f"customers leaving. NOTHING disabled.\n\n" + "\n".join(report_lines))
        logger.error("Mass DNS failure (%d of %d active, limit %d) — "
                     "escalating, no changes.",
                     len(to_disable), total_active, max_disable)
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
