"""
Tests for ownerp_pull_update.py, the pull-update agent.

Standard library only. The release manager is replaced by a recording fake of
api(), update_docker_odoo.py by a tiny script that echoes its arguments and
exits with a chosen code - no network, no Docker.

Run from the repository root:

    python3 -m unittest tests.test_ownerp_pull_update -v
"""

import copy
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
try:
    import yaml  # noqa: F401
except ImportError:
    sys.modules["yaml"] = types.ModuleType("yaml")
import ownerp_pull_update as pull  # noqa: E402

BASE = "https://rm.example.invalid"
ENV = {"RM_PULL_URL": BASE, "RM_PULL_MODULE_HOST": "modules.example.invalid"}
CONTAINER = {"container_name": "web1", "database_name": "web1_db", "odoo_version": "19.0"}
JOB = {
    "run_id": 7,
    "instance": "web1_db",
    "odoo_version": "19.0",
    "docker_image": "myodoo/prepare-v19:26.10.13-3.12.15",
    "kernel": {"zip": "odoo-kernel-19.0.zip", "url": "https://modules.example.invalid/19.0/odoo-kernel-19.0.zip"},
    "modules": [
        {
            "name": "account",
            "version": "19.0.1.2.3",
            "zip": "account-19.0.1.2.3.zip",
            "url": "https://modules.example.invalid/19.0/account-19.0.1.2.3.zip",
        }
    ],
}


class FakeApi:
    """Answers like the release manager and records every call."""

    def __init__(self, job_status=200, job=None):
        self.calls = []
        self.job_status = job_status
        self.job = copy.deepcopy(JOB) if job is None else job

    def __call__(self, base_url, token, method, path, body=None):
        self.calls.append((method, path, body))
        if path.endswith("/job"):
            return self.job_status, (self.job if self.job_status == 200 else None)
        return 204, None

    def paths(self):
        return [path for _method, path, _body in self.calls]

    def finish_body(self):
        return [body for _method, path, body in self.calls if path.endswith("/finish")][0]


class CheckJobTest(unittest.TestCase):
    def check(self, **changes):
        job = copy.deepcopy(JOB)
        job.update(changes)
        return pull.check_job(job, CONTAINER, ENV, BASE)

    def test_a_valid_job_becomes_release_lines(self):
        self.assertEqual(
            self.check(),
            [
                "https://modules.example.invalid/19.0",
                "myodoo/prepare-v19:26.10.13-3.12.15",
                "odoo-kernel-19.0.zip",
                "account-19.0.1.2.3.zip",
            ],
        )

    def test_jobs_that_do_not_fit_this_server_are_refused(self):
        evil_module = dict(JOB["modules"][0], zip="../evil.zip", url="https://modules.example.invalid/19.0/../evil.zip")
        other_host = dict(JOB["modules"][0], url="https://attacker.example.invalid/19.0/account-19.0.1.2.3.zip")
        plain_http = {
            "zip": "odoo-kernel-19.0.zip",
            "url": "http://modules.example.invalid/19.0/odoo-kernel-19.0.zip",
        }
        cases = {
            "other database": {"instance": "someone_else"},
            "other odoo version": {"odoo_version": "18.0"},
            "foreign image": {"docker_image": "evil/odoo:1"},
            "image with a space": {"docker_image": "myodoo/x 1"},
            "path in a zip name": {"modules": [evil_module]},
            "other host": {"modules": [other_host]},
            "plain http": {"kernel": plain_http, "modules": []},
            "no kernel": {"kernel": {}},
            "no run id": {"run_id": "7"},
        }
        for label, changes in cases.items():
            with self.assertRaises(pull.Refused, msg=label):
                self.check(**changes)

    def test_the_module_host_defaults_to_the_release_manager(self):
        job = copy.deepcopy(JOB)
        job["kernel"]["url"] = BASE + "/19.0/odoo-kernel-19.0.zip"
        job["modules"][0]["url"] = BASE + "/19.0/account-19.0.1.2.3.zip"
        self.assertTrue(pull.check_job(job, CONTAINER, {"RM_PULL_URL": BASE}, BASE))


