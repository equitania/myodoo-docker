"""
Tests for the SCCS guard of getScripts.py (v9.41.0).

On 19.11.2026 `ups` overwrote a developer's own Fish configuration in a
personal account and pruned the conf.d files it did not ship (project hooks,
PATH entries). That configuration is synchronised by SCCS
(SkillsCommandsConfigsSync). A home NOT owned by root with an SCCS config is
now left alone; /root on a customer server keeps getting ours.

Standard library only. See test_getscripts_output.py for why HOME is
redirected around the import and why a placeholder stands in for `requests`.

Run from the repository root:

    python3 -m unittest tests.test_getscripts_sccs_guard -v
"""

import os
import sys
import tempfile
import types
import unittest
from unittest import mock

_REAL_HOME = os.environ.get("HOME")
os.environ["HOME"] = tempfile.mkdtemp(prefix="getscripts-test-home-")

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, REPO)
try:
    import requests  # noqa: F401
except ImportError:
    sys.modules["requests"] = types.ModuleType("requests")
import getScripts as gs  # noqa: E402

if _REAL_HOME is not None:
    os.environ["HOME"] = _REAL_HOME


SCCS_CONFIG = """\
repository:
  path: ~/gitbase/sccs-sync

sync_categories:
  claude_skills:
    enabled: true
    local_path: ~/.claude/skills
  fish_config:
    # the whole ~/.config/fish tree
    local_path: ~/.config/fish
    enabled: {fish}
  starship_config:
    enabled: {starship}
    local_path: ~/.config/starship.toml
"""


class SccsManagesTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="sccs-guard-home-")
        self.config = os.path.join(self.home, gs.SCCS_CONFIG_RELPATH)

    def _write(self, text, mode="w"):
        os.makedirs(os.path.dirname(self.config), exist_ok=True)
        with open(self.config, mode) as handle:
            handle.write(text)

    def test_no_sccs_config_means_ours_is_copied(self):
        self.assertFalse(gs.sccs_manages(self.home, "fish_config"))

    def test_enabled_category_is_managed(self):
        self._write(SCCS_CONFIG.format(fish="true", starship="true"))
        self.assertTrue(gs.sccs_manages(self.home, "fish_config"))
        self.assertTrue(gs.sccs_manages(self.home, "starship_config"))

    def test_explicitly_disabled_category_is_not_managed(self):
        self._write(SCCS_CONFIG.format(fish="false", starship="true"))
        self.assertFalse(gs.sccs_manages(self.home, "fish_config"))
        self.assertTrue(gs.sccs_manages(self.home, "starship_config"))

    def test_yaml_spellings_of_false_and_trailing_comment(self):
        for value in ("no", "Off", "'false'", "False  # parked"):
            with self.subTest(value=value):
                self._write(SCCS_CONFIG.format(fish=value, starship="true"))
                self.assertFalse(gs.sccs_manages(self.home, "fish_config"))

    def test_missing_category_counts_as_managed(self):
        # SCCS enables fish_config and starship_config by default; a config
        # that does not mention them still syncs them.
        self._write("repository:\n  path: ~/sync\nsync_categories: {}\n")
        self.assertTrue(gs.sccs_manages(self.home, "fish_config"))

    def test_block_without_enabled_key_counts_as_managed(self):
        # The enabled: of the NEXT category must not be read as this one's.
        self._write("sync_categories:\n  fish_config:\n    local_path: ~/.config/fish\n"
                    "  starship_config:\n    enabled: false\n")
        self.assertTrue(gs.sccs_manages(self.home, "fish_config"))
        self.assertFalse(gs.sccs_manages(self.home, "starship_config"))

    def test_similar_category_name_is_not_confused(self):
        self._write("sync_categories:\n  fish_functions:\n    enabled: false\n"
                    "  fish_config:\n    enabled: true\n")
        self.assertTrue(gs.sccs_manages(self.home, "fish_config"))

    def test_unreadable_config_protects_the_users_files(self):
        self._write(b"\xff\xfe not utf-8", mode="wb")
        with mock.patch.object(gs, "logger"):
            self.assertTrue(gs.sccs_manages(self.home, "fish_config"))

    def test_root_owned_home_always_gets_our_configuration(self):
        self._write(SCCS_CONFIG.format(fish="true", starship="true"))
        real_stat = os.stat

        def stat(path, *args, **kwargs):
            result = real_stat(path, *args, **kwargs)
            if os.path.realpath(path) == os.path.realpath(self.home):
                return mock.Mock(st_uid=0, st_mode=result.st_mode)
            return result

        with mock.patch.object(gs.os, "stat", side_effect=stat):
            self.assertFalse(gs.sccs_manages(self.home, "fish_config"))

    def test_missing_home_is_not_managed(self):
        self.assertFalse(gs.sccs_manages(os.path.join(self.home, "gone"), "fish_config"))


