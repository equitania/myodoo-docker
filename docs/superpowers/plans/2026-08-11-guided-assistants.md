# Guided Assistants Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ownerp_wizard.py` walks an operator through adding an Odoo instance to `docker2update.yaml` and through changing individual fields, and cannot leave the customer's file in a state the validator rejects.

**Architecture:** One standalone Python script that imports `ownerp_validate` from the same directory for its schema and its checks. Field edits locate their line through the validator's positioned loader. Every write goes to a temporary file in the same directory, is validated there, and only then replaces the original with `os.replace()`.

**Tech Stack:** Python 3, standard library plus PyYAML. Tests are stdlib `unittest`. Target is system Python on Debian/Ubuntu servers under PEP 668 — no `pip install`.

**Spec:** `docs/superpowers/specs/2026-08-11-guided-assistants-design.md`

## Global Constraints

- **The customer's configuration file is never opened for writing.** Every write path is: temp file in the same directory → validate → `os.replace()`. No exception.
- **A rejected result leaves the original byte-identical.** This is the property the tests must prove, not merely assert.
- **Scalars only.** `pre_build_files` and `proxy` are never edited. Shown, not touched.
- **Never remove an entry.** No code path deletes a container, a database or a service block.
- **A finding, a prompt or a summary must never contain the value of `db_password`** — nor of any key whose lowercased name ends in `password`, nor `admin_passwd`.
- **Standard library plus PyYAML only.** No new dependency; no `requirements.txt`, no `pyproject.toml` change.
- **UTF-8 explicitly** on every file operation: `open(..., encoding="utf-8")`.
- **All code, comments and documentation in English.** Commit messages in English.
- **Commit prefixes:** `[ADD]` new features, `[CHG]` modifications, `[FIX]` bug fixes.
- **`ownerp_wizard.py` carries `Version: 1.0.0` / `Date: 11.08.2026` and stays at 1.0.0 for the whole plan** — it is new and ships once. Do not bump it per task.
- **Never edit anything under `scripts/lib/`** — dead code that reaches no server.
- **Do not modify `scripts/ownerp_validate.py`.** It is imported, not changed. If you believe it needs a change, stop and report instead.
- **Do not commit to a remote.** Commit locally only.
- **Test suite:** `python3 -m unittest discover -s tests` from the repository root. It stands at **343 tests, OK**, and must pass at the end of every task.

## What already exists and is imported

`scripts/ownerp_validate.py` v1.0.0, in the same directory:

```python
ERROR = "error";  WARNING = "warning"
Finding = namedtuple("Finding", "severity file line path message")

class PositionedDict(dict):
    line = 0          # 1-based line of the mapping's FIRST KEY
    key_lines = None  # {key: 1-based line of that key}

line_of(mapping, key=None)   # unknown key -> 0, deliberately
load_positioned(path)        # -> (data, fatal)
validate_update(path)        # -> (findings, fatal)
CONTAINER_FIELDS             # the 19-key schema; 10 of them "required": True
parse_port(value)            # -> int | None
is_empty(value)  redacted(key)  expand(path)
```

The shipped container block in `scripts/docker2update.yaml`, which the appended
block must match in shape:

```yaml
  - active: true
    type: "F"
    delay_time: 10
    container_name: "live-odoo"
    database_name: "live_odoo"
    port: "127.0.0.1:11000"
    longpolling_port: "127.0.0.1:12000"
    dockerfile_path: "$HOME/docker-builds/live-odoo/"
    docker_image_name: "odoo/live"
    db_user: "ownerp"
    db_password: "CHANGE_ME_BEFORE_PRODUCTION"  # WARNING: Replace with secure password!
    db_host: "live-db"
    volume: "--network live-db-net -v /opt/odoo/live:/opt/odoo/data"
    odoo_version: "18"
    translate: "Y"
    db_password_via_env: true  # secure default: password via -e PGPASSWORD, not argv
```

