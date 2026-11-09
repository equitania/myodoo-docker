#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Title:            ownerp_wizard.py
# Description:      Guided editing of docker2update.yaml and
#                   container2backup.yaml - add an entry, change a field.
#                   Validates before it replaces anything.
# Version:          1.3.0
# Date:             09.11.2026
# Author:           Equitania Software GmbH
# ==============================================================================
#
# This is the only tool in the ownERP set that writes to a customer's
# configuration. Every write goes through safe_write(): a timestamped backup,
# a temporary file in the same directory, a validation run against that file,
# and only then os.replace(). A rejected result leaves the original byte for
# byte as it was.
#
# It edits scalar fields only, plus one exception: the sizing block, a mapping
# that is written and replaced as a single-line flow mapping. pre_build_files
# and proxy are a list and a mapping - a value that spans lines has no single
# line to replace, and guessing at one is how a config file gets quietly
# corrupted. Those stay with mcedit, and so does removing an entry and a
# sizing block written over several lines.
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

# The sizing module is optional here: without it the review step only prints
# the command to run later.
try:
    import ownerp_sizing
except ImportError:  # pragma: no cover - depends on the installation
    ownerp_sizing = None

# The validator is not optional here. A wizard that cannot check its own
# output must not write, so there is nothing to degrade to - unlike the runner,
# which keeps a built-in check when the validator is missing.
try:
    import ownerp_validate as validator
except ImportError:  # pragma: no cover - depends on the installation
    validator = None

SCRIPT_VERSION = "1.3.0"
SCRIPT_DATE = "09.11.2026"

DEFAULT_UPDATE_CONFIG = os.path.join(os.path.expanduser("~"), "docker2update.yaml")
DEFAULT_BACKUP_CONFIG = os.path.join(os.path.expanduser("~"),
                                     "container2backup.yaml")

# The two configurations this tool may write to. Held as data rather than as
# two parallel code paths, because the mechanics are identical - a list of
# mappings under one top-level key - and only the names differ. A second write
# implementation is a second place for the backup/validate/replace sequence to
# drift out of step.
UPDATE = "update"
BACKUP = "backup"


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
    if isinstance(value, dict):
        # One-line flow mapping: it has a single line to find and replace,
        # which is the only reason a mapping may be written here at all.
        inner = ", ".join(f"{key}: {format_value(item)}"
                          for key, item in value.items())
        return "{" + inner + "}"
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


def safe_write(path, new_lines, now=None, kind=UPDATE):
    """Replace `path` with `new_lines`, but only if the result validates.

    Returns (ok, findings, backup). On rejection the original is untouched,
    the temporary file and the backup are removed, and backup is None - a
    backup of a file nobody changed is litter, and litter teaches operators to
    ignore .bak-* files.

    `kind` picks the schema. Validating a backup configuration against the
    update schema would reject every field it has and accept none it lacks,
    so the wrong one here is not a near miss - it is a tool that can never
    write that file.
    """
    validate = (validator.validate_backup if kind == BACKUP
                else validator.validate_update)
    backup = backup_name(path, now)
    shutil.copy2(path, backup)

    tmp = f"{path}.tmp-{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write("\n".join(new_lines))

        findings, fatal = validate(tmp)
        errors = [f for f in findings if f.severity == validator.ERROR]
        if fatal is not None or errors:
            os.remove(tmp)
            os.remove(backup)
            return False, ([fatal] if fatal is not None else findings), None

        os.replace(tmp, path)
        return True, findings, backup
    except BaseException:
        # BaseException, not Exception: a Ctrl-C between the copy and the
        # replace is an operator abort, and an abort must leave no .bak-* and
        # no .tmp-* behind. KeyboardInterrupt does not inherit from Exception,
        # so the narrower clause would walk straight past it.
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


def bind_prefix(value):
    """The bind address a port value carries, including the colon, or "".

    "127.0.0.1:11000" -> "127.0.0.1:",  "[::1]:11000" -> "[::1]:",  11000 -> ""
    """
    text = str(value).strip()
    if validator.parse_port(text) is None:
        return ""
    head, sep, _tail = text.rpartition(":")
    return head + sep if sep else ""


