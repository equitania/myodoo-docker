#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Title:            ownerp_state.py
# Description:      What state is this server in? Collected once, rendered as
#                   text (dostat) or handed to the console.
# Version:          1.0.0
# Date:             13.08.2026
# Author:           Equitania Software GmbH
# ==============================================================================
# Why this exists:
#   Every fact an operator wants at a glance already lives somewhere on the
#   machine — in docker2update.yaml, in container2backup.yaml, in the backup
#   directory, in /etc/cron.d/myodoo-maintenance, in the readiness checks. It
#   is spread across five tools with five output formats, and nothing puts it
#   on one page. This does.
#
# The rule this module is built around:
#   A status tool must work on a broken server, because that is where it is
#   needed. Every source here is optional. Docker not running, PyYAML absent,
#   a configuration that does not parse, /etc unreadable because we are not
#   root — each of those degrades that one section to "unknown", with the
#   reason attached, and the other three still render. A traceback is never
#   the right answer to "what is wrong with this machine".
#
# What it never does:
#   Write. Anything. It opens files for reading, runs `docker ps`, and calls
#   the read-only entry points of the sibling scripts. Every change to a
#   configuration goes through ownerp_wizard.py, and every change to the cron
#   through ownerp_cron.py — one write path per file, and this is not one.
#
# Why it carries no UI import:
#   Stage 3 of the console design puts a Textual interface on top of this. If
#   the data layer knew about the interface, it could not be tested without it
#   and `dostat` could not exist. It stays plain Python; `dostat` is this file's
#   own main(), and the console will be a second consumer.
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
import glob
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

SCRIPT_VERSION = "1.0.0"
SCRIPT_DATE = "13.08.2026"

HOME = os.path.expanduser("~")
UPDATE_YAML = "docker2update.yaml"
BACKUP_YAML = "container2backup.yaml"
HISTORY_FILE = "update-history.jsonl"
HISTORY_TS_FORMAT = "%Y-%m-%dT%H:%M:%S"

DEFAULT_BACKUP_PATH = "/opt/backups"
# container2backup.py writes database archives into <backup_path>/docker as
# <database>_<data_container>_dockerbackup_<timestamp>.<ext>.
DOCKER_SUBDIR = "docker"
BACKUP_SUFFIXES = (".7z", ".7z.gpg", ".zip", ".tar.gz", ".tar.zst")

# A backup older than this is worth pointing at. Matches the thresholds
# server-readiness.py uses for the backup log, so the two never disagree.
BACKUP_WARN_AGE = 26 * 3600
BACKUP_FAIL_AGE = 50 * 3600

# Free space on the backup target below which the number is worth reading.
DISK_WARN_PERCENT = 85
DISK_FAIL_PERCENT = 95

DOCKER_TIMEOUT = 10


# ==============================================================================
# Data
# ==============================================================================

@dataclass
class Instance:
    """One entry of docker2update.yaml, plus what the machine says about it."""

    name: str
    database: str = ""
    version: str = ""
    active: bool = True
    mode: str = ""
    # None means "docker could not be asked", which is not the same as "not
    # running" and must not be rendered as though it were.
    running: Optional[bool] = None
    status: str = ""
    last_run: Optional[dict] = None

    @property
    def last_run_text(self) -> str:
        if not self.last_run:
            return "never"
        try:
            when = time.strftime(
                "%d.%m. %H:%M",
                time.strptime(self.last_run.get("ts", ""), HISTORY_TS_FORMAT))
        except (ValueError, TypeError):
            when = "?"
        result = self.last_run.get("result", "?")
        return f"{when} {self.last_run.get('mode', '?')} {result}"


@dataclass
class Archive:
    """One backup file on disk."""

    path: str
    size: int
    mtime: float

    @property
    def age(self) -> float:
        return time.time() - self.mtime


