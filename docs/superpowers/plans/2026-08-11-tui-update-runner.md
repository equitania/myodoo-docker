# TUI Update Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the operator a curses list to pick systems, mode and a run comment for an ad-hoc Odoo update, instead of editing `active:`/`type:` in `docker2update.yaml` with mcedit and editing them back afterwards.

**Architecture:** A new `scripts/ownerp_tui.py` reads the YAML read-only, renders a selection list enriched with each system's last run, and then leaves curses and starts `update_docker_odoo.py` as a subprocess — one invocation per mode group. The runner gains three flags (`-s` repeatable, `--type`, `--comment`), records every run in `~/update-history.jsonl`, and stops skipping explicitly named but inactive containers. The TUI never writes to any YAML.

**Tech Stack:** Python 3 standard library only (`curses`, `json`, `subprocess`, `unittest`) plus PyYAML from apt (`python3-yaml`). Fish shell for the `doup` switch.

**Spec:** `docs/superpowers/specs/2026-08-11-tui-update-runner-design.md`

## Global Constraints

- **No new dependencies.** Stdlib + `python3-yaml`/`python3-dotenv` from apt. PEP 668 makes `pip install` as root fail on modern Debian/Ubuntu, and `python3-textual` is not available across all target distributions.
- **The TUI never writes to a YAML file.** No exception, no "just this one field".
- **Never a TUI without a TTY.** Cron and pipes always get the classic runner.
- **Minimum terminal size: 80×20.**
- **Never edit anything under `scripts/lib/`.** It is dead code — nothing imports it, so a change there passes every check and reaches no server. Fix `getScripts.py` itself.
- **Code, comments and documentation in English.** Conversation is German.
- **Version headers:** every touched script gets both its `# Version X.Y.Z` header comment *and* its `SCRIPT_VERSION` constant bumped, plus `# Date DD.MM.YYYY` / `SCRIPT_DATE` set to **11.08.2026**. `/afterwork` scans for a mismatch between the two.
- **Commit prefixes:** `[ADD]` new features, `[CHG]` modifications, `[FIX]` bug fixes.
- **Tests:** stdlib `unittest` in `tests/`, run with `python3 -m unittest discover -s tests`. The suite is at 159 tests before this plan; every task adds to it.
- **Never `logger.level`** — it is `NOTSET` under `basicConfig`. Always `logger.getEffectiveLevel()`.

---

### Task 1: Run history — read, write, retention

**Files:**
- Modify: `scripts/update_docker_odoo.py` (add the history block after the run-log block, around line 250)
- Test: `tests/test_update_history.py` (create)

**Interfaces:**
- Consumes: nothing
- Produces: `HISTORY_FILE`, `HISTORY_TS_FORMAT`, `DEFAULT_HISTORY_RETENTION_DAYS`, `resolve_history_retention(config) -> float`, `read_history(path=None, limit=None) -> list[dict]` (newest first), `write_history(entry, path=None, retention_days=DEFAULT_HISTORY_RETENTION_DAYS) -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_update_history.py`:

```python
"""
Tests for the run history of update_docker_odoo.py.

Standard library only, like the rest of the suite. PyYAML is imported at module
level by the script but no function under test touches it, so a placeholder
module stands in when it is absent.

Run from the repository root:

    python3 -m unittest tests.test_update_history -v
"""

import json
import os
import sys
import tempfile
import time
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
try:
    import yaml  # noqa: F401
except ImportError:
    sys.modules["yaml"] = types.ModuleType("yaml")
import update_docker_odoo as udo  # noqa: E402


def entry(container="live-odoo", ts=None, **extra):
    data = {
        "ts": ts or time.strftime(udo.HISTORY_TS_FORMAT),
        "container": container,
        "mode": "F",
        "result": "ok",
    }
    data.update(extra)
    return data


def stamp(days_ago):
    return time.strftime(udo.HISTORY_TS_FORMAT,
                         time.localtime(time.time() - days_ago * 86400))


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "update-history.jsonl")

    def read_raw(self):
        with open(self.path, encoding="utf8") as handle:
            return handle.read()

    def test_an_entry_is_written_as_one_json_line(self):
        udo.write_history(entry(), path=self.path)

        lines = self.read_raw().strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["container"], "live-odoo")

    def test_entries_come_back_newest_first(self):
        udo.write_history(entry("first"), path=self.path)
        udo.write_history(entry("second"), path=self.path)

        names = [item["container"] for item in udo.read_history(self.path)]
        self.assertEqual(names, ["second", "first"])

    def test_limit_returns_only_the_newest(self):
        for name in ("a", "b", "c"):
            udo.write_history(entry(name), path=self.path)

        self.assertEqual([i["container"] for i in udo.read_history(self.path, limit=2)],
                         ["c", "b"])

    def test_a_malformed_line_is_skipped_not_fatal(self):
        udo.write_history(entry("good"), path=self.path)
        with open(self.path, "a", encoding="utf8") as handle:
            handle.write("{ this is not json\n")

        self.assertEqual([i["container"] for i in udo.read_history(self.path)], ["good"])

    def test_a_missing_file_reads_as_empty(self):
        self.assertEqual(udo.read_history(self.path), [])

    def test_expired_entries_are_pruned_on_write(self):
        udo.write_history(entry("old", ts=stamp(400)), path=self.path, retention_days=365)
        udo.write_history(entry("new"), path=self.path, retention_days=365)

        self.assertEqual([i["container"] for i in udo.read_history(self.path)], ["new"])

    def test_retention_zero_keeps_everything(self):
        udo.write_history(entry("ancient", ts=stamp(5000)), path=self.path, retention_days=0)
        udo.write_history(entry("new"), path=self.path, retention_days=0)

        self.assertEqual(len(udo.read_history(self.path)), 2)

    def test_an_undatable_entry_is_never_pruned(self):
        udo.write_history(entry("weird", ts="not-a-date"), path=self.path, retention_days=1)
        udo.write_history(entry("new"), path=self.path, retention_days=1)

        self.assertEqual(len(udo.read_history(self.path)), 2)

    def test_an_unwritable_path_costs_the_history_not_an_exception(self):
        unwritable = "/proc/definitely/not/writable/history.jsonl"
        udo.write_history(entry(), path=unwritable)   # must not raise
        self.assertEqual(udo.read_history(unwritable), [])

    def test_no_temp_file_is_left_behind(self):
        udo.write_history(entry(), path=self.path)

        self.assertFalse(os.path.exists(f"{self.path}.tmp"))


class HistoryRetentionResolutionTest(unittest.TestCase):
    def test_the_default_applies_without_configuration(self):
        self.assertEqual(udo.resolve_history_retention({}),
                         udo.DEFAULT_HISTORY_RETENTION_DAYS)

    def test_the_defaults_block_wins(self):
        config = {"defaults": {"history_retention_days": 30}}
        self.assertEqual(udo.resolve_history_retention(config), 30)

    def test_zero_is_kept_as_zero_not_read_as_unset(self):
        config = {"defaults": {"history_retention_days": 0}}
        self.assertEqual(udo.resolve_history_retention(config), 0)

    def test_an_empty_value_reads_as_unset(self):
        config = {"defaults": {"history_retention_days": ""}}
        self.assertEqual(udo.resolve_history_retention(config),
                         udo.DEFAULT_HISTORY_RETENTION_DAYS)

    def test_an_unusable_value_falls_back_to_the_default(self):
        config = {"defaults": {"history_retention_days": "yes please"}}
        self.assertEqual(udo.resolve_history_retention(config),
                         udo.DEFAULT_HISTORY_RETENTION_DAYS)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_update_history -v`
Expected: FAIL — `AttributeError: module 'update_docker_odoo' has no attribute 'HISTORY_TS_FORMAT'`

- [ ] **Step 3: Add `json` to the imports**

In `scripts/update_docker_odoo.py`, the import block at the top (line 25-36) is alphabetically loose; add `json` next to `atexit`:

```python
import os
import re
import sys
import time
import yaml
import json
import atexit
import shutil
```

- [ ] **Step 4: Write the history block**

Insert after the run-log section (after `prune_run_logs`/`open_run_log` and before `def load_config`, around line 250 — anywhere in that region is fine as long as it is above its first use):

