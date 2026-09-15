"""
Tests for scripts/container2backup.py: the --validate delegation to
ownerp_validate.py, the backup_path fallback that prevents a mid-run
KeyError when a service block omits it, and check_paths()'s split between
hard path issues (abort a non-interactive run, unchanged) and FastReport
path issues (a per-database WARNING since 4.9.0 - that database's SQL dump
and filestore still run, only its FastReport part is skipped).

Standard library only, like the rest of the suite. container2backup.py
imports both PyYAML and python-dotenv at module level, but none of the
functions under test touch them, so placeholders stand in when they are
absent (customer servers and CI have the real ones).

Run from the repository root:

    python3 -m unittest tests.test_container2backup -v
"""

import io
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
try:
    import yaml  # noqa: F401
except ImportError:
    sys.modules["yaml"] = types.ModuleType("yaml")
dotenv = types.ModuleType("dotenv")
dotenv.load_dotenv = lambda *args, **kwargs: None
sys.modules.setdefault("dotenv", dotenv)
import container2backup as c2b  # noqa: E402


class RunExternalValidationTest(unittest.TestCase):
    # NOTE: container2backup.py does a bare 'import os' and calls
    # os.path.isfile(...) / os.path.join(...) - there is no 'from os.path
    # import isfile' name to patch, so the patch target is c2b.os.path.isfile.

    def test_it_delegates_with_backup_flag_and_config_path(self):
        import subprocess
        recorded = {}

        def fake_run(argv, **kwargs):
            recorded["argv"] = argv
            return subprocess.CompletedProcess(argv, 0)

        with mock.patch.object(c2b.os.path, "isfile", return_value=True), \
             mock.patch.object(c2b.subprocess, "run", side_effect=fake_run):
            code = c2b.run_external_validation("/etc/my.yaml")

        self.assertEqual(code, 0)
        self.assertIn("--backup", recorded["argv"])
        self.assertIn("/etc/my.yaml", recorded["argv"])
        self.assertTrue(recorded["argv"][1].endswith("ownerp_validate.py"))

    def test_it_passes_the_validators_exit_code_through(self):
        import subprocess
        with mock.patch.object(c2b.os.path, "isfile", return_value=True), \
             mock.patch.object(c2b.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 1)):
            code = c2b.run_external_validation("/etc/my.yaml")
        self.assertEqual(code, 1)

    def test_a_missing_validator_exits_2_not_0(self):
        # container2backup.py has no older --validate behaviour to fall back
        # to, so silence must never look like a clean configuration - unlike
        # update_docker_odoo.py's (handled=False, 0), a missing validator here
        # is reported as "cannot check" via exit code 2.
        with mock.patch.object(c2b.os.path, "isfile", return_value=False):
            code = c2b.run_external_validation("/etc/my.yaml")
        self.assertEqual(code, 2)

    def test_the_validator_is_looked_for_beside_this_script(self):
        self.assertEqual(
            c2b.validator_path(),
            os.path.join(os.path.dirname(os.path.abspath(c2b.__file__)),
                         "ownerp_validate.py"))


class BackupAdditionalServiceTest(unittest.TestCase):
    def setUp(self):
        # backup_additional_service() calls compress_directory(), which does
        # real archive work - patch it out so these tests only exercise the
        # backup_path fallback / path-building logic.
        self.compress_patch = mock.patch.object(
            c2b, "compress_directory", return_value="/tmp/fake-archive.7z")
        self.compress_patch.start()
        self.addCleanup(self.compress_patch.stop)
        # backup_additional_service() reads the module-global 'config' (only
        # ever populated when the script runs as __main__) purely to pass it
        # through to the (here mocked) compress_directory - give it a value
        # so evaluating that argument does not NameError.
        self.config_patch = mock.patch.object(c2b, "config", {}, create=True)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.exists_patch = mock.patch.object(c2b.os.path, "exists", return_value=True)
        self.exists_patch.start()
        self.addCleanup(self.exists_patch.stop)
        self.makedirs_patch = mock.patch.object(c2b.os, "makedirs")
        self.makedirs_patch.start()
        self.addCleanup(self.makedirs_patch.stop)

    def test_falls_back_to_the_service_name_when_backup_path_is_absent(self):
        service_config = {"source_path": "/etc/nginx"}
        c2b.backup_additional_service(
            service_config, "/opt/backups", "2026-08-11_00-00-00", "nginx")

        self.assertEqual(
            c2b.compress_directory.call_args[0][1],
            "/opt/backups/nginx/nginx_2026-08-11_00-00-00")

    def test_prefers_an_explicit_backup_path_when_present(self):
        service_config = {
            "source_path": "/etc/nginx",
            "backup_path": "custom-subdir",
        }
        c2b.backup_additional_service(
            service_config, "/opt/backups", "2026-08-11_00-00-00", "nginx")

        self.assertEqual(
            c2b.compress_directory.call_args[0][1],
            "/opt/backups/custom-subdir/custom-subdir_2026-08-11_00-00-00")

    def test_a_missing_source_path_is_skipped_not_a_keyerror(self):
        # check_paths() warns about this before the run and aborts under cron
        # or on the interactive default, but an operator answering 'y' to
        # "continue anyway?" used to reach a bare service_config['source_path']
        # here and get an unhandled KeyError instead of the clean skip the
        # earlier warning implied.
        service_config = {"backup_path": "nginx"}
        c2b.backup_additional_service(
            service_config, "/opt/backups", "2026-08-11_00-00-00", "nginx")

        c2b.compress_directory.assert_not_called()


