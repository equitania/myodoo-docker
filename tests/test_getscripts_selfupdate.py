"""
Tests for getScripts.py's self-update-and-restart (self_update_and_reexec()).

Without this, a newer getScripts.py pulled by `ups` only takes effect on the
NEXT `ups` - this run keeps executing the old code already loaded into the
interpreter. self_update_and_reexec() detects a newer version in the freshly
pulled repository, replaces the running script with it, and restarts the
process via os.execv() - once, not in a loop, and without a second network
pull for the update_repository() call at main()'s usual call site.

No network, no real os.execv, no real git repository: update_repository()'s
git calls go through subprocess.check_output()/run_command()/_run_git_network(),
all mocked here; the running script and the "repository" are plain temp
directories. Standard library only, like the rest of the suite - see
test_getscripts_output.py for why HOME is redirected around the import and why
a placeholder stands in for `requests`.

Run from the repository root:

    python3 -m unittest tests.test_getscripts_selfupdate -v
"""

import inspect
import io
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

_REAL_HOME = os.environ.get("HOME")
os.environ["HOME"] = tempfile.mkdtemp(prefix="getscripts-test-home-")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
try:
    import requests  # noqa: F401
except ImportError:
    sys.modules["requests"] = types.ModuleType("requests")
import getScripts as gs  # noqa: E402

if _REAL_HOME is not None:
    os.environ["HOME"] = _REAL_HOME


# self_update_and_reexec() compares the repository's version against the
# SCRIPT_VERSION constant of the process actually running - not against
# anything written into the fake "running file" on disk - so these are
# derived from gs.SCRIPT_VERSION rather than hardcoded, and stay correct
# whenever that constant is next bumped.
RUNNING_VERSION = gs.SCRIPT_VERSION
OLDER_VERSION = "0.0.1"
NEWER_VERSION = f"{int(gs.SCRIPT_VERSION.split('.')[0]) + 1}.0.0"


def fake_check_output(head_values, branch="2026"):
    """Stand-in for subprocess.check_output() inside update_repository():
    every "--abbrev-ref" query reports branch, every "rev-parse HEAD" query
    pops the next value off head_values - repeating the last one once the
    list is down to a single entry, so a test only has to list what changes."""
    calls = []
    remaining = list(head_values)

    def _side_effect(args, **kwargs):
        calls.append(args)
        if "--abbrev-ref" in args:
            return f"{branch}\n"
        value = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return f"{value}\n"

    return _side_effect, calls