```python
##############################################################################
# Run history
#
# One JSON line per container run, in the operator's home rather than in a
# build folder: the point of this file is the view across all instances, which
# is exactly what a per-instance log cannot give. Written by the runner and not
# by its callers, so runs started classically or from cron are recorded too.
#
# It is a convenience, never a precondition. Every function here swallows its
# own I/O errors - a history that cannot be written costs a log line, not an
# update.
##############################################################################

HISTORY_FILE = join(expanduser("~"), "update-history.jsonl")

HISTORY_TS_FORMAT = "%Y-%m-%dT%H:%M:%S"

# How long an entry is kept, in days. Override with
# 'defaults.history_retention_days' in docker2update.yaml. 0 keeps everything.
DEFAULT_HISTORY_RETENTION_DAYS = 365


def resolve_history_retention(config):
    """Days to keep history entries: defaults block, else built-in.

    An unusable value falls back to the default rather than raising, the same
    way resolve_log_retention() treats one: a typo in the YAML must not be able
    to stop an update, and refusing to delete is the safe direction.
    """
    defaults = (config or {}).get('defaults') or {}
    value = defaults.get('history_retention_days')
    # Present but empty reads as 'not configured'. 0 does NOT - it is the
    # explicit 'never delete'.
    if value is None or value == "":
        return DEFAULT_HISTORY_RETENTION_DAYS
    try:
        days = float(value)
    except (TypeError, ValueError):
        logger.warning(f"Ignoring unusable history_retention_days: {value!r}")
        return DEFAULT_HISTORY_RETENTION_DAYS
    return max(0, days)


def read_history(path=None, limit=None):
    """Return history entries, newest first.

    A line that cannot be parsed is skipped rather than reported: the only way
    one gets there is a write cut short by a crash, and the reader's job is to
    survive that, not to explain it.
    """
    entries = []
    try:
        with open(path or HISTORY_FILE, encoding="utf8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    entries.reverse()
    return entries[:limit] if limit else entries


def write_history(entry, path=None, retention_days=DEFAULT_HISTORY_RETENTION_DAYS):
    """Append one entry, dropping what has expired. Never raises.

    The file is rewritten through a temp file and os.replace() so a crash
    mid-write cannot leave a truncated history behind - the old file stays
    intact until the new one is complete.
    """
    path = path or HISTORY_FILE
    try:
        cutoff = (time.time() - retention_days * 86400) if retention_days else None
        kept = []
        try:
            with open(path, encoding="utf8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    if cutoff is None:
                        kept.append(line)
                        continue
                    try:
                        written = time.mktime(time.strptime(
                            json.loads(line).get("ts", ""), HISTORY_TS_FORMAT))
                    except (ValueError, TypeError, AttributeError):
                        # An entry we cannot date is not ours to delete.
                        kept.append(line)
                        continue
                    if written >= cutoff:
                        kept.append(line)
        except OSError:
            pass  # no history yet, or unreadable - either way, start fresh

        kept.append(json.dumps(entry, ensure_ascii=False, sort_keys=True))
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf8") as handle:
            handle.write("\n".join(kept) + "\n")
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning(f"Could not write run history: {exc}")
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python3 -m unittest tests.test_update_history -v`
Expected: PASS

- [ ] **Step 6: Run the whole suite**

Run: `python3 -m unittest discover -s tests`
Expected: OK - the suite stood at 159 before this plan and grows with every task

- [ ] **Step 7: Commit**

```bash
git add scripts/update_docker_odoo.py tests/test_update_history.py
git commit -m "[ADD] update_docker_odoo.py: run history in ~/update-history.jsonl

One JSON line per container run, written atomically, pruned by
defaults.history_retention_days (365 default, 0 keeps everything). A history
that cannot be written costs a log line, never an update."
```

---

### Task 2: Runner flags — repeatable `-s`, `--type`, `--comment`

**Files:**
- Modify: `scripts/update_docker_odoo.py` — `parse_arguments()` (around line 740), the container loop in `main()` (around line 1869)
- Test: `tests/test_update_docker_odoo.py` (extend)

**Interfaces:**
- Consumes: nothing from Task 1
- Produces: `selected_container_names(args) -> list[str]`, `container_matches_selection(container, selected) -> bool`, argparse attributes `args.specific_container` (list or None), `args.update_type` (`"M"`/`"F"`/`"N"` or None), `args.comment` (str or None)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_update_docker_odoo.py` (the file already has the `sys.path` and yaml-placeholder preamble):

```python
class SelectionTest(unittest.TestCase):
    """The -s flag: repeatable, comma-separated, and stronger than 'active'."""

    def parse(self, argv):
        original = sys.argv
        sys.argv = ["update_docker_odoo.py"] + argv
        try:
            return udo.parse_arguments()
        finally:
            sys.argv = original

    def test_a_single_name_still_works(self):
        args = self.parse(["-s", "live-odoo"])
        self.assertEqual(udo.selected_container_names(args), ["live-odoo"])

    def test_the_flag_can_be_repeated(self):
        args = self.parse(["-s", "live-odoo", "-s", "test-odoo"])
        self.assertEqual(udo.selected_container_names(args),
                         ["live-odoo", "test-odoo"])

    def test_a_comma_separated_list_is_split(self):
        args = self.parse(["-s", "live-odoo,test-odoo"])
        self.assertEqual(udo.selected_container_names(args),
                         ["live-odoo", "test-odoo"])

    def test_whitespace_and_empty_parts_are_dropped(self):
        args = self.parse(["-s", " live-odoo , , test-odoo "])
        self.assertEqual(udo.selected_container_names(args),
                         ["live-odoo", "test-odoo"])

    def test_without_the_flag_the_selection_is_empty(self):
        self.assertEqual(udo.selected_container_names(self.parse([])), [])

    def test_a_named_container_runs_even_when_inactive(self):
        container = {"container_name": "parked-odoo", "active": False}
        self.assertTrue(udo.container_matches_selection(container, ["parked-odoo"]))

    def test_an_unnamed_container_is_skipped_when_a_selection_exists(self):
        container = {"container_name": "other-odoo", "active": True}
        self.assertFalse(udo.container_matches_selection(container, ["parked-odoo"]))

    def test_without_a_selection_active_decides(self):
        self.assertTrue(udo.container_matches_selection(
            {"container_name": "a", "active": True}, []))
        self.assertFalse(udo.container_matches_selection(
            {"container_name": "b", "active": False}, []))

    def test_a_container_without_an_active_key_takes_part(self):
        self.assertTrue(udo.container_matches_selection({"container_name": "a"}, []))


class RuntimeOverrideTest(unittest.TestCase):
    def parse(self, argv):
        original = sys.argv
        sys.argv = ["update_docker_odoo.py"] + argv
        try:
            return udo.parse_arguments()
        finally:
            sys.argv = original

    def test_the_type_override_is_parsed(self):
        self.assertEqual(self.parse(["--type", "F"]).update_type, "F")

    def test_an_invalid_type_is_rejected(self):
        with self.assertRaises(SystemExit):
            self.parse(["--type", "X"])

    def test_the_comment_is_parsed(self):
        self.assertEqual(self.parse(["--comment", "eq_stock"]).comment, "eq_stock")

    def test_both_default_to_none(self):
        args = self.parse([])
        self.assertIsNone(args.update_type)
        self.assertIsNone(args.comment)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_update_docker_odoo -v`
Expected: FAIL — `AttributeError: module 'update_docker_odoo' has no attribute 'selected_container_names'`

- [ ] **Step 3: Change the `-s` argument and add the two new ones**

In `parse_arguments()`, replace the existing `-s` block:

```python
    parser.add_argument('-s', '--specific-container', action='append', metavar='NAME',
                        help='Update only the named container. Repeatable, and '
                             'accepts a comma-separated list. A named container '
                             'runs even when its "active" is false.')

    parser.add_argument('--type', dest='update_type', choices=['M', 'F', 'N'],
                        help="Runtime override of the container's 'type' for this "
                             "run. The YAML file is not modified.")

    parser.add_argument('--comment', metavar='TEXT',
                        help='Recorded in the run log header and the run history')
```

Add three lines to the `Examples:` block of the epilog, under the existing `-s` example:

```
  python3 update_docker_odoo.py -s live-odoo,test-odoo  # Update several containers
  python3 update_docker_odoo.py -s live-odoo --type F   # Override the YAML 'type' once
  python3 update_docker_odoo.py -s live-odoo --comment "eq_stock"   # Note it in the log/history
```

- [ ] **Step 4: Add the two selection helpers**

Put them directly above `parse_arguments()`:

```python
def selected_container_names(args):
    """Flatten -s into a list of names; empty when the flag was not given.

    Both spellings are accepted because both are natural: repeating the flag is
    what a script does, a comma-separated list is what a person types.
    """
    names = []
    for value in (getattr(args, 'specific_container', None) or []):
        names.extend(part.strip() for part in str(value).split(',') if part.strip())
    return names


def container_matches_selection(container, selected):
    """Whether this container takes part in the run.

    An explicit selection wins over 'active'. Naming a container is a deliberate
    act; skipping it because the YAML has it parked is the opposite of what was
    asked - and from the TUI, where the operator just ticked it, it would look
    like the tool ignored the click.
    """
    if selected:
        return container.get('container_name') in selected
    return bool(container.get('active', True))
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python3 -m unittest tests.test_update_docker_odoo -v`
Expected: PASS

- [ ] **Step 6: Wire the helpers into the container loop**

In `main()`, above the `for container in config['containers']:` loop, insert the unknown-name check:

```python
    # An unknown name is an error, not a silent no-op: a typo in `-s` would
    # otherwise look exactly like a successful run that updated nothing.
    selected = selected_container_names(args)
    known = [c.get('container_name') for c in config['containers']]
    unknown = [name for name in selected if name not in known]
    if unknown:
        logger.error(f"Unknown container(s) in --specific-container: {', '.join(unknown)}")
        logger.error(f"Known containers: {', '.join(n for n in known if n)}")
        return 1
