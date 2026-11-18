#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Title:            ownerp_pg_update.py
# Description:      Update PostgreSQL containers to the newest patch release of
#                   their major version, keeping the Debian base they run on.
# Version:          1.0.0
# Date:             18.11.2026
# Author:           Equitania Software GmbH
# ==============================================================================
# Why this exists:
#   A minor update of PostgreSQL is a new image on the same data directory. The
#   hard part is choosing the right image: on Docker Hub the plain tag
#   `postgres:16.x` is the bookworm image up to 16.8 and the trixie image from
#   16.9 on. A base change alters text collation, so this tool always pins the
#   base the running container already has.
#
# Called bare on a terminal it shows every PostgreSQL container with a
# recommendation and asks which ones to update; `--json` prints the same facts
# for an agent; `--container NAME --no-input` runs without questions.
#
# The code finds the PostgreSQL containers, reads the running server version
# and the base, pairs them with their Odoo containers and chooses the tag to
# update to. Phase 1 (prepare) checks one target and pulls or builds the image;
# backup writes the dumps. Neither changes a container. Phase 2 (update_one)
# switches to the new image, verifies it and undoes the switch on any failure;
# rollback goes back to the parked old server later. The old container is only
# ever renamed, never removed.
#
# System Python 3 with python3-yaml only, like the other delivered scripts.
# ==============================================================================

import argparse
import datetime
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Optional, Set, Tuple

import yaml

SCRIPT_VERSION = "1.0.0"
SCRIPT_DATE = "18.11.2026"

Runner = Callable[[List[str]], Tuple[int, str]]
Fetch = Callable[[str], Optional[str]]          # url -> body, None on any failure

POSTGRES_REPOSITORY = "postgres"
PGVECTOR_REPOSITORY = "postgres-pgvector"
HUB_TAGS_URL = ("https://hub.docker.com/v2/repositories/library/postgres/tags"
                "?name=%d.&page_size=100")
HUB_MAX_PAGES = 10
HUB_TIMEOUT = 15


@dataclass
class Base:
    libc: str                 # "glibc 2.36" or "musl 1.2.5"
    codename: Optional[str]   # "bookworm", "trixie"; None for alpine/unknown


@dataclass
class OdooInfo:
    name: str
    image: str
    running: bool
    version: Optional[str]
    database: Optional[str]
    workers: Optional[int]
    has_sizing: bool


@dataclass
class PgTarget:
    name: str
    image: str
    inspect: dict
    version: Optional[Tuple[int, int]]      # (16, 8) from the running server
    base: Optional[Base]
    kind: str                               # "compose" | "legacy"
    compose_file: Optional[str]
    compose_service: Optional[str]
    db_user: Optional[str]
    pgdata: Optional[str]
    odoo: List[OdooInfo] = field(default_factory=list)
    others: List[str] = field(default_factory=list)
    shared: bool = False
    vector: bool = False
    foreign: bool = False
    compose_project: Optional[str] = None   # label com.docker.compose.project (compose kind)
    compose_files: List[str] = field(default_factory=list)   # every file the project was read from


@dataclass
class Choice:
    tag: Optional[str]          # full image reference to switch to, None = nothing
    version: Optional[Tuple[int, int]]
    note: str                   # one line for the plan / overview
    blocked: Optional[str] = None   # reason the update cannot run


# --- sibling scripts ----------------------------------------------------------

def load_sibling(name: str):
    """A script from this script's own folder as a module; None when missing or broken."""
    module = sys.modules.get(name)
    if module is not None:
        return module
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".py")
        if not os.path.isfile(path):
            return None
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module          # dataclasses look the module up
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
        return module
    except Exception:
        return None


def _need(name: str):
    module = load_sibling(name)
    if module is None:
        raise RuntimeError("%s.py is missing next to ownerp_pg_update.py" % name)
    return module


def default_runner(argv: List[str]) -> Tuple[int, str]:
    return _need("ownerp_sizing").default_runner(argv)


# --- server version, user, base -----------------------------------------------

def server_version(name: str, user: str, run: Runner) -> Optional[Tuple[int, int]]:
    """(major, minor) the running server reports; None when it does not answer."""
    code, out = run(["docker", "exec", name, "psql", "-U", user, "-d", "postgres",
                     "-Atc", "SHOW server_version"])
    if code != 0:
        return None
    match = re.match(r"\s*(\d+)\.(\d+)", out)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def db_user_for(inspect: dict, update_cfg: dict, cli_user: Optional[str],
                run: Runner) -> Optional[str]:
    """First user the server accepts: CLI, POSTGRES_USER, docker2update.yaml, postgres."""
    migrate = _need("ownerp_migrate")
    name = migrate._name_of(inspect)
    candidates: List[Optional[str]] = [cli_user, migrate._env_of(inspect).get("POSTGRES_USER")]
    for entry in (update_cfg or {}).get("containers") or []:
        if isinstance(entry, dict) and entry.get("db_host") == name:
            candidates.append(entry.get("db_user"))
    candidates.append("postgres")
    tried: Set[str] = set()
    for user in candidates:
        if not user or user in tried:
            continue
        tried.add(user)
        if server_version(name, user, run) is not None:
            return user
    return None


def _unquote(value: str) -> str:
    return value.strip().strip('"').strip("'")


def _parse_base(os_release: str, ldd_line: str) -> Base:
    fields: Dict[str, str] = {}
    for line in os_release.splitlines():
        key, sep, value = line.partition("=")
        if sep and re.match(r"^[A-Z_]+$", key.strip()):
            fields[key.strip()] = _unquote(value)
    if fields.get("ID") == "alpine":
        return Base("musl " + fields.get("VERSION_ID", "unknown"), None)
    found = re.search(r"(\d+\.\d+)\s*$", ldd_line.strip())
    libc = "glibc " + found.group(1) if found else "glibc unknown"
    return Base(libc, fields.get("VERSION_CODENAME") or None)


def base_of_container(name: str, run: Runner) -> Optional[Base]:
    code, release = run(["docker", "exec", name, "cat", "/etc/os-release"])
    if code != 0:
        return None
    _, ldd = run(["docker", "exec", name, "sh", "-c", "ldd --version 2>&1 | head -n1"])
    return _parse_base(release, ldd)


def base_of_image(image: str, run: Runner) -> Optional[Base]:
    code, out = run(["docker", "run", "--rm", "--entrypoint", "sh", image, "-c",
                     "cat /etc/os-release; ldd --version 2>&1 | head -n1"])
    if code != 0:
        return None
    lines = [line for line in out.splitlines() if line.strip()]
    ldd = next((line for line in reversed(lines) if "=" not in line), "")
    return _parse_base(out, ldd)


# --- discovery ----------------------------------------------------------------

def _is_running(inspect: dict) -> bool:
    return bool((inspect.get("State") or {}).get("Running"))


def _inspect_all(run: Runner) -> List[dict]:
    code, out = run(["docker", "ps", "-aq"])
    if code != 0 or not out.strip():
        return []
    code, out = run(["docker", "inspect"] + out.split())
    if code != 0:
        return []
    try:
        data = json.loads(out)
    except ValueError:
        return []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _user_networks(inspect: dict) -> Set[str]:
    migrate = _need("ownerp_migrate")
    return {n for n in migrate._networks(inspect) if n not in ("bridge", "host", "none")}


def _compose_of(inspect: dict) -> Tuple[str, Optional[str], Optional[str]]:
    labels = (inspect.get("Config") or {}).get("Labels") or {}
    files = labels.get("com.docker.compose.project.config_files")
    if files:
        first = files.split(",")[0].strip()
        return "compose", first or None, labels.get("com.docker.compose.service")
    return "legacy", None, None


def _compose_extra(inspect: dict) -> Tuple[Optional[str], List[str]]:
    """(project name, all config files) from the compose labels; (None, []) for a plain container."""
    labels = (inspect.get("Config") or {}).get("Labels") or {}
    files = [f.strip() for f in (labels.get("com.docker.compose.project.config_files")
                                 or "").split(",") if f.strip()]
    return labels.get("com.docker.compose.project") or None, files


def _first_database(name: str, user: str, run: Runner) -> Optional[str]:
    migrate = _need("ownerp_migrate")
    code, out = run(["docker", "exec", name, "psql", "-U", user, "-d", "postgres", "-Atqc",
                     "SELECT datname FROM pg_database WHERE datistemplate = false"])
    if code != 0:
        return None
    for line in out.splitlines():
        line = line.strip()
        if line and line not in migrate.SYSTEM_DATABASES:
            return line
    return None


def _odoo_version(pg_name: str, user: str, database: str, run: Runner) -> Optional[str]:
    code, out = run(["docker", "exec", pg_name, "psql", "-U", user, "-d", database, "-Atqc",
                     "SELECT latest_version FROM ir_module_module WHERE name = 'base'"])
    if code != 0 or not out.strip():
        return None
    head = out.strip().splitlines()[0].split(".")[0]
    return head if head.isdigit() else None


def _yaml_entry(update_cfg: dict, name: str) -> Optional[dict]:
    for entry in (update_cfg or {}).get("containers") or []:
        if isinstance(entry, dict) and (entry.get("container_name") or entry.get("name")) == name:
            return entry
    return None


def _workers_of(entry: Optional[dict]) -> Optional[int]:
    sizing = entry.get("sizing") if entry else None
    if isinstance(sizing, dict) and isinstance(sizing.get("workers"), int):
        return sizing["workers"]
    return None


def discover(run: Runner, update_cfg: dict, cli_user: Optional[str] = None) -> List[PgTarget]:
    """Every running PostgreSQL container with version, base and its Odoo containers."""
    migrate = _need("ownerp_migrate")
    sizing = _need("ownerp_sizing")
    update_cfg = update_cfg or {}
    everything = _inspect_all(run)
    odoo_all = [c for c in everything if migrate.is_odoo(c)]
    pg_all = [c for c in everything if migrate.is_postgres(c) and not migrate.is_odoo(c)]
    by_name = {migrate._name_of(c): c for c in everything}
    targets: List[PgTarget] = []
    for inspect in pg_all:
        if not _is_running(inspect):
            continue
        name = migrate._name_of(inspect)
        repository = migrate._image_of(inspect)
        user = db_user_for(inspect, update_cfg, cli_user, run)
        kind, compose_file, compose_service = _compose_of(inspect)
        compose_project, compose_files = _compose_extra(inspect)
        target = PgTarget(
            name=name,
            image=(inspect.get("Config") or {}).get("Image") or "",
            inspect=inspect,
            version=server_version(name, user, run) if user else None,
            base=base_of_container(name, run),
            kind=kind, compose_file=compose_file, compose_service=compose_service,
            db_user=user,
            pgdata=sizing.find_pgdata(json.dumps(inspect.get("Mounts") or [])),
            vector=repository == PGVECTOR_REPOSITORY,
            foreign=repository not in (POSTGRES_REPOSITORY, PGVECTOR_REPOSITORY),
            compose_project=compose_project, compose_files=compose_files,
        )
        paired = [o for o in odoo_all if migrate._pair_database_container(o, pg_all) is inspect]
        entries = [e for e in update_cfg.get("containers") or []
                   if isinstance(e, dict) and e.get("db_host") == name]
        names = [migrate._name_of(o) for o in paired]
        names += [e.get("container_name") or e.get("name") for e in entries]
        seen: Set[str] = set()
        for odoo_name in names:
            if not odoo_name or odoo_name in seen:
                continue
            seen.add(odoo_name)
            container = by_name.get(odoo_name)
            entry = _yaml_entry(update_cfg, odoo_name)
            database = (entry or {}).get("database_name")
            if database is None and user:
                database = _first_database(name, user, run)
            version = _odoo_version(name, user, database, run) if user and database else None
            image = ((container.get("Config") or {}).get("Image") or "") if container else ""
            target.odoo.append(OdooInfo(
                name=odoo_name, image=image,
                running=_is_running(container) if container else False,
                version=version, database=database,
                workers=_workers_of(entry),
                has_sizing=isinstance((entry or {}).get("sizing"), dict)))
        target.shared = len(target.odoo) > 1
        networks = _user_networks(inspect)
        target.others = sorted(
            migrate._name_of(c) for c in everything
            if c is not inspect and not migrate.is_odoo(c) and not migrate.is_postgres(c)
            and networks & _user_networks(c))
        targets.append(target)
    return targets


