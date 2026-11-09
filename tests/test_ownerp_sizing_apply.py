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


def recommended_pg(version=18):
    live = sz.Instance(name="live-odoo", version=version, role="live", users=None,
                       overrides={}, db_container=None, build_dir="", conf={})
    test = sz.Instance(name="test-odoo", version=version, role="test", users=None,
                       overrides={}, db_container=None, build_dir="", conf={})
    return sz.compute_plan(sz.Hardware(4, 16384), [live, test]).results[0].pg


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


# --- postgresql.conf writer ------------------------------------------------

PG_CONF = (
    "# PostgreSQL configuration\n"
    "max_connections = 200                   # Standard for 16GB system\n"
    "shared_buffers = 4GB                   # 25% of total RAM\n"
    "work_mem = 16MB                        # Increased for complex queries\n"
    "maintenance_work_mem = 2GB             # For VACUUM, CREATE INDEX\n"
    "effective_cache_size = 12GB            # 75% of total RAM\n"
    "random_page_cost = 1.1\n"
)


def show_value(key, text):
    """What PostgreSQL would answer for SHOW <key> (MiB values print in the largest unit)."""
    if key == "max_connections":
        return text
    mib = sz.pg_size_mib(text)
    return "%dGB" % (mib // 1024) if mib % 1024 == 0 else "%dMB" % mib


class FakeDocker:
    """Records argv lists and answers like docker would; no real process is started."""

    def __init__(self, pgdata, conf_path, ready=None, show=None, inspect_rc=0):
        self.calls = []
        self.pgdata = pgdata
        self.conf_path = conf_path
        self.ready = ready or (lambda n: 0)     # n-th pg_isready call (1-based) -> rc
        self.show = show                         # key -> text overriding the file value
        self.inspect_rc = inspect_rc
        self.isready_calls = 0

    def __call__(self, argv):
        self.calls.append(list(argv))
        if argv[:2] == ["docker", "inspect"]:
            if self.inspect_rc:
                return self.inspect_rc, "Error: No such object"
            return 0, json.dumps([{"Type": "bind", "Source": self.pgdata,
                                   "Destination": "/var/lib/postgresql/data"}])
        if "pg_isready" in argv:
            self.isready_calls += 1
            return self.ready(self.isready_calls), ""
        if "psql" in argv:
            key = argv[-1].split()[1]
            if self.show and key in self.show:
                return 0, self.show[key] + "\n"
            with open(self.conf_path, encoding="utf8") as handle:
                values = sz.parse_pg_conf_values(handle.read())
            return 0, show_value(key, values[key]) + "\n"
        return 0, ""

    def verbs(self):
        return [c[1] for c in self.calls if c[0] == "docker"]


class PgBase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.conf = os.path.join(self.dir, "postgresql.conf")
        with open(self.conf, "w", encoding="utf8") as handle:
            handle.write(PG_CONF)
        os.chmod(self.conf, 0o640)
        self.sleeps = []

    def tearDown(self):
        shutil.rmtree(self.dir)

    def read(self):
        with open(self.conf, encoding="utf8") as handle:
            return handle.read()

    def baks(self):
        return glob.glob(self.conf + ".bak_*")

    def sync(self, rec=None, entry=None, overrides=(), docker=None, retries=6):
        self.docker = docker or FakeDocker(self.dir, self.conf)
        self.entry = {} if entry is None else entry
        rec = recommended_pg() if rec is None else rec
        return sz.sync_postgres("live-db", rec, set(overrides), self.entry, self.docker, "odoo",
                                sleep=self.sleeps.append, retries=retries)


class TestPgHelpers(unittest.TestCase):
    def test_size_parsing_and_equality(self):
        self.assertEqual(sz.pg_size_mib("4GB"), 4096)
        self.assertEqual(sz.pg_size_mib("512MB"), 512)
        self.assertEqual(sz.pg_size_mib("8192kB"), 8)
        self.assertEqual(sz.pg_size_mib("1TB"), 1048576)
        self.assertIsNone(sz.pg_size_mib("100"))
        self.assertTrue(sz.pg_equal("shared_buffers", "4GB", "4096MB"))
        self.assertTrue(sz.pg_equal("max_connections", "200", "200"))
        self.assertFalse(sz.pg_equal("work_mem", "16MB", "32MB"))

    def test_parse_takes_the_last_occurrence_and_strips_comments(self):
        values = sz.parse_pg_conf_values(
            "shared_buffers = 1GB\n# shared_buffers = 9GB\nshared_buffers = '2GB' # x\n"
            "work_mem = 4MB   # y\n")
        self.assertEqual(values["shared_buffers"], "2GB")
        self.assertEqual(values["work_mem"], "4MB")

    def test_find_pgdata_from_inspect_json(self):
        def mounts(destination):
            return json.dumps([{"Source": "/data/pg", "Destination": destination}])
        self.assertEqual(sz.find_pgdata(mounts("/var/lib/postgresql/data")), "/data/pg")
        self.assertEqual(sz.find_pgdata(mounts("/var/lib/postgresql/data/")), "/data/pg")
        self.assertIsNone(sz.find_pgdata(mounts("/other")))
        self.assertIsNone(sz.find_pgdata("not json"))

    def test_patch_replaces_last_active_line_and_appends(self):
        text = "a = 1\nwork_mem = 4MB\nwork_mem = 8MB  # c\nz = 2\n"
        out = sz.patch_pg_conf_text(text, {"work_mem": "16MB", "shared_buffers": "1GB"})
        self.assertIn("work_mem = 4MB\n", out)
        self.assertIn("work_mem = 16MB   # ownerp_sizing (was: 8MB)\n", out)
        self.assertIn("shared_buffers = 1GB", out)
        self.assertEqual(out.count("# ownerp_sizing"), 2)   # replaced line + one header

    def test_container_running(self):
        self.assertTrue(sz.container_running("x", lambda a: (0, "true\n")))
        self.assertFalse(sz.container_running("x", lambda a: (0, "false\n")))
        self.assertIsNone(sz.container_running("x", lambda a: (1, "")))


class TestPgSync(PgBase):
    def test_profile_values_are_rewritten_and_unrelated_settings_survive(self):
        rec = recommended_pg()
        result = self.sync()
        self.assertIsNone(result.error)
        self.assertTrue(result.changed)
        values = sz.parse_pg_conf_values(self.read())
        for key, value in rec.items():
            self.assertEqual(values[key], value)
        self.assertIn("random_page_cost = 1.1\n", self.read())
        self.assertEqual(len(self.baks()), 1)
        with open(self.baks()[0], encoding="utf8") as handle:
            self.assertEqual(handle.read(), PG_CONF)
        self.assertEqual(os.stat(self.conf).st_mode & 0o7777, 0o640)

    def test_restart_keys_restart_and_other_keys_only_reload(self):
        result = self.sync()
        self.assertTrue(result.restarted)
        self.assertIn(["docker", "restart", "live-db"], self.docker.calls)
        self.assertNotIn(["docker", "kill", "--signal=HUP", "live-db"], self.docker.calls)

    def test_only_reload_keys_send_hup(self):
        rec = {"work_mem": "32MB"}
        result = self.sync(rec=rec)
        self.assertFalse(result.restarted)
        self.assertIn(["docker", "kill", "--signal=HUP", "live-db"], self.docker.calls)
        self.assertNotIn(["docker", "restart", "live-db"], self.docker.calls)
        self.assertTrue(result.verified)

    def test_verification_reads_show_for_each_changed_key(self):
        result = self.sync()
        shows = [c[-1] for c in self.docker.calls if "psql" in c]
        for key in ("shared_buffers", "max_connections", "work_mem"):
            self.assertIn("SHOW %s" % key, shows)
        self.assertTrue(result.verified)
        self.assertIn(["docker", "exec", "live-db", "pg_isready", "-U", "odoo", "-d", "postgres"],
                      self.docker.calls)

    def test_unit_mixed_values_are_not_a_hand_edit(self):
        with open(self.conf, "w", encoding="utf8") as handle:
            handle.write("shared_buffers = 4096MB\n")
        result = self.sync(rec={"shared_buffers": "4GB"})
        self.assertEqual(result.decisions[0].action, "same")
        self.assertFalse(result.changed)
        self.assertEqual(self.docker.verbs(), ["inspect"])

    def test_a_hand_value_is_kept_and_reported(self):
        text = PG_CONF.replace("work_mem = 16MB", "work_mem = 99MB")
        with open(self.conf, "w", encoding="utf8") as handle:
            handle.write(text)
        result = self.sync(rec={"work_mem": "32MB", "shared_buffers": "3GB"})
        by_key = {d.key: d for d in result.decisions}
        self.assertEqual(by_key["work_mem"].action, "keep")
        self.assertEqual(sz.parse_pg_conf_values(self.read())["work_mem"], "99MB")
        self.assertEqual(sz.parse_pg_conf_values(self.read())["shared_buffers"], "3GB")

    def test_state_entry_is_updated_in_place_after_success(self):
        result = self.sync()
        self.assertTrue(result.verified)
        self.assertEqual(self.entry["shared_buffers"]["known"], [recommended_pg()["shared_buffers"]])
        self.assertEqual(self.entry["shared_buffers"]["status"], "accepted")

    def test_database_that_does_not_come_up_is_rolled_back(self):
        # first restart: never ready (6 tries); rollback restart: ready
        result = self.sync(docker=FakeDocker(self.dir, self.conf,
                                             ready=lambda n: 1 if n <= 6 else 0))
        self.assertTrue(result.rolled_back)
        self.assertFalse(result.changed)
        self.assertEqual(self.read(), PG_CONF)
        self.assertIn("rolled back", result.error)
        self.assertEqual(self.docker.verbs().count("restart"), 2)
        self.assertEqual(self.entry, {})
        self.assertTrue(all(s == 5 for s in self.sleeps) and self.sleeps)

    def test_a_database_that_stays_down_after_rollback_is_reported(self):
        result = self.sync(docker=FakeDocker(self.dir, self.conf, ready=lambda n: 1))
        self.assertTrue(result.rolled_back)
        self.assertEqual(self.read(), PG_CONF)
        self.assertIn("rolled back", result.error)
        self.assertIn("not answering", result.error)

    def test_a_value_the_server_did_not_take_is_rolled_back(self):
        old = {"shared_buffers": "4GB"}
        result = self.sync(docker=FakeDocker(self.dir, self.conf, show=old))
        self.assertTrue(result.rolled_back)
        self.assertFalse(result.verified)
        self.assertEqual(self.read(), PG_CONF)
        self.assertIn("rolled back", result.error)

    def test_an_external_database_is_skipped_not_failed(self):
        result = self.sync(docker=FakeDocker(self.dir, self.conf, inspect_rc=1))
        self.assertIsNotNone(result.skipped)
        self.assertIn("not a local container", result.skipped)
        self.assertIsNone(result.error)
        self.assertEqual(self.read(), PG_CONF)
        self.assertEqual(self.baks(), [])

    def test_missing_or_non_utf8_conf_is_an_error(self):
        with open(self.conf, "wb") as handle:
            handle.write(b"work_mem = 4MB\n# \xff\xfe\n")
        result = self.sync()
        self.assertIsNotNone(result.error)
        self.assertFalse(result.changed)
        os.remove(self.conf)
        self.assertIsNotNone(self.sync().error)

    def test_wrong_state_shape_blocks_the_write(self):
        result = self.sync(entry={"work_mem": "oops"})
        self.assertIn("nothing written", result.error)
        self.assertEqual(self.read(), PG_CONF)
        self.assertNotIn("restart", self.docker.verbs())

    def test_the_regression_gate_protects_foreign_settings(self):
        patched = PG_CONF.replace("random_page_cost = 1.1", "random_page_cost = 4.0")
        reason = sz.conf_regression(PG_CONF, patched, {"work_mem"},
                                    values_of=sz.parse_pg_conf_values)
        self.assertIn("random_page_cost", reason)
