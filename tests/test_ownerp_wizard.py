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
import shutil
import tempfile
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


def validator_error():
    import ownerp_validate
    return ownerp_validate.ERROR


class SafeWriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "docker2update.yaml")
        shutil.copy(TEMPLATE, self.path)
        with open(self.path, encoding="utf-8") as handle:
            self.original = handle.read()

    def lines(self):
        with open(self.path, encoding="utf-8") as handle:
            return handle.read().split("\n")

    def current(self):
        with open(self.path, encoding="utf-8") as handle:
            return handle.read()

    def leftovers(self):
        return sorted(n for n in os.listdir(self.tmp.name)
                      if n != "docker2update.yaml")

    def test_a_clean_write_replaces_the_file_and_keeps_the_backup(self):
        new = self.lines()
        new.insert(0, "# touched by the test")
        ok, findings, backup = wiz.safe_write(self.path, new)
        self.assertTrue(ok, [f.message for f in findings])
        self.assertTrue(self.current().startswith("# touched by the test"))
        self.assertTrue(os.path.isfile(backup))
        with open(backup, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), self.original)

    def test_a_rejected_write_leaves_the_original_byte_identical(self):
        new = [line.replace('type: "F"', 'type: "X"') for line in self.lines()]
        ok, findings, backup = wiz.safe_write(self.path, new)
        self.assertFalse(ok)
        self.assertEqual(self.current(), self.original)
        self.assertIsNone(backup)
        self.assertTrue(any(f.severity == validator_error() for f in findings))

    def test_a_rejected_write_leaves_no_backup_and_no_temp_file(self):
        new = [line.replace('type: "F"', 'type: "X"') for line in self.lines()]
        wiz.safe_write(self.path, new)
        self.assertEqual(self.leftovers(), [])

    def test_unparseable_output_is_rejected_too(self):
        new = self.lines() + ["  this: is: not: yaml"]
        ok, _findings, backup = wiz.safe_write(self.path, new)
        self.assertFalse(ok)
        self.assertEqual(self.current(), self.original)
        self.assertIsNone(backup)
        self.assertEqual(self.leftovers(), [])

    def test_warnings_alone_do_not_block_the_write(self):
        # The template's dockerfile_path does not exist here - a warning.
        new = self.lines()
        ok, findings, _backup = wiz.safe_write(self.path, new)
        self.assertTrue(ok)
        self.assertTrue(findings, "expected the path warnings")

    def test_the_backup_name_carries_a_timestamp(self):
        import datetime
        stamp = datetime.datetime(2026, 8, 11, 19, 30, 5)
        self.assertTrue(
            wiz.backup_name("/x/c.yaml", stamp).endswith(".bak-20260811_193005"))

    def test_the_temp_file_lives_beside_the_original(self):
        # os.replace() is only atomic within one filesystem.
        seen = {}
        real_replace = os.replace

        def spy(src, dst):
            seen["src"] = src
            return real_replace(src, dst)

        from unittest import mock
        with mock.patch.object(wiz.os, "replace", side_effect=spy):
            wiz.safe_write(self.path, self.lines())
        self.assertEqual(os.path.dirname(seen["src"]),
                         os.path.dirname(self.path))


CONTAINERS = [
    {"container_name": "live-odoo", "database_name": "live_odoo",
     "port": "127.0.0.1:11000", "longpolling_port": "127.0.0.1:12000",
     "dockerfile_path": "$HOME/docker-builds/live-odoo/",
     "docker_image_name": "odoo/live", "db_user": "ownerp",
     "db_host": "live-db", "odoo_version": "18", "active": True},
    {"container_name": "test-odoo", "database_name": "test_db",
     "port": "127.0.0.1:13000", "longpolling_port": "127.0.0.1:14000",
     "dockerfile_path": "$HOME/docker-builds/test-odoo/",
     "docker_image_name": "odoo/test", "db_user": "ownerp",
     "db_host": "test-db", "odoo_version": "18", "active": False},
]


class FormMatchesSchemaTest(unittest.TestCase):
    """The one test that keeps the form and the schema from drifting apart."""

    def test_every_required_schema_field_is_asked_for(self):
        import ownerp_validate as ov
        required = {name for name, rule in ov.CONTAINER_FIELDS.items()
                    if rule.get("required")}
        asked = {field.name for field in wiz.UPDATE_FORM}
        self.assertEqual(required - asked, set(),
                         "required schema fields missing from the form")

    def test_every_form_field_exists_in_the_schema(self):
        import ownerp_validate as ov
        asked = {field.name for field in wiz.UPDATE_FORM}
        self.assertEqual(asked - set(ov.CONTAINER_FIELDS), set(),
                         "form asks for fields the schema does not know")

    def test_the_form_asks_in_the_shipped_order(self):
        self.assertEqual([f.name for f in wiz.UPDATE_FORM][:5],
                         ["active", "type", "delay_time",
                          "container_name", "database_name"])

    def test_every_field_has_a_label_and_help(self):
        for field in wiz.UPDATE_FORM:
            self.assertTrue(field.label, field.name)
            self.assertTrue(field.help, field.name)

    def test_the_form_asks_for_no_list_or_mapping_field(self):
        # Scalars only: pre_build_files and proxy have no single line to
        # replace, so the wizard shows them and never edits them.
        import ownerp_validate as ov
        for field in wiz.UPDATE_FORM:
            expected = ov.CONTAINER_FIELDS[field.name].get("type")
            self.assertNotIn(expected, (list, dict), field.name)