class CheckPathsTest(unittest.TestCase):
    """check_paths() must keep service path problems as hard `issues` (the
    caller aborts a non-interactive run over these, unchanged) while a
    database's fast_report problems go into the separate, non-aborting
    `fastreport_warnings` list."""

    def test_a_missing_service_source_path_is_a_hard_issue(self):
        config = {
            "services": {"nginx": {"enabled": True, "source_path": "/does/not/exist-xyz"}},
            "databases": [],
        }
        issues, fastreport_warnings = c2b.check_paths(config)
        self.assertEqual(len(issues), 1)
        self.assertIn("nginx", issues[0])
        self.assertEqual(fastreport_warnings, [])

    def test_a_missing_fastreport_path_is_a_warning_not_an_issue(self):
        config = {
            "services": {},
            "databases": [{
                "name": "live_db",
                "fast_report": {"enabled": True, "path": "/does/not/exist-xyz"},
            }],
        }
        issues, fastreport_warnings = c2b.check_paths(config)
        self.assertEqual(issues, [])
        self.assertEqual(len(fastreport_warnings), 1)
        self.assertIn("live_db", fastreport_warnings[0])

    def test_fastreport_enabled_without_a_path_is_also_a_warning(self):
        config = {
            "services": {},
            "databases": [{"name": "live_db", "fast_report": {"enabled": True}}],
        }
        issues, fastreport_warnings = c2b.check_paths(config)
        self.assertEqual(issues, [])
        self.assertEqual(len(fastreport_warnings), 1)
        self.assertIn("No fast-report path configured", fastreport_warnings[0])

    def test_a_disabled_fastreport_is_not_reported_at_all(self):
        config = {
            "services": {},
            "databases": [{
                "name": "live_db",
                "fast_report": {"enabled": False, "path": "/does/not/exist-xyz"},
            }],
        }
        issues, fastreport_warnings = c2b.check_paths(config)
        self.assertEqual((issues, fastreport_warnings), ([], []))

    def test_a_hard_issue_and_a_fastreport_warning_are_kept_apart(self):
        config = {
            "services": {"nginx": {"enabled": True, "source_path": "/does/not/exist-xyz"}},
            "databases": [{
                "name": "live_db",
                "fast_report": {"enabled": True, "path": "/also/missing-xyz"},
            }],
        }
        issues, fastreport_warnings = c2b.check_paths(config)
        self.assertEqual(len(issues), 1)
        self.assertEqual(len(fastreport_warnings), 1)

    def test_two_databases_each_report_their_own_fastreport_problem(self):
        config = {
            "services": {},
            "databases": [
                {"name": "live_db", "fast_report": {"enabled": True, "path": "/missing-a"}},
                {"name": "test_db", "fast_report": {"enabled": True, "path": "/missing-b"}},
            ],
        }
        issues, fastreport_warnings = c2b.check_paths(config)
        self.assertEqual(issues, [])
        self.assertEqual(len(fastreport_warnings), 2)
        joined = " ".join(fastreport_warnings)
        self.assertIn("live_db", joined)
        self.assertIn("test_db", joined)


class BackupFastReportTest(unittest.TestCase):
    """backup_fast_report() is what actually runs (or skips) a database's
    FastReport part; check_paths() only reports the problem up front."""

    def setUp(self):
        self.compress_patch = mock.patch.object(
            c2b, "compress_directory", return_value="/tmp/fake-fastreport.7z")
        self.compress_patch.start()
        self.addCleanup(self.compress_patch.stop)
        self.config_patch = mock.patch.object(c2b, "config", {}, create=True)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)

    def test_a_missing_path_is_skipped_with_a_warning_naming_the_database(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            result = c2b.backup_fast_report(
                "live_db", {"enabled": True, "path": "/does/not/exist-xyz"},
                "/opt/backups", "2026-09-15_00-00-00")
        self.assertFalse(result)
        c2b.compress_directory.assert_not_called()
        output = buf.getvalue()
        self.assertIn("live_db", output)
        self.assertIn("skipped", output)

    def test_no_path_at_all_is_skipped_with_a_warning_naming_the_database(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            result = c2b.backup_fast_report(
                "live_db", {"enabled": True}, "/opt/backups", "2026-09-15_00-00-00")
        self.assertFalse(result)
        c2b.compress_directory.assert_not_called()
        self.assertIn("skipped", buf.getvalue())

    def test_an_existing_path_still_runs_the_fastreport_backup(self):
        with tempfile.TemporaryDirectory() as report_dir:
            result = c2b.backup_fast_report(
                "live_db", {"enabled": True, "path": report_dir},
                "/opt/backups", "2026-09-15_00-00-00")
        self.assertTrue(result)
        c2b.compress_directory.assert_called_once()


if __name__ == "__main__":
    unittest.main()
