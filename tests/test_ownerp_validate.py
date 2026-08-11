"""
Tests for ownerp_validate.py.

Unlike the rest of the suite, these tests need a real PyYAML: the module under
test exists to parse YAML, so a placeholder module would test nothing. The
whole module skips itself when PyYAML is absent.

Run from the repository root:

    python3 -m unittest tests.test_ownerp_validate -v
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

import ownerp_validate as ov  # noqa: E402

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def write(tmpdir, name, text):
    """Write a YAML fixture and return its path."""
    path = os.path.join(tmpdir, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(textwrap.dedent(text).lstrip("\n"))
    return path


class PositionedLoadingTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_a_mapping_knows_its_own_line(self):
        path = write(self.tmp.name, "c.yaml", """
            # a comment
            defaults:
              db_user: ownerp
        """)
        data, fatal = ov.load_positioned(path)
        self.assertIsNone(fatal)
        self.assertEqual(data["defaults"].line, 3)

    def test_every_key_knows_its_own_line(self):
        path = write(self.tmp.name, "c.yaml", """
            defaults:
              db_user: ownerp
              backup_path: /opt/backups
        """)
        data, _ = ov.load_positioned(path)
        self.assertEqual(ov.line_of(data["defaults"], "db_user"), 2)
        self.assertEqual(ov.line_of(data["defaults"], "backup_path"), 3)

    def test_a_nested_mapping_reports_its_own_line_not_its_parents(self):
        path = write(self.tmp.name, "c.yaml", """
            defaults:
              compression:
                format: "7z"
        """)
        data, _ = ov.load_positioned(path)
        self.assertEqual(data["defaults"].line, 2)
        self.assertEqual(data["defaults"]["compression"].line, 3)

    def test_a_mapping_inside_a_list_keeps_its_position(self):
        path = write(self.tmp.name, "c.yaml", """
            containers:
              - container_name: live-odoo
              - container_name: test-odoo
        """)
        data, _ = ov.load_positioned(path)
        self.assertEqual(ov.line_of(data["containers"][1], "container_name"), 3)

    def test_line_of_an_unknown_key_is_zero(self):
        path = write(self.tmp.name, "c.yaml", "defaults:\n  db_user: ownerp\n")
        data, _ = ov.load_positioned(path)
        self.assertEqual(ov.line_of(data["defaults"], "nope"), 0)

    def test_broken_yaml_is_one_finding_with_a_line(self):
        path = write(self.tmp.name, "c.yaml", """
            containers:
              - active: true
               type: "F"
        """)
        data, fatal = ov.load_positioned(path)
        self.assertIsNone(data)
        self.assertEqual(fatal.severity, ov.ERROR)
        self.assertGreater(fatal.line, 0)

    def test_a_missing_file_is_a_fatal_finding(self):
        data, fatal = ov.load_positioned(os.path.join(self.tmp.name, "nope.yaml"))
        self.assertIsNone(data)
        self.assertIn("not found", fatal.message)

    def test_a_top_level_that_is_not_a_mapping_is_fatal(self):
        path = write(self.tmp.name, "c.yaml", "- one\n- two\n")
        data, fatal = ov.load_positioned(path)
        self.assertIsNone(data)
        self.assertIn("mapping", fatal.message)

    def test_an_empty_file_is_fatal(self):
        path = write(self.tmp.name, "c.yaml", "")
        data, fatal = ov.load_positioned(path)
        self.assertIsNone(data)
        self.assertIsNotNone(fatal)
