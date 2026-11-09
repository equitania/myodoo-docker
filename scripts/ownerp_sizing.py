#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Title:            ownerp_sizing.py
# Description:      One host-wide calculation of Odoo workers, memory limits and
#                   PostgreSQL memory per hardware and instance role.
# Version:          1.0.0
# Date:             09.11.2026
# Author:           Equitania Software GmbH
# ==============================================================================
# Why this exists:
#   Workers, memory limits and PostgreSQL memory of all instances on a host draw
#   from the same CPUs and the same RAM. Sizing one instance at a time cannot
#   respect that. This module looks at the whole host at once: hardware, the
#   instances and their roles (live / test / demo), and returns one plan.
#
# What it never does:
#   Write anything, import YAML, or refuse. When even the minimal staffing does
#   not fit the RAM budget, the plan is still complete and carries
#   `over_budget = True` plus a warning naming need and budget.
#
# All arithmetic is integer MiB, floored. System Python 3 standard library only.
# ==============================================================================

import json
import math
import os
import re
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Set, Tuple

SCRIPT_VERSION = "1.0.0"
SCRIPT_DATE = "09.11.2026"

MIB = 1048576
PROCESS_MIB = 325          # official guide: memory per Odoo process
USERS_PER_WORKER = 6
DB_MAXCONN = 16
PG_FLOOR_CONNECTIONS = 100

OVERRIDE_KEYS = ("workers", "max_cron_threads", "limit_memory_soft_mb",
                 "limit_memory_hard_mb", "db_maxconn", "pg_shared_buffers_mb",
                 "pg_max_connections")

# role -> (workers, cron, soft MiB, hard MiB) for the fixed-size roles
FIXED_ROLES = {"test": (2, 1, 512, 1200), "demo": (1, 1, 384, 1024)}
PG_WEIGHTS = {"live": 3, "test": 1, "demo": 1}
SHIPPED_WORKERS, SHIPPED_CRON = 3, 2

_BASE_KEYS = ("workers", "max_cron_threads", "limit_memory_soft", "limit_memory_hard", "db_maxconn")
_KEYS_BY_VERSION = {
    16: _BASE_KEYS,
    18: _BASE_KEYS + ("limit_memory_soft_gevent", "limit_memory_hard_gevent", "db_maxconn_gevent"),
    19: _BASE_KEYS + ("db_maxconn_gevent",),
}


class SizingError(Exception):
    """The hardware or the configuration could not be read."""


@dataclass(frozen=True)
class Hardware:
    cpus: int
    ram_mib: int


@dataclass
class Instance:
    name: str
    version: Optional[int]
    role: Optional[str]
    users: Optional[int]
    overrides: Dict[str, int]
    db_container: Optional[str]
    build_dir: str
    conf: Dict[str, str]


@dataclass
class InstanceResult:
    name: str
    role: Optional[str]
    sized: bool
    workers: int
    cron: int
    processes: int
    odoo: Dict[str, str]
    pg: Dict[str, str]
    reasons: List[str]
    warnings: List[str]


@dataclass
class Plan:
    hardware: Hardware
    budget_mib: int
    need_mib: int
    pg_total_mib: int
    results: List[InstanceResult]
    over_budget: bool
    warnings: List[str]


# --- reading ---------------------------------------------------------------

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeError):
        return None