@dataclass
class BackupEntry:
    """One database from container2backup.yaml and its archives on disk."""

    database: str
    sql_container: str = ""
    data_container: str = ""
    retention_days: Optional[int] = None
    only_sql_dump: bool = False
    archives: List[Archive] = field(default_factory=list)

    @property
    def newest(self) -> Optional[Archive]:
        return self.archives[0] if self.archives else None

    @property
    def severity(self) -> str:
        """OK, WARN or FAIL, from the age of the newest archive."""
        if not self.newest:
            return "FAIL"
        if self.newest.age >= BACKUP_FAIL_AGE:
            return "FAIL"
        if self.newest.age >= BACKUP_WARN_AGE:
            return "WARN"
        return "OK"


@dataclass
class Disk:
    """Free space on one path."""

    path: str
    total: int = 0
    used: int = 0
    free: int = 0

    @property
    def percent_used(self) -> int:
        return int(round(self.used * 100.0 / self.total)) if self.total else 0

    @property
    def severity(self) -> str:
        if not self.total:
            return "SKIP"
        if self.percent_used >= DISK_FAIL_PERCENT:
            return "FAIL"
        if self.percent_used >= DISK_WARN_PERCENT:
            return "WARN"
        return "OK"


@dataclass
class Section:
    """One area of the report. `error` set means: could not be determined.

    Kept explicit rather than signalled by an empty list, because "no instances
    configured" and "the configuration does not parse" call for opposite
    reactions from whoever reads this.
    """

    name: str
    error: Optional[str] = None

    @property
    def known(self) -> bool:
        return self.error is None


@dataclass
class Instances(Section):
    entries: List[Instance] = field(default_factory=list)
    docker_error: Optional[str] = None


@dataclass
class Backups(Section):
    entries: List[BackupEntry] = field(default_factory=list)
    backup_path: str = DEFAULT_BACKUP_PATH
    disk: Optional[Disk] = None


@dataclass
class Maintenance(Section):
    jobs: List[object] = field(default_factory=list)   # ownerp_cron.CronJob


@dataclass
class Health(Section):
    findings: List[object] = field(default_factory=list)   # readiness Finding

    def by_severity(self, name: str) -> List[object]:
        return [f for f in self.findings
                if getattr(f.severity, "value", f.severity) == name]


@dataclass
class ServerState:
    """Everything, collected once."""

    hostname: str = ""
    collected_at: float = 0.0
    instances: Instances = field(default_factory=lambda: Instances("instances"))
    backups: Backups = field(default_factory=lambda: Backups("backups"))
    maintenance: Maintenance = field(
        default_factory=lambda: Maintenance("maintenance"))
    health: Health = field(default_factory=lambda: Health("health"))


# ==============================================================================
# Helpers
# ==============================================================================

def human_size(num_bytes: float) -> str:
    """Bytes as something a person reads at a glance."""
    step = 1024.0
    for unit in ("B", "K", "M", "G", "T"):
        if abs(num_bytes) < step or unit == "T":
            return f"{num_bytes:.0f}{unit}" if unit == "B" else f"{num_bytes:.1f}{unit}"
        num_bytes /= step
    return f"{num_bytes:.1f}T"


def human_age(seconds: float) -> str:
    """A duration as the largest unit that still says something useful."""
    if seconds < 0:
        return "in the future"
    if seconds < 90:
        return f"{int(seconds)} s"
    if seconds < 5400:
        return f"{int(seconds / 60)} min"
    if seconds < 172800:
        return f"{seconds / 3600:.1f} h"
    return f"{int(seconds / 86400)} d"


def _load_module(path: str, name: str):
    """Import a sibling script by path, or None.

    By path because two of them carry a hyphen (server-readiness.py) and none
    of them are on the import path: on a server they sit beside this file in
    $HOME, in the repository in scripts/.
    """
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        # A sibling that fails to import must cost its own section, nothing
        # more. Which one broke is reported by the caller as that section's
        # error; re-raising here would take the whole report down with it.
        return None


def _here() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _read_yaml(path: str):
    """(data, error). Every failure mode is a sentence, never an exception."""
    if not os.path.isfile(path):
        return None, f"{path} not found"
    try:
        import yaml  # noqa: PLC0415 — optional, and only needed here
    except ImportError:
        return None, "PyYAML is not installed"
    try:
        with open(path, encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}, None
    except Exception as exc:                      # yaml.YAMLError and OSError
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark else ""
        return None, f"{os.path.basename(path)} does not parse{where}"


