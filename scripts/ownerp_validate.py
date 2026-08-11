#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Title:            ownerp_validate.py
# Description:      Read-only validation of docker2update.yaml and
#                   container2backup.yaml against declared schemas
# Version:          1.0.0
# Date:             11.08.2026
# Author:           Equitania Software GmbH
# ==============================================================================
#
# This script never writes. It opens configuration files for reading, reports
# what is wrong with a file and a line number, and sets an exit code:
#
#   0  no errors (warnings may be present)
#   1  at least one error
#   2  a file is missing, unreadable, unparseable, or PyYAML is absent
#
# Warnings deliberately do not affect the exit code. A path that does not exist
# yet is a normal state during onboarding, which is exactly when this validator
# is run against a configuration that is still being written.
#
##############################################################################
import os
import re
import sys
import difflib
import argparse
import collections

# PyYAML is imported defensively: a missing parser must produce the apt hint
# and exit 2, not a traceback in front of an operator.
try:
    import yaml
except ImportError:  # pragma: no cover - depends on the machine
    yaml = None

SCRIPT_VERSION = "1.0.0"
SCRIPT_DATE = "11.08.2026"

ERROR = "error"
WARNING = "warning"

DEFAULT_UPDATE_CONFIG = os.path.join(os.path.expanduser("~"), "docker2update.yaml")
DEFAULT_BACKUP_CONFIG = os.path.join(os.path.expanduser("~"), "container2backup.yaml")

# severity: ERROR or WARNING
# file:     the configuration file the finding is about
# line:     1-based line inside that file, 0 when unknown
# path:     the dotted position in the schema, e.g. "containers[0].port"
# message:  what is wrong, without the path in front of it
Finding = collections.namedtuple("Finding", "severity file line path message")


class PositionedDict(dict):
    """A dict that remembers where in the file it came from.

    Plain dicts lose every position the parser knew, and a finding without a
    line number makes the operator search a 400-line file by hand. Nothing is
    smuggled into the data itself - the positions live on the object, so every
    consumer downstream treats this as an ordinary dict.

    'line' is the line of the mapping's FIRST KEY, not of the key that
    introduced it - that is what PyYAML's start_mark points at for a block
    mapping. For

        defaults:          <- line 1
          db_user: ownerp  <- line 2

    data["defaults"].line is 2. This is deliberate and the tests pin it: the
    mapping's own key is reported through the parent's key_lines, and the
    first-key line is the right neighbourhood for a finding about something
    the mapping is missing.
    """

    line = 0          # 1-based line of the mapping's first key
    key_lines = None  # {key: 1-based line of that key}


def line_of(mapping, key=None):
    """Return the 1-based line of `key` inside `mapping`, or of the mapping."""
    if key is None:
        return getattr(mapping, "line", 0)
    lines = getattr(mapping, "key_lines", None) or {}
    return lines.get(key, 0)


_LOADER = None


def positioned_loader():
    """Build (once) the SafeLoader subclass that records positions.

    Built lazily rather than at import time because PyYAML may be absent -
    subclassing yaml.SafeLoader at module level would turn that into an
    AttributeError before main() can print the apt hint.
    """
    global _LOADER
    if _LOADER is not None:
        return _LOADER

    class PositionedLoader(yaml.SafeLoader):
        def construct_positioned_mapping(self, node):
            self.flatten_mapping(node)
            data = PositionedDict()
            data.line = node.start_mark.line + 1
            data.key_lines = {}
            # deep=True: the default two-pass construction hands out an empty
            # dict first and fills it later, which would defeat the subclass.
            for key_node, value_node in node.value:
                key = self.construct_object(key_node, deep=True)
                try:
                    data.key_lines[key] = key_node.start_mark.line + 1
                except TypeError:      # an unhashable key - YAML allows it
                    continue
                data[key] = self.construct_object(value_node, deep=True)
            return data

    PositionedLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        PositionedLoader.construct_positioned_mapping)
    _LOADER = PositionedLoader
    return _LOADER


def load_positioned(path):
    """Load a YAML file, keeping positions.

    Returns (data, fatal). On success fatal is None; on failure data is None
    and fatal is the single Finding that explains why nothing could be read.
    """
    if not os.path.isfile(path):
        return None, Finding(ERROR, path, 0, "", "configuration file not found")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.load(handle, Loader=positioned_loader())
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        line = mark.line + 1 if mark is not None else 0
        problem = getattr(error, "problem", None) or str(error)
        return None, Finding(ERROR, path, line, "",
                             f"YAML syntax error: {problem}")
    except OSError as error:
        return None, Finding(ERROR, path, 0, "", f"cannot read file: {error}")

    if data is None:
        return None, Finding(ERROR, path, 0, "", "file is empty")
    if not isinstance(data, dict):
        return None, Finding(ERROR, path, 0, "",
                             "top level must be a mapping of settings")
    return data, None


