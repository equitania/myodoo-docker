"""
Tests for the state file, the hand-edit decisions and the odoo.conf writer of
ownerp_sizing.py.

Run from the repository root:

    python3 -m unittest tests.test_ownerp_sizing_apply -v
"""

import glob
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import ownerp_sizing as sz  # noqa: E402

CONF = (
    "[options]\n"
    "# keep this comment\n"
    "workers = 3\n"
    "max_cron_threads = 2\n"
    "limit_memory_soft = 2147483648\n"
    "limit_memory_hard = 2684354560\n"
    "db_maxconn = 100\n"
    "db_password = secret\n"
    "dbfilter =\n"
)
TEMPLATE = {
    "workers": "3", "max_cron_threads": "2", "limit_memory_soft": "2147483648",
    "limit_memory_hard": "2684354560", "db_maxconn": "100",
}


def recommended(version=18):
    live = sz.Instance(name="live-odoo", version=version, role="live", users=None,
                       overrides={}, db_container=None, build_dir="", conf={})
    test = sz.Instance(name="test-odoo", version=version, role="test", users=None,
                       overrides={}, db_container=None, build_dir="", conf={})
    return sz.compute_plan(sz.Hardware(4, 16384), [live, test]).results[0].odoo


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.conf = os.path.join(self.dir, "odoo.conf")
        self.write(CONF)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def write(self, text):
        with open(self.conf, "w", encoding="utf8") as handle:
            handle.write(text)

    def read(self):
        with open(self.conf, encoding="utf8") as handle:
            return handle.read()

    def baks(self):
        return glob.glob(self.conf + ".bak_*")

    def seed_state(self, state):
        with open(os.path.join(self.dir, sz.STATE_NAME), "w", encoding="utf8") as handle:
            json.dump(state, handle)

    def sync(self, rec=None, overrides=()):
        return sz.sync_odoo_conf(self.dir, rec or recommended(), set(overrides), TEMPLATE)


class TestDecideKey(unittest.TestCase):
    def test_decide_key_table(self):
        d = sz.decide_key("workers", "8", "5", {"status": "hand", "known": []}, False, override=True)
        self.assertEqual(d.action, "write")
        self.assertIn("Override", d.note)
        self.assertEqual(sz.decide_key("workers", "5", "5", None, False, override=True).action, "same")
        self.assertEqual(sz.decide_key("workers", "5", "5", None, True).action, "same")
        self.assertEqual(sz.decide_key("workers", "8", "5", {"status": "hand", "known": []}, True).action,
                         "keep")
        self.assertEqual(sz.decide_key("workers", None, "5", None, False).action, "write")
        self.assertEqual(sz.decide_key("workers", "8", "5",
                                       {"status": "accepted", "known": ["8"]}, False).action, "write")
        self.assertEqual(sz.decide_key("workers", "3", "5", None, True).action, "write")
        no_entry = sz.decide_key("workers", "8", "5", None, False)
        self.assertEqual(no_entry.action, "keep")
        self.assertIn("dosize --review", no_entry.note)
        reviewed = sz.decide_key("workers", "7", "5", {"status": "accepted", "known": ["8"]}, False)
        self.assertEqual(reviewed.action, "keep")
        self.assertNotIn("dosize --review", reviewed.note)

    def test_custom_equal(self):
        d = sz.decide_key("k", "1.0", "1", None, False, equal=lambda a, b: float(a) == float(b))
        self.assertEqual(d.action, "same")

    def test_format_decision(self):
        self.assertEqual(sz.format_decision(sz.KeyDecision("workers", "keep", "8", "5", "")),
                         "workers: hand 8, recommended 5 - unchanged")
        self.assertEqual(sz.format_decision(sz.KeyDecision("workers", "write", "3", "5", "")),
                         "workers: 3 -> 5")
        self.assertEqual(sz.format_decision(sz.KeyDecision("workers", "same", "5", "5", "")),
                         "workers: 5 (ok)")


