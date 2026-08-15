"""
Tests for what copy_scripts() delivers to a server.

The bug this pins: ownerp_cron.py and ownerp_migrate.py were committed without
the execute bit. `cp` carries the source mode over, so they arrived on the
server unexecutable and both `docron` and the reconstruction died with "exists
but is not an executable file" — on the customer's terminal, at the moment they
were needed.

getScripts.py sets the bit at delivery time now, but that is the safety net.
This is the fix: a script that declares an interpreter must be committed
executable, and a delivered script must actually exist.

Run from the repository root:

    python3 -m unittest tests.test_delivered_scripts -v
"""

import os
import re
import subprocess
import sys
import tempfile
import types
import unittest

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SCRIPTS = os.path.join(REPO, "scripts")
GETSCRIPTS = os.path.join(REPO, "getScripts.py")

# Same preamble as test_getscripts_output.py, for the same two reasons: the
# script imports `requests` at module level (nothing here touches it), and it
# opens its log file at import time — a test run must not append to the
# operator's real ~/getscripts.log.
_REAL_HOME = os.environ.get("HOME")
os.environ["HOME"] = tempfile.mkdtemp(prefix="delivered-scripts-test-home-")

sys.path.insert(0, REPO)
try:
    import requests  # noqa: F401
except ImportError:
    sys.modules["requests"] = types.ModuleType("requests")
import getScripts as gs  # noqa: E402

if _REAL_HOME is not None:
    os.environ["HOME"] = _REAL_HOME


def delivered_names():
    """The file list copy_scripts() walks, read from the source."""
    with open(GETSCRIPTS, "r", encoding="utf-8") as handle:
        text = handle.read()
    block = re.search(r"def copy_scripts\(.*?\n    scripts = \[(.*?)\]",
                      text, re.DOTALL)
    assert block, "copy_scripts() no longer has a literal script list"
    return re.findall(r'"([^"]+)"', block.group(1))


def has_shebang(path):
    with open(path, "rb") as handle:
        return handle.read(2) == b"#!"


def git_mode(relative):
    output = subprocess.run(["git", "-C", REPO, "ls-files", "-s", relative],
                            capture_output=True, text=True, check=False).stdout
    return output.split()[0] if output.strip() else None


class DeliveredScriptsTest(unittest.TestCase):
    def test_every_delivered_file_exists(self):
        missing = []
        for name in delivered_names():
            source = (GETSCRIPTS if name == "getScripts.py"
                      else os.path.join(SCRIPTS, name))
            if not os.path.isfile(source):
                missing.append(name)
        self.assertEqual(missing, [],
                         f"copy_scripts() delivers files that do not exist: {missing}")

    def test_every_shebang_script_is_committed_executable(self):
        """Otherwise the alias that calls it dies on the customer's terminal."""
        not_executable = []
        for name in delivered_names():
            relative = ("getScripts.py" if name == "getScripts.py"
                        else f"scripts/{name}")
            source = os.path.join(REPO, relative)
            if not os.path.isfile(source) or not has_shebang(source):
                continue
            mode = git_mode(relative)
            if mode and mode != "100755":
                not_executable.append(f"{relative} ({mode})")
        self.assertEqual(not_executable, [],
                         "committed without the execute bit: "
                         + ", ".join(not_executable))

    def test_the_new_tools_are_on_the_delivery_list(self):
        delivered = delivered_names()
        for name in ("ownerp_cron.py", "ownerp_migrate.py",
                     "nginx-cert-guard.py", "server-readiness.py"):
            self.assertIn(name, delivered)


class DeliveryHardeningTest(unittest.TestCase):
    def test_delivery_repairs_a_missing_execute_bit(self):
        """The safety net, exercised: shebang in, execute bit out."""
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "thing.py")
            with open(script, "w", encoding="utf-8") as handle:
                handle.write("#!/usr/bin/python3\nprint('hi')\n")
            os.chmod(script, 0o644)
            gs._ensure_executable(script)
            self.assertTrue(os.stat(script).st_mode & 0o111)

    def test_delivery_leaves_data_files_alone(self):
        """myodoo-maintenance.cron is delivered by the same loop and is not code."""
        with tempfile.TemporaryDirectory() as tmp:
            data = os.path.join(tmp, "some.cron")
            with open(data, "w", encoding="utf-8") as handle:
                handle.write("0 2 * * * root /root/thing.py\n")
            os.chmod(data, 0o644)
            gs._ensure_executable(data)
            self.assertFalse(os.stat(data).st_mode & 0o111)

    def test_an_unreadable_file_does_not_stop_the_delivery(self):
        """One bad file must not abort copy_scripts() for everything after it."""
        gs._ensure_executable(os.path.join(tempfile.gettempdir(), "does-not-exist"))


