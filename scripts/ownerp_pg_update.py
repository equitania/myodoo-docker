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
# This part is read-only: it finds the PostgreSQL containers, reads the running
# server version and the base, pairs them with their Odoo containers and
# chooses the tag to update to. It never changes a container.
#
# System Python 3 standard library only (yaml is read by the caller).
# ==============================================================================

import datetime
import importlib.util
import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

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
    return SizingView(recommended, current, differs, None)


def backup_routes(databases: List[str], backup_cfg: Optional[dict],
                  container: str) -> Tuple[List[str], List[str]]:
    """(listed, unlisted): databases container2backup.yaml covers via this container."""
    covered = {str(e.get("name")) for e in (backup_cfg or {}).get("databases") or []
               if isinstance(e, dict) and e.get("sql_container") == container}
    return ([d for d in databases if d in covered],
            [d for d in databases if d not in covered])


def collation_mismatches(target: PgTarget, run: Runner) -> List[str]:
    """Databases whose recorded collation version differs from the library's (major >= 15)."""
    if target.version is None or target.version[0] < 15:
        return []
    code, out = run(["docker", "exec", target.name, "psql", "-U", target.db_user or "postgres",
                     "-d", "postgres", "-Atqc",
                     "SELECT datname FROM pg_database WHERE datcollversion IS DISTINCT FROM "
                     "pg_database_collation_actual_version(oid) AND datcollversion IS NOT NULL"])
    if code != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def _eol_month(major: int) -> Optional[datetime.date]:
    match = re.match(r"^(\d{2})/(\d{4})$", EOL.get(major) or "")
    return datetime.date(int(match.group(2)), int(match.group(1)), 1) if match else None


def recommend(target: PgTarget, choice: Choice, sizing: SizingView, unlisted: List[str],
              today: datetime.date, collation_mismatch: List[str]) -> List[Rec]:
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


def render_overview(rows: List[Row]) -> str:
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
    out += ["", "Select (e.g. 1,3 - a for all recommended - Enter to leave):"]
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
                       "blocked": choice.blocked},
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