# Ports are configured as strings with an optional bind address - the shipped
# templates use "127.0.0.1:11000". A plain integer rule would flag every real
# customer configuration, so the form is parsed instead of typed.
PORT_RE = re.compile(
    r"^(?:\[(?P<v6>[0-9A-Fa-f:]+)\]:|(?P<v4>[0-9.]+):)?(?P<port>\d{1,5})$")


def parse_port(value):
    """Return the port number of an accepted form, or None."""
    if isinstance(value, bool):
        # True == 1 in Python, and a port of 1 is not what anybody wrote.
        return None
    match = PORT_RE.match(str(value).strip())
    if not match:
        return None
    port = int(match.group("port"))
    return port if 1 <= port <= 65535 else None


def is_empty(value):
    """Empty for the purposes of a required field.

    False and 0 are values, not omissions - 'active: false' and
    'delay_time: 0' are both legitimate settings.
    """
    if value is None:
        return True
    return isinstance(value, (str, list, dict)) and not value


def redacted(key):
    """True for keys whose value must never reach a finding."""
    lowered = str(key).lower()
    return lowered.endswith("password") or lowered == "admin_passwd"


def expand(path):
    """Expand ~ and $VARS the way the scripts themselves do."""
    return os.path.expandvars(os.path.expanduser(str(path)))


def _shown(key, value):
    """The value as it may appear in a finding."""
    if redacted(key):
        return "<redacted>"
    text = str(value)
    return text if len(text) <= 60 else text[:57] + "..."


def _type_name(expected):
    names = {str: "a string", int: "a whole number", bool: "true or false",
             dict: "a mapping", list: "a list", float: "a number"}
    if isinstance(expected, tuple):
        return " or ".join(names.get(item, item.__name__) for item in expected)
    return names.get(expected, expected.__name__)


def _join(prefix, key):
    """Dotted schema path, without a leading dot at the top level."""
    return f"{prefix}.{key}" if prefix else str(key)


def _add(findings, severity, file_path, line, path, message, downgrade):
    """Append a finding, downgrading it when the block is inactive.

    A parked 'active: false' block stops no run. Keeping the exit code red for
    it would teach operators to ignore the exit code, so its findings are
    reported in full but never block.
    """
    if downgrade and severity == ERROR:
        severity = WARNING
        message = f"(inactive) {message}"
    findings.append(Finding(severity, file_path, line, path, message))