# --- registry -----------------------------------------------------------------

def _http_get(url: str) -> Optional[str]:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(request, timeout=HUB_TIMEOUT) as response:
            return response.read().decode("utf-8", "replace")
    except Exception:
        return None


def hub_tags(major: int, fetch: Fetch = _http_get) -> Optional[Set[str]]:
    """All Docker Hub tag names of one postgres major; None when the first page fails."""
    url: Optional[str] = HUB_TAGS_URL % major
    tags: Set[str] = set()
    for page in range(HUB_MAX_PAGES):
        if not url:
            break
        body = fetch(url)
        try:
            data = json.loads(body) if body else None
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except ValueError:
            return None if page == 0 else tags
        for item in data.get("results") or []:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                tags.add(item["name"])
        url = data.get("next")
    return tags


# --- choice -------------------------------------------------------------------

def _tag_suffix(image: str) -> str:
    """Everything after `M[.n]` in the running tag: "" for 16.8, "-alpine" for 16.8-alpine."""
    _, sep, tail = image.rpartition(":")
    if not sep or "/" in tail:
        return ""
    match = re.match(r"^\d+(?:\.\d+)?(.*)$", tail)
    return match.group(1) if match else ""


def choose(target: PgTarget, tags: Optional[Set[str]], to: Optional[str]) -> Choice:
    """The image to switch to; the running base is always kept."""
    if target.foreign:
        return Choice(None, None, "not maintained by this tool",
                      blocked="image %s is not maintained by this tool" % target.image)
    if to:
        asked = re.match(r"^(\d+)\.(\d+)(-.+)?$", to)
        if not asked:
            return Choice(None, None, "invalid --to value",
                          blocked="--to must look like X.Y or X.Y-suffix, got %r" % to)
        if target.version is not None and int(asked.group(1)) != target.version[0]:
            return Choice(None, None, "major upgrades are not supported",
                          blocked="major upgrades are not supported")
    if target.version is None:
        return Choice(None, None, "running version unknown",
                      blocked="the running server version could not be read")
    major, minor = target.version
    codename = target.base.codename if target.base else None
    suffix = _tag_suffix(target.image)
    repository = PGVECTOR_REPOSITORY if target.vector else POSTGRES_REPOSITORY

    def pinned(k: int) -> str:
        return "%d.%d-%s" % (major, k, codename) if codename else "%d.%d%s" % (major, k, suffix)

    if to:
        k = int(asked.group(2))
        if k <= minor:
            if k == minor:
                return Choice(None, None, "current")
            return Choice(None, None, "downgrade refused",
                          blocked="%s is older than the running %d.%d" % (to, major, minor))
        name = to if asked.group(3) else pinned(k)
        if tags is not None and name not in tags:
            return Choice(None, None, "tag not found",
                          blocked="tag %s does not exist on the registry" % name)
        return Choice("%s:%s" % (repository, name), (major, k),
                      "%d.%d -> %d.%d (requested)" % (major, minor, major, k))
    if tags is None:
        return Choice(None, None, "unknown (no registry access)")
    newer = [k for k in range(minor + 1, 1000) if pinned(k) in tags]
    if newer:
        k = newer[-1]
        return Choice("%s:%s" % (repository, pinned(k)), (major, k),
                      "%d.%d -> %d.%d (base %s kept)" % (major, minor, major, k,
                                                         codename or "unchanged"))
    plain = sorted(int(m.group(1)) for m in
                   (re.match(r"^%d\.(\d+)$" % major, t) for t in tags)
                   if m and int(m.group(1)) > minor)
    if plain:
        k = plain[-1]
        return Choice("%s:%d.%d" % (repository, major, k), (major, k),
                      "%d.%d -> %d.%d; no pinned tag found, confirm the base after the pull"
                      % (major, minor, major, k))
    return Choice(None, None, "current")


# --- recommendations ----------------------------------------------------------

# First month in which a major no longer gets fixes ("MM/YYYY").
EOL = {12: "11/2024", 13: "11/2025", 14: "11/2026", 15: "11/2027",
       16: "11/2028", 17: "11/2029", 18: "11/2030"}


@dataclass
class Rec:
    id: str
    text: str


@dataclass
class SizingView:
    recommended: Dict[str, str]
    current: Dict[str, str]
    differs: Dict[str, Tuple[str, str]]     # key -> (current, recommended)
    skipped: Optional[str]                  # e.g. "shared container", "role unknown"
    overrides: Set[str] = field(default_factory=set)    # settings an applied override pins


def sizing_view(target: PgTarget, update_cfg: dict, role: Optional[str], run: Runner,
                hardware=None) -> SizingView:
    """Calculated PostgreSQL memory values against the running ones; informs only."""
    if target.shared:
        return SizingView({}, {}, {}, "shared container")
    sizing = _need("ownerp_sizing")
    containers = [c for c in (update_cfg or {}).get("containers") or [] if isinstance(c, dict)]
    instances = sizing.instances_from_config(containers)
    # Same selection as ownerp_sizing._run_pg: match on db_container alone.
    match = next((i for i in instances if i.db_container == target.name), None)
    if match is None:
        if role not in sizing.PG_WEIGHTS:
            return SizingView({}, {}, {}, "role unknown")
        match = sizing.Instance(name=target.name, version=None, role=role, users=None,
                                overrides={}, db_container=target.name, build_dir="", conf={})
        instances.append(match)
    elif match.role not in sizing.PG_WEIGHTS:       # no usable profile: the role fills in
        if role not in sizing.PG_WEIGHTS:
            return SizingView({}, {}, {}, "role unknown")
        match.role = role
    current = sizing.pg_current_values(target.name, run, target.db_user or "postgres")
    if current is None:
        return SizingView({}, {}, {}, "current values unreadable")
    try:
        plan = sizing.compute_plan(hardware if hardware is not None else sizing.probe_hardware(),
                                   instances)
    except sizing.SizingError as exc:
        return SizingView({}, current, {}, "sizing unavailable: %s" % exc)
    recommended = dict(plan.results[instances.index(match)].pg)
    differs = {key: (current[key], value) for key, value in recommended.items()
               if key in current and not sizing.pg_equal(key, current[key], value)}
    return SizingView(recommended, current, differs, None,
                      sizing.override_conf_keys(plan.results[instances.index(match)], "pg"))


def backup_routes(databases: List[str], backup_cfg: Optional[dict],
                  container: str) -> Tuple[List[str], List[str]]:
    """(listed, unlisted): databases container2backup.yaml covers via this container."""
    covered = {str(e.get("name")) for e in (backup_cfg or {}).get("databases") or []
               if isinstance(e, dict) and e.get("sql_container") == container}
    return ([d for d in databases if d in covered],
            [d for d in databases if d not in covered])


def collation_mismatches(target: PgTarget, run: Runner) -> Optional[List[str]]:
    """Databases whose recorded collation version differs from the library's (major >= 15).

    [] means "no mismatch" (and, below major 15, "nothing to check"); None means the
    query failed, so the state is unknown.
    """
    if target.version is None or target.version[0] < 15:
        return []
    code, out = run(["docker", "exec", target.name, "psql", "-U", target.db_user or "postgres",
                     "-d", "postgres", "-Atqc",
                     "SELECT datname FROM pg_database WHERE datcollversion IS DISTINCT FROM "
                     "pg_database_collation_actual_version(oid) AND datcollversion IS NOT NULL"])
    if code != 0:
        return None
    return [line.strip() for line in out.splitlines() if line.strip()]


def _eol_month(major: int) -> Optional[datetime.date]:
    match = re.match(r"^(\d{2})/(\d{4})$", EOL.get(major) or "")
    return datetime.date(int(match.group(2)), int(match.group(1)), 1) if match else None


def recommend(target: PgTarget, choice: Choice, sizing: SizingView, unlisted: List[str],
              today: datetime.date, collation_mismatch: Optional[List[str]]) -> List[Rec]:
    """Fixed set of hints in a fixed order; nothing here runs anything."""
    recs: List[Rec] = []
    if target.foreign and choice.blocked:
        recs.append(Rec("foreign_image", "foreign image %s: this tool cannot update it"
                        % target.image))
    eol = _eol_month(target.version[0]) if target.version else None
    if eol is not None and eol <= today:
        recs.append(Rec("major_eol", "PostgreSQL %d is out of support since %s; plan a major "
                        "upgrade separately" % (target.version[0], EOL[target.version[0]])))
    if choice.tag:
        codename = target.base.codename if target.base else None
        stays = " (stays on %s)" % codename if codename and choice.tag.endswith("-" + codename) else ""
        recs.append(Rec("patch_update", "patch update available: %s%s" % (choice.tag, stays)))
    if target.kind == "legacy":
        recs.append(Rec("convert_compose", "convert to a compose-managed container"))
    if sizing.differs:
        listing = ", ".join("%s %s -> %s" % (key, cur, rec)
                            for key, (cur, rec) in sorted(sizing.differs.items()))
        recs.append(Rec("sizing_differs", "memory settings differ from the calculation: " + listing))
    if target.shared:
        recs.append(Rec("shared_db", "database container is shared; memory settings stay"))
    if unlisted:
        recs.append(Rec("backup_missing", "not covered by container2backup.yaml: "
                        + ", ".join(unlisted)))
    if collation_mismatch:
        recs.append(Rec("collation_mismatch", "collation version already mismatched in: "
                        + ", ".join(collation_mismatch)))
    return recs


# --- overview, JSON, selection --------------------------------------------------

Row = Tuple[PgTarget, Choice, List[Rec]]


def _version_text(version: Optional[Tuple[int, int]]) -> Optional[str]:
    return "%d.%d" % version if version else None


def _update_cell(choice: Choice) -> str:
    if choice.tag:
        return choice.tag.partition(":")[2] or choice.tag
    return choice.note


def _odoo_cell(target: PgTarget) -> str:
    if not target.odoo:
        return "-"
    cells = []
    for info in target.odoo:
        parts = [p for p in (info.version,
                             "db %s" % info.database if info.database else None,
                             "%d workers" % info.workers if info.workers is not None else None) if p]
        cells.append("%s (%s)" % (info.name, ", ".join(parts)) if parts else info.name)
    return ", ".join(cells) + (" (shared)" if target.shared else "")


SELECT_PROMPT = "Select (e.g. 1,3 - a for all recommended - Enter to leave):"


def render_overview(rows: List[Row], prompt: bool = True) -> str:
    header = ("#", "PostgreSQL", "Version", "Update", "Kind", "Odoo")
    body = [(str(n), t.name, _version_text(t.version) or "?", _update_cell(c), t.kind,
             _odoo_cell(t)) for n, (t, c, _) in enumerate(rows, 1)]
    # Only the first five columns are padded; the Odoo column is last and stays ragged.
    widths = [max(len(r[i]) for r in [header] + body) for i in range(5)]

    def line(cells) -> str:
        return " " + "  ".join(cells[i].rjust(widths[i]) if i == 0 else cells[i].ljust(widths[i])
                               for i in range(5)) + "  " + cells[5]

    out = [line(header)] + [line(r) for r in body] + [""]
    for n, (_, _, recs) in enumerate(rows, 1):
        out.append(" %d  %s" % (n, "; ".join(r.text for r in recs) if recs else "nothing to do"))
    if prompt:
        out += ["", SELECT_PROMPT]
    return "\n".join(out)


def overview_json(rows: List[Row]) -> dict:
    containers = []
    for target, choice, recs in rows:
        containers.append({
            "name": target.name,
            "image": target.image,
            "version": _version_text(target.version),
            "base": {"libc": target.base.libc, "codename": target.base.codename}
            if target.base else None,
            "kind": target.kind,
            "compose_file": target.compose_file,
            "update": {"available": bool(choice.tag), "image": choice.tag,
                       "version": _version_text(choice.version), "note": choice.note,
                       "blocked": choice.blocked,
                       "release_notes": release_note_links(target.version, choice.version)
                       if choice.tag and target.version and choice.version else []},
            "odoo": [{"name": o.name, "image": o.image, "running": o.running,
                      "version": o.version, "database": o.database, "workers": o.workers,
                      "has_sizing": o.has_sizing} for o in target.odoo],
            "other_clients": list(target.others),
            "shared": target.shared,
            "recommendations": [{"id": r.id, "text": r.text} for r in recs],
        })
    return {"tool": "ownerp_pg_update", "version": SCRIPT_VERSION, "containers": containers}