def suggest_bind(containers):
    """The bind address every existing port agrees on, or "".

    The shipped layout binds to 127.0.0.1 and puts nginx in front. A wizard
    that hands out a bare port number on such a host would publish the next
    instance on every interface - a change nobody asked for and nobody sees.
    """
    prefixes = set()
    for container in containers:
        for field in ("port", "longpolling_port"):
            value = container.get(field)
            if not validator.is_empty(value) and validator.parse_port(value):
                prefixes.add(bind_prefix(value))
    return prefixes.pop() if len(prefixes) == 1 else ""


def with_bind(containers, port):
    """A port suggestion in the form the existing entries use."""
    prefix = suggest_bind(containers)
    return f"{prefix}{port}" if prefix else port


def keep_bind_address(old_value, new_value):
    """Carry a bind address over to a value the operator typed bare.

    Typing "19000" to change a port is not a request to unbind it from
    localhost, but that is what replacing "127.0.0.1:13000" with 19000 does.
    An explicit address in the new value always wins.
    """
    if validator.parse_port(new_value) is None:
        return new_value
    if bind_prefix(new_value):
        return new_value
    prefix = bind_prefix(old_value)
    return f"{prefix}{new_value}" if prefix else new_value


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
          lambda c, e: with_bind(c, suggest_free_port(c))),
    Field("longpolling_port", "Longpolling port",
          "host port, mapped to 8072 inside the container",
          lambda c, e: with_bind(c, suggest_longpolling(
              c, validator.parse_port(e.get("port")) or 0))),
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

# Comments the shipped template carries on specific keys. An operator opening
# the file afterwards should not be able to tell a generated block from a
# typed one - and the PGPASSWORD note is the kind of thing that stops someone
# turning the flag off without reading why it is on.
BLOCK_COMMENTS = {
    "db_password_via_env":
        "  # secure default: password via -e PGPASSWORD, not argv",
}


# ==============================================================================
# The backup configuration
# ==============================================================================

def update_instances(path=None):
    """The containers of docker2update.yaml, or [] when it cannot be read.

    Read-only and best-effort: the backup form uses it to suggest, and a
    missing or broken update configuration must cost a suggestion, never the
    ability to edit the backup file.
    """
    if validator is None:
        return []
    try:
        data, fatal = validator.load_positioned(path or DEFAULT_UPDATE_CONFIG)
    except OSError:
        return []
    if fatal is not None or not isinstance(data, dict):
        return []
    containers = data.get("containers") or []
    return [c for c in containers if isinstance(c, dict)]


def instance_for_database(database, instances=None):
    """The update entry serving `database`, when exactly one does.

    Two entries naming the same database is a configuration error the
    validator already reports; suggesting from either of them here would put a
    guess in front of an operator who is mid-way through fixing it.
    """
    if not database:
        return None
    matches = [c for c in (instances if instances is not None
                           else update_instances())
               if c.get("database_name") == database]
    return matches[0] if len(matches) == 1 else None


def suggest_from_instance(field, entry, instances=None):
    """Fill a backup field from the update entry that serves this database.

    This is the point of editing the two files with one tool. The pairing a
    backup entry needs - which Postgres container holds the database, which
    Odoo container holds the filestore - is already written down in
    docker2update.yaml as db_host and container_name. Asking the operator to
    retype it is asking them to introduce a typo into a backup.
    """
    instance = instance_for_database(entry.get("name", ""), instances)
    if instance is None:
        return None
    return {"sql_container": instance.get("db_host"),
            "data_container": instance.get("container_name"),
            "db_user": instance.get("db_user")}.get(field)


def suggest_backup_unanimous(databases, field, fallback=None):
    """A value every configured database agrees on, else `fallback`."""
    values = {d.get(field) for d in databases if d.get(field) is not None}
    return values.pop() if len(values) == 1 else fallback