def validate_mapping(data, fields, path_prefix, file_path, findings,
                     downgrade=False):
    """Walk one mapping against a field schema, appending findings."""
    if not isinstance(data, dict):
        _add(findings, ERROR, file_path, line_of(data), path_prefix,
             f"must be {_type_name(dict)}", downgrade)
        return

    for key, rule in fields.items():
        line = line_of(data, key)
        path = _join(path_prefix, key)
        present = key in data
        value = data.get(key)

        if not present or is_empty(value):
            if rule.get("required"):
                what = "is missing" if not present else "is empty"
                _add(findings, ERROR, file_path, line or line_of(data), path,
                     what, downgrade)
            continue

        if rule.get("free"):
            continue

        expected = rule.get("type")
        if expected is not None:
            wrong = not isinstance(value, expected)
            # bool is a subclass of int: 'delay_time: true' must not pass,
            # whether the rule names int directly or as part of a tuple
            # ("type": (int, float), used by odoo_version-style rules).
            expected_types = expected if isinstance(expected, tuple) else (expected,)
            if not wrong and int in expected_types and isinstance(value, bool):
                wrong = True
            if wrong:
                _add(findings, ERROR, file_path, line, path,
                     f"must be {_type_name(expected)}, not "
                     f'"{_shown(key, value)}"', downgrade)
                continue

        if "enum" in rule and value not in rule["enum"]:
            allowed = ", ".join(str(item) for item in rule["enum"])
            _add(findings, ERROR, file_path, line, path,
                 f'"{_shown(key, value)}" is not one of {allowed}', downgrade)
            continue

        if rule.get("port"):
            if parse_port(value) is None:
                _add(findings, ERROR, file_path, line, path,
                     f'"{_shown(key, value)}" is not a valid port - use 11000, '
                     '"11000", "127.0.0.1:11000" or "[::1]:11000", '
                     'in the range 1-65535', downgrade)
            continue

        if "min" in rule or "max" in rule:
            # A schema may declare min/max without a type rule (or with a
            # type that still admits non-numeric values); comparing a string
            # against a number raises TypeError, and this tool exists to
            # survive malformed customer input, not to crash on it.
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                _add(findings, ERROR, file_path, line, path,
                     f'must be a number, not "{_shown(key, value)}"', downgrade)
                continue
            if "min" in rule and value < rule["min"]:
                _add(findings, ERROR, file_path, line, path,
                     f"must be at least {rule['min']}", downgrade)
                continue
            if "max" in rule and value > rule["max"]:
                _add(findings, ERROR, file_path, line, path,
                     f"must be at most {rule['max']}", downgrade)
                continue

        if "fields" in rule:
            validate_mapping(value, rule["fields"], path, file_path, findings,
                             downgrade)

        # A list rule may carry min_items without an item schema - the two are
        # independent, so this check must not live inside the item branch.
        if "min_items" in rule and len(value) < rule["min_items"]:
            _add(findings, ERROR, file_path, line, path,
                 f"must hold at least {rule['min_items']} entries", downgrade)

        if "item" in rule:
            for index, entry in enumerate(value):
                validate_mapping(entry, rule["item"]["fields"],
                                 f"{path}[{index}]", file_path, findings,
                                 downgrade)

        if "path" in rule:
            target = expand(value)
            # Route through _shown, same as every other branch: a path rule
            # paired with a password-named key must not print the value.
            shown = _shown(key, target)
            if not os.path.exists(target):
                _add(findings, WARNING, file_path, line, path,
                     f"{shown} does not exist", downgrade)
            elif rule["path"] == "dir" and not os.path.isdir(target):
                _add(findings, WARNING, file_path, line, path,
                     f"{shown} exists but is not a directory", downgrade)

    known = list(fields)
    for key in data:
        if key in fields:
            continue
        close = difflib.get_close_matches(str(key), known, n=1, cutoff=0.6)
        hint = f' - did you mean "{close[0]}"?' if close else ""
        _add(findings, WARNING, file_path, line_of(data, key),
             _join(path_prefix, key), f"unknown key{hint}", downgrade)


PROXY_FIELDS = {
    "http_proxy":  {"type": str},
    "https_proxy": {"type": str},
    "no_proxy":    {"type": str},
}

# The item schemas are module constants rather than nested "item" rules,
# because containers and databases are walked by hand further down: each entry
# needs its own downgrade decision, which the generic walker cannot make. A
# nested "item" rule here would walk them a second time and report every fault
# twice.
CONTAINER_FIELDS = {
    "active":              {"type": bool},
    "type":                {"required": True, "enum": ["M", "F", "N"]},
    "delay_time":          {"type": int, "min": 0},
    "container_name":      {"type": str, "required": True},
    "database_name":       {"type": str, "required": True},
    "port":                {"required": True, "port": True},
    "longpolling_port":    {"required": True, "port": True},
    "dockerfile_path":     {"type": str, "required": True, "path": "dir"},
    "docker_image_name":   {"type": str, "required": True},
    "db_user":             {"type": str, "required": True},
    "db_password":         {"type": str, "required": True},
    "db_host":             {"type": str, "required": True},
    "volume":              {"type": str},
    "odoo_version":        {"type": (str, int)},
    "translate":           {"enum": ["Y", "N"]},
    "db_password_via_env": {"type": bool},
    "log_retention_days":  {"type": int, "min": 0},
    "proxy":               {"type": dict, "fields": PROXY_FIELDS},
    "pre_build_files":     {"type": list, "item": {"fields": {
        "source": {"type": str, "required": True, "path": "any"},
        "target": {"type": str},
    }}},
}

UPDATE_SCHEMA = {
    "defaults": {
        "type": dict,
        "fields": {
            "proxy":                  {"type": dict, "fields": PROXY_FIELDS},
            "dockerfiles_source":     {"type": str, "path": "dir"},
            "log_retention_days":     {"type": int, "min": 0},
            "history_retention_days": {"type": int, "min": 0},
        },
    },
    "containers": {"type": list, "required": True, "min_items": 1},
}

SERVICE_FIELDS = {
    "enabled":        {"type": bool},
    "source_path":    {"type": str, "required": True, "path": "any"},
    "backup_path":    {"type": str, "required": True},
    "retention_days": {"type": int, "min": 0},
}

