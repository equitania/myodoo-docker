#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Title:            ownerp_wizard.py
# Description:      Guided editing of docker2update.yaml - add an instance,
#                   change a field. Validates before it replaces anything.
# Version:          1.0.0
# Date:             12.08.2026
# Author:           Equitania Software GmbH
# ==============================================================================
#
# This is the only tool in the ownERP set that writes to a customer's
# configuration. Every write goes through safe_write(): a timestamped backup,
# a temporary file in the same directory, a validation run against that file,
# and only then os.replace(). A rejected result leaves the original byte for
# byte as it was.
#
# It edits scalar fields only. pre_build_files and proxy are a list and a
# mapping - a value that spans lines has no single line to replace, and
# guessing at one is how a config file gets quietly corrupted. Those stay with
# mcedit, and so does removing an entry.
#
##############################################################################
import os
import re
import sys
import json
import shutil
import getpass
import argparse
import datetime
import collections

# The validator is not optional here. A wizard that cannot check its own
# output must not write, so there is nothing to degrade to - unlike the runner,
# which keeps a built-in check when the validator is missing.
try:
    import ownerp_validate as validator
except ImportError:  # pragma: no cover - depends on the installation
    validator = None

SCRIPT_VERSION = "1.0.0"
SCRIPT_DATE = "12.08.2026"

DEFAULT_UPDATE_CONFIG = os.path.join(os.path.expanduser("~"), "docker2update.yaml")


def split_comment(text):
    """Split a YAML line into its code part and its trailing comment.

    Quote-aware, because a naive split on '#' corrupts a line like

        volume: "--network x -v /opt/a#b:/data"  # note

    where the first '#' is part of the value. A '#' starts a comment only
    outside quotes and only when it follows whitespace or begins the line.

    The comment carries the whitespace that preceded it, so that
    code + comment reconstructs the line byte for byte - two spaces before a
    '#' must not silently become one.
    """
    in_single = in_double = False
    for index, char in enumerate(text):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            if index == 0 or text[index - 1].isspace():
                head = text[:index]
                code = head.rstrip()
                return code, head[len(code):] + text[index:]
    return text, ""


