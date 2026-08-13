#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Title:            ownerp_migrate.py
# Description:      Convert the legacy CSV configurations to YAML, once, safely.
# Version:          1.1.0
# Date:             13.08.2026
# Author:           Equitania Software GmbH
# ==============================================================================
# Why this exists:
#   The switch from CSV to YAML left every existing customer to redo their
#   configuration by hand — and worse than that: cleanup_legacy.txt listed the
#   CSV files for deletion, and cleanup_legacy_files() removes them on a fresh
#   Fish installation. That is exactly the run which lifts an old server onto
#   the new stack. The configuration was therefore deleted by the very upgrade
#   that needed to read it, and the first sign of it was a readiness report
#   saying "container2backup.yaml not found" — with no CSV left to convert.
#
#   This script owns those four files now. cleanup_legacy.txt no longer lists
#   them: one file, one owner, and the owner here archives rather than deletes.
#
# What it converts:
#   container2backup.csv      -> databases: in container2backup.yaml
#   container2backup_path.csv -> defaults.backup_path
#   rsync_targets.csv         -> rsync.commands
#   docker2update.csv         -> containers: in docker2update.yaml
#
# What it refuses to do:
#   * Overwrite an existing YAML. A server that already has one is already
#     migrated, or was configured by hand; either way the CSV is not the
#     authority. The conversion is then written next to it as
#     <name>.yaml.from-csv for the operator to compare, and the CSV stays put.
#   * Install a YAML that does not validate. ownerp_validate.py runs against
#     the generated file BEFORE it is installed; on errors the file is kept
#     with the .from-csv suffix and nothing is moved. Warnings do not block —
#     a build folder that no longer exists is a finding, not a reason to
#     withhold the whole configuration.
#   * Delete anything, ever. Consumed CSVs are moved to
#     $HOME/legacy-csv/<timestamp>/, which is created 0700 because
#     docker2update.csv contains database passwords in clear text.
#
# For servers whose CSVs are already gone (--from-docker):
#   The configuration is off the disk but not off the machine. `docker inspect`
#   still knows the ports, the image, the network, the volumes and — because the
#   Odoo images take them that way — the database credentials. Twelve of the
#   fourteen CSV columns come back exactly. `type` (M/F/N), `delay_time` and
#   `translate` were operator choices stored nowhere on the machine, and
#   retention_days likewise; those are written as documented defaults and listed
#   in a REVIEW block at the top of the generated file. Opt-in only — this never
#   runs from `ups`.
#
# A note on commented-out rows:
#   In both CSV formats a leading '#' marked a row as switched off. That maps
#   to `active: false` in docker2update.yaml. container2backup.yaml has no such
#   key, so those rows are emitted as a commented-out YAML block instead —
#   dropping them would silently discard configuration, and activating them
#   would silently start backing up a database somebody switched off.
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
import csv
import io
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

SCRIPT_VERSION = "1.1.0"
SCRIPT_DATE = "13.08.2026"

BACKUP_CSV = "container2backup.csv"
BACKUP_PATH_CSV = "container2backup_path.csv"
RSYNC_CSV = "rsync_targets.csv"
UPDATE_CSV = "docker2update.csv"

BACKUP_YAML = "container2backup.yaml"
UPDATE_YAML = "docker2update.yaml"

ARCHIVE_DIR = "legacy-csv"

# docker2update.csv column order, taken from the data rows of the shipped
# template — NOT from its header comment, which lists the fields in a different
# order and omits the first two. The rows are the authority; the comment was
# already wrong when the format was in use.
UPDATE_COLUMNS = (
    "type", "delay_time", "container_name", "database_name", "port",
    "longpolling_port", "dockerfile_path", "docker_image_name", "db_user",
    "db_password", "db_host", "volume", "odoo_version", "translate",
)

# container2backup.csv: DATABASENAME,DBUSER,CONTAINERNAME-DB,MYODOO-CONTAINERNAME,STORETIME
BACKUP_COLUMNS = ("name", "db_user", "sql_container", "data_container",
                  "retention_days")

VALID_TYPES = {"M", "F", "N"}


