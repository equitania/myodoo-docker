# Configuration Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A read-only `ownerp_validate.py` that checks `docker2update.yaml` and `container2backup.yaml` against declared schemas and reports every finding with a file and a line number.

**Architecture:** One standalone script, called as a subprocess by `update_docker_odoo.py --validate` and `container2backup.py --validate`. A `SafeLoader` subclass keeps YAML positions so findings can name a line. Schemas are declared as data; the checks are pure functions from loaded data to a list of `Finding`. The rendering layer holds no logic.

**Tech Stack:** Python 3, standard library plus PyYAML. Tests are stdlib `unittest`. Target is system Python on Debian/Ubuntu servers under PEP 668 — no `pip install`, no third-party dependency beyond `python3-yaml`.

**Spec:** `docs/superpowers/specs/2026-08-11-config-validation-design.md`

## Global Constraints

- **Read-only, without exception.** Nothing in this plan opens a configuration file for writing. The validator never writes; the runner's `--validate` path stops writing.
- **Standard library plus PyYAML only.** No new dependency. No `requirements.txt`, no `pyproject.toml` entry — these are server scripts copied into `$HOME`.
- **UTF-8 for every file operation.** `open(..., encoding="utf-8")` explicitly.
- **All code, comments and documentation in English.** Commit messages in English.
- **Commit prefixes:** `[ADD]` new features, `[CHG]` modifications, `[FIX]` bug fixes.
- **Version headers:** when a script carries a version, bump it AND set the date to `11.08.2026`. Header comment and any version constant must agree.
- **Never edit anything under `scripts/lib/`** — it is dead code that reaches no server.
- **Do not commit to a remote.** Commit locally only; the human partner pushes.
- **Test suite command:** `python3 -m unittest discover -s tests` from the repository root. It must pass at the end of every task.
- **A finding must never contain the value of a key whose lowercased name ends in `password`, nor of `admin_passwd`.** This output is pasted into support tickets.
- **Findings are 1-based line numbers.** PyYAML marks are 0-based; always `+ 1`.
- **Severity vocabulary:** exactly the two strings `"error"` and `"warning"`.
- **Exit codes:** `0` no errors, `1` at least one error, `2` a file is missing, unreadable, unparseable, or PyYAML is absent.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/ownerp_validate.py` (new) | Everything: loader, schemas, checks, report, CLI. One file, ~600 lines, because it is copied to servers as a single script. |
| `scripts/update_docker_odoo.py` (modify) | `--validate` delegates; the DNS write path can no longer run under `--validate` |
| `scripts/container2backup.py` (modify) | `--validate` delegates; `backup_path` read defensively |
| `getScripts.py` (modify) | distributes the new script |
| `fish/conf.d/33-aliases-backup.fish` (modify) | `doval` alias |
| `tests/test_ownerp_validate.py` (new) | The whole validator |
| `tests/test_update_docker_odoo.py` (modify) | Delegation and the read-only guarantee |

Inside `ownerp_validate.py` the sections are, in order: header and constants,
`PositionedDict` + loader, `Finding` + helpers, the generic schema walker, the
two schemas, the per-file entry points with their collision checks, rendering,
`main()`.

---

## Task 1: The positioned loader

**Files:**
- Create: `scripts/ownerp_validate.py`
- Test: `tests/test_ownerp_validate.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `SCRIPT_VERSION = "1.0.0"`, `SCRIPT_DATE = "11.08.2026"`
  - `ERROR = "error"`, `WARNING = "warning"`
  - `Finding = namedtuple("Finding", "severity file line path message")`
  - `class PositionedDict(dict)` with instance attributes `line: int` and `key_lines: dict`
  - `line_of(mapping, key=None) -> int` — the line of `key` inside `mapping`, or of the mapping itself; `0` when unknown
  - `load_positioned(path) -> (data, fatal)` where `fatal` is `None` on success or a `Finding` describing why nothing could be loaded

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ownerp_validate.py`:

```python
"""
Tests for ownerp_validate.py.

Unlike the rest of the suite, these tests need a real PyYAML: the module under
test exists to parse YAML, so a placeholder module would test nothing. The
whole module skips itself when PyYAML is absent.

Run from the repository root:

    python3 -m unittest tests.test_ownerp_validate -v
"""

import os
import sys
import textwrap
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

try:
    import yaml  # noqa: F401
except ImportError:  # pragma: no cover - depends on the machine
    raise unittest.SkipTest("PyYAML is not installed")

