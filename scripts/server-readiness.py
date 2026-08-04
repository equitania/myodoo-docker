#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Title:            server-readiness.py
# Description:      Report whether this server matches the state myodoo-docker
#                   expects, and name the exact command that closes each gap.
# Version:          1.1.1
# Date:             04.08.2026
# Author:           Equitania Software GmbH
# ==============================================================================
# Why this exists:
#   getScripts.py delivers every maintenance tool to /root but never runs or
#   even mentions them. So the repository knows exactly which state a server
#   should be in, yet never tells the administrator whether it actually is.
#
#   The failure mode this was written for: a server whose backup still runs
#   from a hand-written `crontab -e` entry never had setup-maintenance-cron.sh
#   executed, so /etc/logrotate.d/myodoo-maintenance does not exist and
#   /var/log/container2backup.log has been growing unbounded since day one.
#   Nothing surfaced that — it was only found by looking for it.
#
# What it does:
#   Runs a registry of read-only checks and prints a traffic-light report. Every
#   non-OK finding carries exactly one copy-paste command that fixes it.
#
#   (no flag)   Full report, including the checks that passed.
#   --brief     Only non-OK lines plus the summary. Used by getScripts.py.
#   --quiet     Like --brief, but prints nothing at all when everything is OK.
#               For cron: cron only mails when there is output, so a weekly job
#               speaks up only on actual drift.
#
# Exit codes: 0 when no FAIL is present, 1 otherwise. WARN and SKIP do not
# affect the exit code.
#
# This script NEVER writes. It does not touch /etc, does not restart services
# and makes no network calls, so it is safe to run on a live server at any time.
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
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, Optional, Tuple

SCRIPT_VERSION = "1.1.1"
SCRIPT_DATE = "04.08.2026"

# Installed locations managed by setup-maintenance-cron.sh.
CRON_DEST = "etc/cron.d/myodoo-maintenance"
LOGROTATE_DEST = "etc/logrotate.d/myodoo-maintenance"

# Templates delivered to $HOME by getScripts.py; they are the reference state.
CRON_TEMPLATE = "myodoo-maintenance.cron"
LOGROTATE_TEMPLATE = "myodoo-maintenance.logrotate"

# Scripts copy_scripts() in getScripts.py delivers. Compared against the repo
# checkout to detect a server running stale tooling.
DELIVERED_SCRIPTS = (
    "update_docker_odoo.py",
    "cleanup-weblogs.py",
    "container2backup.py",
    "restore-zip.sh",
    "ssl-renew.sh",
    "nginx-cert-guard.py",
    "nightly-cleanup.sh",
    "deploy-nginx-base.sh",
    "setup-maintenance-cron.sh",
    "server-readiness.py",
)

# Job names that must run from /etc/cron.d/myodoo-maintenance and nowhere else.
MANAGED_JOBS = (
    "container2backup",
    "ssl-renew",
    "cleanup-weblogs",
    "nightly-cleanup",
    "nginx-cert-guard",
)

BACKUP_LOG = "var/log/container2backup.log"
# Must mirror container2backup.py: it reads defaults.backup_path and falls back
# to /opt/backups. Any other key/default here checks a config nothing ever reads.
DEFAULT_BACKUP_PATH = "/opt/backups"

# Thresholds. Kept here so they are adjustable without hunting through checks.
LOG_WARN_BYTES = 100 * 1024 ** 2
LOG_FAIL_BYTES = 1024 ** 3
BACKUP_WARN_AGE = 26 * 3600          # tolerates a late-running 02:00 job
BACKUP_FAIL_AGE = 7 * 86400
DISK_WARN_PCT = 85
DISK_FAIL_PCT = 95