BACKUP_FORM = [
    Field("name", "Database name",
          "the PostgreSQL database to back up", None),
    Field("sql_container", "Database container",
          "the Postgres container holding it - pg_dump runs in here",
          lambda d, e: suggest_from_instance("sql_container", e)),
    Field("data_container", "Odoo container",
          "the Odoo container holding the filestore",
          lambda d, e: suggest_from_instance("data_container", e)),
    Field("db_user", "Database user",
          "the PostgreSQL role pg_dump connects as",
          lambda d, e: suggest_from_instance("db_user", e)
          or suggest_backup_unanimous(d, "db_user")),
    Field("retention_days", "Keep archives for (days)",
          "older archives of this database are removed after a successful run",
          lambda d, e: suggest_backup_unanimous(d, "retention_days", 14)),
    Field("only_sql_dump", "Database only, no filestore",
          "true skips the filestore - much faster, and not a full backup",
          lambda d, e: False),
    Field("stream", "Stream into one .tar.zst",
          "true for large filestores: no uncompressed staging copy is made",
          lambda d, e: suggest_backup_unanimous(d, "stream", False)),
]

# Which top-level list each configuration keeps its entries in, what makes an
# entry unique, and which form describes it. Everything below reads this
# instead of naming "containers" or "databases" directly.
KINDS = {
    UPDATE: {
        "path": DEFAULT_UPDATE_CONFIG,
        "collection": "containers",
        "form": UPDATE_FORM,
        "label": "instance",
        "unique": ("container_name", "database_name"),
        "fields": lambda: validator.CONTAINER_FIELDS,
    },
    BACKUP: {
        "path": DEFAULT_BACKUP_CONFIG,
        "collection": "databases",
        "form": BACKUP_FORM,
        "label": "database",
        "unique": ("name",),
        "fields": lambda: validator.DATABASE_FIELDS,
    },
}


def render_entry(entry, form):
    """A new entry as a list of lines, in the shipped shape."""
    lines = []
    for field in form:
        if field.name not in entry:
            continue
        lead = "  - " if not lines else "    "
        comment = BLOCK_COMMENTS.get(field.name, "")
        lines.append(f"{lead}{field.name}: {format_value(entry[field.name])}{comment}")
    return lines


def collection_end(lines, data, key):
    """0-based index just past the last entry of the list under `key`.

    Found through the positioned loader rather than by pattern: the last
    entry's own first-key line is known, and entry_bounds walks to the first
    following line at the list's indentation or less.
    """
    entries = data.get(key) or []
    if not entries:
        # An empty list: insert right after the key itself. A key that is not
        # in the file at all has no insertion point, and saying so beats
        # writing the entry into whatever happens to be at line 0.
        line = validator.line_of(data, key)
        if not line:
            raise KeyError(f"`{key}:` is not in this file")
        return line
    indent = 2  # the '- ' of a list entry under a top-level key
    _first, end = entry_bounds(lines, entries[-1].line, indent)
    return end


def append_entry(lines, data, entry, kind=UPDATE):
    """Insert a rendered entry at the end of that kind's collection."""
    spec = KINDS[kind]
    at = collection_end(lines, data, spec["collection"])
    return lines[:at] + render_entry(entry, spec["form"]) + lines[at:]


def patch_entry_field(lines, data, index, field, value, kind=UPDATE):
    """Rewrite one field of one entry, or insert it when absent."""
    entry = (data.get(KINDS[kind]["collection"]) or [])[index]
    line_number = validator.line_of(entry, field)
    result = list(lines)
    if line_number:
        result[line_number - 1] = patch_line(result[line_number - 1], value)
        return result

    # Absent: insert at the end of this entry's block, at its indentation.
    _first, end = entry_bounds(lines, entry.line, 2)
    indent = " " * 4
    result.insert(end, f"{indent}{field}: {format_value(value)}")
    return result


# ==============================================================================
# The write API
# ==============================================================================
#
# Everything above is a pure function over lines. These three are the whole
# cycle - read, change, validate, replace - in one call, and they need no
# terminal. That is what the console of stage 3 consumes, and what the
# interactive path below now runs on: one write path per file, exercised by
# both callers, so the one that is used less often cannot rot unnoticed.

WriteResult = collections.namedtuple("WriteResult",
                                     "ok findings backup error")
WriteResult.__new__.__defaults__ = (False, (), None, None)


def load_config(path):
    """(lines, data, error). Every failure is a sentence, never an exception."""
    if validator is None:
        return None, None, ("ownerp_validate.py is not installed beside this "
                            "script - run ups")
    try:
        data, fatal = validator.load_positioned(path)
    except OSError as exc:
        return None, None, f"{path} cannot be read: {exc}"
    if fatal is not None:
        where = f"line {fatal.line}: " if fatal.line else ""
        return None, None, f"{where}{fatal.message}"
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().split("\n")
    except OSError as exc:
        return None, None, f"{path} cannot be read: {exc}"
    return lines, data, None