```

Then replace the two skip blocks at the top of the loop:

```python
    for container in config['containers']:
        container_name = container.get('container_name', 'unknown')

        if not container_matches_selection(container, selected):
            if selected:
                logger.info(f"Skipping container {container_name} (not selected)")
            else:
                logger.info(f"Skipping inactive container: {container_name}")
            continue

        # A copy, so the override cannot reach the structure that
        # save_updated_config() writes back.
        if args.update_type:
            container = dict(container, type=args.update_type)
```

- [ ] **Step 7: Verify the whole suite still passes**

Run: `python3 -m unittest discover -s tests`
Expected: OK, more tests than the previous task left behind

- [ ] **Step 8: Verify by hand that a parked container now runs when named**

```bash
python3 - <<'PY'
import sys, types, tempfile, os
sys.path.insert(0, "scripts")
sys.modules.setdefault("yaml", types.ModuleType("yaml"))
import update_docker_odoo as udo
parked = {"container_name": "parked-odoo", "active": False}
print("named   ->", udo.container_matches_selection(parked, ["parked-odoo"]))
print("unnamed ->", udo.container_matches_selection(parked, []))
PY
```
Expected: `named   -> True`, `unnamed -> False`

- [ ] **Step 9: Commit**

```bash
git add scripts/update_docker_odoo.py tests/test_update_docker_odoo.py
git commit -m "[CHG] update_docker_odoo.py: -s repeatable, --type and --comment

-s now takes several names (repeated or comma-separated) and overrides
'active: false' - naming a container is a deliberate act, and skipping it
because the YAML has it parked is the opposite of what was asked. An unknown
name is an error instead of a run that silently updates nothing.

--type overrides the YAML 'type' for one run, --comment is recorded with it.
Neither touches the file."
```

---

### Task 3: Record every run — comment in the log header, entry in the history

**Files:**
- Modify: `scripts/update_docker_odoo.py` — `process_container()`/`_process_container()` signature (line 1324/1339), the `open_run_log()` call (line 1404), the loop body in `main()`, version header
- Test: `tests/test_update_docker_odoo.py` (extend)

**Interfaces:**
- Consumes: `write_history`, `resolve_history_retention`, `HISTORY_TS_FORMAT` (Task 1); `selected_container_names` (Task 2)
- Produces: `history_entry(container, comment, success, warnings, errors, duration, log_path) -> dict`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_update_docker_odoo.py`:

```python
class HistoryEntryTest(unittest.TestCase):
    """The mapping from a finished container run to its history line."""

    CONTAINER = {"container_name": "live-odoo", "database_name": "live_db", "type": "F"}

    def entry(self, **kwargs):
        params = dict(container=self.CONTAINER, comment="eq_stock nachgezogen",
                      success=True, warnings=0, errors=0, duration=812.4,
                      log_path="/opt/odoo/live/update_20260811_143207.log")
        params.update(kwargs)
        return udo.history_entry(**params)

    def test_a_clean_run_is_ok(self):
        self.assertEqual(self.entry()["result"], "ok")

    def test_warnings_are_reported_as_such(self):
        self.assertEqual(self.entry(warnings=3)["result"], "warnings")

    def test_errors_outrank_warnings(self):
        self.assertEqual(self.entry(warnings=3, errors=1)["result"], "errors")

    def test_a_failed_run_is_failed_regardless_of_counts(self):
        self.assertEqual(self.entry(success=False, errors=0)["result"], "failed")

    def test_the_fields_the_tui_reads_are_present(self):
        item = self.entry()
        self.assertEqual(item["container"], "live-odoo")
        self.assertEqual(item["database"], "live_db")
        self.assertEqual(item["mode"], "F")
        self.assertEqual(item["comment"], "eq_stock nachgezogen")
        self.assertEqual(item["duration_s"], 812)
        self.assertEqual(item["script_version"], udo.SCRIPT_VERSION)
        self.assertEqual(item["log"], "/opt/odoo/live/update_20260811_143207.log")

    def test_the_timestamp_round_trips_through_the_history_format(self):
        import time as _time
        _time.strptime(self.entry()["ts"], udo.HISTORY_TS_FORMAT)

    def test_a_missing_comment_becomes_an_empty_string(self):
        # json.dumps of None would be 'null' and every reader would need a
        # special case; the empty string is what "no comment" means here.
        self.assertEqual(self.entry(comment=None)["comment"], "")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_update_docker_odoo -v`
Expected: FAIL — `AttributeError: module 'update_docker_odoo' has no attribute 'history_entry'`

- [ ] **Step 3: Add `history_entry()` next to the other history functions**

```python
def history_entry(container, comment, success, warnings, errors, duration, log_path):
    """Build the history line for one finished container run.

    Kept apart from write_history() so the classification - which is the only
    judgement in the whole file - can be asserted without touching the disk.
    """
    if not success:
        result = "failed"
    elif errors:
        result = "errors"
    elif warnings:
        result = "warnings"
    else:
        result = "ok"
    return {
        "ts": time.strftime(HISTORY_TS_FORMAT),
        "container": container.get('container_name', 'unknown'),
        "database": container.get('database_name', ''),
        "mode": container.get('type', ''),
        "comment": comment or "",
        "result": result,
        "warnings": warnings,
        "errors": errors,
        "duration_s": int(duration),
        "log": log_path or "",
        "script_version": SCRIPT_VERSION,
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest tests.test_update_docker_odoo -v`
Expected: PASS

- [ ] **Step 5: Pass the comment into the run log header**

Change both signatures (line 1324 and 1339) to take the comment:

```python
def process_container(container, proxy_settings=None, dockerfiles_source=None,
                      log_retention_days=None, run_comment=None):
```

```python
def _process_container(container, proxy_settings=None, dockerfiles_source=None,
                       log_retention_days=None, run_comment=None):
```

and forward it in the wrapper's call:

```python
        return _process_container(container, proxy_settings, dockerfiles_source,
                                  log_retention_days, run_comment)
```

Then extend the `open_run_log()` call (line 1404) so the comment stands in the header, where whoever opens the log a month later reads why the run happened:

```python
    open_run_log(path, container_name,
                 header_lines=[f"image:     {image}", f"path:      {path}"]
                 + ([f"volume:    {volume}"] if volume else [])
                 + ([f"comment:   {run_comment}"] if run_comment else []),
                 retention_days=(DEFAULT_LOG_RETENTION_DAYS
                                 if log_retention_days is None
                                 else log_retention_days))
```

- [ ] **Step 6: Record the run in `main()`**

Resolve the retention once, above the container loop:

```python
    history_retention = resolve_history_retention(config)
```

Then replace the body of the `try:` in the loop so it times the run, remembers which log belongs to it, and records the outcome on both paths:

```python
        try:
            # First statement in the try, so the except branch below can always
            # read it: an exception from expand_path() would otherwise leave it
            # holding the previous container's start time - or nothing at all on
            # the first iteration.
            container_started = time.time()
            defaults = config.get('defaults') or {}
            dockerfiles_source = expand_path(
                defaults.get('dockerfiles_source') or DEFAULT_DOCKERFILES_SOURCE)
            # The log path is read by index rather than from the return value:
            # open_run_log() may fail (unwritable folder) and then RUN_LOG_FILES
            # still holds the *previous* container's log, which would be a lie.
            logs_before = len(RUN_LOG_FILES)
            result = process_container(container, resolve_proxy_settings(config, container),
                                       dockerfiles_source,
                                       resolve_log_retention(config, container),
                                       args.comment)
            warning_count = error_count = 0
            if isinstance(result, tuple):
                success, info_count, warning_count, error_count = result
                total_info_count += info_count
                total_warning_count += warning_count
                total_error_count += error_count
            else:
                success = result

            write_history(history_entry(
                container, args.comment, bool(success), warning_count, error_count,
                time.time() - container_started,
                RUN_LOG_FILES[-1] if len(RUN_LOG_FILES) > logs_before else ""),
                retention_days=history_retention)

            if success:
                success_count += 1
            else:
                failure_count += 1
        except Exception as e:
            logger.error(f"Exception processing container {container_name}: {e}")
            failure_count += 1
            total_error_count += 1
            write_history(history_entry(
                container, args.comment, False, 0, 1,
                time.time() - container_started, ""),
                retention_days=history_retention)
```

Note the loop already binds `container_name` as of Task 2, so the `container.get(...)` in the exception message is replaced by it.

- [ ] **Step 7: Bump the version header**

Both places, and they must agree — `/afterwork` scans for a mismatch:

```python
# Version 5.11.0
# Date 11.08.2026
```

```python
SCRIPT_VERSION = "5.11.0"
SCRIPT_DATE = "11.08.2026"
```

- [ ] **Step 8: Document the new key in the config template**

In `scripts/docker2update.yaml`, extend the commented `defaults` block, right under `log_retention_days`:

```yaml
#  # Days to keep entries in ~/update-history.jsonl (0 = keep forever). The
#  # history holds one line per container run - what ran when, in which mode,
#  # with which result and comment - and is what the TUI shows while you pick.
#  history_retention_days: 365
```

- [ ] **Step 9: Run the whole suite**

Run: `python3 -m unittest discover -s tests`
Expected: OK, more tests than the previous task left behind

- [ ] **Step 10: Commit**

