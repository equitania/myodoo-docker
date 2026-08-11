"""
Tests for scripts/container2backup.py: the --validate delegation to
ownerp_validate.py, and the backup_path fallback that prevents a mid-run
KeyError when a service block omits it.

Standard library only, like the rest of the suite. container2backup.py
imports both PyYAML and python-dotenv at module level, but none of the
functions under test touch them, so placeholders stand in when they are
absent (customer servers and CI have the real ones).

Run from the repository root:

    python3 -m unittest tests.test_container2backup -v
"""

import os
import sys
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


if __name__ == "__main__":
    unittest.main()