def format_value(value):
    """Render a Python value as a YAML scalar, matching the template style.

    Strings are double-quoted via json.dumps: YAML's double-quoted scalar
    style uses the same escapes as JSON, so this is both correct and shorter
    than hand-rolling the escaping.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(str(value))


KEY_RE = re.compile(r"^(?P<lead>\s*(?:-\s+)?)(?P<key>[A-Za-z0-9_]+)\s*:\s*")


def patch_line(line, new_value):
    """Rewrite one 'key: value' line, keeping everything except the value."""
    code, comment = split_comment(line)
    match = KEY_RE.match(code)
    if not match:
        raise ValueError(f"not a key line: {line!r}")
    return f"{match.group('lead')}{match.group('key')}: {format_value(new_value)}{comment}"


def entry_bounds(lines, start_line, indent):
    """Half-open 0-based range of the block starting at 1-based `start_line`.

    The block ends at the first following line that carries content at an
    indentation of `indent` or less - the next sibling entry or the next
    top-level key. Trailing blank lines belong to whatever comes after, not
    to this entry.
    """
    first = start_line - 1
    last = len(lines)
    for index in range(first + 1, len(lines)):
        stripped = lines[index].strip()
        if not stripped:
            continue
        current = len(lines[index]) - len(lines[index].lstrip())
        if current <= indent:
            last = index
            break
    # Give trailing blank lines back to the following block.
    while last > first + 1 and not lines[last - 1].strip():
        last -= 1
    return first, last


def backup_name(path, now=None):
    """Timestamped backup path, in the style of ngx-conf-wizard.sh.

    Never a single '.backup' that the next run overwrites: the run that needs
    a backup is often the one after the run that made the mistake.
    """
    stamp = (now or datetime.datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"{path}.bak-{stamp}"


def safe_write(path, new_lines, now=None):
    """Replace `path` with `new_lines`, but only if the result validates.

    Returns (ok, findings, backup). On rejection the original is untouched,
    the temporary file and the backup are removed, and backup is None - a
    backup of a file nobody changed is litter, and litter teaches operators to
    ignore .bak-* files.
    """
    backup = backup_name(path, now)
    shutil.copy2(path, backup)

    tmp = f"{path}.tmp-{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write("\n".join(new_lines))

        findings, fatal = validator.validate_update(tmp)
        errors = [f for f in findings if f.severity == validator.ERROR]
        if fatal is not None or errors:
            os.remove(tmp)
            os.remove(backup)
            return False, ([fatal] if fatal is not None else findings), None

        os.replace(tmp, path)
        return True, findings, backup
    except Exception:
        # Any unexpected failure leaves the original in place, and leaves
        # nothing behind that suggests otherwise.
        if os.path.exists(tmp):
            os.remove(tmp)
        if os.path.exists(backup):
            os.remove(backup)
        raise


Field = collections.namedtuple("Field", "name label help suggest")

# The values the shipped template carries, used when the configuration holds
# no entry to learn from - the first container on a fresh server should still
# be a guided walk, not a blank form.
TEMPLATE_DEFAULTS = {
    "active": True, "type": "F", "delay_time": 10,
    "port": 11000, "longpolling_port": 12000,
    "dockerfile_path": "$HOME/docker-builds/{name}/",
    "docker_image_name": "odoo/{name}", "db_user": "ownerp",
    "odoo_version": "18", "translate": "Y", "db_password_via_env": True,
}


def used_ports(containers):
    """Every host port already taken, from both port fields of every entry.

    Inactive entries count: their ports are still written down, and an
    operator who reactivates one must not find it clashing with something the
    wizard handed out in the meantime.
    """
    taken = set()
    for container in containers:
        for field in ("port", "longpolling_port"):
            number = validator.parse_port(container.get(field))
            if number is not None:
                taken.add(number)
    return taken


def suggest_free_port(containers, step=1000):
    taken = used_ports(containers)
    if not taken:
        return TEMPLATE_DEFAULTS["port"]
    candidate = max(taken) + step
    while candidate in taken:
        candidate += step
    return candidate


def suggest_longpolling(containers, http_port, step=1000):
    taken = used_ports(containers) | {http_port}
    candidate = http_port + step
    while candidate in taken:
        candidate += step
    return candidate


def suggest_unanimous(containers, field):
    """The value when every entry agrees on it, otherwise None."""
    values = {container.get(field) for container in containers
              if not validator.is_empty(container.get(field))}
    return values.pop() if len(values) == 1 else None


def suggest_path_pattern(containers, field, new_name):
    """The shared pattern of an existing field, with the new name substituted.

    Each entry's value is turned into a pattern by replacing its own container
    name with a placeholder. All entries must agree on the pattern; a
    disagreement means there is no convention to follow, and inventing one
    would be a guess dressed up as help.
    """
    patterns = set()
    for container in containers:
        value = container.get(field)
        name = container.get("container_name")
        if validator.is_empty(value) or validator.is_empty(name):
            continue
        if name not in str(value):
            return None
        patterns.add(str(value).replace(name, "{name}"))
    if len(patterns) != 1:
        return None
    return patterns.pop().format(name=new_name)


def suggest_image_name(containers, new_name):
    """Follow the shipped convention: live-odoo -> odoo/live.

    Name substitution cannot do this one - "live-odoo" does not occur in
    "odoo/live". What is shared is the prefix up to and including the last
    slash; the tail is the container name's first '-' separated token.
    """
    if not new_name:
        return None
    prefixes = {str(c["docker_image_name"]).rsplit("/", 1)[0] + "/"
                for c in containers
                if not validator.is_empty(c.get("docker_image_name"))
                and "/" in str(c.get("docker_image_name", ""))}
    if len(prefixes) > 1:
        return None
    prefix = prefixes.pop() if prefixes else "odoo/"
    return prefix + new_name.split("-")[0]


UPDATE_FORM = [
    Field("active", "Take part in updates",
          "false parks the entry - doup skips it until you select it by name",
          lambda c, e: TEMPLATE_DEFAULTS["active"]),
    Field("type", "Update mode",
          "M = modules only (2-3 min), F = full (10-20 min), "
          "N = neutralize the database first, then a full update",
          lambda c, e: TEMPLATE_DEFAULTS["type"]),
    Field("delay_time", "Delay before restart (seconds)",
          "how long to wait for the container to stop before starting it again",
          lambda c, e: suggest_unanimous(c, "delay_time")
          or TEMPLATE_DEFAULTS["delay_time"]),
    Field("container_name", "Container name",
          "the Docker container name, e.g. live-odoo", None),
    Field("database_name", "Database name",
          "the Odoo database this container serves", None),
    Field("port", "HTTP port",
          "host port, mapped to 8069 inside the container; "
          'accepts 11000 or "127.0.0.1:11000"',
          lambda c, e: suggest_free_port(c)),
    Field("longpolling_port", "Longpolling port",
          "host port, mapped to 8072 inside the container",
          lambda c, e: suggest_longpolling(c, validator.parse_port(e.get("port")) or 0)),
    Field("dockerfile_path", "Build folder",
          "the folder holding the Dockerfile for this instance",
          lambda c, e: suggest_path_pattern(c, "dockerfile_path",
                                            e.get("container_name", ""))
          or TEMPLATE_DEFAULTS["dockerfile_path"].format(
              name=e.get("container_name", ""))),
    Field("docker_image_name", "Image name",
          "the tag docker build writes, e.g. odoo/live",
          lambda c, e: suggest_image_name(c, e.get("container_name", ""))),
    Field("db_user", "Database user",
          "the PostgreSQL role Odoo connects as",
          lambda c, e: suggest_unanimous(c, "db_user")
          or TEMPLATE_DEFAULTS["db_user"]),
    Field("db_password", "Database password",
          "not echoed, and never shown again in this session", None),
    Field("db_host", "Database host",
          "hostname or IP of the PostgreSQL container",
          lambda c, e: suggest_unanimous(c, "db_host")),
    Field("volume", "Docker volume and network arguments",
          "passed to docker run verbatim, e.g. "
          "--network live-db-net -v /opt/odoo/live:/opt/odoo/data", None),
    Field("odoo_version", "Odoo version",
          "major version as a string, e.g. 18",
          lambda c, e: suggest_unanimous(c, "odoo_version")
          or TEMPLATE_DEFAULTS["odoo_version"]),
    Field("translate", "Load translations",
          "Y or N",
          lambda c, e: TEMPLATE_DEFAULTS["translate"]),
    Field("db_password_via_env", "Pass the password via environment",
          "true keeps it out of argv, where every local user can read it "
          "with ps aux - set false only for legacy images",
          lambda c, e: TEMPLATE_DEFAULTS["db_password_via_env"]),
]