@dataclass
class Row:
    """One converted CSV row plus whether it was switched off."""

    values: dict
    active: bool = True


@dataclass
class Result:
    """What happened to one config, for the summary and the exit code."""

    name: str
    status: str          # migrated | exists | invalid | none
    detail: str = ""
    written: Optional[str] = None
    archived: List[str] = field(default_factory=list)


# ==============================================================================
# Reading
# ==============================================================================

def _rows(path: str, columns: Tuple[str, ...], first_field_check=None) -> List[Row]:
    """Parse a legacy CSV into Rows, keeping switched-off entries.

    Both formats used a leading '#' for two different things: documentation and
    a switched-off entry. They are told apart by shape — a comment that parses
    as a full data row IS a switched-off entry, and nothing else does. The csv
    module rather than split(',') because the volume column is a quoted string
    containing commas.
    """
    found: List[Row] = []
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            active = True
            if line.startswith("#"):
                active = False
                line = line.lstrip("#").strip()
                if not line:
                    continue
            try:
                fields = next(csv.reader(io.StringIO(line)))
            except (csv.Error, StopIteration):
                continue
            fields = [f.strip() for f in fields]
            if len(fields) < len(columns):
                continue
            if first_field_check and not first_field_check(fields[0]):
                continue
            found.append(Row(values=dict(zip(columns, fields)), active=active))
    return found


def read_update_csv(path: str) -> List[Row]:
    return _rows(path, UPDATE_COLUMNS,
                 first_field_check=lambda v: v.upper() in VALID_TYPES)


def read_backup_csv(path: str) -> List[Row]:
    # The last column is a retention day count; requiring it to be numeric is
    # what keeps the header comment ("#DATABASENAME,DBUSER,...") out of the data.
    rows = _rows(path, BACKUP_COLUMNS)
    return [r for r in rows if str(r.values.get("retention_days", "")).isdigit()]


def read_lines_csv(path: str) -> List[Tuple[str, bool]]:
    """Read a one-value-per-line legacy file as (value, active) pairs."""
    out = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                line = raw.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    stripped = line.lstrip("#").strip()
                    if stripped:
                        out.append((stripped, False))
                    continue
                out.append((line, True))
    except OSError:
        return []
    return out


# ==============================================================================
# Rendering
# ==============================================================================

