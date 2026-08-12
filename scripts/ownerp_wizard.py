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


def render_container(entry):
    """The new entry as a list of lines, in the shipped shape."""
    lines = []
    for field in UPDATE_FORM:
        if field.name not in entry:
            continue
        lead = "  - " if not lines else "    "
        comment = BLOCK_COMMENTS.get(field.name, "")
        lines.append(f"{lead}{field.name}: {format_value(entry[field.name])}{comment}")
    return lines


def containers_end(lines, data):
    """0-based index just past the last container entry.

    Found through the positioned loader rather than by pattern: the last
    entry's own first-key line is known, and entry_bounds walks to the first
    following line at the list's indentation or less.
    """
    containers = data.get("containers") or []
    if not containers:
        # An empty list: insert right after the 'containers:' key itself.
        return validator.line_of(data, "containers")
    last = containers[-1]
    indent = 2  # the '- ' of a list entry under a top-level key
    _first, end = entry_bounds(lines, last.line, indent)
    return end


def append_container(lines, data, entry):
    """Insert a rendered entry at the end of the containers list."""
    at = containers_end(lines, data)
    return lines[:at] + render_container(entry) + lines[at:]


def patch_field(lines, data, index, field, value):
    """Rewrite one field of containers[index], or insert it when absent."""
    container = (data.get("containers") or [])[index]
    line_number = validator.line_of(container, field)
    result = list(lines)
    if line_number:
        result[line_number - 1] = patch_line(result[line_number - 1], value)
        return result

    # Absent: insert at the end of this entry's block, at its indentation.
    _first, end = entry_bounds(lines, container.line, 2)
    indent = " " * 4
    result.insert(end, f"{indent}{field}: {format_value(value)}")
    return result


MASK = "********"


def coerce(field_name, text):
    """Turn prompt text into the type the schema expects for that field.

    A schema entry whose type is a tuple - odoo_version is (str, int) - falls
    through to text on purpose: every shipped template writes it quoted, and
    picking one half of the tuple would silently change the file's style.
    """
    rule = validator.CONTAINER_FIELDS.get(field_name, {})
    if rule.get("type") is bool:
        return text.strip().lower() in ("true", "yes", "y", "1", "ja", "j")
    if rule.get("type") is int:
        return int(text.strip())
    if rule.get("port"):
        stripped = text.strip()
        return int(stripped) if stripped.isdigit() else stripped
    return text.strip()


def summary_lines(entry):
    """The confirmation block. A password is masked, never printed."""
    lines = []
    for field in UPDATE_FORM:
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


def ask(field, containers, entry):
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
            return coerce(field.name, text)
        except ValueError:
            print("    Not a number - try again.")


def confirm(question, default=False):
    hint = "Y/n" if default else "y/N"
    answer = input(f"  {question} ({hint}): ").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes", "j", "ja")


def ask_unique(field, containers, entry, taken):
    """Ask until the answer is not already used by another entry.

    Caught here rather than at validation: the wizard already holds every
    existing name, and saying so at the moment it is typed is worth more than
    a finding five prompts later.
    """
    while True:
        value = ask(field, containers, entry)
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


def add_container(path, lines, data):
    """Walk the form, confirm, write. Returns an exit code."""
    containers = data.get("containers") or []
    names = {c.get("container_name") for c in containers}
    databases = {c.get("database_name") for c in containers}

    entry = {}
    print("\nNew instance - Enter takes the value in brackets.\n")
    for field in UPDATE_FORM:
        if field.name == "container_name":
            entry[field.name] = ask_unique(field, containers, entry, names)
        elif field.name == "database_name":
            entry[field.name] = ask_unique(field, containers, entry, databases)
        else:
            entry[field.name] = ask(field, containers, entry)

    while True:
        print("\n" + "\n".join(summary_lines(entry)))
        if not confirm("\n  Write this entry?", default=True):
            print("Nothing written.")
            return 0

        ok, findings, backup = safe_write(path, append_container(lines, data, entry))
        if ok:
            print(f"\n  Written to {path}")
            print(f"  Backup:    {backup}")
            print_findings(findings)
            offer_build_folder(entry["dockerfile_path"])
            return 0

        print("\n  Not written - the result would be invalid:")
        print_findings(findings)
        print(f"  {path} is unchanged.")
        if not confirm("\n  Correct a field and try again?", default=True):
            return 1
        entry = correct_one_field(entry, containers)