# ==============================================================================
# Collectors
# ==============================================================================

def docker_status(timeout: int = DOCKER_TIMEOUT):
    """(name -> status text, error). Never raises, never blocks forever."""
    if not shutil.which("docker"):
        return {}, "docker is not installed"
    try:
        completed = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return {}, f"docker did not answer within {timeout} s"
    except OSError as exc:
        return {}, f"docker could not be run: {exc}"
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        return {}, detail[-1] if detail else "docker ps failed"
    status = {}
    for line in completed.stdout.splitlines():
        if "\t" in line:
            name, _, text = line.partition("\t")
            status[name.strip()] = text.strip()
    return status, None


def read_history(home: str = HOME, limit: int = 4000) -> Dict[str, dict]:
    """container name -> its newest run, from update-history.jsonl.

    Absent history is normal on a server that has not updated yet, so it is
    not an error — it renders as "never".
    """
    path = os.path.join(home, HISTORY_FILE)
    latest: Dict[str, dict] = {}
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()[-limit:]
    except OSError:
        return latest
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue                              # a torn line is not fatal
        name = entry.get("container")
        if not name:
            continue
        previous = latest.get(name)
        if previous is None or entry.get("ts", "") >= previous.get("ts", ""):
            latest[name] = entry
    return latest


def collect_instances(home: str = HOME, docker: bool = True) -> Instances:
    """docker2update.yaml, joined with `docker ps` and the run history."""
    config, error = _read_yaml(os.path.join(home, UPDATE_YAML))
    if error:
        return Instances("instances", error=error)

    containers = config.get("containers") or []
    if not isinstance(containers, list):
        return Instances("instances",
                         error=f"{UPDATE_YAML}: `containers` is not a list")

    # Three states, not two. "not asked" and "asked, and it is down" are
    # different facts, and an empty status string looks identical to both —
    # which is how a skipped query comes to render as a stopped container.
    if not docker:
        status, docker_error, asked = {}, None, False
    else:
        status, docker_error = docker_status()
        asked = docker_error is None
    history = read_history(home)

    entries = []
    for raw in containers:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("container_name") or "").strip()
        if not name:
            continue
        text = status.get(name, "")
        entries.append(Instance(
            name=name,
            database=str(raw.get("database_name") or ""),
            version=str(raw.get("odoo_version") or ""),
            active=raw.get("active", True) is not False,
            mode=str(raw.get("type") or ""),
            running=text.lower().startswith("up") if asked else None,
            status=text,
            last_run=history.get(name),
        ))
    return Instances("instances", entries=entries, docker_error=docker_error)


def find_archives(backup_path: str, database: str,
                  data_container: str) -> List[Archive]:
    """Every archive of one database, newest first.

    Matched on the stem container2backup.py builds, which carries both names —
    two databases backed up from the same container stay apart, and so do two
    containers serving the same database name.
    """
    folder = os.path.join(backup_path, DOCKER_SUBDIR)
    stem = f"{database}_{data_container}_dockerbackup_" if data_container else \
           f"{database}_"
    found = []
    for candidate in glob.glob(os.path.join(folder, stem + "*")):
        if not candidate.endswith(BACKUP_SUFFIXES):
            continue
        try:
            info = os.stat(candidate)
        except OSError:
            continue                              # deleted mid-scan
        found.append(Archive(candidate, info.st_size, info.st_mtime))
    return sorted(found, key=lambda a: a.mtime, reverse=True)


