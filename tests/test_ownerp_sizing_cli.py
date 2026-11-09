"""
Tests for the report, the per-value review and the CLI of ownerp_sizing.py.

Run from the repository root:

    uv run --with pyyaml python -m unittest tests.test_ownerp_sizing_cli -q

The whole module skips itself when PyYAML is not installed.
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

try:
    import yaml  # noqa: F401
except ImportError:  # pragma: no cover - depends on the machine
    raise unittest.SkipTest("PyYAML is not installed")

import ownerp_sizing as sz  # noqa: E402

CONF_FIT = "[options]\nworkers = 5\nmax_cron_threads = 1\n"


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = sz.main(argv)
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def build_dir(self, name, conf=CONF_FIT):
        path = os.path.join(self.tmp, name)
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "odoo.conf"), "w", encoding="utf-8") as fh:
            fh.write(conf)
        return path

    def config(self, entries):
        """entries: (name, role, conf) - role None means no sizing block."""
        containers = []
        for name, role, conf in entries:
            entry = {"active": True, "container_name": name, "odoo_version": "18",
                     "dockerfile_path": self.build_dir(name, conf),
                     "db_host": name.replace("odoo", "db"), "db_user": "odoo"}
            if role:
                entry["sizing"] = {"profile": role}
            containers.append(entry)
        path = os.path.join(self.tmp, "docker2update.yaml")
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump({"containers": containers}, fh)
        return path

    def live_test(self, live_conf=CONF_FIT, test_conf=CONF_FIT):
        return self.config([("live-odoo", "live", live_conf), ("test-odoo", "test", test_conf)])


class TestReport(Base):
    def test_report_shows_hardware_budget_and_reasons(self):
        code, out, _ = run_main(["--config", self.live_test(), "--cpus", "4", "--ram-mib", "16384"])
        self.assertEqual(code, 0)
        for text in ("4 CPU", "16.0 GiB", "9626 MiB", "5 workers", "other instances use 3"):
            self.assertIn(text, out)
        self.assertNotIn("\x1b[", out)

    def test_report_for_a_host_without_blocks_says_how_to_opt_in(self):
        path = self.config([("live-odoo", None, CONF_FIT)])
        code, out, _ = run_main(["report", "--config", path, "--cpus", "4", "--ram-mib", "16384"])
        self.assertEqual(code, 0)
        self.assertIn("without sizing block", out)
        self.assertIn("wizup", out)

    def test_report_marks_kept_hand_values(self):
        path = self.live_test(live_conf="[options]\nworkers = 8\nmax_cron_threads = 1\n")
        build = os.path.join(self.tmp, "live-odoo")
        sz.save_state(build, {"odoo": {"workers": {"status": "hand", "known": ["8"]}}})
        _, out, _ = run_main(["--config", path, "--cpus", "4", "--ram-mib", "16384"])
        self.assertIn("workers: hand 8, recommended 5 - unchanged", out)

    def test_report_uses_the_template_of_the_dockerfiles_folder(self):
        path = self.live_test(live_conf="[options]\nworkers = 3\n")
        docker = os.path.join(self.tmp, "Dockerfiles", "v18-odoo")
        os.makedirs(docker)
        with open(os.path.join(docker, "odoo.conf"), "w", encoding="utf-8") as fh:
            fh.write("[options]\nworkers = 3\n")
        _, out, _ = run_main(["--config", path, "--cpus", "4", "--ram-mib", "16384",
                              "--dockerfiles", os.path.join(self.tmp, "Dockerfiles")])
        self.assertIn("workers: 3 -> 5", out)

    def test_report_exit_codes(self):
        base = ["--config", self.live_test()]
        self.assertEqual(run_main(base + ["--cpus", "4", "--ram-mib", "16384"])[0], 0)
        code, out, _ = run_main(base + ["--cpus", "2", "--ram-mib", "4096"])
        self.assertEqual(code, 1)
        self.assertIn("over budget", out)
        code, _, err = run_main(["--config", os.path.join(self.tmp, "missing.yaml"),
                                 "--cpus", "4", "--ram-mib", "16384"])
        self.assertEqual(code, 2)
        self.assertIn("missing.yaml", err)

    def test_report_json_roundtrip(self):
        code, out, _ = run_main(["--json", "--config", self.live_test(),
                                 "--cpus", "4", "--ram-mib", "16384"])
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(data["results"][0]["odoo"]["workers"], "5")
        self.assertEqual(data["hardware"], {"cpus": 4, "ram_mib": 16384})
        self.assertFalse(data["over_budget"])


def plan_for(conf):
    instance = sz.Instance(name="live-odoo", version=18, role="live", users=None, overrides={},
                           db_container="live-db", build_dir="", conf=conf)
    test = sz.Instance(name="test-odoo", version=18, role="test", users=None, overrides={},
                       db_container="test-db", build_dir="", conf={})
    plan = sz.compute_plan(sz.Hardware(4, 16384), [instance, test])
    return instance, plan.results[0]


DIFFERING = {"workers": "3", "db_maxconn": "100", "db_maxconn_gevent": "False"}


class TestReview(Base):
    def test_pending_values_lists_only_differing_unreviewed_keys(self):
        instance, result = plan_for(dict(DIFFERING, max_cron_threads="1"))
        state = {"odoo": {"db_maxconn_gevent": {"status": "hand", "known": ["False"]}}}
        pending = sz.pending_values(instance, result, state, None)
        self.assertEqual([(s, k, c) for s, k, c, _ in pending],
                         [("odoo", "workers", "3"), ("odoo", "db_maxconn", "100")])
        self.assertEqual(pending[0][3], result.odoo["workers"])
        current = {"shared_buffers": "1GB", "max_connections": "100", "work_mem": "4MB"}
        with_pg = sz.pending_values(instance, result, {}, current)
        self.assertIn(("pg", "shared_buffers", "1GB", result.pg["shared_buffers"]), with_pg)
        self.assertIn(("pg", "work_mem", "4MB", result.pg["work_mem"]), with_pg)
        self.assertNotIn("effective_cache_size", [k for _, k, _, _ in with_pg])

    def test_review_asks_per_value_and_records_accept_and_keep(self):
        build = self.build_dir("live-odoo", "[options]\nworkers = 3\n")
        instance, result = plan_for(dict(DIFFERING, max_cron_threads="1"))
        instance.build_dir = build
        answers = iter(["y", "", "q"])
        prompts = []

        def ask(prompt):
            prompts.append(prompt)
            return next(answers)

        with open(os.path.join(build, "odoo.conf"), encoding="utf-8") as fh:
            before = fh.read()
        state = sz.review(instance, result, {}, ask=ask, out=lambda *a: None)
        self.assertEqual(prompts[0], "workers: current 3 -> recommended 5 - accept? (y/N/q)")
        self.assertEqual(len(prompts), 3)
        self.assertEqual(state["odoo"]["workers"], {"status": "accepted", "known": ["3"]})
        self.assertEqual(state["odoo"]["db_maxconn"], {"status": "hand", "known": ["100"]})
        self.assertNotIn("db_maxconn_gevent", state["odoo"])
        with open(os.path.join(build, "odoo.conf"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), before)
        self.assertFalse(os.path.exists(os.path.join(build, sz.STATE_NAME)))

    def test_accepted_pg_value_follows_the_recommendation_despite_unit_spelling(self):
        instance, result = plan_for({})
        state = sz.review(instance, result, {}, ask=lambda prompt: "y", out=lambda *a: None,
                          pg_current={"shared_buffers": "1GB"})
        entry = state["pg"]["shared_buffers"]
        self.assertEqual(entry, {"status": "accepted", "known": ["1GB"]})
        decision = sz.decide_key("shared_buffers", "1024MB", "3072MB", entry, False,
                                 equal=lambda a, b: sz.pg_equal("shared_buffers", a, b))
        self.assertEqual(decision.action, "write")

    def test_review_with_a_corrupt_state_stops_with_a_message(self):
        path = self.live_test()
        build = os.path.join(self.tmp, "live-odoo")
        with open(os.path.join(build, sz.STATE_NAME), "w", encoding="utf-8") as fh:
            fh.write("{broken")
        with mock.patch.object(sz, "_stdin_is_tty", return_value=True), \
                mock.patch.object(sz, "default_runner", side_effect=AssertionError("docker")):
            code, _, err = run_main(["--review", "live-odoo", "--config", path,
                                     "--cpus", "4", "--ram-mib", "16384"])
        self.assertEqual(code, 2)
        self.assertIn(sz.STATE_NAME, err)

    def test_review_flag_without_terminal_is_refused(self):
        path = self.live_test()
        with mock.patch.object(sz, "_stdin_is_tty", return_value=False):
            code, _, err = run_main(["--review", "live-odoo", "--config", path,
                                     "--cpus", "4", "--ram-mib", "16384"])
        self.assertEqual(code, 2)
        self.assertIn("terminal", err)

    def test_review_flag_saves_the_state(self):
        path = self.live_test(live_conf="[options]\nworkers = 3\nmax_cron_threads = 1\n")
        with mock.patch.object(sz, "_stdin_is_tty", return_value=True), \
                mock.patch.object(sz, "default_runner", return_value=(1, "no docker in tests")), \
                mock.patch("builtins.input", side_effect=["y"]):
            code, _, _ = run_main(["--review", "live-odoo", "--config", path,
                                   "--cpus", "4", "--ram-mib", "16384"])
        self.assertEqual(code, 0)
        state, problem = sz.load_state(os.path.join(self.tmp, "live-odoo"))
        self.assertIsNone(problem)
        self.assertEqual(state["odoo"]["workers"], {"status": "accepted", "known": ["3"]})

    def test_review_prints_the_plan_warnings_before_the_first_prompt(self):
        path = self.live_test(live_conf="[options]\nworkers = 3\nmax_cron_threads = 1\n")
        out = io.StringIO()
        seen = []

        def fake_input(prompt=""):
            seen.append(out.getvalue())
            return "y"
        with mock.patch.object(sz, "_stdin_is_tty", return_value=True), \
                mock.patch.object(sz, "default_runner", return_value=(1, "no docker")), \
                mock.patch("builtins.input", side_effect=fake_input), \
                contextlib.redirect_stdout(out):
            sz.main(["--review", "live-odoo", "--config", path,
                     "--cpus", "1", "--ram-mib", "1500"])
        self.assertTrue(seen)
        self.assertIn("over budget", seen[0])

    def test_pg_current_values_reads_show_output_and_survives_failure(self):
        calls = []

        def run(argv):
            calls.append(argv)
            return 0, "shared_buffers|1GB\nmax_connections|100\n"

        values = sz.pg_current_values("live-db", run, "odoo")
        self.assertEqual(values, {"shared_buffers": "1GB", "max_connections": "100"})
        self.assertEqual(calls[0][:3], ["docker", "exec", "live-db"])
        self.assertIsNone(sz.pg_current_values("live-db", lambda argv: (1, "no such container")))


class TestPgSubcommand(Base):
    def pg(self, *extra):
        return run_main(["pg", "--json"] + list(extra))

    def test_pg_subcommand_uses_the_yaml_role_over_the_flag(self):
        path = self.config([("test-odoo", "test", CONF_FIT)])
        code, out, _ = self.pg("--role", "live", "--container", "test-db", "--config", path,
                               "--cpus", "4", "--ram-mib", "16384")
        data = json.loads(out)
        with open(path, encoding="utf-8") as fh:
            containers = yaml.safe_load(fh)["containers"]
        expected = sz.compute_plan(sz.Hardware(4, 16384), sz.instances_from_config(containers))
        self.assertEqual(code, 0)
        self.assertEqual(data["values"], expected.results[0].pg)
        self.assertEqual(data["role"], "test")
        self.assertEqual(data["container"], "test-db")
        self.assertEqual(data["base_profile"], "4cpu16gb")

    def test_pg_subcommand_for_a_new_container_uses_the_flag(self):
        path = self.config([])
        code, out, _ = self.pg("--role", "live", "--container", "live-db", "--config", path,
                               "--cpus", "4", "--ram-mib", "16384")
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(data["values"]["shared_buffers"], "4096MB")
        self.assertEqual(data["role"], "live")
        self.assertFalse(data["over_budget"])

    def test_pg_subcommand_without_a_config_file_is_an_empty_host(self):
        code, out, _ = self.pg("--role", "live", "--container", "live-db",
                               "--config", os.path.join(self.tmp, "none.yaml"),
                               "--cpus", "4", "--ram-mib", "16384")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["values"]["shared_buffers"], "4096MB")

    def test_pg_subcommand_over_budget_exits_zero_and_warns(self):
        path = self.config([("test-odoo", "test", CONF_FIT)])
        code, out, err = self.pg("--role", "live", "--container", "live-db", "--config", path,
                                 "--cpus", "2", "--ram-mib", "4096")
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertTrue(data["over_budget"])
        self.assertIn("over budget", err)
        self.assertTrue(data["values"])


if __name__ == "__main__":
    unittest.main()
