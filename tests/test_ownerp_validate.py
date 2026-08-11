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

    def test_an_unhashable_key_is_a_fatal_finding_with_a_line(self):
        # A key like "{a: 1}" is a mapping and cannot be a dict key.
        # yaml.safe_load() raises ConstructorError for this (a YAMLError
        # subclass), and load_positioned() must report the same fatal
        # finding instead of silently dropping the key/value pair - a
        # dropped pair here previously produced clean data where safe_load()
        # (what update_docker_odoo.py actually calls) raises.
        path = write(self.tmp.name, "c.yaml", "{a: 1}: stray\n")
        data, fatal = ov.load_positioned(path)
        self.assertIsNone(data)
        self.assertIsNotNone(fatal)
        self.assertEqual(fatal.severity, ov.ERROR)
        self.assertGreater(fatal.line, 0)
        self.assertIn("unhashable", fatal.message)


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

    def test_a_bool_is_not_accepted_where_a_tuple_type_includes_int(self):
        # "expected is int" is an identity check and misses a tuple like
        # (int, float) - a bool must still be rejected in that case.
        schema = {"count": {"type": (int, float)}}
        findings = []
        ov.validate_mapping({"count": True}, schema, "root", "f.yaml", findings)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].path, "root.count")

    def test_a_value_below_min_is_an_error(self):
        findings = self.walk({"name": "live", "count": -1})
        self.assertIn("0", findings[0].message)

    def test_min_without_a_type_rule_reports_a_finding_not_a_crash(self):
        # A schema may declare min/max without type; a non-numeric value must
        # not raise TypeError out of the comparison.
        schema = {"count": {"min": 0}}
        findings = []
        ov.validate_mapping({"count": "drei"}, schema, "root", "f.yaml", findings)
        self.assertEqual(findings[0].severity, ov.ERROR)
        self.assertEqual(findings[0].path, "root.count")

    def test_min_items_is_checked_without_an_item_schema(self):
        # min_items and item are independent rules - this must not depend on
        # an "item" branch being present.
        schema = {"tags": {"type": list, "min_items": 2}}
        findings = []
        ov.validate_mapping({"tags": ["one"]}, schema, "root", "f.yaml", findings)
        self.assertEqual(findings[0].severity, ov.ERROR)
        self.assertIn("2", findings[0].message)

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

    def test_a_password_value_never_appears_via_the_path_rule(self):
        # The path branch builds its own message and must go through the same
        # redaction guard as every other branch (type, enum, port).
        schema = {"db_password": {"type": str, "path": "file"}}
        findings = []
        ov.validate_mapping({"db_password": "/definitely/not/here"}, schema,
                            "root", "f.yaml", findings)
        self.assertTrue(findings)
        self.assertNotIn("/definitely/not/here", findings[0].message)


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


GOOD_UPDATE = """
    defaults:
      log_retention_days: 90
      history_retention_days: 365
    containers:
      - active: true
        type: "F"
        delay_time: 10
        container_name: "live-odoo"
        database_name: "live_odoo"
        port: "127.0.0.1:11000"
        longpolling_port: "127.0.0.1:12000"
        dockerfile_path: "{here}"
        docker_image_name: "odoo/live"
        db_user: "ownerp"
        db_password: "secret"
        db_host: "live-db"
        volume: "-v /opt/odoo/live:/opt/odoo/data"
        odoo_version: "18"
        translate: "Y"
        db_password_via_env: true
"""


class UpdateSchemaTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.here = os.path.dirname(os.path.abspath(__file__))

    def check(self, text):
        path = write(self.tmp.name, "u.yaml", text.format(here=self.here))
        findings, fatal = ov.validate_update(path)
        self.assertIsNone(fatal, fatal and fatal.message)
        return findings

    def errors(self, text):
        return [f for f in self.check(text) if f.severity == ov.ERROR]

    def test_a_good_configuration_produces_no_errors(self):
        self.assertEqual(self.errors(GOOD_UPDATE), [])

    def test_a_good_configuration_produces_no_unknown_keys(self):
        self.assertEqual(
            [f for f in self.check(GOOD_UPDATE) if "unknown key" in f.message],
            [])

    def test_a_missing_containers_section_is_an_error(self):
        errors = self.errors("defaults:\n  log_retention_days: 90\n")
        self.assertTrue(any("containers" in f.path for f in errors))

    def test_an_empty_containers_list_is_an_error(self):
        self.assertTrue(self.errors("containers: []\n"))

    def test_a_bad_type_letter_is_an_error(self):
        errors = self.errors(GOOD_UPDATE.replace('type: "F"', 'type: "X"'))
        self.assertEqual(len(errors), 1)
        self.assertIn("M, F, N", errors[0].message)

    def test_a_non_numeric_delay_time_is_an_error(self):
        errors = self.errors(GOOD_UPDATE.replace("delay_time: 10",
                                                 'delay_time: "zehn"'))
        self.assertEqual(len(errors), 1)

    def test_a_bad_retention_in_defaults_is_an_error(self):
        errors = self.errors(GOOD_UPDATE.replace("log_retention_days: 90",
                                                 'log_retention_days: "90 days"'))
        self.assertTrue(any("log_retention_days" in f.path for f in errors))

    def test_a_missing_dockerfile_path_is_a_warning_not_an_error(self):
        text = GOOD_UPDATE.replace('dockerfile_path: "{here}"',
                                   'dockerfile_path: "/definitely/not/here"')
        findings = self.check(text)
        self.assertEqual([f for f in findings if f.severity == ov.ERROR], [])
        self.assertTrue(any("dockerfile_path" in f.path for f in findings))

    def test_a_typo_in_a_container_key_is_a_warning_with_a_suggestion(self):
        findings = self.check(GOOD_UPDATE.replace('odoo_version: "18"',
                                                  'odoo_versoin: "18"'))
        hits = [f for f in findings if "unknown key" in f.message]
        self.assertEqual(len(hits), 1)
        self.assertIn("odoo_version", hits[0].message)
        self.assertEqual(hits[0].severity, ov.WARNING)


class CollisionTest(UpdateSchemaTest):
    TWO = GOOD_UPDATE + """
      - active: true
        type: "M"
        delay_time: 10
        container_name: "test-odoo"
        database_name: "test_db"
        port: "127.0.0.1:13000"
        longpolling_port: "127.0.0.1:14000"
        dockerfile_path: "{here}"
        docker_image_name: "odoo/test"
        db_user: "ownerp"
        db_password: "secret"
        db_host: "test-db"
"""

    def test_two_distinct_containers_do_not_collide(self):
        self.assertEqual(self.errors(self.TWO), [])

    def test_a_duplicate_container_name_is_an_error(self):
        errors = self.errors(self.TWO.replace('"test-odoo"', '"live-odoo"'))
        self.assertEqual(len(errors), 1)
        self.assertIn("container_name", errors[0].path)

    def test_a_duplicate_database_name_is_an_error(self):
        errors = self.errors(self.TWO.replace('"test_db"', '"live_odoo"'))
        self.assertEqual(len(errors), 1)
        self.assertIn("database_name", errors[0].path)

    def test_an_unhashable_container_name_produces_a_finding_not_a_crash(self):
        # container_name: [a, b] used to blow up _duplicates() with
        # "TypeError: unhashable type: 'list'" - the schema's own {"type":
        # str} rule must report it instead, and the duplicate check must
        # step around it without raising.
        text = GOOD_UPDATE.replace(
            'container_name: "live-odoo"',
            "container_name:\n          - a\n          - b")
        findings = self.check(text)
        self.assertTrue(any("container_name" in f.path for f in findings))

    def test_a_duplicate_port_is_an_error_naming_the_other_line(self):
        errors = self.errors(self.TWO.replace('"127.0.0.1:13000"',
                                              '"127.0.0.1:11000"'))
        self.assertEqual(len(errors), 1)
        self.assertIn("live-odoo", errors[0].message)
        self.assertIn("line", errors[0].message)

    def test_a_port_colliding_with_a_longpolling_port_is_an_error(self):
        # Both are host ports and share one namespace.
        errors = self.errors(self.TWO.replace('"127.0.0.1:13000"',
                                              '"127.0.0.1:12000"'))
        self.assertEqual(len(errors), 1)

    def test_the_same_port_on_a_different_bind_address_is_still_a_collision(self):
        errors = self.errors(self.TWO.replace('"127.0.0.1:13000"',
                                              '"0.0.0.0:11000"'))
        self.assertEqual(len(errors), 1)

    def test_an_inactive_container_never_collides(self):
        # The second block reuses the first block's port, but cannot run.
        text = (self.TWO
                .replace('"127.0.0.1:13000"', '"127.0.0.1:11000"')
                .replace('- active: true\n        type: "M"',
                         '- active: false\n        type: "M"'))
        self.assertIn('active: false', text)   # the replace really matched
        self.assertEqual(self.errors(text), [])