def entries_of(data, kind=UPDATE):
    """The list this kind edits, mappings only."""
    entries = data.get(KINDS[kind]["collection"]) or []
    return [e for e in entries if isinstance(e, dict)]


def duplicate_of(data, entry, kind=UPDATE, skip=None):
    """The field of `entry` that collides with an existing one, or None.

    Checked before the write rather than left to the validator, because the
    validator's rejection arrives after the entry was built and reads like a
    fault in the tool. `skip` is the index being edited, which must not count
    as a duplicate of itself.
    """
    for field in KINDS[kind]["unique"]:
        value = entry.get(field)
        if value in (None, ""):
            continue
        for index, existing in enumerate(entries_of(data, kind)):
            if index != skip and existing.get(field) == value:
                return field
    return None


def is_flow_line(lines, line_number):
    """Whether the key on this 1-based line holds a complete {...} mapping."""
    if not line_number or line_number > len(lines):
        return False
    code, _comment = split_comment(lines[line_number - 1])
    match = KEY_RE.match(code)
    if not match:
        return False
    rest = code[match.end():].strip()
    return rest.startswith("{") and rest.endswith("}")


def set_fields(path, index, changes, kind=UPDATE, now=None):
    """Change several scalar fields of one entry in a SINGLE write.

    A form edits an entry, not a field. Calling set_field once per changed
    field would leave one timestamped backup per keystroke-session and, worse,
    a half-applied entry whenever the third of five writes is rejected. This
    validates the whole set once and replaces the file once: all of it, or
    none of it.

    The order of the two loops is the substance, not tidiness. A recorded line
    number belongs to the file as it was read; replacing a line keeps every
    other number valid, while inserting one shifts everything below it. So the
    fields that already have a line are patched first, and only then are the
    absent ones appended — each of which recomputes the entry's end against
    the lines as they now stand.
    """
    lines, data, error = load_config(path)
    if error:
        return WriteResult(error=error)

    entries = entries_of(data, kind)
    if not 0 <= index < len(entries):
        return WriteResult(error=f"there is no entry {index} in {path}")
    current = entries[index]

    prepared = []
    for field, value in changes.items():
        existing = current.get(field)
        if isinstance(existing, dict) and isinstance(value, dict) \
                and is_flow_line(lines, validator.line_of(current, field)):
            pass  # a one-line mapping has one line to replace
        elif isinstance(existing, (list, dict)):
            # A value spanning several lines has no single line to replace,
            # and guessing at one is how a configuration gets quietly
            # corrupted.
            return WriteResult(
                error=f"{field} is not a scalar - edit it with mcedit")

        if field in KINDS[kind]["unique"]:
            clash = duplicate_of(data, {field: value}, kind, skip=index)
            if clash:
                return WriteResult(
                    error=f"{field} {value!r} is already in use")

        if validator.parse_port(existing) is not None:
            # Changing a port must not silently unbind it from localhost.
            value = keep_bind_address(existing, value)

        prepared.append((field, value, validator.line_of(current, field)))

    new_lines = list(lines)
    for _field, value, line_number in prepared:
        if line_number:
            new_lines[line_number - 1] = patch_line(
                new_lines[line_number - 1], value)
    for field, value, line_number in prepared:
        if not line_number:
            new_lines = patch_entry_field(new_lines, data, index, field,
                                          value, kind)

    ok, findings, backup = safe_write(path, new_lines, now=now, kind=kind)
    return WriteResult(ok=ok, findings=tuple(findings), backup=backup)


def set_field(path, index, field, value, kind=UPDATE, now=None):
    """Change one scalar field of one entry. No terminal involved."""
    return set_fields(path, index, {field: value}, kind=kind, now=now)


def add_entry(path, entry, kind=UPDATE, now=None):
    """Append one entry. No terminal involved."""
    lines, data, error = load_config(path)
    if error:
        return WriteResult(error=error)

    clash = duplicate_of(data, entry, kind)
    if clash:
        return WriteResult(error=f"{clash} {entry.get(clash)!r} is already in use")

    try:
        new_lines = append_entry(lines, data, entry, kind)
    except KeyError as exc:
        return WriteResult(error=str(exc).strip("'"))

    ok, findings, backup = safe_write(path, new_lines, now=now, kind=kind)
    return WriteResult(ok=ok, findings=tuple(findings), backup=backup)