def correct_one_field(entry, containers):
    """Re-ask one field, keeping everything else the operator typed."""
    fields = [f for f in UPDATE_FORM if f.name in entry]
    for number, field in enumerate(fields, 1):
        value = MASK if validator.redacted(field.name) else entry[field.name]
        print(f"  {number:>2}) {field.label:<38} {value}")
    choice = input("  Field number: ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(fields):
        field = fields[int(choice) - 1]
        entry[field.name] = ask(field, containers, entry)
    return entry


def edit_field(path, lines, data):
    """Change one scalar field of one existing entry. Returns an exit code."""
    containers = data.get("containers") or []
    if not containers:
        print("No entries to edit.")
        return 0

    for number, container in enumerate(containers, 1):
        print(f"  {number:>2}) {container.get('container_name', '?')}")
    choice = input("  Entry number: ").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(containers):
        print("Cancelled.")
        return 0
    index = int(choice) - 1
    container = containers[index]

    # Scalars only. A list or a mapping has no single line to replace, and
    # guessing at one is how a configuration gets quietly corrupted.
    editable = [f for f in UPDATE_FORM
                if not isinstance(container.get(f.name), (list, dict))]
    for number, field in enumerate(editable, 1):
        value = MASK if validator.redacted(field.name) else container.get(field.name, "-")
        print(f"  {number:>2}) {field.label:<38} {value}")
    choice = input("  Field number: ").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(editable):
        print("Cancelled.")
        return 0
    field = editable[int(choice) - 1]

    value = ask(field, containers, dict(container))
    # Changing a port must not silently unbind it from localhost.
    value = keep_bind_address(container.get(field.name), value)
    if not confirm(f"\n  Set {field.label} to "
                   f"{MASK if validator.redacted(field.name) else value}?",
                   default=True):
        print("Nothing written.")
        return 0

    ok, findings, backup = safe_write(
        path, patch_field(lines, data, index, field.name, value))
    if ok:
        print(f"\n  Written to {path}\n  Backup:    {backup}")
        return 0
    print("\n  Not written - the result would be invalid:")
    print_findings(findings)
    print(f"  {path} is unchanged.")
    return 1


def parse_arguments(argv):
    parser = argparse.ArgumentParser(
        prog="ownerp_wizard.py",
        description="Guided editing of docker2update.yaml.")
    parser.add_argument("--update", nargs="?", const=DEFAULT_UPDATE_CONFIG,
                        metavar="PATH",
                        help=f"the configuration to edit "
                             f"(default: {DEFAULT_UPDATE_CONFIG})")
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

    path = args.update or DEFAULT_UPDATE_CONFIG
    print(f"ownerp_wizard.py {SCRIPT_VERSION} ({SCRIPT_DATE})\n{path}")

    data, fatal = validator.load_positioned(path)
    if fatal is not None:
        print(f"\n  {fatal.line or ''}  {fatal.message}")
        print("  Fix it first - 'doval' shows every finding with its line.")
        return 2
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().split("\n")

    print("\n  1) Add an instance\n  2) Change a field\n  q) Quit")
    choice = input("\n  Choice [1]: ").strip() or "1"
    if choice == "1":
        return add_container(path, lines, data)
    if choice == "2":
        return edit_field(path, lines, data)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        # EOFError as well as Ctrl-C: Ctrl-D at a prompt is an operator
        # closing the input, not a fault, and it must read like one.
        print("\nCancelled - nothing written.")
        sys.exit(130)