def parse_selection(text: str, count: int, recommended: Set[int]) -> Optional[List[int]]:
    """1-based numbers from `1,3` / `1 3`, `a` for all recommended, `` for none; else None."""
    text = text.strip().lower()
    if not text:
        return []
    if text == "a":
        return sorted(recommended)
    chosen: List[int] = []
    for token in re.split(r"[,\s]+", text):
        if not token.isdecimal() or not 1 <= int(token) <= count:
            return None
        if int(token) not in chosen:
            chosen.append(int(token))
    return chosen


# ── Compose file derived from a running container ────────────────────────────

# Same text as the Dockerfile that pg-local-deploy.sh writes for pgvector.
VECTOR_DOCKERFILE = """ARG PG_VERSION
FROM postgres:${PG_VERSION}
RUN apt-get update \\
 && apt-get install -y --no-install-recommends "postgresql-${PG_MAJOR}-pgvector" \\
 && rm -rf /var/lib/apt/lists/*
"""

DEFAULT_PGDATA = "/var/lib/postgresql/data"
DEFAULT_SHM_SIZE = 64 * 1024 * 1024
SERVICE = "postgres"
_ANONYMOUS_VOLUME = re.compile(r"^[0-9a-f]{64}$")
_SECRET_KEY = re.compile(r"^(\s*)([A-Za-z0-9_.-]*(?:PASSWORD|SECRET|KEY)[A-Za-z0-9_.-]*)"
                         r"(\s*:\s*)(\S.*)$", re.IGNORECASE)


def deploy_dir_for(name: str, pgdata_mount: dict, home: str) -> str:
    """Where the compose file of a converted container lives."""
    if pgdata_mount.get("Type") == "bind" and pgdata_mount.get("Source"):
        source = str(pgdata_mount["Source"]).rstrip("/") or "/"
        return os.path.join(os.path.dirname(source), name + "-deploy")
    return os.path.join(home, "pg-deploy", name)


def _dest(path: str) -> str:
    return str(path).rstrip("/") or "/"


def _escape(value):
    """Compose interpolates `$` in every string value; `$$` keeps it literal."""
    if isinstance(value, str):
        return value.replace("$", "$$")
    if isinstance(value, list):
        return [_escape(item) for item in value]
    if isinstance(value, dict):
        return {key: _escape(item) for key, item in value.items()}
    return value


