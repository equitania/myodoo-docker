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


class PortParsingTest(unittest.TestCase):
    def test_the_four_accepted_forms(self):
        self.assertEqual(ov.parse_port(11000), 11000)
        self.assertEqual(ov.parse_port("11000"), 11000)
        self.assertEqual(ov.parse_port("127.0.0.1:11000"), 11000)
        self.assertEqual(ov.parse_port("[::1]:11000"), 11000)

    def test_out_of_range_and_nonsense_are_rejected(self):
        self.assertIsNone(ov.parse_port(0))
        self.assertIsNone(ov.parse_port(70000))
        self.assertIsNone(ov.parse_port("achtzehn"))
        self.assertIsNone(ov.parse_port("127.0.0.1:"))

    def test_a_bool_is_not_a_port(self):
        # True == 1 in Python; a port of True must not become port 1.
        self.assertIsNone(ov.parse_port(True))


class EmptinessTest(unittest.TestCase):
    def test_false_and_zero_are_not_empty(self):
        self.assertFalse(ov.is_empty(False))
        self.assertFalse(ov.is_empty(0))

    def test_none_and_blank_containers_are_empty(self):
        for value in (None, "", [], {}):
            self.assertTrue(ov.is_empty(value), repr(value))


class SchemaWalkerTest(unittest.TestCase):
    SCHEMA = {
        "name":   {"type": str, "required": True},
        "count":  {"type": int, "min": 0},
        "mode":   {"enum": ["M", "F", "N"]},
        "port":   {"port": True},
        "flag":   {"type": bool},
        "notes":  {"free": True},
    }

    def walk(self, mapping, downgrade=False):
        findings = []
        ov.validate_mapping(mapping, self.SCHEMA, "root", "f.yaml",
                            findings, downgrade=downgrade)
        return findings

    def test_a_clean_mapping_produces_nothing(self):
        self.assertEqual(self.walk({"name": "live", "count": 3, "mode": "F",
                                    "port": "127.0.0.1:11000", "flag": True,
                                    "notes": {"anything": [1, 2]}}), [])

    def test_a_missing_required_field_is_an_error(self):
        findings = self.walk({"count": 1})
        self.assertEqual([f.severity for f in findings], [ov.ERROR])
        self.assertEqual(findings[0].path, "root.name")

    def test_an_empty_required_field_is_an_error(self):
        self.assertEqual(self.walk({"name": ""})[0].severity, ov.ERROR)

    def test_a_wrong_type_is_an_error(self):
        findings = self.walk({"name": "live", "count": "drei"})
        self.assertEqual(findings[0].path, "root.count")
        self.assertEqual(findings[0].severity, ov.ERROR)

    def test_a_bool_is_not_accepted_where_an_int_is_required(self):
        findings = self.walk({"name": "live", "count": True})
        self.assertEqual(findings[0].path, "root.count")

    def test_a_value_below_min_is_an_error(self):
        findings = self.walk({"name": "live", "count": -1})
        self.assertIn("0", findings[0].message)

    def test_a_value_outside_the_enum_is_an_error(self):
        findings = self.walk({"name": "live", "mode": "X"})
        self.assertIn("M, F, N", findings[0].message)

    def test_an_unknown_key_is_a_warning_with_a_suggestion(self):
        findings = self.walk({"name": "live", "cout": 3})
        self.assertEqual(findings[0].severity, ov.WARNING)
        self.assertIn("count", findings[0].message)

    def test_an_unrecognisable_key_is_a_warning_without_a_suggestion(self):
        findings = self.walk({"name": "live", "zzzzzzzz": 3})
        self.assertEqual(findings[0].severity, ov.WARNING)
        self.assertNotIn("did you mean", findings[0].message)

    def test_downgrade_turns_every_error_into_a_warning(self):
        findings = self.walk({"count": "drei"}, downgrade=True)
        self.assertTrue(findings)
        self.assertTrue(all(f.severity == ov.WARNING for f in findings))
        self.assertTrue(all(f.message.startswith("(inactive)") for f in findings))

    def test_findings_carry_the_line_of_the_offending_key(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "c.yaml", """
                name: live
                count: drei
            """)
            data, _ = ov.load_positioned(path)
            findings = []
            ov.validate_mapping(data, self.SCHEMA, "root", path, findings)
            self.assertEqual(findings[0].line, 2)


class RedactionTest(unittest.TestCase):
    SCHEMA = {"db_password": {"type": str, "required": True}}

    def test_a_password_value_never_appears_in_a_finding(self):
        findings = []
        ov.validate_mapping({"db_password": 12345}, self.SCHEMA,
                            "containers[0]", "f.yaml", findings)
        self.assertTrue(findings)
        self.assertNotIn("12345", findings[0].message)

    def test_redacted_recognises_the_password_keys(self):
        self.assertTrue(ov.redacted("db_password"))
        self.assertTrue(ov.redacted("DB_PASSWORD"))
        self.assertTrue(ov.redacted("admin_passwd"))
        self.assertFalse(ov.redacted("db_user"))


class PathRuleTest(unittest.TestCase):
    SCHEMA = {"where": {"type": str, "path": "dir"}}

    def test_a_missing_path_is_a_warning(self):
        findings = []
        ov.validate_mapping({"where": "/definitely/not/here"}, self.SCHEMA,
                            "root", "f.yaml", findings)
        self.assertEqual(findings[0].severity, ov.WARNING)

    def test_an_existing_directory_produces_nothing(self):
        findings = []
        ov.validate_mapping({"where": os.path.dirname(__file__)}, self.SCHEMA,
                            "root", "f.yaml", findings)
        self.assertEqual(findings, [])