```bash
git add scripts/update_docker_odoo.py scripts/docker2update.yaml tests/test_update_docker_odoo.py
git commit -m "[ADD] update_docker_odoo.py v5.11.0: every run is recorded

Each container run appends a line to ~/update-history.jsonl - what ran when,
in which mode, with which result, duration, log path and comment. --comment
also lands in the run log header, where whoever opens that log a month later
reads why the run happened.

Written by the runner, so classic and cron runs are recorded as well - which
is the whole point of a central file."
```

---

### Task 4: `UpdateSelection` — the TUI's state, without curses

**Files:**
- Create: `scripts/ownerp_tui.py`
- Test: `tests/test_ownerp_tui.py`

**Interfaces:**
- Consumes: the history format from Task 1 (`read_history` entries), the flag contract from Task 2 (`-s`, `--type`, `--comment`)
- Produces: `MODES`, `UpdateSelection(containers)` with `.rows`, `.comment`, `.cursor`, `.move(delta)`, `.toggle(index=None)`, `.toggle_all()`, `.rotate_mode(index=None)`, `.selected_rows`, `.can_start()`, `.needs_extra_confirmation()`, `.runner_invocations(script) -> list[list[str]]`; `last_run_by_container(entries) -> dict`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ownerp_tui.py`:

```python
"""
Tests for the selection state of ownerp_tui.py.

The curses drawing layer is deliberately not tested - it is kept thin enough
that there is nothing in it to assert. Everything worth asserting lives in
UpdateSelection, which never touches a terminal.

Run from the repository root:

    python3 -m unittest tests.test_ownerp_tui -v
"""

import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
# The stub goes in BEFORE the import below: importing ownerp_tui pulls in
# update_docker_odoo, which imports yaml at module level while none of the
# functions under test touch it. Same convention as the sibling test files.
try:
    import yaml  # noqa: F401
except ImportError:
    sys.modules["yaml"] = types.ModuleType("yaml")
import ownerp_tui as tui  # noqa: E402

CONTAINERS = [
    {"container_name": "live-odoo", "database_name": "live_db",
     "odoo_version": "18", "type": "F", "active": True},
    {"container_name": "test-odoo", "database_name": "test_db",
     "odoo_version": "18", "type": "M", "active": False},
    {"container_name": "demo-odoo", "database_name": "demo_db",
     "odoo_version": "16", "type": "N", "active": False},
]


class PreselectionTest(unittest.TestCase):
    def test_active_containers_start_selected(self):
        selection = tui.UpdateSelection(CONTAINERS)
        self.assertEqual([row["selected"] for row in selection.rows],
                         [True, False, False])

    def test_the_mode_comes_from_the_yaml_type(self):
        selection = tui.UpdateSelection(CONTAINERS)
        self.assertEqual([row["mode"] for row in selection.rows], ["F", "M", "N"])

    def test_a_missing_active_key_counts_as_active(self):
        selection = tui.UpdateSelection([{"container_name": "a", "type": "F"}])
        self.assertTrue(selection.rows[0]["selected"])

    def test_an_unusable_type_falls_back_to_full(self):
        selection = tui.UpdateSelection([{"container_name": "a", "type": "X"}])
        self.assertEqual(selection.rows[0]["mode"], "F")

    def test_a_lowercase_type_is_accepted(self):
        selection = tui.UpdateSelection([{"container_name": "a", "type": "m"}])
        self.assertEqual(selection.rows[0]["mode"], "M")


class NavigationTest(unittest.TestCase):
    def setUp(self):
        self.selection = tui.UpdateSelection(CONTAINERS)

    def test_the_cursor_stops_at_the_top(self):
        self.selection.move(-5)
        self.assertEqual(self.selection.cursor, 0)

    def test_the_cursor_stops_at_the_bottom(self):
        self.selection.move(99)
        self.assertEqual(self.selection.cursor, len(CONTAINERS) - 1)

    def test_moving_an_empty_list_leaves_the_cursor_alone(self):
        selection = tui.UpdateSelection([])
        selection.move(1)                             # must not raise
        self.assertEqual(selection.cursor, 0)


class SelectionTest(unittest.TestCase):
    def setUp(self):
        self.selection = tui.UpdateSelection(CONTAINERS)

    def test_toggling_flips_the_row_under_the_cursor(self):
        self.selection.toggle()
        self.assertFalse(self.selection.rows[0]["selected"])

    def test_toggle_all_selects_everything_when_some_are_unselected(self):
        self.selection.toggle_all()
        self.assertTrue(all(row["selected"] for row in self.selection.rows))

    def test_toggle_all_clears_when_everything_is_selected(self):
        self.selection.toggle_all()
        self.selection.toggle_all()
        self.assertFalse(any(row["selected"] for row in self.selection.rows))

    def test_the_mode_rotates_m_f_n_and_wraps(self):
        self.selection.cursor = 1              # starts at M
        for expected in ("F", "N", "M"):
            self.selection.rotate_mode()
            self.assertEqual(self.selection.rows[1]["mode"], expected)

    def test_an_empty_selection_cannot_start(self):
        self.selection.toggle()                # unselect the only active row
        self.assertFalse(self.selection.can_start())

    def test_a_selection_can_start(self):
        self.assertTrue(self.selection.can_start())


class ConfirmationTest(unittest.TestCase):
    def test_a_neutralize_in_the_selection_needs_extra_confirmation(self):
        selection = tui.UpdateSelection(CONTAINERS)
        selection.cursor = 2                   # demo-odoo, mode N
        selection.toggle()
        self.assertTrue(selection.needs_extra_confirmation())

    def test_an_unselected_neutralize_does_not(self):
        # demo-odoo is mode N but inactive, so it is not part of the run.
        self.assertFalse(tui.UpdateSelection(CONTAINERS).needs_extra_confirmation())


class RunnerInvocationTest(unittest.TestCase):
    SCRIPT = "/root/update_docker_odoo.py"

    def test_one_mode_produces_exactly_one_invocation(self):
        selection = tui.UpdateSelection(CONTAINERS)
        self.assertEqual(selection.runner_invocations(self.SCRIPT),
                         [[self.SCRIPT, "-s", "live-odoo", "--type", "F"]])

    def test_containers_of_the_same_mode_share_one_invocation(self):
        selection = tui.UpdateSelection(CONTAINERS)
        selection.rows[2]["mode"] = "F"
        selection.rows[2]["selected"] = True
        self.assertEqual(selection.runner_invocations(self.SCRIPT),
                         [[self.SCRIPT, "-s", "live-odoo,demo-odoo", "--type", "F"]])

    def test_mixed_modes_produce_one_invocation_per_mode(self):
        selection = tui.UpdateSelection(CONTAINERS)
        selection.rows[1]["selected"] = True
        self.assertEqual(selection.runner_invocations(self.SCRIPT), [
            [self.SCRIPT, "-s", "live-odoo", "--type", "F"],
            [self.SCRIPT, "-s", "test-odoo", "--type", "M"],
        ])

    def test_the_groups_keep_the_order_of_the_list(self):
        selection = tui.UpdateSelection(CONTAINERS)
        selection.rows[0]["selected"] = False
        selection.rows[1]["selected"] = True
        selection.rows[2]["selected"] = True
        self.assertEqual([argv[4] for argv in selection.runner_invocations(self.SCRIPT)],
                         ["M", "N"])

    def test_the_comment_is_appended_to_every_invocation(self):
        selection = tui.UpdateSelection(CONTAINERS)
        selection.rows[1]["selected"] = True
        selection.comment = "eq_stock nachgezogen"
        for argv in selection.runner_invocations(self.SCRIPT):
            self.assertEqual(argv[-2:], ["--comment", "eq_stock nachgezogen"])

    def test_an_empty_comment_adds_no_flag(self):
        argv = tui.UpdateSelection(CONTAINERS).runner_invocations(self.SCRIPT)[0]
        self.assertNotIn("--comment", argv)

    def test_an_empty_selection_produces_no_invocation(self):
        selection = tui.UpdateSelection(CONTAINERS)
        selection.rows[0]["selected"] = False
        self.assertEqual(selection.runner_invocations(self.SCRIPT), [])


class LastRunTest(unittest.TestCase):
    ENTRIES = [                                 # newest first, as read_history returns
        {"ts": "2026-08-03T10:00:00", "container": "live-odoo", "mode": "F",
         "result": "ok", "comment": "eq_stock"},
        {"ts": "2026-07-28T10:00:00", "container": "live-odoo", "mode": "M",
         "result": "errors", "comment": ""},
        {"ts": "2026-07-28T09:00:00", "container": "test-odoo", "mode": "M",
         "result": "ok", "comment": ""},
    ]

    def test_only_the_newest_entry_per_container_is_kept(self):
        latest = tui.last_run_by_container(self.ENTRIES)
        self.assertEqual(latest["live-odoo"]["ts"], "2026-08-03T10:00:00")

    def test_every_container_in_the_history_appears(self):
        self.assertEqual(set(tui.last_run_by_container(self.ENTRIES)),
                         {"live-odoo", "test-odoo"})

    def test_an_empty_history_maps_to_nothing(self):
        self.assertEqual(tui.last_run_by_container([]), {})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_ownerp_tui -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ownerp_tui'`

- [ ] **Step 3: Create the script with its state model**