class TestSync(Base):
    def test_template_default_values_are_rewritten_and_everything_else_is_byte_identical(self):
        rec = recommended()
        result = self.sync()
        self.assertTrue(result.changed)
        self.assertIsNone(result.error)
        text = self.read()
        values = sz.parse_conf_values(text)
        self.assertEqual(values["workers"], "5")
        for key in ("limit_memory_soft", "limit_memory_hard", "db_maxconn", "max_cron_threads"):
            self.assertEqual(values[key], rec[key])
        for line in ("[options]", "# keep this comment", "db_password = secret", "dbfilter ="):
            self.assertIn(line, text.splitlines())
        self.assertEqual(len(text.splitlines()), len(CONF.splitlines()) + 3)  # v18 gevent keys appended
        baks = self.baks()
        self.assertEqual(len(baks), 1)
        with open(baks[0], encoding="utf8") as handle:
            self.assertEqual(handle.read(), CONF)

    def test_a_hand_edit_is_kept_and_reported(self):
        self.write(CONF.replace("workers = 3", "workers = 8"))
        result = self.sync()
        self.assertEqual(sz.parse_conf_values(self.read())["workers"], "8")
        keep = [d for d in result.decisions if d.action == "keep"]
        self.assertEqual([d.key for d in keep], ["workers"])
        self.assertEqual(sz.format_decision(keep[0]), "workers: hand 8, recommended 5 - unchanged")

    def test_an_accepted_value_follows_the_recommendation_and_is_remembered(self):
        self.write(CONF.replace("workers = 3", "workers = 8"))
        self.seed_state({"odoo": {"workers": {"status": "accepted", "known": ["8"]}}, "pg": {}})
        self.sync()
        self.assertEqual(sz.parse_conf_values(self.read())["workers"], "5")
        state, err = sz.load_state(self.dir)
        self.assertIsNone(err)
        self.assertIn("5", state["odoo"]["workers"]["known"])
        self.write(self.read().replace("workers = 5", "workers = 7"))
        result = self.sync()
        self.assertEqual(sz.parse_conf_values(self.read())["workers"], "7")
        self.assertEqual([d.action for d in result.decisions if d.key == "workers"], ["keep"])

    def test_a_hand_status_is_never_overwritten_even_at_the_template_default(self):
        self.seed_state({"odoo": {"workers": {"status": "hand", "known": []}}, "pg": {}})
        result = self.sync()
        self.assertEqual(sz.parse_conf_values(self.read())["workers"], "3")
        self.assertEqual([d.action for d in result.decisions if d.key == "workers"], ["keep"])

    def test_an_override_writes_over_a_hand_value(self):
        self.write(CONF.replace("workers = 3", "workers = 8"))
        self.seed_state({"odoo": {"workers": {"status": "hand", "known": []}}, "pg": {}})
        self.sync(overrides=["workers"])
        self.assertEqual(sz.parse_conf_values(self.read())["workers"], "5")

    def test_missing_gevent_key_is_appended_for_v19(self):
        rec = recommended(19)
        self.assertEqual(rec["db_maxconn_gevent"], "16")
        self.sync(rec)
        text = self.read()
        self.assertEqual(text.splitlines()[-1], "db_maxconn_gevent = 16")
        self.assertNotIn("limit_memory_soft_gevent", sz.parse_conf_values(text))

    def test_a_corrupt_state_file_blocks_the_write(self):
        with open(os.path.join(self.dir, sz.STATE_NAME), "w") as handle:
            handle.write("{not json")
        result = self.sync()
        self.assertIn("state", result.error)
        self.assertFalse(result.changed)
        self.assertEqual(self.read(), CONF)
        self.assertEqual(self.baks(), [])

    def test_missing_odoo_conf_is_an_error_not_an_exception(self):
        os.remove(self.conf)
        result = self.sync()
        self.assertTrue(result.error)
        self.assertFalse(result.changed)

    def test_sync_is_idempotent(self):
        self.sync()
        first = self.read()
        result = self.sync()
        self.assertFalse(result.changed)
        self.assertIsNone(result.error)
        self.assertEqual(self.read(), first)
        self.assertEqual(len(self.baks()), 1)

    def test_file_mode_is_kept(self):
        os.chmod(self.conf, 0o640)
        self.sync()
        self.assertEqual(os.stat(self.conf).st_mode & 0o777, 0o640)