class InactiveDowngradeTest(UpdateSchemaTest):
    BROKEN = GOOD_UPDATE.replace('type: "F"', 'type: "X"')

    def test_a_broken_active_block_yields_errors(self):
        self.assertTrue(self.errors(self.BROKEN))

    def test_the_same_block_inactive_yields_warnings_only(self):
        findings = self.check(self.BROKEN.replace("active: true",
                                                  "active: false"))
        self.assertEqual([f for f in findings if f.severity == ov.ERROR], [])
        self.assertTrue(any("(inactive)" in f.message for f in findings))


GOOD_BACKUP = """
    defaults:
      retention_days: 14
      db_user: ownerp
      backup_path: "{here}"
      temp_path: "{here}"
      stream: false
      compression:
        format: "7z"
        level: 5
    services:
      nginx:
        enabled: true
        source_path: "{here}"
        backup_path: nginx
        retention_days: 7
    databases:
      - name: live_db
        sql_container: live-db
        data_container: live-odoo
        retention_days: 7
        only_sql_dump: false
        fast_report:
          enabled: false
          path: "{here}"
    rsync:
      enabled: false
      commands: []
"""


class BackupSchemaTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.here = os.path.dirname(os.path.abspath(__file__))

    def check(self, text):
        path = write(self.tmp.name, "b.yaml", text.format(here=self.here))
        findings, fatal = ov.validate_backup(path)
        self.assertIsNone(fatal, fatal and fatal.message)
        return findings

    def errors(self, text):
        return [f for f in self.check(text) if f.severity == ov.ERROR]

    def test_a_good_configuration_produces_no_errors(self):
        self.assertEqual(self.errors(GOOD_BACKUP), [])

    def test_a_good_configuration_produces_no_unknown_keys(self):
        self.assertEqual(
            [f for f in self.check(GOOD_BACKUP) if "unknown key" in f.message],
            [])

    def test_an_unknown_compression_format_is_an_error(self):
        errors = self.errors(GOOD_BACKUP.replace('format: "7z"',
                                                 'format: "rar"'))
        self.assertEqual(len(errors), 1)

    def test_a_compression_level_above_nine_is_an_error(self):
        self.assertTrue(self.errors(GOOD_BACKUP.replace("level: 5",
                                                        "level: 11")))

    def test_a_service_without_a_source_path_is_an_error(self):
        errors = self.errors(GOOD_BACKUP.replace(
            'source_path: "{here}"\n        backup_path: nginx',
            'backup_path: nginx'))
        self.assertTrue(any("source_path" in f.path for f in errors))

    def test_a_service_without_a_backup_path_is_an_error(self):
        # This one is a KeyError at runtime today, not a message.
        # The replacement must remove the whole indented line - leaving the
        # leading spaces behind merges into the next line's indentation and
        # turns this into a YAML syntax error instead of the missing-key
        # scenario the test is after.
        errors = self.errors(GOOD_BACKUP.replace(
            "        backup_path: nginx\n", ""))
        self.assertTrue(any("services.nginx.backup_path" in f.path
                            for f in errors))

    def test_a_database_without_a_sql_container_is_an_error(self):
        errors = self.errors(GOOD_BACKUP.replace(
            "        sql_container: live-db\n", ""))
        self.assertTrue(any("sql_container" in f.path for f in errors))

    def test_an_unhashable_database_name_produces_a_finding_not_a_crash(self):
        # databases[].name: [a, b] routes through the same _duplicates() as
        # container_name/database_name above and used to crash the same way.
        text = GOOD_BACKUP.replace(
            "- name: live_db",
            "- name:\n            - a\n            - b", 1)
        findings = self.check(text)
        self.assertTrue(any("name" in f.path for f in findings))

    def test_a_duplicate_database_name_is_an_error(self):
        # Inserted ahead of "rsync:" (i.e. still inside the databases list,
        # at the same indentation as the existing entry) - appending after
        # the whole fixture would land the block below "rsync:", outside
        # "databases:" entirely, and break YAML parsing.
        text = GOOD_BACKUP.replace(
            "    rsync:",
            "      - name: live_db\n"
            "        sql_container: other-db\n"
            "        data_container: other-odoo\n"
            "    rsync:")
        errors = self.errors(text)
        self.assertEqual(len(errors), 1)
        self.assertIn("name", errors[0].path)

    def test_additional_paths_is_known_and_not_inspected(self):
        text = GOOD_BACKUP.replace("        only_sql_dump: false",
                                   "        only_sql_dump: false\n"
                                   "        additional_paths:\n"
                                   "          whatever:\n"
                                   "            anything: 1")
        self.assertEqual(
            [f for f in self.check(text) if "unknown key" in f.message], [])

    def test_a_typo_in_defaults_is_a_warning_with_a_suggestion(self):
        findings = self.check(GOOD_BACKUP.replace("retention_days: 14",
                                                  "retention_day: 14"))
        hits = [f for f in findings if "unknown key" in f.message]
        self.assertEqual(len(hits), 1)
        self.assertIn("retention_days", hits[0].message)


