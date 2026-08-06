"""
Tests for the container entrypoint Dockerfiles/*/bin/boot.

Standard library only (unittest, subprocess) — the same rule as the rest of the
suite: customer servers run the system Python and carry no test framework.

The script is exercised for real. Each run gets a PATH whose first entry holds
two stand-ins: a 'whoami' that claims to be the odoo user (so the direct branch
runs instead of 'su - odoo') and a 'python3' that records the arguments it was
called with. Nothing else about the script is stubbed out.

Run from the repository root:

    python3 -m unittest tests.test_boot_script -v
"""

import os
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCKERFILES = os.path.join(REPO, "Dockerfiles")

# Odoo 19 warns on every start without http_interface and Odoo 20 will default
# it to 127.0.0.1. The other versions have neither the warning nor the coming
# default change, so their boot scripts stay untouched.
INTERFACE_ARGUMENT = "--http-interface=0.0.0.0"


def boot_path(version):
    return os.path.join(DOCKERFILES, version, "bin", "boot")


def write_executable(path, text):
    with open(path, "w", encoding="utf8") as handle:
        handle.write(text)
    os.chmod(path, 0o755)


def run_boot(version, *arguments):
    """Run a boot script and return the argument list odoo-bin was given."""
    with tempfile.TemporaryDirectory() as tmp:
        fake_bin = os.path.join(tmp, "bin")
        os.makedirs(fake_bin)
        recorded = os.path.join(tmp, "arguments")

        write_executable(os.path.join(fake_bin, "whoami"), "#!/bin/sh\necho odoo\n")
        write_executable(
            os.path.join(fake_bin, "python3"),
            '#!/bin/sh\nprintf "%s\\n" "$@" > "$RECORDED_ARGUMENTS"\n',
        )

        environment = dict(os.environ)
        environment["PATH"] = fake_bin + os.pathsep + environment.get("PATH", "")
        environment["RECORDED_ARGUMENTS"] = recorded

        result = subprocess.run(
            ["bash", boot_path(version)] + list(arguments),
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if not os.path.isfile(recorded):
            raise AssertionError(
                "odoo-bin was never called.\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
        with open(recorded, encoding="utf8") as handle:
            return [line for line in handle.read().splitlines() if line]


class BootUpdateTest(unittest.TestCase):
    """The update run is the one that produced the warning in the doup report."""

    def test_update_sets_the_http_interface(self):
        arguments = run_boot("v19-odoo", "update", "--database=demo")
        self.assertIn(INTERFACE_ARGUMENT, arguments)

    def test_neutralize_sets_the_http_interface(self):
        arguments = run_boot("v19-odoo", "neutralize", "--database=demo")
        self.assertIn(INTERFACE_ARGUMENT, arguments)

    def test_update_still_carries_its_own_flags(self):
        arguments = run_boot("v19-odoo", "update", "--database=demo")
        for flag in ("--update=all", "--workers=0", "--stop-after-init"):
            self.assertIn(flag, arguments)

    def test_update_still_passes_the_callers_arguments_through(self):
        arguments = run_boot("v19-odoo", "update", "--database=demo")
        self.assertIn("--database=demo", arguments)

    def test_update_does_not_read_the_configuration_file(self):
        """Adding -c here would hand the update run the customer's addons_path
        and db_host — a behaviour change the warning does not justify."""
        arguments = run_boot("v19-odoo", "update", "--database=demo")
        self.assertNotIn("-c", arguments)


class BootStartTest(unittest.TestCase):
    """The running container reads odoo.conf, so the flag would be redundant."""

    def test_start_reads_the_configuration_file(self):
        arguments = run_boot("v19-odoo", "start")
        self.assertIn("-c", arguments)
        self.assertIn("/opt/odoo/etc/odoo.conf", arguments)

    def test_start_leaves_the_http_interface_to_the_configuration(self):
        arguments = run_boot("v19-odoo", "start")
        self.assertNotIn(INTERFACE_ARGUMENT, arguments)


class BootDispatchTest(unittest.TestCase):
    def test_an_unknown_command_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_bin = os.path.join(tmp, "bin")
            os.makedirs(fake_bin)
            write_executable(os.path.join(fake_bin, "whoami"), "#!/bin/sh\necho odoo\n")
            environment = dict(os.environ)
            environment["PATH"] = fake_bin + os.pathsep + environment.get("PATH", "")
            result = subprocess.run(
                ["bash", boot_path("v19-odoo"), "rm -rf /"],
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to run unknown command", result.stderr)


class BootOtherVersionsTest(unittest.TestCase):
    """Odoo 16 and 18 emit no such warning — an argument they never needed is a
    change to a customer image for nothing."""

    def test_older_versions_do_not_set_the_http_interface(self):
        for version in ("v16-odoo", "v18-odoo"):
            with self.subTest(version=version):
                with open(boot_path(version), encoding="utf8") as handle:
                    self.assertNotIn("--http-interface", handle.read())


if __name__ == "__main__":
    unittest.main()
