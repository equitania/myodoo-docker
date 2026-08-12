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
