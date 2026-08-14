"""
Tests for scripts/bootstrap.sh — the parts that decide whether a fresh server
comes up on a storage driver that can export usable images.

Only ensure_overlay2_pin() is exercised here, and it is the right one to pin:
it is the single place where the moby#52431 workaround is decided, it edits a
file that stops docker from starting when it is malformed, and it is the branch
that was silently doing nothing on any host whose daemon.json existed for an
unrelated reason.

The script is sourced with BOOTSTRAP_NO_MAIN=1 so nothing provisions the
machine running the suite, and DOCKER_DAEMON_JSON points at a temp file.

Run from the repository root:

    python3 -m unittest tests.test_bootstrap -v
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
BOOTSTRAP = os.path.join(REPO, "scripts", "bootstrap.sh")

HAS_BASH = shutil.which("bash") is not None


def call(function, daemon_json):
    """Source bootstrap.sh and run one function against a temp daemon.json."""
    script = (
        f'set -euo pipefail\n'
        f'export BOOTSTRAP_NO_MAIN=1\n'
        f'export DOCKER_DAEMON_JSON="{daemon_json}"\n'
        f'source "{BOOTSTRAP}"\n'
        f'SUDO=""\n'
        f'{function}\n'
    )
    return subprocess.run(["bash", "-c", script],
                          capture_output=True, text=True)


@unittest.skipUnless(HAS_BASH, "needs bash to source the script")
class Overlay2PinTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "daemon.json")
        self.addCleanup(shutil.rmtree, self.tmp)

    def write(self, data):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(data)

    def read(self):
        with open(self.path, encoding="utf-8") as handle:
            return json.load(handle)

    def test_an_absent_file_is_created_with_the_pin(self):
        result = call("ensure_overlay2_pin", self.path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read(), {"storage-driver": "overlay2"})

    def raw(self):
        with open(self.path, "rb") as handle:
            return handle.read()

    def test_a_file_that_already_pins_overlay2_is_left_alone(self):
        self.write('{\n  "storage-driver": "overlay2"\n}\n')
        before = self.raw()
        self.assertEqual(call("ensure_overlay2_pin", self.path).returncode, 0)
        self.assertEqual(self.raw(), before)

    def test_other_settings_survive_the_merge(self):
        """This is the case the previous version skipped with a warning:
        daemon.json exists for log-opts or a registry mirror, the pin never
        happens, and that one server comes up on the containerd store."""
        self.write(json.dumps({
            "log-driver": "json-file",
            "log-opts": {"max-size": "10m", "max-file": "3"},
            "dns": ["1.1.1.1"],
        }))
        self.assertEqual(call("ensure_overlay2_pin", self.path).returncode, 0)
        data = self.read()
        self.assertEqual(data["storage-driver"], "overlay2")
        self.assertEqual(data["log-opts"], {"max-size": "10m", "max-file": "3"})
        self.assertEqual(data["dns"], ["1.1.1.1"])
        self.assertEqual(data["log-driver"], "json-file")

    def test_a_deliberate_other_driver_is_reported_not_overridden(self):
        self.write(json.dumps({"storage-driver": "btrfs"}))
        result = call("ensure_overlay2_pin", self.path)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.read(), {"storage-driver": "btrfs"})
        self.assertIn("btrfs", result.stderr)

    def test_unparsable_json_is_left_untouched_and_reported(self):
        """A half-written daemon.json stops docker from starting at all, so the
        one thing this must never do is write over a file it cannot read."""
        self.write("{ this is not json")
        result = call("ensure_overlay2_pin", self.path)
        self.assertEqual(result.returncode, 0)
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "{ this is not json")
        self.assertIn("could not be read as JSON", result.stderr)


@unittest.skipUnless(HAS_BASH, "needs bash to parse the script")
class ScriptShapeTest(unittest.TestCase):

    def test_the_script_parses(self):
        self.assertEqual(
            subprocess.run(["bash", "-n", BOOTSTRAP]).returncode, 0)

    def test_sourcing_it_provisions_nothing(self):
        """The BOOTSTRAP_NO_MAIN guard is what makes the tests above safe to
        run on a developer machine."""
        result = subprocess.run(
            ["bash", "-c",
             f'export BOOTSTRAP_NO_MAIN=1; source "{BOOTSTRAP}"; echo sourced'],
            capture_output=True, text=True)
        self.assertIn("sourced", result.stdout)

    def test_the_version_header_matches_the_constant(self):
        with open(BOOTSTRAP, encoding="utf-8") as handle:
            text = handle.read()
        header = [line for line in text.splitlines()
                  if line.startswith("# Version ")][0]
        constant = [line for line in text.splitlines()
                    if line.startswith("SCRIPT_VERSION=")][0]
        self.assertIn(constant.split('"')[1], header)


if __name__ == "__main__":
    unittest.main()
