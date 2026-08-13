"""
Tests for the login command overview (fish/functions/linux/ownerp-help.fish).

The panel is curated by hand — an auto-listing of every alias would be forty
lines nobody reads. Curation rots: an alias gets renamed, the panel keeps
advertising the old name, and the operator who trusted it types something that
does not exist. That is what this pins.

Run from the repository root:

    python3 -m unittest tests.test_fish_help -v
"""

import os
import re
import shlex
import unittest

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
FISH = os.path.join(REPO, "fish")
HELP = os.path.join(FISH, "functions", "linux", "ownerp-help.fish")
PROMPT = os.path.join(FISH, "conf.d", "50-prompt.fish")

# Commands that are not aliases or functions of this repository: external tools
# delivered by other packages. Naming them here is the point — an unexplained
# gap in the check would be indistinguishable from a typo.
EXTERNAL = {"odoodev"}


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def advertised_commands():
    """Every command the panel names, in order.

    Read from the __ownerp_help_row calls rather than from the rendered output:
    running fish would make this test depend on a shell the CI image may not
    have, and the call arguments are the source of truth either way.
    """
    commands = []
    for line in read(HELP).splitlines():
        line = line.strip()
        if not line.startswith("__ownerp_help_row"):
            continue
        parts = shlex.split(line)
        # func, label, cmd1, desc1, cmd2, desc2
        for index in (2, 4):
            if len(parts) > index and parts[index]:
                commands.append(parts[index])
    return commands


def defined_names():
    """Alias and function names this repository's fish config defines."""
    names = set()
    conf_dir = os.path.join(FISH, "conf.d")
    for entry in os.listdir(conf_dir):
        if not entry.endswith(".fish"):
            continue
        for match in re.finditer(r"^alias\s+'?([^'=\s]+)'?=",
                                 read(os.path.join(conf_dir, entry)), re.MULTILINE):
            names.add(match.group(1))
    functions_dir = os.path.join(FISH, "functions")
    for root, _dirs, files in os.walk(functions_dir):
        for entry in files:
            if not entry.endswith(".fish"):
                continue
            for match in re.finditer(r"^function\s+'?([^'\s]+)'?",
                                     read(os.path.join(root, entry)), re.MULTILINE):
                names.add(match.group(1))
    return names


class AdvertisedCommandsTest(unittest.TestCase):
    def test_the_panel_advertises_something(self):
        self.assertGreater(len(advertised_commands()), 10)

    def test_every_advertised_command_exists(self):
        defined = defined_names()
        missing = [c for c in advertised_commands()
                   if c not in defined and c not in EXTERNAL]
        self.assertEqual(missing, [],
                         f"the login panel names commands that do not exist: {missing}")

    def test_the_commands_this_release_added_are_on_it(self):
        advertised = advertised_commands()
        for command in ("docron", "tui", "wiz", "doval"):
            self.assertIn(command, advertised)


class LoginBehaviourTest(unittest.TestCase):
    def test_the_panel_is_login_only(self):
        """A tmux session with six panes must not print it six times."""
        text = read(PROMPT)
        self.assertIn("status is-login", text)

    def test_fastfetch_still_runs_on_every_interactive_shell(self):
        self.assertIn("fastfetch", read(PROMPT))

    def test_a_missing_function_does_not_break_the_login(self):
        """An older server gets the file after the config; the guard matters."""
        self.assertIn("functions -q ownerp-help", read(PROMPT))

    def test_help_is_reachable_by_name(self):
        aliases = read(os.path.join(FISH, "conf.d", "30-aliases-system.fish"))
        self.assertRegex(aliases, r"(?m)^alias help='ownerp-help'")


if __name__ == "__main__":
    unittest.main()
