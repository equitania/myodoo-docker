"""
Tests for the run log of update_docker_odoo.py.

Standard library only, like the rest of the suite. PyYAML is imported at module
level by the script but only used by load_config; none of the functions under
test touch it, so a placeholder module stands in when it is absent (customer
servers and CI have the real one).

Run from the repository root:

    python3 -m unittest tests.test_update_docker_odoo -v
"""

import os
import re
import sys
import tempfile
import time
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
try:
    import yaml  # noqa: F401
except ImportError:
    sys.modules["yaml"] = types.ModuleType("yaml")
import update_docker_odoo as udo  # noqa: E402

LOG_NAME_PATTERN = re.compile(r"^update_\d{8}_\d{6}\.log$")

# True only when the real PyYAML is on sys.path; the two tests below need it
# to actually load a config file from disk, not just parse argv.
HAS_REAL_YAML = hasattr(sys.modules.get("yaml"), "safe_load")


def read(path):
    with open(path, encoding="utf8") as handle:
        return handle.read()


class RunLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        udo.RUN_LOG_FILES.clear()
        self.addCleanup(udo.close_run_log)
        self.addCleanup(udo.RUN_LOG_FILES.clear)

    def test_the_log_lands_in_the_build_folder(self):
        path = udo.open_run_log(self.tmp, "ivy-odoo")
        self.assertEqual(os.path.dirname(path), self.tmp)
        self.assertTrue(os.path.isfile(path))

    def test_the_name_carries_date_and_time(self):
        path = udo.open_run_log(self.tmp, "ivy-odoo")
        self.assertRegex(os.path.basename(path), LOG_NAME_PATTERN)

    def test_the_header_names_the_container_and_the_script_version(self):
        path = udo.open_run_log(self.tmp, "ivy-odoo")
        udo.close_run_log()
        content = read(path)
        self.assertIn("ivy-odoo", content)
        self.assertIn(udo.SCRIPT_VERSION, content)

    def test_extra_header_lines_are_written(self):
        path = udo.open_run_log(self.tmp, "ivy-odoo",
                                header_lines=["image: odoo/ivy:latest"])
        udo.close_run_log()
        self.assertIn("image: odoo/ivy:latest", read(path))

    def test_written_lines_reach_the_file(self):
        path = udo.open_run_log(self.tmp, "ivy-odoo")
        udo.run_log_write("build image odoo/ivy ... ok (23s)")
        udo.close_run_log()
        self.assertIn("build image odoo/ivy ... ok (23s)", read(path))

    def test_lines_are_flushed_before_the_log_is_closed(self):
        """A run killed mid-build must still leave its lines behind."""
        path = udo.open_run_log(self.tmp, "ivy-odoo")
        udo.run_log_write("stop ivy-odoo")
        self.assertIn("stop ivy-odoo", read(path))

    def test_carriage_returns_never_reach_the_file(self):
        path = udo.open_run_log(self.tmp, "ivy-odoo")
        udo.run_log_write("\r  spinner residue\r")
        udo.close_run_log()
        self.assertNotIn("\r", read(path))

    def test_writing_without_an_open_log_is_ignored(self):
        udo.close_run_log()
        udo.run_log_write("nothing should happen here")  # must not raise

    def test_the_path_is_collected_for_the_closing_block(self):
        path = udo.open_run_log(self.tmp, "ivy-odoo")
        self.assertIn(path, udo.RUN_LOG_FILES)

    def test_a_second_container_gets_its_own_file(self):
        first = udo.open_run_log(self.tmp, "ivy-odoo")
        udo.close_run_log()
        second_dir = tempfile.mkdtemp()
        second = udo.open_run_log(second_dir, "equitania-odoo")
        udo.close_run_log()
        self.assertNotEqual(first, second)
        self.assertEqual(udo.RUN_LOG_FILES, [first, second])

    def test_an_unwritable_folder_never_stops_the_run(self):
        """The log is a convenience. Losing it must not cost the update."""
        missing = os.path.join(self.tmp, "does", "not", "exist")
        self.assertIsNone(udo.open_run_log(missing, "ivy-odoo"))
        udo.run_log_write("still fine")  # must not raise