def _duration(nanoseconds: int) -> str:
    if nanoseconds % 1000000000 == 0:
        return "%ds" % (nanoseconds // 1000000000)
    if nanoseconds % 1000000 == 0:
        return "%dms" % (nanoseconds // 1000000)
    return "%dns" % nanoseconds


def _restart_of(policy: dict) -> str:
    name = (policy or {}).get("Name") or "no"
    retries = (policy or {}).get("MaximumRetryCount") or 0
    if name == "on-failure" and retries:
        return "on-failure:%d" % retries
    return name


def _healthcheck_of(config: dict, db_user: str) -> dict:
    found = config.get("Healthcheck") or {}
    test = found.get("Test") or []
    if test == ["NONE"]:
        return {"disable": True}
    if not test:
        return {"test": ["CMD-SHELL", "pg_isready -U %s -d postgres" % db_user],
                "interval": "10s", "timeout": "5s", "retries": 5, "start_period": "30s"}
    result = {"test": list(test)}
    for source, target in (("Interval", "interval"), ("Timeout", "timeout"),
                           ("StartPeriod", "start_period"),
                           ("StartInterval", "start_interval")):
        if found.get(source):
            result[target] = _duration(int(found[source]))
    if found.get("Retries"):
        result["retries"] = int(found["Retries"])
    return result


# HostConfig keys the conversion writes into the compose file (or checks itself).
_HOST_CARRIED = {"RestartPolicy", "ShmSize", "Memory", "NanoCpus", "PortBindings",
                 "ExtraHosts", "Dns", "DnsSearch", "LogConfig", "NetworkMode", "Init",
                 "Sysctls", "GroupAdd", "ReadonlyRootfs", "CpuShares", "CpusetCpus",
                 "MemorySwap", "MemorySwappiness"}
# Keys whose value never matters (covered elsewhere, or only runtime hints).
_HOST_ANYTHING = {"Binds", "ContainerIDFile", "ConsoleSize", "MaskedPaths", "ReadonlyPaths"}
# Keys that may hold these values and still mean "docker's default". Empty values
# (None, False, 0, "", [], {}) are always the default and need no entry.
_HOST_DEFAULTS = {
    "Runtime": ("runc",),
    "CgroupnsMode": ("private", "host"),
    "PidMode": ("private", "shareable"),
    "IpcMode": ("private", "shareable"),
    "PidsLimit": (-1,),
}


def _mount_suffix(mount: dict) -> str:
    """The `:mode` part of a volume string; an unusual mode (SELinux `z`) is kept as given."""
    mode = mount.get("Mode") or ""
    if mode in ("", "rw", "ro"):
        return "" if mount.get("RW", True) else ":ro"
    if not mount.get("RW", True) and "ro" not in mode.split(","):
        mode += ",ro"
    return ":" + mode


def compose_from_inspect(inspect: dict, image_inspect: dict, new_image: str,
                         db_user: str, vector_context: Optional[str] = None
                         ) -> Tuple[Optional[dict], List[str]]:
    """The compose document that recreates a running container with a new image.

    Every setting is carried over; one this function cannot carry over is
    returned as a blocker instead of being dropped. With blockers the document
    is None.
    """
    config = inspect.get("Config") or {}
    host = inspect.get("HostConfig") or {}
    image_config = image_inspect.get("Config") or {}
    blockers: List[str] = []
    warnings: List[str] = []

    # Fail closed: every HostConfig key is carried, a known default, or a blocker.
    for key, value in host.items():
        if key in _HOST_CARRIED or key in _HOST_ANYTHING:
            continue
        if not value or value in _HOST_DEFAULTS.get(key, ()):
            continue
        blockers.append("%s is set (%s) and cannot be carried over to the compose file."
                        % (key, value))
    network_mode = host.get("NetworkMode") or ""
    if network_mode == "host" or network_mode.startswith("container:"):
        blockers.append("NetworkMode is set (%s) and cannot be carried over to the "
                        "compose file." % network_mode)

    # Environment: what the container has on top of the image.
    image_env = set(image_config.get("Env") or [])
    environment: Dict[str, str] = {}
    pgdata = DEFAULT_PGDATA
    for entry in config.get("Env") or []:
        key, _, value = entry.partition("=")
        if key == "PGDATA":
            pgdata = _dest(value) if value else DEFAULT_PGDATA
        if entry in image_env or key == "PGDATA":
            continue
        environment[key] = value
    env_out = dict([("PGDATA", pgdata)] + list(environment.items()))

    # Mounts: the data mount decides everything, an empty database is the worst case.
    volumes: List[str] = []
    external_volumes: Dict[str, dict] = {}
    data_found = False
    for mount in inspect.get("Mounts") or []:
        kind = mount.get("Type")
        destination = _dest(mount.get("Destination", ""))
        if kind == "bind":
            source = mount.get("Source", "")
        elif kind == "volume":
            source = mount.get("Name", "")
            external_volumes[source] = {"external": True}
            if _ANONYMOUS_VOLUME.match(source):
                warnings.append("Volume %s is anonymous; it is kept by its generated name "
                                "and has no name you can recognise." % source)
        else:
            blockers.append("A mount of type '%s' at %s cannot be carried over to the "
                            "compose file." % (kind, destination))
            continue
        if destination == pgdata:
            data_found = True
        if kind == "bind" and mount.get("Propagation") not in (None, "", "rprivate"):
            blockers.append("Mount propagation '%s' of %s is set and cannot be carried over "
                            "to the compose file." % (mount.get("Propagation"), destination))
        volumes.append("%s:%s%s" % (source, destination, _mount_suffix(mount)))
    if not data_found:
        blockers.append("There is no data mount found at %s; the new container would "
                        "start an empty database." % pgdata)

    # Networks
    networks: Dict[str, dict] = {}
    external_networks: Dict[str, dict] = {}
    own_names = {str(inspect.get("Name", "")).lstrip("/"), str(inspect.get("Id", ""))[:12],
                 str(inspect.get("Id", ""))}
    for net, settings in ((inspect.get("NetworkSettings") or {}).get("Networks") or {}).items():
        if net in ("bridge", "none"):
            blockers.append("The container is attached to the '%s' network, which cannot be "
                            "declared in a compose file." % net)
            continue
        entry: dict = {}
        aliases = [a for a in (settings.get("Aliases") or []) if a not in own_names]
        if aliases:
            entry["aliases"] = aliases
        ipam = settings.get("IPAMConfig") or {}
        if ipam.get("IPv4Address"):
            entry["ipv4_address"] = ipam["IPv4Address"]
        if ipam.get("IPv6Address"):
            entry["ipv6_address"] = ipam["IPv6Address"]
        networks[net] = entry
        external_networks[net] = {"external": True}

    if blockers:
        return None, blockers

    service: dict = {"image": new_image}
    if vector_context:
        pg_version = new_image.split(":", 1)[1] if ":" in new_image else new_image
        service["build"] = {"context": vector_context, "args": {"PG_VERSION": pg_version}}
    service["container_name"] = str(inspect.get("Name", "")).lstrip("/")
    if config.get("User"):
        service["user"] = config["User"]
    service["restart"] = _restart_of(host.get("RestartPolicy"))
    if host.get("ShmSize") and host["ShmSize"] != DEFAULT_SHM_SIZE:
        service["shm_size"] = host["ShmSize"]
    if host.get("Memory"):
        service["mem_limit"] = host["Memory"]
    if host.get("NanoCpus"):
        service["cpus"] = host["NanoCpus"] / 1e9
    swap = host.get("MemorySwap")
    memory = host.get("Memory") or 0
    if swap not in (None, 0) and swap != 2 * memory and not (swap == -1 and memory == 0):
        service["memswap_limit"] = swap
    if host.get("MemorySwappiness") not in (None, -1):
        service["mem_swappiness"] = host["MemorySwappiness"]
    if host.get("CpuShares"):
        service["cpu_shares"] = host["CpuShares"]
    if host.get("CpusetCpus"):
        service["cpuset"] = host["CpusetCpus"]
    if host.get("Init"):
        service["init"] = True
    if host.get("ReadonlyRootfs"):
        service["read_only"] = True
    if host.get("Sysctls"):
        service["sysctls"] = dict(host["Sysctls"])
    if host.get("GroupAdd"):
        service["group_add"] = list(host["GroupAdd"])
    if config.get("StopSignal") and config["StopSignal"] != image_config.get("StopSignal"):
        service["stop_signal"] = config["StopSignal"]
    if config.get("StopTimeout") is not None:
        service["stop_grace_period"] = "%ds" % config["StopTimeout"]
    if config.get("WorkingDir") and config["WorkingDir"] != image_config.get("WorkingDir"):
        service["working_dir"] = config["WorkingDir"]
    service["environment"] = env_out
    service["volumes"] = volumes

    ports: List[str] = []
    for container_port, bindings in (host.get("PortBindings") or {}).items():
        for binding in bindings or []:
            host_ip = binding.get("HostIp") or ""
            if ":" in host_ip:
                host_ip = "[%s]" % host_ip
            parts = [host_ip, binding.get("HostPort") or "", container_port]
            ports.append(":".join(part for part in parts if part))
    if ports:
        service["ports"] = ports
    if networks:
        service["networks"] = networks
    for key, target in (("ExtraHosts", "extra_hosts"), ("Dns", "dns"),
                        ("DnsSearch", "dns_search")):
        if host.get(key):
            service[target] = list(host[key])

    log = host.get("LogConfig") or {}
    if (log.get("Type") or "json-file") != "json-file" or log.get("Config"):
        service["logging"] = {"driver": log.get("Type") or "json-file"}
        if log.get("Config"):
            service["logging"]["options"] = dict(log["Config"])

    for key, target in (("Cmd", "command"), ("Entrypoint", "entrypoint")):
        if (config.get(key) or []) != (image_config.get(key) or []):
            service[target] = list(config.get(key) or [])
    service["healthcheck"] = _healthcheck_of(config, db_user)

    image_labels = image_config.get("Labels") or {}
    labels = {k: v for k, v in (config.get("Labels") or {}).items()
              if image_labels.get(k) != v and not k.startswith("com.docker.compose.")}
    if labels:
        service["labels"] = labels

    document: dict = {"services": {SERVICE: _escape(service)}}
    if external_networks:
        document["networks"] = external_networks
    if external_volumes:
        document["volumes"] = external_volumes
    if warnings:
        document["x-pgup-warnings"] = warnings
    return document, []


def render_compose(document: dict, name: str) -> str:
    """The compose file text: a header with the control commands, then the YAML."""
    header = [
        '# Generated by ownerp_pg_update.py for container "%s".' % name,
        "# Control (independent of the working directory, via -f):",
        "#   docker compose -f docker-compose.yml up -d     # start / update",
        "#   docker compose -f docker-compose.yml stop      # stop",
        "#   docker compose -f docker-compose.yml start     # start again",
        "#   docker compose -f docker-compose.yml down      # remove (the data directory stays)",
    ]
    body = yaml.safe_dump(document, sort_keys=False, default_flow_style=False,
                          allow_unicode=True, width=1000000)
    return "\n".join(header) + "\n" + body


def mask_compose(text: str) -> str:
    """The compose text with the value of every password, secret or key hidden."""
    lines = []
    for line in text.splitlines():
        match = _SECRET_KEY.match(line)
        if match:
            line = '%s%s%s"***"' % match.group(1, 2, 3)
        lines.append(line)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def write_private(path: str, text: str) -> None:
    """Write a file that holds a password: 0600 from the first byte on."""
    directory = os.path.dirname(os.path.abspath(path))
    handle, temp = tempfile.mkstemp(prefix=".pgup-", dir=directory)    # created 0600
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as out:
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_content(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def _replace_value(line: str, key: str, value: str) -> Optional[str]:
    """`line` with the value of `key:` replaced; None when the line is not that key."""
    match = re.match(r'^(\s*(?:-\s+)?%s:\s*)("[^"]*"|\'[^\']*\'|[^\s#]\S*)(.*)$'
                     % re.escape(key), line)
    if not match:
        return None
    quote = "'" if match.group(2).startswith("'") else '"'
    return "%s%s%s%s%s" % (match.group(1), quote, value, quote, match.group(3))


def patch_compose_image(text: str, service: str, new_image: str,
                        pg_version: Optional[str]) -> str:
    """Set the image (and the PG_VERSION build argument) of one service in place.

    Only those lines change. The result is parsed and compared with the parsed
    original, so anything this line-based edit did not follow raises ValueError.
    """
    lines = text.splitlines(keepends=True)
    body = [line.rstrip("\r\n") for line in lines]
    start = None
    for number, line in enumerate(body):
        if re.match(r"^services:\s*(#.*)?$", line):
            start = number
            break
    if start is None:
        raise ValueError("no services: section found")
    child = None
    first = None
    for number in range(start + 1, len(body)):
        if _is_content(body[number]):
            if _indent(body[number]) == 0:
                break
            if child is None:
                child = _indent(body[number])
            if _indent(body[number]) == child and re.match(
                    r"^\s*%s:\s*(#.*)?$" % re.escape(service), body[number]):
                first = number
                break
    if first is None:
        raise ValueError("service %s not found in the compose file" % service)
    end = len(body)
    for number in range(first + 1, len(body)):
        if _is_content(body[number]) and _indent(body[number]) <= child:
            end = number
            break

    block_indent = min((_indent(body[n]) for n in range(first + 1, end) if _is_content(body[n])),
                       default=None)
    if block_indent is None:
        raise ValueError("service %s is empty" % service)
    image_lines = [n for n in range(first + 1, end)
                   if _indent(body[n]) == block_indent
                   and re.match(r"^\s*image:", body[n])]
    if len(image_lines) != 1:
        raise ValueError("service %s has no single image: line" % service)
    edits = {image_lines[0]: _replace_value(body[image_lines[0]], "image", new_image)}
    if pg_version is not None:
        arg_lines = [n for n in range(first + 1, end) if re.match(r"^\s*PG_VERSION:", body[n])]
        if len(arg_lines) != 1:
            raise ValueError("service %s has no single PG_VERSION: line" % service)
        edits[arg_lines[0]] = _replace_value(body[arg_lines[0]], "PG_VERSION", pg_version)
    if any(new is None for new in edits.values()):
        raise ValueError("a line to patch is not a plain scalar value")
    out = list(lines)
    for number, new in edits.items():
        out[number] = new + lines[number][len(body[number]):]
    patched = "".join(out)

    try:
        after = yaml.safe_load(patched)
        expected = yaml.safe_load(text)
        expected["services"][service]["image"] = new_image
        if pg_version is not None:
            expected["services"][service]["build"]["args"]["PG_VERSION"] = pg_version
    except (yaml.YAMLError, KeyError, TypeError, AttributeError) as error:
        raise ValueError("compose file not understood: %s" % error)
    if after != expected:
        raise ValueError("the patched compose file differs in more than the new image")
    return patched


# ── Phase 1: plan, image pull, guards, backup ────────────────────────────────

RELEASE_NOTES_URL = "https://www.postgresql.org/docs/release/%d.%d/"
RELEASE_NOTES_HEADING = ("Release notes to read first (a patch release can require a manual "
                         "step afterwards):")
DEFAULT_BACKUP_PATH = "/opt/backups"
DiskUsage = Callable[[str], object]


@dataclass
class Options:
    to: Optional[str] = None
    dry_run: bool = False
    no_input: bool = False
    sizing: str = "show"            # "apply" | "show" | "skip"
    role: Optional[str] = None
    db_user: Optional[str] = None
    skip_backup: bool = False
    force: bool = False
    home: str = os.path.expanduser("~")
    update_config: str = ""         # default <home>/docker2update.yaml
    backup_config: str = ""         # default <home>/container2backup.yaml


@dataclass
class UpdatePlan:
    target: PgTarget
    choice: Choice
    deploy_dir: str
    compose_file: str
    compose_text: Optional[str]            # legacy: new file; compose: patched text
    databases: List[str]
    listed: List[str]
    unlisted: List[str]
    stop_odoo: List[str]                   # running Odoo containers only
    sizing: SizingView
    parked_name: Optional[str]             # legacy: "<name>-pre-<M.n>"
    problems: List[str]                    # non-empty -> the update must not start


def release_note_links(current: Tuple[int, int], target: Tuple[int, int]) -> List[str]:
    """One release-notes URL per release from current (exclusive) to target, newest first."""
    if target[0] != current[0] or target[1] <= current[1]:
        return []
    return [RELEASE_NOTES_URL % (target[0], k) for k in range(target[1], current[1], -1)]


def compose_cmd(run: Runner) -> Optional[List[str]]:
    for candidate in (["docker", "compose"], ["docker-compose"]):
        code, _ = run(candidate + ["version"])
        if code == 0:
            return candidate
    return None


def _load_yaml(path: str) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, UnicodeError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


def _configs(opts: Options) -> Tuple[dict, Optional[dict]]:
    update = _load_yaml(opts.update_config or os.path.join(opts.home, "docker2update.yaml"))
    backup = _load_yaml(opts.backup_config or os.path.join(opts.home, "container2backup.yaml"))
    return update or {}, backup


def _mkdir_private(path: str) -> None:
    """Create a directory (and its missing parents) that only the owner may enter."""
    if os.path.isdir(path):
        return
    parent = os.path.dirname(path)
    if parent and parent != path:
        _mkdir_private(parent)
    os.mkdir(path, 0o700)
    os.chmod(path, 0o700)


def _gib(size: float) -> str:
    return "%.1f GiB" % (size / 1024 ** 3)


def _nearest_existing(path: str) -> str:
    while path and not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path or "/"


def _data_path(target: PgTarget) -> Optional[str]:
    """The host directory that holds PG_VERSION (PGDATA may be a subdirectory of the mount)."""
    if not target.pgdata:
        return None
    for entry in (target.inspect.get("Config") or {}).get("Env") or []:
        key, _, value = entry.partition("=")
        if key == "PGDATA" and value.startswith(DEFAULT_PGDATA + "/"):
            return os.path.join(target.pgdata, value[len(DEFAULT_PGDATA) + 1:])
    return target.pgdata


def _list_databases(target: PgTarget, run: Runner) -> Optional[List[str]]:
    return _databases_of(target.name, target.db_user or "postgres", run)


def _databases_of(name: str, user: str, run: Runner) -> Optional[List[str]]:
    migrate = _need("ownerp_migrate")
    code, out = run(["docker", "exec", name, "psql", "-U", user,
                     "-d", "postgres", "-Atqc",
                     "SELECT datname FROM pg_database WHERE datistemplate = false"])
    if code != 0:
        return None
    return [line.strip() for line in out.splitlines()
            if line.strip() and line.strip() not in migrate.SYSTEM_DATABASES]


def _database_size(target: PgTarget, database: str, run: Runner) -> Optional[int]:
    code, out = run(["docker", "exec", target.name, "psql", "-U", target.db_user or "postgres",
                     "-d", "postgres", "-Atqc",
                     "SELECT pg_database_size('%s')" % database.replace("'", "''")])
    try:
        return int(out.strip()) if code == 0 else None
    except ValueError:
        return None


def _tail(output: str) -> str:
    lines = [line for line in output.strip().splitlines() if line.strip()]
    return lines[-1].strip() if lines else "no output"


def prepare(target: PgTarget, choice: Choice, opts: Options, run: Runner,
            disk_usage: DiskUsage = shutil.disk_usage, hardware=None) -> UpdatePlan:
    """Every read-only check for one target; only `docker pull` / `docker build` change anything."""
    update_cfg, backup_cfg = _configs(opts)
    plan = UpdatePlan(
        target=target, choice=choice, deploy_dir="", compose_file="", compose_text=None,
        databases=[], listed=[], unlisted=[],
        stop_odoo=[o.name for o in target.odoo if o.running],
        sizing=SizingView({}, {}, {}, "not calculated"), parked_name=None, problems=[])
    problems = plan.problems
    only_conversion = (target.kind == "legacy" and choice.tag is None and not choice.blocked
                       and choice.note == "current")

    # Facts every later step needs.
    if choice.blocked:
        problems.append(choice.blocked)
    elif choice.tag is None and not only_conversion:
        problems.append("nothing to do" if choice.note == "current"
                        else "no update available (%s)" % choice.note)
    data = _data_path(target)
    if target.pgdata is None:
        problems.append("data directory not found (PGDATA is not at %s)" % DEFAULT_PGDATA)
    else:
        try:
            if not os.path.isfile(os.path.join(data, "PG_VERSION")):
                problems.append("PG_VERSION not found in %s; this is not a PostgreSQL data "
                                "directory" % data)
        except OSError:
            problems.append("cannot read the data directory %s (needs root)" % data)
    if not target.db_user:
        problems.append("no database user accepted by the server")
    if target.kind == "compose" and len(target.compose_files) > 1:
        problems.append("container is defined by several compose files (%s); update it by hand"
                        % ", ".join(target.compose_files))
    if not _is_running(target.inspect):
        problems.append("container %s is not running" % target.name)
    if not problems and compose_cmd(run) is None:
        problems.append("docker compose is not installed")
    if problems:
        return plan

    new_image = choice.tag or target.image
    vector = target.vector
    pg_version = new_image.partition(":")[2] if vector else None

    # Where the compose file lives.
    if target.kind == "compose":
        if not target.compose_file:
            problems.append("cannot read the compose file: its path is unknown")
            return plan
        plan.compose_file = target.compose_file
        plan.deploy_dir = os.path.dirname(os.path.abspath(target.compose_file))
    else:
        data_mount = next((m for m in target.inspect.get("Mounts") or []
                           if _dest(m.get("Destination", "")) == DEFAULT_PGDATA), {})
        plan.deploy_dir = deploy_dir_for(target.name, data_mount, opts.home)
        plan.compose_file = os.path.join(plan.deploy_dir, "docker-compose.yml")
    context = os.path.join(plan.deploy_dir, "pgvector")

    # The compose text: a new file for a legacy container, a patched one otherwise.
    if target.kind == "legacy":
        plan.parked_name = "%s-pre-%s" % (
            target.name, "%d.%d" % target.version if target.version else "unknown")
        code, out = run(["docker", "image", "inspect", target.image])
        image_inspect = None
        if code == 0:
            try:
                found = json.loads(out)
                image_inspect = found[0] if isinstance(found, list) and found else None
            except ValueError:
                image_inspect = None
        if not isinstance(image_inspect, dict):
            problems.append("cannot inspect the running image %s" % target.image)
        else:
            document, blockers = compose_from_inspect(
                target.inspect, image_inspect, new_image, target.db_user,
                vector_context=context if vector else None)
            problems.extend(blockers)
            if document is not None:
                plan.compose_text = render_compose(document, target.name)
        if run(["docker", "inspect", plan.parked_name])[0] == 0:
            problems.append("%s exists from an earlier update; remove it or roll back first"
                            % plan.parked_name)
    else:
        try:
            with open(target.compose_file, encoding="utf-8") as handle:
                original = handle.read()
        except (OSError, UnicodeError) as error:
            problems.append("cannot read the compose file %s: %s" % (target.compose_file, error))
        else:
            try:
                plan.compose_text = patch_compose_image(
                    original, target.compose_service or SERVICE, new_image, pg_version)
            except ValueError as error:
                problems.append("compose file %s cannot be patched: %s"
                                % (target.compose_file, error))

    # Databases and their backup route.
    databases = _list_databases(target, run)
    if databases is None:
        problems.append("cannot list the databases of %s" % target.name)
    else:
        plan.databases = databases
        plan.listed, plan.unlisted = backup_routes(databases, backup_cfg, target.name)
        if not opts.skip_backup and plan.unlisted:
            free = disk_usage(_nearest_existing(plan.deploy_dir)).free
            total = 0
            readable = True
            for database in plan.unlisted:
                size = _database_size(target, database, run)
                if size is None:
                    readable = False
                    problems.append("cannot read the size of database %s" % database)
                else:
                    total += size
            # All dumps land in the same directory, so the sum has to fit.
            if readable and free < total:
                problems.append("not enough free space in %s for the dumps of %s: needs "
                                "%s, free %s" % (plan.deploy_dir, ", ".join(plan.unlisted),
                                                 _gib(total), _gib(free)))
    plan.sizing = (SizingView({}, {}, {}, "skipped") if opts.sizing == "skip"
                   else sizing_view(target, update_cfg, opts.role, run, hardware))
    if problems or only_conversion:
        return plan

    # The only changes: pull or build, then the base guard on what arrived.
    if vector:
        dockerfile = os.path.join(context, "Dockerfile")
        try:
            if not os.path.exists(dockerfile):
                _mkdir_private(plan.deploy_dir)
                os.makedirs(context, exist_ok=True)
                with open(dockerfile, "w", encoding="utf-8") as handle:
                    handle.write(VECTOR_DOCKERFILE)
        except OSError as error:
            problems.append("cannot write %s: %s" % (dockerfile, error))
            return plan
        code, out = run(["docker", "build", "--build-arg", "PG_VERSION=%s" % pg_version,
                         "-t", choice.tag, context])
        if code != 0:
            problems.append("docker build of %s failed: %s" % (choice.tag, _tail(out)))
            return plan
    else:
        code, out = run(["docker", "pull", choice.tag])
        if code != 0:
            problems.append("docker pull of %s failed: %s" % (choice.tag, _tail(out)))
            return plan
    new_base = base_of_image(choice.tag, run)
    if target.base is None or new_base is None:
        problems.append("cannot compare the base system of %s with the running container"
                        % choice.tag)
    elif new_base.libc != target.base.libc:
        major = choice.version[0] if choice.version else (target.version or (0, 0))[0]
        problems.append("base system would change (%s -> %s) and no %d.x-%s image exists"
                        % (target.base.libc, new_base.libc, major,
                           target.base.codename or "<same base>"))
    return plan


def _compose_warnings(plan: UpdatePlan) -> List[str]:
    if plan.target.kind != "legacy" or not plan.compose_text:
        return []
    try:
        document = yaml.safe_load(plan.compose_text)
    except yaml.YAMLError:
        return []
    found = document.get("x-pgup-warnings") if isinstance(document, dict) else None
    return [str(item) for item in found] if isinstance(found, list) else []


def render_plan(plan: UpdatePlan, dry_run: bool = False) -> str:
    target, choice = plan.target, plan.choice
    if plan.problems:
        return "\n".join(["Cannot update %s:" % target.name]
                         + ["  - %s" % problem for problem in plan.problems])
    current = _version_text(target.version) or "?"
    lines = []
    if choice.tag:
        lines.append("%s: %s -> %s (%s)" % (target.name, current, _version_text(choice.version),
                                            choice.tag))
    else:
        lines.append("%s: conversion to compose only, version stays %s" % (target.name, current))
    if target.base:
        lines.append("Base system: %s%s, unchanged" % (
            target.base.libc, " (%s)" % target.base.codename if target.base.codename else ""))
    if plan.stop_odoo:
        lines.append("Odoo containers stopped during the switch: %s" % ", ".join(plan.stop_odoo))
    if target.others:
        lines.append("Other clients that lose their connection for a moment: %s"
                     % ", ".join(target.others))
    if plan.databases:
        lines.append("Backup before the switch:")
        for database in plan.databases:
            route = ("container2backup (listed)" if database in plan.listed
                     else "own dump below %s" % os.path.join(plan.deploy_dir, "pre-update"))
            lines.append("  %s: %s" % (database, route))
    lines.append("Compose file: %s" % plan.compose_file)
    for warning in _compose_warnings(plan):
        lines.append("  Warning: %s" % warning)
    if dry_run and plan.compose_text and target.kind == "legacy":
        lines.append("--- %s (passwords masked) ---" % plan.compose_file)
        lines.append(mask_compose(plan.compose_text).rstrip("\n"))
        lines.append("---")
    sizing = plan.sizing
    if sizing.skipped:
        lines.append("Memory settings: %s" % sizing.skipped)
    elif sizing.differs:
        lines.append("Memory settings differ from the calculation:")
        for key, (cur, rec) in sorted(sizing.differs.items()):
            lines.append("  %s: %s -> %s" % (key, cur, rec))
    if choice.tag and target.version and choice.version:
        links = release_note_links(target.version, choice.version)
        if links:
            lines.append(RELEASE_NOTES_HEADING)
            lines.extend("  %s" % link for link in links)
    lines.append("Rollback: pgup --rollback %s" % target.name)
    return "\n".join(lines)


# --- backup -------------------------------------------------------------------

def _dump_to_file(argv: List[str], path: str) -> int:
    """Run a command with its binary stdout written to `path`; the exit code.

    The caller creates `path` (mode 0600) first; this only fills it.
    """
    try:
        with open(path, "wb") as handle:
            return subprocess.run(argv, stdout=handle).returncode
    except OSError:
        return 127


def backup(plan: UpdatePlan, opts: Options, run: Runner, stream: Runner, out
           ) -> Tuple[bool, List[str]]:
    """Dumps before the switch (Odoo already stopped); (ok, where the dumps are)."""
    if opts.skip_backup:
        out("WARNING: backup skipped on request; there is no dump to go back to")
        return True, []
    target = plan.target
    user = target.db_user or "postgres"
    locations: List[str] = []
    if plan.listed:
        script = os.path.join(opts.home, "container2backup.py")
        argv = [sys.executable, script, "--sql-only"]
        for database in plan.listed:
            argv += ["--only-db", database]
        code, _ = stream(argv)
        if code != 0:
            out("ERROR: container2backup failed (exit %d); the update stops here" % code)
            return False, locations
        _, backup_cfg = _configs(opts)
        defaults = (backup_cfg or {}).get("defaults") or {}
        locations.append(str(defaults.get("backup_path") or DEFAULT_BACKUP_PATH))
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = os.path.join(plan.deploy_dir, "pre-update", stamp)
    try:
        _mkdir_private(folder if plan.unlisted else plan.deploy_dir)
    except OSError as error:
        out("ERROR: cannot create the backup directory: %s" % error)
        return False, locations
    for database in plan.unlisted:
        path = os.path.join(folder, database.replace(os.sep, "_") + ".dump")
        try:
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        except OSError as error:
            out("ERROR: cannot create %s: %s" % (path, error))
            return False, locations
        code = _dump_to_file(["docker", "exec", target.name, "pg_dump", "-U", user, "-Fc",
                              "--dbname=%s" % database], path)
        if code != 0:
            out("ERROR: pg_dump of %s failed (exit %d); the partial file %s is kept"
                % (database, code, path))
            return False, locations
        locations.append(path)
    code, text = run(["docker", "exec", target.name, "pg_dumpall", "-U", user,
                      "--globals-only"])
    if code != 0:
        out("ERROR: pg_dumpall --globals-only failed: %s" % _tail(text))
        return False, locations
    path = os.path.join(plan.deploy_dir, "globals-%s.sql" % stamp)
    try:
        write_private(path, text)
    except OSError as error:
        out("ERROR: cannot write %s: %s" % (path, error))
        return False, locations
    locations.append(path)
    return True, locations


# ── Phase 2: switch, verify, undo, rollback ──────────────────────────────────

STATE_DIR = "pg-deploy/state"
CONFIRM_AFTER = datetime.timedelta(days=7)
READY_RETRIES = 60
STOP_TIMEOUT = 120      # seconds a database container gets to finish its shutdown checkpoint


def state_path(home: str, name: str) -> str:
    return os.path.join(home, STATE_DIR, name + ".json")


def facts(name: str, user: str, pgdata: Optional[str], run: Runner) -> dict:
    """What a verification compares: version, databases (sorted) and data directory owner.

    A value that cannot be read is None; the owner is None when the data
    directory cannot be stat-ed (not root).
    """
    owner = None
    if pgdata:
        try:
            info = os.stat(pgdata)
            owner = "%d:%d" % (info.st_uid, info.st_gid)
        except OSError:
            owner = None
    databases = _databases_of(name, user, run)
    return {"version": server_version(name, user, run),
            "databases": sorted(databases) if databases is not None else None,
            "owner": owner}


def wait_ready(name: str, user: str, run: Runner, sleep=time.sleep,
               retries: int = READY_RETRIES) -> bool:
    for attempt in range(retries):
        code, _ = run(["docker", "exec", name, "pg_isready", "-U", user, "-d", "postgres"])
        if code == 0:
            return True
        if attempt < retries - 1:
            sleep(5)
    return False


def _checked(run: Runner, argv: List[str], out, what: str) -> bool:
    """Run a command that changes something; a non-zero exit is reported and returned."""
    code, text = run(argv)
    if code != 0:
        out("ERROR: %s failed (exit %d): %s" % (what, code, _tail(text)))
        return False
    return True


def _start_odoo(names: List[str], run: Runner, out) -> bool:
    ok = True
    for odoo in names:
        out("Starting %s" % odoo)
        ok = _checked(run, ["docker", "start", odoo], out, "docker start %s" % odoo) and ok
    return ok


def _lookup(name: str, run: Runner) -> Tuple[Optional[bool], Optional[dict]]:
    """(found, inspect): found is False when the container does not exist, None when
    docker could not tell."""
    code, text = run(["docker", "inspect", "--type", "container", name])
    if code == 0:
        try:
            data = json.loads(text)
        except ValueError:
            return None, None
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return True, data[0]
        return None, None
    if "no such" in text.lower():
        return False, None
    return None, None


def _state_text(name: str, run: Runner) -> str:
    found, info = _lookup(name, run)
    if found is None:
        return "state unknown (docker did not answer)"
    if not found:
        return "does not exist"
    return "%s, image %s" % ("running" if (info.get("State") or {}).get("Running") else "stopped",
                             (info.get("Config") or {}).get("Image") or "?")


def _compose_base(cmd: List[str], project: Optional[str], compose_file: str) -> List[str]:
    """`docker compose [-p PROJECT] -f FILE`; the project of a compose-managed container is
    always passed so that compose finds the services it already runs."""
    return cmd + (["-p", project] if project else []) + ["-f", compose_file]


def _up_argv(cmd: List[str], project: Optional[str], compose_file: str, service: str
             ) -> List[str]:
    """Start exactly one service: never its dependencies and never a sibling (Odoo!)."""
    return _compose_base(cmd, project, compose_file) + ["up", "-d", "--no-deps", service]


def _stop_database(name: str, run: Runner, out) -> bool:
    """Stop the database container with room for its shutdown checkpoint (when it runs)."""
    found, info = _lookup(name, run)
    if found and (info.get("State") or {}).get("Running"):
        return _checked(run, ["docker", "stop", "-t", str(STOP_TIMEOUT), name], out,
                        "docker stop %s" % name)
    return True


def _undo_legacy(state: dict, cmd: List[str], run: Runner, out) -> bool:
    name, parked = state["name"], state.get("parked_name")
    named, info = _lookup(name, run)
    park, parked_info = _lookup(parked, run) if parked else (False, None)
    if named is None or park is None:
        out("ERROR: docker does not tell whether %s and %s exist" % (name, parked))
        return False
    if park:
        if named:
            # Two containers: the one on the original name is the one this tool created.
            compose_file = state["compose_file"]
            if not os.path.isfile(compose_file):
                out("ERROR: %s holds the new server but %s is gone; it cannot be removed "
                    "the safe way" % (name, compose_file))
                return False
            # The generated file holds the one service this tool created; `down` is only ever
            # used on it, never on a compose file the operator owns.
            if not _stop_database(name, run, out):
                return False
            if not _checked(run, _compose_base(cmd, None, compose_file) + ["down", "-t",
                                                                           str(STOP_TIMEOUT)],
                            out, "%s -f %s down" % (" ".join(cmd), compose_file)):
                return False
            named, _ = _lookup(name, run)
            if named is not False:
                out("ERROR: %s still exists after down" % name)
                return False
        if not _checked(run, ["docker", "rename", parked, name], out,
                        "docker rename %s %s" % (parked, name)):
            return False
        if not _checked(run, ["docker", "update", "--restart=%s" % (state.get("parked_restart")
                                                                    or "no"), name],
                        out, "docker update --restart on %s" % name):
            return False
        running = bool((parked_info.get("State") or {}).get("Running"))
    else:
        if not named:
            out("ERROR: neither %s nor %s exists" % (name, parked))
            return False
        image = (info.get("Config") or {}).get("Image")
        if image != state.get("old_image"):
            out("ERROR: %s was never parked but runs %s instead of %s" % (name, image,
                                                                            state.get("old_image")))
            return False
        running = bool((info.get("State") or {}).get("Running"))
    if not running:
        return _checked(run, ["docker", "start", name], out, "docker start %s" % name)
    return True


def _undo_compose(state: dict, cmd: List[str], run: Runner, out) -> bool:
    compose_file, backup_file = state["compose_file"], state.get("compose_backup")
    # No backup yet means the file was never touched; `up -d` then only starts the container.
    if backup_file and os.path.isfile(backup_file):
        try:
            with open(backup_file, encoding="utf-8") as handle:
                write_private(compose_file, handle.read())
        except (OSError, UnicodeError) as error:
            out("ERROR: cannot restore %s from %s: %s" % (compose_file, backup_file, error))
            return False
    # Only the file is restored and only the database service is started again: the
    # file may hold other services (Odoo) that must stay as they are, so no `down` here.
    if not _stop_database(state["name"], run, out):
        return False
    argv = _up_argv(cmd, state.get("compose_project"), compose_file,
                    state.get("compose_service") or SERVICE)
    return _checked(run, argv, out, " ".join(argv))


def _undo(state: dict, cmd: List[str], run: Runner, out) -> bool:
    """Put the old server back from whatever state the host is really in."""
    if state.get("kind") == "legacy":
        return _undo_legacy(state, cmd, run, out)
    return _undo_compose(state, cmd, run, out)


def _archive_state(path: str, label: str, stamp: str, out) -> None:
    try:
        os.replace(path, "%s.%s-%s" % (path, label, stamp))
    except OSError as error:
        out("WARNING: cannot rename the state file %s: %s" % (path, error))


def _stranded(state: dict, path: str, run: Runner, cmd: Optional[List[str]] = None,
              extra_odoo=(), undone: bool = False) -> List[str]:
    """What the operator sees when the old server is not back: facts, then the next step.

    `undone`: the undo itself completed (the state file is archived) but the old server was
    not checked. Every command printed is a plain `docker ...` / `pgup ...` line.
    """
    name, parked = state["name"], state.get("parked_name")
    lines = (["The old server was put back but not checked yet. Odoo stays stopped."] if undone
             else ["ERROR: the old server could not be brought back automatically. "
                   "Odoo stays stopped."])
    for container in (name, parked):
        if container:
            lines.append("  %s: %s" % (container, _state_text(container, run)))
    if not undone:
        lines.append("  State file (kept): %s" % path)
    cmd = cmd or ["docker", "compose"]
    named, info = _lookup(name, run)
    park = _lookup(parked, run)[0] if parked else False
    backup_file = state.get("compose_backup")
    lines.append("Next step:")
    if undone:
        lines.append("  docker exec %s pg_isready -U %s -d postgres"
                     % (name, state.get("db_user") or "postgres"))
    elif (state.get("kind") == "legacy" and park) or (
            state.get("kind") == "compose" and backup_file and os.path.isfile(backup_file)):
        lines.append("  pgup --rollback %s" % name)
    elif state.get("kind") == "compose":
        lines.append("  %s" % " ".join(_up_argv(cmd, state.get("compose_project"),
                                                 state["compose_file"],
                                                 state.get("compose_service") or SERVICE)))
    elif named:
        policy = _restart_of(((info or {}).get("HostConfig") or {}).get("RestartPolicy"))
        wanted = state.get("parked_restart") or "no"
        running = bool(((info or {}).get("State") or {}).get("Running"))
        if policy != wanted:
            lines.append("  docker update --restart=%s %s" % (wanted, name))
        if not running:
            lines.append("  docker start %s" % name)
        if running and policy == wanted:
            lines.append("  docker logs --tail 50 %s" % name)
    elif park is False and named is False:
        lines.append("  neither %s nor %s exists; the data directory is untouched. Start a "
                     "server on it from the compose file:" % (name, parked))
        lines.append("  %s" % " ".join(_up_argv(cmd, None, state["compose_file"], SERVICE)))
    else:
        lines.append("  docker did not answer; check with: docker ps -a")
    odoo = list(state.get("stopped_odoo") or [])
    odoo += [o for o in extra_odoo if o not in odoo]
    if odoo:
        lines.append("Then, once the database answers, start Odoo:")
        lines.extend("  docker start %s" % o for o in odoo)
    return lines


def _recover(plan: UpdatePlan, state: dict, path: str, cmd: List[str], user: str,
             before_version, run: Runner, out, sleep) -> int:
    out("Going back to the old server")
    ok = False
    try:
        ok = _undo(state, cmd, run, out)
    except (Exception, KeyboardInterrupt) as error:
        out("ERROR: the undo stopped unexpectedly: %s" % (error or type(error).__name__))
    interrupted = False
    try:
        if ok and not wait_ready(state["name"], user, run, sleep):
            out("ERROR: the old server does not answer")
            ok = False
        elif ok and server_version(state["name"], user, run) != before_version:
            out("ERROR: the server on %s does not report the old version %s"
                % (state["name"], _version_text(before_version)))
            ok = False
    except KeyboardInterrupt:
        # The undo itself is complete; only the check is missing. Close the books.
        out("Interrupted while waiting for the old server.")
        interrupted, ok = True, False
        _archive_state(path, "undone", datetime.datetime.now().strftime("%Y%m%d-%H%M%S"), out)
    if not ok:
        for line in _stranded(state, path, run, cmd, undone=interrupted):
            out(line)
        return 2
    _start_odoo(plan.stop_odoo, run, out)
    _archive_state(path, "undone", datetime.datetime.now().strftime("%Y%m%d-%H%M%S"), out)
    out("The old server (%s) is running again and Odoo is back on it; nothing was lost."
        % _version_text(before_version))
    return 1


def _switch(plan: UpdatePlan, state: dict, cmd: List[str], user: str, pgdata: Optional[str],
            before: dict, expected, run: Runner, out, sleep) -> Optional[str]:
    """Steps 5 to 8; None when the new server is up and verified, else the reason."""
    target = plan.target
    name = target.name
    out("Stopping %s" % name)
    if not _checked(run, ["docker", "stop", "-t", str(STOP_TIMEOUT), name], out,
                    "docker stop %s" % name):
        return "could not stop %s" % name
    if target.kind == "legacy":
        parked = plan.parked_name
        out("Parking the old container as %s" % parked)
        if not _checked(run, ["docker", "rename", name, parked], out,
                        "docker rename %s %s" % (name, parked)):
            return "could not rename %s" % name
        if not _checked(run, ["docker", "update", "--restart=no", parked], out,
                        "docker update --restart=no %s" % parked):
            return "could not set the restart policy of %s" % parked
        _mkdir_private(plan.deploy_dir)
        write_private(plan.compose_file, plan.compose_text)
    else:
        with open(plan.compose_file, encoding="utf-8") as handle:
            write_private(state["compose_backup"], handle.read())
        write_private(plan.compose_file, plan.compose_text)
    out("Starting the new server (%s)" % state["new_image"])
    argv = _up_argv(cmd, state["compose_project"], plan.compose_file, state["compose_service"])
    if not _checked(run, argv, out, " ".join(argv)):
        return "the new server did not start"
    if not wait_ready(name, user, run, sleep):
        return "the new server does not become ready"
    after = facts(name, user, pgdata, run)
    if after["version"] != expected:
        return "the new server reports version %s, expected %s" % (
            _version_text(after["version"]) or "nothing", _version_text(expected))
    if after["databases"] != before["databases"]:
        return "the databases differ: before %s, after %s" % (before["databases"],
                                                              after["databases"])
    if before["owner"] is None or after["owner"] is None:
        out("Data directory owner not compared (cannot read %s without root)" % pgdata)
    elif before["owner"] != after["owner"]:
        return "the data directory owner changed from %s to %s" % (before["owner"],
                                                                   after["owner"])
    return None


def _sizing_state_io(plan: UpdatePlan, opts: Options):
    """(load, save) for the sizing state: the instance's build dir, else pg-deploy/state."""
    sizing = _need("ownerp_sizing")
    update_cfg, _ = _configs(opts)
    entry = next((e for e in update_cfg.get("containers") or []
                  if isinstance(e, dict) and e.get("db_host") == plan.target.name
                  and isinstance(e.get("sizing"), dict) and e.get("dockerfile_path")), None)
    if entry is not None:
        build_dir = os.path.expandvars(os.path.expanduser(str(entry["dockerfile_path"])))

        def save_managed(state):
            problem = sizing.save_state(build_dir, state)
            sizing.ensure_dockerignore(build_dir)
            return problem

        return (lambda: sizing.load_state(build_dir)), save_managed
    path = os.path.join(opts.home, STATE_DIR, plan.target.name + ".sizing.json")

    def load():
        if not os.path.exists(path):
            return {}, None
        try:
            with open(path, encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, ValueError) as error:
            return {}, "cannot read %s: %s" % (path, error)
        if not isinstance(state, dict) or not isinstance(state.get("pg", {}), dict):
            return {}, "cannot read %s: unexpected content" % path
        return state, None

    def save(state):
        try:
            _mkdir_private(os.path.dirname(path))
            write_private(path, json.dumps(state, indent=2, sort_keys=True) + "\n")
        except OSError as error:
            return "cannot write %s: %s" % (path, error)
        return None

    return load, save


def _apply_sizing(plan: UpdatePlan, opts: Options, user: str, run: Runner, out, sleep
                  ) -> bool:
    """Memory settings on the new server. The outcome is a report line, never an exit code;
    the return value says whether postgresql.conf was changed (and stayed changed)."""
    label = "Memory settings"
    changed = False
    try:
        sizing = _need("ownerp_sizing")
        if not plan.sizing.recommended:
            out("%s: nothing calculated, left alone" % label)
            return False
        load, save = _sizing_state_io(plan, opts)
        state, problem = load()
        if problem:
            out("%s: ERROR %s; not changed" % (label, problem))
            return False
        pg_state = state.setdefault("pg", {})
        before = json.dumps(pg_state, sort_keys=True)
        sync = sizing.sync_postgres(plan.target.name, plan.sizing.recommended,
                                    plan.sizing.overrides, pg_state, run, user, sleep=sleep)
        changed = bool(sync.changed and not sync.rolled_back)
        if json.dumps(pg_state, sort_keys=True) != before:
            problem = save(state)
            if problem:
                out("%s: ERROR state not saved: %s" % (label, problem))
        if sync.skipped:
            out("%s: skipped (%s)" % (label, sync.skipped))
        elif sync.error:
            hint = ("; the refused values are kept as hand values until accepted in dosize "
                    "--review" if sync.rolled_back else "")
            out("%s: ERROR %s%s; the update continues" % (label, sync.error, hint))
        else:
            written = sum(1 for d in sync.decisions if d.action == "write") if sync.changed else 0
            out("%s: %d written, %d unchanged" % (label, written, len(sync.decisions) - written))
            for decision in sync.decisions:
                if decision.action == "keep" or (decision.action == "write" and sync.changed):
                    out("  " + sizing.format_decision(decision))
            if sync.restarted and sync.verified:
                out("  database restarted, new values verified with SHOW")
    except Exception as error:
        out("%s: ERROR %s: %s; the update continues" % (label, type(error).__name__, error))
    return changed


def _version_key(text: str) -> Tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text))


def _vector_hints(plan: UpdatePlan, user: str, run: Runner) -> List[str]:
    """Databases whose pgvector extension is older than the one the new image ships."""
    name = plan.target.name
    code, text = run(["docker", "exec", name, "psql", "-U", user, "-d", "postgres", "-Atqc",
                      "SELECT default_version FROM pg_available_extensions WHERE name='vector'"])
    if code != 0 or not text.strip():
        return []
    default = text.strip().splitlines()[0]
    hints = []
    for database in plan.databases:
        code, text = run(["docker", "exec", name, "psql", "-U", user, "-d", database, "-Atqc",
                          "SELECT extversion FROM pg_extension WHERE extname='vector'"])
        installed = text.strip().splitlines()[0] if code == 0 and text.strip() else ""
        if installed and _version_key(installed) < _version_key(default):
            hints.append("%s: pgvector %s, the new image has %s: docker exec %s psql -U %s -d %s "
                         "-c \"ALTER EXTENSION vector UPDATE\""
                         % (database, installed, default, name, user, database))
    return hints


def _size_text(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return "%.1f %s" % (value, unit) if unit != "B" else "%d B" % size
        value /= 1024
    return "%d B" % size


def _older_backups(plan: UpdatePlan, locations: List[str]) -> Optional[str]:
    root = os.path.join(plan.deploy_dir, "pre-update")
    try:
        folders = [os.path.join(root, entry) for entry in sorted(os.listdir(root))
                   if os.path.isdir(os.path.join(root, entry))]
    except OSError:
        return None
    current = {os.path.dirname(location) for location in locations}
    older = [folder for folder in folders if folder not in current]
    if not older:
        return None
    total = 0
    for folder in older:
        for base, _, files in os.walk(folder):
            for item in files:
                try:
                    total += os.path.getsize(os.path.join(base, item))
                except OSError:
                    pass
    return ("%d older backup director%s in %s, %s in total; this tool deletes none"
            % (len(older), "y" if len(older) == 1 else "ies", root, _size_text(total)))


def update_one(plan: UpdatePlan, opts: Options, run: Runner, stream: Runner, out,
               sleep=time.sleep) -> int:
    """Switch one database container to the new image. 0 done, 1 undone, 2 needs the operator.

    Ctrl-C at any point ends in a defined state: before the state file exists nothing
    was changed on the database, so Odoo simply starts again; afterwards the old server is
    put back, unless Odoo is already being started on the verified new one.
    """
    progress: dict = {}
    try:
        return _update_run(plan, opts, run, stream, out, sleep, progress)
    except KeyboardInterrupt:
        pass
    state = progress.get("state")
    name = plan.target.name
    if state is None:
        out("Interrupted; nothing was changed on the database.")
        _start_odoo(plan.stop_odoo, run, out)
        return 1
    if progress.get("odoo_starting"):
        out("Interrupted while starting Odoo. The new server is verified and keeps running.")
        out("Start the Odoo containers that are still stopped:")
        for odoo in plan.stop_odoo:
            out("  docker start %s" % odoo)
        out("Go back to the old server instead:  pgup --rollback %s" % name)
        return 2
    out("Interrupted.")
    return _recover(plan, state, progress["path"], progress["cmd"], progress["user"],
                    progress["before_version"], run, out, sleep)


def _update_run(plan: UpdatePlan, opts: Options, run: Runner, stream: Runner, out, sleep,
                progress: dict) -> int:
    if plan.problems:
        out(render_plan(plan))
        return 2
    if opts.dry_run:
        out(render_plan(plan, dry_run=True))
        return 0
    target, choice = plan.target, plan.choice
    name = target.name
    user = target.db_user or "postgres"
    pgdata = _data_path(target)
    cmd = compose_cmd(run)
    if cmd is None:
        out("ERROR: docker compose is not installed; nothing was changed")
        return 2

    for odoo in plan.stop_odoo:
        out("Stopping %s" % odoo)
        if not _checked(run, ["docker", "stop", odoo], out, "docker stop %s" % odoo):
            out("The update stops here; no database container was touched.")
            _start_odoo(plan.stop_odoo, run, out)
            return 1

    ok, locations = backup(plan, opts, run, stream, out)
    if not ok:
        out("The update stops here; no database container was touched.")
        _start_odoo(plan.stop_odoo, run, out)
        return 1

    before = facts(name, user, pgdata, run)
    if before["version"] is None or before["databases"] is None:
        out("ERROR: cannot read the version and databases of %s; the update stops here" % name)
        _start_odoo(plan.stop_odoo, run, out)
        return 1
    # None (the query failed) adds nothing here, so every mismatch found later counts as new.
    before_collation = set(collation_mismatches(target, run) or [])
    expected = (choice.version if choice.tag else None) or before["version"]
    now = datetime.datetime.now().replace(microsecond=0)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    state = {
        "name": name, "kind": target.kind,
        "old_image": target.image, "new_image": choice.tag or target.image,
        "old_version": _version_text(before["version"]), "new_version": _version_text(expected),
        "parked_name": plan.parked_name,
        "parked_restart": _restart_of((target.inspect.get("HostConfig") or {}).get(
            "RestartPolicy")),
        "compose_file": plan.compose_file,
        "compose_backup": ("%s.bak-%s" % (plan.compose_file, stamp)
                           if target.kind == "compose" else None),
        "compose_service": ((target.compose_service or SERVICE) if target.kind == "compose"
                            else SERVICE),
        "compose_project": target.compose_project if target.kind == "compose" else None,
        "stopped_odoo": list(plan.stop_odoo),
        "time": now.isoformat(),
        "db_user": user,
        "sizing_applied": False,
    }
    path = state_path(opts.home, name)
    try:
        _mkdir_private(os.path.dirname(path))
        write_private(path, json.dumps(state, indent=2, sort_keys=True) + "\n")
    except OSError as error:
        out("ERROR: cannot write the state file %s: %s; the update stops here" % (path, error))
        _start_odoo(plan.stop_odoo, run, out)
        return 1
    progress.update(state=state, path=path, cmd=cmd, user=user, before_version=before["version"])

    try:
        error = _switch(plan, state, cmd, user, pgdata, before, expected, run, out, sleep)
    except (Exception, KeyboardInterrupt) as exc:
        error = ("interrupted" if isinstance(exc, KeyboardInterrupt)
                 else "unexpected %s: %s" % (type(exc).__name__, exc))
    if error:
        out("ERROR: %s" % error)
        return _recover(plan, state, path, cmd, user, before["version"], run, out, sleep)

    out("The new server runs %s and the databases match." % _version_text(expected))
    found = collation_mismatches(replace(target, version=expected), run)
    if found is None:
        out("ERROR: the collation check could not run on the new server; Odoo stays stopped.")
        out("Two ways forward:")
        out("  1. Go back to the old server:  pgup --rollback %s" % name)
        out("  2. Keep the new server, look for a collation mismatch by hand (any line it "
            "prints is a database to reindex):")
        out("       docker exec %s psql -U %s -d postgres -Atc %s" % (name, user, shlex.quote(
            "SELECT datname FROM pg_database WHERE datcollversion IS DISTINCT FROM "
            "pg_database_collation_actual_version(oid)")))
        if plan.stop_odoo:
            out("     then start Odoo:")
            for odoo in plan.stop_odoo:
                out("       docker start %s" % odoo)
        return 2
    new_collation = [d for d in found if d not in before_collation]
    if new_collation:
        out("ERROR: the collation version no longer matches in: %s" % ", ".join(new_collation))
        out("Odoo stays stopped. Two ways forward:")
        out("  1. Go back to the old server:  pgup --rollback %s" % name)
        out("  2. Keep the new server, rebuild the indexes and record the new collation "
            "version, for each database:")
        for database in new_collation:
            quoted = '"%s"' % database.replace('"', '""')
            for sql in ("REINDEX DATABASE %s" % quoted,
                        "ALTER DATABASE %s REFRESH COLLATION VERSION" % quoted):
                out("       docker exec %s psql -U %s -d %s -c %s"
                    % (name, user, shlex.quote(database), shlex.quote(sql)))
        if plan.stop_odoo:
            out("     then start Odoo: %s" % "; ".join("docker start %s" % o
                                                      for o in plan.stop_odoo))
        return 2

    if opts.sizing == "apply" and plan.sizing.skipped is None:
        if _apply_sizing(plan, opts, user, run, out, sleep):
            state["sizing_applied"] = True
            try:
                write_private(path, json.dumps(state, indent=2, sort_keys=True) + "\n")
            except OSError as error:
                out("WARNING: cannot record the memory settings in %s: %s" % (path, error))
        if not wait_ready(name, user, run, sleep):
            out("ERROR: %s does not answer after the memory settings; Odoo stays stopped. "
                "Go back with: pgup --rollback %s" % (name, name))
            return 2

    code = 0
    progress["odoo_starting"] = True
    if not _start_odoo(plan.stop_odoo, run, out):
        out("ERROR: not every Odoo container could be started")
        code = 2
    hints = _vector_hints(plan, user, run) if target.vector else []

    if choice.tag:
        out("Done: %s %s -> %s (%s)" % (name, _version_text(before["version"]),
                                        _version_text(expected), choice.tag))
    else:
        out("Done: %s now runs from a compose file, version stays %s"
            % (name, _version_text(before["version"])))
    for location in locations:
        out("Backup: %s" % location)
    out("Compose file: %s" % plan.compose_file)
    if target.kind == "compose":
        out("Previous compose file: %s" % state["compose_backup"])
    if plan.parked_name:
        out("The old container is parked as %s (stopped, restart policy no)." % plan.parked_name)
        out("Once you are satisfied, remove it:  docker rm %s" % plan.parked_name)
    for hint in hints:
        out("pgvector: %s" % hint)
    older = _older_backups(plan, locations)
    if older:
        out(older)
    out("Rollback: pgup --rollback %s" % name)
    return code


def _paired_running(name: str, state: dict, opts: Options, run: Runner) -> List[str]:
    """Odoo containers that are running now and belong to this database container."""
    update_cfg, _ = _configs(opts)
    try:
        for found in discover(run, update_cfg, opts.db_user or state.get("db_user")):
            if found.name == name:
                return [o.name for o in found.odoo if o.running]
    except Exception:
        pass
    # The server is not found as a running PostgreSQL container: use what the update stopped.
    running = []
    for candidate in state.get("stopped_odoo") or []:
        _, info = _lookup(candidate, run)
        if info and (info.get("State") or {}).get("Running"):
            running.append(candidate)
    return running


def rollback(name: str, opts: Options, run: Runner, out, now=None, ask=None,
             sleep=time.sleep) -> int:
    """Go back to the server the last update replaced. 0 done, 2 not possible or not verified."""
    now = now or datetime.datetime.now()
    path = state_path(opts.home, name)
    try:
        with open(path, encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        out("No update state found for %s (%s); there is nothing to roll back." % (name, path))
        return 2
    if (not isinstance(state, dict) or state.get("name") != name
            or state.get("kind") not in ("legacy", "compose")):
        out("The state file %s is not usable; nothing was changed." % path)
        return 2
    cmd = compose_cmd(run)
    if cmd is None:
        out("ERROR: docker compose is not installed; nothing was changed")
        return 2
    user = state.get("db_user") or opts.db_user or "postgres"
    if state["kind"] == "legacy":
        found, _ = _lookup(state.get("parked_name") or "", run)
        if not found:
            out("Cannot roll back: the parked container %s %s; nothing was changed."
                % (state.get("parked_name"), "is missing" if found is False
                   else "could not be looked up"))
            return 2
    elif not state.get("compose_backup") or not os.path.isfile(state["compose_backup"]):
        out("Cannot roll back: the previous compose file %s is missing; nothing was changed."
            % state.get("compose_backup"))
        return 2

    try:
        made = datetime.datetime.fromisoformat(state.get("time") or "")
    except ValueError:
        made = None
    if made is None or now - made > CONFIRM_AFTER:
        days = "an unknown time" if made is None else "%d days" % (now - made).days
        if not opts.force:
            question = ("The update of %s was made %s ago (limit %d days); data written since "
                        "stays on the data directory but the old server may not accept it. "
                        "Roll back anyway?" % (name, days, CONFIRM_AFTER.days))
            if opts.no_input or ask is None:
                out("%s Use --force to roll back without asking." % question)
                return 2
            if not ask(question):
                out("Rollback cancelled; nothing was changed.")
                return 2

    odoo = _paired_running(name, state, opts, run)
    stopped: List[str] = []
    for container in odoo:
        out("Stopping %s" % container)
        if not _checked(run, ["docker", "stop", container], out, "docker stop %s" % container):
            out("Rollback stops here; the database container was not touched.")
            _start_odoo(odoo, run, out)
            return 2
        stopped.append(container)

    old = _version_key(state.get("old_version") or "")
    ok = False
    try:
        ok = _undo(state, cmd, run, out)
    except (Exception, KeyboardInterrupt) as error:
        out("ERROR: the rollback stopped unexpectedly: %s" % (error or type(error).__name__))
    if ok and not wait_ready(name, user, run, sleep):
        out("ERROR: the old server does not answer")
        ok = False
    elif ok:
        version = server_version(name, user, run)
        if version is None or tuple(version) != old[:2]:
            out("ERROR: the server on %s reports %s, expected %s"
                % (name, _version_text(version) or "nothing", state.get("old_version")))
            ok = False
    if not ok:
        for line in _stranded(state, path, run, cmd, extra_odoo=stopped):
            out(line)
        return 2
    # What this run stopped, plus what the update stopped and nobody started again (an
    # update that ended with exit 2 leaves Odoo down and sends the operator here).
    to_start = list(stopped)
    for candidate in state.get("stopped_odoo") or []:
        if candidate in to_start:
            continue
        found, info = _lookup(candidate, run)
        if found and not (info.get("State") or {}).get("Running"):
            to_start.append(candidate)
    _start_odoo(to_start, run, out)
    _archive_state(path, "rolled-back", now.strftime("%Y%m%d-%H%M%S"), out)
    out("Rolled back: %s runs %s again (%s)." % (name, state.get("old_version"),
                                                  state.get("old_image")))
    if state["kind"] == "legacy":
        out("The compose file %s stays on disk; the new image stays in the local image store."
            % state["compose_file"])
    if state.get("sizing_applied"):
        out("The memory settings in postgresql.conf were not reverted.")
    return 0


# --- command line -------------------------------------------------------------------

ROLES = ("live", "test", "demo")
NOTHING_TO_DO = "nothing to do"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pgup",
        description="Update PostgreSQL containers to the newest patch release of their major "
                    "version. Without options on a terminal: overview and selection.")
    parser.add_argument("--container", action="append", default=[], metavar="NAME",
                        help="database container to update (repeatable, updated in this order)")
    parser.add_argument("--to", metavar="VERSION",
                        help="update to this release (X.Y) instead of the newest; one container")
    parser.add_argument("--dry-run", action="store_true",
                        help="run every check and print the plan; change nothing")
    parser.add_argument("--json", action="store_true",
                        help="print the overview as JSON; change nothing")
    parser.add_argument("--no-input", action="store_true",
                        help="never ask; needed to run without a terminal")
    parser.add_argument("--sizing", choices=("apply", "show", "skip"),
                        help="memory settings: write them, only show them (default) or leave "
                             "them out")
    parser.add_argument("--role", choices=ROLES,
                        help="role for the memory calculation when docker2update.yaml names none")
    parser.add_argument("--db-user", metavar="USER", help="database superuser to connect as")
    parser.add_argument("--skip-backup", action="store_true",
                        help="update without a dump (there is nothing to restore from then)")
    parser.add_argument("--rollback", metavar="NAME",
                        help="go back to the server the last update of NAME replaced")
    parser.add_argument("--force", action="store_true",
                        help="with --rollback: do not ask when the update is older than %d days"
                             % CONFIRM_AFTER.days)
    parser.add_argument("--config", metavar="PATH",
                        help="docker2update.yaml to read (default: ~/docker2update.yaml)")
    parser.add_argument("--version", action="version",
                        version="ownerp_pg_update %s (%s)" % (SCRIPT_VERSION, SCRIPT_DATE))
    return parser


def default_stream(argv: List[str]) -> Tuple[int, str]:
    """Run a command with its output going straight to the terminal; (exit code, "")."""
    try:
        return subprocess.run(argv).returncode, ""
    except OSError:
        return 127, ""


def build_rows(targets: List[PgTarget], opts: Options, run: Runner, fetch: Optional[Fetch],
               today: datetime.date, to: Optional[str] = None) -> List[Row]:
    """One overview row per target: the update choice and the recommendations. Read-only."""
    update_cfg, backup_cfg = _configs(opts)
    tags_of: Dict[int, Optional[Set[str]]] = {}
    rows: List[Row] = []
    for target in targets:
        tags = None
        if target.version is not None and not target.foreign:
            major = target.version[0]
            if major not in tags_of:
                tags_of[major] = hub_tags(major, fetch) if fetch else hub_tags(major)
            tags = tags_of[major]
        choice = choose(target, tags, to)
        if opts.sizing == "skip":
            sizing = SizingView({}, {}, {}, "skipped")
        else:
            try:
                sizing = sizing_view(target, update_cfg, opts.role, run)
            except Exception as error:      # the overview must not die on the calculation
                sizing = SizingView({}, {}, {}, "sizing unavailable: %s" % error)
        _, unlisted = backup_routes(_list_databases(target, run) or [], backup_cfg, target.name)
        rows.append((target, choice, recommend(target, choice, sizing, unlisted, today,
                                               collation_mismatches(target, run))))
    return rows


def _plan_text(plan: UpdatePlan, dry_run: bool) -> str:
    if plan.problems == [NOTHING_TO_DO]:
        return "%s: nothing to do, the newest patch release is running" % plan.target.name
    return render_plan(plan, dry_run=dry_run)


def _run_series(chosen: List[Tuple[PgTarget, Choice]], opts: Options, sizing_given: bool,
                interactive: bool, run: Runner, stream: Runner, out, ask_line) -> int:
    """Phase 1 for every chosen container, one confirmation, then phase 2 in the given order."""
    items = [[prepare(target, choice, opts, run), opts] for target, choice in chosen]

    def show(item) -> None:
        out("")
        out(_plan_text(item[0], opts.dry_run))

    for item in items:
        show(item)
    dialog = interactive and not opts.no_input and not opts.dry_run
    if dialog:
        for item in items:
            plan = item[0]
            if plan.problems or opts.role or plan.sizing.skipped != "role unknown":
                continue
            answer = ask_line("Role of %s (%s, Enter to skip):"
                              % (plan.target.name, "/".join(ROLES))).strip().lower()
            if answer in ROLES:
                item[1] = replace(opts, role=answer)
                item[0] = prepare(plan.target, plan.choice, item[1], run)
                show(item)

    broken = [plan.target.name for plan, _ in items
              if plan.problems and plan.problems != [NOTHING_TO_DO]]
    if broken:
        out("")
        out("Nothing was started: %s cannot be updated (see above). Solve that or leave the "
            "container out." % ", ".join(broken))
        return 2
    todo = [(plan, item_opts) for plan, item_opts in items if not plan.problems]
    if opts.dry_run or not todo:
        return 0
    if not interactive and not opts.no_input:
        out("")
        out("Nothing was started: this call needs --no-input to run without a terminal.")
        return 2
    if dialog:
        out("")
        if not sizing_given and any(plan.sizing.differs for plan, _ in todo):
            if ask_line("Apply the recommended memory settings? (y/N)").strip().lower() in (
                    "y", "yes"):
                todo = [(plan, replace(item_opts, sizing="apply")) for plan, item_opts in todo]
        names = ", ".join(plan.target.name for plan, _ in todo)
        if ask_line("Update %s now? (y/N)" % names).strip().lower() not in ("y", "yes"):
            out("Nothing was changed.")
            return 0

    for index, (plan, item_opts) in enumerate(todo):
        out("")
        code = update_one(plan, item_opts, run, stream, out)
        if code != 0:
            waiting = [later.target.name for later, _ in todo[index + 1:]]
            if waiting:
                out("")
                out("Not started: %s" % ", ".join(waiting))
            return code
    return 0


def main(argv=None, run: Optional[Runner] = None, stream: Optional[Runner] = None,
         fetch: Optional[Fetch] = None, stdin=None, out=print) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.to and len(args.container) != 1:
        parser.error("--to needs exactly one --container")
    run = run or default_runner
    stream = stream or default_stream
    stdin = stdin if stdin is not None else sys.stdin
    try:
        interactive = bool(stdin.isatty())
    except (AttributeError, ValueError):
        interactive = False
    opts = Options(to=args.to, dry_run=args.dry_run, no_input=args.no_input,
                   sizing=args.sizing or "show", role=args.role, db_user=args.db_user,
                   skip_backup=args.skip_backup, force=args.force,
                   update_config=args.config or "")

    def problem(text: str) -> None:
        # --json promises one document on stdout, so its errors go to stderr.
        if args.json:
            sys.stderr.write(text + "\n")
        else:
            out(text)

    def ask_line(question: str) -> str:
        out(question)
        try:
            return stdin.readline()
        except (OSError, ValueError):
            return ""

    if not args.json and hasattr(os, "geteuid") and os.geteuid() != 0:
        out("Note: not running as root; the memory settings and the check of the data "
            "directory need root.")

    if args.rollback:
        ask = None
        if interactive and not args.no_input:
            def ask(question: str) -> bool:
                return ask_line(question + " (y/N)").strip().lower() in ("y", "yes")
        return rollback(args.rollback, opts, run, out, ask=ask)

    code, _ = run(["docker", "ps", "-aq"])
    if code != 0:
        problem("ERROR: Docker cannot be asked (docker ps failed); nothing was changed.")
        return 2
    try:
        update_cfg, _ = _configs(opts)
        targets = discover(run, update_cfg, opts.db_user)
    except RuntimeError as error:
        problem("ERROR: %s" % error)
        return 2
    by_name = {target.name: target for target in targets}
    unknown = [name for name in args.container if name not in by_name]
    if unknown:
        problem("No running PostgreSQL container named %s. Found: %s"
                % (", ".join(unknown), ", ".join(sorted(by_name)) or "none"))
        return 2
    wanted: List[PgTarget] = []
    for name in args.container:
        if by_name[name] not in wanted:
            wanted.append(by_name[name])
    today = datetime.date.today()

    if args.json:
        out(json.dumps(overview_json(build_rows(wanted or targets, opts, run, fetch, today)),
                       indent=2))
        return 0
    if wanted:
        rows = build_rows(wanted, opts, run, fetch, today, to=opts.to)
        return _run_series([(target, choice) for target, choice, _ in rows], opts,
                           args.sizing is not None, interactive, run, stream, out, ask_line)

    if not targets:
        out("No running PostgreSQL container found.")
        return 0
    rows = build_rows(targets, opts, run, fetch, today)
    if not interactive or args.no_input:
        out(render_overview(rows, prompt=False))
        return 0
    recommended = {number for number, (_, choice, _) in enumerate(rows, 1) if choice.tag}
    out(render_overview(rows, prompt=False))
    out("")
    while True:
        picked = parse_selection(ask_line(SELECT_PROMPT), len(rows), recommended)
        if picked is not None:
            break
        out("Not understood.")
    if not picked:
        return 0
    return _run_series([(rows[number - 1][0], rows[number - 1][1]) for number in picked], opts,
                       args.sizing is not None, interactive, run, stream, out, ask_line)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        # update_one and rollback handle Ctrl-C themselves; this is a prompt or a check.
        print("\nInterrupted; nothing was changed by this step.")
        sys.exit(130)