class ShippedTemplateTest(unittest.TestCase):
    """The schema must know every key the shipped templates carry.

    Without this, a key added to a template a year from now silently becomes a
    false 'unknown key' on every customer server, and the typo check is the
    first thing operators learn to ignore. Path warnings are expected here -
    the templates point at paths that only exist on a real server.
    """

    def assert_clean(self, findings, path):
        errors = [f for f in findings if f.severity == ov.ERROR]
        self.assertEqual(errors, [], f"{path}: {[f.message for f in errors]}")
        unknown = [f for f in findings if "unknown key" in f.message]
        self.assertEqual(unknown, [],
                         f"{path}: {[f.message for f in unknown]}")

    def test_the_update_template_validates(self):
        path = os.path.join(REPO_ROOT, "scripts", "docker2update.yaml")
        findings, fatal = ov.validate_update(path)
        self.assertIsNone(fatal)
        self.assert_clean(findings, path)

    def test_the_proxy_example_validates(self):
        path = os.path.join(REPO_ROOT, "scripts",
                            "docker2update-proxy-example.yaml")
        findings, fatal = ov.validate_update(path)
        self.assertIsNone(fatal)
        self.assert_clean(findings, path)

    def test_the_backup_template_validates(self):
        path = os.path.join(REPO_ROOT, "scripts", "container2backup.yaml")
        findings, fatal = ov.validate_backup(path)
        self.assertIsNone(fatal)
        self.assert_clean(findings, path)


class CommandLineTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.here = os.path.dirname(os.path.abspath(__file__))

    def run_main(self, argv):
        import contextlib
        import io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = ov.main(argv)
        return code, buffer.getvalue()

    def test_a_clean_file_exits_zero(self):
        path = write(self.tmp.name, "u.yaml", GOOD_UPDATE.format(here=self.here))
        code, output = self.run_main(["--update", path])
        self.assertEqual(code, 0)
        self.assertIn("no findings", output)

    def test_an_error_exits_one(self):
        text = GOOD_UPDATE.format(here=self.here).replace('type: "F"', 'type: "X"')
        path = write(self.tmp.name, "u.yaml", text)
        code, output = self.run_main(["--update", path])
        self.assertEqual(code, 1)
        self.assertIn("1 error", output)

    def test_a_warning_alone_still_exits_zero(self):
        text = GOOD_UPDATE.format(here=self.here).replace(
            f'dockerfile_path: "{self.here}"', 'dockerfile_path: "/nope/nope"')
        path = write(self.tmp.name, "u.yaml", text)
        code, output = self.run_main(["--update", path])
        self.assertEqual(code, 0)
        self.assertIn("warning", output)

    def test_unparseable_yaml_exits_two(self):
        path = write(self.tmp.name, "u.yaml",
                     "containers:\n  - active: true\n   type: F\n")
        code, _ = self.run_main(["--update", path])
        self.assertEqual(code, 2)

    def test_a_file_named_explicitly_but_missing_exits_two(self):
        code, output = self.run_main(
            ["--update", os.path.join(self.tmp.name, "nope.yaml")])
        self.assertEqual(code, 2)
        self.assertIn("not found", output)

    def test_a_default_file_that_is_absent_is_skipped_not_fatal(self):
        # The default paths are computed at import time, so patching HOME here
        # would change nothing and the test would silently read the real ~.
        from unittest import mock
        absent = os.path.join(self.tmp.name, "absent.yaml")
        with mock.patch.object(ov, "DEFAULT_UPDATE_CONFIG", absent), \
             mock.patch.object(ov, "DEFAULT_BACKUP_CONFIG", absent):
            code, output = self.run_main([])
        self.assertEqual(code, 0)
        self.assertIn("skipped", output)

    def test_the_report_names_the_line(self):
        text = GOOD_UPDATE.format(here=self.here).replace('type: "F"', 'type: "X"')
        path = write(self.tmp.name, "u.yaml", text)
        _, output = self.run_main(["--update", path])
        self.assertRegex(output, r"\s6\s")   # 'type:' sits on line 6

    def test_version_prints_and_exits_zero(self):
        code, output = self.run_main(["--version"])
        self.assertEqual(code, 0)
        self.assertIn(ov.SCRIPT_VERSION, output)