def age_log(directory, days, name_only=False):
    """Create a run log whose name puts it `days` days in the past."""
    stamp = time.strftime("%Y%m%d_%H%M%S",
                          time.localtime(time.time() - days * 86400))
    path = os.path.join(directory, f"update_{stamp}.log")
    if not name_only:
        with open(path, "w", encoding="utf8") as handle:
            handle.write("old run\n")
    return path


class PruneRunLogsTest(unittest.TestCase):
    """Deleting files needs a narrower target than a glob. Age comes from the
    name, which is also what proves the file is ours to delete."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(udo.close_run_log)
        self.addCleanup(udo.RUN_LOG_FILES.clear)

    def test_a_log_older_than_the_limit_is_removed(self):
        old = age_log(self.tmp, 120)
        self.assertEqual(udo.prune_run_logs(self.tmp, 90), 1)
        self.assertFalse(os.path.exists(old))

    def test_a_log_within_the_limit_survives(self):
        recent = age_log(self.tmp, 10)
        udo.prune_run_logs(self.tmp, 90)
        self.assertTrue(os.path.exists(recent))

    def test_the_boundary_sits_where_it_was_configured(self):
        """Not testable at exactly N days - the clock moves on between building
        the name and comparing it. A day either side is what matters."""
        just_inside = age_log(self.tmp, 89)
        just_outside = age_log(self.tmp, 91)
        self.assertEqual(udo.prune_run_logs(self.tmp, 90), 1)
        self.assertTrue(os.path.exists(just_inside))
        self.assertFalse(os.path.exists(just_outside))

    def test_only_this_script_s_own_log_names_are_touched(self):
        strangers = []
        for name in ("odoo.conf", "Dockerfile", "build.log", "update.log",
                     "update_2026.log", "update_20260101_120000.log.bak",
                     "release.file"):
            path = os.path.join(self.tmp, name)
            with open(path, "w", encoding="utf8") as handle:
                handle.write("not a run log\n")
            strangers.append(path)
        udo.prune_run_logs(self.tmp, 0.0001)
        for path in strangers:
            self.assertTrue(os.path.exists(path), f"deleted {path}")

    def test_a_directory_with_a_matching_name_is_left_alone(self):
        trap = os.path.join(self.tmp, "update_20200101_120000.log")
        os.makedirs(trap)
        udo.prune_run_logs(self.tmp, 1)
        self.assertTrue(os.path.isdir(trap))

    def test_subfolders_are_not_searched(self):
        nested = os.path.join(self.tmp, "filestore-backup")
        os.makedirs(nested)
        buried = age_log(nested, 999)
        udo.prune_run_logs(self.tmp, 1)
        self.assertTrue(os.path.exists(buried))

    def test_the_log_of_the_running_update_is_never_deleted(self):
        """Its name is minutes old, but a clock skew or a zero limit must not
        be able to delete the file currently being written."""
        current = udo.open_run_log(self.tmp, "ivy-odoo")
        udo.prune_run_logs(self.tmp, 0.0001, keep=current)
        self.assertTrue(os.path.exists(current))

    def test_zero_days_disables_pruning(self):
        old = age_log(self.tmp, 3650)
        self.assertEqual(udo.prune_run_logs(self.tmp, 0), 0)
        self.assertTrue(os.path.exists(old))

    def test_no_setting_disables_pruning(self):
        old = age_log(self.tmp, 3650)
        self.assertEqual(udo.prune_run_logs(self.tmp, None), 0)
        self.assertTrue(os.path.exists(old))

    def test_a_missing_folder_never_stops_the_run(self):
        self.assertEqual(
            udo.prune_run_logs(os.path.join(self.tmp, "gone"), 90), 0)


class LogRetentionSettingTest(unittest.TestCase):
    def test_the_container_setting_wins(self):
        config = {"defaults": {"log_retention_days": 90}}
        container = {"log_retention_days": 7}
        self.assertEqual(udo.resolve_log_retention(config, container), 7)

    def test_the_defaults_block_applies_without_a_container_setting(self):
        config = {"defaults": {"log_retention_days": 30}}
        self.assertEqual(udo.resolve_log_retention(config, {}), 30)

    def test_without_any_setting_the_built_in_default_applies(self):
        self.assertEqual(udo.resolve_log_retention({}, {}),
                         udo.DEFAULT_LOG_RETENTION_DAYS)

    def test_zero_is_kept_rather_than_treated_as_missing(self):
        """0 means 'never delete' - it must not fall through to the default."""
        config = {"defaults": {"log_retention_days": 0}}
        self.assertEqual(udo.resolve_log_retention(config, {}), 0)

    def test_an_unusable_value_falls_back_to_the_default_instead_of_raising(self):
        config = {"defaults": {"log_retention_days": "ninety"}}
        self.assertEqual(udo.resolve_log_retention(config, {}),
                         udo.DEFAULT_LOG_RETENTION_DAYS)

    def test_a_negative_value_is_treated_as_disabled(self):
        config = {"defaults": {"log_retention_days": -5}}
        self.assertEqual(udo.resolve_log_retention(config, {}), 0)


class DockerignoreTest(unittest.TestCase):
    """The build folder is the build context: every log file would otherwise be
    shipped to the daemon on every build."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_a_missing_dockerignore_is_created_with_the_log_pattern(self):
        udo.ensure_log_ignored(self.tmp)
        content = read(os.path.join(self.tmp, ".dockerignore"))
        self.assertIn("*.log", content.split())

    def test_an_existing_dockerignore_only_gains_the_pattern(self):
        path = os.path.join(self.tmp, ".dockerignore")
        with open(path, "w", encoding="utf8") as handle:
            handle.write("filestore-backup/\nrelease.file-*\n")
        udo.ensure_log_ignored(self.tmp)
        lines = read(path).split()
        self.assertIn("filestore-backup/", lines)
        self.assertIn("release.file-*", lines)
        self.assertIn("*.log", lines)

    def test_a_dockerignore_that_already_covers_logs_is_left_alone(self):
        path = os.path.join(self.tmp, ".dockerignore")
        original = "__pycache__/\n*.log\n*.tmp\n"
        with open(path, "w", encoding="utf8") as handle:
            handle.write(original)
        udo.ensure_log_ignored(self.tmp)
        self.assertEqual(read(path), original)

    def test_a_commented_out_pattern_does_not_count_as_covered(self):
        path = os.path.join(self.tmp, ".dockerignore")
        with open(path, "w", encoding="utf8") as handle:
            handle.write("# *.log\n")
        udo.ensure_log_ignored(self.tmp)
        self.assertIn("*.log", read(path).split())

    def test_an_unwritable_folder_never_stops_the_run(self):
        udo.ensure_log_ignored(os.path.join(self.tmp, "nope"))  # must not raise