class SuggestionTest(unittest.TestCase):
    def test_used_ports_covers_both_port_fields_and_inactive_entries(self):
        self.assertEqual(wiz.used_ports(CONTAINERS),
                         {11000, 12000, 13000, 14000})

    def test_the_next_free_port_clears_every_used_one(self):
        port = wiz.suggest_free_port(CONTAINERS)
        self.assertNotIn(port, wiz.used_ports(CONTAINERS))
        self.assertGreater(port, 14000)

    def test_the_longpolling_port_does_not_collide_with_the_http_port(self):
        http = wiz.suggest_free_port(CONTAINERS)
        poll = wiz.suggest_longpolling(CONTAINERS, http)
        self.assertNotEqual(poll, http)
        self.assertNotIn(poll, wiz.used_ports(CONTAINERS))

    def test_an_empty_configuration_falls_back_to_the_template_port(self):
        self.assertEqual(wiz.suggest_free_port([]), 11000)

    def test_a_unanimous_value_is_suggested(self):
        self.assertEqual(wiz.suggest_unanimous(CONTAINERS, "db_user"), "ownerp")

    def test_a_split_value_is_not_suggested(self):
        self.assertIsNone(wiz.suggest_unanimous(CONTAINERS, "db_host"))

    def test_an_empty_configuration_suggests_nothing_unanimous(self):
        self.assertIsNone(wiz.suggest_unanimous([], "db_user"))

    def test_the_path_pattern_substitutes_the_new_name(self):
        self.assertEqual(
            wiz.suggest_path_pattern(CONTAINERS, "dockerfile_path", "demo-odoo"),
            "$HOME/docker-builds/demo-odoo/")

    def test_the_path_pattern_gives_up_when_the_paths_disagree(self):
        containers = [dict(CONTAINERS[0]),
                      dict(CONTAINERS[1], dockerfile_path="/srv/other/")]
        self.assertIsNone(
            wiz.suggest_path_pattern(containers, "dockerfile_path", "demo-odoo"))

    def test_the_image_name_follows_the_shipped_convention(self):
        # live-odoo -> odoo/live, so demo-odoo -> odoo/demo. Name substitution
        # cannot do this: "live-odoo" does not occur in "odoo/live".
        self.assertEqual(wiz.suggest_image_name(CONTAINERS, "demo-odoo"),
                         "odoo/demo")

    def test_the_image_name_gives_up_when_the_prefixes_disagree(self):
        containers = [dict(CONTAINERS[0]),
                      dict(CONTAINERS[1], docker_image_name="other/test")]
        self.assertIsNone(wiz.suggest_image_name(containers, "demo-odoo"))

    def test_an_empty_configuration_suggests_the_template_image_prefix(self):
        self.assertEqual(wiz.suggest_image_name([], "demo-odoo"), "odoo/demo")

    def test_no_suggestion_is_offered_for_a_password(self):
        password = [f for f in wiz.UPDATE_FORM if f.name == "db_password"][0]
        self.assertIsNone(password.suggest)


NEW_ENTRY = {
    "active": True, "type": "F", "delay_time": 10,
    "container_name": "demo-odoo", "database_name": "demo_db",
    "port": 15000, "longpolling_port": 16000,
    "dockerfile_path": "$HOME/docker-builds/demo-odoo/",
    "docker_image_name": "odoo/demo", "db_user": "ownerp",
    "db_password": "s3cret", "db_host": "demo-db",
    "volume": "--network demo-db-net -v /opt/odoo/demo:/opt/odoo/data",
    "odoo_version": "18", "translate": "Y", "db_password_via_env": True,
}