class RestrictedRunRespectsSccsTest(unittest.TestCase):
    """The restricted mode (no root, no sudo) is exactly the personal-account case."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        patches = [
            mock.patch.object(gs, "RESTRICTED_MARKER", os.path.join(self.tmp, "marker")),
            mock.patch.object(gs, "print_header"),
            mock.patch.object(gs, "ensure_proxy_environment"),
            mock.patch.object(gs, "self_update_and_reexec"),
            mock.patch.object(gs, "is_starship_installed", return_value=(True, "1.24.0")),
            mock.patch.object(gs, "is_fastfetch_installed", return_value=(False, None)),
            mock.patch.object(gs, "_offer_restricted_shell_change"),
            mock.patch.object(gs, "restricted_docker_state", return_value="absent"),
            mock.patch.object(gs.os.path, "expanduser", return_value=self.tmp),
            mock.patch.object(gs, "logger"),
            mock.patch.object(gs, "update_repository"),
            mock.patch.object(gs, "get_os_info", return_value=("debian", "13")),
            mock.patch.object(gs, "restricted_missing_packages", return_value=([], [])),
            mock.patch.object(gs, "is_fish_installed", return_value=(True, "4.0.2")),
        ]
        for patch in patches:
            patch.start()
        self.addCleanup(mock.patch.stopall)
        self.fish = mock.patch.object(gs, "copy_fish_configuration", return_value=True).start()
        self.starship = mock.patch.object(gs, "copy_starship_configuration",
                                          return_value=True).start()
        self.printed = mock.patch("builtins.print").start()

    def _output(self):
        return "\n".join(" ".join(str(a) for a in c.args) for c in self.printed.call_args_list)

    def test_sccs_managed_home_keeps_its_fish_and_starship_files(self):
        with mock.patch.object(gs, "sccs_manages", return_value=True):
            self.assertEqual(gs.run_restricted_mode(), 0)
        self.fish.assert_not_called()
        self.starship.assert_not_called()
        self.assertIn("Fish-Konfiguration: von SCCS verwaltet, übersprungen", self._output())
        self.assertIn("Starship-Prompt: von SCCS verwaltet, übersprungen", self._output())

    def test_home_without_sccs_is_set_up_as_before(self):
        with mock.patch.object(gs, "sccs_manages", return_value=False):
            self.assertEqual(gs.run_restricted_mode(), 0)
        self.fish.assert_called_once()
        self.starship.assert_called_once()


class MainPathIsGuardedTest(unittest.TestCase):
    """main() is too wide to run here; pin that both copies sit behind the guard."""

    def test_every_copy_call_is_preceded_by_its_guard(self):
        with open(os.path.join(REPO, "getScripts.py"), encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        calls = {"copy_fish_configuration(": "fish_config",
                 "copy_starship_configuration(": "starship_config"}
        for call, category in calls.items():
            sites = [i for i, line in enumerate(lines)
                     if call in line and not line.lstrip().startswith(("def ", "#"))]
            self.assertTrue(sites, call)
            for i in sites:
                window = "\n".join(lines[max(0, i - 4):i + 1])
                with self.subTest(call=call, line=i + 1):
                    self.assertIn("sccs_manages(", window)
                    self.assertIn(f'"{category}"', window)


if __name__ == "__main__":
    unittest.main()
