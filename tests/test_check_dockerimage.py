"""
Tests for the build-context check in check_dockerimage_odoo.py.

The bug this pins: a manually created build folder has no `zips/` directory,
and the Dockerfile bind-mounts it. Docker aborts with

    failed to compute cache key: ... "/zips"

which names neither the directory's purpose nor the way out. `ca-certificates/`
is the same trap one COPY further down. update_docker_odoo.py creates `zips/`
as a fallback, but only when the build runs through `doup` - the first build of
a new instance is regularly done by hand.

The check is Dockerfile-driven on purpose: an installation may carry its own
COPY lines, and a hard-coded list of directory names would not see them.

Run from the repository root:

    python3 -m unittest tests.test_check_dockerimage -v
"""

import importlib.util
import io
import os
import re
import shutil
import tempfile
import unittest

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DOCKERFILES = os.path.join(REPO, "Dockerfiles")
VERSIONS = ("v16", "v18", "v19")
SCRIPT_NAME = "check_dockerimage_odoo.py"


def load_script(version="v18"):
    """Import one version's check script as a module.

    Safe because the procedural block lives behind `if __name__ == "__main__"`
    since v3.4.0 - importing it downloads nothing and rewrites no Dockerfile.
    """
    path = os.path.join(DOCKERFILES, f"{version}-odoo", SCRIPT_NAME)
    spec = importlib.util.spec_from_file_location(f"check_dockerimage_{version}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_script()


class TestParseContextSources(unittest.TestCase):
    """What the parser reads out of a Dockerfile, and what it deliberately ignores."""

    def parse(self, text):
        return dict(MODULE.parse_context_sources(text))

    def test_bind_mount_source_is_creatable(self):
        """zips/ only has to exist - an empty directory is a valid bind source."""
        found = self.parse(
            "FROM base:1\n"
            "RUN --mount=type=bind,source=zips,target=/opt/odoo/zips \\\n"
            "    cd /opt/odoo/ && \\\n"
            "    python3 build_odoo.py\n"
        )
        self.assertIn("zips", found)
        self.assertTrue(found["zips"], "a bind source must be creatable")

    def test_copy_directory_with_slash_is_creatable(self):
        """COPY of a directory succeeds when the directory is empty."""
        found = self.parse("FROM base:1\nCOPY ca-certificates/ /usr/local/share/ca-certificates/\n")
        self.assertTrue(found["ca-certificates/"])

    def test_copy_without_slash_is_not_creatable(self):
        """`COPY bin /app/bin/` needs the boot script - an empty bin/ is useless."""
        found = self.parse("FROM base:1\nCOPY bin /app/bin/\n")
        self.assertFalse(found["bin"])

    def test_copy_file_is_not_creatable(self):
        found = self.parse("FROM base:1\nCOPY build_odoo.py /opt/odoo/\n")
        self.assertFalse(found["build_odoo.py"])

    def test_release_file_is_ignored(self):
        """This script downloads release.file itself - never report it missing."""
        found = self.parse("FROM base:1\nCOPY release.file /opt/odoo/\n")
        self.assertNotIn("release.file", found)

    def test_glob_is_ignored(self):
        """An unmatched customer-modules glob is the Dockerfile author's call."""
        found = self.parse("FROM base:1\nCOPY *custom_modules.* /opt/odoo/\n")
        self.assertEqual(found, {})

    def test_remote_url_is_ignored(self):
        found = self.parse("FROM base:1\nADD https://example.org/x.tar.gz /opt/\n")
        self.assertEqual(found, {})

    def test_from_stage_is_ignored(self):
        """--from=builder copies out of another stage, not out of the context."""
        found = self.parse("FROM base:1\nCOPY --from=builder /out /opt/odoo/\n")
        self.assertEqual(found, {})

    def test_chown_flag_is_not_mistaken_for_a_source(self):
        found = self.parse("FROM base:1\nCOPY --chown=odoo:odoo odoo.conf /opt/odoo/etc/\n")
        self.assertEqual(list(found), ["odoo.conf"])

    def test_comments_and_multiple_sources(self):
        found = self.parse(
            "FROM base:1\n"
            "# COPY commented.py /opt/\n"
            "COPY a.py b.py /opt/odoo/\n"
        )
        self.assertEqual(sorted(found), ["a.py", "b.py"])


class TestCheckBuildContext(unittest.TestCase):
    """End-to-end behaviour in a scratch build folder."""

    DOCKERFILE = (
        "FROM base:1\n"
        "COPY build_odoo.py /opt/odoo/\n"
        "COPY odoo.conf /opt/odoo/etc/\n"
        "RUN --mount=type=bind,source=zips,target=/opt/odoo/zips \\\n"
        "    python3 build_odoo.py\n"
        "COPY ca-certificates/ /usr/local/share/ca-certificates/\n"
        "COPY bin /app/bin/\n"
    )

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="build-context-test-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, name, content="x"):
        path = os.path.join(self.dir, name)
        with io.open(path, "w", encoding="utf8") as handle:
            handle.write(content)

    def complete_folder(self):
        self.write("Dockerfile", self.DOCKERFILE)
        self.write("build_odoo.py")
        self.write("odoo.conf")
        os.makedirs(os.path.join(self.dir, "bin"))
        self.write(os.path.join("bin", "boot"))

    def test_creates_missing_directories_and_succeeds(self):
        """The reported bug: zips/ and ca-certificates/ absent, everything else fine."""
        self.complete_folder()

        self.assertTrue(MODULE.check_build_context(self.dir))

        self.assertTrue(os.path.isdir(os.path.join(self.dir, "zips")))
        self.assertTrue(os.path.isdir(os.path.join(self.dir, "ca-certificates")))

    def test_creating_a_directory_is_not_a_failure(self):
        """An installation without an internal CA must not carry a warning forever."""
        self.complete_folder()
        self.assertTrue(MODULE.check_build_context(self.dir))
        # Second run: nothing left to create, same verdict.
        self.assertTrue(MODULE.check_build_context(self.dir))

    def test_missing_file_fails(self):
        self.complete_folder()
        os.remove(os.path.join(self.dir, "odoo.conf"))
        self.assertFalse(MODULE.check_build_context(self.dir))

    def test_missing_bin_directory_fails(self):
        """bin/ carries the boot script - creating it empty would hide the fault."""
        self.complete_folder()
        shutil.rmtree(os.path.join(self.dir, "bin"))
        self.assertFalse(MODULE.check_build_context(self.dir))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "bin")))

    def test_missing_dockerfile_fails_without_traceback(self):
        """sed would abort with a traceback; this states the fault instead."""
        self.assertFalse(MODULE.check_build_context(self.dir))