Sixteen keys. `- ` at two spaces, the remaining keys at four.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/ownerp_wizard.py` (new) | everything: line mechanics, safe write, form, suggestions, prompts, CLI |
| `scripts/ownerp_tui.py` (modify) | one new key, `w`, plus a reload afterwards |
| `getScripts.py` (modify) | distribute the script |
| `fish/conf.d/33-aliases-backup.fish` (modify) | `wiz` alias |
| `tests/test_ownerp_wizard.py` (new) | the whole wizard |

Inside `ownerp_wizard.py`, in order: header and imports, line mechanics, safe
write, the form and suggestions, the two write operations, prompts, `main()`.

---

## Task 1: Line mechanics

**Files:**
- Create: `scripts/ownerp_wizard.py`
- Test: `tests/test_ownerp_wizard.py`

**Interfaces:**
- Consumes: nothing from the validator yet
- Produces:
  - `split_comment(text) -> (code, comment)` — splits a YAML line into its code part and its trailing comment, **quote-aware**
  - `format_value(value) -> str` — renders a Python value as a YAML scalar
  - `patch_line(line, new_value) -> str` — rewrites one `key: value` line, preserving indentation, key and trailing comment
  - `entry_bounds(lines, start_line, indent) -> (first, last)` — the 0-based half-open range of the block that begins at 1-based `start_line`

**The trap this task exists for:** a naive `text.split("#")` corrupts
`volume: "--network x -v /opt/a#b:/data"  # note`. The `#` inside the quoted
scalar is not a comment. `split_comment` walks the line tracking whether it is
inside a single- or double-quoted scalar, and only treats `#` as a comment when
it is outside quotes **and** preceded by whitespace or at the start.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ownerp_wizard.py`:

```python
"""
Tests for ownerp_wizard.py.

Like the validator's tests, these need a real PyYAML: the wizard imports
ownerp_validate, which subclasses yaml.SafeLoader. The whole module skips
itself when PyYAML is absent.

Run from the repository root:

    python3 -m unittest tests.test_ownerp_wizard -v
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

import ownerp_wizard as wiz  # noqa: E402

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TEMPLATE = os.path.join(REPO_ROOT, "scripts", "docker2update.yaml")


class SplitCommentTest(unittest.TestCase):
    def test_a_plain_line_has_no_comment(self):
        self.assertEqual(wiz.split_comment('    port: "11000"'),
                         ('    port: "11000"', ""))

    def test_a_trailing_comment_is_split_off(self):
        code, comment = wiz.split_comment('    x: true  # secure default')
        self.assertEqual(code, '    x: true')
        self.assertEqual(comment, '  # secure default')

    def test_a_hash_inside_a_double_quoted_value_is_not_a_comment(self):
        line = '    volume: "-v /opt/a#b:/data"'
        self.assertEqual(wiz.split_comment(line), (line, ""))

    def test_a_hash_inside_a_single_quoted_value_is_not_a_comment(self):
        line = "    volume: '-v /opt/a#b:/data'"
        self.assertEqual(wiz.split_comment(line), (line, ""))

    def test_a_quoted_hash_and_a_real_comment_together(self):
        code, comment = wiz.split_comment('    v: "a#b"  # note')
        self.assertEqual(code, '    v: "a#b"')
        self.assertEqual(comment, '  # note')

    def test_a_hash_without_leading_space_is_not_a_comment(self):
        # 'a#b' unquoted is a legal YAML scalar; '#' only starts a comment
        # when it follows whitespace.
        line = '    v: a#b'
        self.assertEqual(wiz.split_comment(line), (line, ""))


class FormatValueTest(unittest.TestCase):
    def test_strings_are_double_quoted(self):
        self.assertEqual(wiz.format_value("live-odoo"), '"live-odoo"')

    def test_booleans_are_lowercase_and_bare(self):
        self.assertEqual(wiz.format_value(True), "true")
        self.assertEqual(wiz.format_value(False), "false")

    def test_integers_are_bare(self):
        self.assertEqual(wiz.format_value(10), "10")

    def test_a_quote_inside_a_string_is_escaped(self):
        self.assertEqual(wiz.format_value('a"b'), '"a\\"b"')

    def test_a_backslash_inside_a_string_is_escaped(self):
        self.assertEqual(wiz.format_value("a\\b"), '"a\\\\b"')

    def test_the_result_round_trips_through_yaml(self):
        for value in ("live-odoo", "$HOME/x/", 'a"b', "a\\b", "a#b", True, 10):
            rendered = wiz.format_value(value)
            self.assertEqual(yaml.safe_load(f"k: {rendered}")["k"], value,
                             f"round trip failed for {value!r}")


class PatchLineTest(unittest.TestCase):
    def test_the_value_is_replaced_and_indentation_kept(self):
        self.assertEqual(wiz.patch_line('    port: "11000"', "12000"),
                         '    port: "12000"')

    def test_a_trailing_comment_survives(self):
        self.assertEqual(
            wiz.patch_line('    db_password_via_env: true  # secure default',
                           False),
            '    db_password_via_env: false  # secure default')

    def test_a_hash_inside_the_old_value_does_not_confuse_it(self):
        self.assertEqual(wiz.patch_line('    v: "a#b"  # note', "c"),
                         '    v: "c"  # note')

    def test_the_first_key_of_a_list_entry_keeps_its_dash(self):
        self.assertEqual(wiz.patch_line('  - active: true', False),
                         '  - active: false')


class EntryBoundsTest(unittest.TestCase):
    LINES = textwrap.dedent("""
        containers:
          - active: true
            type: "F"
          - active: false
            type: "M"

        # trailing comment
    """).lstrip("\n").split("\n")

    def test_the_first_entry_ends_where_the_second_begins(self):
        self.assertEqual(wiz.entry_bounds(self.LINES, 2, 2), (1, 3))

    def test_the_last_entry_ends_before_the_blank_tail(self):
        first, last = wiz.entry_bounds(self.LINES, 4, 2)
        self.assertEqual(first, 3)
        self.assertEqual(last, 5)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_ownerp_wizard -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ownerp_wizard'`

- [ ] **Step 3: Write the header and the line mechanics**

Create `scripts/ownerp_wizard.py`, executable:

```python
#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Title:            ownerp_wizard.py
# Description:      Guided editing of docker2update.yaml - add an instance,
#                   change a field. Validates before it replaces anything.
# Version:          1.0.0
# Date:             11.08.2026
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

# The validator is not optional here. A wizard that cannot check its own
# output must not write, so there is nothing to degrade to - unlike the runner,
# which keeps a built-in check when the validator is missing.
try:
    import ownerp_validate as validator
except ImportError:  # pragma: no cover - depends on the installation
    validator = None

SCRIPT_VERSION = "1.0.0"
SCRIPT_DATE = "11.08.2026"

DEFAULT_UPDATE_CONFIG = os.path.join(os.path.expanduser("~"), "docker2update.yaml")


def split_comment(text):
    """Split a YAML line into its code part and its trailing comment.

    Quote-aware, because a naive split on '#' corrupts a line like

        volume: "--network x -v /opt/a#b:/data"  # note

    where the first '#' is part of the value. A '#' starts a comment only
    outside quotes and only when it follows whitespace or begins the line.
    """
    in_single = in_double = False
    for index, char in enumerate(text):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            if index == 0 or text[index - 1].isspace():
                # The gap belongs to the comment, so code + comment
                # reconstructs the line byte for byte - two spaces before a
                # '#' must not silently become one.
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
    top-level key. Trailing blank lines and comment-only lines belong to
    whatever comes after, not to this entry.
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
    # Give trailing blank and comment lines back to the following block.
    while last > first + 1 and not lines[last - 1].strip():
        last -= 1
    return first, last
```

**Note on `split_comment`'s return value:** the tests require the comment to
carry the whitespace that preceded it, so that `code + comment` reconstructs
the original line. Make the implementation satisfy the tests; the sketch above
is the shape, not necessarily the exact slicing.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_ownerp_wizard -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
chmod +x scripts/ownerp_wizard.py
git add scripts/ownerp_wizard.py tests/test_ownerp_wizard.py
git commit -m "[ADD] ownerp_wizard.py v1.0.0: quote-aware line mechanics"
```

---

## Task 2: The safe write

**Files:**
- Modify: `scripts/ownerp_wizard.py`
- Test: `tests/test_ownerp_wizard.py`

**Interfaces:**
- Consumes: `validator.validate_update` from the imported module
- Produces:
  - `backup_name(path, now) -> str` — `<path>.bak-<YYYYmmdd_HHMMSS>`
  - `safe_write(path, new_lines, now=None) -> (ok, findings, backup)` — the whole eight-step sequence

**The sequence, with no branch left implicit:**

1. Copy the original to `backup_name(path, now)`.
2. Write the new text to `<path>.tmp-<pid>` in the **same directory**, so the
   later `os.replace()` is atomic (it is only atomic within one filesystem).
3. `validator.validate_update(tmp)`.
4. Any `ERROR` finding, or a `fatal` — remove the temp file, remove the
   backup, leave the original untouched, return `(False, findings, None)`.
5. Otherwise `os.replace(tmp, path)`, keep the backup, return
   `(True, findings, backup)`.

**The backup is kept only when the original was actually replaced.** A backup
identical to a file nobody changed is litter in the operator's home directory,
and litter trains people to ignore `.bak-*` files — the exact wrong habit for
the one case where it matters.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ownerp_wizard.py`:

```python
import shutil
import tempfile


class SafeWriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "docker2update.yaml")
        shutil.copy(TEMPLATE, self.path)
        with open(self.path, encoding="utf-8") as handle:
            self.original = handle.read()

    def lines(self):
        with open(self.path, encoding="utf-8") as handle:
            return handle.read().split("\n")

    def current(self):
        with open(self.path, encoding="utf-8") as handle:
            return handle.read()

    def leftovers(self):
        return sorted(n for n in os.listdir(self.tmp.name)
                      if n != "docker2update.yaml")

    def test_a_clean_write_replaces_the_file_and_keeps_the_backup(self):
        new = self.lines()
        new.insert(0, "# touched by the test")
        ok, findings, backup = wiz.safe_write(self.path, new)
        self.assertTrue(ok, [f.message for f in findings])
        self.assertTrue(self.current().startswith("# touched by the test"))
        self.assertTrue(os.path.isfile(backup))
        with open(backup, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), self.original)

    def test_a_rejected_write_leaves_the_original_byte_identical(self):
        new = [line.replace('type: "F"', 'type: "X"') for line in self.lines()]
        ok, findings, backup = wiz.safe_write(self.path, new)
        self.assertFalse(ok)
        self.assertEqual(self.current(), self.original)
        self.assertIsNone(backup)
        self.assertTrue(any(f.severity == validator_error() for f in findings))

    def test_a_rejected_write_leaves_no_backup_and_no_temp_file(self):
        new = [line.replace('type: "F"', 'type: "X"') for line in self.lines()]
        wiz.safe_write(self.path, new)
        self.assertEqual(self.leftovers(), [])

    def test_unparseable_output_is_rejected_too(self):
        new = self.lines() + ["  this: is: not: yaml"]
        ok, _findings, backup = wiz.safe_write(self.path, new)
        self.assertFalse(ok)
        self.assertEqual(self.current(), self.original)
        self.assertIsNone(backup)

    def test_warnings_alone_do_not_block_the_write(self):
        # The template's dockerfile_path does not exist here - a warning.
        new = self.lines()
        ok, findings, _backup = wiz.safe_write(self.path, new)
        self.assertTrue(ok)
        self.assertTrue(findings, "expected the path warnings")

    def test_the_backup_name_carries_a_timestamp(self):
        import datetime
        stamp = datetime.datetime(2026, 8, 11, 19, 30, 5)
        self.assertTrue(
            wiz.backup_name("/x/c.yaml", stamp).endswith(".bak-20260811_193005"))

    def test_the_temp_file_lives_beside_the_original(self):
        # os.replace() is only atomic within one filesystem.
        seen = {}
        real_replace = os.replace

        def spy(src, dst):
            seen["src"] = src
            return real_replace(src, dst)

        from unittest import mock
        with mock.patch.object(wiz.os, "replace", side_effect=spy):
            wiz.safe_write(self.path, self.lines())
        self.assertEqual(os.path.dirname(seen["src"]),
                         os.path.dirname(self.path))


def validator_error():
    import ownerp_validate
    return ownerp_validate.ERROR
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_ownerp_wizard -v`
Expected: FAIL with `AttributeError: module 'ownerp_wizard' has no attribute 'safe_write'`

- [ ] **Step 3: Write the safe write**

Append to `scripts/ownerp_wizard.py`:

```python
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
        for leftover in (tmp,):
            if os.path.exists(leftover):
                os.remove(leftover)
        if os.path.exists(backup):
            os.remove(backup)
        raise
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_ownerp_wizard -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/ownerp_wizard.py tests/test_ownerp_wizard.py
git commit -m "[ADD] ownerp_wizard.py: validate-then-replace write with a timestamped backup"
```

---

## Task 3: The form and the suggestions

**Files:**
- Modify: `scripts/ownerp_wizard.py`
- Test: `tests/test_ownerp_wizard.py`

**Interfaces:**
- Consumes: `validator.CONTAINER_FIELDS`, `validator.parse_port`
- Produces:
  - `Field = namedtuple("Field", "name label help suggest")`
  - `UPDATE_FORM` — the sixteen fields of the shipped block, in the shipped order
  - `TEMPLATE_DEFAULTS` — the shipped values, used when the configuration is empty
  - `used_ports(containers) -> set[int]`
  - `suggest_free_port(containers)` / `suggest_longpolling(containers, http)`
  - `suggest_unanimous(containers, field)` — the value when every entry agrees, else `None`
  - `suggest_path_pattern(containers, field, new_name)` — the shared pattern with the new name substituted

**The form is not the schema.** `CONTAINER_FIELDS` says a `port` must parse and
is required; it does not say what to call it on screen, in what order to ask,
or what to propose. The form does. **A test holds the two together**: every
`required` field of the schema appears in the form, and every field of the form
exists in the schema. That is the same guard the shipped-template test provides
in building block 2 — the place drift appears when nobody is looking.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ownerp_wizard.py`:

```python
CONTAINERS = [
    {"container_name": "live-odoo", "database_name": "live_odoo",
     "port": "127.0.0.1:11000", "longpolling_port": "127.0.0.1:12000",
     "dockerfile_path": "$HOME/docker-builds/live-odoo/",
     "docker_image_name": "odoo/live", "db_user": "ownerp",
     "db_host": "live-db", "odoo_version": "18", "active": True},
    {"container_name": "test-odoo", "database_name": "test_db",
     "port": "127.0.0.1:13000", "longpolling_port": "127.0.0.1:14000",
     "dockerfile_path": "$HOME/docker-builds/test-odoo/",
     "docker_image_name": "odoo/test", "db_user": "ownerp",
     "db_host": "test-db", "odoo_version": "18", "active": False},
]


class FormMatchesSchemaTest(unittest.TestCase):
    """The one test that keeps the form and the schema from drifting apart."""

    def test_every_required_schema_field_is_asked_for(self):
        import ownerp_validate as ov
        required = {name for name, rule in ov.CONTAINER_FIELDS.items()
                    if rule.get("required")}
        asked = {field.name for field in wiz.UPDATE_FORM}
        self.assertEqual(required - asked, set(),
                         "required schema fields missing from the form")

    def test_every_form_field_exists_in_the_schema(self):
        import ownerp_validate as ov
        asked = {field.name for field in wiz.UPDATE_FORM}
        self.assertEqual(asked - set(ov.CONTAINER_FIELDS), set(),
                         "form asks for fields the schema does not know")

    def test_the_form_asks_in_the_shipped_order(self):
        self.assertEqual([f.name for f in wiz.UPDATE_FORM][:5],
                         ["active", "type", "delay_time",
                          "container_name", "database_name"])

    def test_every_field_has_a_label_and_help(self):
        for field in wiz.UPDATE_FORM:
            self.assertTrue(field.label, field.name)
            self.assertTrue(field.help, field.name)


class SuggestionTest(unittest.TestCase):
    def test_used_ports_covers_both_port_fields_and_inactive_entries(self):
        self.assertEqual(wiz.used_ports(CONTAINERS),
                         {11000, 12000, 13000, 14000})

    def test_the_next_free_port_clears_every_used_one(self):
        port = wiz.suggest_free_port(CONTAINERS)
        self.assertNotIn(port, wiz.used_ports(CONTAINERS))
        self.assertGreater(port, 14000)

    def test_the_longpolling_port_does_not_collide_with_the_http_port(self):
        http = wiz.suggest_free_port(CONTAINERS)
        poll = wiz.suggest_longpolling(CONTAINERS, http)
        self.assertNotEqual(poll, http)
        self.assertNotIn(poll, wiz.used_ports(CONTAINERS))

    def test_an_empty_configuration_falls_back_to_the_template_port(self):
        self.assertEqual(wiz.suggest_free_port([]), 11000)

    def test_a_unanimous_value_is_suggested(self):
        self.assertEqual(wiz.suggest_unanimous(CONTAINERS, "db_user"), "ownerp")

    def test_a_split_value_is_not_suggested(self):
        self.assertIsNone(wiz.suggest_unanimous(CONTAINERS, "db_host"))

    def test_an_empty_configuration_suggests_nothing_unanimous(self):
        self.assertIsNone(wiz.suggest_unanimous([], "db_user"))

    def test_the_path_pattern_substitutes_the_new_name(self):
        self.assertEqual(
            wiz.suggest_path_pattern(CONTAINERS, "dockerfile_path", "demo-odoo"),
            "$HOME/docker-builds/demo-odoo/")

    def test_the_path_pattern_gives_up_when_the_paths_disagree(self):
        containers = [dict(CONTAINERS[0]),
                      dict(CONTAINERS[1], dockerfile_path="/srv/other/")]
        self.assertIsNone(
            wiz.suggest_path_pattern(containers, "dockerfile_path", "demo-odoo"))

    def test_the_image_name_follows_the_shipped_convention(self):
        # live-odoo -> odoo/live, so demo-odoo -> odoo/demo. Name substitution
        # cannot do this: "live-odoo" does not occur in "odoo/live".
        self.assertEqual(wiz.suggest_image_name(CONTAINERS, "demo-odoo"),
                         "odoo/demo")

    def test_the_image_name_gives_up_when_the_prefixes_disagree(self):
        containers = [dict(CONTAINERS[0]),
                      dict(CONTAINERS[1], docker_image_name="other/test")]
        self.assertIsNone(wiz.suggest_image_name(containers, "demo-odoo"))

    def test_an_empty_configuration_suggests_the_template_image_prefix(self):
        self.assertEqual(wiz.suggest_image_name([], "demo-odoo"), "odoo/demo")

    def test_no_suggestion_is_offered_for_a_password(self):
        password = [f for f in wiz.UPDATE_FORM if f.name == "db_password"][0]
        self.assertIsNone(password.suggest)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_ownerp_wizard -v`
Expected: FAIL with `AttributeError: module 'ownerp_wizard' has no attribute 'UPDATE_FORM'`

- [ ] **Step 3: Write the form and the suggestions**

Append to `scripts/ownerp_wizard.py`:

```python
import collections

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
```

A `suggest` callable takes `(containers, entry_so_far)` — the second argument
is what the operator has answered up to this point, which is how the
longpolling port can build on the HTTP port and the build folder can use the
container name.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_ownerp_wizard -v`
Expected: PASS. If `FormMatchesSchemaTest` fails, the form and the schema
disagree — fix the form, and say in your report which field it was.

- [ ] **Step 5: Commit**

```bash
git add scripts/ownerp_wizard.py tests/test_ownerp_wizard.py
git commit -m "[ADD] ownerp_wizard.py: the form, and suggestions drawn from the existing config"
```

---

## Task 4: Appending an entry and patching a field

**Files:**
- Modify: `scripts/ownerp_wizard.py`
- Test: `tests/test_ownerp_wizard.py`

**Interfaces:**
- Consumes: everything from Tasks 1–3, plus `validator.load_positioned`, `validator.line_of`
- Produces:
  - `render_container(entry) -> list[str]` — the commented block
  - `containers_end(lines, data) -> int` — the 0-based index to insert at
  - `append_container(lines, data, entry) -> list[str]`
  - `patch_field(lines, data, index, field, value) -> list[str]`

**The property the tests must prove, not assert:** appending and patching leave
**every other line byte-identical**. Compare the full line lists, not a
substring.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ownerp_wizard.py`:

```python
NEW_ENTRY = {
    "active": True, "type": "F", "delay_time": 10,
    "container_name": "demo-odoo", "database_name": "demo_db",
    "port": 15000, "longpolling_port": 16000,
    "dockerfile_path": "$HOME/docker-builds/demo-odoo/",
    "docker_image_name": "odoo/demo", "db_user": "ownerp",
    "db_password": "s3cret", "db_host": "demo-db",
    "volume": "--network demo-db-net -v /opt/odoo/demo:/opt/odoo/data",
    "odoo_version": "18", "translate": "Y", "db_password_via_env": True,
}


class AppendTest(unittest.TestCase):
    def setUp(self):
        with open(TEMPLATE, encoding="utf-8") as handle:
            self.lines = handle.read().split("\n")
        self.data, fatal = wiz.validator.load_positioned(TEMPLATE)
        self.assertIsNone(fatal)

    def test_the_result_parses_and_holds_the_new_entry(self):
        result = wiz.append_container(self.lines, self.data, NEW_ENTRY)
        parsed = yaml.safe_load("\n".join(result))
        names = [c["container_name"] for c in parsed["containers"]]
        self.assertEqual(names[-1], "demo-odoo")

    def test_every_entered_value_survives_the_round_trip(self):
        result = wiz.append_container(self.lines, self.data, NEW_ENTRY)
        parsed = yaml.safe_load("\n".join(result))["containers"][-1]
        for key, value in NEW_ENTRY.items():
            if key in ("port", "longpolling_port"):
                self.assertEqual(wiz.validator.parse_port(parsed[key]), value)
            else:
                self.assertEqual(parsed[key], value, key)

    def test_every_pre_existing_line_is_untouched(self):
        # Split at the real insertion point rather than assuming the template
        # ends with exactly one blank line - the property under test is
        # "nothing else moved", not "the file has a particular tail".
        at = wiz.containers_end(self.lines, self.data)
        block = wiz.render_container(NEW_ENTRY)
        result = wiz.append_container(self.lines, self.data, NEW_ENTRY)
        self.assertEqual(result[:at], self.lines[:at])
        self.assertEqual(result[at + len(block):], self.lines[at:])

    def test_the_block_matches_the_shipped_indentation(self):
        block = wiz.render_container(NEW_ENTRY)
        self.assertTrue(block[0].startswith("  - "), block[0])
        self.assertTrue(all(l.startswith("    ") for l in block[1:]), block)


class PatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "c.yaml")
        shutil.copy(TEMPLATE, self.path)
        with open(self.path, encoding="utf-8") as handle:
            self.lines = handle.read().split("\n")
        self.data, _ = wiz.validator.load_positioned(self.path)

    def test_only_the_target_line_changes(self):
        result = wiz.patch_field(self.lines, self.data, 0, "port", 19000)
        differing = [i for i, (a, b) in enumerate(zip(self.lines, result))
                     if a != b]
        self.assertEqual(len(differing), 1, differing)

    def test_the_new_value_is_readable_again(self):
        result = wiz.patch_field(self.lines, self.data, 0, "port", 19000)
        parsed = yaml.safe_load("\n".join(result))["containers"][0]
        self.assertEqual(wiz.validator.parse_port(parsed["port"]), 19000)

    def test_the_second_container_is_reachable_and_the_first_untouched(self):
        # This is what save_updated_config() gets wrong: it scans forward for
        # the next matching key and can land in the following entry.
        result = wiz.patch_field(self.lines, self.data, 1, "port", 19000)
        parsed = yaml.safe_load("\n".join(result))["containers"]
        self.assertEqual(wiz.validator.parse_port(parsed[1]["port"]), 19000)
        self.assertEqual(wiz.validator.parse_port(parsed[0]["port"]), 11000)

    def test_a_trailing_comment_on_the_target_line_survives(self):
        result = wiz.patch_field(self.lines, self.data, 0,
                                 "db_password_via_env", False)
        line = [l for l in result if "db_password_via_env" in l][0]
        self.assertIn("#", line)
        self.assertIn("false", line)

    def test_an_absent_field_is_inserted_at_the_entrys_indentation(self):
        result = wiz.patch_field(self.lines, self.data, 0,
                                 "log_retention_days", 30)
        parsed = yaml.safe_load("\n".join(result))["containers"][0]
        self.assertEqual(parsed["log_retention_days"], 30)
        line = [l for l in result if "log_retention_days" in l][0]
        self.assertTrue(line.startswith("    "), repr(line))

    def test_patching_never_touches_another_entrys_line(self):
        result = wiz.patch_field(self.lines, self.data, 0, "port", 19000)
        parsed = yaml.safe_load("\n".join(result))["containers"][1]
        self.assertEqual(wiz.validator.parse_port(parsed["port"]), 13000)
        self.assertEqual(wiz.validator.parse_port(parsed["longpolling_port"]),
                         14000)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_ownerp_wizard -v`
Expected: FAIL with `AttributeError: module 'ownerp_wizard' has no attribute 'append_container'`

- [ ] **Step 3: Write the two write operations**

Append to `scripts/ownerp_wizard.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_ownerp_wizard -v`
Expected: PASS

- [ ] **Step 5: Prove the whole chain by hand**

```bash
cp scripts/docker2update.yaml /tmp/w.yaml
python3 - <<'PY'
import sys; sys.path.insert(0, "scripts")
import ownerp_wizard as wiz
lines = open("/tmp/w.yaml", encoding="utf-8").read().split("\n")
data, _ = wiz.validator.load_positioned("/tmp/w.yaml")
entry = dict(wiz.TEMPLATE_DEFAULTS)
entry.update(container_name="demo-odoo", database_name="demo_db",
             port=15000, longpolling_port=16000,
             dockerfile_path="/tmp", docker_image_name="odoo/demo",
             db_password="x", db_host="demo-db", volume="-v /tmp:/data")
ok, findings, backup = wiz.safe_write("/tmp/w.yaml",
                                      wiz.append_container(lines, data, entry))
print("ok:", ok, "| backup:", backup)
PY
python3 scripts/ownerp_validate.py --update /tmp/w.yaml; echo "exit=$?"
tail -20 /tmp/w.yaml
```

Expected: `ok: True`, the validator exits 0, and the appended block reads like
the shipped ones. Paste the real output into your report.

- [ ] **Step 6: Commit**

```bash
git add scripts/ownerp_wizard.py tests/test_ownerp_wizard.py
git commit -m "[ADD] ownerp_wizard.py: append an entry, patch a field by line number"
```

---

## Task 5: Prompts and the command line

**Files:**
- Modify: `scripts/ownerp_wizard.py`
- Test: `tests/test_ownerp_wizard.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4
- Produces:
  - `preflight() -> str | None` — the reason the wizard must not run, or `None`
  - `ask(field, containers, entry) -> value` — one prompt with its suggestion
  - `coerce(field_name, text) -> value` — text to the type the schema wants
  - `summary_lines(entry) -> list[str]` — the confirmation, passwords masked
  - `main(argv=None) -> int`

**Refusals, all of them before anything is read or written:**

| Situation | Behaviour |
|---|---|
| `validator is None` | Message naming `ups`, exit 2. Writing without validating is what this block exists to prevent |
| stdout or stdin is not a TTY | Message naming mcedit, exit 2. A wizard has no business in a cron job |
| The configuration does not parse | Message pointing at `doval` for the line number, exit 2 |
| A duplicate container name is entered | Rejected at the prompt with the existing names listed — not at validation |

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ownerp_wizard.py`:

```python
class CoerceTest(unittest.TestCase):
    def test_a_boolean_field_takes_yes_and_no(self):
        self.assertIs(wiz.coerce("active", "true"), True)
        self.assertIs(wiz.coerce("active", "false"), False)

    def test_an_integer_field_becomes_an_int(self):
        self.assertEqual(wiz.coerce("delay_time", "10"), 10)

    def test_a_port_field_keeps_a_bind_address_as_text(self):
        self.assertEqual(wiz.coerce("port", "127.0.0.1:11000"),
                         "127.0.0.1:11000")

    def test_a_bare_port_becomes_an_int(self):
        self.assertEqual(wiz.coerce("port", "11000"), 11000)

    def test_a_string_field_stays_text(self):
        self.assertEqual(wiz.coerce("container_name", "demo-odoo"),
                         "demo-odoo")


class SummaryTest(unittest.TestCase):
    def test_the_password_is_masked(self):
        lines = wiz.summary_lines(NEW_ENTRY)
        joined = "\n".join(lines)
        self.assertNotIn("s3cret", joined)
        self.assertIn("*", joined)

    def test_every_other_value_is_shown(self):
        joined = "\n".join(wiz.summary_lines(NEW_ENTRY))
        self.assertIn("demo-odoo", joined)
        self.assertIn("15000", joined)


class PreflightTest(unittest.TestCase):
    def test_it_refuses_without_a_tty(self):
        from unittest import mock
        with mock.patch.object(wiz.sys.stdout, "isatty", return_value=False):
            self.assertIsNotNone(wiz.preflight())

    def test_it_refuses_without_the_validator(self):
        from unittest import mock
        with mock.patch.object(wiz, "validator", None), \
             mock.patch.object(wiz.sys.stdout, "isatty", return_value=True), \
             mock.patch.object(wiz.sys.stdin, "isatty", return_value=True):
            reason = wiz.preflight()
        self.assertIsNotNone(reason)
        self.assertIn("ups", reason)


class BuildFolderTest(unittest.TestCase):
    """The wizard's one write outside the YAML, and only after asking."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.target = os.path.join(self.tmp.name, "docker-builds", "demo-odoo")

    def test_it_creates_the_directory_on_yes(self):
        import contextlib, io
        from unittest import mock
        with mock.patch.object(wiz, "confirm", return_value=True), \
             contextlib.redirect_stdout(io.StringIO()):
            wiz.offer_build_folder(self.target)
        self.assertTrue(os.path.isdir(self.target))

    def test_it_creates_nothing_on_no(self):
        import contextlib, io
        from unittest import mock
        with mock.patch.object(wiz, "confirm", return_value=False), \
             contextlib.redirect_stdout(io.StringIO()):
            wiz.offer_build_folder(self.target)
        self.assertFalse(os.path.exists(self.target))

    def test_it_does_not_ask_when_the_directory_exists(self):
        import contextlib, io
        from unittest import mock
        os.makedirs(self.target)
        with mock.patch.object(wiz, "confirm") as asked, \
             contextlib.redirect_stdout(io.StringIO()):
            wiz.offer_build_folder(self.target)
        asked.assert_not_called()

    def test_it_puts_nothing_inside_the_new_directory(self):
        # Populating a build folder belongs to odoo_build_cache.py.
        import contextlib, io
        from unittest import mock
        with mock.patch.object(wiz, "confirm", return_value=True), \
             contextlib.redirect_stdout(io.StringIO()):
            wiz.offer_build_folder(self.target)
        self.assertEqual(os.listdir(self.target), [])