# The update-shaped names kept as they were. Ninety tests and the whole
# interactive path call these; they are the update kind of the generic four
# above and nothing more.
def render_container(entry):
    """The new instance as a list of lines, in the shipped shape."""
    return render_entry(entry, UPDATE_FORM)


def containers_end(lines, data):
    """0-based index just past the last container entry."""
    return collection_end(lines, data, "containers")


def append_container(lines, data, entry):
    """Insert a rendered entry at the end of the containers list."""
    return append_entry(lines, data, entry, UPDATE)


def patch_field(lines, data, index, field, value):
    """Rewrite one field of containers[index], or insert it when absent."""
    return patch_entry_field(lines, data, index, field, value, UPDATE)


MASK = "********"


SIZING_ROLES = ("live", "test", "demo")

# Pseudo fields of the update form: two flat answers that fold into the one
# `sizing` mapping of the file. Not in UPDATE_FORM - the schema has no such
# keys, and the field-by-field editor must not offer them.
SIZING_FORM = [
    Field("sizing_profile", "Role", "live, test or demo", None),
    Field("sizing_users", "Concurrent users",
          "empty = from hardware (live only)", None),
]


def flatten_sizing(entry):
    """A copy of `entry` with sizing_profile/sizing_users read from the block."""
    flat = dict(entry)
    block = entry.get("sizing")
    if isinstance(block, dict):
        for key in ("profile", "users"):
            if block.get(key) is not None:
                flat["sizing_" + key] = block[key]
    return flat


def fold_sizing(entry, changes):
    """`changes` with the two sizing pseudo keys replaced by a `sizing` dict.

    Keys already in the block (workers: 6 ...) stay. A users value of None
    drops the users key ("from hardware"). Without a sizing change the
    changes come back untouched, so an untouched form leaves the block alone.
    """
    if "sizing_profile" not in changes and "sizing_users" not in changes:
        return changes
    folded = {k: v for k, v in changes.items()
              if k not in ("sizing_profile", "sizing_users")}
    existing = entry.get("sizing")
    block = dict(existing) if isinstance(existing, dict) else {}
    if changes.get("sizing_profile") is not None:
        block["profile"] = changes["sizing_profile"]
    if "sizing_users" in changes:
        if changes["sizing_users"] is None:
            block.pop("users", None)
        else:
            block["users"] = changes["sizing_users"]
    if block:
        folded["sizing"] = block
    return folded


def coerce(field_name, text, kind=UPDATE):
    """Turn prompt text into the type the schema expects for that field.

    A schema entry whose type is a tuple - odoo_version is (str, int) - falls
    through to text on purpose: every shipped template writes it quoted, and
    picking one half of the tuple would silently change the file's style.
    """
    if field_name == "sizing_users":
        return int(text.strip()) if text.strip() else None
    if field_name == "sizing_profile":
        return text.strip().lower()
    rule = KINDS[kind]["fields"]().get(field_name, {})
    if rule.get("type") is bool:
        return text.strip().lower() in ("true", "yes", "y", "1", "ja", "j")
    if rule.get("type") is int:
        return int(text.strip())
    if rule.get("port"):
        stripped = text.strip()
        return int(stripped) if stripped.isdigit() else stripped
    return text.strip()


def summary_lines(entry, form=None):
    """The confirmation block. A password is masked, never printed."""
    lines = []
    for field in (form or UPDATE_FORM):
        if field.name not in entry:
            continue
        value = MASK if validator.redacted(field.name) else entry[field.name]
        lines.append(f"  {field.label + ':':<38} {value}")
    return lines


def preflight():
    """The reason the wizard must not run, or None."""
    if validator is None:
        return ("ownerp_validate.py is not installed beside this script. "
                "The wizard validates before it writes, so it will not run "
                "without it - install it with 'ups'.")
    if not sys.stdout.isatty() or not sys.stdin.isatty():
        return ("This wizard needs a terminal. Edit the configuration with "
                "'edup' (mcedit) instead, and check it with 'doval'.")
    return None