class TestReview(Base):
    def test_known_holds_only_the_value_in_the_file(self):
        self.write(CONF.replace("workers = 3", "workers = 8"))
        self.seed_state({"odoo": {"workers": {"status": "accepted", "known": ["8"]}}, "pg": {}})
        self.sync()
        rec = dict(recommended())
        rec["workers"] = "6"
        self.sync(rec)
        self.assertEqual(sz.parse_conf_values(self.read())["workers"], "6")
        state, _ = sz.load_state(self.dir)
        self.assertEqual(state["odoo"]["workers"]["known"], ["6"])
        self.write(self.read().replace("workers = 6", "workers = 5"))
        result = self.sync(rec)
        self.assertEqual(sz.parse_conf_values(self.read())["workers"], "5")
        self.assertEqual([d.action for d in result.decisions if d.key == "workers"], ["keep"])

    def test_non_utf8_conf_is_an_error(self):
        raw = CONF.encode() + b"# caf\xe9\n"
        with open(self.conf, "wb") as handle:
            handle.write(raw)
        result = self.sync()
        self.assertTrue(result.error)
        self.assertFalse(result.changed)
        with open(self.conf, "rb") as handle:
            self.assertEqual(handle.read(), raw)
        self.assertEqual(self.baks(), [])

    def test_wrong_state_shapes_block_the_write(self):
        shapes = [
            {"odoo": ["workers"], "pg": {}},
            {"odoo": "workers"},
            {"odoo": {"workers": {"status": "accepted", "known": "88"}}},
            {"odoo": {"workers": {"status": "accepted", "known": None}}},
            {"odoo": {"workers": {"status": "weird", "known": []}}},
            {"odoo": {"workers": "accepted"}},
            [],
        ]
        for shape in shapes:
            self.seed_state(shape)
            self.assertEqual(sz.load_state(self.dir)[0], {})
            self.assertTrue(sz.load_state(self.dir)[1], shape)
            result = self.sync()
            self.assertIn("state", result.error)
            self.assertEqual(self.read(), CONF)
            self.assertEqual(self.baks(), [])


class TestRegressionAndState(Base):
    def test_conf_regression_refuses_a_changed_foreign_key(self):
        patched = CONF.replace("db_password = secret", "db_password = other")
        self.assertEqual(sz.conf_regression(CONF, patched, {"workers"}),
                         "would change setting: db_password")
        dropped = CONF.replace("db_password = secret\n", "")
        self.assertIn("would drop setting: db_password", sz.conf_regression(CONF, dropped, set()))
        self.assertIn("would add setting", sz.conf_regression(CONF, CONF + "x = 1\n", set()))
        self.assertIsNone(sz.conf_regression(CONF, CONF.replace("workers = 3", "workers = 5"),
                                             {"workers"}))

    def test_patch_conf_text_replaces_in_place_and_appends(self):
        out = sz.patch_conf_text(CONF, {"workers": "5", "new_key": "1"})
        lines = out.splitlines()
        self.assertEqual(lines[lines.index("workers = 5") - 1], "# keep this comment")
        self.assertEqual(lines[-1], "new_key = 1")

    def test_state_roundtrip_and_dockerignore(self):
        state = {"odoo": {"workers": {"status": "accepted", "known": ["5"]}}, "pg": {}}
        self.assertIsNone(sz.save_state(self.dir, state))
        self.assertEqual(sz.load_state(self.dir), (state, None))
        self.assertEqual(sz.load_state(os.path.join(self.dir, "nope")), ({}, None))
        path = os.path.join(self.dir, ".dockerignore")
        with open(path, "w") as handle:
            handle.write("*.log")
        sz.ensure_dockerignore(self.dir)
        sz.ensure_dockerignore(self.dir)
        with open(path) as handle:
            self.assertEqual(handle.read().splitlines(), ["*.log", sz.STATE_NAME])


if __name__ == "__main__":
    unittest.main()