class MainTest(unittest.TestCase):
    def test_version_prints_and_exits_zero(self):
        import contextlib, io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = wiz.main(["--version"])
        self.assertEqual(code, 0)
        self.assertIn(wiz.SCRIPT_VERSION, buffer.getvalue())

    def test_it_exits_two_without_a_tty(self):
        import contextlib, io
        from unittest import mock
        buffer = io.StringIO()
        with mock.patch.object(wiz.sys.stdout, "isatty", return_value=False), \
             contextlib.redirect_stdout(buffer):
            self.assertEqual(wiz.main([]), 2)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_ownerp_wizard -v`
Expected: FAIL with `AttributeError: module 'ownerp_wizard' has no attribute 'coerce'`

- [ ] **Step 3: Write the prompts and the CLI**

Append to `scripts/ownerp_wizard.py`. `--version` must be a `store_true`
handled at the top of `main()` — argparse's own version action raises
`SystemExit` and would break `main()`'s contract of returning an int, the same
rule `ownerp_validate.py` follows.

```python
MASK = "********"


def coerce(field_name, text):
    """Turn prompt text into the type the schema expects for that field."""
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
```

```python
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
            for finding in findings:
                print(f"  warning {finding.line or '':>4}  "
                      f"{finding.path}: {finding.message}")
            offer_build_folder(entry["dockerfile_path"])
            return 0

        print("\n  Not written - the result would be invalid:")
        for finding in findings:
            print(f"  {finding.line or '':>4}  {finding.path}: {finding.message}")
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
    for finding in findings:
        print(f"  {finding.line or '':>4}  {finding.path}: {finding.message}")
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
    except KeyboardInterrupt:
        print("\nCancelled - nothing written.")
        sys.exit(130)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_ownerp_wizard -v`
Expected: PASS

- [ ] **Step 5: Walk the wizard by hand**

Run `python3 scripts/ownerp_wizard.py --update /tmp/w2.yaml` against a copy of
the template and add one container, taking every suggestion. Then run
`python3 scripts/ownerp_validate.py --update /tmp/w2.yaml` and confirm exit 0.
Paste both transcripts into your report, with the password line redacted.

Then repeat, entering `X` for the update mode, and confirm the write is
rejected, the file is unchanged, and no `.bak-*` or `.tmp-*` is left behind.

- [ ] **Step 6: Commit**

```bash
git add scripts/ownerp_wizard.py tests/test_ownerp_wizard.py
git commit -m "[ADD] ownerp_wizard.py: prompts, suggestions in brackets, and the command line"
```

---

## Task 6: The TUI key, distribution and documentation

**Files:**
- Modify: `scripts/ownerp_tui.py` (header `Version 1.0.0` → `1.1.0`, date `11.08.2026`)
- Modify: `getScripts.py` (`SCRIPT_VERSION` `9.12.0` → `9.13.0`)
- Modify: `fish/conf.d/33-aliases-backup.fish` (`1.2.0` → `1.3.0`)
- Modify: `RELEASE_NOTES.md`, `CLAUDE.md`, `ReadMe.md`, `usage/AGENT.md`, `docs/INSTALLATION_GUIDE.md`
- Test: `tests/test_ownerp_tui.py`

- [ ] **Step 1: Add the `w` key to the TUI**

**The real names, read out of `ownerp_tui.py` v1.0.0 — do not assume others:**

```python
RUNNER_SCRIPT = join(expanduser("~"), "update_docker_odoo.py")   # a FULL PATH
def load_containers(path=CONFIG_FILE): ...
class UpdateSelection:  # constructed as UpdateSelection(containers) - one argument
def last_run_by_container(entries): ...                          # takes entries
HELP_LINES = [...]
```

Add the constant next to `RUNNER_SCRIPT`, in the same form — a full path, not
a bare name, because `run_outside_curses()` prefixes only `sys.executable`:

```python
WIZARD_SCRIPT = join(expanduser("~"), "ownerp_wizard.py")
```

And, beside the existing `v` branch in the key loop:

```python
        elif key == ord("w"):
            argv = [WIZARD_SCRIPT, "--update"]
            if config:
                argv.append(config)
            run_outside_curses(stdscr, [argv])
            # The wizard may have added an entry. Without this reload the list
            # on screen is a snapshot of a file that no longer looks that way,
            # and the next Enter would run against a stale selection. This is
            # the difference from the 'v' key, which only reads.
            containers = load_containers(config) if config else load_containers()
            selection = UpdateSelection(containers)
            message = "Configuration reloaded."