Create `scripts/ownerp_tui.py` (executable, `chmod +x`):

```python
#!/usr/bin/python3
# -*- coding: utf-8 -*-
# Terminal UI for selecting Odoo container updates
# Version 1.0.0
# Date 11.08.2026
##############################################################################
#
#    Shell Script for Odoo, Open Source Management Solution
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
#
##############################################################################
"""Pick the systems for an ad-hoc update, then hand the work to the runner.

This script decides nothing about updating and executes nothing itself. It
selects - which systems, in which mode, with which comment - and then leaves
curses and starts update_docker_odoo.py as a subprocess. The runner keeps its
logging, its run log and its exit code; wrapping a twenty-minute build in a
curses window would mean rebuilding all of that inside a pad nobody can scroll.

It never writes to docker2update.yaml. `active:` and `type:` are read as the
pre-selection and nothing else - that is what makes it safe to change them for
one run.
"""

SCRIPT_VERSION = "1.0.0"
SCRIPT_DATE = "11.08.2026"

# The update modes, in the order the 'm' key rotates them.
MODES = ("M", "F", "N")

MODE_LABELS = {
    "M": "Module copy",
    "F": "Full update",
    "N": "Neutralize and update",
}


def last_run_by_container(entries):
    """Map container name -> its newest history entry.

    Takes the list read_history() returns (newest first), so the first entry
    seen for a name is the one to keep.
    """
    latest = {}
    for item in entries:
        name = item.get("container")
        if name and name not in latest:
            latest[name] = item
    return latest


class UpdateSelection:
    """What the operator has picked: systems, modes, and one comment.

    Deliberately free of curses. Everything worth asserting lives here, which
    keeps the drawing code thin enough that there is nothing in it to test.
    """

    def __init__(self, containers):
        self.rows = []
        for container in containers:
            mode = str(container.get('type', 'F') or 'F').upper()
            self.rows.append({
                "name": container.get('container_name', 'unknown'),
                "database": container.get('database_name', ''),
                "version": str(container.get('odoo_version', '') or ''),
                # An unusable type falls back to F rather than refusing to
                # start: the operator can see and change the mode on screen.
                "mode": mode if mode in MODES else "F",
                "selected": bool(container.get('active', True)),
            })
        self.comment = ""
        self.cursor = 0

    # -- navigation and selection -----------------------------------------

    def move(self, delta):
        if self.rows:
            self.cursor = max(0, min(len(self.rows) - 1, self.cursor + delta))

    def toggle(self, index=None):
        if self.rows:
            row = self.rows[self.cursor if index is None else index]
            row["selected"] = not row["selected"]

    def toggle_all(self):
        """Select everything - or clear it, when everything already is."""
        target = not all(row["selected"] for row in self.rows) if self.rows else False
        for row in self.rows:
            row["selected"] = target

    def rotate_mode(self, index=None):
        if self.rows:
            row = self.rows[self.cursor if index is None else index]
            row["mode"] = MODES[(MODES.index(row["mode"]) + 1) % len(MODES)]

    # -- what the runner is asked to do -----------------------------------

    @property
    def selected_rows(self):
        return [row for row in self.rows if row["selected"]]

    def can_start(self):
        return bool(self.selected_rows)

    def needs_extra_confirmation(self):
        """True when the run neutralizes a database.

        Neutralizing is destructive - it rewrites mail servers, cron and
        outgoing interfaces - and must never be one keystroke away from a typo.
        """
        return any(row["mode"] == "N" for row in self.selected_rows)

    def runner_invocations(self, script):
        """One argument list per mode group, in the order of the list.

        --type applies to a whole invocation, so a selection with mixed modes
        becomes several runs. Grouping here rather than inventing a
        per-container flag syntax keeps -s the same thing an operator types by
        hand.
        """
        groups = []                        # [(mode, [names])], first appearance wins
        for row in self.selected_rows:
            for mode, names in groups:
                if mode == row["mode"]:
                    names.append(row["name"])
                    break
            else:
                groups.append((row["mode"], [row["name"]]))

        invocations = []
        for mode, names in groups:
            argv = [script, "-s", ",".join(names), "--type", mode]
            if self.comment:
                argv += ["--comment", self.comment]
            invocations.append(argv)
        return invocations
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest tests.test_ownerp_tui -v`
Expected: PASS

- [ ] **Step 5: Run the whole suite**

Run: `python3 -m unittest discover -s tests`
Expected: OK, more tests than the previous task left behind

- [ ] **Step 6: Commit**

```bash
chmod +x scripts/ownerp_tui.py
git add scripts/ownerp_tui.py tests/test_ownerp_tui.py
git commit -m "[ADD] ownerp_tui.py v1.0.0: the selection state, without curses

UpdateSelection holds what the operator picked - systems, per-row mode, one
comment - and turns it into runner argument lists, grouped by mode because
--type applies per invocation. No curses call in any of it, which is what
makes it testable and keeps the drawing code that follows thin.

A selection containing a Neutralize is flagged as needing a second
confirmation: it is destructive and must not be one keystroke from a typo."
```

---

### Task 5: The curses frontend

**Files:**
- Modify: `scripts/ownerp_tui.py` (append to the file from Task 4)
- Test: `tests/test_ownerp_tui.py` (extend — only the parts that do not draw)

**Interfaces:**
- Consumes: `UpdateSelection`, `last_run_by_container`, `MODES`, `MODE_LABELS` (Task 4); `read_history` (Task 1) imported from the runner
- Produces: `preflight() -> str|None` (a refusal reason, or None), `format_last_run(entry) -> str`, `TUI_DEFAULT_MARKER`, `tui_is_default() -> bool`, `set_tui_default(enabled) -> None`, `main(argv=None) -> int`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ownerp_tui.py`:

```python
class PreflightTest(unittest.TestCase):
    """The refusals that must happen before curses is ever initialised."""

    def test_no_tty_is_refused(self):
        reason = tui.preflight(is_tty=False, size=(120, 40), term="xterm")
        self.assertIn("terminal", reason.lower())

    def test_a_dumb_terminal_is_refused(self):
        reason = tui.preflight(is_tty=True, size=(120, 40), term="dumb")
        self.assertIn("TERM", reason)

    def test_a_small_window_is_refused_and_says_the_actual_size(self):
        reason = tui.preflight(is_tty=True, size=(71, 18), term="xterm")
        self.assertIn("71", reason)
        self.assertIn("18", reason)

    def test_a_usable_terminal_passes(self):
        self.assertIsNone(tui.preflight(is_tty=True, size=(80, 20), term="xterm"))

    def test_the_minimum_is_inclusive(self):
        self.assertIsNone(tui.preflight(is_tty=True, size=tui.MIN_SIZE, term="xterm"))


class LastRunFormatTest(unittest.TestCase):
    def test_a_run_is_summarised_as_date_mode_result(self):
        text = tui.format_last_run({"ts": "2026-08-03T10:00:00", "mode": "F",
                                    "result": "ok", "comment": ""})
        self.assertTrue(text.startswith("03.08."))
        self.assertIn("F", text)
        self.assertIn("ok", text)

    def test_a_comment_is_quoted_after_the_result(self):
        text = tui.format_last_run({"ts": "2026-08-03T10:00:00", "mode": "F",
                                    "result": "ok", "comment": "eq_stock"})
        self.assertIn('"eq_stock"', text)

    def test_nothing_known_shows_a_dash(self):
        self.assertEqual(tui.format_last_run(None), "—")

    def test_an_unparsable_timestamp_becomes_a_question_mark(self):
        text = tui.format_last_run({"ts": "yesterday", "mode": "F",
                                    "result": "ok", "comment": ""})
        self.assertTrue(text.startswith("?"))
        self.assertIn("ok", text)


class DefaultMarkerTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.marker = os.path.join(tempfile.mkdtemp(), ".ownerp_tui_default")

    def test_it_is_off_until_the_marker_exists(self):
        self.assertFalse(tui.tui_is_default(self.marker))

    def test_setting_it_creates_the_marker(self):
        tui.set_tui_default(True, self.marker)
        self.assertTrue(tui.tui_is_default(self.marker))

    def test_clearing_it_removes_the_marker(self):
        tui.set_tui_default(True, self.marker)
        tui.set_tui_default(False, self.marker)
        self.assertFalse(tui.tui_is_default(self.marker))

    def test_clearing_an_absent_marker_is_not_an_error(self):
        tui.set_tui_default(False, self.marker)       # must not raise
        self.assertFalse(tui.tui_is_default(self.marker))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_ownerp_tui -v`
Expected: FAIL — `AttributeError: module 'ownerp_tui' has no attribute 'preflight'`

- [ ] **Step 3: Add the imports and the non-drawing helpers**

At the top of `scripts/ownerp_tui.py`, under the docstring:

```python
import os
import sys
import time
import curses
import argparse
import subprocess
from os.path import expanduser, join

# The runner is imported for its history reader and for its path. It lives
# beside this script on a server ($HOME) and in scripts/ in the repository -
# both are covered by adding this file's own directory to the path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import update_docker_odoo as runner
except ImportError:          # pragma: no cover - a server always has it
    runner = None

RUNNER_SCRIPT = join(expanduser("~"), "update_docker_odoo.py")
CONFIG_FILE = join(expanduser("~"), "docker2update.yaml")