DATABASE_FIELDS = {
    "name":             {"type": str, "required": True},
    "db_user":          {"type": str},
    "sql_container":    {"type": str, "required": True},
    "data_container":   {"type": str, "required": True},
    "retention_days":   {"type": int, "min": 0},
    "only_sql_dump":    {"type": bool},
    "stream":           {"type": bool},
    "additional_paths": {"free": True},
    "fast_report": {"type": dict, "fields": {
        "enabled": {"type": bool},
        "path":    {"type": str, "path": "dir"},
    }},
}

BACKUP_SCHEMA = {
    "defaults": {
        "type": dict,
        "fields": {
            "retention_days":   {"type": int, "min": 0},
            "db_user":          {"type": str},
            "backup_path":      {"type": str, "path": "dir"},
            "temp_path":        {"type": str, "path": "dir"},
            "stream":           {"type": bool},
            "additional_paths": {"free": True},
            "compression": {"type": dict, "fields": {
                "format": {"enum": ["7z", "zip", "gzip", "zstd"]},
                "level":  {"type": int, "min": 0, "max": 9},
            }},
        },
    },
    # services is a mapping of operator-chosen names, so its keys cannot be
    # enumerated - each value is validated against SERVICE_FIELDS below.
    "services": {"type": dict},
    "databases": {"type": list},
    "rsync": {
        "type": dict,
        "fields": {
            "enabled":  {"type": bool},
            "commands": {"type": list},
        },
    },
}


def _duplicates(findings, entries, field, file_path, label):
    """Report a repeated value of `field` across `entries`.

    entries is a list of (mapping, display_name). The first occurrence is the
    reference; every later one names it and its line.
    """
    seen = {}
    for mapping, name in entries:
        value = mapping.get(field)
        if is_empty(value):
            continue
        if value in seen:
            first_map, first_name = seen[value]
            findings.append(Finding(
                ERROR, file_path, line_of(mapping, field),
                f"{label}.{field}",
                f'"{value}" is already used by {first_name} '
                f"(line {line_of(first_map, field)})"))
        else:
            seen[value] = (mapping, name)


def _check_port_collisions(findings, active, file_path):
    """port and longpolling_port are both host ports: one namespace."""
    seen = {}
    for mapping, name in active:
        for field in ("port", "longpolling_port"):
            number = parse_port(mapping.get(field))
            if number is None:
                continue
            if number in seen:
                other_map, other_name, other_field = seen[number]
                findings.append(Finding(
                    ERROR, file_path, line_of(mapping, field),
                    f"containers.{field}",
                    f"{number} collides with {other_name} "
                    f"({other_field}, line {line_of(other_map, other_field)})"))
            else:
                seen[number] = (mapping, name, field)


def validate_update(path):
    """Validate a docker2update.yaml. Returns (findings, fatal)."""
    data, fatal = load_positioned(path)
    if fatal is not None:
        return [], fatal

    findings = []
    validate_mapping(data, UPDATE_SCHEMA, "", path, findings)

    containers = data.get("containers")
    if isinstance(containers, list):
        for index, container in enumerate(containers):
            inactive = (isinstance(container, dict)
                        and not container.get("active", True))
            validate_mapping(container, CONTAINER_FIELDS,
                             f"containers[{index}]", path, findings,
                             downgrade=inactive)

        # Collisions are only real between entries that can both run.
        active = [(c, c.get("container_name") or f"containers[{i}]")
                  for i, c in enumerate(containers)
                  if isinstance(c, dict) and c.get("active", True)]
        _duplicates(findings, active, "container_name", path, "containers")
        _duplicates(findings, active, "database_name", path, "containers")
        _check_port_collisions(findings, active, path)

    return _sorted(findings), None


def validate_backup(path):
    """Validate a container2backup.yaml. Returns (findings, fatal)."""
    data, fatal = load_positioned(path)
    if fatal is not None:
        return [], fatal

    findings = []
    validate_mapping(data, BACKUP_SCHEMA, "", path, findings)

    services = data.get("services")
    if isinstance(services, dict):
        for name, service in services.items():
            disabled = (isinstance(service, dict)
                        and not service.get("enabled", True))
            validate_mapping(service, SERVICE_FIELDS, f"services.{name}",
                             path, findings, downgrade=disabled)

    databases = data.get("databases")
    if isinstance(databases, list):
        for index, database in enumerate(databases):
            validate_mapping(database, DATABASE_FIELDS,
                             f"databases[{index}]", path, findings)
        entries = [(d, d.get("name") or f"databases[{i}]")
                   for i, d in enumerate(databases) if isinstance(d, dict)]
        _duplicates(findings, entries, "name", path, "databases")

    return _sorted(findings), None


def _sorted(findings):
    """Findings in file order, errors before warnings on the same line."""
    return sorted(findings, key=lambda f: (f.line, f.severity != ERROR))