class ConfigTest(unittest.TestCase):
    def test_token_key(self):
        self.assertEqual(pull.token_key("web-1.prod"), "RM_PULL_TOKEN_WEB_1_PROD")

    def test_read_env_and_configured_instances(self):
        path = os.path.join(tempfile.mkdtemp(), ".env")
        with open(path, "w", encoding="utf8") as handle:
            handle.write("# comment\nRM_PULL_URL=https://rm.example.invalid\nRM_PULL_TOKEN_WEB1='abc'\n\n")
        env = pull.read_env((path,))
        self.assertEqual(env["RM_PULL_TOKEN_WEB1"], "abc")
        containers = [CONTAINER, {"container_name": "web2", "database_name": "web2_db"}]
        self.assertEqual(pull.configured_instances(env, containers), [(CONTAINER, "abc")])

    def test_unconfigured_server_does_nothing_quietly(self):
        original = pull.read_env
        pull.read_env = lambda paths=None: {}
        try:
            self.assertEqual(pull.main([]), 0)
        finally:
            pull.read_env = original


class ProcessInstanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.original_api = pull.api
        self.original_work = pull.WORK_DIR
        pull.WORK_DIR = os.path.join(self.tmp, "work")
        self.out = []

    def tearDown(self):
        pull.api = self.original_api
        pull.WORK_DIR = self.original_work

    def runner(self, exit_code):
        path = os.path.join(self.tmp, "fake_doup.py")
        with open(path, "w", encoding="utf8") as handle:
            handle.write(
                "import sys\n"
                "args = sys.argv[1:]\n"
                "release = open(args[args.index('--release-file') + 1]).read()\n"
                "print('ARGS', ' '.join(args))\n"
                "print('RELEASE', release.replace(chr(10), '|'))\n"
                "sys.exit(%d)\n" % exit_code
            )
        return path

    def process(self, fake, exit_code=0):
        pull.api = fake
        return pull.process_instance(CONTAINER, "tok", ENV, BASE, runner=self.runner(exit_code), out=self.out.append)

    def test_nothing_to_do(self):
        fake = FakeApi(job_status=204)
        self.assertEqual(self.process(fake), 0)
        self.assertEqual(fake.paths(), ["/rm/api/v1/job"])

    def test_a_job_is_carried_out_with_the_release_file(self):
        fake = FakeApi()
        self.assertEqual(self.process(fake), 0)
        self.assertEqual(fake.paths(), ["/rm/api/v1/job", "/rm/api/v1/runs/7/start", "/rm/api/v1/runs/7/finish"])
        body = fake.finish_body()
        self.assertEqual(body["exit_code"], 0)
        self.assertIn("-s web1 --release-file", body["log"])
        self.assertIn("RELEASE https://modules.example.invalid/19.0|myodoo/prepare-v19", body["log"])
        # The release file is removed after the run.
        self.assertEqual(os.listdir(pull.WORK_DIR), [])

    def test_a_failed_update_is_reported_with_its_exit_code(self):
        fake = FakeApi()
        self.assertEqual(self.process(fake, exit_code=1), 1)
        self.assertEqual(fake.finish_body()["exit_code"], 1)

    def test_a_refused_job_is_reported_and_not_run(self):
        job = copy.deepcopy(JOB)
        job["instance"] = "someone_else"
        fake = FakeApi(job=job)
        self.assertEqual(self.process(fake), 1)
        body = fake.finish_body()
        self.assertEqual(body["exit_code"], 2)
        self.assertIn("Refused", body["log"])
        self.assertNotIn("ARGS", body["log"])

    def test_an_unauthorised_token_is_reported(self):
        fake = FakeApi(job_status=401)
        self.assertEqual(self.process(fake), 1)
        self.assertIn("401", self.out[0])

    def test_long_output_keeps_its_end(self):
        text = "x" * (pull.LOG_LIMIT + 50) + "END"
        cut = pull.tail(text)
        self.assertTrue(cut.endswith("END"))
        self.assertLess(len(cut), pull.LOG_LIMIT + 100)


if __name__ == "__main__":
    unittest.main()