class Severity(Enum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass
class Finding:
    check_id: str
    severity: Severity
    title: str
    detail: str
    fix: Optional[str] = None


@dataclass
class HealthContext:
    """Where to look. `root` exists so the checks can be exercised against a
    throwaway directory tree instead of only on a live server."""
    root: str = "/"
    home: str = "/root"
    repo: str = "/root/myodoo-docker"

    def p(self, relative: str) -> str:
        """Resolve a root-relative path (no leading slash) against self.root."""
        return os.path.join(self.root, relative.lstrip("/"))


# ==============================================================================
# Helpers
# ==============================================================================

def _read(path: str) -> Optional[str]:
    """Read a text file, returning None when it is missing or unreadable."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except (OSError, UnicodeError):
        return None


def _run(command: List[str], timeout: int = 15) -> Tuple[int, str]:
    """Run a command and return (returncode, combined output).

    Never raises: a missing binary or a timeout yields a non-zero code so the
    calling check can decide between SKIP and a real finding.
    """
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, f"{result.stdout}{result.stderr}".strip()
    except FileNotFoundError:
        return 127, "command not found"
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    except OSError as exc:
        return 1, str(exc)


def _human(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024 or unit == "TB":
            return f"{num_bytes:.0f} {unit}" if unit == "B" else f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def _age(seconds: float) -> str:
    if seconds < 3600:
        return f"{seconds / 60:.0f} min"
    if seconds < 86400:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} d"


def _logrotate_paths(text: str) -> List[str]:
    """Extract the log paths a logrotate stanza covers.

    logrotate lists them whitespace-separated before the opening brace; the
    paths are read from the template rather than hard-coded so a new log added
    upstream is checked automatically.

    Comment lines must be stripped first — the template's header mentions
    /etc/cron.d/myodoo-maintenance and would otherwise be counted as a log.
    """
    head = text.split("{", 1)[0]
    body = "\n".join(l for l in head.splitlines() if not l.lstrip().startswith("#"))
    return [token for token in body.split() if token.startswith("/")]


def _cron_command_lines(text: str) -> List[str]:
    """Return the executable lines of a crontab, ignoring comments, blank lines
    and environment assignments (MAILTO=, PATH=)."""
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if re.match(r"^[A-Z_]+\s*=", line):
            continue
        lines.append(line)
    return lines


def _normalise_cron_line(line: str) -> str:
    """Collapse whitespace and reduce script paths to their basename.

    setup-maintenance-cron.sh rewrites the command paths when installed with a
    SCRIPT_DIR other than /root, so a byte comparison would flag those servers
    forever. Normalising the path makes the comparison about schedule and script
    set, which is what actually matters.
    """
    collapsed = " ".join(line.split())
    return re.sub(r"(?<= )/\S+/(?=\S)", "", collapsed)


def _extract_version(text: str) -> Optional[str]:
    """Best-effort version read for the report's detail line.

    The delivered scripts are inconsistent: `# Version:  x.y.z`, `Version: x.y.z`
    and `SCRIPT_VERSION="x.y.z"` all occur, and some scripts carry no version at
    all. This is display-only; staleness itself is decided by content hash.
    """
    for pattern in (
        r"^#?\s*Version:\s*([0-9]+\.[0-9]+\.[0-9]+)",
        r'^SCRIPT_VERSION\s*=\s*["\']([0-9]+\.[0-9]+\.[0-9]+)["\']',
    ):
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            return match.group(1)
    return None


def _ok(check_id: str, title: str, detail: str) -> Finding:
    return Finding(check_id, Severity.OK, title, detail)


def _skip(check_id: str, title: str, detail: str) -> Finding:
    return Finding(check_id, Severity.SKIP, title, detail)


# ==============================================================================
# Checks — maintenance cron and logrotate
# ==============================================================================

FIX_SETUP_CRON = "/root/setup-maintenance-cron.sh"


def check_maintenance_cron_present(ctx: HealthContext) -> Finding:
    # Report the logical path, not the root-prefixed one: on a live server they
    # are identical, and under --root the prefix only adds noise.
    shown = "/" + CRON_DEST
    path = ctx.p(CRON_DEST)
    if os.path.isfile(path):
        jobs = len(_cron_command_lines(_read(path) or ""))
        return _ok("maintenance_cron_present", "Maintenance cron",
                   f"{shown} active ({jobs} jobs)")
    return Finding(
        "maintenance_cron_present", Severity.FAIL, "Maintenance cron",
        f"{shown} missing — backup, cert renewal and log cleanup are not scheduled",
        FIX_SETUP_CRON,
    )


def check_maintenance_cron_current(ctx: HealthContext) -> Finding:
    installed = _read(ctx.p(CRON_DEST))
    template = _read(os.path.join(ctx.home, CRON_TEMPLATE))
    if installed is None:
        return _skip("maintenance_cron_current", "Cron up to date",
                     "no installed cron to compare")
    if template is None:
        return _skip("maintenance_cron_current", "Cron up to date",
                     f"template {CRON_TEMPLATE} not found in {ctx.home}")

    if installed == template:
        return _ok("maintenance_cron_current", "Cron up to date",
                   "matches the delivered template")

    # Differs byte-wise: decide whether that is only the SCRIPT_DIR rewrite.
    installed_jobs = {_normalise_cron_line(l) for l in _cron_command_lines(installed)}
    template_jobs = {_normalise_cron_line(l) for l in _cron_command_lines(template)}
    if installed_jobs == template_jobs:
        return _ok("maintenance_cron_current", "Cron up to date",
                   "same schedule and scripts (installed to a custom path)")

    missing = len(template_jobs - installed_jobs)
    extra = len(installed_jobs - template_jobs)
    return Finding(
        "maintenance_cron_current", Severity.WARN, "Cron up to date",
        f"schedule differs from the template ({missing} missing, {extra} extra)",
        FIX_SETUP_CRON,
    )


def check_logrotate_present(ctx: HealthContext) -> Finding:
    shown = "/" + LOGROTATE_DEST
    if os.path.isfile(ctx.p(LOGROTATE_DEST)):
        return _ok("logrotate_present", "Logrotate", f"{shown} installed")
    return Finding(
        "logrotate_present", Severity.FAIL, "Logrotate",
        f"{shown} missing — the maintenance logs grow unbounded",
        FIX_SETUP_CRON,
    )


def check_logrotate_coverage(ctx: HealthContext) -> Finding:
    installed = _read(ctx.p(LOGROTATE_DEST))
    template = _read(os.path.join(ctx.home, LOGROTATE_TEMPLATE))
    if installed is None:
        return _skip("logrotate_coverage", "Logrotate coverage",
                     "no installed config to inspect")
    if template is None:
        return _skip("logrotate_coverage", "Logrotate coverage",
                     f"template {LOGROTATE_TEMPLATE} not found in {ctx.home}")

    expected = _logrotate_paths(template)
    covered = set(_logrotate_paths(installed))
    missing = [path for path in expected if path not in covered]
    if not missing:
        return _ok("logrotate_coverage", "Logrotate coverage",
                   f"all {len(expected)} log paths covered")
    return Finding(
        "logrotate_coverage", Severity.WARN, "Logrotate coverage",
        f"not rotated: {', '.join(missing)}",
        FIX_SETUP_CRON,
    )


def check_duplicate_cron_entries(ctx: HealthContext) -> Finding:
    """Find maintenance jobs scheduled outside /etc/cron.d/myodoo-maintenance.

    Two sources: root's personal crontab and any other file in /etc/cron.d.
    With the managed cron active these run twice — for the backup that means two
    concurrent dumps of the same database.
    """
    duplicates = []

    code, output = _run(["crontab", "-l"])
    if code == 0:
        for line in _cron_command_lines(output):
            for job in MANAGED_JOBS:
                if job in line:
                    duplicates.append(f"crontab -l: {job}")

    cron_d = ctx.p("etc/cron.d")
    managed = os.path.basename(CRON_DEST)
    try:
        entries = sorted(os.listdir(cron_d))
    except OSError:
        entries = []
    for name in entries:
        if name == managed:
            continue
        content = _read(os.path.join(cron_d, name))
        if not content:
            continue
        for job in MANAGED_JOBS:
            if job in content:
                duplicates.append(f"/etc/cron.d/{name}: {job}")

    if not duplicates:
        return _ok("duplicate_cron_entries", "Duplicate cron",
                   "no competing maintenance entries")

    listed = "; ".join(sorted(set(duplicates)))
    if os.path.isfile(ctx.p(CRON_DEST)):
        return Finding(
            "duplicate_cron_entries", Severity.FAIL, "Duplicate cron",
            f"scheduled twice — {listed}",
            "crontab -e   # remove the legacy line(s), or rm the stray /etc/cron.d file",
        )
    return Finding(
        "duplicate_cron_entries", Severity.WARN, "Duplicate cron",
        f"legacy setup, not managed by setup-maintenance-cron.sh — {listed}",
        FIX_SETUP_CRON + "   # then remove the legacy entries",
    )


# ==============================================================================
# Checks — backup health
# ==============================================================================

def check_log_sizes(ctx: HealthContext) -> Finding:
    """Size of the maintenance logs. A large log means rotation is not working,
    regardless of whether the config file happens to exist."""
    template = _read(os.path.join(ctx.home, LOGROTATE_TEMPLATE))
    paths = _logrotate_paths(template) if template else [f"/{BACKUP_LOG}"]

    worst = Severity.OK
    offenders = []
    for path in paths:
        full = ctx.p(path)
        try:
            size = os.path.getsize(full)
        except OSError:
            continue
        if size >= LOG_FAIL_BYTES:
            worst = Severity.FAIL
            offenders.append(f"{path} ({_human(size)})")
        elif size >= LOG_WARN_BYTES:
            if worst is not Severity.FAIL:
                worst = Severity.WARN
            offenders.append(f"{path} ({_human(size)})")

    if worst is Severity.OK:
        return _ok("log_sizes", "Log sizes", f"all {len(paths)} maintenance logs within limits")
    return Finding(
        "log_sizes", worst, "Log sizes",
        f"oversized, rotation is not taking effect: {', '.join(offenders)}",
        "logrotate -f /etc/logrotate.d/myodoo-maintenance",
    )


def check_backup_recency(ctx: HealthContext) -> Finding:
    try:
        age = time.time() - os.path.getmtime(ctx.p(BACKUP_LOG))
    except OSError:
        return Finding(
            "backup_recency", Severity.WARN, "Backup recency",
            f"/{BACKUP_LOG} does not exist — no backup has ever logged here",
            FIX_SETUP_CRON,
        )

    if age >= BACKUP_FAIL_AGE:
        return Finding(
            "backup_recency", Severity.FAIL, "Backup recency",
            f"last backup activity {_age(age)} ago",
            "dobk   # run a backup now, then check the cron schedule",
        )
    if age >= BACKUP_WARN_AGE:
        return Finding(
            "backup_recency", Severity.WARN, "Backup recency",
            f"last backup activity {_age(age)} ago (expected within 26 h)",
            "dobk",
        )
    return _ok("backup_recency", "Backup recency", f"last activity {_age(age)} ago")


def _load_backup_config(ctx: HealthContext) -> Tuple[Optional[dict], Optional[str]]:
    """Return (config, error). Missing PyYAML is reported as an error string so
    the caller can SKIP rather than fail."""
    path = os.path.join(ctx.home, "container2backup.yaml")
    if not os.path.isfile(path):
        return None, f"{path} not found"
    try:
        import yaml  # noqa: PLC0415 — optional dependency, only needed here
    except ImportError:
        return None, "PyYAML not installed"
    text = _read(path)
    if text is None:
        return None, f"{path} unreadable"
    try:
        return yaml.safe_load(text) or {}, None
    except Exception as exc:                      # yaml.YAMLError and friends
        return None, f"invalid YAML: {exc}"


def check_backup_config(ctx: HealthContext) -> Finding:
    config, error = _load_backup_config(ctx)
    if error == "PyYAML not installed":
        return _skip("backup_config", "Backup config", error)
    if error:
        return Finding(
            "backup_config", Severity.FAIL, "Backup config", error,
            "edbk   # create or repair the backup configuration",
        )

    # The key is `databases` — that is what container2backup.py iterates over.
    databases = config.get("databases") or []
    if not databases:
        return Finding(
            "backup_config", Severity.WARN, "Backup config",
            "no databases defined — the backup would do nothing",
            "edbk",
        )
    return _ok("backup_config", "Backup config",
               f"{len(databases)} database(s) configured")


def check_backup_disk_space(ctx: HealthContext) -> Finding:
    config, error = _load_backup_config(ctx)
    folder = DEFAULT_BACKUP_PATH
    source = "default"
    if config:
        configured = (config.get("defaults") or {}).get("backup_path")
        if configured:
            # container2backup.py expands both, and the shipped config uses $HOME.
            folder = os.path.expandvars(os.path.expanduser(str(configured)))
            source = "container2backup.yaml"

    target = ctx.p(folder)
    try:
        usage = shutil.disk_usage(target)
    except OSError:
        return _skip("backup_disk_space", "Backup disk",
                     f"{folder} not accessible ({source})")

    used_pct = usage.used / usage.total * 100 if usage.total else 0
    detail = (f"{folder}: {used_pct:.0f}% used, "
              f"{_human(usage.free)} free of {_human(usage.total)}")
    if used_pct >= DISK_FAIL_PCT:
        return Finding("backup_disk_space", Severity.FAIL, "Backup disk", detail,
                       "llbk   # review and prune old backups")
    if used_pct >= DISK_WARN_PCT:
        return Finding("backup_disk_space", Severity.WARN, "Backup disk", detail,
                       "llbk   # consider lowering retention_days")
    return _ok("backup_disk_space", "Backup disk", detail)


# ==============================================================================
# Checks — infrastructure, each from a real incident
# ==============================================================================

def check_docker_storage_driver(ctx: HealthContext) -> Finding:
    """Docker >= 29 defaults to the containerd image store, which produces
    hollow/broken images on export (moby#52431). overlay2 is the safe driver."""
    if not shutil.which("docker"):
        return _skip("docker_storage_driver", "Docker driver", "docker not installed")

    code, output = _run(["docker", "info", "--format", "{{.Driver}}"])
    if code != 0:
        return _skip("docker_storage_driver", "Docker driver",
                     "docker info unavailable (daemon not running?)")

    driver = output.strip().splitlines()[-1] if output.strip() else ""
    if driver == "overlay2":
        return _ok("docker_storage_driver", "Docker driver", "overlay2")
    return Finding(
        "docker_storage_driver", Severity.FAIL, "Docker driver",
        f"storage driver is '{driver}', not overlay2 — builds can produce "
        f"broken images (moby#52431)",
        'Set {"storage-driver": "overlay2"} in /etc/docker/daemon.json, '
        "then: systemctl restart docker && docker builder prune",
    )


def check_nginx_unit_dropin(ctx: HealthContext) -> Finding:
    """`nginx -t` empties /run/nginx.pid, after which the nginx.org unit's reload
    fails with a kill usage error and the old config silently stays live. The
    drop-in fixes the reload and adds Restart=on-failure so an apt upgrade that
    kills nginx mid-swap does not leave it down."""
    if not shutil.which("nginx"):
        return _skip("nginx_unit_dropin", "nginx unit", "nginx not installed")

    dropin_dir = ctx.p("etc/systemd/system/nginx.service.d")
    combined = ""
    try:
        for name in sorted(os.listdir(dropin_dir)):
            if name.endswith(".conf"):
                combined += _read(os.path.join(dropin_dir, name)) or ""
    except OSError:
        combined = ""

    has_mainpid = "$MAINPID" in combined
    has_restart = re.search(r"^\s*Restart\s*=\s*on-failure", combined, re.MULTILINE) is not None
    if has_mainpid and has_restart:
        return _ok("nginx_unit_dropin", "nginx unit", "reload + restart drop-in present")

    # Name the commands that actually close the gap. deploy-nginx-base.sh only
    # repairs an empty /run/nginx.pid at runtime; it writes no unit drop-in, and
    # bootstrap.sh writes the Restart one but not the ExecReload one.
    lacking = []
    fix_lines = ["mkdir -p /etc/systemd/system/nginx.service.d"]
    if not has_mainpid:
        lacking.append("$MAINPID reload (reloads fail silently after nginx -t)")
        fix_lines.append(
            "printf '[Service]\\nExecReload=\\n"
            "ExecReload=/bin/kill -s HUP $MAINPID\\n' > "
            "/etc/systemd/system/nginx.service.d/10-reload-mainpid.conf"
        )
    if not has_restart:
        lacking.append("Restart=on-failure (stays down after an apt upgrade)")
        fix_lines.append(
            "printf '[Unit]\\nStartLimitIntervalSec=300\\nStartLimitBurst=5\\n\\n"
            "[Service]\\nRestart=on-failure\\nRestartSec=10\\n' > "
            "/etc/systemd/system/nginx.service.d/10-restart.conf"
        )
        fix_lines.append(
            "(the Restart drop-in is also written by myodoo-docker/scripts/bootstrap.sh)"
        )
    fix_lines.append("systemctl daemon-reload")
    return Finding(
        "nginx_unit_dropin", Severity.WARN, "nginx unit",
        "drop-in incomplete: " + "; ".join(lacking),
        "\n".join(fix_lines),
    )


def check_certbot_timer_window(ctx: HealthContext) -> Finding:
    """The distro certbot.timer fires inside the 06:00-07:00 apt window, where a
    renewal can collide with a package upgrade. bootstrap.sh pins it to 03:00."""
    if not shutil.which("systemctl"):
        return _skip("certbot_timer_window", "certbot timer", "systemd not available")

    code, output = _run(["systemctl", "show", "certbot.timer", "-p", "TimersCalendar"])
    if code != 0 or "TimersCalendar=" not in output:
        return _skip("certbot_timer_window", "certbot timer", "certbot.timer not present")

    calendar = output.split("TimersCalendar=", 1)[1].strip()
    if not calendar:
        return _skip("certbot_timer_window", "certbot timer", "no calendar entry")
    if "03:00" in calendar:
        return _ok("certbot_timer_window", "certbot timer", "pinned to the 03:00 slot")
    return Finding(
        "certbot_timer_window", Severity.WARN, "certbot timer",
        f"stock schedule ({calendar}) — renewal can collide with the apt window; "
        f"expected OnCalendar=*-*-* 03:00:00",
        "mkdir -p /etc/systemd/system/certbot.timer.d\n"
        "printf '[Timer]\\nOnCalendar=\\nOnCalendar=*-*-* 03:00:00\\n"
        "RandomizedDelaySec=1800\\n' > "
        "/etc/systemd/system/certbot.timer.d/10-offpeak.conf\n"
        "systemctl daemon-reload && systemctl restart certbot.timer\n"
        "The empty 'OnCalendar=' line is mandatory: it clears the stock schedule.\n"
        "Without it systemd ADDS 03:00 instead of replacing 00,12:00:00.\n"
        "Alternative: re-run myodoo-docker/scripts/bootstrap.sh — it writes this "
        "drop-in itself.",
    )


def check_script_versions(ctx: HealthContext) -> Finding:
    """Compare the delivered scripts in $HOME against the repository checkout.

    Compared by content, not by version header: the headers are inconsistent
    across scripts (some carry none at all), and a hash also catches a script
    that was edited in place on the server.
    """
    repo_scripts = os.path.join(ctx.repo, "scripts")
    if not os.path.isdir(repo_scripts):
        return _skip("script_versions", "Script versions",
                     f"repository checkout not found at {ctx.repo}")

    stale, absent = [], []
    compared = 0
    for name in DELIVERED_SCRIPTS:
        reference = _read(os.path.join(repo_scripts, name))
        if reference is None:
            continue
        deployed = _read(os.path.join(ctx.home, name))
        if deployed is None:
            absent.append(name)
            continue
        compared += 1
        if deployed != reference:
            version = _extract_version(reference)
            stale.append(f"{name}{' -> ' + version if version else ''}")

    if not stale and not absent:
        return _ok("script_versions", "Script versions",
                   f"all {compared} delivered scripts match the repository")

    parts = []
    if stale:
        parts.append(f"outdated: {', '.join(sorted(stale))}")
    if absent:
        parts.append(f"not deployed: {', '.join(sorted(absent))}")
    return Finding(
        "script_versions", Severity.WARN, "Script versions",
        "; ".join(parts),
        "ups   # re-run getScripts.py to redeploy",
    )


# ==============================================================================
# Registry and runner
# ==============================================================================

CHECKS: Tuple[Callable[[HealthContext], Finding], ...] = (
    check_maintenance_cron_present,
    check_maintenance_cron_current,
    check_logrotate_present,
    check_logrotate_coverage,
    check_duplicate_cron_entries,
    check_log_sizes,
    check_backup_recency,
    check_backup_config,
    check_docker_storage_driver,
    check_nginx_unit_dropin,
    check_certbot_timer_window,
    check_script_versions,
    check_backup_disk_space,
)


def run_checks(ctx: HealthContext) -> List[Finding]:
    """Run every check. A check that raises becomes a SKIP finding carrying the
    error — one broken check must never cost the administrator the whole
    report."""
    findings = []
    for check in CHECKS:
        try:
            findings.append(check(ctx))
        except Exception as exc:
            findings.append(Finding(
                check.__name__, Severity.SKIP, check.__name__,
                f"check failed to run: {type(exc).__name__}: {exc}",
            ))
    return findings


# ==============================================================================
# Report
# ==============================================================================

def _palette(stream) -> dict:
    if not stream.isatty():
        return {level: "" for level in list(Severity) + ["reset", "dim"]}
    return {
        Severity.OK: "\033[0;32m",
        Severity.WARN: "\033[1;33m",
        Severity.FAIL: "\033[0;31m",
        Severity.SKIP: "",
        "reset": "\033[0m",
        "dim": "\033[2m",
    }


def print_report(findings: List[Finding], mode: str = "full", stream=None) -> None:
    """Render the report.

    mode 'full'  — every finding
    mode 'brief' — only non-OK findings plus the summary
    mode 'quiet' — nothing at all unless something is actually wrong

    'quiet' deliberately triggers on WARN/FAIL only, not on SKIP: a server
    without Docker produces a permanent SKIP, and letting that mail every week
    would train the reader to ignore the report. SKIPs are still shown once
    something else has triggered output, because they explain coverage gaps.
    """
    stream = stream or sys.stdout
    counts = {level: sum(1 for f in findings if f.severity is level) for level in Severity}
    noteworthy = [f for f in findings if f.severity is not Severity.OK]
    actionable = [f for f in findings if f.severity in (Severity.WARN, Severity.FAIL)]

    if mode == "quiet" and not actionable:
        return

    shown = findings if mode == "full" else noteworthy
    colors = _palette(stream)
    width = max((len(f.title) for f in shown), default=0)

    def emit(text: str = "") -> None:
        print(text, file=stream)

    emit()
    emit("=" * 60)
    emit("  Server Readiness Report")
    emit("=" * 60)

    if not shown:
        emit(f"  {colors[Severity.OK]}All {counts[Severity.OK]} checks passed.{colors['reset']}")
    for finding in shown:
        color = colors[finding.severity]
        label = f"[{finding.severity.value}]".ljust(6)
        emit(f"  {color}{label}{colors['reset']} {finding.title.ljust(width)}  {finding.detail}")
        if finding.fix:
            # Align under the detail column: 2 indent + 6 label + 1 gap + title + 2 gap.
            indent = " " * (11 + width)
            fix_lines = finding.fix.split("\n")
            emit(f"{indent}{colors['dim']}Fix:{colors['reset']} {fix_lines[0]}")
            # Continuation lines line up under the first one (past the "Fix: " label).
            # A fix that spells out a file's exact content must survive copy & paste
            # verbatim — squeezing it into one line invites pasting the prose too.
            for fix_line in fix_lines[1:]:
                emit(f"{indent}     {fix_line}")

    emit("-" * 60)
    summary = (f"  {counts[Severity.OK]} OK · {counts[Severity.WARN]} WARN · "
               f"{counts[Severity.FAIL]} FAIL · {counts[Severity.SKIP]} skipped")
    emit(summary)
    if mode != "full" and counts[Severity.OK]:
        emit(f"  {colors['dim']}Run server-readiness.py for the full list.{colors['reset']}")
    emit("=" * 60)
    emit()


# ==============================================================================
# Entry point
# ==============================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report whether this server matches the expected myodoo-docker state.",
        epilog="Read-only: this script never modifies the system.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--brief", action="store_true",
                      help="only show findings that are not OK")
    mode.add_argument("--quiet", action="store_true",
                      help="like --brief, but print nothing when everything is OK (for cron)")
    parser.add_argument("--root", default="/",
                        help="path prefix to inspect instead of / (for testing)")
    parser.add_argument("--home", default=None,
                        help="where the delivered scripts live (default: ~ of the invoking user)")
    parser.add_argument("--repo", default=None,
                        help="myodoo-docker checkout (default: <home>/myodoo-docker)")
    parser.add_argument("--version", action="version",
                        version=f"server-readiness.py {SCRIPT_VERSION} ({SCRIPT_DATE})")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    home = args.home or os.path.expanduser("~")
    ctx = HealthContext(
        root=args.root,
        home=home,
        repo=args.repo or os.path.join(home, "myodoo-docker"),
    )

    findings = run_checks(ctx)
    mode = "quiet" if args.quiet else "brief" if args.brief else "full"
    print_report(findings, mode)

    return 1 if any(f.severity is Severity.FAIL for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
