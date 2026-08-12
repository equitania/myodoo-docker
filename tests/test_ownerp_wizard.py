"""
Tests for ownerp_wizard.py.

Like the validator's tests, these need a real PyYAML: the wizard imports
ownerp_validate, which subclasses yaml.SafeLoader. The whole module skips
itself when PyYAML is absent.

Run from the repository root:

    python3 -m unittest tests.test_ownerp_wizard -v
"""

import os
import sys
import textwrap
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

try:
    import yaml  # noqa: F401
except ImportError:  # pragma: no cover - depends on the machine
    raise unittest.SkipTest("PyYAML is not installed")

import ownerp_wizard as wiz  # noqa: E402

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TEMPLATE = os.path.join(REPO_ROOT, "scripts", "docker2update.yaml")


class SplitCommentTest(unittest.TestCase):
    def test_a_plain_line_has_no_comment(self):
        self.assertEqual(wiz.split_comment('    port: "11000"'),
                         ('    port: "11000"', ""))

    def test_a_trailing_comment_is_split_off(self):
        code, comment = wiz.split_comment('    x: true  # secure default')
        self.assertEqual(code, '    x: true')
        self.assertEqual(comment, '  # secure default')

    def test_a_hash_inside_a_double_quoted_value_is_not_a_comment(self):
        line = '    volume: "-v /opt/a#b:/data"'
        self.assertEqual(wiz.split_comment(line), (line, ""))

    def test_a_hash_inside_a_single_quoted_value_is_not_a_comment(self):
        line = "    volume: '-v /opt/a#b:/data'"
        self.assertEqual(wiz.split_comment(line), (line, ""))

    def test_a_quoted_hash_and_a_real_comment_together(self):
        code, comment = wiz.split_comment('    v: "a#b"  # note')
        self.assertEqual(code, '    v: "a#b"')
        self.assertEqual(comment, '  # note')

    def test_a_hash_without_leading_space_is_not_a_comment(self):
        # 'a#b' unquoted is a legal YAML scalar; '#' only starts a comment
        # when it follows whitespace.
        line = '    v: a#b'
        self.assertEqual(wiz.split_comment(line), (line, ""))

    def test_code_and_comment_reconstruct_the_line(self):
        for line in ('    x: true  # secure default',
                     '    v: "a#b"  # note',
                     '    port: "11000"'):
            code, comment = wiz.split_comment(line)
            self.assertEqual(code + comment, line)


class FormatValueTest(unittest.TestCase):
    def test_strings_are_double_quoted(self):
        self.assertEqual(wiz.format_value("live-odoo"), '"live-odoo"')

    def test_booleans_are_lowercase_and_bare(self):
        self.assertEqual(wiz.format_value(True), "true")
        self.assertEqual(wiz.format_value(False), "false")

    def test_integers_are_bare(self):
        self.assertEqual(wiz.format_value(10), "10")

    def test_a_quote_inside_a_string_is_escaped(self):
        self.assertEqual(wiz.format_value('a"b'), '"a\\"b"')

    def test_a_backslash_inside_a_string_is_escaped(self):
        self.assertEqual(wiz.format_value("a\\b"), '"a\\\\b"')

    def test_the_result_round_trips_through_yaml(self):
        for value in ("live-odoo", "$HOME/x/", 'a"b', "a\\b", "a#b", True, 10):
            rendered = wiz.format_value(value)
            self.assertEqual(yaml.safe_load(f"k: {rendered}")["k"], value,
                             f"round trip failed for {value!r}")


class PatchLineTest(unittest.TestCase):
    def test_the_value_is_replaced_and_indentation_kept(self):
        self.assertEqual(wiz.patch_line('    port: "11000"', "12000"),
                         '    port: "12000"')

    def test_a_trailing_comment_survives(self):
        self.assertEqual(
            wiz.patch_line('    db_password_via_env: true  # secure default',
                           False),
            '    db_password_via_env: false  # secure default')

    def test_a_hash_inside_the_old_value_does_not_confuse_it(self):
        self.assertEqual(wiz.patch_line('    v: "a#b"  # note', "c"),
                         '    v: "c"  # note')

    def test_the_first_key_of_a_list_entry_keeps_its_dash(self):
        self.assertEqual(wiz.patch_line('  - active: true', False),
                         '  - active: false')

    def test_a_line_without_a_key_is_refused(self):
        with self.assertRaises(ValueError):
            wiz.patch_line("    # just a comment", "x")


class EntryBoundsTest(unittest.TestCase):
    LINES = textwrap.dedent("""
        containers:
          - active: true
            type: "F"
          - active: false
            type: "M"

        # trailing comment
    """).lstrip("\n").split("\n")

    def test_the_first_entry_ends_where_the_second_begins(self):
        self.assertEqual(wiz.entry_bounds(self.LINES, 2, 2), (1, 3))

    def test_the_last_entry_ends_before_the_blank_tail(self):
        first, last = wiz.entry_bounds(self.LINES, 4, 2)
        self.assertEqual(first, 3)
        self.assertEqual(last, 5)
