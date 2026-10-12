"""Tests for scripts/pg-local-deploy.sh and scripts/fr-local-deploy.sh.

Both scripts are interactive end to end. They are sourced with
PG_DEPLOY_NO_MAIN / FR_DEPLOY_NO_MAIN so only their helper functions load;
nothing is pulled, started or created.
"""
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PG = ROOT / "scripts" / "pg-local-deploy.sh"
FR = ROOT / "scripts" / "fr-local-deploy.sh"


def source_and_run(script: Path, guard: str, body: str, stdin: str = ""):
    code = f'export {guard}=1\nsource "{script}"\n{body}\n'
    return subprocess.run(["bash", "-c", code], input=stdin, capture_output=True,
                          text=True, timeout=30)


@unittest.skipUnless(shutil.which("bash"), "bash missing")
class SyntaxTests(unittest.TestCase):
    def test_both_scripts_parse(self):
        for script in (PG, FR):
            result = subprocess.run(["bash", "-n", str(script)], capture_output=True,
                                    text=True)
            self.assertEqual(result.returncode, 0, f"{script.name}: {result.stderr}")

    def test_sourcing_stops_before_the_interactive_flow(self):
        for script, guard in ((PG, "PG_DEPLOY_NO_MAIN"), (FR, "FR_DEPLOY_NO_MAIN")):
            result = source_and_run(script, guard, 'echo loaded', stdin="")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "loaded", script.name)


@unittest.skipUnless(shutil.which("bash") and shutil.which("python3"), "bash/python3 missing")
class PostgresVersionTests(unittest.TestCase):
    def latest(self, names):
        payload = json.dumps({"results": [{"name": n} for n in names]})
        result = source_and_run(PG, "PG_DEPLOY_NO_MAIN", "_pg_latest_per_major", payload)
        return result.returncode, result.stdout.splitlines()

    def test_newest_patch_per_major_newest_major_first(self):
        code, lines = self.latest(["16.14", "18.4", "17.10", "18.6", "16.15",
                                   "17.11", "18", "latest"])
        self.assertEqual(code, 0)
        self.assertEqual(lines, ["18 18.6", "17 17.11", "16 16.15"])

    def test_minor_compared_as_number_not_text(self):
        _, lines = self.latest(["17.9", "17.10"])
        self.assertEqual(lines, ["17 17.10"])

    def test_variants_and_betas_are_ignored(self):
        _, lines = self.latest(["19beta1", "18.6-alpine", "18.6-trixie", "18-bookworm"])
        self.assertEqual(lines, [])

    def test_garbage_is_a_failure_not_a_suggestion(self):
        result = source_and_run(PG, "PG_DEPLOY_NO_MAIN", "_pg_latest_per_major",
                                "<html>rate limited</html>")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


class PostgresUserTests(unittest.TestCase):
    """The compose file and docker run must carry the pinned user and PGDATA."""

    text = PG.read_text(encoding="utf-8")

    def test_pinned_uid(self):
        self.assertIn('PG_HOST_USER="postgres"', self.text)
        self.assertIn("PG_UID=5432", self.text)

    def test_pgdata_is_explicit_in_compose_and_run(self):
        # postgres:18 moved its default PGDATA and refuses an unused mount at
        # /var/lib/postgresql/data - setting it keeps 14..18 on one layout.
        self.assertIn('PGDATA: "/var/lib/postgresql/data"', self.text)
        self.assertIn("-e PGDATA=/var/lib/postgresql/data", self.text)

    def test_user_reaches_compose_and_run(self):
        self.assertIn("${user_block}", self.text)
        self.assertIn('"${user_args[@]}"', self.text)

    def test_no_hardcoded_image_uid_in_chown(self):
        self.assertNotIn("chown 999:999", self.text)


@unittest.skipUnless(shutil.which("bash"), "bash missing")
class FastReportTagTests(unittest.TestCase):
    def newest(self, tags):
        result = source_and_run(FR, "FR_DEPLOY_NO_MAIN", "_newest_release_tag",
                                "\n".join(tags) + "\n")
        return result.stdout.strip()

    def test_newest_release_tag_by_version_not_text(self):
        self.assertEqual(self.newest(["2026.2.3-3.2.7", "2026.10.1-3.3.0",
                                      "2026.2.10-3.2.9"]), "2026.10.1-3.3.0")

    def test_non_release_tags_are_never_suggested(self):
        self.assertEqual(self.newest(["latest", "main", "2026.2.3-3.2.7", "test-x"]),
                         "2026.2.3-3.2.7")
        self.assertEqual(self.newest(["latest", "main"]), "")

    def test_token_is_asked_before_the_tag(self):
        text = FR.read_text(encoding="utf-8")
        self.assertLess(text.index("GitLab Registry Token"), text.index('Image-Tag ['))


@unittest.skipUnless(shutil.which("bash"), "bash missing")
class HostUserTests(unittest.TestCase):
    @unittest.skipIf(os.geteuid() == 0, "runs as root")
    def test_without_root_nothing_is_created(self):
        for script, guard in ((PG, "PG_DEPLOY_NO_MAIN"), (FR, "FR_DEPLOY_NO_MAIN")):
            result = source_and_run(script, guard,
                                    '_ensure_host_user postgres 5432 test; echo rc=$?')
            self.assertIn("braucht root", result.stdout, script.name)
            self.assertIn("rc=0", result.stdout)


if __name__ == "__main__":
    unittest.main()