```

Read the loop's surroundings before writing this: confirm what `config` holds
at that point (the `-c` value or `None`) and that `containers` and `selection`
are the names the loop actually uses. The wizard's own exit code is deliberately
not folded into `worst` — a cancelled wizard is not a failed update run.

Add `w` to the key legend line and to `HELP_LINES`.

- [ ] **Step 2: Test the reload**

The `w` branch itself is curses code and is not tested. What it depends on is:
a fresh `UpdateSelection` built from a longer container list must show the new
entry and pre-select it by its `active` flag. Append to
`tests/test_ownerp_tui.py` (keep the file's existing PyYAML stand-in):

```python
class ReloadAfterWizardTest(unittest.TestCase):
    """What the TUI's 'w' key relies on after the wizard has written."""

    def test_a_rebuilt_selection_shows_an_added_container(self):
        before = tui.UpdateSelection(CONTAINERS)
        after = tui.UpdateSelection(CONTAINERS + [
            {"container_name": "demo-odoo", "database_name": "demo_db",
             "odoo_version": "18", "type": "F", "active": True}])
        self.assertEqual(len(after.rows), len(before.rows) + 1)
        self.assertEqual(after.rows[-1]["name"], "demo-odoo")

    def test_the_added_container_is_preselected_from_its_active_flag(self):
        selection = tui.UpdateSelection(CONTAINERS + [
            {"container_name": "demo-odoo", "database_name": "demo_db",
             "odoo_version": "18", "type": "F", "active": True}])
        self.assertTrue(selection.rows[-1]["selected"])

    def test_a_rebuilt_selection_carries_no_state_from_the_old_one(self):
        # The reload replaces the object; a comment typed before the wizard
        # ran must not silently survive into the new selection.
        before = tui.UpdateSelection(CONTAINERS)
        before.comment = "typed earlier"
        after = tui.UpdateSelection(CONTAINERS)
        self.assertNotEqual(after.comment, "typed earlier")