class SelfUpdateTestBase(unittest.TestCase):
    """Common fixture: a fake "running" getScripts.py and a fake ~/myodoo-docker
    repository, both plain temp directories - self_update_and_reexec() never
    learns the difference because __file__ and the home resolution are
    patched to point at them."""

    def setUp(self):
        # realpath() right away: on macOS, tempfile.mkdtemp() returns a path
        # under /var, itself a symlink to /private/var - self_update_and_
        # reexec() calls os.path.realpath(__file__), so an assertion against
        # the raw mkdtemp() path would flake on exactly that platform.
        self.server_home = os.path.realpath(tempfile.mkdtemp(prefix="getscripts-selfupdate-home-"))
        self.addCleanup(shutil.rmtree, self.server_home, ignore_errors=True)
        self.repo_dir = os.path.join(self.server_home, "myodoo-docker")
        os.makedirs(self.repo_dir)

        self.running_dir = os.path.realpath(tempfile.mkdtemp(prefix="getscripts-selfupdate-running-"))
        self.addCleanup(shutil.rmtree, self.running_dir, ignore_errors=True)
        self.running_path = os.path.join(self.running_dir, "getScripts.py")
        self.write_running_script(RUNNING_VERSION)
        os.chmod(self.running_path, 0o755)

        self._orig_file = gs.__file__
        gs.__file__ = self.running_path
        self.addCleanup(self._restore_file)

        home_patch = mock.patch.object(
            gs, "_resolve_target_home_for_self_update", return_value=self.server_home
        )
        home_patch.start()
        self.addCleanup(home_patch.stop)

        repo_state_patch = mock.patch.dict(
            gs._REPO_PULL_STATE, {"pulled": False, "prev_head": None, "reported": False}
        )
        repo_state_patch.start()
        self.addCleanup(repo_state_patch.stop)

        env_patch = mock.patch.dict(os.environ, {}, clear=False)
        env_patch.start()
        os.environ.pop("GETSCRIPTS_REEXECED", None)
        os.environ.pop("GETSCRIPTS_PREV_HEAD", None)
        self.addCleanup(env_patch.stop)

        self.statuses = []
        status_patch = mock.patch.object(gs, "status", side_effect=lambda m: self.statuses.append(m))
        status_patch.start()
        self.addCleanup(status_patch.stop)

    def _restore_file(self):
        gs.__file__ = self._orig_file

    def write_running_script(self, version):
        with open(self.running_path, "w", encoding="utf-8") as f:
            f.write(f'SCRIPT_VERSION = "{version}"\n')

    def write_repo_script(self, version_line):
        """version_line is written verbatim after a comment line, so a test
        can pass an unparsable value too."""
        with open(os.path.join(self.repo_dir, "getScripts.py"), "w", encoding="utf-8") as f:
            f.write("# repository copy\n")
            f.write(version_line + "\n")

    def running_content(self):
        with open(self.running_path, encoding="utf-8") as f:
            return f.read()

    def running_mode(self):
        return os.stat(self.running_path).st_mode


class NoRepositoryOrSelfSkipTest(SelfUpdateTestBase):
    """Cases where self_update_and_reexec() must do nothing at all."""

    def test_reexeced_loop_guard_skips_before_touching_anything(self):
        os.environ["GETSCRIPTS_REEXECED"] = "1"
        with mock.patch.object(gs, "update_repository") as update_repo, \
             mock.patch("os.execv") as execv:
            gs.self_update_and_reexec()
        update_repo.assert_not_called()
        execv.assert_not_called()

    def test_missing_repository_skips_the_fresh_install_path_untouched(self):
        shutil.rmtree(self.repo_dir)
        with mock.patch.object(gs, "update_repository") as update_repo, \
             mock.patch("os.execv") as execv:
            gs.self_update_and_reexec()
        update_repo.assert_not_called()
        execv.assert_not_called()

    def test_running_from_inside_the_repository_itself_is_skipped(self):
        gs.__file__ = os.path.join(self.repo_dir, "getScripts.py")
        self.write_repo_script(f'SCRIPT_VERSION = "{NEWER_VERSION}"')
        with mock.patch.object(gs, "update_repository") as update_repo, \
             mock.patch("os.execv") as execv:
            gs.self_update_and_reexec()
        update_repo.assert_not_called()
        execv.assert_not_called()


class VersionCompareTest(SelfUpdateTestBase):
    """No replace, no restart unless the repository is STRICTLY newer."""

    def _run(self):
        with mock.patch.object(gs, "update_repository") as update_repo, \
             mock.patch("os.execv") as execv:
            gs.self_update_and_reexec()
        update_repo.assert_called_once_with(self.repo_dir, gs.SERVER_BRANCH)
        return execv

    def test_equal_version_does_not_reexec(self):
        self.write_repo_script(f'SCRIPT_VERSION = "{RUNNING_VERSION}"')
        execv = self._run()
        execv.assert_not_called()
        self.assertEqual(self.running_content(), f'SCRIPT_VERSION = "{RUNNING_VERSION}"\n')

    def test_older_version_does_not_reexec(self):
        self.write_repo_script(f'SCRIPT_VERSION = "{OLDER_VERSION}"')
        execv = self._run()
        execv.assert_not_called()

    def test_unparsable_version_does_not_reexec(self):
        self.write_repo_script('SCRIPT_VERSION = "not-a-version"')
        execv = self._run()
        execv.assert_not_called()

    def test_missing_version_line_does_not_reexec(self):
        with open(os.path.join(self.repo_dir, "getScripts.py"), "w", encoding="utf-8") as f:
            f.write("# no SCRIPT_VERSION here at all\n")
        execv = self._run()
        execv.assert_not_called()