# Below this the list has no room to be a list.
MIN_SIZE = (80, 20)

TUI_DEFAULT_MARKER = join(expanduser("~"), ".ownerp_tui_default")
```

Then append the helpers:

```python
def preflight(is_tty=None, size=None, term=None):
    """Why this terminal cannot host the TUI, or None when it can.

    Checked before curses is initialised, so a refusal is a plain sentence on
    stderr rather than a traceback from a half-set-up screen. Split out from
    main() because these three refusals are the ones worth asserting.
    """
    is_tty = sys.stdout.isatty() if is_tty is None else is_tty
    if not is_tty:
        return ("No terminal on stdout - the TUI needs one. "
                "Use update_docker_odoo.py directly (see --help).")

    term = os.environ.get("TERM", "") if term is None else term
    if term in ("", "dumb"):
        return (f"TERM={term or 'unset'} cannot draw a TUI. "
                "Use update_docker_odoo.py directly (see --help).")

    if size is None:
        size = os.get_terminal_size()
        size = (size.columns, size.lines)
    if size[0] < MIN_SIZE[0] or size[1] < MIN_SIZE[1]:
        return (f"Window too small (currently {size[0]}x{size[1]}, "
                f"need {MIN_SIZE[0]}x{MIN_SIZE[1]}).")
    return None


def format_last_run(entry):
    """One column's worth of 'what happened here last time'."""
    if not entry:
        return "—"
    try:
        when = time.strftime("%d.%m.", time.strptime(entry.get("ts", ""),
                                                     runner.HISTORY_TS_FORMAT))
    except (ValueError, TypeError, AttributeError):
        when = "?"
    text = f"{when} {entry.get('mode', '?')}  {entry.get('result', '?')}"
    comment = entry.get("comment") or ""
    return f'{text}  "{comment}"' if comment else text


def tui_is_default(marker=TUI_DEFAULT_MARKER):
    """Whether `doup` should start the TUI on this server."""
    return os.path.exists(marker)


def set_tui_default(enabled, marker=TUI_DEFAULT_MARKER):
    """Create or remove the marker `doup` looks for. Never raises."""
    try:
        if enabled:
            with open(marker, "w", encoding="utf8") as handle:
                handle.write(f"Set by ownerp_tui.py {SCRIPT_VERSION} on "
                             f"{time.strftime('%d.%m.%Y %H:%M:%S')}\n")
        elif os.path.exists(marker):
            os.remove(marker)
    except OSError as exc:
        print(f"Could not change the doup default: {exc}", file=sys.stderr)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest tests.test_ownerp_tui -v`
Expected: PASS

- [ ] **Step 5: Add the config reader and the drawing layer**

Append to `scripts/ownerp_tui.py`:

```python
def load_containers(path=CONFIG_FILE):
    """Read the container list. Returns (containers, error_message).

    Read-only, always: this script has no write path into the YAML and must not
    grow one. A parse error comes back as a sentence with its line number
    rather than a traceback - the operator's next move is to open the file at
    that line, and a stack trace does not help them find it.
    """
    import yaml
    try:
        with open(path, encoding="utf8") as handle:
            config = yaml.safe_load(handle) or {}
    except FileNotFoundError:
        return [], f"Configuration not found: {path}"
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark else ""
        return [], f"{path} cannot be parsed{where}: {getattr(exc, 'problem', exc)}"
    except OSError as exc:
        return [], f"{path} cannot be read: {exc}"
    containers = config.get("containers") or []
    if not containers:
        return [], f"{path} lists no containers."
    return containers, None


HELP_LINES = [
    "  ↑ ↓ / j k   move            Space   select / unselect",
    "  a           all / none      m       mode  M → F → N",
    "  c           run comment     Enter   start the selected systems",
    "  v           validate the configuration",
    "  d           use the TUI as the default for `doup` on this server",
    "  q / Esc     quit",
    "",
    "  M  module copy (2-3 min)   F  full update (10-20 min)",
    "  N  neutralize, then full update - destructive, asks twice",
    "",
    "  Nothing here is ever written to docker2update.yaml. The ticks and modes",
    "  are read from `active:` and `type:` as a starting point, and changing",
    "  them applies to this run only.",
]


def draw(stdscr, selection, latest, message=""):
    """Render the list. Kept deliberately dumb - all state lives elsewhere."""
    stdscr.erase()
    height, width = stdscr.getmaxyx()

    stdscr.addnstr(0, 0, " ownERP Update".ljust(width - 1), width - 1,
                   curses.A_REVERSE)
    header_right = f"{CONFIG_FILE} "
    if len(header_right) < width - 20:
        stdscr.addnstr(0, width - 1 - len(header_right), header_right,
                       len(header_right), curses.A_REVERSE)

    # One line for the header, one for the footer, one for the message.
    visible = max(1, height - 4)
    first = max(0, min(selection.cursor - visible + 1, len(selection.rows) - visible))
    first = max(0, first)

    for offset, row in enumerate(selection.rows[first:first + visible]):
        index = first + offset
        mark = "x" if row["selected"] else " "
        version = f"v{row['version']}" if row["version"] else ""
        line = (f" [{mark}] {row['name']:<18.18} {row['mode']}   {version:<5.5} "
                f"{format_last_run(latest.get(row['name']))}")
        attr = curses.A_BOLD if index == selection.cursor else curses.A_NORMAL
        stdscr.addnstr(2 + offset, 0, line.ljust(width - 1), width - 1, attr)

    if message:
        stdscr.addnstr(height - 2, 0, f" {message}"[:width - 1], width - 1,
                       curses.A_BOLD)
    footer = (" Space select   m mode   c comment   Enter start   "
              "v validate   ? help   q quit")
    stdscr.addnstr(height - 1, 0, footer.ljust(width - 1), width - 1,
                   curses.A_REVERSE)
    stdscr.refresh()


def prompt(stdscr, question, default=""):
    """Read one line from the operator. Returns None when cancelled."""
    height, width = stdscr.getmaxyx()
    curses.echo()
    curses.curs_set(1)
    try:
        stdscr.addnstr(height - 2, 0, f" {question} ".ljust(width - 1), width - 1,
                       curses.A_BOLD)
        stdscr.move(height - 2, len(question) + 2)
        stdscr.clrtoeol()
        raw = stdscr.getstr(height - 2, len(question) + 2, 120)
    except KeyboardInterrupt:
        return None
    finally:
        curses.noecho()
        curses.curs_set(0)
    return raw.decode("utf8", errors="replace").strip() or default


def confirm(stdscr, lines, question):
    """Show a block and ask for y/n. Returns True only on an explicit yes."""
    height, width = stdscr.getmaxyx()
    stdscr.erase()
    for index, line in enumerate(lines[:height - 3]):
        stdscr.addnstr(1 + index, 2, line, width - 3)
    stdscr.addnstr(height - 2, 2, f"{question} (y/N) ", width - 3, curses.A_BOLD)
    stdscr.refresh()
    return stdscr.getch() in (ord("y"), ord("Y"))


def show_block(stdscr, lines):
    """Show a block of text until a key is pressed."""
    height, width = stdscr.getmaxyx()
    stdscr.erase()
    for index, line in enumerate(lines[:height - 3]):
        stdscr.addnstr(1 + index, 2, line, width - 3)
    stdscr.addnstr(height - 2, 2, "Press any key.", width - 3, curses.A_BOLD)
    stdscr.refresh()
    stdscr.getch()
```

- [ ] **Step 6: Add the run handling and the key loop**

Append:

```python
def run_outside_curses(stdscr, invocations):
    """Leave curses, run the invocations in order, return the worst exit code.

    Sequential and never parallel: two docker builds on one host compete for
    the same disk and the same daemon, and the run logs would interleave on
    screen. A failing group does not stop the following ones - the operator
    selected them - but its exit code survives to the end.

    The screen is restored explicitly in a finally block. endwin() only
    suspends curses, and while a following refresh() usually revives it, the
    input modes (noecho, cbreak, cursor visibility) are not guaranteed to come
    back with it - and a list that echoes every keystroke is worse than no
    list at all.
    """
    curses.endwin()
    worst = 0
    try:
        for argv in invocations:
            print(f"\n$ {' '.join(argv)}\n", flush=True)
            worst = max(worst, subprocess.call([sys.executable] + argv))
        print("\nDone. Press Enter to return to the list.", flush=True)
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
    finally:
        stdscr.clear()
        curses.noecho()
        curses.cbreak()
        curses.curs_set(0)
        stdscr.keypad(True)
        stdscr.refresh()
    return worst