class TestReleaseDownload(unittest.TestCase):
    """A failed release-manager download must leave the build folder buildable.

    The bug this pins (demo server, 20.11.2026): the release manager was not
    reachable for a moment. The script had already renamed release.file away,
    wget -O left an empty file behind, the unhandled CalledProcessError printed
    the access code into the run log, and the build then failed on
    'No valid release file'. The previous release.file was perfectly usable.
    """

    CODE = "SECRETACCESSCODE42"
    RELEASE = "https://example.invalid/base/\nmyodoo/prepare-v18:26.10.13-3.13.16\nodoo-kernel-18.0.zip\n"
    OLD_RELEASE = "https://example.invalid/old/\nmyodoo/prepare-v18:26.09.01-3.13.10\n"

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="release-download-test-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.cwd = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, self.cwd)
        self.write("release.txt", self.CODE + "\n")
        self.write("release.file", self.OLD_RELEASE)
        self.write("Dockerfile", "FROM myodoo/prepare-v18:26.09.01-3.13.10\n#\n#\n# Date 01.09.2026\n")
        self.wget_calls = []
        self.real_run = MODULE.subprocess.run
        self.addCleanup(setattr, MODULE.subprocess, "run", self.real_run)
        self.addCleanup(setattr, MODULE, "check_build_context", MODULE.check_build_context)
        MODULE.check_build_context = lambda *a, **k: True

    def write(self, name, content):
        with io.open(os.path.join(self.dir, name), "w", encoding="utf8") as handle:
            handle.write(content)

    def read(self, name):
        with io.open(os.path.join(self.dir, name), "r", encoding="utf8") as handle:
            return handle.read()

    def fake_wget(self, returncode=0, content=None):
        """Replace subprocess.run for wget only; sed still runs for real."""
        def run(cmd, *args, **kwargs):
            if cmd and cmd[0] == "wget":
                self.wget_calls.append(cmd)
                target = cmd[cmd.index("-O") + 1]
                # wget -O creates (truncates) the target even when it fails
                with io.open(target, "w", encoding="utf8") as handle:
                    handle.write(content or "")
                if kwargs.get("check") and returncode:
                    raise MODULE.subprocess.CalledProcessError(returncode, cmd)
                return MODULE.subprocess.CompletedProcess(cmd, returncode)
            return self.real_run(cmd, *args, **kwargs)
        MODULE.subprocess.run = run

    def run_main(self):
        out = io.StringIO()
        import contextlib
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = MODULE.main()
        return code, out.getvalue()

    def backups(self):
        return [n for n in os.listdir(self.dir) if n.startswith("release.file-")]

    def test_failed_download_keeps_the_previous_release_file(self):
        self.fake_wget(returncode=4)
        code, _ = self.run_main()
        self.assertNotEqual(code, 0)
        self.assertEqual(self.read("release.file"), self.OLD_RELEASE)
        self.assertEqual(self.backups(), [])
        self.assertNotIn("release.file.download", os.listdir(self.dir))

    def test_failed_download_never_prints_the_access_code(self):
        self.fake_wget(returncode=4)
        _, output = self.run_main()
        self.assertNotIn(self.CODE, output)
        self.assertNotIn("Traceback", output)
        self.assertIn("previous release.file", output)

    def test_empty_download_keeps_the_previous_release_file(self):
        self.fake_wget(returncode=0, content="")
        code, _ = self.run_main()
        self.assertNotEqual(code, 0)
        self.assertEqual(self.read("release.file"), self.OLD_RELEASE)

    def test_failed_download_leaves_the_dockerfile_alone(self):
        before = self.read("Dockerfile")
        self.fake_wget(returncode=4)
        self.run_main()
        self.assertEqual(self.read("Dockerfile"), before)

    def test_successful_download_replaces_and_backs_up(self):
        self.fake_wget(returncode=0, content=self.RELEASE)
        code, output = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(self.read("release.file"), self.RELEASE)
        backups = self.backups()
        self.assertEqual(len(backups), 1)
        self.assertEqual(self.read(backups[0]), self.OLD_RELEASE)
        self.assertTrue(self.read("Dockerfile").startswith(
            "FROM myodoo/prepare-v18:26.10.13-3.13.16\n"))
        self.assertNotIn(self.CODE, output)

    def test_wget_is_bounded(self):
        """No timeout meant a dropping firewall could hang the nightly run."""
        self.fake_wget(returncode=0, content=self.RELEASE)
        self.run_main()
        cmd = self.wget_calls[0]
        self.assertTrue(any(part.startswith("--timeout=") for part in cmd), cmd)
        self.assertTrue(any(part.startswith("--tries=") for part in cmd), cmd)

    def test_first_run_without_previous_release_file(self):
        os.remove(os.path.join(self.dir, "release.file"))
        self.fake_wget(returncode=4)
        code, output = self.run_main()
        self.assertNotEqual(code, 0)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "release.file")))
        self.assertNotIn(self.CODE, output)