class NewerVersionReexecTest(SelfUpdateTestBase):
    """The main case: a newer repository version replaces the running script
    and restarts the process exactly once."""

    def test_file_replaced_atomically_with_mode_preserved_and_execv_called_once(self):
        self.write_repo_script(f'SCRIPT_VERSION = "{NEWER_VERSION}"')
        gs._REPO_PULL_STATE["prev_head"] = "deadbeef"
        sys_argv_backup = sys.argv[:]
        sys.argv = ["/whatever/getScripts.py", "--dns-check"]
        try:
            with mock.patch.object(gs, "update_repository") as update_repo, \
                 mock.patch("os.execv") as execv:
                gs.self_update_and_reexec()
        finally:
            sys.argv = sys_argv_backup

        update_repo.assert_called_once_with(self.repo_dir, gs.SERVER_BRANCH)
        execv.assert_called_once_with(
            sys.executable, [sys.executable, self.running_path, "--dns-check"]
        )
        self.assertIn(f'SCRIPT_VERSION = "{NEWER_VERSION}"', self.running_content())
        self.assertEqual(self.running_mode(), 0o100755)
        self.assertEqual(os.environ.get("GETSCRIPTS_REEXECED"), "1")
        self.assertEqual(os.environ.get("GETSCRIPTS_PREV_HEAD"), "deadbeef")
        self.assertTrue(any(RUNNING_VERSION in s and NEWER_VERSION in s for s in self.statuses))

    def test_no_temp_file_left_behind_after_a_successful_replace(self):
        self.write_repo_script(f'SCRIPT_VERSION = "{NEWER_VERSION}"')
        with mock.patch.object(gs, "update_repository"), mock.patch("os.execv"):
            gs.self_update_and_reexec()
        leftovers = [n for n in os.listdir(self.running_dir) if n != "getScripts.py"]
        self.assertEqual(leftovers, [])


class FailureModesTest(SelfUpdateTestBase):
    """Every failure is a warning on the current process, never a crash and
    never a restart with half-applied state."""

    def test_repository_update_failure_warns_and_does_not_reexec(self):
        self.write_repo_script(f'SCRIPT_VERSION = "{NEWER_VERSION}"')
        with mock.patch.object(gs, "update_repository", side_effect=RuntimeError("boom")), \
             mock.patch("os.execv") as execv, \
             mock.patch.object(gs.logger, "warning") as warning:
            gs.self_update_and_reexec()
        execv.assert_not_called()
        self.assertTrue(warning.called)
        self.assertEqual(self.running_content(), f'SCRIPT_VERSION = "{RUNNING_VERSION}"\n')

    def test_file_replace_failure_leaves_the_original_untouched(self):
        self.write_repo_script(f'SCRIPT_VERSION = "{NEWER_VERSION}"')
        original = self.running_content()
        with mock.patch.object(gs, "update_repository"), \
             mock.patch("os.replace", side_effect=OSError("disk full")), \
             mock.patch("os.execv") as execv, \
             mock.patch.object(gs.logger, "warning") as warning:
            gs.self_update_and_reexec()
        execv.assert_not_called()
        self.assertTrue(warning.called)
        self.assertEqual(self.running_content(), original)
        self.assertNotIn("GETSCRIPTS_REEXECED", os.environ)
        # mkstemp's temp file must not survive a failed replace either.
        leftovers = [n for n in os.listdir(self.running_dir) if n != "getScripts.py"]
        self.assertEqual(leftovers, [])


