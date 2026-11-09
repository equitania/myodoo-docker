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

import math
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

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