def loop(stdscr, selection, latest):
    """The key loop. Returns the worst exit code of everything it started."""
    curses.curs_set(0)
    message = ""
    worst = 0

    while True:
        draw(stdscr, selection, latest, message)
        message = ""
        key = stdscr.getch()

        if key in (ord("q"), 27):                      # 27 = Esc
            return worst
        if key == curses.KEY_RESIZE:
            continue
        if key in (curses.KEY_UP, ord("k")):
            selection.move(-1)
        elif key in (curses.KEY_DOWN, ord("j")):
            selection.move(1)
        elif key == ord(" "):
            selection.toggle()
        elif key == ord("a"):
            selection.toggle_all()
        elif key == ord("m"):
            selection.rotate_mode()
        elif key == ord("c"):
            answer = prompt(stdscr, "Comment for this run:", selection.comment)
            if answer is not None:
                selection.comment = answer
        elif key == ord("d"):
            set_tui_default(not tui_is_default())
            message = ("`doup` now starts the TUI." if tui_is_default()
                       else "`doup` now starts the runner directly.")
        elif key in (ord("?"), ord("h")):
            show_block(stdscr, HELP_LINES)
        elif key == ord("v"):
            worst = max(worst, run_outside_curses(
                stdscr, [[RUNNER_SCRIPT, "--validate"]]))
        elif key in (curses.KEY_ENTER, 10, 13):
            if not selection.can_start():
                message = "Nothing selected - Space ticks a system."
                continue
            summary = ["This run:", ""]
            summary += [f"  {row['name']:<20} {MODE_LABELS[row['mode']]}"
                        for row in selection.selected_rows]
            summary += ["", f'  comment: "{selection.comment}"'
                        if selection.comment else "  no comment"]
            if not confirm(stdscr, summary,
                           f"Start {len(selection.selected_rows)} system(s)?"):
                message = "Cancelled."
                continue
            if selection.needs_extra_confirmation():
                victims = [row for row in selection.selected_rows if row["mode"] == "N"]
                warning = ["NEUTRALIZE - this rewrites the database:", ""]
                warning += [f"  {row['name']}  (database {row['database']})"
                            for row in victims]
                warning += ["", "Mail servers, cron jobs and outgoing interfaces",
                            "are disabled in these databases. On a live system",
                            "this is not what you want."]
                if not confirm(stdscr, warning, "Neutralize these databases?"):
                    message = "Cancelled."
                    continue
            worst = max(worst, run_outside_curses(
                stdscr, selection.runner_invocations(RUNNER_SCRIPT)))
            latest = last_run_by_container(runner.read_history() if runner else [])
```

- [ ] **Step 7: Add `main()` and the entry point**

Append:

```python
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Select Odoo container updates and hand them to "
                    "update_docker_odoo.py.")
    parser.add_argument("-c", "--config", default=CONFIG_FILE,
                        help=f"Configuration file (default: {CONFIG_FILE})")
    parser.add_argument("--make-default", action="store_true",
                        help="Let `doup` start this TUI on an interactive terminal")
    parser.add_argument("--no-default", action="store_true",
                        help="Let `doup` start the runner directly again")
    args = parser.parse_args(argv)

    if args.make_default or args.no_default:
        set_tui_default(args.make_default)
        print("`doup` now starts the TUI." if tui_is_default()
              else "`doup` now starts the runner directly.")
        return 0

    refusal = preflight()
    if refusal:
        print(refusal, file=sys.stderr)
        return 2

    containers, error = load_containers(args.config)
    if error:
        print(error, file=sys.stderr)
        print(f"Open it with: mcedit {args.config}", file=sys.stderr)
        return 1

    selection = UpdateSelection(containers)
    latest = last_run_by_container(runner.read_history() if runner else [])
    # curses.wrapper restores the terminal on any exit, exception included - a
    # wrecked terminal after a crash is what operators hold against TUIs.
    return curses.wrapper(loop, selection, latest)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 8: Verify the suite still passes**

Run: `python3 -m unittest discover -s tests`
Expected: OK, no failures

- [ ] **Step 9: Verify the refusals by hand**

```bash
python3 scripts/ownerp_tui.py < /dev/null | cat        # no TTY on stdout
echo "exit: $?"
TERM=dumb python3 scripts/ownerp_tui.py
echo "exit: $?"
```
Expected: both print one sentence pointing at `update_docker_odoo.py`, exit code 2, no traceback.

- [ ] **Step 10: Verify the screen by hand**

Create a throwaway config and start the TUI in a real terminal:

```bash
cat > /tmp/tui-demo.yaml <<'YAML'
containers:
  - active: true
    type: "F"
    container_name: "live-odoo"
    database_name: "live_db"
    odoo_version: "18"
  - active: false
    type: "M"
    container_name: "test-odoo"
    database_name: "test_db"
    odoo_version: "18"
YAML
python3 scripts/ownerp_tui.py -c /tmp/tui-demo.yaml
```

Check, then quit with `q`:
- live-odoo is ticked, test-odoo is not
- `j`/`k` move, `Space` toggles, `m` rotates the mode M → F → N
- `c` accepts a comment, `?` shows the help, `Esc` leaves it
- `Enter` with nothing selected reports it instead of starting
- Resizing the window does not corrupt the screen
- After `q` the terminal is intact (`echo test` behaves normally)

- [ ] **Step 11: Commit**

```bash
git add scripts/ownerp_tui.py tests/test_ownerp_tui.py
git commit -m "[ADD] ownerp_tui.py: the curses frontend

The list, the keys, the confirmation dialogs, and the three refusals that
happen before curses is ever initialised: no TTY, TERM=dumb, window below
80x20 - each a plain sentence on stderr and exit 2, never a traceback from a
half-built screen.

Starting hands over to update_docker_odoo.py outside curses, one invocation
per mode group, sequentially; the worst exit code survives. A Neutralize in
the selection asks a second time and names the databases it would rewrite."
```

---

### Task 6: Distribution — `getScripts.py`, the `doup` switch, the `tui` alias

**Files:**
- Modify: `getScripts.py` — `copy_scripts()` list (around line 3790), version header
- Create: `fish/functions/linux/doup.fish`
- Modify: `fish/conf.d/33-aliases-backup.fish`

**Interfaces:**
- Consumes: `~/ownerp_tui.py` and `~/.ownerp_tui_default` (Task 5)
- Produces: `doup` (function), `tui` (alias)

- [ ] **Step 1: Add the script to the distribution list**

In `getScripts.py`, `copy_scripts()`, add one entry after `"update_docker_odoo.py"`:

```python
    scripts = [
        "update_docker_odoo.py",
        "ownerp_tui.py",
        "cleanup-weblogs.py",
```

- [ ] **Step 2: Replace the `doup` alias with a function**

Edit `fish/conf.d/33-aliases-backup.fish` — bump its header and drop the `doup` alias, because in Fish an alias *is* a function and one defined in `conf.d` would win over the autoloaded one:

```fish
# Backup and Update Aliases
# Version 1.1.0 | 11.08.2026

# Backup operations
alias dobk='$HOME/container2backup.py'
alias edbk='mcedit $HOME/container2backup.yaml'
alias llbk='ll /opt/backups/docker'
alias cpbk='cp /opt/backups/docker/'
alias cdbk='cd /opt/backups/docker'

# Update operations
# NOTE: `doup` is a function (functions/linux/doup.fish), not an alias - it
# picks between the TUI and the runner. An alias here would shadow it.
alias tui='$HOME/ownerp_tui.py'
alias edup='mcedit $HOME/docker2update.yaml'
```

- [ ] **Step 3: Create the switch**

Create `fish/functions/linux/doup.fish`:

```fish
# Update Odoo containers
# Version 1.0.0 | 11.08.2026

function doup --description "Update Odoo containers (TUI when enabled)"
    # Three conditions, all of them required, because each one protects a
    # different caller:
    #   no arguments    - `doup -s live-odoo` must reach the runner untouched
    #   interactive     - a cron job must never end up waiting inside a TUI
    #   marker present  - the TUI is opt-in per server until it has proven itself
    if test (count $argv) -eq 0; and status is-interactive; and test -f $HOME/.ownerp_tui_default
        $HOME/ownerp_tui.py
    else
        $HOME/update_docker_odoo.py $argv
    end
end
```

- [ ] **Step 4: Bump the getScripts version**

Both the constant and nothing else — `getScripts.py` carries no `# Version` header comment:

```python
SCRIPT_VERSION = "9.11.0"
SCRIPT_DATE = "11.08.2026"
```

- [ ] **Step 5: Check the Fish syntax**

Run: `fish -n fish/functions/linux/doup.fish && fish -n fish/conf.d/33-aliases-backup.fish && echo "FISH OK"`
Expected: `FISH OK`

- [ ] **Step 6: Verify the switch picks correctly**

Stub both targets in a throwaway `$HOME` so the function announces which one it
picked, then walk the truth table. `fish -i -c` makes `status is-interactive`
true, which is what separates the operator's shell from cron:

```bash
rm -rf /tmp/doup-test && mkdir -p /tmp/doup-test
printf '#!/bin/sh\necho "REACHED=tui args=$*"\n' > /tmp/doup-test/ownerp_tui.py
printf '#!/bin/sh\necho "REACHED=runner args=$*"\n' > /tmp/doup-test/update_docker_odoo.py
chmod +x /tmp/doup-test/*.py
touch /tmp/doup-test/.ownerp_tui_default

HOME=/tmp/doup-test fish    -c 'source fish/functions/linux/doup.fish; doup'
HOME=/tmp/doup-test fish    -c 'source fish/functions/linux/doup.fish; doup -s live-odoo'
HOME=/tmp/doup-test fish -i -c 'source fish/functions/linux/doup.fish; doup'
HOME=/tmp/doup-test fish -i -c 'source fish/functions/linux/doup.fish; doup -s live-odoo'
rm -f /tmp/doup-test/.ownerp_tui_default
HOME=/tmp/doup-test fish -i -c 'source fish/functions/linux/doup.fish; doup'
```