class AppendTest(unittest.TestCase):
    def setUp(self):
        with open(TEMPLATE, encoding="utf-8") as handle:
            self.lines = handle.read().split("\n")
        self.data, fatal = wiz.validator.load_positioned(TEMPLATE)
        self.assertIsNone(fatal)

    def test_the_result_parses_and_holds_the_new_entry(self):
        result = wiz.append_container(self.lines, self.data, NEW_ENTRY)
        parsed = yaml.safe_load("\n".join(result))
        names = [c["container_name"] for c in parsed["containers"]]
        self.assertEqual(names[-1], "demo-odoo")

    def test_every_entered_value_survives_the_round_trip(self):
        result = wiz.append_container(self.lines, self.data, NEW_ENTRY)
        parsed = yaml.safe_load("\n".join(result))["containers"][-1]
        for key, value in NEW_ENTRY.items():
            if key in ("port", "longpolling_port"):
                self.assertEqual(wiz.validator.parse_port(parsed[key]), value)
            else:
                self.assertEqual(parsed[key], value, key)

    def test_every_pre_existing_line_is_untouched(self):
        # Split at the real insertion point rather than assuming the template
        # ends with exactly one blank line - the property under test is
        # "nothing else moved", not "the file has a particular tail".
        at = wiz.containers_end(self.lines, self.data)
        block = wiz.render_container(NEW_ENTRY)
        result = wiz.append_container(self.lines, self.data, NEW_ENTRY)
        self.assertEqual(result[:at], self.lines[:at])
        self.assertEqual(result[at + len(block):], self.lines[at:])

    def test_the_block_matches_the_shipped_indentation(self):
        block = wiz.render_container(NEW_ENTRY)
        self.assertTrue(block[0].startswith("  - "), block[0])
        self.assertTrue(all(l.startswith("    ") for l in block[1:]), block)

    def test_the_appended_block_carries_the_pgpassword_note(self):
        # An operator reading the file afterwards should not be able to tell a
        # generated block from a typed one - and the note is what stops
        # somebody turning the flag off without reading why it is on.
        block = wiz.render_container(NEW_ENTRY)
        line = [l for l in block if "db_password_via_env" in l][0]
        self.assertIn("PGPASSWORD", line)


class PatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "c.yaml")
        shutil.copy(TEMPLATE, self.path)
        with open(self.path, encoding="utf-8") as handle:
            self.lines = handle.read().split("\n")
        self.data, _ = wiz.validator.load_positioned(self.path)

    def test_only_the_target_line_changes(self):
        result = wiz.patch_field(self.lines, self.data, 0, "port", 19000)
        self.assertEqual(len(result), len(self.lines))
        differing = [i for i, (a, b) in enumerate(zip(self.lines, result))
                     if a != b]
        self.assertEqual(len(differing), 1, differing)

    def test_the_new_value_is_readable_again(self):
        result = wiz.patch_field(self.lines, self.data, 0, "port", 19000)
        parsed = yaml.safe_load("\n".join(result))["containers"][0]
        self.assertEqual(wiz.validator.parse_port(parsed["port"]), 19000)

    def test_the_second_container_is_reachable_and_the_first_untouched(self):
        # This is what save_updated_config() gets wrong: it scans forward for
        # the next matching key and can land in the following entry.
        result = wiz.patch_field(self.lines, self.data, 1, "port", 19000)
        parsed = yaml.safe_load("\n".join(result))["containers"]
        self.assertEqual(wiz.validator.parse_port(parsed[1]["port"]), 19000)
        self.assertEqual(wiz.validator.parse_port(parsed[0]["port"]), 11000)

    def test_a_trailing_comment_on_the_target_line_survives(self):
        result = wiz.patch_field(self.lines, self.data, 0,
                                 "db_password_via_env", False)
        # Match the data line, not the key's own mention in the template's
        # header comment - "in l" would find that one first.
        line = [l for l in result
                if l.strip().startswith("db_password_via_env")][0]
        self.assertIn("#", line)
        self.assertIn("false", line)

    def test_an_absent_field_is_inserted_at_the_entrys_indentation(self):
        result = wiz.patch_field(self.lines, self.data, 0,
                                 "log_retention_days", 30)
        parsed = yaml.safe_load("\n".join(result))["containers"][0]
        self.assertEqual(parsed["log_retention_days"], 30)
        line = [l for l in result
                if l.strip().startswith("log_retention_days")][0]
        self.assertTrue(line.startswith("    "), repr(line))

    def test_an_inserted_field_lands_in_its_own_entry(self):
        result = wiz.patch_field(self.lines, self.data, 0,
                                 "log_retention_days", 30)
        parsed = yaml.safe_load("\n".join(result))["containers"]
        self.assertNotIn("log_retention_days", parsed[1])

    def test_patching_never_touches_another_entrys_line(self):
        result = wiz.patch_field(self.lines, self.data, 0, "port", 19000)
        parsed = yaml.safe_load("\n".join(result))["containers"][1]
        self.assertEqual(wiz.validator.parse_port(parsed["port"]), 13000)
        self.assertEqual(wiz.validator.parse_port(parsed["longpolling_port"]),
                         14000)

    def test_a_patched_file_still_validates(self):
        result = wiz.patch_field(self.lines, self.data, 0, "port", 19000)
        ok, findings, _backup = wiz.safe_write(self.path, result)
        self.assertTrue(ok, [f.message for f in findings])
