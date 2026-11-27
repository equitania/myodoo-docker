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

    def base_path(self, tag):
        result = source_and_run(FR, "FR_DEPLOY_NO_MAIN", f'_container_base_path "{tag}"')
        return result.stdout.strip()

    def test_base_path_does_not_expire_with_the_year(self):
        # The rule was "tag contains 2026": every 2027 image got the legacy
        # mount path and died on a missing appsettings.json.
        for tag in ("2026.2.8-3.3.2", "2027.1.3-3.4.3", "2030.1.0-4.0.0"):
            self.assertEqual(self.base_path(tag), "/app/wwwroot", tag)

    def test_base_path_legacy_only_for_images_before_2026(self):
        for tag in ("2025.2.11", "2024.1.0-2.9.0"):
            self.assertEqual(self.base_path(tag), "/app/fr_api/wwwroot", tag)

    def test_base_path_of_an_unversioned_tag_is_the_current_layout(self):
        for tag in ("latest", "main", "test-2026"):
            self.assertEqual(self.base_path(tag), "/app/wwwroot", tag)

    def test_main_flow_uses_the_helper(self):
        text = FR.read_text(encoding="utf-8")
        self.assertNotIn("*2026*", text)
        self.assertIn('container_base_path="$(_container_base_path "$fr_version")"', text)


@unittest.skipUnless(shutil.which("bash"), "bash missing")
class HostUserTests(unittest.TestCase):
    @unittest.skipIf(os.geteuid() == 0, "runs as root")
    def test_without_root_nothing_is_created(self):
        for script, guard in ((PG, "PG_DEPLOY_NO_MAIN"), (FR, "FR_DEPLOY_NO_MAIN")):
            result = source_and_run(script, guard,
                                    '_ensure_host_user postgres 5432 test; echo rc=$?')
            self.assertIn("braucht root", result.stdout, script.name)
            self.assertIn("rc=0", result.stdout)


@unittest.skipUnless(shutil.which("bash") and shutil.which("python3"), "bash/python3 missing")
class PostgresSizingTests(unittest.TestCase):
    SIZING = ROOT / "scripts" / "ownerp_sizing.py"

    def block(self, extra="--cpus 4 --ram-mib 16384", sizing=None, role="live"):
        env_line = (f'export OWNERP_SIZING="{sizing or self.SIZING}"\n'
                    f'export OWNERP_SIZING_ARGS="--config /nonexistent {extra}"\n')
        return source_and_run(PG, "PG_DEPLOY_NO_MAIN",
                              env_line + f"_pg_sizing_block {role} live-db")

    def test_sizing_block_for_a_new_live_container(self):
        result = self.block()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("shared_buffers = 4096MB", result.stdout)
        self.assertIn("4cpu16gb", result.stdout)
        self.assertIn("# --- ownerp_sizing override ---", result.stdout)

    def test_missing_module_means_fallback(self):
        result = self.block(sizing="/nonexistent/ownerp_sizing.py")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_over_budget_still_prints_the_block_and_warns(self):
        result = self.block(extra="--cpus 1 --ram-mib 1024")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("shared_buffers = ", result.stdout)
        self.assertIn("over budget", result.stderr)


