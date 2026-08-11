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
