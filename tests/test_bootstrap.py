"""
Tests for scripts/bootstrap.sh — the storage-driver pin.

Since 1.13.0 the pin is opt-in (DOCKER_STORAGE_DRIVER); the A/B test of
14.08.2026 found the containerd image store builds 2.2 GB / 22-layer images
without fault on Docker 29.7.2, so pinning overlay2 by default had no grounds
left. ensure_storage_driver_pin() stays because a host where a store fault is
actually observed still needs it — and it is worth testing: it edits a file
that stops docker from starting when it is malformed.

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
        result = call("ensure_storage_driver_pin overlay2", self.path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read(), {"storage-driver": "overlay2"})

    def raw(self):
        with open(self.path, "rb") as handle:
            return handle.read()

    def test_a_file_that_already_pins_overlay2_is_left_alone(self):
        self.write('{\n  "storage-driver": "overlay2"\n}\n')
        before = self.raw()
        self.assertEqual(call("ensure_storage_driver_pin overlay2", self.path).returncode, 0)
        self.assertEqual(self.raw(), before)

    def test_other_settings_survive_the_merge(self):
        """The case a `if [ ! -f daemon.json ]` guard skipped silently:
        the file exists for log-opts or a registry mirror, and the pin an
        operator explicitly asked for never happens."""
        self.write(json.dumps({
            "log-driver": "json-file",
            "log-opts": {"max-size": "10m", "max-file": "3"},
            "dns": ["1.1.1.1"],
        }))
        self.assertEqual(call("ensure_storage_driver_pin overlay2", self.path).returncode, 0)
        data = self.read()
        self.assertEqual(data["storage-driver"], "overlay2")
        self.assertEqual(data["log-opts"], {"max-size": "10m", "max-file": "3"})
        self.assertEqual(data["dns"], ["1.1.1.1"])
        self.assertEqual(data["log-driver"], "json-file")

    def test_a_deliberate_other_driver_is_reported_not_overridden(self):
        self.write(json.dumps({"storage-driver": "btrfs"}))
        result = call("ensure_storage_driver_pin overlay2", self.path)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.read(), {"storage-driver": "btrfs"})
        self.assertIn("btrfs", result.stderr)

    def test_unparsable_json_is_left_untouched_and_reported(self):
        """A half-written daemon.json stops docker from starting at all, so the
        one thing this must never do is write over a file it cannot read."""
        self.write("{ this is not json")
        result = call("ensure_storage_driver_pin overlay2", self.path)
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

    def test_no_storage_driver_is_pinned_by_default(self):
        """The 14.08.2026 A/B test removed the grounds for the default pin.
        Reintroducing one has to be a decision, not a leftover."""
        with open(BOOTSTRAP, encoding="utf-8") as handle:
            text = handle.read()
        code = [line for line in text.splitlines()
                if not line.lstrip().startswith("#")]
        calls = [line for line in code if "ensure_storage_driver_pin " in line]
        self.assertEqual(len(calls), 1, calls)
        self.assertIn('"${DOCKER_STORAGE_DRIVER}"', calls[0])
        self.assertRegex(text, r'DOCKER_STORAGE_DRIVER="\$\{DOCKER_STORAGE_DRIVER:-\}"')

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