```

Check the row key names (`name`, `selected`) against `UpdateSelection` before
writing — the existing tests in that file already assert on them.

- [ ] **Step 3: Distribution and alias**

`getScripts.py`: add `"ownerp_wizard.py"` to `copy_scripts()` after
`"ownerp_validate.py"`; bump `SCRIPT_VERSION` to `"9.13.0"`.

`fish/conf.d/33-aliases-backup.fish`: add `alias wiz='$HOME/ownerp_wizard.py'`
and bump the header to `# Version 1.3.0 | 11.08.2026`.

Verify: `fish -c 'source fish/conf.d/33-aliases-backup.fish; and functions -q wiz; and echo OK'`

- [ ] **Step 4: Documentation**

Both language halves of every bilingual file. German quotation marks are always
the pair „…“ — opening U+201E, closing U+201C, never an ASCII `"` as the
closing quote, which breaks the PDF export.

- `RELEASE_NOTES.md` — a new entry: the wizard, the `w` key, `getScripts.py` 9.13.0.
- `CLAUDE.md` — component 8, and `wiz` in the alias block. Do not renumber 1–7.
- `ReadMe.md` — component, alias and quick-reference row, both halves.
- `usage/AGENT.md` — a row for `ownerp_wizard.py`, and this guardrail: **the
  wizard is the only tool in this set that writes to a customer configuration,
  it refuses without a TTY, and it never removes an entry.**