class TestRepositoryBuildFolders(unittest.TestCase):
    """The shipped build folders must pass their own check, unchanged."""

    def test_every_version_folder_is_complete(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                source = os.path.join(DOCKERFILES, f"{version}-odoo")
                self.assertTrue(os.path.isdir(source), f"{source} missing")
                scratch = tempfile.mkdtemp(prefix=f"repo-context-{version}-")
                self.addCleanup(shutil.rmtree, scratch, True)
                target = os.path.join(scratch, "build")
                shutil.copytree(source, target)
                # zips/ is not in git; the check must create it and still pass.
                self.assertFalse(os.path.exists(os.path.join(target, "zips")))
                module = load_script(version)
                self.assertTrue(module.check_build_context(target),
                                f"{version} build folder is incomplete")

    def test_all_versions_carry_the_same_script(self):
        """v16/v18/v19 are byte-identical - a fix in one must reach all three.

        sync_build_scripts() compares the '# Version X.Y.Z' header, so a copy
        left behind would never be distributed to the installations using it.
        """
        contents = {}
        for version in VERSIONS:
            path = os.path.join(DOCKERFILES, f"{version}-odoo", SCRIPT_NAME)
            with io.open(path, "r", encoding="utf8") as handle:
                contents[version] = handle.read()
        reference = contents[VERSIONS[0]]
        for version in VERSIONS[1:]:
            self.assertEqual(contents[version], reference,
                             f"{version} {SCRIPT_NAME} differs from {VERSIONS[0]}")

    def test_version_header_is_parsable(self):
        """sync_build_scripts() needs it to decide whether to distribute."""
        path = os.path.join(DOCKERFILES, "v18-odoo", SCRIPT_NAME)
        with io.open(path, "r", encoding="utf8") as handle:
            head = handle.read(600)
        self.assertRegex(head, re.compile(r"^# Version \d+\.\d+\.\d+$", re.MULTILINE))


if __name__ == "__main__":
    unittest.main()
