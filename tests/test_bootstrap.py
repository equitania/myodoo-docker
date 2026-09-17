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


def resolve_target_user_call(current_user, sudo_user="", sudo_command=""):
    """Source bootstrap.sh with id/getent stubbed and print the resolved target.

    SUDO_USER and SUDO_COMMAND are exported exactly as sudo leaves them behind;
    an empty value means the variable is unset.
    """
    exports = ""
    if sudo_user:
        exports += f'export SUDO_USER="{sudo_user}"\n'
    if sudo_command:
        exports += f'export SUDO_COMMAND="{sudo_command}"\n'
    script = (
        f'unset SUDO_USER SUDO_COMMAND\n'
        f'export BOOTSTRAP_NO_MAIN=1\n'
        f'source "{BOOTSTRAP}"\n'
        f'{exports}'
        f'id() {{ echo {current_user}; }}\n'
        f'getent() {{ echo "$2:x:0:0::/home/$2:/bin/bash" | sed "s#/home/root#/root#"; }}\n'
        f'resolve_target_user >/dev/null\n'
        f'echo "$TARGET_USER $TARGET_HOME"\n'
    )
    return subprocess.run(["bash", "-c", script],
                          capture_output=True, text=True)


@unittest.skipUnless(HAS_BASH, "needs bash to source the script")
class ResolveTargetUserTest(unittest.TestCase):
    """Operators on customer servers work in a root shell opened with
    'sudo su'. That shell still carries SUDO_USER, so before 1.15.2 the script
    cloned myodoo-docker into the operator's home and ran getScripts.py as the
    operator — while getScripts.py itself (>= 9.7.3) installs for root there."""

    def test_sudo_su_targets_root(self):
        result = resolve_target_user_call("root", "operator", "/usr/bin/su")
        self.assertEqual(result.stdout.strip(), "root /root", result.stderr)

    def test_sudo_su_with_a_dash_targets_root(self):
        result = resolve_target_user_call("root", "operator", "/usr/bin/su -")
        self.assertEqual(result.stdout.strip(), "root /root", result.stderr)

    def test_sudo_dash_s_targets_root(self):
        result = resolve_target_user_call("root", "operator", "/usr/bin/fish")
        self.assertEqual(result.stdout.strip(), "root /root", result.stderr)

    def test_sudo_dash_i_targets_root(self):
        result = resolve_target_user_call("root", "operator", "/bin/bash -l")
        self.assertEqual(result.stdout.strip(), "root /root", result.stderr)

    def test_sudo_on_the_script_targets_the_operator(self):
        result = resolve_target_user_call(
            "root", "operator", "/opt/myodoo-bootstrap.sh")
        self.assertEqual(result.stdout.strip(), "operator /home/operator",
                         result.stderr)

    def test_sudo_bash_on_the_script_targets_the_operator(self):
        """A shell that runs a script is not an interactive root shell."""
        result = resolve_target_user_call(
            "root", "operator", "/usr/bin/bash /opt/myodoo-bootstrap.sh")
        self.assertEqual(result.stdout.strip(), "operator /home/operator",
                         result.stderr)

    def test_plain_root_targets_root(self):
        result = resolve_target_user_call("root")
        self.assertEqual(result.stdout.strip(), "root /root", result.stderr)


def run_as_target_call(uid, current_user, target_user):
    """Source bootstrap.sh with id/runuser/sudo stubbed and call run_as_target.

    The stubs print what would be executed instead of switching users, so the
    test needs neither root nor a second account on the machine running it.
    """
    script = (
        f'export BOOTSTRAP_NO_MAIN=1\n'
        f'source "{BOOTSTRAP}"\n'
        f'id() {{ if [ "$1" = "-u" ]; then echo {uid}; else echo {current_user}; fi; }}\n'
        f'runuser() {{ echo "runuser $*"; }}\n'
        f'sudo() {{ echo "sudo $*"; }}\n'
        f'resolve_privilege >/dev/null\n'
        f'TARGET_USER={target_user}\n'
        f'TARGET_HOME=/home/{target_user}\n'
        f'run_as_target echo hello\n'
    )
    return subprocess.run(["bash", "-c", script],
                          capture_output=True, text=True)


@unittest.skipUnless(HAS_BASH, "needs bash to source the script")
class RunAsTargetTest(unittest.TestCase):
    """Started with sudo, the script runs as root with SUDO="" while the target
    is the operator who called sudo. Before 1.15.1 that case expanded to
    `-u <user> -H git clone …` and aborted with "-u: command not found"."""

    def test_root_switches_to_the_operator_with_runuser(self):
        result = run_as_target_call(0, "root", "operator")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(),
                         "runuser -u operator -- env HOME=/home/operator echo hello")

    def test_a_non_root_caller_uses_sudo(self):
        result = run_as_target_call(1000, "someone", "operator")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "sudo -u operator -H echo hello")

    def test_the_target_user_itself_runs_the_command_directly(self):
        result = run_as_target_call(1000, "operator", "operator")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "hello")


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

    def test_overlay2_is_the_default_and_can_be_switched_off(self):
        """overlay2 is pinned again since 1.14.0, for speed: on a real Odoo
        build the containerd store was 2.6x slower cold, and its build cache did
        not survive the `docker system prune -f` doup runs after every update.

        The `:-` vs `-` distinction is the substance. With `:-`, an explicit
        DOCKER_STORAGE_DRIVER="" would fall back to overlay2 and there would be
        no way to ask for Docker's own default at all."""
        with open(BOOTSTRAP, encoding="utf-8") as handle:
            text = handle.read()
        code = [line for line in text.splitlines()
                if not line.lstrip().startswith("#")]
        calls = [line for line in code if "ensure_storage_driver_pin " in line]
        self.assertEqual(len(calls), 1, calls)
        self.assertIn('"${DOCKER_STORAGE_DRIVER}"', calls[0])
        self.assertRegex(text, r'DOCKER_STORAGE_DRIVER="\$\{DOCKER_STORAGE_DRIVER-overlay2\}"')

    def test_an_empty_value_really_means_dockers_default(self):
        result = subprocess.run(
            ["bash", "-c",
             f'export BOOTSTRAP_NO_MAIN=1 DOCKER_STORAGE_DRIVER=""; '
             f'source "{BOOTSTRAP}"; echo "driver=[${{DOCKER_STORAGE_DRIVER}}]"'],
            capture_output=True, text=True)
        self.assertIn("driver=[]", result.stdout)

    def test_unset_means_overlay2(self):
        result = subprocess.run(
            ["bash", "-c",
             f'export BOOTSTRAP_NO_MAIN=1; unset DOCKER_STORAGE_DRIVER; '
             f'source "{BOOTSTRAP}"; echo "driver=[${{DOCKER_STORAGE_DRIVER}}]"'],
            capture_output=True, text=True)
        self.assertIn("driver=[overlay2]", result.stdout)

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
