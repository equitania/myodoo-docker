"""
Tests for ownerp_wizard.py.

Like the validator's tests, these need a real PyYAML: the wizard imports
ownerp_validate, which subclasses yaml.SafeLoader. The whole module skips
itself when PyYAML is absent.

Run from the repository root:

    python3 -m unittest tests.test_ownerp_wizard -v
"""

import io
import os
import sys
import shutil
import contextlib
import tempfile
import textwrap
import unittest
from unittest import mock

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

    def test_a_ctrl_c_mid_write_leaves_no_backup_and_no_temp_file(self):
        # KeyboardInterrupt does not inherit from Exception, so a narrower
        # except clause walks straight past it and leaves the litter behind.
        with mock.patch.object(wiz.validator, "validate_update",
                               side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                wiz.safe_write(self.path, self.lines())
        self.assertEqual(self.leftovers(), [])
        self.assertEqual(self.current(), self.original)

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

    def test_the_bind_address_is_read_off_a_port_value(self):
        self.assertEqual(wiz.bind_prefix("127.0.0.1:11000"), "127.0.0.1:")
        self.assertEqual(wiz.bind_prefix("[::1]:11000"), "[::1]:")
        self.assertEqual(wiz.bind_prefix(11000), "")
        self.assertEqual(wiz.bind_prefix("not a port"), "")

    def test_a_unanimous_bind_address_is_suggested(self):
        self.assertEqual(wiz.suggest_bind(CONTAINERS), "127.0.0.1:")

    def test_a_split_bind_address_suggests_none(self):
        containers = [dict(CONTAINERS[0]), dict(CONTAINERS[1], port=13000)]
        self.assertEqual(wiz.suggest_bind(containers), "")

    def test_a_port_suggestion_keeps_the_shipped_bind_address(self):
        # A bare number on a 127.0.0.1 host would publish the new instance on
        # every interface - a change nobody asked for and nobody sees.
        port = [f for f in wiz.UPDATE_FORM if f.name == "port"][0]
        self.assertEqual(port.suggest(CONTAINERS, {}), "127.0.0.1:15000")

    def test_a_longpolling_suggestion_keeps_it_too(self):
        poll = [f for f in wiz.UPDATE_FORM if f.name == "longpolling_port"][0]
        suggestion = poll.suggest(CONTAINERS, {"port": "127.0.0.1:15000"})
        self.assertTrue(str(suggestion).startswith("127.0.0.1:"), suggestion)

    def test_an_empty_configuration_suggests_a_bare_port(self):
        port = [f for f in wiz.UPDATE_FORM if f.name == "port"][0]
        self.assertEqual(port.suggest([], {}), 11000)

    def test_a_bare_replacement_keeps_the_old_bind_address(self):
        self.assertEqual(wiz.keep_bind_address("127.0.0.1:13000", 19000),
                         "127.0.0.1:19000")

    def test_an_explicit_replacement_wins(self):
        self.assertEqual(wiz.keep_bind_address("127.0.0.1:13000", "0.0.0.0:19000"),
                         "0.0.0.0:19000")

    def test_an_unbound_old_value_stays_unbound(self):
        self.assertEqual(wiz.keep_bind_address(13000, 19000), 19000)

    def test_a_non_port_field_is_left_alone(self):
        self.assertEqual(wiz.keep_bind_address("live-db", "demo-db"), "demo-db")

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


class CoerceTest(unittest.TestCase):
    def test_a_boolean_field_takes_yes_and_no(self):
        self.assertIs(wiz.coerce("active", "true"), True)
        self.assertIs(wiz.coerce("active", "false"), False)

    def test_an_integer_field_becomes_an_int(self):
        self.assertEqual(wiz.coerce("delay_time", "10"), 10)

    def test_a_port_field_keeps_a_bind_address_as_text(self):
        self.assertEqual(wiz.coerce("port", "127.0.0.1:11000"),
                         "127.0.0.1:11000")

    def test_a_bare_port_becomes_an_int(self):
        self.assertEqual(wiz.coerce("port", "11000"), 11000)

    def test_a_string_field_stays_text(self):
        self.assertEqual(wiz.coerce("container_name", "demo-odoo"),
                         "demo-odoo")

    def test_a_field_typed_as_a_tuple_stays_text(self):
        # odoo_version is (str, int) in the schema. The int branch must not
        # claim it - "18" is written as a string in every shipped template.
        self.assertEqual(wiz.coerce("odoo_version", "18"), "18")


class SummaryTest(unittest.TestCase):
    def test_the_password_is_masked(self):
        lines = wiz.summary_lines(NEW_ENTRY)
        joined = "\n".join(lines)
        self.assertNotIn("s3cret", joined)
        self.assertIn("*", joined)

    def test_every_other_value_is_shown(self):
        joined = "\n".join(wiz.summary_lines(NEW_ENTRY))
        self.assertIn("demo-odoo", joined)
        self.assertIn("15000", joined)


class PrintFindingsTest(unittest.TestCase):
    def test_the_blocking_error_is_told_apart_from_the_warnings(self):
        import ownerp_validate as ov
        findings = [
            ov.Finding(ov.WARNING, "c.yaml", 85, "containers[0].dockerfile_path",
                       "/x does not exist"),
            ov.Finding(ov.ERROR, "c.yaml", 119, "containers[2].type",
                       '"X" is not one of M, F, N'),
        ]
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            wiz.print_findings(findings)
        warning_line, error_line = buffer.getvalue().rstrip("\n").split("\n")
        self.assertIn("warning", warning_line)
        self.assertIn("error", error_line)
        self.assertNotIn("error", warning_line)

    def test_a_password_value_never_reaches_the_output(self):
        import ownerp_validate as ov
        findings = [ov.Finding(ov.ERROR, "c.yaml", 12, "containers[0].db_password",
                               f"{ov._shown('db_password', 's3cret')} is wrong")]
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            wiz.print_findings(findings)
        self.assertNotIn("s3cret", buffer.getvalue())


class PreflightTest(unittest.TestCase):
    def test_it_refuses_without_a_tty(self):
        with mock.patch.object(wiz.sys.stdout, "isatty", return_value=False):
            self.assertIsNotNone(wiz.preflight())

    def test_it_refuses_without_the_validator(self):
        with mock.patch.object(wiz, "validator", None), \
             mock.patch.object(wiz.sys.stdout, "isatty", return_value=True), \
             mock.patch.object(wiz.sys.stdin, "isatty", return_value=True):
            reason = wiz.preflight()
        self.assertIsNotNone(reason)
        self.assertIn("ups", reason)

    def test_it_passes_with_a_tty_and_the_validator(self):
        with mock.patch.object(wiz.sys.stdout, "isatty", return_value=True), \
             mock.patch.object(wiz.sys.stdin, "isatty", return_value=True):
            self.assertIsNone(wiz.preflight())


class BuildFolderTest(unittest.TestCase):
    """The wizard's one write outside the YAML, and only after asking."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.target = os.path.join(self.tmp.name, "docker-builds", "demo-odoo")

    def test_it_creates_the_directory_on_yes(self):
        with mock.patch.object(wiz, "confirm", return_value=True), \
             contextlib.redirect_stdout(io.StringIO()):
            wiz.offer_build_folder(self.target)
        self.assertTrue(os.path.isdir(self.target))

    def test_it_creates_nothing_on_no(self):
        with mock.patch.object(wiz, "confirm", return_value=False), \
             contextlib.redirect_stdout(io.StringIO()):
            wiz.offer_build_folder(self.target)
        self.assertFalse(os.path.exists(self.target))

    def test_it_does_not_ask_when_the_directory_exists(self):
        os.makedirs(self.target)
        with mock.patch.object(wiz, "confirm") as asked, \
             contextlib.redirect_stdout(io.StringIO()):
            wiz.offer_build_folder(self.target)
        asked.assert_not_called()

    def test_it_puts_nothing_inside_the_new_directory(self):
        # Populating a build folder belongs to odoo_build_cache.py.
        with mock.patch.object(wiz, "confirm", return_value=True), \
             contextlib.redirect_stdout(io.StringIO()):
            wiz.offer_build_folder(self.target)
        self.assertEqual(os.listdir(self.target), [])


class _TTYBuffer(io.StringIO):
    """A capture buffer that still looks like a terminal.

    redirect_stdout replaces sys.stdout *after* any patch of the old object,
    so patching the real stdout's isatty does nothing once the redirect is in
    place - preflight() then refuses and main() returns 2 before reaching a
    single prompt. That failure mode passed one of these tests for the wrong
    reason, because the refusal message also names 'doval'.
    """

    def isatty(self):
        return True


class MainTest(unittest.TestCase):
    def test_version_prints_and_exits_zero(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = wiz.main(["--version"])
        self.assertEqual(code, 0)
        self.assertIn(wiz.SCRIPT_VERSION, buffer.getvalue())

    def test_it_exits_two_without_a_tty_on_stdout(self):
        buffer = io.StringIO()  # a plain buffer is not a terminal
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(wiz.main([]), 2)
        self.assertIn("edup", buffer.getvalue())

    def test_it_exits_two_without_a_tty_on_stdin(self):
        buffer = _TTYBuffer()
        with mock.patch.object(wiz.sys.stdin, "isatty", return_value=False), \
             contextlib.redirect_stdout(buffer):
            self.assertEqual(wiz.main([]), 2)
        self.assertIn("edup", buffer.getvalue())

    def test_ctrl_d_at_a_prompt_is_an_abort_not_a_traceback(self):
        # A closed stdin reaches the prompt as EOFError. The __main__ guard
        # turns it into a sentence, not a stack trace - and nothing is written
        # either way.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "c.yaml")
        shutil.copy(TEMPLATE, path)
        with open(path, encoding="utf-8") as handle:
            before = handle.read()
        with mock.patch.object(wiz.sys.stdin, "isatty", return_value=True), \
             mock.patch("builtins.input", side_effect=EOFError), \
             contextlib.redirect_stdout(_TTYBuffer()):
            with self.assertRaises(EOFError):
                wiz.main(["--update", path])
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), before)
        self.assertEqual(sorted(os.listdir(tmp.name)), ["c.yaml"])

    def test_it_exits_two_when_the_configuration_does_not_parse(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        broken = os.path.join(tmp.name, "broken.yaml")
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write("containers:\n  - this: is: not: yaml\n")
        buffer = _TTYBuffer()
        with mock.patch.object(wiz.sys.stdin, "isatty", return_value=True), \
             contextlib.redirect_stdout(buffer):
            code = wiz.main(["--update", broken])
        self.assertEqual(code, 2)
        # "Fix it first" comes only from the parse branch; "doval" alone would
        # also match the no-TTY refusal.
        self.assertIn("Fix it first", buffer.getvalue())


# ==============================================================================
# Stage 2: the backup configuration, and the write API both callers share
# ==============================================================================

BACKUP_TEMPLATE = os.path.join(REPO_ROOT, "scripts", "container2backup.yaml")

BACKUP_CONFIG = textwrap.dedent("""\
    defaults:
      retention_days: 14
      db_user: ownerp
      backup_path: /opt/backups
      temp_path: /tmp/odoo_backup
      stream: false
      compression:
        format: "7z"
        level: 5

    databases:
      - name: live_db
        db_user: ownerp
        sql_container: live-db
        data_container: live-odoo
        retention_days: 5
""")

UPDATE_CONFIG = textwrap.dedent("""\
    defaults:
      log_retention_days: 90

    containers:
      - active: true
        type: F
        delay_time: 10
        container_name: live-odoo
        database_name: live_db
        port: "127.0.0.1:11000"
        longpolling_port: "127.0.0.1:12000"
        dockerfile_path: /root/docker-builds/live-odoo/
        docker_image_name: odoo/live
        db_user: ownerp
        db_password: secret
        db_host: live-db
        volume: "-v /opt/odoo/live:/opt/odoo/data"
        odoo_version: "18"
        translate: Y
""")


# Appended to UPDATE_CONFIG when a second entry is needed. Written out rather
# than dedented inline: the list indentation is two spaces and getting it wrong
# produces a YAML error that reads like a bug in the code under test.
SECOND_CONTAINER = (
    "  - active: true\n"
    "    type: F\n"
    "    container_name: test-odoo\n"
    "    database_name: test_db\n"
    '    port: "127.0.0.1:13000"\n'
    '    longpolling_port: "127.0.0.1:14000"\n'
    "    dockerfile_path: /root/docker-builds/test-odoo/\n"
    "    docker_image_name: odoo/test\n"
    "    db_user: ownerp\n"
    "    db_password: secret\n"
    "    db_host: test-db\n"
    '    volume: "-v /opt/odoo/test:/opt/odoo/data"\n'
    '    odoo_version: "18"\n'
    "    translate: Y\n"
)


class ConfigFixture(unittest.TestCase):
    """A throwaway directory holding both configurations."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="wizard-stage2-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.backup = self.write("container2backup.yaml", BACKUP_CONFIG)
        self.update = self.write("docker2update.yaml", UPDATE_CONFIG)

    def write(self, name, text):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def read(self, path):
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def parsed(self, path):
        return yaml.safe_load(self.read(path))


class BackupWriteTest(ConfigFixture):
    """container2backup.yaml had no editor at all before this."""

    def test_a_database_is_appended_and_the_file_still_parses(self):
        result = wiz.add_entry(self.backup, {
            "name": "test_db", "sql_container": "test-db",
            "data_container": "test-odoo", "db_user": "ownerp",
            "retention_days": 7,
        }, kind=wiz.BACKUP)
        self.assertTrue(result.ok, result.error or result.findings)
        names = [d["name"] for d in self.parsed(self.backup)["databases"]]
        self.assertEqual(names, ["live_db", "test_db"])

    def test_the_existing_entry_is_untouched_by_an_append(self):
        before = self.read(self.backup).splitlines()
        wiz.add_entry(self.backup, {
            "name": "test_db", "sql_container": "test-db",
            "data_container": "test-odoo",
        }, kind=wiz.BACKUP)
        after = self.read(self.backup).splitlines()
        self.assertEqual(before, after[:len(before)])

    def test_a_field_of_an_existing_database_is_changed_in_place(self):
        result = wiz.set_field(self.backup, 0, "retention_days", 30,
                               kind=wiz.BACKUP)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(self.parsed(self.backup)["databases"][0]["retention_days"],
                         30)

    def test_a_duplicate_database_name_is_refused_before_the_write(self):
        result = wiz.add_entry(self.backup, {
            "name": "live_db", "sql_container": "other-db",
            "data_container": "other-odoo",
        }, kind=wiz.BACKUP)
        self.assertFalse(result.ok)
        self.assertIn("already in use", result.error)
        self.assertEqual(self.read(self.backup), BACKUP_CONFIG)

    def test_an_entry_missing_a_required_field_is_rejected_and_nothing_changes(self):
        """sql_container is required; the validator must catch it, not the disk."""
        result = wiz.add_entry(self.backup, {"name": "test_db"},
                               kind=wiz.BACKUP)
        self.assertFalse(result.ok)
        self.assertIsNone(result.backup)
        self.assertEqual(self.read(self.backup), BACKUP_CONFIG)

    def test_the_backup_schema_is_used_not_the_update_one(self):
        """Validating this file as an update config would reject every field."""
        result = wiz.set_field(self.backup, 0, "only_sql_dump", True,
                               kind=wiz.BACKUP)
        self.assertTrue(result.ok, result.error)
        self.assertIs(self.parsed(self.backup)["databases"][0]["only_sql_dump"],
                      True)

    def test_the_shipped_template_can_be_appended_to(self):
        """The real template, whose last entry ends in a nested fast_report
        block. entry_bounds has to walk past that mapping to find the end of
        the list, and landing inside it would produce unparseable YAML."""
        path = self.write("from-template.yaml", self.read(BACKUP_TEMPLATE))
        before = [d["name"] for d in self.parsed(path)["databases"]]
        result = wiz.add_entry(path, {
            "name": "third_db", "sql_container": "third-db",
            "data_container": "third-odoo",
        }, kind=wiz.BACKUP)
        self.assertTrue(result.ok, result.error or result.findings)
        self.assertEqual([d["name"] for d in self.parsed(path)["databases"]],
                         before + ["third_db"])

    def test_the_nested_block_of_the_previous_entry_survives(self):
        path = self.write("from-template.yaml", self.read(BACKUP_TEMPLATE))
        wiz.add_entry(path, {"name": "third_db", "sql_container": "third-db",
                             "data_container": "third-odoo"}, kind=wiz.BACKUP)
        by_name = {d["name"]: d for d in self.parsed(path)["databases"]}
        self.assertEqual(by_name["live_db"]["fast_report"]["path"],
                         "/opt/fast-report/fr-live")


class SuggestionFromUpdateConfigTest(ConfigFixture):
    """The pairing is already written down once; retyping it invites a typo."""

    def test_the_containers_come_from_the_matching_update_entry(self):
        instances = wiz.update_instances(self.update)
        entry = {"name": "live_db"}
        self.assertEqual(
            wiz.suggest_from_instance("sql_container", entry, instances),
            "live-db")
        self.assertEqual(
            wiz.suggest_from_instance("data_container", entry, instances),
            "live-odoo")

    def test_an_unknown_database_suggests_nothing(self):
        instances = wiz.update_instances(self.update)
        self.assertIsNone(wiz.suggest_from_instance(
            "sql_container", {"name": "nope_db"}, instances))

    def test_two_instances_on_one_database_suggest_nothing(self):
        """That is a config error the validator reports; a guess would obscure it."""
        doubled = UPDATE_CONFIG + SECOND_CONTAINER.replace("test_db", "live_db")
        path = self.write("doubled.yaml", doubled)
        instances = wiz.update_instances(path)
        self.assertIsNone(wiz.suggest_from_instance(
            "sql_container", {"name": "live_db"}, instances))

    def test_a_missing_update_config_costs_a_suggestion_not_the_editor(self):
        self.assertEqual(wiz.update_instances(os.path.join(self.dir, "gone.yaml")),
                         [])

    def test_a_broken_update_config_costs_a_suggestion_not_the_editor(self):
        path = self.write("broken.yaml", "containers: [unclosed\n")
        self.assertEqual(wiz.update_instances(path), [])

    def test_retention_falls_back_to_what_the_others_agree_on(self):
        databases = [{"retention_days": 5}, {"retention_days": 5}]
        self.assertEqual(wiz.suggest_backup_unanimous(databases,
                                                      "retention_days"), 5)

    def test_a_disagreement_suggests_the_fallback_rather_than_a_guess(self):
        databases = [{"retention_days": 5}, {"retention_days": 30}]
        self.assertEqual(
            wiz.suggest_backup_unanimous(databases, "retention_days", 14), 14)


class WriteApiTest(ConfigFixture):
    """The API the console consumes. No terminal is involved anywhere here."""

    def test_a_missing_file_is_an_error_not_an_exception(self):
        result = wiz.set_field(os.path.join(self.dir, "gone.yaml"), 0, "x", 1)
        self.assertFalse(result.ok)
        self.assertIn("not found", result.error)

    def test_an_unparseable_file_is_an_error_not_an_exception(self):
        path = self.write("broken.yaml", "containers: [unclosed\n")
        result = wiz.set_field(path, 0, "port", 11000)
        self.assertFalse(result.ok)
        self.assertIsNotNone(result.error)

    def test_an_index_out_of_range_says_so(self):
        result = wiz.set_field(self.update, 99, "port", 11000)
        self.assertIn("no entry 99", result.error)

    def test_a_list_valued_field_is_refused_rather_than_guessed_at(self):
        path = self.write("withlist.yaml", UPDATE_CONFIG
                          + "    pre_build_files:\n"
                            "      - /root/certs/ca.crt\n")
        result = wiz.set_field(path, 0, "pre_build_files", "x")
        self.assertFalse(result.ok)
        self.assertIn("not a scalar", result.error)

    def test_changing_a_port_keeps_its_bind_address(self):
        """127.0.0.1:11000 -> 19000 must not become a public bind."""
        result = wiz.set_field(self.update, 0, "port", 19000)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(self.parsed(self.update)["containers"][0]["port"],
                         "127.0.0.1:19000")

    def test_renaming_a_container_to_an_existing_name_is_refused(self):
        path = self.write("two.yaml", UPDATE_CONFIG + SECOND_CONTAINER)
        result = wiz.set_field(path, 1, "container_name", "live-odoo")
        self.assertFalse(result.ok)
        self.assertIn("already in use", result.error)

    def test_setting_a_field_to_its_own_value_is_not_a_duplicate(self):
        result = wiz.set_field(self.update, 0, "container_name", "live-odoo")
        self.assertTrue(result.ok, result.error)

    def test_a_rejected_write_leaves_no_backup_behind(self):
        """A .bak-* of a file nobody changed teaches operators to ignore them."""
        wiz.add_entry(self.backup, {"name": "broken_db"}, kind=wiz.BACKUP)
        leftovers = [f for f in os.listdir(self.dir) if ".bak-" in f]
        self.assertEqual(leftovers, [])

    def test_a_successful_write_keeps_its_backup(self):
        result = wiz.set_field(self.backup, 0, "retention_days", 21,
                               kind=wiz.BACKUP)
        self.assertTrue(os.path.isfile(result.backup))
        self.assertEqual(self.read(result.backup), BACKUP_CONFIG)

    def test_the_backup_holds_the_previous_content_exactly(self):
        wiz.set_field(self.update, 0, "delay_time", 45)
        backups = [f for f in os.listdir(self.dir) if ".bak-" in f]
        self.assertEqual(len(backups), 1)
        self.assertEqual(self.read(os.path.join(self.dir, backups[0])),
                         UPDATE_CONFIG)


class GenericCollectionTest(ConfigFixture):
    """The update-shaped names must stay exactly what they were."""

    def test_the_legacy_names_still_target_containers(self):
        lines, data, error = wiz.load_config(self.update)
        self.assertIsNone(error)
        self.assertEqual(wiz.containers_end(lines, data),
                         wiz.collection_end(lines, data, "containers"))

    def test_appending_without_a_kind_still_means_update(self):
        lines, data, _ = wiz.load_config(self.update)
        entry = {"container_name": "x-odoo", "database_name": "x_db"}
        self.assertEqual(wiz.append_container(lines, data, entry),
                         wiz.append_entry(lines, data, entry, wiz.UPDATE))

    def test_a_file_without_the_collection_key_says_so(self):
        path = self.write("nokey.yaml", "defaults:\n  retention_days: 14\n")
        result = wiz.add_entry(path, {"name": "x_db",
                                      "sql_container": "a",
                                      "data_container": "b"},
                               kind=wiz.BACKUP)
        self.assertFalse(result.ok)
        self.assertIn("databases", result.error)