@unittest.skipUnless(shutil.which("bash"), "bash missing")
class FastReportNonInteractiveTests(unittest.TestCase):
    """--non-interactive: every value from options, never a prompt."""

    def fr(self, body, stdin=""):
        return source_and_run(FR, "FR_DEPLOY_NO_MAIN", body, stdin=stdin)

    def test_options_are_parsed(self):
        r = self.fr('_parse_args --non-interactive --name demo-fr-19 --port 8819 '
                    '--token-file /x --tag 1.2 --basedir /srv/fr --recreate && '
                    'echo "$NONINTERACTIVE|$OPT_NAME|$OPT_PORT|$OPT_TOKEN_FILE|$OPT_TAG|'
                    '$OPT_BASEDIR|$OPT_RECREATE"')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "1|demo-fr-19|8819|/x|1.2|/srv/fr|1")

    def test_missing_required_values_fail(self):
        r = self.fr('_parse_args --non-interactive --name a')
        self.assertEqual(r.returncode, 1)
        self.assertIn("--port", r.stderr)
        self.assertIn("--token-file", r.stderr)

    def test_token_from_environment_satisfies_the_requirement(self):
        r = self.fr('FR_REGISTRY_TOKEN=t _parse_args --non-interactive --name a --port 1')
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_unknown_option_and_missing_value_fail(self):
        self.assertEqual(self.fr('_parse_args --bogus').returncode, 1)
        self.assertEqual(self.fr('_parse_args --name').returncode, 1)

    def test_no_options_stays_interactive(self):
        r = self.fr('_parse_args && echo "$NONINTERACTIVE"')
        self.assertEqual(r.stdout.strip(), "0")

    def test_ask_prefers_option_then_default_without_reading(self):
        # stdin carries an answer that must NOT be read in non-interactive mode
        r = self.fr('NONINTERACTIVE=1; echo "[$(_ask "p: " "" dflt)][$(_ask "p: " opt dflt)]"',
                    stdin="typed\n")
        self.assertEqual(r.stdout.strip(), "[dflt][opt]")

    def test_ask_reads_when_interactive(self):
        r = self.fr('echo "[$(_ask "p: " "" dflt)]"', stdin="typed\n")
        self.assertEqual(r.stdout.strip(), "[typed]")

    def test_token_file_must_be_private(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            tok = Path(d) / "token"
            tok.write_text("glpat-secret\n")
            os.chmod(tok, 0o644)
            r = self.fr(f'_read_token_file "{tok}"')
            self.assertEqual(r.returncode, 1)
            self.assertNotIn("glpat-secret", r.stdout + r.stderr)
            os.chmod(tok, 0o600)
            r = self.fr(f'_read_token_file "{tok}"')
            self.assertEqual((r.returncode, r.stdout), (0, "glpat-secret"))

    def test_every_prompt_in_the_flow_has_a_non_interactive_branch(self):
        flow = FR.read_text().split('_parse_args "$@" || exit 1', 1)[1]
        lines = flow.splitlines()
        prompts = [i for i, ln in enumerate(lines)
                   if ("read -rp" in ln or "_read_masked \"" in ln or "_read_pwd_twice \"" in ln)]
        self.assertTrue(prompts)
        for i in prompts:
            context = "\n".join(lines[max(0, i - 12):i + 1])
            self.assertTrue("NONINTERACTIVE" in context or "OPT_TOKEN_FILE" in context
                            or "FR_REGISTRY_TOKEN" in context,
                            f"unguarded prompt: {lines[i].strip()}")

    def test_generated_credentials_go_to_a_private_file(self):
        text = FR.read_text()
        self.assertIn("generated-credentials.txt", text)
        self.assertIn("umask 077", text)


@unittest.skipUnless(shutil.which("bash"), "bash missing")
class PostgresNonInteractiveTests(unittest.TestCase):
    """1.6.0: --non-interactive for calls without a terminal; EOF no longer loops."""

    def pg(self, body, stdin=""):
        return source_and_run(PG, "PG_DEPLOY_NO_MAIN", body, stdin=stdin)

    def test_options_are_parsed(self):
        r = self.pg('_parse_args --non-interactive --name test-db --version 17.12 '
                    '--password-file /p --basedir /srv/pg --user u --db d --role test '
                    '--profile 2cpu4gb --port 15432 --ssl --pgvector --recreate && '
                    'echo "$NONINTERACTIVE|$OPT_NAME|$OPT_VERSION|$OPT_PASSWORD_FILE|$OPT_BASEDIR|'
                    '$OPT_USER|$OPT_DB|$OPT_ROLE|$OPT_PROFILE|$OPT_PORT|$OPT_SSL|$OPT_PGVECTOR|'
                    '$OPT_RECREATE"')
        self.assertEqual(r.returncode, 0, r.stderr)
        # role/profile become the menu answers the flow already validates
        self.assertEqual(r.stdout.strip(), "1|test-db|17.12|/p|/srv/pg|u|d|2|1|15432|y|y|1")

    def test_live_role_and_users(self):
        r = self.pg('_parse_args --role live --users 40 && echo "$OPT_ROLE|$OPT_USERS"')
        self.assertEqual(r.stdout.strip(), "1|40")

    def test_password_file_and_version_are_required(self):
        r = self.pg('_parse_args --non-interactive --name a')
        self.assertEqual(r.returncode, 1)
        self.assertIn("--password-file", r.stderr)
        self.assertIn("--version", r.stderr)

    def test_bad_values_fail(self):
        self.assertEqual(self.pg('_parse_args --role prod').returncode, 1)
        self.assertEqual(self.pg('_parse_args --profile 16cpu').returncode, 1)
        self.assertEqual(self.pg('_parse_args --bogus').returncode, 1)
        self.assertEqual(self.pg('_parse_args --name').returncode, 1)

    def test_ask_never_reads_in_non_interactive_mode(self):
        r = self.pg('NONINTERACTIVE=1; echo "[$(_ask "p: " "")][$(_ask "p: " opt)]"',
                    stdin="typed\n")
        self.assertEqual(r.stdout.strip(), "[][opt]")

    def test_ask_reads_when_interactive(self):
        r = self.pg('echo "[$(_ask "p: " "")]"', stdin="typed\n")
        self.assertEqual(r.stdout.strip(), "[typed]")

    def test_password_file_must_be_private_and_not_empty(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            pw = Path(d) / "pw"
            pw.write_text("Xq7-secret\nsecond line\n")
            os.chmod(pw, 0o644)
            r = self.pg(f'_read_password_file "{pw}"')
            self.assertEqual(r.returncode, 1)
            self.assertNotIn("Xq7-secret", r.stdout + r.stderr)
            os.chmod(pw, 0o600)
            r = self.pg(f'_read_password_file "{pw}"')
            self.assertEqual((r.returncode, r.stdout), (0, "Xq7-secret"))
            pw.write_text("no-newline")
            r = self.pg(f'_read_password_file "{pw}"')
            self.assertEqual((r.returncode, r.stdout), (0, "no-newline"))
            pw.write_text("\n")
            self.assertEqual(self.pg(f'_read_password_file "{pw}"').returncode, 1)

    def test_password_prompt_stops_at_end_of_input(self):
        # Before 1.6.0 an exhausted answer file asked for the password forever.
        r = subprocess.run(
            ["bash", "-c", f'export PG_DEPLOY_NO_MAIN=1; source "{PG}"; '
                           '_read_pwd_twice "DB-Passwort"; echo "rc=$?"'],
            input="", capture_output=True, text=True, timeout=10)
        self.assertIn("rc=1", r.stdout)
        self.assertIn("EOF", r.stderr)

    def test_password_prompt_still_reads_a_typed_password(self):
        r = self.pg('_read_pwd_twice "DB-Passwort"', stdin="abc\nabc\n")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "abc"))

    def test_every_prompt_in_the_flow_has_a_non_interactive_branch(self):
        flow = PG.read_text().split('_parse_args "$@" || exit 1', 1)[1]
        lines = flow.splitlines()
        prompts = [i for i, ln in enumerate(lines) if "read -rp" in ln or "_read_pwd_twice \"" in ln]
        self.assertTrue(prompts)
        for i in prompts:
            context = "\n".join(lines[max(0, i - 12):i + 1])
            self.assertIn("NONINTERACTIVE", context, f"unguarded prompt: {lines[i].strip()}")


if __name__ == "__main__":
    unittest.main()