class UpdateRepositoryReexecReportingTest(unittest.TestCase):
    """update_repository() itself, called from main()'s usual call site in the
    process self_update_and_reexec() just re-exec'd into: it must not pull
    again, but must still show the commit list once, using GETSCRIPTS_PREV_HEAD."""

    def setUp(self):
        self.addCleanup(mock.patch.dict(
            gs._REPO_PULL_STATE, {"pulled": False, "prev_head": None, "reported": False}
        ).stop)
        mock.patch.dict(
            gs._REPO_PULL_STATE, {"pulled": False, "prev_head": None, "reported": False}
        ).start()
        env_patch = mock.patch.dict(os.environ, {"GETSCRIPTS_REEXECED": "1",
                                                  "GETSCRIPTS_PREV_HEAD": "oldhash"})
        env_patch.start()
        self.addCleanup(env_patch.stop)

    def test_no_pull_but_commit_list_reported_once_from_prev_head_env(self):
        run_calls = []

        def fake_run_command(command, **kwargs):
            run_calls.append(command)
            return types.SimpleNamespace(returncode=0, stdout=b"abc123 a commit\n", stderr=b"")

        statuses = []
        side_effect, _ = fake_check_output(["newhash"])

        with mock.patch.object(gs, "run_command", side_effect=fake_run_command), \
             mock.patch.object(gs, "_run_git_network") as run_git_network, \
             mock.patch.object(gs, "status", side_effect=lambda m: statuses.append(m)), \
             mock.patch("os.path.exists", return_value=True), \
             mock.patch("os.chdir"), \
             mock.patch.object(gs.subprocess, "check_output", side_effect=side_effect):
            gs.update_repository("/fake/myodoo-docker", "2026")

        run_git_network.assert_not_called()  # no network pull in the reexec'd process
        pull_run_calls = [c for c in run_calls if c.strip().endswith("pull")]
        self.assertEqual(pull_run_calls, [])
        joined = "\n".join(statuses)
        self.assertIn("Repository updated, new changes downloaded", joined)
        self.assertTrue(gs._REPO_PULL_STATE["reported"])

    def test_calling_it_again_in_the_same_process_does_not_report_twice(self):
        def fake_run_command(command, **kwargs):
            return types.SimpleNamespace(returncode=0, stdout=b"abc123 a commit\n", stderr=b"")

        statuses = []
        side_effect, _ = fake_check_output(["newhash"])

        with mock.patch.object(gs, "run_command", side_effect=fake_run_command), \
             mock.patch.object(gs, "_run_git_network") as run_git_network, \
             mock.patch.object(gs, "status", side_effect=lambda m: statuses.append(m)), \
             mock.patch("os.path.exists", return_value=True), \
             mock.patch("os.chdir"), \
             mock.patch.object(gs.subprocess, "check_output", side_effect=side_effect):
            gs.update_repository("/fake/myodoo-docker", "2026")
            gs.update_repository("/fake/myodoo-docker", "2026")

        run_git_network.assert_not_called()
        self.assertEqual(
            sum(1 for s in statuses if "Repository updated" in s), 1
        )


class MainCallOrderTest(unittest.TestCase):
    """self_update_and_reexec() must run after the proxy is restored but
    before setup_environment() and the first install step (pip) - anything
    later would otherwise happen twice for one `ups` when a restart occurs."""

    def test_self_update_runs_between_proxy_restore_and_setup_environment(self):
        source = inspect.getsource(gs.main)
        ensure_pos = source.index("ensure_proxy_environment()")
        self_update_pos = source.index("self_update_and_reexec()")
        setup_pos = source.index("setup_environment()")
        upgrade_pip_pos = source.index("upgrade_pip()")

        self.assertLess(ensure_pos, self_update_pos)
        self.assertLess(self_update_pos, setup_pos)
        self.assertLess(self_update_pos, upgrade_pip_pos)


if __name__ == "__main__":
    unittest.main()