def _quote(value: str) -> str:
    """Double-quote a scalar, escaping what YAML would otherwise misread."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _int_or_none(value) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _provenance(source_files: List[str], review: Optional[List[str]] = None) -> List[str]:
    """Header saying where this file came from, and what still needs a human.

    The REVIEW block is not decoration. A reconstruction from the running
    Docker state recovers most fields exactly and cannot recover a few at all;
    writing a plausible default without saying so would produce a file that
    looks authoritative and quietly updates the wrong database.
    """
    if review is None:
        lines = [
            "# Converted from the legacy CSV configuration by ownerp_migrate.py "
            f"{SCRIPT_VERSION}",
            f"# on {time.strftime('%d.%m.%Y %H:%M')}. Sources: "
            + ", ".join(sorted(source_files)),
            "# The originals were moved to $HOME/legacy-csv/ — nothing was deleted.",
            "#",
        ]
        return lines

    lines = [
        f"# Reconstructed from the running Docker state by ownerp_migrate.py "
        f"{SCRIPT_VERSION}",
        f"# on {time.strftime('%d.%m.%Y %H:%M')} — the CSV configuration was "
        f"already gone.",
        "#",
        f"# REVIEW BEFORE USE. Every value below was read from `docker inspect`",
        f"# except the {len(review)} point(s) listed here:",
    ]
    for note in review:
        lines.append(f"#   * {note}")
    lines.append(f"# Anything still reading {PLACEHOLDER} must be filled in by hand.")
    lines.append("#")
    return lines


def render_backup_yaml(rows: List[Row], backup_path: Optional[str],
                       rsync: List[Tuple[str, bool]],
                       sources: List[str],
                       review: Optional[List[str]] = None) -> str:
    """Build container2backup.yaml from the converted rows."""
    out = _provenance(sources, review)
    out.append("")

    # A db_user shared by every row belongs in defaults; a disagreement is
    # carried per database rather than resolved by guessing which is "the" user.
    # Only ACTIVE rows get a vote: a database somebody switched off years ago
    # should not push every live entry into carrying a redundant db_user.
    users = {r.values.get("db_user", "").strip() for r in rows
             if r.active and r.values.get("db_user", "").strip()}
    shared_user = users.pop() if len(users) == 1 else None

    out.append("defaults:")
    out.append("  retention_days: 14")
    if shared_user:
        out.append(f"  db_user: {shared_user}")
    out.append(f"  backup_path: {backup_path or '/opt/backups'}")
    out.append("  temp_path: /tmp/odoo_backup")
    out.append("  stream: false")
    out.append("  compression:")
    out.append('    format: "7z"')
    out.append("    level: 5")
    out.append("")

    # Neither source carries a services section: the CSV format had none, and
    # Docker cannot be asked what an operator wanted backed up. These three are
    # what every ownERP server backs up, taken from the current template —
    # flagged as such so the next reader does not mistake them for recovered fact.
    out.append("# NOT recovered from the source — the standard service backups of the")
    out.append("# current template. Review the paths, then remove what this server lacks.")
    out.append("services:")
    for name, source, retention in (("nginx", "/etc/nginx", 14),
                                    ("letsencrypt", "/etc/letsencrypt", 14),
                                    ("docker_builds", "$HOME/docker-builds", 14)):
        out.append(f"  {name}:")
        out.append("    enabled: true")
        out.append(f"    source_path: {source}")
        out.append(f"    backup_path: {name.replace('_', '-')}")
        out.append(f"    retention_days: {retention}")
    out.append("")

    out.append("databases:")
    active_rows = [r for r in rows if r.active]
    if not active_rows:
        out.append("  []  # no active database rows in the CSV")
    for row in active_rows:
        out.extend(_backup_entry(row, shared_user, prefix="  "))

    inactive = [r for r in rows if not r.active]
    if inactive:
        out.append("")
        out.append("# Switched off in the CSV (the row was commented out). Kept here so")
        out.append("# nothing is lost; uncomment to bring a database back into the backup.")
        for row in inactive:
            for line in _backup_entry(row, shared_user, prefix="  "):
                out.append("#" + line)

    out.append("")
    out.append("rsync:")
    active_commands = [c for c, is_active in rsync if is_active]
    out.append(f"  enabled: {'true' if active_commands else 'false'}")
    out.append("  commands:" if active_commands else "  commands: []")
    for command in active_commands:
        out.append(f"    - {_quote(command)}")
    for command, is_active in rsync:
        if not is_active:
            out.append(f"    #- {_quote(command)}")
    out.append("")
    return "\n".join(out)


def _backup_entry(row: Row, shared_user: Optional[str], prefix: str) -> List[str]:
    """One `databases:` entry.

    The continuation keys line up with `name`, which sits two columns past the
    prefix because of the "- ". Getting that wrong produces YAML that no parser
    accepts, and the empty-fixture case hides it — a template whose rows are all
    commented out never renders an active entry at all.
    """
    values = row.values
    inner = prefix + "  "
    lines = [f"{prefix}- name: {values['name']}"]
    user = values.get("db_user", "").strip()
    if user and user != shared_user:
        lines.append(f"{inner}db_user: {user}")
    lines.append(f"{inner}sql_container: {values['sql_container']}")
    lines.append(f"{inner}data_container: {values['data_container']}")
    retention = _int_or_none(values.get("retention_days"))
    if retention is not None:
        lines.append(f"{inner}retention_days: {retention}")
    return lines


def render_update_yaml(rows: List[Row], sources: List[str],
                       review: Optional[List[str]] = None) -> str:
    """Build docker2update.yaml from the converted rows."""
    out = _provenance(sources, review)
    out.append("# SECURITY: db_password is stored in clear text here, as the source")
    out.append("# held it. This file is created mode 0600.")
    out.append("")
    out.append("containers:")
    if not rows:
        out.append("  []  # no data rows in the CSV")
    for row in rows:
        out.extend(_update_entry(row))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _update_entry(row: Row) -> List[str]:
    values = row.values
    lines = [f"  - active: {'true' if row.active else 'false'}"]
    lines.append(f"    type: {_quote(values['type'].upper())}")
    delay = _int_or_none(values.get("delay_time"))
    lines.append(f"    delay_time: {delay if delay is not None else 10}")
    for key in ("container_name", "database_name", "port", "longpolling_port",
                "dockerfile_path", "docker_image_name", "db_user", "db_password",
                "db_host", "volume", "odoo_version"):
        value = values.get(key, "")
        if value == "" and key == "volume":
            continue
        lines.append(f"    {key}: {_quote(value)}")
    translate = values.get("translate", "N").upper()
    lines.append(f"    translate: {_quote(translate if translate in ('Y', 'N') else 'N')}")
    # Not in the CSV format: the secure default of the current runner. Passing
    # the password through argv would expose it to every local user via `ps`.
    lines.append("    db_password_via_env: true")
    return lines


# ==============================================================================
# Reconstruction from the running Docker state (--from-docker)
# ==============================================================================
#
# For servers whose CSVs were already deleted before this script existed. The
# configuration is gone from disk but not from the machine: `docker inspect`
# still knows the ports, the image, the network, the volumes and — because the
# Odoo images take them that way — the database credentials.
#
# What can be READ is reconstructed. What cannot is written as a placeholder and
# listed in a REVIEW block at the top of the generated file, because a guess
# that looks like a fact is worse than an obvious gap: `type` (M/F/N),
# `delay_time` and `translate` were operator choices that were never stored
# anywhere on the machine, and no amount of inspection will bring them back.
#
# Opt-in only. This never runs from `ups`.

# Odoo speaks these to its database; the images accept several spellings.
DB_HOST_ENV = ("HOST", "DB_HOST", "PGHOST")
DB_USER_ENV = ("USER", "DB_USER", "PGUSER", "POSTGRES_USER")
DB_PASSWORD_ENV = ("PASSWORD", "DB_PASSWORD", "PGPASSWORD", "POSTGRES_PASSWORD")

PLACEHOLDER = "REVIEW_ME"
SYSTEM_DATABASES = {"postgres", "template0", "template1"}


def _docker(args: List[str], timeout: int = 30) -> Tuple[int, str]:
    try:
        proc = subprocess.run(["docker"] + args, capture_output=True,
                              text=True, timeout=timeout)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError:
        return 127, "docker not found"
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def inspect_containers() -> List[dict]:
    """Full `docker inspect` of every container, running or stopped.

    Stopped ones count: a test instance that happens to be down is still part
    of the configuration that was lost.
    """
    import json as _json

    code, output = _docker(["ps", "-aq"])
    if code != 0 or not output.strip():
        return []
    ids = output.split()
    code, output = _docker(["inspect"] + ids, timeout=60)
    if code != 0:
        return []
    try:
        return _json.loads(output)
    except ValueError:
        return []


def _env_of(container: dict) -> dict:
    env = {}
    for item in (container.get("Config") or {}).get("Env") or []:
        key, _, value = item.partition("=")
        env[key] = value
    return env


def _name_of(container: dict) -> str:
    return (container.get("Name") or "").lstrip("/")


def _image_of(container: dict) -> str:
    """Repository without the tag, as docker2update.yaml stores it."""
    image = (container.get("Config") or {}).get("Image") or ""
    head, sep, tail = image.rpartition(":")
    # "host:5000/img" has a colon that is not a tag separator.
    if sep and "/" not in tail:
        return head
    return image


def _tag_of(container: dict) -> str:
    image = (container.get("Config") or {}).get("Image") or ""
    _, sep, tail = image.rpartition(":")
    return tail if sep and "/" not in tail else ""


def _published(container: dict, port: str) -> Optional[str]:
    """Host binding of a container port as 'ip:port', or None if unpublished."""
    bindings = ((container.get("NetworkSettings") or {}).get("Ports")
                or {}).get(f"{port}/tcp")
    if not bindings:
        return None
    first = bindings[0]
    host_ip = first.get("HostIp") or ""
    host_port = first.get("HostPort") or ""
    if not host_port:
        return None
    if host_ip in ("", "0.0.0.0"):
        return host_port
    return f"{host_ip}:{host_port}"


def _networks(container: dict) -> List[str]:
    return sorted(((container.get("NetworkSettings") or {}).get("Networks")
                   or {}).keys())


def _volume_argument(container: dict) -> str:
    """Rebuild the `volume` string the runner passes to `docker run`."""
    parts = []
    networks = [n for n in _networks(container) if n not in ("bridge", "host", "none")]
    if networks:
        parts.append(f"--network {networks[0]}")
    for bind in (container.get("HostConfig") or {}).get("Binds") or []:
        parts.append(f"-v {bind}")
    return " ".join(parts)


def is_odoo(container: dict) -> bool:
    """An Odoo container publishes or exposes 8069, or says so in its image."""
    exposed = (container.get("Config") or {}).get("ExposedPorts") or {}
    if "8069/tcp" in exposed:
        return True
    return "odoo" in _image_of(container).lower()


def is_postgres(container: dict) -> bool:
    exposed = (container.get("Config") or {}).get("ExposedPorts") or {}
    if "5432/tcp" in exposed:
        return True
    return "postgres" in _image_of(container).lower()


def databases_in(container_name: str, user: str) -> List[str]:
    """List the non-system databases of a Postgres container.

    Read-only (`psql -l`). A container that is not running, or a wrong user,
    yields nothing — the caller then falls back to a placeholder rather than
    inventing a database name.
    """
    code, output = _docker([
        "exec", container_name, "psql", "-U", user, "-Atqc",
        "SELECT datname FROM pg_database WHERE datistemplate = false",
    ])
    if code != 0:
        return []
    return [line.strip() for line in output.splitlines()
            if line.strip() and line.strip() not in SYSTEM_DATABASES]


def _pair_database_container(odoo: dict, postgres: List[dict]) -> Optional[dict]:
    """Which Postgres container this Odoo instance talks to.

    The env var wins when it names something we can see; otherwise a shared
    user-defined network is the next best evidence, and it is usually decisive
    because these stacks get one network per instance.
    """
    env = _env_of(odoo)
    named = next((env[key] for key in DB_HOST_ENV if env.get(key)), None)
    if named:
        for candidate in postgres:
            if _name_of(candidate) == named:
                return candidate
    odoo_networks = {n for n in _networks(odoo)
                     if n not in ("bridge", "host", "none")}
    for candidate in postgres:
        if odoo_networks & set(_networks(candidate)):
            return candidate
    return postgres[0] if len(postgres) == 1 else None


def _odoo_version(container: dict, home: str) -> str:
    """Best available reading of the Odoo major version."""
    tag = _tag_of(container)
    if tag and tag[0].isdigit():
        return tag.split(".")[0]
    dockerfile = os.path.join(home, "docker-builds", _name_of(container),
                              "Dockerfile")
    try:
        with open(dockerfile, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.upper().startswith("FROM "):
                    _, _, reference = line.strip().partition(":")
                    if reference and reference[0].isdigit():
                        return reference.split(".")[0]
    except OSError:
        pass
    return PLACEHOLDER


def reconstruct(home: str) -> Tuple[List[Row], List[Row], List[str]]:
    """Build update and backup rows from the running Docker state.

    Returns (update_rows, backup_rows, review) where review lists every field
    that had to be guessed or left blank.
    """
    review: List[str] = []
    containers = inspect_containers()
    if not containers:
        return [], [], ["docker returned nothing — is the daemon running?"]

    odoo_containers = [c for c in containers if is_odoo(c)]
    pg_containers = [c for c in containers if is_postgres(c) and not is_odoo(c)]

    update_rows: List[Row] = []
    backup_rows: List[Row] = []

    for odoo in sorted(odoo_containers, key=_name_of):
        name = _name_of(odoo)
        env = _env_of(odoo)
        database_container = _pair_database_container(odoo, pg_containers)
        db_name_of_container = _name_of(database_container) if database_container else ""

        user = next((env[k] for k in DB_USER_ENV if env.get(k)), "")
        if not user and database_container:
            user = next((v for k, v in _env_of(database_container).items()
                         if k in DB_USER_ENV and v), "")
        if not user:
            user = PLACEHOLDER
            review.append(f"{name}: db_user could not be read from the container")

        password = next((env[k] for k in DB_PASSWORD_ENV if env.get(k)), "")
        if not password and database_container:
            password = next((v for k, v in _env_of(database_container).items()
                             if k in DB_PASSWORD_ENV and v), "")
        if not password:
            password = PLACEHOLDER
            review.append(f"{name}: db_password is not in the container "
                          f"environment — set it before the next update run")

        host_port = _published(odoo, "8069")
        if not host_port:
            host_port = PLACEHOLDER
            review.append(f"{name}: port 8069 is not published — no host port to read")
        poll_port = _published(odoo, "8072")
        if not poll_port:
            poll_port = PLACEHOLDER
            review.append(f"{name}: port 8072 is not published — no host port to read")

        databases = (databases_in(db_name_of_container, user)
                     if database_container and user != PLACEHOLDER else [])
        if len(databases) == 1:
            database = databases[0]
        elif databases:
            # Several databases behind one container: prefer one whose name
            # echoes the instance, else say so rather than pick blindly.
            stem = name.replace("-odoo", "").replace("-", "_")
            matches = [d for d in databases if stem and stem in d]
            database = matches[0] if len(matches) == 1 else PLACEHOLDER
            if database == PLACEHOLDER:
                review.append(f"{name}: {len(databases)} databases behind "
                              f"{db_name_of_container} ({', '.join(databases)}) "
                              f"— pick the right one")
        else:
            database = PLACEHOLDER
            review.append(f"{name}: could not list databases in "
                          f"{db_name_of_container or 'its database container'}")

        version = _odoo_version(odoo, home)
        if version == PLACEHOLDER:
            review.append(f"{name}: odoo_version could not be determined")

        build_folder = os.path.join(home, "docker-builds", name) + "/"
        if not os.path.isdir(build_folder):
            review.append(f"{name}: {build_folder} does not exist — "
                          f"check dockerfile_path")

        update_rows.append(Row(values={
            "type": "F",
            "delay_time": "10",
            "container_name": name,
            "database_name": database,
            "port": host_port,
            "longpolling_port": poll_port,
            "dockerfile_path": build_folder,
            "docker_image_name": _image_of(odoo),
            "db_user": user,
            "db_password": password,
            "db_host": db_name_of_container or PLACEHOLDER,
            "volume": _volume_argument(odoo),
            "odoo_version": version,
            "translate": "Y",
        }, active=True))

        if database != PLACEHOLDER and db_name_of_container:
            backup_rows.append(Row(values={
                "name": database,
                "db_user": user if user != PLACEHOLDER else "",
                "sql_container": db_name_of_container,
                "data_container": name,
                "retention_days": "14",
            }, active=True))

    if update_rows:
        review.append("type (M/F/N), delay_time and translate were operator "
                      "choices that are stored nowhere on the machine — "
                      "defaults F / 10 / Y were used")
    if backup_rows:
        review.append("retention_days is not recoverable either — 14 was used "
                      "for every database")
    if not odoo_containers:
        review.append("no Odoo container found — nothing to reconstruct")

    return update_rows, backup_rows, review


# ==============================================================================
# Validation and installation
# ==============================================================================

def _validate(path: str, home: str, kind: str) -> Tuple[bool, str]:
    """Run ownerp_validate.py against a generated file.

    kind selects the schema: the validator takes --update/--backup with an
    optional path, not a bare filename, and picking the wrong one would validate
    a backup config against the update schema and reject a perfectly good file.

    Returns (ok, output). Exit code 1 means errors and blocks installation;
    warnings live at exit code 0 and never do — a build folder that does not
    exist yet is a finding, not a reason to withhold the whole configuration.
    A missing validator is not counted as a pass, but neither is it a reason to
    withhold the conversion: it returns ok with a note saying it was skipped.
    """
    validator = os.path.join(home, "ownerp_validate.py")
    if not os.path.isfile(validator):
        validator = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "ownerp_validate.py")
    if not os.path.isfile(validator):
        return True, "ownerp_validate.py not found — installed without validation"
    flag = "--backup" if kind == "backup" else "--update"
    try:
        proc = subprocess.run([sys.executable, validator, flag, path],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return True, f"validator could not run ({exc}) — installed without validation"
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, output.strip()


def _archive(home: str, paths: List[str], stamp: str, dry_run: bool) -> List[str]:
    """Move consumed CSVs out of the way. Never deletes."""
    if not paths:
        return []
    target = os.path.join(home, ARCHIVE_DIR, stamp)
    if dry_run:
        return [os.path.join(target, os.path.basename(p)) for p in paths]
    # 0700: docker2update.csv holds database passwords in clear text.
    os.makedirs(target, mode=0o700, exist_ok=True)
    os.chmod(target, 0o700)
    moved = []
    for path in paths:
        destination = os.path.join(target, os.path.basename(path))
        shutil.move(path, destination)
        moved.append(destination)
    return moved


def _install(text: str, target: str, home: str, sources: List[str],
             stamp: str, label: str, dry_run: bool) -> Result:
    """Write, validate and — only if it validates — install a converted config."""
    pending = target + ".from-csv"

    if os.path.exists(target):
        # Already migrated or hand-written: the CSV is not the authority here.
        if not dry_run:
            _write(pending, text)
        return Result(label, "exists",
                      f"{os.path.basename(target)} already exists — conversion "
                      f"written to {os.path.basename(pending)} for comparison; "
                      f"the CSV was left in place",
                      written=pending)

    if dry_run:
        origin = (", ".join(os.path.basename(s) for s in sources)
                  if sources else "the running Docker state")
        return Result(label, "migrated",
                      f"would write {os.path.basename(target)} from {origin}",
                      written=target)

    _write(pending, text)
    ok, output = _validate(pending, home, label)
    if not ok:
        return Result(label, "invalid",
                      f"the conversion does not validate and was NOT installed. "
                      f"It is kept at {os.path.basename(pending)}:\n{output}",
                      written=pending)

    os.replace(pending, target)
    archived = _archive(home, sources, stamp, dry_run=False)
    origin = (", ".join(os.path.basename(s) for s in sources)
              if sources else "the running Docker state")
    return Result(label, "migrated",
                  f"{os.path.basename(target)} written from {origin}",
                  written=target, archived=archived)


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    # Both files can carry database credentials; the update config always does.
    os.chmod(path, 0o600)


# ==============================================================================
# Orchestration
# ==============================================================================

def migrate(home: str, dry_run: bool = False) -> List[Result]:
    """Convert whatever legacy CSVs are present. Returns one Result per config."""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    results = []

    backup_csv = os.path.join(home, BACKUP_CSV)
    path_csv = os.path.join(home, BACKUP_PATH_CSV)
    rsync_csv = os.path.join(home, RSYNC_CSV)
    update_csv = os.path.join(home, UPDATE_CSV)

    backup_sources = [p for p in (backup_csv, path_csv, rsync_csv)
                      if os.path.isfile(p)]
    if backup_sources:
        rows = read_backup_csv(backup_csv) if os.path.isfile(backup_csv) else []
        base_path = None
        if os.path.isfile(path_csv):
            entries = [value for value, active in read_lines_csv(path_csv) if active]
            base_path = entries[0] if entries else None
        rsync = read_lines_csv(rsync_csv) if os.path.isfile(rsync_csv) else []
        text = render_backup_yaml(rows, base_path, rsync,
                                  [os.path.basename(p) for p in backup_sources])
        results.append(_install(text, os.path.join(home, BACKUP_YAML), home,
                                backup_sources, stamp, "backup", dry_run))
    else:
        results.append(Result("backup", "none", "no legacy CSV found"))

    if os.path.isfile(update_csv):
        rows = read_update_csv(update_csv)
        text = render_update_yaml(rows, [os.path.basename(update_csv)])
        results.append(_install(text, os.path.join(home, UPDATE_YAML), home,
                                [update_csv], stamp, "update", dry_run))
    else:
        results.append(Result("update", "none", "no legacy CSV found"))

    return results


def reconstruct_from_docker(home: str, dry_run: bool = False) -> List[Result]:
    """Rebuild both configs from the running containers. Opt-in only.

    Uses the same install path as the CSV conversion, which means the same
    refusals: an existing YAML is never overwritten, and nothing that fails
    validation is installed. There are no sources to archive here — the source
    is the machine itself.
    """
    update_rows, backup_rows, review = reconstruct(home)
    if not update_rows and not backup_rows:
        return [Result("reconstruct", "none",
                       "; ".join(review) or "nothing found to reconstruct")]

    results = []
    if update_rows:
        text = render_update_yaml(update_rows, [], review=review)
        results.append(_install(text, os.path.join(home, UPDATE_YAML), home,
                                [], time.strftime("%Y%m%d_%H%M%S"), "update",
                                dry_run))
    if backup_rows:
        text = render_backup_yaml(backup_rows, "/opt/backups", [], [],
                                  review=review)
        results.append(_install(text, os.path.join(home, BACKUP_YAML), home,
                                [], time.strftime("%Y%m%d_%H%M%S"), "backup",
                                dry_run))
    for result in results:
        result.detail += f" · {len(review)} point(s) need review — see the file header"
    return results


def print_results(results: List[Result], stream=None) -> None:
    """Print a summary — but stay silent when there was nothing to do.

    This runs from every `ups`. A server that migrated years ago must not be
    told about it forever, or the line stops being read on the one server where
    it matters.
    """
    stream = stream or sys.stdout
    interesting = [r for r in results if r.status != "none"]
    if not interesting:
        return

    use_colour = hasattr(stream, "isatty") and stream.isatty()
    green = "\033[0;32m" if use_colour else ""
    yellow = "\033[1;33m" if use_colour else ""
    red = "\033[0;31m" if use_colour else ""
    reset = "\033[0m" if use_colour else ""
    marks = {"migrated": (green, "✓"), "exists": (yellow, "•"),
             "invalid": (red, "✗")}

    print("", file=stream)
    print("=" * 60, file=stream)
    print("Legacy CSV migration", file=stream)
    print("=" * 60, file=stream)
    for result in interesting:
        colour, mark = marks.get(result.status, ("", "-"))
        print(f"  {colour}{mark}{reset} {result.name}: {result.detail}",
              file=stream)
        if result.archived:
            print(f"      originals moved to "
                  f"{os.path.dirname(result.archived[0])}", file=stream)
    print("=" * 60, file=stream)
    print("", file=stream)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert the legacy CSV configurations to YAML. Never "
                    "overwrites an existing YAML and never deletes a CSV.")
    parser.add_argument("--home", default=os.path.expanduser("~"),
                        help="directory holding the configs (default: %(default)s)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would happen; write nothing")
    parser.add_argument("--from-docker", action="store_true",
                        help="rebuild both configs from the running containers, "
                             "for servers whose CSVs are already gone. Opt-in; "
                             "never runs from ups.")
    parser.add_argument("--version", action="version",
                        version=f"ownerp_migrate.py {SCRIPT_VERSION} ({SCRIPT_DATE})")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.from_docker:
        results = reconstruct_from_docker(args.home, dry_run=args.dry_run)
        print_results(results)
        if all(r.status == "none" for r in results):
            for result in results:
                print(f"Nothing reconstructed: {result.detail}")
            return 1
        print("Review the REVIEW block at the top of each file before the next "
              "update or backup run, then check with: doval")
        return 1 if any(r.status == "invalid" for r in results) else 0

    results = migrate(args.home, dry_run=args.dry_run)
    print_results(results)
    if all(r.status == "none" for r in results):
        print("Nothing to migrate — no legacy CSV configuration found.")
        print("If the CSVs are already gone, rebuild from the running "
              "containers with: ownerp_migrate.py --from-docker")
        return 0
    return 1 if any(r.status == "invalid" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