import ownerp_validate as ov  # noqa: E402

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def write(tmpdir, name, text):
    """Write a YAML fixture and return its path."""
    path = os.path.join(tmpdir, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(textwrap.dedent(text).lstrip("\n"))
    return path


class PositionedLoadingTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_a_mapping_knows_its_own_line(self):
        path = write(self.tmp.name, "c.yaml", """
            # a comment
            defaults:
              db_user: ownerp
        """)
        data, fatal = ov.load_positioned(path)
        self.assertIsNone(fatal)
        self.assertEqual(data["defaults"].line, 3)

    def test_every_key_knows_its_own_line(self):
        path = write(self.tmp.name, "c.yaml", """
            defaults:
              db_user: ownerp
              backup_path: /opt/backups
        """)
        data, _ = ov.load_positioned(path)
        self.assertEqual(ov.line_of(data["defaults"], "db_user"), 2)
        self.assertEqual(ov.line_of(data["defaults"], "backup_path"), 3)

    def test_a_nested_mapping_reports_its_own_line_not_its_parents(self):
        path = write(self.tmp.name, "c.yaml", """
            defaults:
              compression:
                format: "7z"
        """)
        data, _ = ov.load_positioned(path)
        self.assertEqual(data["defaults"].line, 2)
        self.assertEqual(data["defaults"]["compression"].line, 3)

    def test_a_mapping_inside_a_list_keeps_its_position(self):
        path = write(self.tmp.name, "c.yaml", """
            containers:
              - container_name: live-odoo
              - container_name: test-odoo
        """)
        data, _ = ov.load_positioned(path)
        self.assertEqual(ov.line_of(data["containers"][1], "container_name"), 3)

    def test_line_of_an_unknown_key_is_zero(self):
        path = write(self.tmp.name, "c.yaml", "defaults:\n  db_user: ownerp\n")
        data, _ = ov.load_positioned(path)
        self.assertEqual(ov.line_of(data["defaults"], "nope"), 0)

    def test_broken_yaml_is_one_finding_with_a_line(self):
        path = write(self.tmp.name, "c.yaml", """
            containers:
              - active: true
               type: "F"
        """)
        data, fatal = ov.load_positioned(path)
        self.assertIsNone(data)
        self.assertEqual(fatal.severity, ov.ERROR)
        self.assertGreater(fatal.line, 0)

    def test_a_missing_file_is_a_fatal_finding(self):
        data, fatal = ov.load_positioned(os.path.join(self.tmp.name, "nope.yaml"))
        self.assertIsNone(data)
        self.assertIn("not found", fatal.message)

    def test_a_top_level_that_is_not_a_mapping_is_fatal(self):
        path = write(self.tmp.name, "c.yaml", "- one\n- two\n")
        data, fatal = ov.load_positioned(path)
        self.assertIsNone(data)
        self.assertIn("mapping", fatal.message)

    def test_an_empty_file_is_fatal(self):
        path = write(self.tmp.name, "c.yaml", "")
        data, fatal = ov.load_positioned(path)
        self.assertIsNone(data)
        self.assertIsNotNone(fatal)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_ownerp_validate -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ownerp_validate'`

- [ ] **Step 3: Write the script header and the loader**

Create `scripts/ownerp_validate.py`, executable (`chmod +x`):

```python
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
    """Return the 1-based line of `key` inside `mapping`, or of the mapping.

    An unknown key returns 0, not the mapping's line: callers use
    'line_of(data, key) or line_of(data)' to fall back deliberately, and a
    non-zero answer here would take that choice away from them.
    """
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_ownerp_validate -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Commit**

```bash
chmod +x scripts/ownerp_validate.py
git add scripts/ownerp_validate.py tests/test_ownerp_validate.py
git commit -m "[ADD] ownerp_validate.py v1.0.0: YAML loading that keeps line numbers"
```

---

## Task 2: Findings and the schema walker

**Files:**
- Modify: `scripts/ownerp_validate.py`
- Test: `tests/test_ownerp_validate.py`

**Interfaces:**
- Consumes: `Finding`, `PositionedDict`, `line_of` from Task 1
- Produces:
  - `parse_port(value) -> int | None`
  - `is_empty(value) -> bool`
  - `redacted(key) -> bool`
  - `expand(path) -> str`
  - `validate_mapping(data, fields, path_prefix, file_path, findings, downgrade=False)` — walks one mapping against a field schema and appends `Finding`s
  - Rule vocabulary understood by `validate_mapping`: `required`, `type`, `enum`, `min`, `max`, `port`, `path` (`"dir"` / `"file"` / `"any"`), `fields`, `item`, `min_items`, `free`

**Rule semantics, exactly:**

| Rule | Meaning |
|---|---|
| `required: True` | Missing or empty → error. `False` and `0` are **not** empty. |
| `type` | A type or tuple of types. `int` rejects `bool` explicitly (`True` is an `int` in Python). |
| `enum` | Value must be in the list; compared as-is, no case folding. |
| `min` / `max` | Numeric bounds, checked only after the type check passed. |
| `port: True` | Value must parse via `parse_port` and land in 1–65535. |
| `path` | Existence check on the expanded value → **warning** when absent. `"dir"` also warns when the target exists but is not a directory. |
| `fields` | The value must be a mapping; recurse into it. |
| `item` | The value must be a list; apply the item schema to each element. |
| `min_items` | List shorter than this → error. |
| `free: True` | Presence is known, the value is not inspected at all. |

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ownerp_validate.py`:

```python
class PortParsingTest(unittest.TestCase):
    def test_the_four_accepted_forms(self):
        self.assertEqual(ov.parse_port(11000), 11000)
        self.assertEqual(ov.parse_port("11000"), 11000)
        self.assertEqual(ov.parse_port("127.0.0.1:11000"), 11000)
        self.assertEqual(ov.parse_port("[::1]:11000"), 11000)

    def test_out_of_range_and_nonsense_are_rejected(self):
        self.assertIsNone(ov.parse_port(0))
        self.assertIsNone(ov.parse_port(70000))
        self.assertIsNone(ov.parse_port("achtzehn"))
        self.assertIsNone(ov.parse_port("127.0.0.1:"))

    def test_a_bool_is_not_a_port(self):
        # True == 1 in Python; a port of True must not become port 1.
        self.assertIsNone(ov.parse_port(True))


class EmptinessTest(unittest.TestCase):
    def test_false_and_zero_are_not_empty(self):
        self.assertFalse(ov.is_empty(False))
        self.assertFalse(ov.is_empty(0))

    def test_none_and_blank_containers_are_empty(self):
        for value in (None, "", [], {}):
            self.assertTrue(ov.is_empty(value), repr(value))


class SchemaWalkerTest(unittest.TestCase):
    SCHEMA = {
        "name":   {"type": str, "required": True},
        "count":  {"type": int, "min": 0},
        "mode":   {"enum": ["M", "F", "N"]},
        "port":   {"port": True},
        "flag":   {"type": bool},
        "notes":  {"free": True},
    }

    def walk(self, mapping, downgrade=False):
        findings = []
        ov.validate_mapping(mapping, self.SCHEMA, "root", "f.yaml",
                            findings, downgrade=downgrade)
        return findings

    def test_a_clean_mapping_produces_nothing(self):
        self.assertEqual(self.walk({"name": "live", "count": 3, "mode": "F",
                                    "port": "127.0.0.1:11000", "flag": True,
                                    "notes": {"anything": [1, 2]}}), [])

    def test_a_missing_required_field_is_an_error(self):
        findings = self.walk({"count": 1})
        self.assertEqual([f.severity for f in findings], [ov.ERROR])
        self.assertEqual(findings[0].path, "root.name")

    def test_an_empty_required_field_is_an_error(self):
        self.assertEqual(self.walk({"name": ""})[0].severity, ov.ERROR)

    def test_a_wrong_type_is_an_error(self):
        findings = self.walk({"name": "live", "count": "drei"})
        self.assertEqual(findings[0].path, "root.count")
        self.assertEqual(findings[0].severity, ov.ERROR)

    def test_a_bool_is_not_accepted_where_an_int_is_required(self):
        findings = self.walk({"name": "live", "count": True})
        self.assertEqual(findings[0].path, "root.count")

    def test_a_value_below_min_is_an_error(self):
        findings = self.walk({"name": "live", "count": -1})
        self.assertIn("0", findings[0].message)

    def test_a_value_outside_the_enum_is_an_error(self):
        findings = self.walk({"name": "live", "mode": "X"})
        self.assertIn("M, F, N", findings[0].message)

    def test_an_unknown_key_is_a_warning_with_a_suggestion(self):
        findings = self.walk({"name": "live", "cout": 3})
        self.assertEqual(findings[0].severity, ov.WARNING)
        self.assertIn("count", findings[0].message)

    def test_an_unrecognisable_key_is_a_warning_without_a_suggestion(self):
        findings = self.walk({"name": "live", "zzzzzzzz": 3})
        self.assertEqual(findings[0].severity, ov.WARNING)
        self.assertNotIn("did you mean", findings[0].message)

    def test_downgrade_turns_every_error_into_a_warning(self):
        findings = self.walk({"count": "drei"}, downgrade=True)
        self.assertTrue(findings)
        self.assertTrue(all(f.severity == ov.WARNING for f in findings))
        self.assertTrue(all(f.message.startswith("(inactive)") for f in findings))

    def test_findings_carry_the_line_of_the_offending_key(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "c.yaml", """
                name: live
                count: drei
            """)
            data, _ = ov.load_positioned(path)
            findings = []
            ov.validate_mapping(data, self.SCHEMA, "root", path, findings)
            self.assertEqual(findings[0].line, 2)


class RedactionTest(unittest.TestCase):
    SCHEMA = {"db_password": {"type": str, "required": True}}

    def test_a_password_value_never_appears_in_a_finding(self):
        findings = []
        ov.validate_mapping({"db_password": 12345}, self.SCHEMA,
                            "containers[0]", "f.yaml", findings)
        self.assertTrue(findings)
        self.assertNotIn("12345", findings[0].message)

    def test_redacted_recognises_the_password_keys(self):
        self.assertTrue(ov.redacted("db_password"))
        self.assertTrue(ov.redacted("DB_PASSWORD"))
        self.assertTrue(ov.redacted("admin_passwd"))
        self.assertFalse(ov.redacted("db_user"))


class PathRuleTest(unittest.TestCase):
    SCHEMA = {"where": {"type": str, "path": "dir"}}

    def test_a_missing_path_is_a_warning(self):
        findings = []
        ov.validate_mapping({"where": "/definitely/not/here"}, self.SCHEMA,
                            "root", "f.yaml", findings)
        self.assertEqual(findings[0].severity, ov.WARNING)

    def test_an_existing_directory_produces_nothing(self):
        findings = []
        ov.validate_mapping({"where": os.path.dirname(__file__)}, self.SCHEMA,
                            "root", "f.yaml", findings)
        self.assertEqual(findings, [])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_ownerp_validate -v`
Expected: FAIL with `AttributeError: module 'ownerp_validate' has no attribute 'parse_port'`

- [ ] **Step 3: Write the helpers and the walker**

Append to `scripts/ownerp_validate.py`, after `load_positioned`:

```python
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
            # bool is a subclass of int: 'delay_time: true' must not pass.
            if not wrong and expected is int and isinstance(value, bool):
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
            if not os.path.exists(target):
                _add(findings, WARNING, file_path, line, path,
                     f"{target} does not exist", downgrade)
            elif rule["path"] == "dir" and not os.path.isdir(target):
                _add(findings, WARNING, file_path, line, path,
                     f"{target} exists but is not a directory", downgrade)

    known = list(fields)
    for key in data:
        if key in fields:
            continue
        close = difflib.get_close_matches(str(key), known, n=1, cutoff=0.6)
        hint = f' - did you mean "{close[0]}"?' if close else ""
        _add(findings, WARNING, file_path, line_of(data, key),
             _join(path_prefix, key), f"unknown key{hint}", downgrade)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_ownerp_validate -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/ownerp_validate.py tests/test_ownerp_validate.py
git commit -m "[ADD] ownerp_validate.py: findings and the declarative schema walker"
```

---

## Task 3: The two schemas and the cross-entry checks

**Files:**
- Modify: `scripts/ownerp_validate.py`
- Test: `tests/test_ownerp_validate.py`

**Interfaces:**
- Consumes: `validate_mapping`, `parse_port`, `line_of`, `Finding` from Task 2
- Produces:
  - `UPDATE_SCHEMA`, `BACKUP_SCHEMA` — top-level field schemas
  - `validate_update(path) -> (findings, fatal)`
  - `validate_backup(path) -> (findings, fatal)`

**The key lists are not invented — they were read out of the code.** The
runner reads exactly these container keys: `active`, `type`, `delay_time`,
`container_name`, `database_name`, `port`, `longpolling_port`,
`dockerfile_path`, `docker_image_name`, `db_user`, `db_password`, `db_host`,
`volume`, `odoo_version`, `translate`, `db_password_via_env`,
`log_retention_days`, `proxy`, `pre_build_files`; and these `defaults` keys:
`proxy`, `dockerfiles_source`, `log_retention_days`, `history_retention_days`.

The backup script reads `defaults`: `retention_days`, `db_user`,
`backup_path`, `temp_path`, `stream`, `compression.format`,
`compression.level`, `additional_paths`; `services.<name>`: `enabled`,
`source_path`, `backup_path`, `retention_days`; `databases[]`: `name`,
`db_user`, `sql_container`, `data_container`, `retention_days`,
`only_sql_dump`, `stream`, `additional_paths`, `fast_report.enabled`,
`fast_report.path`; and `rsync`: `enabled`, `commands`.

`additional_paths` is `free` in both places: it is a mapping of arbitrary
names to arbitrary sub-mappings, and `create_backup()` accepts it as a
parameter without using it. It is carried in the schema so no operator gets a
false "unknown key" for a setting that has been in the template for years.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ownerp_validate.py`:

```python
GOOD_UPDATE = """
    defaults:
      log_retention_days: 90
      history_retention_days: 365
    containers:
      - active: true
        type: "F"
        delay_time: 10
        container_name: "live-odoo"
        database_name: "live_odoo"
        port: "127.0.0.1:11000"
        longpolling_port: "127.0.0.1:12000"
        dockerfile_path: "{here}"
        docker_image_name: "odoo/live"
        db_user: "ownerp"
        db_password: "secret"
        db_host: "live-db"
        volume: "-v /opt/odoo/live:/opt/odoo/data"
        odoo_version: "18"
        translate: "Y"
        db_password_via_env: true
"""


class UpdateSchemaTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.here = os.path.dirname(os.path.abspath(__file__))

    def check(self, text):
        path = write(self.tmp.name, "u.yaml", text.format(here=self.here))
        findings, fatal = ov.validate_update(path)
        self.assertIsNone(fatal, fatal and fatal.message)
        return findings

    def errors(self, text):
        return [f for f in self.check(text) if f.severity == ov.ERROR]

    def test_a_good_configuration_produces_no_errors(self):
        self.assertEqual(self.errors(GOOD_UPDATE), [])

    def test_a_good_configuration_produces_no_unknown_keys(self):
        self.assertEqual(
            [f for f in self.check(GOOD_UPDATE) if "unknown key" in f.message],
            [])

    def test_a_missing_containers_section_is_an_error(self):
        errors = self.errors("defaults:\n  log_retention_days: 90\n")
        self.assertTrue(any("containers" in f.path for f in errors))

    def test_an_empty_containers_list_is_an_error(self):
        self.assertTrue(self.errors("containers: []\n"))

    def test_a_bad_type_letter_is_an_error(self):
        errors = self.errors(GOOD_UPDATE.replace('type: "F"', 'type: "X"'))
        self.assertEqual(len(errors), 1)
        self.assertIn("M, F, N", errors[0].message)

    def test_a_non_numeric_delay_time_is_an_error(self):
        errors = self.errors(GOOD_UPDATE.replace("delay_time: 10",
                                                 'delay_time: "zehn"'))
        self.assertEqual(len(errors), 1)

    def test_a_bad_retention_in_defaults_is_an_error(self):
        errors = self.errors(GOOD_UPDATE.replace("log_retention_days: 90",
                                                 'log_retention_days: "90 days"'))
        self.assertTrue(any("log_retention_days" in f.path for f in errors))

    def test_a_missing_dockerfile_path_is_a_warning_not_an_error(self):
        text = GOOD_UPDATE.replace('dockerfile_path: "{here}"',
                                   'dockerfile_path: "/definitely/not/here"')
        findings = self.check(text)
        self.assertEqual([f for f in findings if f.severity == ov.ERROR], [])
        self.assertTrue(any("dockerfile_path" in f.path for f in findings))

    def test_a_typo_in_a_container_key_is_a_warning_with_a_suggestion(self):
        findings = self.check(GOOD_UPDATE.replace('odoo_version: "18"',
                                                  'odoo_versoin: "18"'))
        hits = [f for f in findings if "unknown key" in f.message]
        self.assertEqual(len(hits), 1)
        self.assertIn("odoo_version", hits[0].message)
        self.assertEqual(hits[0].severity, ov.WARNING)


class CollisionTest(UpdateSchemaTest):
    TWO = GOOD_UPDATE + """
      - active: true
        type: "M"
        delay_time: 10
        container_name: "test-odoo"
        database_name: "test_db"
        port: "127.0.0.1:13000"
        longpolling_port: "127.0.0.1:14000"
        dockerfile_path: "{here}"
        docker_image_name: "odoo/test"
        db_user: "ownerp"
        db_password: "secret"
        db_host: "test-db"
"""

    def test_two_distinct_containers_do_not_collide(self):
        self.assertEqual(self.errors(self.TWO), [])

    def test_a_duplicate_container_name_is_an_error(self):
        errors = self.errors(self.TWO.replace('"test-odoo"', '"live-odoo"'))
        self.assertTrue(any("container_name" in f.path for f in errors))

    def test_a_duplicate_database_name_is_an_error(self):
        errors = self.errors(self.TWO.replace('"test_db"', '"live_odoo"'))
        self.assertTrue(any("database_name" in f.path for f in errors))

    def test_a_duplicate_port_is_an_error_naming_the_other_line(self):
        errors = self.errors(self.TWO.replace('"127.0.0.1:13000"',
                                              '"127.0.0.1:11000"'))
        self.assertEqual(len(errors), 1)
        self.assertIn("live-odoo", errors[0].message)
        self.assertIn("line", errors[0].message)

    def test_a_port_colliding_with_a_longpolling_port_is_an_error(self):
        # Both are host ports and share one namespace.
        errors = self.errors(self.TWO.replace('"127.0.0.1:13000"',
                                              '"127.0.0.1:12000"'))
        self.assertEqual(len(errors), 1)

    def test_the_same_port_on_a_different_bind_address_is_still_a_collision(self):
        errors = self.errors(self.TWO.replace('"127.0.0.1:13000"',
                                              '"0.0.0.0:11000"'))
        self.assertEqual(len(errors), 1)

    def test_an_inactive_container_never_collides(self):
        # The second block reuses the first block's port, but cannot run.
        text = (self.TWO
                .replace('"127.0.0.1:13000"', '"127.0.0.1:11000"')
                .replace('- active: true\n        type: "M"',
                         '- active: false\n        type: "M"'))
        self.assertIn('active: false', text)   # the replace really matched
        self.assertEqual(self.errors(text), [])


class InactiveDowngradeTest(UpdateSchemaTest):
    BROKEN = GOOD_UPDATE.replace('type: "F"', 'type: "X"')

    def test_a_broken_active_block_yields_errors(self):
        self.assertTrue(self.errors(self.BROKEN))

    def test_the_same_block_inactive_yields_warnings_only(self):
        findings = self.check(self.BROKEN.replace("active: true",
                                                  "active: false"))
        self.assertEqual([f for f in findings if f.severity == ov.ERROR], [])
        self.assertTrue(any("(inactive)" in f.message for f in findings))


GOOD_BACKUP = """
    defaults:
      retention_days: 14
      db_user: ownerp
      backup_path: "{here}"
      temp_path: "{here}"
      stream: false
      compression:
        format: "7z"
        level: 5
    services:
      nginx:
        enabled: true
        source_path: "{here}"
        backup_path: nginx
        retention_days: 7
    databases:
      - name: live_db
        sql_container: live-db
        data_container: live-odoo
        retention_days: 7
        only_sql_dump: false
        fast_report:
          enabled: false
          path: "{here}"
    rsync:
      enabled: false
      commands: []
"""


class BackupSchemaTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.here = os.path.dirname(os.path.abspath(__file__))

    def check(self, text):
        path = write(self.tmp.name, "b.yaml", text.format(here=self.here))
        findings, fatal = ov.validate_backup(path)
        self.assertIsNone(fatal, fatal and fatal.message)
        return findings

    def errors(self, text):
        return [f for f in self.check(text) if f.severity == ov.ERROR]

    def test_a_good_configuration_produces_no_errors(self):
        self.assertEqual(self.errors(GOOD_BACKUP), [])

    def test_a_good_configuration_produces_no_unknown_keys(self):
        self.assertEqual(
            [f for f in self.check(GOOD_BACKUP) if "unknown key" in f.message],
            [])

    def test_an_unknown_compression_format_is_an_error(self):
        errors = self.errors(GOOD_BACKUP.replace('format: "7z"',
                                                 'format: "rar"'))
        self.assertEqual(len(errors), 1)

    def test_a_compression_level_above_nine_is_an_error(self):
        self.assertTrue(self.errors(GOOD_BACKUP.replace("level: 5",
                                                        "level: 11")))

    def test_a_service_without_a_source_path_is_an_error(self):
        errors = self.errors(GOOD_BACKUP.replace(
            'source_path: "{here}"\n        backup_path: nginx',
            'backup_path: nginx'))
        self.assertTrue(any("source_path" in f.path for f in errors))

    def test_a_service_without_a_backup_path_is_an_error(self):
        # This one is a KeyError at runtime today, not a message.
        errors = self.errors(GOOD_BACKUP.replace("backup_path: nginx\n", ""))
        self.assertTrue(any("services.nginx.backup_path" in f.path
                            for f in errors))

    def test_a_database_without_a_sql_container_is_an_error(self):
        errors = self.errors(GOOD_BACKUP.replace(
            "sql_container: live-db\n", ""))
        self.assertTrue(any("sql_container" in f.path for f in errors))

    def test_a_duplicate_database_name_is_an_error(self):
        text = GOOD_BACKUP + """
      - name: live_db
        sql_container: other-db
        data_container: other-odoo
"""
        errors = self.errors(text)
        self.assertTrue(any("name" in f.path for f in errors))

    def test_additional_paths_is_known_and_not_inspected(self):
        text = GOOD_BACKUP.replace("        only_sql_dump: false",
                                   "        only_sql_dump: false\n"
                                   "        additional_paths:\n"
                                   "          whatever:\n"
                                   "            anything: 1")
        self.assertEqual(
            [f for f in self.check(text) if "unknown key" in f.message], [])

    def test_a_typo_in_defaults_is_a_warning_with_a_suggestion(self):
        findings = self.check(GOOD_BACKUP.replace("retention_days: 14",
                                                  "retention_day: 14"))
        hits = [f for f in findings if "unknown key" in f.message]
        self.assertEqual(len(hits), 1)
        self.assertIn("retention_days", hits[0].message)


class ShippedTemplateTest(unittest.TestCase):
    """The schema must know every key the shipped templates carry.

    Without this, a key added to a template a year from now silently becomes a
    false 'unknown key' on every customer server, and the typo check is the
    first thing operators learn to ignore. Path warnings are expected here -
    the templates point at paths that only exist on a real server.
    """

    def assert_clean(self, findings, path):
        errors = [f for f in findings if f.severity == ov.ERROR]
        self.assertEqual(errors, [], f"{path}: {[f.message for f in errors]}")
        unknown = [f for f in findings if "unknown key" in f.message]
        self.assertEqual(unknown, [],
                         f"{path}: {[f.message for f in unknown]}")

    def test_the_update_template_validates(self):
        path = os.path.join(REPO_ROOT, "scripts", "docker2update.yaml")
        findings, fatal = ov.validate_update(path)
        self.assertIsNone(fatal)
        self.assert_clean(findings, path)

    def test_the_proxy_example_validates(self):
        path = os.path.join(REPO_ROOT, "scripts",
                            "docker2update-proxy-example.yaml")
        findings, fatal = ov.validate_update(path)
        self.assertIsNone(fatal)
        self.assert_clean(findings, path)

    def test_the_backup_template_validates(self):
        path = os.path.join(REPO_ROOT, "scripts", "container2backup.yaml")
        findings, fatal = ov.validate_backup(path)
        self.assertIsNone(fatal)
        self.assert_clean(findings, path)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_ownerp_validate -v`
Expected: FAIL with `AttributeError: module 'ownerp_validate' has no attribute 'validate_update'`

- [ ] **Step 3: Write the schemas and the entry points**

Append to `scripts/ownerp_validate.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_ownerp_validate -v`
Expected: PASS. If `ShippedTemplateTest` reports an unknown key, the schema is
missing a key that the template carries — add it to the schema after checking
that a script actually reads it, and say so in the task report.

- [ ] **Step 5: Commit**

```bash
git add scripts/ownerp_validate.py tests/test_ownerp_validate.py
git commit -m "[ADD] ownerp_validate.py: schemas for both configs, collisions, inactive downgrade"
```

---

## Task 4: The report and the command line

**Files:**
- Modify: `scripts/ownerp_validate.py`
- Test: `tests/test_ownerp_validate.py`

**Interfaces:**
- Consumes: `validate_update`, `validate_backup` from Task 3
- Produces:
  - `render(path, findings, fatal, stream)` — writes one file's block
  - `main(argv=None) -> int` — the exit code

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ownerp_validate.py`:

```python
class CommandLineTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.here = os.path.dirname(os.path.abspath(__file__))

    def run_main(self, argv):
        import contextlib
        import io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = ov.main(argv)
        return code, buffer.getvalue()

    def test_a_clean_file_exits_zero(self):
        path = write(self.tmp.name, "u.yaml", GOOD_UPDATE.format(here=self.here))
        code, output = self.run_main(["--update", path])
        self.assertEqual(code, 0)
        self.assertIn("no findings", output)

    def test_an_error_exits_one(self):
        text = GOOD_UPDATE.format(here=self.here).replace('type: "F"', 'type: "X"')
        path = write(self.tmp.name, "u.yaml", text)
        code, output = self.run_main(["--update", path])
        self.assertEqual(code, 1)
        self.assertIn("1 error", output)

    def test_a_warning_alone_still_exits_zero(self):
        text = GOOD_UPDATE.format(here=self.here).replace(
            f'dockerfile_path: "{self.here}"', 'dockerfile_path: "/nope/nope"')
        path = write(self.tmp.name, "u.yaml", text)
        code, output = self.run_main(["--update", path])
        self.assertEqual(code, 0)
        self.assertIn("warning", output)

    def test_unparseable_yaml_exits_two(self):
        path = write(self.tmp.name, "u.yaml",
                     "containers:\n  - active: true\n   type: F\n")
        code, _ = self.run_main(["--update", path])
        self.assertEqual(code, 2)

    def test_a_file_named_explicitly_but_missing_exits_two(self):
        code, output = self.run_main(
            ["--update", os.path.join(self.tmp.name, "nope.yaml")])
        self.assertEqual(code, 2)
        self.assertIn("not found", output)

    def test_a_default_file_that_is_absent_is_skipped_not_fatal(self):
        # The default paths are computed at import time, so patching HOME here
        # would change nothing and the test would silently read the real ~.
        from unittest import mock
        absent = os.path.join(self.tmp.name, "absent.yaml")
        with mock.patch.object(ov, "DEFAULT_UPDATE_CONFIG", absent), \
             mock.patch.object(ov, "DEFAULT_BACKUP_CONFIG", absent):
            code, output = self.run_main([])
        self.assertEqual(code, 0)
        self.assertIn("skipped", output)

    def test_the_report_names_the_line(self):
        text = GOOD_UPDATE.format(here=self.here).replace('type: "F"', 'type: "X"')
        path = write(self.tmp.name, "u.yaml", text)
        _, output = self.run_main(["--update", path])
        self.assertRegex(output, r"\s6\s")   # 'type:' sits on line 6

    def test_version_prints_and_exits_zero(self):
        code, output = self.run_main(["--version"])
        self.assertEqual(code, 0)
        self.assertIn(ov.SCRIPT_VERSION, output)
```

**Note:** `--version` must be handled without `argparse`'s own `action="version"`,
which calls `sys.exit()` and would escape `main()`'s return-code contract.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_ownerp_validate -v`
Expected: FAIL with `AttributeError: module 'ownerp_validate' has no attribute 'main'`

- [ ] **Step 3: Write the report and main**

Append to `scripts/ownerp_validate.py`:

```python
MARK = {ERROR: "✗", WARNING: "⚠"}


def _line(finding):
    """One report line: mark, line number, dotted path, message."""
    where = f"{finding.path}: " if finding.path else ""
    return (f"  {MARK[finding.severity]}  {finding.line or '':>3}  "
            f"{where}{finding.message}\n")


def render(path, findings, fatal, stream=None):
    """Write one file's block. Returns (errors, warnings)."""
    out = stream or sys.stdout
    if fatal is not None:
        out.write(f"\n{path}\n" + _line(fatal))
        return 1, 0
    if not findings:
        out.write(f"\n{path} - no findings\n")
        return 0, 0

    out.write(f"\n{path}\n")
    for finding in findings:
        out.write(_line(finding))
    errors = sum(1 for f in findings if f.severity == ERROR)
    return errors, len(findings) - errors


def parse_arguments(argv):
    parser = argparse.ArgumentParser(
        prog="ownerp_validate.py",
        description="Read-only validation of the ownERP YAML configurations.")
    parser.add_argument("--update", nargs="?", const=DEFAULT_UPDATE_CONFIG,
                        metavar="PATH",
                        help="validate docker2update.yaml "
                             f"(default: {DEFAULT_UPDATE_CONFIG})")
    parser.add_argument("--backup", nargs="?", const=DEFAULT_BACKUP_CONFIG,
                        metavar="PATH",
                        help="validate container2backup.yaml "
                             f"(default: {DEFAULT_BACKUP_CONFIG})")
    # Not argparse's own version action: it calls sys.exit() and would escape
    # main()'s return-code contract, which the tests and the callers rely on.
    parser.add_argument("--version", action="store_true",
                        help="print the version and exit")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_arguments(argv)

    if args.version:
        print(f"ownerp_validate.py {SCRIPT_VERSION} ({SCRIPT_DATE})")
        return 0

    if yaml is None:
        print("PyYAML is not installed. Install it with:\n"
              "  apt install python3-yaml", file=sys.stderr)
        return 2

    print(f"ownerp_validate.py {SCRIPT_VERSION} ({SCRIPT_DATE})")

    # With no flag both files are checked at their default paths. A file that
    # was not asked for by name and is simply not there is a legitimate
    # installation - a server that runs updates but no backups - so it is
    # skipped rather than failed.
    jobs = []
    if args.update or args.backup:
        if args.update:
            jobs.append((args.update, validate_update, True))
        if args.backup:
            jobs.append((args.backup, validate_backup, True))
    else:
        jobs.append((DEFAULT_UPDATE_CONFIG, validate_update, False))
        jobs.append((DEFAULT_BACKUP_CONFIG, validate_backup, False))

    errors = warnings = 0
    unreadable = False
    for path, check, named in jobs:
        if not named and not os.path.isfile(path):
            print(f"\n{path} - skipped, not present")
            continue
        findings, fatal = check(path)
        if fatal is not None:
            unreadable = True
        file_errors, file_warnings = render(path, findings, fatal)
        if fatal is None:
            errors += file_errors
            warnings += file_warnings

    print()
    if unreadable:
        print("configuration could not be read")
        return 2
    if errors or warnings:
        print(f"{errors} error{'s' if errors != 1 else ''}, "
              f"{warnings} warning{'s' if warnings != 1 else ''}")
    else:
        print("no findings")
    return 1 if errors else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_ownerp_validate -v`
Expected: PASS

- [ ] **Step 5: Run it by hand against the shipped templates**

```bash
python3 scripts/ownerp_validate.py --update scripts/docker2update.yaml
python3 scripts/ownerp_validate.py --backup scripts/container2backup.yaml
echo "exit: $?"
```

Expected: path warnings only, exit 0. Paste the output into the task report.

- [ ] **Step 6: Commit**

```bash
git add scripts/ownerp_validate.py tests/test_ownerp_validate.py
git commit -m "[ADD] ownerp_validate.py: report rendering, command line and exit codes"
```

---

## Task 5: The runner delegates, and stops writing

**Files:**
- Modify: `scripts/update_docker_odoo.py` (header `Version 5.11.0` → `5.12.0`, date `11.08.2026`)
- Test: `tests/test_update_docker_odoo.py`

**Interfaces:**
- Consumes: `scripts/ownerp_validate.py` as a subprocess
- Produces: `run_external_validation(config_file) -> (handled: bool, code: int)`

**Two independent guarantees, both required:**

1. `--validate` delegates before `load_config()` is even called, so broken YAML
   gets the validator's line number instead of the runner's generic message.
2. The DNS optimisation's `save_updated_config()` call is guarded by
   `args.validate` as well, so the fallback path (validator not installed) is
   read-only too. Belt and braces: each is testable on its own.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_update_docker_odoo.py` (keep the file's existing PyYAML
stand-in pattern at the top — do not change it):

```python
class ExternalValidationTest(unittest.TestCase):
    """--validate delegates to ownerp_validate.py, and never writes."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    # NOTE: update_docker_odoo.py does 'from os.path import ... isfile ...',
    # so the name to patch is udo.isfile - patching udo.os.path.isfile would
    # leave the module-level name untouched and the test would pass by
    # accident against the real filesystem.

    def test_it_delegates_when_the_validator_sits_beside_the_script(self):
        import subprocess
        from unittest import mock
        recorded = {}

        def fake_run(argv, **kwargs):
            recorded["argv"] = argv
            return subprocess.CompletedProcess(argv, 0)

        with mock.patch.object(udo, "isfile", return_value=True), \
             mock.patch.object(udo.subprocess, "run", side_effect=fake_run):
            handled, code = udo.run_external_validation("/etc/my.yaml")

        self.assertTrue(handled)
        self.assertEqual(code, 0)
        self.assertIn("--update", recorded["argv"])
        self.assertIn("/etc/my.yaml", recorded["argv"])
        self.assertTrue(recorded["argv"][1].endswith("ownerp_validate.py"))

    def test_it_passes_the_validators_exit_code_through(self):
        import subprocess
        from unittest import mock
        with mock.patch.object(udo, "isfile", return_value=True), \
             mock.patch.object(udo.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 1)):
            handled, code = udo.run_external_validation("/etc/my.yaml")
        self.assertEqual((handled, code), (True, 1))

    def test_it_falls_back_when_the_validator_is_absent(self):
        from unittest import mock
        with mock.patch.object(udo, "isfile", return_value=False):
            handled, code = udo.run_external_validation("/etc/my.yaml")
        self.assertFalse(handled)

    def test_the_validator_is_looked_for_beside_this_script(self):
        self.assertEqual(
            udo.validator_path(),
            os.path.join(os.path.dirname(os.path.abspath(udo.__file__)),
                         "ownerp_validate.py"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_update_docker_odoo -v`
Expected: FAIL with `AttributeError: module 'update_docker_odoo' has no attribute 'run_external_validation'`

- [ ] **Step 3: Add the delegation**

In `scripts/update_docker_odoo.py`, after `load_config()`:

```python
VALIDATOR_SCRIPT = "ownerp_validate.py"


def validator_path():
    """The validator that ships beside this script."""
    return join(os.path.dirname(os.path.abspath(__file__)), VALIDATOR_SCRIPT)


def run_external_validation(config_file):
    """Hand --validate to ownerp_validate.py.

    Returns (handled, exit_code). handled is False when the validator is not
    installed - an older installation keeps the flag it always had, with the
    built-in per-container check behind it, rather than losing it to a hard
    failure.
    """
    validator = validator_path()
    if not isfile(validator):
        logger.warning(
            f"{VALIDATOR_SCRIPT} not found beside this script - falling back "
            "to the built-in configuration check. Run 'ups' to install it.")
        return False, 0
    result = subprocess.run([sys.executable, validator, "--update", config_file])
    return True, result.returncode
```

- [ ] **Step 4: Wire it into main()**

In `main()`, immediately after the PyYAML import check and **before**
`config = load_config(args.config)`:

```python
    # --validate is strictly read-only, and delegating before load_config()
    # means broken YAML gets a line number instead of a generic message.
    if args.validate:
        handled, code = run_external_validation(args.config)
        if handled:
            return code
```

Then, in the DNS block further down, replace:

```python
    if config_modified:
        if save_updated_config(config, args.config):
```

with:

```python
    if config_modified and args.validate:
        # The fallback path lands here when the validator is not installed.
        # --validate never writes, so report what a real run would change.
        print("DNS optimizations would be applied (not written: "
              "--validate is read-only)")
    elif config_modified:
        if save_updated_config(config, args.config):
```

- [ ] **Step 5: Bump the version header**

`# Version 5.11.0` → `# Version 5.12.0`, `# Date 11.08.2026` (unchanged).
Check for a `SCRIPT_VERSION` constant and update it to match.

- [ ] **Step 6: Run the full suite**

Run: `python3 -m unittest discover -s tests`
Expected: PASS

- [ ] **Step 7: Verify the read-only guarantee by hand**

```bash
cp scripts/docker2update.yaml /tmp/v.yaml
md5=$(md5sum /tmp/v.yaml 2>/dev/null || md5 -q /tmp/v.yaml)
python3 scripts/update_docker_odoo.py -c /tmp/v.yaml --validate
md5b=$(md5sum /tmp/v.yaml 2>/dev/null || md5 -q /tmp/v.yaml)
test "$md5" = "$md5b" && echo "UNCHANGED" || echo "FILE WAS WRITTEN"
```

Expected: `UNCHANGED`. Paste the output into the task report.

- [ ] **Step 8: Commit**

```bash
git add scripts/update_docker_odoo.py tests/test_update_docker_odoo.py
git commit -m "[FIX] update_docker_odoo.py v5.12.0: --validate delegates and no longer writes the YAML"
```

---

## Task 6: The backup script gets --validate

**Files:**
- Modify: `scripts/container2backup.py` (header `Version: 4.7.1` → `4.8.0`, `Date: 11.08.2026`)

**Interfaces:**
- Consumes: `scripts/ownerp_validate.py` as a subprocess
- Produces: nothing other scripts use

- [ ] **Step 1: Move the argument parsing above the banner**

In the `if __name__ == "__main__":` block, move the four `argparse` lines
(currently below the version and system-information banner) to the very top of
the block, and gate the banner on `not args.validate`:

```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Backup Odoo databases with Docker')
    parser.add_argument('--sql-only', action='store_true',
                        help='Force SQL dump only mode for all databases (overrides YAML settings)')
    parser.add_argument('--validate', action='store_true',
                        help='Only validate the configuration, then exit')
    args = parser.parse_args()

    base_path = expanduser("~")
    backup_config = base_path + '/container2backup.yaml'

    if args.validate:
        sys.exit(run_external_validation(backup_config))

    # Display version information
    print("===================================================")
    # ... the existing banner, system information and backup flow follow here,
    # unchanged, except that the 'base_path' / 'backup_config' assignments and
    # the argparse block that used to sit inside them are now above.
```

The banner prints `/etc/os-release` in full; a validation run has no use for
it. Everything below the banner keeps its current order, with two removals:
the old `argparse` block (now above) and the second `base_path` /
`backup_config` assignment, which would otherwise shadow the first. Do not
delete anything else from that block.

- [ ] **Step 2: Add the delegation**

Above the `if __name__ == "__main__":` block:

```python
VALIDATOR_SCRIPT = "ownerp_validate.py"


def run_external_validation(config_file):
    """Hand --validate to ownerp_validate.py beside this script.

    Unlike update_docker_odoo.py there is no older behaviour to fall back to,
    so a missing validator is reported as 'cannot check' (exit 2) rather than
    as a clean configuration.
    """
    validator = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             VALIDATOR_SCRIPT)
    if not os.path.isfile(validator):
        print(f"{VALIDATOR_SCRIPT} not found beside this script. "
              "Run 'ups' to install it.")
        return 2
    result = subprocess.run([sys.executable, validator, "--backup", config_file])
    return result.returncode
```

Check the module's imports: `sys` and `subprocess` must be imported at the top.
Add whichever is missing.

- [ ] **Step 3: Fix the bare backup_path subscript**

Two places read `service_config['backup_path']` with a bare subscript
(around lines 781 and 1379). A missing key is a `KeyError` in the middle of a
backup run. Replace both with a fallback to the service's own name:

```python
    # A missing backup_path used to raise KeyError mid-run. The service name
    # is the obvious subdirectory, and the validator reports the omission.
    backup_subdir = service_config.get('backup_path') or service_name
```

At line 781 the function is `backup_additional_service(service_config, ...)`,
which does not receive the service name — add a `service_name` parameter and
pass it from the caller at line 1379, which iterates
`config.get('services', {}).items()` and therefore has it.

- [ ] **Step 4: Bump the version header**

`# Version:          4.8.0`, `# Date:             11.08.2026`. Check for a
`SCRIPT_VERSION` constant (the banner prints one) and keep the two in step.

- [ ] **Step 5: Verify by hand**

```bash
python3 -m py_compile scripts/container2backup.py && echo "compiles"
cp scripts/container2backup.yaml ~/container2backup.yaml.probe
python3 scripts/container2backup.py --validate 2>&1 | head -20
echo "exit: $?"
```

The script reads `~/container2backup.yaml`; if you do not have one, expect
`not found` and exit 2 — which is itself the specified behaviour. Report which
of the two you saw.

- [ ] **Step 6: Run the full suite**

Run: `python3 -m unittest discover -s tests`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add scripts/container2backup.py
git commit -m "[ADD] container2backup.py v4.8.0: --validate, and backup_path no longer raises KeyError"
```

---

## Task 7: Distribution, alias and documentation

**Files:**
- Modify: `getScripts.py` (`SCRIPT_VERSION = "9.11.0"` → `"9.12.0"`, `SCRIPT_DATE = "11.08.2026"`)
- Modify: `fish/conf.d/33-aliases-backup.fish` (`Version 1.1.0` → `1.2.0`)
- Modify: `RELEASE_NOTES.md`, `CLAUDE.md`, `ReadMe.md`, `usage/AGENT.md`, `docs/INSTALLATION_GUIDE.md`

**Interfaces:**
- Consumes: everything built in Tasks 1–6
- Produces: nothing other tasks use

- [ ] **Step 1: Distribute the script**

In `getScripts.py`, `copy_scripts()`, add `"ownerp_validate.py"` directly after
`"ownerp_tui.py"` in the `scripts` list. Check whether the copy loop preserves
the executable bit; `ownerp_tui.py` is executable and went through the same
loop, so follow whatever it does.

Bump `SCRIPT_VERSION` to `"9.12.0"` and confirm `SCRIPT_DATE` is `"11.08.2026"`.

- [ ] **Step 2: Add the alias**

In `fish/conf.d/33-aliases-backup.fish`, under the update section:

```fish
alias doval='$HOME/ownerp_validate.py'
```

Bump the file's header to `# Version 1.2.0 | 11.08.2026`.

- [ ] **Step 3: Verify the alias file parses**

Run: `fish -c 'source fish/conf.d/33-aliases-backup.fish; and functions -q doval; and echo OK'`
Expected: `OK`

- [ ] **Step 4: Documentation**

Add to each, in the style already used there:

- `RELEASE_NOTES.md` — a new entry naming `ownerp_validate.py` 1.0.0,
  `update_docker_odoo.py` 5.12.0 (delegation plus the read-only fix),
  `container2backup.py` 4.8.0 (`--validate` plus the `KeyError` fix),
  `getScripts.py` 9.12.0.
- `CLAUDE.md` — a component entry for `ownerp_validate.py` in the numbered
  component list, and the `doval` alias in the alias table. The existing
  numbering runs 1–6; the validator becomes 7 rather than renumbering
  everything.
- `ReadMe.md` — **both language halves**: the component, the `doval` alias, the
  script table.
- `usage/AGENT.md` — the flag rows for `--validate` on both scripts, a row for
  `ownerp_validate.py`, and a guardrail: `--validate` is read-only and its
  warnings do not affect the exit code, so a script that gates on it must test
  for `!= 0`, not for "no output".
- `docs/INSTALLATION_GUIDE.md` — a short section in **both** the German and the
  English half: run `doval` after editing a configuration, what the three exit
  codes mean.

German text follows the repo's typography rule: quotation marks always as the
pair „…“ (U+201E opening, U+201C closing), never an ASCII `"` as the closing
quote.

- [ ] **Step 5: Run the full suite one last time**

Run: `python3 -m unittest discover -s tests`
Expected: PASS. Report the final test count.

- [ ] **Step 6: Commit**

```bash
git add getScripts.py fish/conf.d/33-aliases-backup.fish RELEASE_NOTES.md \
        CLAUDE.md ReadMe.md usage/AGENT.md docs/INSTALLATION_GUIDE.md
git commit -m "[ADD] distribute ownerp_validate.py, add the doval alias, document building block 2"
```

**Do not push.** The human partner pushes to both remotes.

---

## Model Selection

| Task | Tier | Why |
|---|---|---|
| 1 | cheap | The loader code is in this plan verbatim; transcription plus tests. |
| 2 | cheap | Same — the walker is written out in full. |
| 3 | standard | The schemas are given, but the double-walk note and any template mismatch need judgment. |
| 4 | cheap | Rendering and argparse, both written out. |
| 5 | standard | Two edits inside a 2200-line script, in the right places, without disturbing the run path. |
| 6 | standard | Restructuring a top-level block and threading a new parameter through two call sites. |
| 7 | cheap for the code, standard for the German documentation | Two one-line code edits; the docs are prose in two languages. |

## Notes carried forward from reading the code

Three things surfaced while writing this plan. None of them block it; all
belong in the final report to the human partner.

1. **`additional_paths` is dead.** `container2backup.py` collects it from
   `defaults` and each database, merges the two, passes it into
   `create_backup(..., additional_paths=...)` — and `create_backup` never reads
   the parameter. The schema carries the key so nobody gets a false warning;
   whether the feature should be built or removed is a separate decision.
2. **The `rsync` block was missing from the spec's schema sketch**, along with
   `databases[].db_user` and `additional_paths`. All three are read by the
   backup script. They are in this plan's schemas. This is exactly the drift
   the spec predicted between "what the templates carry" and "what the code
   reads".
3. **`services.docker_builds` uses an underscore while its `backup_path` is
   `docker-builds`.** Not a fault — the key is an operator-chosen name — but it
   is why `services` cannot have an enumerated key list.