def ask(field, containers, entry, kind=UPDATE):
    """One prompt, with its suggestion in brackets. Enter takes the suggestion."""
    if validator.redacted(field.name):
        while True:
            value = getpass.getpass(f"  {field.label}: ")
            if value:
                return value
            print("    A password is required.")

    suggestion = field.suggest(containers, entry) if field.suggest else None
    hint = f" [{suggestion}]" if suggestion not in (None, "") else ""
    print(f"    {field.help}")
    while True:
        text = input(f"  {field.label}{hint}: ").strip()
        if not text and suggestion not in (None, ""):
            return suggestion
        if not text:
            print("    This field is required.")
            continue
        try:
            return coerce(field.name, text, kind)
        except ValueError:
            print("    Not a number - try again.")


def confirm(question, default=False):
    hint = "Y/n" if default else "y/N"
    answer = input(f"  {question} ({hint}): ").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes", "j", "ja")


def ask_unique(field, containers, entry, taken, kind=UPDATE):
    """Ask until the answer is not already used by another entry.

    Caught here rather than at validation: the wizard already holds every
    existing name, and saying so at the moment it is typed is worth more than
    a finding five prompts later.
    """
    while True:
        value = ask(field, containers, entry, kind)
        if value not in taken:
            return value
        print(f"    Already used: {', '.join(sorted(str(t) for t in taken))}")


def offer_build_folder(path):
    """The one filesystem write, and only after asking.

    A brand-new instance has no build folder yet, so the validator's warning
    is the normal state rather than a fault. Creating the empty directory is
    the step the operator would take next anyway. Nothing is copied into it -
    populating a build folder belongs to odoo_build_cache.py and
    sync_build_scripts(), and a second deployment path is the last thing this
    set of tools needs.
    """
    target = validator.expand(path)
    if os.path.isdir(target):
        return
    print(f"\n  The build folder does not exist yet: {target}")
    if not confirm("Create the empty directory now?", default=True):
        print("    Left alone. 'doval' will report it until it exists.")
        return
    try:
        os.makedirs(target, exist_ok=True)
        print(f"    Created: {target}")
    except OSError as error:
        print(f"    Could not create it: {error}")


def print_findings(findings):
    """Render findings with their severity in front of the line number.

    The severity is not decoration. A rejected write prints every finding the
    validator returned, and the path warnings that were there all along would
    otherwise read as co-defendants of the one error that actually blocked it.
    """
    for finding in findings:
        mark = "error  " if finding.severity == validator.ERROR else "warning"
        print(f"  {mark} {finding.line or '':>4}  {finding.path}: {finding.message}")


def add_container(path, lines, data, kind=UPDATE):
    """Walk the form, confirm, write. Returns an exit code.

    The write itself goes through add_entry(), the same call the console makes.
    It re-reads the file each attempt, which is what makes the retry loop
    correct: after a rejection the operator may well have been fixing the file
    in another window.
    """
    spec = KINDS[kind]
    entries = entries_of(data, kind)
    taken = {field: {e.get(field) for e in entries}
             for field in spec["unique"]}

    entry = {}
    print(f"\nNew {spec['label']} - Enter takes the value in brackets.\n")
    for field in spec["form"]:
        if field.name in taken:
            entry[field.name] = ask_unique(field, entries, entry,
                                           taken[field.name], kind)
        else:
            entry[field.name] = ask(field, entries, entry, kind)

    while True:
        print("\n" + "\n".join(summary_lines(entry, spec["form"])))
        if not confirm("\n  Write this entry?", default=True):
            print("Nothing written.")
            return 0

        result = add_entry(path, entry, kind)
        if result.error:
            print(f"\n  Not written: {result.error}")
            return 1
        if result.ok:
            print(f"\n  Written to {path}")
            print(f"  Backup:    {result.backup}")
            print_findings(result.findings)
            if kind == UPDATE:
                offer_build_folder(entry["dockerfile_path"])
            return 0

        print("\n  Not written - the result would be invalid:")
        print_findings(result.findings)
        print(f"  {path} is unchanged.")
        if not confirm("\n  Correct a field and try again?", default=True):
            return 1
        entry = correct_one_field(entry, entries, kind)