Expected, in order: `runner` (cron case — no TTY beats the marker), `runner`
with the args intact, `tui`, `runner` with the args intact, `runner`.

Do NOT write `function status; return 1; end` to fake the interactive check —
`status` is a reserved word in Fish 4 and the shell refuses the definition.

- [ ] **Step 7: Run the whole suite**

Run: `python3 -m unittest discover -s tests`
Expected: OK, no failures

- [ ] **Step 8: Commit**

```bash
git add getScripts.py fish/functions/linux/doup.fish fish/conf.d/33-aliases-backup.fish
git commit -m "[ADD] distribute ownerp_tui.py, doup picks between TUI and runner

getScripts.py v9.11.0 ships ownerp_tui.py to \$HOME, \`tui\` starts it, and
\`doup\` becomes a function with three conditions that each protect a different
caller: arguments always reach the runner, a non-interactive shell always
reaches the runner, and the TUI stays opt-in per server via
~/.ownerp_tui_default.

The doup alias is removed - in Fish an alias is a function, and one in conf.d
would shadow the autoloaded one."
```

---

### Task 7: Documentation

**Files:**
- Modify: `RELEASE_NOTES.md`, `CLAUDE.md`, `docs/INSTALLATION_GUIDE.md` (DE + EN sections), `docs/superpowers/specs/2026-08-11-tui-update-runner-design.md` (status line)

**Interfaces:**
- Consumes: everything from Tasks 1-6
- Produces: nothing

- [ ] **Step 1: Write the release notes entry**

At the top of `RELEASE_NOTES.md`, directly under `# Release Notes`:

```markdown
## Picking Systems Instead of Editing YAML (11.08.2026)

*ownerp_tui.py v1.0.0, update_docker_odoo.py v5.11.0, getScripts.py v9.11.0*

### Added
- **A TUI for ad-hoc updates**, started with `tui`. It lists every system from
  `docker2update.yaml` with its mode and its last run, and hands the selection
  to `update_docker_odoo.py`. Selecting a system for one run used to mean
  editing `active:` and `type:` with mcedit and editing them back afterwards —
  with twenty systems that is where mistakes come from, because the file is
  left in a state nobody intended and the next scheduled run acts on it.
- **The TUI never writes to the YAML.** Ticks and modes are read from `active:`
  and `type:` as a starting point; the run itself is passed as arguments. There
  is nothing to turn back afterwards, and the heavily commented config — which
  is the documentation for these files — is never at risk.
- **`~/update-history.jsonl`**: one line per container run — what ran when, in
  which mode, with which result, duration, log path and comment. Written by the
  runner, so classic and cron runs are recorded too, which is the whole point of
  a central file. Retention via `defaults.history_retention_days`, 365 days by
  default, `0` keeps everything.
- **`--comment TEXT`** is recorded in the history and in the run log header,
  where whoever opens that log a month later reads why the run happened.
- **`--type M|F|N`** overrides the YAML mode for one run without touching it.
  Since it applies per invocation, a selection with mixed modes becomes one
  runner call per mode, run in order.

### Changed
- **`-s` takes several names**, repeated or comma-separated. `-s live-odoo`
  keeps working exactly as before.
- **`doup` becomes a function** that starts the TUI only when all three
  conditions hold: no arguments, an interactive shell, and
  `~/.ownerp_tui_default` present (toggled with `d` in the TUI, or
  `ownerp_tui.py --make-default`). Arguments and non-interactive shells always
  reach the runner directly — no cron job can end up waiting inside a TUI.

### Fixed
- **`-s` now overrides `active: false`.** The container loop checked `active`
  before the `-s` match, so an explicitly named but parked container was skipped
  without a word. Naming a container is a deliberate act. An unknown name is now
  an error instead of a run that silently updates nothing.

### Notes
- Stdlib `curses`, no new dependency: the root-run scripts use system Python,
  PEP 668 makes `pip install` as root fail, and `python3-textual` is not
  available across all target distributions.
- Blocks two and three of the design — schema validation and the guided
  assistants for onboarding and backup configuration — are specified in
  `docs/superpowers/specs/2026-08-11-tui-update-runner-design.md` and not yet
  built. `v` in the TUI calls the existing `--validate` until then.
```

- [ ] **Step 2: Update the component list in CLAUDE.md**

In the `### Key Components` section, add a block after `#### 3. update_docker_odoo.py`:

```markdown
#### 4. ownerp_tui.py (v1.0.0)
- **Purpose**: curses TUI for picking systems, mode and a run comment
- **Started with**: `tui`, or `doup` when `~/.ownerp_tui_default` exists
- **Never writes to the YAML** — `active:`/`type:` are read as the
  pre-selection, the run is passed as arguments (`-s`, `--type`, `--comment`)
- **One runner invocation per mode group**, sequential, worst exit code wins
- **Refuses without a TTY**, on `TERM=dumb`, or below 80×20 — cron always gets
  the classic runner
```

and update the `update_docker_odoo.py` entry's version to `(v5.11.0)`, adding:

```markdown
  - Run history in `~/update-history.jsonl` (one line per container run,
    `defaults.history_retention_days`, 365 default, 0 = forever)
  - `-s` repeatable/comma-separated and stronger than `active: false`
```

- [ ] **Step 3: Document it in the installation guide (both languages)**

In the German chapter on updates, after the `doup` description:

```markdown
### TUI-Modus

`tui` startet die Auswahlmaske: alle Systeme aus `docker2update.yaml` mit Modus
und letztem Lauf. Space wählt aus, `m` schaltet den Modus (M/F/N), `c` hinterlegt
einen Kommentar, Enter startet. Die YAML wird dabei **nicht** verändert — Haken
und Modus gelten nur für diesen Lauf.

```bash
tui                                  # Auswahlmaske
doup                                 # klassisch, oder TUI wenn als Standard gesetzt
doup -s live-odoo --type F           # ohne TUI, ein System, Modus einmalig
doup -s live-odoo --comment "eq_stock nachgezogen"
```

Mit `d` in der Maske (oder `ownerp_tui.py --make-default`) wird die TUI zum
Standard für `doup`. Mit Argumenten oder ohne Terminal läuft immer das klassische
Skript — ein Cronjob kann nie in der Maske hängenbleiben.

Jeder Lauf landet in `~/update-history.jsonl`: wann, welches System, welcher
Modus, welches Ergebnis, welcher Kommentar.
```

The English chapter gets the same block, translated:

```markdown
### TUI mode

`tui` opens the selection screen: every system from `docker2update.yaml` with its
mode and its last run. Space selects, `m` cycles the mode (M/F/N), `c` records a
comment, Enter starts. The YAML is **not** modified — ticks and mode apply to
this run only.

```bash
tui                                  # selection screen
doup                                 # classic, or the TUI when set as default
doup -s live-odoo --type F           # no TUI, one system, mode just this once
doup -s live-odoo --comment "pulled in eq_stock"
```

`d` in the screen (or `ownerp_tui.py --make-default`) makes the TUI the default
for `doup`. With arguments, or without a terminal, the classic script always runs
— no cron job can end up waiting in the screen.

Every run is recorded in `~/update-history.jsonl`: when, which system, which
mode, which result, which comment.
```

- [ ] **Step 4: Mark the spec as implemented**

In `docs/superpowers/specs/2026-08-11-tui-update-runner-design.md`, line 3:

```markdown
*11.08.2026 · building block 1 of 3 · status: implemented*
```

- [ ] **Step 5: Verify nothing is stale**

Run: `grep -rn "5\.10\.0\|9\.10\.0" CLAUDE.md RELEASE_NOTES.md docs/INSTALLATION_GUIDE.md`
Expected: only historical entries in `RELEASE_NOTES.md` — no current-version claim left behind in `CLAUDE.md`.

- [ ] **Step 6: Run the whole suite one last time**

Run: `python3 -m unittest discover -s tests`
Expected: OK, no failures

- [ ] **Step 7: Commit**

```bash
git add RELEASE_NOTES.md CLAUDE.md docs/INSTALLATION_GUIDE.md docs/superpowers/specs/2026-08-11-tui-update-runner-design.md
git commit -m "[ADD] document the TUI update runner

Release notes for ownerp_tui.py v1.0.0 / update_docker_odoo.py v5.11.0 /
getScripts.py v9.11.0, the component entry in CLAUDE.md, and a TUI section in
both language chapters of the installation guide."
```

- [ ] **Step 8: Push to both remotes**

```bash
git push origin 2026 && git push upstream 2026
```

---

## After this plan

Building blocks 2 and 3 from the spec are not part of it:

- **Block 2 — schema validation.** Replaces what `v` calls: required fields,
  types, port collisions, paths that must exist, duplicate container names.
  Usable from the command line without the TUI.
- **Block 3 — guided assistants.** A second menu: onboard a new server,
  maintain the backup configuration. Writes by appending a fully commented block
  and by patching individual fields line-wise, so comments and formatting
  survive.

Each gets its own spec and its own plan.