def probe_hardware(root: str = "/") -> Hardware:
    cpuinfo = read_text(os.path.join(root, "proc", "cpuinfo"))
    meminfo = read_text(os.path.join(root, "proc", "meminfo"))
    if cpuinfo is None or meminfo is None:
        raise SizingError("cannot read /proc/cpuinfo or /proc/meminfo")
    cpus = sum(1 for line in cpuinfo.splitlines() if re.match(r"processor\s*:", line))
    match = re.search(r"^MemTotal:\s*(\d+)\s*kB", meminfo, re.M)
    if cpus < 1 or not match:
        raise SizingError("cannot determine CPU count or memory from /proc")
    return Hardware(cpus, int(match.group(1)) // 1024)


def odoo_major(version) -> Optional[int]:
    if version is None or isinstance(version, bool):
        return None
    match = re.match(r"\s*(\d+)", str(version))
    return int(match.group(1)) if match else None


def odoo_keys(version) -> Tuple[str, ...]:
    major = odoo_major(version)
    if major is None:
        return _BASE_KEYS
    eligible = [v for v in _KEYS_BY_VERSION if v <= major]
    return _KEYS_BY_VERSION[max(eligible)] if eligible else _BASE_KEYS


def parse_conf_values(text: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line[0] in "#;[" or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def _as_int(value) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def instances_from_config(containers: List[dict], selected: Optional[str] = None,
                          read_text=read_text) -> List[Instance]:
    result = []
    for entry in containers or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("container_name", ""))
        if entry.get("active", True) is False and name != selected:
            continue
        build_dir = os.path.expandvars(os.path.expanduser(str(entry.get("dockerfile_path", ""))))
        text = read_text(os.path.join(build_dir, "odoo.conf")) if build_dir else None
        block = entry.get("sizing")
        block = block if isinstance(block, dict) else {}
        role = block.get("profile")
        overrides = {}
        for key in OVERRIDE_KEYS:
            number = _as_int(block.get(key))
            if number is not None:
                overrides[key] = number
        result.append(Instance(
            name=name,
            version=odoo_major(entry.get("odoo_version")),
            role=str(role) if role else None,
            users=_as_int(block.get("users")),
            overrides=overrides,
            db_container=entry.get("db_host"),
            build_dir=build_dir,
            conf=parse_conf_values(text) if text is not None else {},
        ))
    return result


# --- calculation -----------------------------------------------------------

def pg_base_profile(hw: Hardware) -> str:
    if hw.cpus >= 8 and hw.ram_mib >= 28 * 1024:
        return "8cpu32gb"
    if hw.cpus >= 4 and hw.ram_mib >= 14 * 1024:
        return "4cpu16gb"
    if hw.ram_mib >= 7 * 1024:
        return "2cpu8gb"
    return "2cpu4gb"


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _need(workers: int, cron: int) -> int:
    return (workers + cron + 1) * PROCESS_MIB


def _blockless_counts(conf: Dict[str, str]) -> Tuple[int, int]:
    workers = _as_int(conf.get("workers"))
    cron = _as_int(conf.get("max_cron_threads"))
    if workers is None or workers < 0:
        return SHIPPED_WORKERS, SHIPPED_CRON
    if workers == 0:
        return 1, 0
    return workers, cron if cron is not None and cron >= 0 else SHIPPED_CRON


class _Slot:
    """Working state of one instance during the calculation."""

    def __init__(self, inst: Instance, warnings: List[str]):
        self.inst = inst
        self.ov: Dict[str, int] = {}
        for key, value in inst.overrides.items():
            minimum = 64 if key.endswith("_mb") else 1
            if value < minimum:
                warnings.append("%s: override %s = %d ignored (minimum %d), computed value kept"
                                % (inst.name, key, value, minimum))
            else:
                self.ov[key] = value
        self.role = inst.role if inst.role in ("live", "test", "demo") else None
        self.workers = 0
        self.cron = 0
        self.soft = 0
        self.hard = 0
        self.reasons: List[str] = []
        self.warnings: List[str] = []

    @property
    def fixed_workers(self) -> bool:
        return "workers" in self.ov


def compute_plan(hw: Hardware, instances: List[Instance]) -> Plan:
    cpus, ram = hw.cpus, hw.ram_mib
    processes_rule = 2 * cpus + 1
    reserve = 1024 + ram // 10
    pg_total = ram // 4
    budget = ram - reserve - pg_total
    cron_live = 2 if cpus >= 8 else 1
    warnings: List[str] = []

    slots = [_Slot(i, warnings) for i in instances]
    live = [s for s in slots if s.role == "live"]
    others_slots = [s for s in slots if s.role != "live"]

    # non-live instances: fixed sizes, or what a blockless conf already uses
    for s in others_slots:
        ov = s.ov
        if s.role in FIXED_ROLES:
            s.workers, s.cron, s.soft, s.hard = FIXED_ROLES[s.role]
            s.soft = ov.get("limit_memory_soft_mb", s.soft)
            s.hard = ov.get("limit_memory_hard_mb", s.hard)
            s.reasons.append("%s profile: %d workers, cron %d, soft %d MiB, hard %d MiB"
                             % (s.role, s.workers, s.cron, s.soft, s.hard))
        else:
            s.workers, s.cron = _blockless_counts(s.inst.conf)
            s.reasons.append("no sizing block: counted with its odoo.conf (%d workers, cron %d)"
                             % (s.workers, s.cron))
        if "workers" in ov:
            s.workers = ov["workers"]
        if "max_cron_threads" in ov:
            s.cron = ov["max_cron_threads"]
    others = sum(s.workers + s.cron for s in others_slots)

    # live instances share what the others leave of the process rule
    n_live = len(live)
    if n_live:
        host_workers = max(2, (processes_rule - others - n_live * cron_live) // n_live)
        for s in live:
            ov = s.ov
            s.cron = ov.get("max_cron_threads", cron_live)
            workers = host_workers
            reason = ("%d workers: %d CPU -> %d processes, other instances use %d, cron %d"
                      % (workers, cpus, processes_rule, others, cron_live))
            users = s.inst.users
            if users and users > 0:
                wanted = math.ceil(users / USERS_PER_WORKER)
                workers = max(2, min(workers, wanted))
                reason = ("%d workers: %d users need %d, %d CPU -> %d processes allow %d"
                          % (workers, users, wanted, cpus, processes_rule, host_workers))
                if wanted > host_workers:
                    msg = ("%s: %d users need %d workers, the host allows %d"
                           % (s.inst.name, users, wanted, host_workers))
                    s.warnings.append(msg)
                    warnings.append("%d users need %d workers, the host allows %d (%s)"
                                    % (users, wanted, host_workers, s.inst.name))
            if "workers" in ov:
                workers = ov["workers"]
                reason = "%d workers: set in the sizing block" % workers
            s.workers = workers
            s.reasons.append(reason)

    def total_need() -> int:
        return sum(_need(s.workers, s.cron) for s in slots)

    # fit into the RAM budget: squeeze the largest live instance, then minimal staffing
    while total_need() > budget:
        squeezable = [s for s in live if s.workers > 2 and not s.fixed_workers]
        if not squeezable:
            break
        max(squeezable, key=lambda s: s.workers).workers -= 1
    if total_need() > budget:
        for s in others_slots:
            if s.workers > 1 and not s.fixed_workers:
                s.workers = 1
                s.reasons.append("1 worker: minimal staffing, the RAM budget is too small")
    need = total_need()
    over = need > budget
    if over:
        if any(s.ov for s in slots):
            warnings.append("Override exceeds the RAM budget: needs %d MiB, budget %d MiB"
                            % (need, budget))
        else:
            warnings.append("over budget: minimal staffing needs %d MiB, budget %d MiB"
                            % (need, budget))
    for s in live:
        s.reasons.append("%d workers after fitting the %d MiB RAM budget" % (s.workers, budget))

    # live memory limits: what the non-live instances leave of the budget
    live_share = budget - sum(_need(s.workers, s.cron) for s in others_slots)
    for s in live:
        ov = s.ov
        soft = _clamp(live_share // (n_live * (s.workers + s.cron + 1)), 600, 2048)
        hard = _clamp(soft * 5 // 4, 1600, 2560)
        s.soft = ov.get("limit_memory_soft_mb", soft)
        s.hard = ov.get("limit_memory_hard_mb", hard)
        s.reasons.append("soft %d MiB / hard %d MiB per process" % (s.soft, s.hard))
        if "limit_memory_soft_mb" in ov and "limit_memory_hard_mb" not in ov:
            s.hard = _clamp(s.soft * 5 // 4, 1600, 2560)

    total = sum(s.workers + s.cron for s in slots)
    if total > processes_rule:
        warnings.append("%d processes > %d (2 x CPU + 1)" % (total, processes_rule))

    # PostgreSQL: split by weight
    weights = [PG_WEIGHTS.get(s.role, 1) if s.role else 1 for s in slots]
    weight_sum = sum(weights) or 1
    results = []
    for s, weight in zip(slots, weights):
        processes = s.workers + s.cron + 1
        sized = s.role is not None
        odoo: Dict[str, str] = {}
        pg: Dict[str, str] = {}
        if sized:
            ov = s.ov
            maxconn = ov.get("db_maxconn", DB_MAXCONN)
            values = {
                "workers": str(s.workers),
                "max_cron_threads": str(s.cron),
                "limit_memory_soft": str(s.soft * MIB),
                "limit_memory_hard": str(s.hard * MIB),
                "db_maxconn": str(maxconn),
                "limit_memory_soft_gevent": str(s.soft * MIB),
                "limit_memory_hard_gevent": str(s.hard * MIB),
                "db_maxconn_gevent": str(maxconn),
            }
            odoo = {k: values[k] for k in odoo_keys(s.inst.version)}
            share = pg_total * weight // weight_sum
            share = ov.get("pg_shared_buffers_mb", share)
            max_conn = ov.get("pg_max_connections",
                              max(PG_FLOOR_CONNECTIONS, processes * DB_MAXCONN + 20))
            pg = {
                "shared_buffers": "%dMB" % share,
                "effective_cache_size": "%dMB" % (3 * share),
                "max_connections": str(max_conn),
                "work_mem": "%dMB" % _clamp(share // (max_conn * 2), 4, 64),
                "maintenance_work_mem": "%dMB" % _clamp(share // 8, 64, 1024),
            }
            s.reasons.append("PostgreSQL: %s shared_buffers (weight %d of %d), %s connections"
                             % (pg["shared_buffers"], weight, weight_sum, max_conn))
        results.append(InstanceResult(
            name=s.inst.name, role=s.inst.role, sized=sized, workers=s.workers,
            cron=s.cron, processes=processes, odoo=odoo, pg=pg,
            reasons=s.reasons, warnings=s.warnings))

    return Plan(hardware=hw, budget_mib=budget, need_mib=need, pg_total_mib=pg_total,
                results=results, over_budget=over, warnings=warnings)


# --- state + decisions -----------------------------------------------------

STATE_NAME = ".sizing_state.json"
CONF_NAME = "odoo.conf"


def load_state(build_dir: str) -> Tuple[dict, Optional[str]]:
    """The per-key decisions of one instance: ({}, None) when there is no file yet."""
    path = os.path.join(build_dir, STATE_NAME)
    if not os.path.exists(path):
        return {}, None
    try:
        with open(path, encoding="utf8") as handle:
            state = json.load(handle)
    except (OSError, ValueError) as error:
        return {}, "cannot read %s: %s" % (path, error)
    if not isinstance(state, dict):
        return {}, "cannot read %s: not a JSON object" % path
    shape = _state_shape_problem(state)
    if shape:
        return {}, "cannot read %s: %s" % (path, shape)
    return state, None


def _state_shape_problem(state: dict) -> Optional[str]:
    for section in ("odoo", "pg"):
        entries = state.get(section, {})
        if not isinstance(entries, dict):
            return "'%s' is not an object" % section
        for key, entry in entries.items():
            if (not isinstance(entry, dict) or entry.get("status") not in ("accepted", "hand")
                    or not isinstance(entry.get("known"), list)
                    or not all(isinstance(v, str) for v in entry["known"])):
                return "invalid entry %s.%s" % (section, key)
    return None


def save_state(build_dir: str, state: dict) -> Optional[str]:
    """Write the state atomically. Returns an error text, or None on success."""
    path = os.path.join(build_dir, STATE_NAME)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp, path)
    except OSError as error:
        return "cannot write %s: %s" % (path, error)
    return None


def ensure_dockerignore(build_dir: str, pattern: str = STATE_NAME) -> None:
    """Keep the state file out of the image build context. Never raises."""
    path = os.path.join(build_dir, ".dockerignore")
    try:
        text = ""
        if os.path.exists(path):
            with open(path, encoding="utf8") as handle:
                text = handle.read()
            if any(line.strip() == pattern for line in text.splitlines()):
                return
        if text and not text.endswith("\n"):
            text += "\n"
        with open(path, "w", encoding="utf8") as handle:
            handle.write(text + pattern + "\n")
    except OSError:
        pass


@dataclass
class KeyDecision:
    key: str
    action: str                  # "write" | "same" | "keep"
    current: Optional[str]
    recommended: str
    note: str


def decide_key(key: str, current: Optional[str], recommended: str, entry: Optional[dict],
               is_default: bool, override: bool = False,
               equal: Callable[[str, str], bool] = lambda a, b: a == b) -> KeyDecision:
    """Decide what to do with one setting; the first matching rule wins."""
    def make(action, note=""):
        return KeyDecision(key, action, current, recommended, note)

    status = entry.get("status") if entry else None
    known = entry.get("known", []) if entry else []
    same = current is not None and equal(current, recommended)
    if override and not same:
        return make("write", "Override")
    if same:
        return make("same")
    if status == "hand":
        return make("keep", "hand-edited")
    if current is None:
        return make("write", "setting absent")
    if status == "accepted" and current in known:
        return make("write", "accepted value follows the recommendation")
    if entry is None and is_default:
        return make("write", "template default")
    note = "differs from the recommendation"
    if entry is None:
        note += "; not reviewed: dosize --review NAME"
    return make("keep", note)


def format_decision(d: KeyDecision) -> str:
    if d.action == "keep":
        return "%s: hand %s, recommended %s - unchanged" % (d.key, d.current, d.recommended)
    if d.action == "write":
        return "%s: %s -> %s" % (d.key, d.current if d.current is not None else "(unset)",
                                 d.recommended)
    return "%s: %s (ok)" % (d.key, d.current)


# --- odoo.conf writer ------------------------------------------------------

def patch_conf_text(text: str, changes: Dict[str, str]) -> str:
    """Replace the line of each changed key in place; append keys that are absent."""
    lines = text.splitlines()
    pending = dict(changes)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped[0] in "#;[" or "=" not in stripped:
            continue
        key = stripped.partition("=")[0].strip()
        if key in changes:
            lines[index] = "%s = %s" % (key, changes[key])
            pending.pop(key, None)
    for key, value in pending.items():
        lines.append("%s = %s" % (key, value))
    return "\n".join(lines) + "\n"


def conf_regression(original: str, patched: str, allowed_keys,
                    values_of: Callable[[str], Dict[str, str]] = parse_conf_values) -> Optional[str]:
    """A reason to refuse the patch, or None when it is safe.

    Every setting must survive with its value; the only permitted difference is
    a value for one of the announced keys.
    """
    before = values_of(original)
    after = values_of(patched)
    allowed = set(allowed_keys)
    for key, value in before.items():
        if key in allowed:
            continue
        if key not in after:
            return "would drop setting: %s" % key
        if after[key] != value:
            return "would change setting: %s" % key
    unexpected = sorted(set(after) - set(before) - allowed)
    if unexpected:
        return "would add setting(s): %s" % ", ".join(unexpected)
    return None


@dataclass
class ConfSync:
    changed: bool
    decisions: List[KeyDecision]
    error: Optional[str]
    backup: Optional[str]


def _remember(state: dict, section: str, decision: KeyDecision) -> None:
    """Record a written or confirmed value as known, so a later change is a hand edit."""
    entries = state.setdefault(section, {})
    entry = entries.get(decision.key)
    if not isinstance(entry, dict):
        entry = entries[decision.key] = {"status": "accepted", "known": []}
    if entry.get("status") == "hand":
        if decision.action != "write":
            return
        entry["status"] = "accepted"     # an override replaced the hand value
    entry["known"] = [decision.recommended]   # only the value now in the file


def sync_odoo_conf(build_dir: str, recommended: Dict[str, str], overrides: Set[str],
                   template_values: Dict[str, str], now=None) -> ConfSync:
    """Bring the recommended settings into <build_dir>/odoo.conf, respecting hand edits."""
    path = os.path.join(build_dir, CONF_NAME)
    try:
        with open(path, encoding="utf8") as handle:
            original = handle.read()
        mode = os.stat(path).st_mode & 0o7777
    except (OSError, ValueError) as error:
        return ConfSync(False, [], "cannot read %s: %s" % (path, error), None)

    state, problem = load_state(build_dir)
    if problem:
        return ConfSync(False, [], "state file unusable, nothing written: %s" % problem, None)
    entries = state.get("odoo")
    entries = entries if isinstance(entries, dict) else {}

    current = parse_conf_values(original)
    decisions = []
    for key, value in recommended.items():
        have = current.get(key)
        entry = entries.get(key) if isinstance(entries.get(key), dict) else None
        is_default = have is not None and have == template_values.get(key)
        decisions.append(decide_key(key, have, value, entry, is_default,
                                    override=key in overrides))
    changes = {d.key: d.recommended for d in decisions if d.action == "write"}

    backup = None
    if changes:
        patched = patch_conf_text(original, changes)
        problem = conf_regression(original, patched, changes)
        if problem:
            return ConfSync(False, decisions, "refusing to patch %s: %s" % (path, problem), None)
        stamp = time.strftime("%Y%m%d_%H%M%S", now if isinstance(now, time.struct_time)
                              else time.localtime(now))
        backup = "%s.bak_%s" % (path, stamp)
        try:
            with open(backup, "w", encoding="utf8") as handle:
                handle.write(original)
        except OSError as error:
            return ConfSync(False, decisions, "cannot write backup %s: %s" % (backup, error), None)
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf8") as handle:
                handle.write(patched)
            os.chmod(tmp, mode)
            os.replace(tmp, path)
        except OSError as error:
            return ConfSync(False, decisions, "cannot write %s: %s" % (path, error), backup)

    before = json.dumps(state, sort_keys=True)
    for d in decisions:
        if d.action == "write" or (d.action == "same" and isinstance(entries.get(d.key), dict)):
            _remember(state, "odoo", d)
    error = None
    if json.dumps(state, sort_keys=True) != before:
        error = save_state(build_dir, state)
        ensure_dockerignore(build_dir)
    return ConfSync(bool(changes), decisions, error, backup)


# --- postgresql.conf writer ------------------------------------------------

PG_RESTART_KEYS = ("shared_buffers", "max_connections")
PG_MEMORY_KEYS = ("shared_buffers", "effective_cache_size", "work_mem", "maintenance_work_mem")
# The four shipped profiles of pg-local-deploy.sh (4 / 8 / 16 / 32 GB): what an
# untouched deployment holds, hence "template default" for decide_key.
PG_PROFILE_VALUES: Dict[str, Tuple[str, ...]] = {
    "shared_buffers": ("1GB", "2GB", "4GB", "8GB"),
    "effective_cache_size": ("3GB", "6GB", "12GB", "24GB"),
    "work_mem": ("4MB", "8MB", "16MB", "32MB"),
    "maintenance_work_mem": ("512MB", "1GB", "2GB", "4GB"),
    "max_connections": ("100", "150", "200", "300"),
}
PG_DATA_DESTINATION = "/var/lib/postgresql/data"
PG_CONF_NAME = "postgresql.conf"
PG_HEADER = "# ownerp_sizing"

Runner = Callable[[List[str]], Tuple[int, str]]

_PG_UNITS = {"kb": 1 / 1024, "mb": 1, "gb": 1024, "tb": 1048576}
_PG_SIZE = re.compile(r"^\s*(\d+)\s*(kB|MB|GB|TB)\s*$", re.IGNORECASE)
_PG_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.]*)\s*(?:=\s*|\s+)(.*)$")


def pg_size_mib(text: str) -> Optional[int]:
    """A PostgreSQL size as whole MiB; None without a unit (a bare number is not guessed)."""
    match = _PG_SIZE.match(text or "")
    if not match:
        return None
    return int(int(match.group(1)) * _PG_UNITS[match.group(2).lower()])


def pg_equal(key: str, a: str, b: str) -> bool:
    if key in PG_MEMORY_KEYS:
        mib_a, mib_b = pg_size_mib(a), pg_size_mib(b)
        if mib_a is not None and mib_b is not None:
            return mib_a == mib_b
    elif key == "max_connections":
        try:
            return int(a) == int(b)
        except (TypeError, ValueError):
            pass
    return a == b


def _pg_value(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("'"):
        end = 1
        while end < len(raw):
            if raw[end] == "'":
                if raw[end + 1:end + 2] == "'":
                    end += 2
                    continue
                break
            end += 1
        return raw[1:end].replace("''", "'")
    return raw.split("#", 1)[0].strip()


def _pg_setting(line: str) -> Optional[Tuple[str, str]]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    match = _PG_LINE.match(stripped)
    if not match:
        return None
    return match.group(1).lower(), _pg_value(match.group(2))


def parse_pg_conf_values(text: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for line in text.splitlines():
        setting = _pg_setting(line)
        if setting:
            values[setting[0]] = setting[1]
    return values


def patch_pg_conf_text(text: str, changes: Dict[str, str]) -> str:
    """Replace the last active line of each key; append absent keys under one header."""
    lines = text.splitlines(keepends=True)
    last: Dict[str, int] = {}
    for index, line in enumerate(lines):
        setting = _pg_setting(line)
        if setting and setting[0] in changes:
            last[setting[0]] = index
    for key, index in last.items():
        old = _pg_setting(lines[index])[1]
        ending = "\r\n" if lines[index].endswith("\r\n") else "\n"
        lines[index] = "%s = %s   %s (was: %s)%s" % (key, changes[key], PG_HEADER, old, ending)
    result = "".join(lines)
    pending = [key for key in changes if key not in last]
    if pending:
        if result and not result.endswith("\n"):
            result += "\n"
        result += "%s\n" % PG_HEADER
        for key in pending:
            result += "%s = %s\n" % (key, changes[key])
    return result


def find_pgdata(mounts_json: str) -> Optional[str]:
    try:
        mounts = json.loads(mounts_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(mounts, list):
        return None
    for mount in mounts:
        if (isinstance(mount, dict) and isinstance(mount.get("Source"), str)
                and str(mount.get("Destination", "")).rstrip("/") == PG_DATA_DESTINATION
                and mount["Source"]):
            return mount["Source"]
    return None


def container_running(name: str, run: Runner) -> Optional[bool]:
    code, out = run(["docker", "inspect", "-f", "{{.State.Running}}", name])
    if code != 0:
        return None
    return out.strip() == "true"


@dataclass
class PgSync:
    changed: bool
    decisions: List[KeyDecision]
    restarted: bool
    verified: Optional[bool]
    rolled_back: bool
    error: Optional[str]
    skipped: Optional[str]


def _replace_file(path: str, data: bytes, mode: int, uid: int, gid: int) -> None:
    """Atomic replace keeping mode and owner; chown failures (not root) are ignored."""
    tmp = path + ".ownerp_tmp"
    with open(tmp, "wb") as handle:
        handle.write(data)
    os.chmod(tmp, mode)
    try:
        os.chown(tmp, uid, gid)
    except OSError:
        pass
    os.replace(tmp, path)


def _wait_ready(db: str, db_user: str, run: Runner, sleep, retries: int) -> bool:
    for attempt in range(retries):
        code, _ = run(["docker", "exec", db, "pg_isready", "-U", db_user, "-d", "postgres"])
        if code == 0:
            return True
        if attempt < retries - 1:
            sleep(5)
    return False


def _verify(db: str, db_user: str, changes: Dict[str, str], run: Runner, sleep,
            attempts: int) -> bool:
    for attempt in range(attempts):
        ok = True
        for key, value in changes.items():
            code, out = run(["docker", "exec", db, "psql", "-U", db_user, "-d", "postgres",
                             "-tAc", "SHOW %s" % key])
            if code != 0 or not pg_equal(key, out.strip(), value):
                ok = False
                break
        if ok:
            return True
        if attempt < attempts - 1:
            sleep(1)      # a reload applies asynchronously
    return False


def _outside_conf_keys(pgdata: str, keys, db: str, db_user: str, run: Runner) -> Set[str]:
    """Keys set by ALTER SYSTEM (postgresql.auto.conf) or the command line: SHOW would
    never show a value written to postgresql.conf for them."""
    found: Set[str] = set()
    try:
        with open(os.path.join(pgdata, "postgresql.auto.conf"), encoding="utf8") as handle:
            found.update(k for k in parse_pg_conf_values(handle.read()) if k in keys)
    except (OSError, ValueError):
        pass
    try:
        names = ", ".join("'%s'" % k for k in keys)
        code, out = run(["docker", "exec", db, "psql", "-U", db_user, "-d", "postgres", "-tAc",
                         "SELECT name, source FROM pg_settings WHERE name IN (%s)" % names])
        if code == 0:
            for line in out.splitlines():
                name, _, source = line.partition("|")
                if source.strip() not in ("", "configuration file", "default") \
                        and name.strip() in keys:
                    found.add(name.strip())
    except Exception:
        pass
    return found


def sync_postgres(db_container: str, recommended: Dict[str, str], overrides: Set[str],
                  state_entry: dict, run: Runner, db_user: str, now=None,
                  sleep=time.sleep, retries: int = 60) -> PgSync:
    """Bring the recommended settings into the database container's postgresql.conf.

    state_entry is the "pg" section of the state file; it is updated IN PLACE after
    a verified change (the caller saves it). The caller guarantees Odoo is stopped.
    """
    def fail(message, decisions=None):
        return PgSync(False, decisions or [], False, None, False, message, None)

    code, out = run(["docker", "inspect", "-f", "{{json .Mounts}}", db_container])
    pgdata = find_pgdata(out) if code == 0 else None
    if pgdata is None:
        return PgSync(False, [], False, None, False, None, "db_host is not a local container")
    if not container_running(db_container, run):
        return PgSync(False, [], False, None, False, None, "database container not running")
    path = os.path.join(pgdata, PG_CONF_NAME)
    try:
        with open(path, "rb") as handle:
            original_bytes = handle.read()
        original = original_bytes.decode("utf8")
        info = os.stat(path)
    except (OSError, ValueError) as error:
        return fail("cannot read %s: %s" % (path, error))
    mode, uid, gid = info.st_mode & 0o7777, info.st_uid, info.st_gid

    problem = _state_shape_problem({"pg": state_entry}) if isinstance(state_entry, dict) \
        else "'pg' is not an object"
    if problem:
        return fail("state unusable, nothing written: %s" % problem)

    current = parse_pg_conf_values(original)
    outside = _outside_conf_keys(pgdata, recommended, db_container, db_user, run)
    decisions = []
    for key, value in recommended.items():
        have = current.get(key)
        if key in outside:
            decisions.append(KeyDecision(
                key, "keep", have, value,
                "set outside postgresql.conf (ALTER SYSTEM or command line) - unchanged"))
            continue
        entry = state_entry.get(key)
        is_default = have is not None and any(
            pg_equal(key, have, known) for known in PG_PROFILE_VALUES.get(key, ()))
        decisions.append(decide_key(key, have, value, entry, is_default,
                                    override=key in overrides,
                                    equal=lambda a, b, k=key: pg_equal(k, a, b)))
    changes = {d.key: d.recommended for d in decisions if d.action == "write"}

    def remember():
        wrapper = {"pg": state_entry}
        for d in decisions:
            if d.action == "write" or (d.action == "same"
                                       and isinstance(state_entry.get(d.key), dict)):
                _remember(wrapper, "pg", d)

    if not changes:
        remember()
        return PgSync(False, decisions, False, None, False, None, None)

    patched = patch_pg_conf_text(original, changes)
    problem = conf_regression(original, patched, changes, values_of=parse_pg_conf_values)
    if problem:
        return fail("refusing to patch %s: %s" % (path, problem), decisions)

    stamp = time.strftime("%Y%m%d_%H%M%S", now if isinstance(now, time.struct_time)
                          else time.localtime(now))
    backup = "%s.bak_%s" % (path, stamp)
    try:
        _replace_file(backup, original_bytes, mode, uid, gid)
        _replace_file(path, patched.encode("utf8"), mode, uid, gid)
    except OSError as error:
        return fail("cannot write %s: %s" % (path, error), decisions)

    restart = any(key in PG_RESTART_KEYS for key in changes)
    problem = None
    good = False
    try:
        if restart:
            try:      # shorten the shutdown checkpoint; failure is not fatal
                run(["docker", "exec", db_container, "psql", "-U", db_user, "-d", "postgres",
                     "-tAc", "CHECKPOINT"])
            except Exception:
                pass
            applied, _ = run(["docker", "restart", "-t", "120", db_container])
        else:
            applied, _ = run(["docker", "kill", "--signal=HUP", db_container])
        good = applied == 0 and _wait_ready(db_container, db_user, run, sleep, retries)
        if good:
            good = _verify(db_container, db_user, changes, run, sleep, 1 if restart else 4)
    except Exception as error:
        problem = "%s: %s" % (type(error).__name__, error)
    if good:
        remember()
        return PgSync(True, decisions, restart, True, False, None, None)

    # rollback: the backup bytes come back, the database restarts on them
    try:
        _replace_file(path, original_bytes, mode, uid, gid)
    except OSError as error:
        return PgSync(False, decisions, restart, False, False,
                      "new settings were not accepted and the backup could not be restored "
                      "(%s); restore %s by hand" % (error, backup), None)
    try:
        run(["docker", "restart", "-t", "120", db_container])
        up = _wait_ready(db_container, db_user, run, sleep, retries)
    except Exception as error:
        up = False
        problem = "%s (rollback restart: %s: %s)" % (problem or "settings not accepted",
                                                     type(error).__name__, error)
    cause = " (%s)" % problem if problem else ""
    if up:
        message = ("the database did not accept the new settings%s; rolled back, "
                   "the old values are active again" % cause)
    else:
        message = ("the database did not accept the new settings%s; rolled back to the old "
                   "postgresql.conf, but the database is not answering - check it" % cause)
    return PgSync(False, decisions, restart, False, True, message, None)