def correct_one_field(entry, containers, kind=UPDATE):
    """Re-ask one field, keeping everything else the operator typed."""
    fields = [f for f in KINDS[kind]["form"] if f.name in entry]
    for number, field in enumerate(fields, 1):
        value = MASK if validator.redacted(field.name) else entry[field.name]
        print(f"  {number:>2}) {field.label:<38} {value}")
    choice = input("  Field number: ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(fields):
        field = fields[int(choice) - 1]
        entry[field.name] = ask(field, containers, entry, kind)
    return entry


def edit_field(path, lines, data, kind=UPDATE):
    """Change one scalar field of one existing entry. Returns an exit code."""
    spec = KINDS[kind]
    entries = entries_of(data, kind)
    if not entries:
        print("No entries to edit.")
        return 0

    identity = spec["unique"][0]
    for number, existing in enumerate(entries, 1):
        print(f"  {number:>2}) {existing.get(identity, '?')}")
    choice = input("  Entry number: ").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(entries):
        print("Cancelled.")
        return 0
    index = int(choice) - 1
    current = entries[index]

    # Scalars only. A list or a mapping has no single line to replace, and
    # guessing at one is how a configuration gets quietly corrupted.
    editable = [f for f in spec["form"]
                if not isinstance(current.get(f.name), (list, dict))]
    for number, field in enumerate(editable, 1):
        value = MASK if validator.redacted(field.name) else current.get(field.name, "-")
        print(f"  {number:>2}) {field.label:<38} {value}")
    choice = input("  Field number: ").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(editable):
        print("Cancelled.")
        return 0
    field = editable[int(choice) - 1]

    value = ask(field, entries, dict(current), kind)
    if not confirm(f"\n  Set {field.label} to "
                   f"{MASK if validator.redacted(field.name) else value}?",
                   default=True):
        print("Nothing written.")
        return 0

    # set_field keeps the bind address and rejects a duplicate identity; both
    # used to live here, and the console would have had to repeat them.
    result = set_field(path, index, field.name, value, kind)
    if result.error:
        print(f"\n  Not written: {result.error}")
        return 1
    if result.ok:
        print(f"\n  Written to {path}\n  Backup:    {result.backup}")
        return 0
    print("\n  Not written - the result would be invalid:")
    print_findings(result.findings)
    print(f"  {path} is unchanged.")
    return 1


def _default_review(name, path, out=print):
    """The per-value review of ownerp_sizing, or the command to run later."""
    if ownerp_sizing is None:
        out(f"  Review later with: dosize --review {name}")
        return 0
    return ownerp_sizing.main(["--review", name, "--config", path])


def ask_sizing(path, index, ask=input, out=print, review=None):
    """The wizup flow for the sizing block of one entry. Returns an exit code.

    Writes through set_fields like every other change. `ask` and `out` are
    injectable so a test needs no terminal; `review` defaults to the per-value
    review of ownerp_sizing, which refuses without a terminal by itself.
    """
    lines, data, error = load_config(path)
    if error:
        out(f"  {error}")
        return 2
    entries = entries_of(data, UPDATE)
    if not 0 <= index < len(entries):
        out(f"  There is no entry {index} in {path}")
        return 2
    current = entries[index]
    name = current.get("container_name", "?")
    block = current.get("sizing") if isinstance(current.get("sizing"), dict) else {}

    default = block.get("profile")
    hint = f" [{default}]" if default else ""
    while True:
        role = ask(f"  Role? (live/test/demo){hint}: ").strip().lower() or default
        if role in SIZING_ROLES:
            break
        out("    Enter live, test or demo.")

    changes = {"sizing_profile": role}
    if role == "live":
        while True:
            text = ask("  Concurrent users (empty = from hardware)? ").strip()
            if not text:
                changes["sizing_users"] = None
                break
            if text.isdigit() and int(text) >= 1:
                changes["sizing_users"] = int(text)
                break
            out("    Enter a whole number of at least 1, or leave it empty.")

    result = set_fields(path, index, fold_sizing(current, changes), UPDATE)
    if result.error:
        out(f"\n  Not written: {result.error}")
        return 1
    if not result.ok:
        out("\n  Not written - the result would be invalid:")
        for finding in result.findings:
            out(f"  {finding.severity}  {finding.path}: {finding.message}")
        out(f"  {path} is unchanged.")
        return 1

    users = changes.get("sizing_users")
    detail = f", {users} concurrent users" if users else ""
    out(f"\n  Sizing role set to {role}{detail} for {name}.")
    out(f"  Written to {path}\n  Backup:    {result.backup}")
    out("  The values take effect with the next doup. Preview: dosize")

    answer = ask("  Review the single values now? (Y/n): ").strip().lower()
    if answer in ("", "y", "yes", "j", "ja"):
        if review is None:
            _default_review(name, path, out)
        else:
            review(name, path)
    return 0


def edit_sizing(path, data):
    """Pick an entry, then run the sizing questions on it."""
    entries = entries_of(data, UPDATE)
    if not entries:
        print("No entries to edit.")
        return 0
    for number, existing in enumerate(entries, 1):
        print(f"  {number:>2}) {existing.get('container_name', '?')}")
    choice = input("  Entry number: ").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(entries):
        print("Cancelled.")
        return 0
    return ask_sizing(path, int(choice) - 1)


def parse_arguments(argv):
    parser = argparse.ArgumentParser(
        prog="ownerp_wizard.py",
        description="Guided editing of docker2update.yaml.")
    parser.add_argument("--update", nargs="?", const=DEFAULT_UPDATE_CONFIG,
                        metavar="PATH",
                        help=f"edit the update configuration "
                             f"(default: {DEFAULT_UPDATE_CONFIG})")
    parser.add_argument("--backup", nargs="?", const=DEFAULT_BACKUP_CONFIG,
                        metavar="PATH",
                        help=f"edit the backup configuration "
                             f"(default: {DEFAULT_BACKUP_CONFIG})")
    # Not argparse's version action: it raises SystemExit and would break
    # main()'s contract of returning an int, the same rule the validator follows.
    parser.add_argument("--version", action="store_true",
                        help="print the version and exit")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_arguments(argv)
    if args.version:
        print(f"ownerp_wizard.py {SCRIPT_VERSION} ({SCRIPT_DATE})")
        return 0

    reason = preflight()
    if reason:
        print(reason)
        return 2

    print(f"ownerp_wizard.py {SCRIPT_VERSION} ({SCRIPT_DATE})")

    # An explicit flag picks the file; without one, ask. Defaulting silently
    # to the update configuration would make the backup side invisible to
    # anyone who does not read --help, and it is the side that had no editor
    # at all until now.
    if args.backup:
        kind, path = BACKUP, args.backup
    elif args.update:
        kind, path = UPDATE, args.update
    else:
        kind, path = choose_config()
        if kind is None:
            return 0

    print(path)
    lines, data, error = load_config(path)
    if error:
        print(f"\n  {error}")
        print("  Fix it first - 'doval' shows every finding with its line.")
        return 2

    # Say once where the better route is. This prompt walks one field at a
    # time because it has to work on a terminal that cannot run Textual; when
    # Textual is available the console edits the same file as a form, and an
    # operator who does not know that keeps coming back here.
    print("\n  konsole edits this file as a form - this prompt is the "
          "fallback.")

    label = KINDS[kind]["label"]
    sizing_line = "\n  3) Set role/sizing" if kind == UPDATE else ""
    print(f"\n  1) Add a{'n' if label[0] in 'aeiou' else ''} {label}"
          f"\n  2) Change a field{sizing_line}\n  q) Quit")
    choice = input("\n  Choice [1]: ").strip() or "1"
    if choice == "1":
        return add_container(path, lines, data, kind)
    if choice == "2":
        return edit_field(path, lines, data, kind)
    if choice == "3" and kind == UPDATE:
        return edit_sizing(path, data)
    return 0


def choose_config():
    """(kind, path), or (None, None) when the operator quits."""
    print("\n  1) Odoo instances    (docker2update.yaml)"
          "\n  2) Database backups  (container2backup.yaml)"
          "\n  q) Quit")
    choice = input("\n  Choice [1]: ").strip() or "1"
    if choice == "2":
        return BACKUP, DEFAULT_BACKUP_CONFIG
    if choice == "1":
        return UPDATE, DEFAULT_UPDATE_CONFIG
    return None, None


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        # EOFError as well as Ctrl-C: Ctrl-D at a prompt is an operator
        # closing the input, not a fault, and it must read like one.
        print("\nCancelled - nothing written.")
        sys.exit(130)