def collect_backups(home: str = HOME, scan: bool = True) -> Backups:
    """container2backup.yaml, joined with what is actually on the disk."""
    config, error = _read_yaml(os.path.join(home, BACKUP_YAML))
    if error:
        return Backups("backups", error=error)

    defaults = config.get("defaults") or {}
    backup_path = str(defaults.get("backup_path") or DEFAULT_BACKUP_PATH)
    default_retention = defaults.get("retention_days")

    databases = config.get("databases") or []
    if not isinstance(databases, list):
        return Backups("backups", backup_path=backup_path,
                       error=f"{BACKUP_YAML}: `databases` is not a list")

    entries = []
    for raw in databases:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        data_container = str(raw.get("data_container") or "")
        retention = raw.get("retention_days", default_retention)
        entries.append(BackupEntry(
            database=name,
            sql_container=str(raw.get("sql_container") or ""),
            data_container=data_container,
            retention_days=retention if isinstance(retention, int) else None,
            only_sql_dump=bool(raw.get("only_sql_dump")),
            archives=find_archives(backup_path, name, data_container)
                     if scan else [],
        ))

    return Backups("backups", entries=entries, backup_path=backup_path,
                   disk=disk_usage(backup_path) if scan else None)


def disk_usage(path: str) -> Optional[Disk]:
    """Free space on `path`, or None when it cannot be measured."""
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return Disk(path, usage.total, usage.used, usage.free)


def collect_maintenance(cron_path: Optional[str] = None) -> Maintenance:
    """The maintenance cron, read through ownerp_cron.py."""
    module = _load_module(os.path.join(_here(), "ownerp_cron.py"), "ownerp_cron")
    if module is None:
        return Maintenance("maintenance",
                           error="ownerp_cron.py is not installed — run ups")
    try:
        cron = module.load(cron_path) if cron_path else module.load()
    except Exception as exc:                      # CronError and OSError
        return Maintenance("maintenance", error=str(exc))
    return Maintenance("maintenance", jobs=list(cron.jobs))


def collect_health(root: str = "/", home: str = HOME,
                   repo: Optional[str] = None) -> Health:
    """The readiness checks, run through server-readiness.py.

    Not reimplemented here: those checks are the single source of truth for
    what "ready" means, and a second opinion that drifts from them would be
    worse than none.
    """
    module = _load_module(os.path.join(_here(), "server-readiness.py"),
                          "server_readiness")
    if module is None:
        return Health("health",
                      error="server-readiness.py is not installed — run ups")
    try:
        context = module.HealthContext(
            root=root, home=home,
            repo=repo or os.path.join(home, "myodoo-docker"))
        return Health("health", findings=list(module.run_checks(context)))
    except Exception as exc:
        return Health("health", error=f"the readiness checks failed: {exc}")


def collect(home: str = HOME, root: str = "/", docker: bool = True,
            scan: bool = True, checks: bool = True,
            cron_path: Optional[str] = None) -> ServerState:
    """Everything, once. Each section fails on its own or not at all."""
    return ServerState(
        hostname=_hostname(),
        collected_at=time.time(),
        instances=collect_instances(home, docker=docker),
        backups=collect_backups(home, scan=scan),
        maintenance=collect_maintenance(cron_path),
        health=collect_health(root, home) if checks
               else Health("health", error="skipped"),
    )


def _hostname() -> str:
    try:
        import socket
        return socket.gethostname()
    except Exception:
        return "?"


# ==============================================================================
# Rendering
# ==============================================================================

def _palette(stream) -> dict:
    use = hasattr(stream, "isatty") and stream.isatty()
    if not use:
        return {k: "" for k in
                ("green", "yellow", "red", "grey", "bold", "reset")}
    return {"green": "\033[0;32m", "yellow": "\033[1;33m", "red": "\033[0;31m",
            "grey": "\033[0;90m", "bold": "\033[1m", "reset": "\033[0m"}


MARKS = {"OK": "ok", "WARN": "!", "FAIL": "XX", "SKIP": "-"}


def _mark(severity: str, colours: dict) -> str:
    colour = {"OK": colours["green"], "WARN": colours["yellow"],
              "FAIL": colours["red"]}.get(severity, colours["grey"])
    return f"{colour}{MARKS.get(severity, '-'):>2}{colours['reset']}"