class RunLogCaptureTest(unittest.TestCase):
    """Child output the quiet console drops must still be in the file - that is
    the entire point of the feature."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(udo.close_run_log)
        self.addCleanup(udo.RUN_LOG_FILES.clear)

    def test_filtered_info_lines_are_still_logged(self):
        path = udo.open_run_log(self.tmp, "ivy-odoo")
        udo.run_command("echo plain-info-line", show_output=False,
                        filter_output=True)
        udo.close_run_log()
        self.assertIn("plain-info-line", read(path))

    def test_warnings_and_errors_are_logged_too(self):
        path = udo.open_run_log(self.tmp, "ivy-odoo")
        udo.run_command("echo 'WARNING something is off' 1>&2",
                        show_output=False, filter_output=True)
        udo.close_run_log()
        self.assertIn("something is off", read(path))


class SelectionTest(unittest.TestCase):
    """The -s flag: repeatable, comma-separated, and stronger than 'active'."""

    def parse(self, argv):
        original = sys.argv
        sys.argv = ["update_docker_odoo.py"] + argv
        try:
            return udo.parse_arguments()
        finally:
            sys.argv = original

    def test_a_single_name_still_works(self):
        args = self.parse(["-s", "live-odoo"])
        self.assertEqual(udo.selected_container_names(args), ["live-odoo"])

    def test_the_flag_can_be_repeated(self):
        args = self.parse(["-s", "live-odoo", "-s", "test-odoo"])
        self.assertEqual(udo.selected_container_names(args),
                         ["live-odoo", "test-odoo"])

    def test_a_comma_separated_list_is_split(self):
        args = self.parse(["-s", "live-odoo,test-odoo"])
        self.assertEqual(udo.selected_container_names(args),
                         ["live-odoo", "test-odoo"])

    def test_whitespace_and_empty_parts_are_dropped(self):
        args = self.parse(["-s", " live-odoo , , test-odoo "])
        self.assertEqual(udo.selected_container_names(args),
                         ["live-odoo", "test-odoo"])

    def test_without_the_flag_the_selection_is_empty(self):
        self.assertEqual(udo.selected_container_names(self.parse([])), [])

    def test_a_named_container_runs_even_when_inactive(self):
        container = {"container_name": "parked-odoo", "active": False}
        self.assertTrue(udo.container_matches_selection(container, ["parked-odoo"]))

    def test_an_unnamed_container_is_skipped_when_a_selection_exists(self):
        container = {"container_name": "other-odoo", "active": True}
        self.assertFalse(udo.container_matches_selection(container, ["parked-odoo"]))

    def test_without_a_selection_active_decides(self):
        self.assertTrue(udo.container_matches_selection(
            {"container_name": "a", "active": True}, []))
        self.assertFalse(udo.container_matches_selection(
            {"container_name": "b", "active": False}, []))

    def test_a_container_without_an_active_key_takes_part(self):
        self.assertTrue(udo.container_matches_selection({"container_name": "a"}, []))


class RuntimeOverrideTest(unittest.TestCase):
    def parse(self, argv):
        original = sys.argv
        sys.argv = ["update_docker_odoo.py"] + argv
        try:
            return udo.parse_arguments()
        finally:
            sys.argv = original

    def test_the_type_override_is_parsed(self):
        self.assertEqual(self.parse(["--type", "F"]).update_type, "F")

    def test_an_invalid_type_is_rejected(self):
        with self.assertRaises(SystemExit):
            self.parse(["--type", "X"])

    def test_the_comment_is_parsed(self):
        self.assertEqual(self.parse(["--comment", "eq_stock"]).comment, "eq_stock")

    def test_both_default_to_none(self):
        args = self.parse([])
        self.assertIsNone(args.update_type)
        self.assertIsNone(args.comment)

    def test_no_cache_is_parsed_and_defaults_to_off(self):
        self.assertTrue(self.parse(["--no-cache"]).no_cache)
        self.assertFalse(self.parse([]).no_cache)


class VerifyBuiltImageTest(unittest.TestCase):
    """A build that reports success is not proof of a usable image.

    Docker >=29 can export an image whose layers carry nothing (moby#52431):
    the build is a two-second cache hit, the image has a plausible size, and
    every file is missing at runtime. The old image is already gone by then -
    update_docker_odoo.py removes it before building - so this cannot roll
    anything back. What it does is name the fault where it happens instead of
    letting it surface as a restart loop and an error naming the wrong file.
    """

    def setUp(self):
        self.commands = []
        self.original = udo.run_command

    def tearDown(self):
        udo.run_command = self.original

    def fake_docker(self, entrypoint="/app/bin/boot", probe_ok=True,
                    inspect_ok=True):
        def run_command(command, *_args, **_kwargs):
            self.commands.append(command)
            if "image inspect" in command:
                return (inspect_ok, entrypoint + "\n", 0, 0, 0)
            return (probe_ok, "", 0, 0, 0)
        udo.run_command = run_command

    def test_a_populated_image_passes(self):
        self.fake_docker(probe_ok=True)
        usable, problem = udo.verify_built_image("odoo/staging")
        self.assertTrue(usable)
        self.assertEqual(problem, "")

    def test_a_hollow_image_fails_and_names_the_way_out(self):
        self.fake_docker(probe_ok=False)
        usable, problem = udo.verify_built_image("odoo/staging")
        self.assertFalse(usable)
        self.assertIn("odoo/staging", problem)
        self.assertIn("/app/bin/boot", problem)
        # The daemon restart is the step that actually worked on 17.08.2026,
        # where a builder prune and --no-cache both did not. Asserting on the
        # prune instead would pass on the mere mention of it in the explanation
        # of what did NOT help - which is how this assertion started passing
        # for the wrong reason when the message was rewritten.
        self.assertIn("systemctl restart docker", problem)
        self.assertIn("does NOT prevent", problem,
                      "the message must say the overlay2 pin is no protection")

    def test_the_probe_tests_the_image_entrypoint(self):
        """Both shapes of the fault have to be caught: a hollow image has no
        /bin/sh and `docker run` itself refuses, and an image that merely lost
        its last COPY still has a shell but no entrypoint."""
        self.fake_docker(entrypoint="/app/bin/boot")
        udo.verify_built_image("odoo/staging")
        probe = self.commands[-1]
        self.assertIn("--entrypoint /bin/sh", probe)
        self.assertIn("test -x /app/bin/boot", probe)

    def test_an_image_without_an_entrypoint_is_not_condemned(self):
        """An installation may drive its container through CMD alone. Refusing
        to build that would be a worse failure than the one guarded against."""
        self.fake_docker(entrypoint="")
        usable, _ = udo.verify_built_image("odoo/staging")
        self.assertTrue(usable)
        self.assertEqual(len(self.commands), 1, "no probe should have run")

    def test_an_unreadable_image_inspect_is_not_condemned(self):
        self.fake_docker(inspect_ok=False)
        usable, _ = udo.verify_built_image("odoo/staging")
        self.assertTrue(usable)


class BuildLooksHollowTest(unittest.TestCase):
    """The retry after a failed build hangs off this predicate, so it has to
    separate the sporadic Docker defect from a real build failure. Retrying a
    Dockerfile error or a full disk would burn the same minutes twice and delay
    the message that actually helps."""

    HOLLOW = ('#16 0.226 runc run failed: unable to start container process: '
              'error during container init: exec: "/bin/sh": stat /bin/sh: '
              'no such file or directory')

    def test_the_missing_shell_is_recognised(self):
        self.assertTrue(udo.build_looks_hollow(self.HOLLOW))

    def test_a_dockerfile_error_is_not(self):
        self.assertFalse(udo.build_looks_hollow(
            "failed to solve: dockerfile parse error on line 12"))

    def test_a_full_disk_is_not(self):
        self.assertFalse(udo.build_looks_hollow(
            "write /var/lib/docker/tmp/x: no space left on device"))

    def test_a_download_timeout_is_not(self):
        self.assertFalse(udo.build_looks_hollow(
            "failed to fetch https://example.invalid/odoo.zip: timeout"))

    def test_no_output_at_all_is_not(self):
        """A build that produced nothing must not be retried on a guess."""
        self.assertFalse(udo.build_looks_hollow(None))
        self.assertFalse(udo.build_looks_hollow(""))

    def test_the_advice_is_shared_by_both_shapes(self):
        """The failed-build path and the hollow-image path must give the same
        instructions - they are the same defect seen from two sides."""
        self.assertIn("systemctl restart docker", udo.HOLLOW_IMAGE_ADVICE)
        self.assertIn("SPORADIC", udo.HOLLOW_IMAGE_ADVICE)
        self.assertIn("does NOT prevent", udo.HOLLOW_IMAGE_ADVICE)


class BenignChildNoiseTest(unittest.TestCase):
    """A warning for a correct state, repeated on every build, is how a recap
    stops being read. This one is `openssl rehash` skipping the certificate
    bundle - which it must, since a bundle is not a single certificate."""

    REHASH = ('rehash: warning: skipping ca-certificates.crt, it does not '
              'contain exactly one certificate or CRL')

    def test_the_rehash_notice_is_not_counted_as_a_warning(self):
        level, _ = udo.classify_line(self.REHASH)
        self.assertEqual(level, 'INFO')

    def test_the_line_is_still_shown_verbatim(self):
        """Not counted is not the same as hidden: the build log keeps it."""
        _, display = udo.classify_line(self.REHASH)
        self.assertIn("rehash", display)

    def test_a_real_warning_still_counts(self):
        level, _ = udo.classify_line("warning: certificate has expired")
        self.assertEqual(level, 'WARNING')

    def test_a_real_error_still_counts(self):
        level, _ = udo.classify_line("ERROR: failed to build")
        self.assertEqual(level, 'ERROR')

    def test_the_exemption_list_stays_short(self):
        """Every entry silences a warning forever, so the list may only hold
        lines whose harmlessness is established rather than assumed."""
        self.assertLessEqual(len(udo.BENIGN_CHILD_NOISE), 3)


class CleanDockerSystemTest(unittest.TestCase):
    """`docker system prune -f` removes every STOPPED container on the host, and
    every unused network, with no project filter of any kind.

    On 17.08.2026 that deleted two of a customer's Odoo containers: one had been
    stopped by hand a minute earlier for a test, and the prune following the next
    build took it. A container stopped for any unrelated reason goes the same way.
    This repository's own Docker rule forbids exactly that, so the cleanup is
    limited to what a build actually leaves behind.
    """

    def setUp(self):
        self.commands = []
        self.original = udo.run_command
        udo.run_command = self.record

    def tearDown(self):
        udo.run_command = self.original

    def record(self, command, *_args, **_kwargs):
        self.commands.append(command)
        return (True, "Total reclaimed space: 296.4MB\n", 0, 0, 0)

    def test_no_container_is_ever_pruned(self):
        udo.clean_docker_system()
        self.assertTrue(self.commands, "nothing ran at all")
        for command in self.commands:
            self.assertNotIn("system prune", command)
            self.assertNotIn("container prune", command)

    def test_networks_are_left_alone(self):
        """Pruning one frees no space and can take a network an instance needs."""
        udo.clean_docker_system()
        for command in self.commands:
            self.assertNotIn("network prune", command)

    def test_images_and_build_cache_are_still_reclaimed(self):
        """The point of the call is space. The 296MB of that run were image
        layers, so restricting it to images and cache loses nothing."""
        udo.clean_docker_system()
        joined = " ".join(self.commands)
        self.assertIn("docker image prune -f", joined)
        self.assertIn("docker builder prune -f", joined)

    def test_the_build_cache_is_not_pruned_wholesale(self):
        """`-af` would discard the cache that makes a warm build take a second
        instead of half a minute. Only unreferenced entries go."""
        udo.clean_docker_system()
        for command in self.commands:
            self.assertNotIn("prune -af", command)

    def test_a_failing_prune_stops_instead_of_carrying_on(self):
        def failing(command, *_args, **_kwargs):
            self.commands.append(command)
            return (False, "", 0, 0, 1)
        udo.run_command = failing
        _info, _warn, err = udo.clean_docker_system()
        self.assertEqual(len(self.commands), 1, "the second prune should not run")
        self.assertEqual(err, 1)


@unittest.skipUnless(HAS_REAL_YAML, "needs real PyYAML to load a config file from disk")
class MainAgainstARealConfigFileTest(unittest.TestCase):
    """Drives udo.main() end to end against a real YAML file on disk.

    Skipped without real PyYAML: main() cannot get past load_config() to
    reach any of the code these tests are actually about, so there would be
    nothing left to regress-test.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dockerfile_dir = os.path.join(self.tmp, "build")
        os.makedirs(self.dockerfile_dir)
        self.config_path = os.path.join(self.tmp, "docker2update.yaml")
        # volume already carries --dns so the always-on DNS optimisation step
        # in main() finds nothing to change and never rewrites the file for
        # a reason unrelated to what is under test here.
        self.config_text = (
            "containers:\n"
            "  - container_name: web1\n"
            "    database_name: web1_db\n"
            "    type: F\n"
            "    active: true\n"
            f"    dockerfile_path: {self.dockerfile_dir}\n"
            "    docker_image_name: myodoo:19\n"
            "    port: 8069\n"
            "    longpolling_port: 8072\n"
            "    db_user: ownerp\n"
            "    db_password: secret\n"
            "    db_host: db\n"
            "    volume: \"-v /vol:/vol --dns 1.1.1.1 --dns 8.8.8.8\"\n"
        )
        with open(self.config_path, "w", encoding="utf8") as handle:
            handle.write(self.config_text)

    def run_main(self, argv):
        original = sys.argv
        sys.argv = ["update_docker_odoo.py", "-c", self.config_path] + argv
        try:
            return udo.main()
        finally:
            sys.argv = original

    def test_a_type_override_never_reaches_the_config_file_on_disk(self):
        """--type overrides the YAML value for this run only.

        A regression guard for main()/_process_container() ever writing the
        runtime override back into the customer's config - today the
        override lives on a dict copy (see the comment above the override in
        main()) and the file is never touched for it. This is the test that
        would fail the day that stops being true.
        """
        with open(self.config_path, "rb") as handle:
            before = handle.read()

        exit_code = self.run_main(["--type", "M", "--validate"])

        with open(self.config_path, "rb") as handle:
            after = handle.read()

        self.assertEqual(exit_code, 0)
        self.assertEqual(before, after)

    def test_no_cache_reaches_the_module_flag_the_build_reads(self):
        """The flag travels as a module-level global rather than through six
        call levels, so the wiring from argv to that global is the part that
        can silently rot."""
        original = udo.BUILD_NO_CACHE
        try:
            self.assertEqual(self.run_main(["--no-cache", "--validate"]), 0)
            self.assertTrue(udo.BUILD_NO_CACHE)
            self.assertEqual(self.run_main(["--validate"]), 0)
            self.assertFalse(udo.BUILD_NO_CACHE)
        finally:
            udo.BUILD_NO_CACHE = original

    def test_an_unknown_specific_container_exits_non_zero(self):
        # Drives the real unknown-name check in main() rather than
        # re-implementing it: a typo in -s must not look like a successful
        # run that quietly updated nothing.
        exit_code = self.run_main(["-s", "does-not-exist"])
        self.assertNotEqual(exit_code, 0)


class HistoryEntryTest(unittest.TestCase):
    """The mapping from a finished container run to its history line."""

    CONTAINER = {"container_name": "live-odoo", "database_name": "live_db", "type": "F"}

    def entry(self, **kwargs):
        params = dict(container=self.CONTAINER, comment="eq_stock nachgezogen",
                      success=True, warnings=0, errors=0, duration=812.4,
                      log_path="/opt/odoo/live/update_20260811_143207.log")
        params.update(kwargs)
        return udo.history_entry(**params)

    def test_a_clean_run_is_ok(self):
        self.assertEqual(self.entry()["result"], "ok")

    def test_warnings_are_reported_as_such(self):
        self.assertEqual(self.entry(warnings=3)["result"], "warnings")

    def test_errors_outrank_warnings(self):
        self.assertEqual(self.entry(warnings=3, errors=1)["result"], "errors")

    def test_a_failed_run_is_failed_regardless_of_counts(self):
        self.assertEqual(self.entry(success=False, errors=0)["result"], "failed")

    def test_the_fields_the_tui_reads_are_present(self):
        item = self.entry()
        self.assertEqual(item["container"], "live-odoo")
        self.assertEqual(item["database"], "live_db")
        self.assertEqual(item["mode"], "F")
        self.assertEqual(item["comment"], "eq_stock nachgezogen")
        self.assertEqual(item["duration_s"], 812)
        self.assertEqual(item["script_version"], udo.SCRIPT_VERSION)
        self.assertEqual(item["log"], "/opt/odoo/live/update_20260811_143207.log")

    def test_the_timestamp_round_trips_through_the_history_format(self):
        import time as _time
        _time.strptime(self.entry()["ts"], udo.HISTORY_TS_FORMAT)

    def test_a_missing_comment_becomes_an_empty_string(self):
        # json.dumps of None would be 'null' and every reader would need a
        # special case; the empty string is what "no comment" means here.
        self.assertEqual(self.entry(comment=None)["comment"], "")


class ExternalValidationTest(unittest.TestCase):
    """--validate delegates to ownerp_validate.py, and never writes."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    # NOTE: update_docker_odoo.py does 'from os.path import ... isfile ...',
    # so the name to patch is udo.isfile - patching udo.os.path.isfile would
    # leave the module-level name untouched and the test would pass by
    # accident against the real filesystem.

    def test_it_delegates_when_the_validator_sits_beside_the_script(self):
        import subprocess
        from unittest import mock
        recorded = {}

        def fake_run(argv, **kwargs):
            recorded["argv"] = argv
            return subprocess.CompletedProcess(argv, 0)

        with mock.patch.object(udo, "isfile", return_value=True), \
             mock.patch.object(udo.subprocess, "run", side_effect=fake_run):
            handled, code = udo.run_external_validation("/etc/my.yaml")

        self.assertTrue(handled)
        self.assertEqual(code, 0)
        self.assertIn("--update", recorded["argv"])
        self.assertIn("/etc/my.yaml", recorded["argv"])
        self.assertTrue(recorded["argv"][1].endswith("ownerp_validate.py"))

    def test_it_passes_the_validators_exit_code_through(self):
        import subprocess
        from unittest import mock
        with mock.patch.object(udo, "isfile", return_value=True), \
             mock.patch.object(udo.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 1)):
            handled, code = udo.run_external_validation("/etc/my.yaml")
        self.assertEqual((handled, code), (True, 1))

    def test_it_falls_back_when_the_validator_is_absent(self):
        from unittest import mock
        with mock.patch.object(udo, "isfile", return_value=False):
            handled, code = udo.run_external_validation("/etc/my.yaml")
        self.assertFalse(handled)

    def test_the_validator_is_looked_for_beside_this_script(self):
        self.assertEqual(
            udo.validator_path(),
            os.path.join(os.path.dirname(os.path.abspath(udo.__file__)),
                         "ownerp_validate.py"))


class BuildRetryCommandTest(unittest.TestCase):
    """The retry exists for hollow layers, which live in the cache the first
    attempt just wrote. On a customer server on 26.08.2026 the retry finished
    in 0 s and produced the same unusable image - twice."""

    def test_the_first_attempt_uses_the_cache(self):
        command = udo.build_command_for_attempt("odoo/test", 1)
        self.assertNotIn("--no-cache", command)
        self.assertNotIn("--pull", command)

    def test_the_retry_builds_from_scratch(self):
        command = udo.build_command_for_attempt("odoo/test", 2)
        self.assertIn("--no-cache", command)
        self.assertIn("--pull", command)

    def test_the_first_attempt_honours_the_configured_cache_flag(self):
        command = udo.build_command_for_attempt("odoo/test", 1, cache_arg="--no-cache ")
        self.assertIn("--no-cache", command)

    def test_the_retry_does_not_duplicate_the_cache_flag(self):
        command = udo.build_command_for_attempt("odoo/test", 2, cache_arg="--no-cache ")
        self.assertEqual(command.count("--no-cache"), 1)

    def test_proxy_build_args_survive_both_attempts(self):
        for attempt in (1, 2):
            with self.subTest(attempt=attempt):
                command = udo.build_command_for_attempt(
                    "odoo/test", attempt, proxy_build_args="--build-arg HTTP_PROXY=x ")
                self.assertIn("--build-arg HTTP_PROXY=x", command)

    def test_the_image_is_tagged_and_the_context_is_the_current_directory(self):
        for attempt in (1, 2):
            with self.subTest(attempt=attempt):
                command = udo.build_command_for_attempt("odoo/test", attempt)
                self.assertIn("-t odoo/test", command)
                self.assertTrue(command.rstrip().endswith(" ."))


class BuilderCachePruneTest(unittest.TestCase):
    """--no-cache tells Docker not to USE the cache; it does not remove it.
    On 26.08.2026 clearing it first was what made the difference."""

    def setUp(self):
        self.commands = []
        self.result = (True, "Total reclaimed space: 4.2GB\n", 0, 0, 0)
        self.original = udo.run_command
        udo.run_command = self.record

    def tearDown(self):
        udo.run_command = self.original

    def record(self, command, *_args, **_kwargs):
        self.commands.append(command)
        return self.result

    def test_it_prunes_the_whole_builder_cache(self):
        udo.drop_builder_cache_before_retry()
        self.assertEqual(self.commands, ["docker builder prune -af"])

    def test_no_container_or_image_is_touched(self):
        """A build leaves cache behind; a stopped container is someone's work."""
        udo.drop_builder_cache_before_retry()
        for command in self.commands:
            self.assertNotIn("system prune", command)
            self.assertNotIn("container prune", command)
            self.assertNotIn("image prune", command)

    def test_a_failing_prune_does_not_stop_the_retry(self):
        """The retry is the point; the prune only improves its odds."""
        self.result = (False, "permission denied", 0, 0, 1)
        info, warn, err = udo.drop_builder_cache_before_retry()
        self.assertEqual((info, warn, err), (0, 0, 1))

    def test_it_reports_the_counts_for_the_run_statistics(self):
        self.result = (True, "", 3, 2, 1)
        self.assertEqual(udo.drop_builder_cache_before_retry(), (3, 2, 1))


if __name__ == "__main__":
    unittest.main()
