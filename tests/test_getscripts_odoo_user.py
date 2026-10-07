"""
Tests for ensure_odoo_host_user() in getScripts.py (v9.29.0).

The Odoo images create their odoo user with UID/GID 8069. getScripts gives
that number a name on the host so `ls -l` on a data volume reads "odoo" - and
only creates, never changes: an existing account belongs to someone.

Standard library only. See test_getscripts_output.py for why HOME is
redirected around the import and why a placeholder stands in for `requests`.

Run from the repository root:

    python3 -m unittest tests.test_getscripts_odoo_user -v
"""

import grp
import os
import pwd
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

_REAL_HOME = os.environ.get("HOME")
os.environ["HOME"] = tempfile.mkdtemp(prefix="getscripts-test-home-")

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, REPO)
try:
    import requests  # noqa: F401
except ImportError:
    sys.modules["requests"] = types.ModuleType("requests")
import getScripts as gs  # noqa: E402

if _REAL_HOME is not None:
    os.environ["HOME"] = _REAL_HOME


def account(name, uid):
    return types.SimpleNamespace(pw_name=name, pw_uid=uid)


def group(name, gid):
    return types.SimpleNamespace(gr_name=name, gr_gid=gid)


class EnsureOdooHostUserTest(unittest.TestCase):
    def setUp(self):
        self.commands = []
        gs._install_report.clear()

    def tearDown(self):
        gs._install_report.clear()

    def _run(self, users=(), groups=(), euid=0, returncode=0):
        """Run ensure_odoo_host_user against a fake account database."""
        def by(items, index):
            def look(key):
                for item in items:
                    if item[index] == key:
                        return item[2]
                raise KeyError(key)
            return look

        user_rows = [(u.pw_name, u.pw_uid, u) for u in users]
        group_rows = [(g.gr_name, g.gr_gid, g) for g in groups]

        def run_command(command, **_kwargs):
            self.commands.append(command)
            return subprocess.CompletedProcess(command, returncode, b"", b"boom")

        with mock.patch.object(gs.os, "geteuid", return_value=euid), \
             mock.patch.object(pwd, "getpwuid", side_effect=by(user_rows, 1)), \
             mock.patch.object(pwd, "getpwnam", side_effect=by(user_rows, 0)), \
             mock.patch.object(grp, "getgrgid", side_effect=by(group_rows, 1)), \
             mock.patch.object(grp, "getgrnam", side_effect=by(group_rows, 0)), \
             mock.patch.object(gs, "run_command", side_effect=run_command):
            gs.ensure_odoo_host_user()
        return gs._install_report[-1][1]

    def test_creates_group_and_user_when_both_are_missing(self):
        self.assertEqual(self._run(), "installed")
        self.assertEqual(self.commands[0], "groupadd -g 8069 odoo")
        self.assertIn("useradd -u 8069 -g 8069", self.commands[1])
        self.assertIn("-s /usr/sbin/nologin", self.commands[1])
        self.assertIn("-M", self.commands[1])

    def test_an_existing_matching_user_is_ok(self):
        self.assertEqual(self._run(users=[account("odoo", 8069)],
                                   groups=[group("odoo", 8069)]), "ok")
        self.assertEqual(self.commands, [])

    def test_an_existing_group_is_reused(self):
        self.assertEqual(self._run(groups=[group("odoo", 8069)]), "installed")
        self.assertEqual(len(self.commands), 1)
        self.assertTrue(self.commands[0].startswith("useradd"))

    def test_an_odoo_user_with_another_uid_is_left_alone(self):
        """A native Odoo installation may own that account."""
        self.assertEqual(self._run(users=[account("odoo", 115)]), "skipped")
        self.assertEqual(self.commands, [])

    def test_another_owner_of_8069_is_left_alone(self):
        self.assertEqual(self._run(users=[account("someone", 8069)]), "skipped")
        self.assertEqual(self.commands, [])

    def test_a_foreign_group_with_gid_8069_is_left_alone(self):
        self.assertEqual(self._run(groups=[group("other", 8069)]), "skipped")
        self.assertEqual(self.commands, [])

    def test_an_odoo_group_with_another_gid_is_left_alone(self):
        self.assertEqual(self._run(groups=[group("odoo", 1001)]), "skipped")
        self.assertEqual(self.commands, [])

    def test_needs_root(self):
        self.assertEqual(self._run(euid=1000), "skipped")
        self.assertEqual(self.commands, [])

    def test_a_failed_useradd_is_reported_not_raised(self):
        self.assertEqual(self._run(groups=[group("odoo", 8069)], returncode=1), "failed")

    def test_the_uid_matches_the_dockerfiles(self):
        for version in ("16", "18", "19"):
            path = os.path.join(REPO, "Dockerfiles", f"v{version}-odoo", "Dockerfile")
            with open(path, encoding="utf-8") as handle:
                self.assertIn(f"--uid {gs.ODOO_HOST_UID} --gid {gs.ODOO_HOST_UID}",
                              handle.read(), path)


if __name__ == "__main__":
    unittest.main()