def render(state: ServerState, stream=None, verbose: bool = False) -> None:
    """The whole state as one page of text."""
    stream = stream or sys.stdout
    c = _palette(stream)
    when = time.strftime("%d.%m.%Y %H:%M", time.localtime(state.collected_at))

    print(f"\n{c['bold']}ownERP  {state.hostname}{c['reset']}"
          f"{c['grey']}   {when}{c['reset']}\n", file=stream)

    _render_instances(state.instances, stream, c)
    _render_backups(state.backups, stream, c)
    _render_maintenance(state.maintenance, stream, c)
    _render_health(state.health, stream, c, verbose)
    print("", file=stream)


def _section(title: str, stream, colours: dict) -> None:
    print(f"{colours['bold']}{title}{colours['reset']}", file=stream)


def _unknown(section: Section, stream, colours: dict) -> None:
    print(f"  {colours['yellow']}?{colours['reset']} {section.error}",
          file=stream)
    print("", file=stream)


def _render_instances(instances: Instances, stream, c: dict) -> None:
    _section("Instances", stream, c)
    if not instances.known:
        return _unknown(instances, stream, c)
    if not instances.entries:
        print(f"  {c['grey']}none configured{c['reset']}\n", file=stream)
        return

    for entry in instances.entries:
        if entry.running is None:
            state, colour = "?", c["grey"]
        elif entry.running:
            state, colour = "up", c["green"]
        else:
            state, colour = "down", c["red"]
        name = entry.name if entry.active else f"{entry.name} (inactive)"
        version = f"v{entry.version}" if entry.version else ""
        print(f"  {colour}{state:>4}{c['reset']}  {name:<22.22} "
              f"{version:<6.6} {c['grey']}{entry.last_run_text}{c['reset']}",
              file=stream)
    if instances.docker_error:
        print(f"  {c['yellow']}?{c['reset']} container state unknown: "
              f"{instances.docker_error}", file=stream)
    print("", file=stream)


def _render_backups(backups: Backups, stream, c: dict) -> None:
    _section("Backup", stream, c)
    if not backups.known:
        return _unknown(backups, stream, c)
    if not backups.entries:
        print(f"  {c['grey']}no databases configured{c['reset']}\n",
              file=stream)
        return

    for entry in backups.entries:
        # "sql only" belongs to the database, not to the archive — putting it
        # after a variable-width detail is what made the columns wander.
        label = (f"{entry.database} (sql only)" if entry.only_sql_dump
                 else entry.database)
        newest = entry.newest
        if newest:
            detail = (f"{human_age(newest.age):>8} ago  "
                      f"{human_size(newest.size):>7}  "
                      f"{len(entry.archives)} kept")
        else:
            detail = "no archive found"
        print(f"  {_mark(entry.severity, c)}  {label:<26.26} {detail}",
              file=stream)

    disk = backups.disk
    if disk:
        print(f"  {_mark(disk.severity, c)}  {c['grey']}{disk.path}: "
              f"{disk.percent_used} % used, {human_size(disk.free)} free"
              f"{c['reset']}", file=stream)
    else:
        print(f"  {c['yellow']}?{c['reset']} {backups.backup_path} "
              f"cannot be measured", file=stream)
    print("", file=stream)


def _render_maintenance(maintenance: Maintenance, stream, c: dict) -> None:
    _section("Maintenance", stream, c)
    if not maintenance.known:
        return _unknown(maintenance, stream, c)
    if not maintenance.jobs:
        print(f"  {c['grey']}no jobs{c['reset']}\n", file=stream)
        return

    module = _load_module(os.path.join(_here(), "ownerp_cron.py"), "ownerp_cron")
    for job in maintenance.jobs:
        active = getattr(job, "active", True)
        state = "on " if active else "off"
        colour = c["green"] if active else c["grey"]
        schedule = getattr(job, "schedule", "")
        when = module.humanise(schedule) if module else schedule
        last = module.last_run(job) if module else None
        ago = f"{human_age(time.time() - last)} ago" if last else "never"
        print(f"  {colour}{state}{c['reset']} {getattr(job, 'job_id', '?'):<18.18} "
              f"{when:<26.26} {c['grey']}{ago}{c['reset']}", file=stream)
    print("", file=stream)