- `docs/INSTALLATION_GUIDE.md` — a short section in both halves: adding an
  instance with `wiz` instead of by hand, and what the backup file is called.

- [ ] **Step 5: Run the full suite**

Run: `python3 -m unittest discover -s tests`
Expected: PASS. Report the final count.

- [ ] **Step 6: Commit**

```bash
git add scripts/ownerp_tui.py getScripts.py fish/conf.d/33-aliases-backup.fish \
        RELEASE_NOTES.md CLAUDE.md ReadMe.md usage/AGENT.md \
        docs/INSTALLATION_GUIDE.md tests/test_ownerp_tui.py
git commit -m "[ADD] distribute ownerp_wizard.py, add the w key and the wiz alias"
```

**Do not push.** The human partner pushes to both remotes.

---

## Model Selection

| Task | Tier | Why |
|---|---|---|
| 1 | cheap | The code is in this plan verbatim; transcription plus tests. |
| 2 | standard | Small, but the failure paths must be exactly right — this is the task that guarantees the original survives. |
| 3 | cheap | Form and suggestions, written out in full. |
| 4 | standard | The insertion point and the absent-field case need judgment against the real template. |
| 5 | standard | The prompt loop and `main()` are described in prose, not written out. |
| 6 | cheap for the code, standard for the German documentation | Three one-line code edits; the docs are prose in two languages. |

## Notes carried forward

- `split_comment` returning the comment **with its leading whitespace** is what
  lets `code + comment` reconstruct a line exactly. The tests pin it; the
  sketch in Task 1 may need adjusting to satisfy them.
- `containers_end` assumes list entries sit at indentation 2 under a top-level
  key, which every shipped layout uses. A configuration that indents
  differently is out of scope; the validator accepts it, the wizard need not.
- `patch_field` takes the container by **index**, not by name. The caller
  resolves the name — the wizard knows the list it displayed.
