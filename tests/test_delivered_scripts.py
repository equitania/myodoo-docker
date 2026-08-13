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