def _render_health(health: Health, stream, c: dict, verbose: bool) -> None:
    _section("System", stream, c)
    if not health.known:
        return _unknown(health, stream, c)

    shown = health.findings if verbose else [
        f for f in health.findings
        if getattr(f.severity, "value", f.severity) in ("WARN", "FAIL")]
    if not shown:
        counts = len(health.findings)
        print(f"  {c['green']}ok{c['reset']} all {counts} checks pass\n",
              file=stream)
        return

    for finding in shown:
        severity = getattr(finding.severity, "value", finding.severity)
        print(f"  {_mark(severity, c)}  {finding.title:<24.24} "
              f"{finding.detail}", file=stream)
        if finding.fix and severity in ("WARN", "FAIL"):
            print(f"      {c['grey']}{finding.fix}{c['reset']}", file=stream)
    if not verbose:
        print(f"  {c['grey']}{len(health.findings) - len(shown)} further "
              f"checks pass — dostat -v for all{c['reset']}", file=stream)
    print("", file=stream)


def as_json(state: ServerState) -> str:
    """The same facts, for anything that would otherwise parse the text."""
    def severity_of(finding):
        return getattr(finding.severity, "value", str(finding.severity))

    return json.dumps({
        "hostname": state.hostname,
        "collected_at": state.collected_at,
        "instances": {
            "error": state.instances.error,
            "docker_error": state.instances.docker_error,
            "entries": [{"name": i.name, "database": i.database,
                         "version": i.version, "active": i.active,
                         "running": i.running, "last_run": i.last_run}
                        for i in state.instances.entries],
        },
        "backups": {
            "error": state.backups.error,
            "backup_path": state.backups.backup_path,
            "percent_used": state.backups.disk.percent_used
                            if state.backups.disk else None,
            "entries": [{"database": b.database,
                         "severity": b.severity,
                         "archives": len(b.archives),
                         "newest_age": b.newest.age if b.newest else None,
                         "newest_size": b.newest.size if b.newest else None}
                        for b in state.backups.entries],
        },
        "maintenance": {
            "error": state.maintenance.error,
            "jobs": [{"id": getattr(j, "job_id", ""),
                      "schedule": getattr(j, "schedule", ""),
                      "active": getattr(j, "active", True)}
                     for j in state.maintenance.jobs],
        },
        "health": {
            "error": state.health.error,
            "findings": [{"id": f.check_id, "severity": severity_of(f),
                          "title": f.title, "detail": f.detail}
                         for f in state.health.findings],
        },
    }, indent=2, sort_keys=True)


def worst(state: ServerState) -> str:
    """The most severe thing in the whole report — this drives the exit code."""
    levels = []
    for entry in state.backups.entries:
        levels.append(entry.severity)
    if state.backups.disk:
        levels.append(state.backups.disk.severity)
    for finding in state.health.findings:
        levels.append(getattr(finding.severity, "value", "SKIP"))
    for entry in state.instances.entries:
        if entry.active and entry.running is False:
            levels.append("FAIL")
    if "FAIL" in levels:
        return "FAIL"
    if "WARN" in levels:
        return "WARN"
    return "OK"


# ==============================================================================
# CLI
# ==============================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="What state is this server in? Reads only — every change "
                    "goes through wiz, docron or edbk.")
    parser.add_argument("--home", default=HOME,
                        help="directory holding the configs (default: %(default)s)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="show the checks that pass as well")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable output")
    parser.add_argument("--no-docker", action="store_true",
                        help="skip `docker ps` (faster, container state unknown)")
    parser.add_argument("--no-checks", action="store_true",
                        help="skip the readiness checks")
    parser.add_argument("--version", action="version",
                        version=f"ownerp_state.py {SCRIPT_VERSION} ({SCRIPT_DATE})")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    state = collect(home=args.home, docker=not args.no_docker,
                    checks=not args.no_checks)
    if args.json:
        print(as_json(state))
    else:
        render(state, verbose=args.verbose)
    # 0 clean, 1 something needs attention, 2 something is broken. A cron job
    # can act on that without parsing anything.
    return {"OK": 0, "WARN": 1, "FAIL": 2}[worst(state)]


if __name__ == "__main__":
    sys.exit(main())