if __name__ == "__main__":
    unittest.main()


class RetiredScriptsTest(unittest.TestCase):
    """Withdrawing a script has to reach servers that already exist.

    Taking a name off the copy_scripts() list stops it being delivered; it
    does not remove the copy already sitting in $HOME. cleanup_legacy.txt does
    not close that gap either — it only runs on a fresh Fish installation, so
    on every server that already had Fish the retired script would outlive its
    replacement, with an alias possibly still pointing at it.
    """

    def test_retired_scripts_are_no_longer_delivered(self):
        delivered = delivered_names()
        for name in gs.RETIRED_SCRIPTS:
            self.assertNotIn(name, delivered,
                             f"{name} is both retired and delivered")

    def test_the_tui_is_retired_and_gone_from_the_repository(self):
        self.assertIn("ownerp_tui.py", gs.RETIRED_SCRIPTS)
        self.assertFalse(os.path.exists(os.path.join(SCRIPTS, "ownerp_tui.py")))

    def test_every_retired_entry_carries_a_reason(self):
        """The log line an operator sees has to say what replaced it."""
        for name, reason in gs.RETIRED_SCRIPTS.items():
            self.assertTrue(reason.strip(), f"{name} has no reason")

    def test_removal_is_not_gated_on_a_fresh_install(self):
        with open(GETSCRIPTS, "r", encoding="utf-8") as handle:
            text = handle.read()
        call = text.index("remove_retired_scripts(_myhome)",
                          text.index("copy_scripts(_myhome"))
        gate = text.index("if fish_is_fresh_install:")
        self.assertLess(call, gate,
                        "retired scripts must be removed on every run")

    def test_a_delivered_script_is_never_on_the_legacy_cleanup_list(self):
        """restore-zip.sh was on both: delivered, then deleted by the same run."""
        with open(os.path.join(REPO, "cleanup_legacy.txt"),
                  encoding="utf-8") as handle:
            listed = {line.strip() for line in handle
                      if line.strip() and not line.startswith("#")}
        clash = sorted(set(delivered_names()) & listed)
        self.assertEqual(clash, [],
                         f"delivered and then deleted on a fresh install: {clash}")

    def test_removing_a_retired_script_is_not_fatal_when_it_is_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            gs.remove_retired_scripts(tmp)

    def test_a_present_retired_script_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            victim = os.path.join(tmp, "ownerp_tui.py")
            with open(victim, "w", encoding="utf-8") as handle:
                handle.write("#!/usr/bin/python3\n")
            gs.remove_retired_scripts(tmp)
            self.assertFalse(os.path.exists(victim))


class VersionHeaderTest(unittest.TestCase):
    """A script's comment header must agree with the constant it prints.

    This has now gone wrong twice: ownerp_cron.py (commit aa29034) and
    docker_table.py (15.08.2026). It is a cosmetic bug with an operational
    cost — the header is what a reader sees when they open the file, and the
    constant is what lands in a pasted log. When the two disagree, a support
    conversation starts from the wrong version and everything reasoned from it
    is off.

    Only files carrying BOTH are checked; a script may legitimately have just
    one of them.
    """

    HEADER = re.compile(r'^#\s*Version[: ]\s*([0-9]+\.[0-9]+\.[0-9]+)', re.M)
    CONSTANT = re.compile(
        r'^(?:SCRIPT_VERSION|_VERSION)\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"', re.M)

    def test_every_header_matches_its_constant(self):
        mismatches = []
        for name in sorted(os.listdir(SCRIPTS)):
            path = os.path.join(SCRIPTS, name)
            if not os.path.isfile(path) or not name.endswith(".py"):
                continue
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            header = self.HEADER.search(text[:2000])
            constant = self.CONSTANT.search(text)
            if header and constant and header.group(1) != constant.group(1):
                mismatches.append(
                    f"{name}: header {header.group(1)} != constant {constant.group(1)}")
        self.assertEqual(mismatches, [], "\n".join(mismatches))

    def test_the_check_can_actually_fail(self):
        """A test that cannot fail proves nothing about the files it reads."""
        text = '# Version: 1.0.0\n\nSCRIPT_VERSION = "1.1.0"\n'
        self.assertNotEqual(self.HEADER.search(text).group(1),
                            self.CONSTANT.search(text).group(1))
