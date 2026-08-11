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
