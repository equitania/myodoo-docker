"""
Tests for docker_table.py — the table behind `dps` and `dpsall`.

The weight is on the three things that can silently go wrong in a table:

  * the header. `docker ps --format table ... | sort` sorted the column titles
    along with the containers, and under a UTF-8 locale "NAMES" collates after
    "ivy-odoo". That defect is the reason this module exists, so the header
    is asserted to be on top and the rows below it to be sorted.
  * the frame. Padding is computed from plain text while the output carries
    ANSI escapes, and a single off-by-one shifts every row after it. Every
    rendering test measures the visible line, escapes stripped.
  * the ports. Shortening "127.0.0.1:11600->8069/tcp" to "11600→8069" throws
    away the bind address, which is exactly the bit that says whether a port
    is reachable from outside. Loopback may lose it; nothing else may.

Run from the repository root:

    python3 -m unittest tests.test_docker_table -v
"""

import contextlib
import importlib.util
import io
import os
import re
import unittest

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SCRIPTS = os.path.join(REPO, "scripts")

_spec = importlib.util.spec_from_file_location(
    "docker_table", os.path.join(SCRIPTS, "docker_table.py"))
dt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dt)

ANSI = re.compile(r"\033\[[0-9;]*m")


def visible(text):
    """The line as the terminal shows it — escapes have length but no width."""
    return ANSI.sub("", text)


class Terminal:
    """A writable stream that can claim to be a terminal, with an encoding.

    Both matter: colour is decided by isatty(), and the box characters by
    whether the encoding can carry them. It is not a StringIO subclass because
    StringIO.encoding is read-only.
    """

    def __init__(self, tty=True, encoding="utf-8"):
        self._buffer = io.StringIO()
        self._tty = tty
        self.encoding = encoding

    def write(self, text):
        return self._buffer.write(text)

    def getvalue(self):
        return self._buffer.getvalue()

    def isatty(self):
        return self._tty


FIELD = {"{{.Names}}": 0, "{{.ID}}": 1, "{{.Image}}": 2, "{{.Command}}": 3,
         "{{.CreatedAt}}": 4, "{{.Status}}": 5, "{{.Ports}}": 6}

# name, id, image, command, created, status, ports
SAMPLE = [
    ("ivy-odoo", "8dcf28d5f3d2", "odoo/ivy", "/app/bin/boot start",
     "2026-08-12 18:11:46 +0200 CEST", "Up 39 hours (healthy)",
     "127.0.0.1:11400->8069/tcp, 127.0.0.1:12400->8072/tcp"),
    ("beta1-db", "4580b5bafd94", "postgres:17.4", "docker-entrypoint.s…",
     "2026-03-27 10:17:48 +0100 CET", "Up 3 days", "5432/tcp"),
    ("Alpha-test", "aaa111bbb222", "alpine:3.20", "sh", "2026-01-01 00:00:00",
     "Exited (0) 5 weeks ago", ""),
    ("nginx-proxy", "def987654321", "nginx:1.27", "nginx -g daemon of…",
     "2026-05-01 09:00:00 +0200 CEST", "Up 2 days (unhealthy)",
     "0.0.0.0:80->80/tcp, :::80->80/tcp"),
]


def runner_for(rows, code=0, err=""):
    """A stand-in for `docker ps` that honours the requested template."""
    def run(command):
        if code != 0:
            return code, "", err
        wanted = [FIELD[t] for t in command[-1].split("\t")]
        lines = ["\t".join(row[i] for i in wanted) for row in rows]
        return 0, "\n".join(lines) + "\n", ""
    return run


def render_sample(columns=None, rows=None, tty=True, colour=None,
                  width=None, encoding="utf-8"):
    columns = columns or dt.BASIC
    parsed = dt.docker_ps(columns, runner=runner_for(rows or SAMPLE))
    out = Terminal(tty=tty, encoding=encoding)
    dt.render(parsed, columns, out, colour=colour, width=width)
    return out.getvalue()


# ==============================================================================
# The defect this module was written for
# ==============================================================================

class HeaderAndOrder(unittest.TestCase):

    def test_the_header_is_the_first_row_not_the_last(self):
        lines = visible(render_sample(width=200)).splitlines()
        self.assertIn("NAME", lines[1])
        self.assertNotIn("NAME", lines[-3])

    def test_rows_are_sorted_by_name_ignoring_case(self):
        # "Alpha-test" sorts first only if the comparison is case-insensitive;
        # a plain sort puts every capitalised name ahead of every lowercase one.
        rows = dt.docker_ps(dt.BASIC, runner=runner_for(SAMPLE))
        self.assertEqual([r[0] for r in rows],
                         ["Alpha-test", "beta1-db", "ivy-odoo",
                          "nginx-proxy"])

    def test_a_container_named_like_the_header_stays_in_the_data(self):
        # The old alias could not tell the two apart at all; here "NAMES" is
        # just another container and sorts between ivy-odoo and nginx-proxy.
        rows = list(SAMPLE) + [("NAMES", "0", "img", "cmd", "when", "Up 1 day",
                                "")]
        lines = visible(render_sample(rows=rows, width=200)).splitlines()
        self.assertTrue(lines[1].startswith("│ NAME "))
        data = [line for line in lines[3:] if line.startswith("│")]
        self.assertEqual(len(data), 5)
        self.assertTrue(data[3].startswith("│ NAMES"))


# ==============================================================================
# Ports
# ==============================================================================

class Ports(unittest.TestCase):

    def test_a_loopback_bind_loses_the_address(self):
        self.assertEqual(dt.compact_port("127.0.0.1:11600->8069/tcp"),
                         ("11600→8069", False))

    def test_a_wildcard_bind_is_marked_and_flagged_public(self):
        self.assertEqual(dt.compact_port("0.0.0.0:8080->80/tcp"),
                         ("*:8080→80", True))

    def test_the_ipv6_wildcard_is_a_wildcard_too(self):
        self.assertEqual(dt.compact_port(":::80->80/tcp"), ("*:80→80", True))

    def test_the_ipv6_loopback_is_loopback(self):
        self.assertEqual(dt.compact_port("[::1]:8069->8069/tcp"),
                         ("8069→8069", False))

    def test_a_specific_address_is_kept_verbatim_and_flagged_public(self):
        self.assertEqual(dt.compact_port("10.0.0.5:11600->8069/tcp"),
                         ("10.0.0.5:11600→8069", True))

    def test_a_non_tcp_protocol_survives(self):
        self.assertEqual(dt.compact_port("0.0.0.0:53->53/udp"),
                         ("*:53→53/udp", True))

    def test_an_exposed_but_unpublished_port_is_left_alone(self):
        self.assertEqual(dt.compact_port("5432/tcp"), ("5432/tcp", False))

    def test_a_port_range_survives(self):
        self.assertEqual(dt.compact_port("127.0.0.1:8000-8002->80-82/tcp"),
                         ("8000-8002→80-82", False))

    def test_nonsense_is_passed_through_rather_than_dropped(self):
        self.assertEqual(dt.compact_port("something odd"),
                         ("something odd", False))

    def test_a_dual_stack_publish_is_listed_once(self):
        cell = dt.ports_cell("0.0.0.0:80->80/tcp, :::80->80/tcp")
        self.assertEqual(cell.text, "*:80→80")

    def test_public_ports_are_coloured_and_loopback_ones_are_not(self):
        cell = dt.ports_cell("127.0.0.1:11600->8069/tcp, 0.0.0.0:80->80/tcp")
        colours = {colour for _, colour in cell.fragments}
        self.assertIn("yellow", colours)
        self.assertIn(None, colours)

    def test_the_ascii_arrow_is_used_when_the_frame_is_ascii(self):
        self.assertEqual(dt.compact_port("127.0.0.1:11600->8069/tcp", "->"),
                         ("11600->8069", False))


# ==============================================================================
# Status
# ==============================================================================

class Status(unittest.TestCase):

    def test_up_is_green(self):
        self.assertEqual(dt.status_colour("Up 3 days"), "green")

    def test_unhealthy_beats_up(self):
        self.assertEqual(dt.status_colour("Up 2 days (unhealthy)"), "red")

    def test_a_starting_healthcheck_is_a_warning(self):
        self.assertEqual(
            dt.status_colour("Up 5 seconds (health: starting)"), "yellow")

    def test_healthy_stays_green(self):
        self.assertEqual(dt.status_colour("Up 39 hours (healthy)"), "green")

    def test_exited_is_red(self):
        self.assertEqual(dt.status_colour("Exited (0) 5 weeks ago"), "red")

    def test_restarting_is_a_warning(self):
        self.assertEqual(dt.status_colour("Restarting (1) 3 seconds ago"),
                         "yellow")

    def test_only_up_counts_as_running(self):
        self.assertTrue(dt.is_running("Up 3 days"))
        self.assertFalse(dt.is_running("Exited (0) 5 weeks ago"))
        self.assertFalse(dt.is_running("Created"))


# ==============================================================================
# The frame
# ==============================================================================

class Frame(unittest.TestCase):

    def test_every_line_is_exactly_as_wide_as_the_widest(self):
        lines = visible(render_sample(width=200)).splitlines()[:-1]
        self.assertEqual(len(set(len(line) for line in lines)), 1)

    def test_colour_does_not_change_the_visible_width(self):
        plain = visible(render_sample(colour=False, width=200)).splitlines()
        coloured = visible(render_sample(colour=True, width=200)).splitlines()
        self.assertEqual([len(x) for x in plain], [len(x) for x in coloured])

    def test_nothing_exceeds_the_terminal_width(self):
        for width in (40, 60, 80, 100, 140):
            text = visible(render_sample(width=width))
            widest = max(len(line) for line in text.splitlines())
            self.assertLessEqual(widest, width, f"at width {width}")

    def test_a_pipe_gets_the_full_table_rather_than_a_guessed_width(self):
        piped = visible(render_sample(tty=False))
        self.assertIn("postgres:17.4", piped)
        self.assertNotIn("...", piped.splitlines()[3])

    def test_a_pipe_gets_no_colour_codes(self):
        self.assertNotIn("\033[", render_sample(tty=False))

    def test_a_terminal_gets_colour_codes(self):
        self.assertIn("\033[", render_sample(tty=True))

    def test_an_ascii_encoding_gets_an_ascii_frame(self):
        text = render_sample(encoding="ascii", width=200)
        self.assertNotIn("│", text)
        self.assertIn("|", text)
        self.assertIn("->", text)

    def test_an_unknown_encoding_does_not_raise(self):
        text = render_sample(encoding="definitely-not-a-codec", width=200)
        self.assertIn("|", text)

    def test_the_name_column_is_shrunk_only_after_the_others_bottom_out(self):
        # At 200 columns nothing needs to give; at 40 everything does.
        wide = dt.column_widths(
            dt.build_cells(dt.docker_ps(dt.BASIC, runner=runner_for(SAMPLE)),
                           dt.BASIC, dt.BOX_UNICODE), dt.BASIC, 200)
        narrow = dt.column_widths(
            dt.build_cells(dt.docker_ps(dt.BASIC, runner=runner_for(SAMPLE)),
                           dt.BASIC, dt.BOX_UNICODE), dt.BASIC, 40)
        self.assertEqual(wide[0], len("ivy-odoo"))
        self.assertLess(narrow[0], wide[0])
        self.assertGreaterEqual(min(narrow), dt.MIN_WIDTH)

    def test_the_ascii_ellipsis_never_overflows_its_column(self):
        cell = dt.Cell.plain("a-very-long-value")
        for width in (1, 2, 3, 4, 10):
            self.assertEqual(len(cell.render(width, dt.palette(None, False),
                                             "...")), width)

    def test_a_cell_of_several_fragments_pads_to_the_column(self):
        cell = dt.ports_cell("127.0.0.1:80->80/tcp, 0.0.0.0:443->443/tcp")
        self.assertEqual(len(cell.render(30, dt.palette(None, False))), 30)


# ==============================================================================
# Collecting
# ==============================================================================

class Collecting(unittest.TestCase):

    def test_a_short_line_pads_instead_of_shifting_the_columns(self):
        def run(_command):
            return 0, "lonely\tsome:image\n", ""
        rows = dt.docker_ps(dt.BASIC, runner=run)
        self.assertEqual(rows, [["lonely", "some:image", "", ""]])

    def test_an_extra_field_does_not_widen_the_row(self):
        def run(_command):
            return 0, "a\tb\tc\td\te\tf\n", ""
        rows = dt.docker_ps(dt.BASIC, runner=run)
        self.assertEqual(len(rows[0]), len(dt.BASIC))

    def test_blank_lines_are_not_containers(self):
        def run(_command):
            return 0, "a\tb\tUp 1 day\t\n\n   \n", ""
        self.assertEqual(len(dt.docker_ps(dt.BASIC, runner=run)), 1)

    def test_a_failing_docker_carries_its_own_message_and_code(self):
        run = runner_for(None, code=1, err="Cannot connect to the daemon")
        with self.assertRaises(dt.DockerError) as caught:
            dt.docker_ps(dt.BASIC, runner=run)
        self.assertIn("Cannot connect", str(caught.exception))
        self.assertEqual(caught.exception.code, 1)

    def test_a_missing_docker_binary_is_reported_not_raised_as_oserror(self):
        real = dt.subprocess.run

        def boom(*_args, **_kwargs):
            raise FileNotFoundError()

        dt.subprocess.run = boom
        try:
            with self.assertRaises(dt.DockerError) as caught:
                dt.docker_ps(dt.BASIC)
            self.assertEqual(caught.exception.code, 127)
        finally:
            dt.subprocess.run = real


# ==============================================================================
# Summary and entry point
# ==============================================================================

class Summary(unittest.TestCase):

    def test_it_counts_running_and_stopped(self):
        line = visible(render_sample(width=200)).splitlines()[-1]
        self.assertIn("4 containers", line)
        self.assertIn("3 running", line)
        self.assertIn("1 stopped", line)

    def test_a_single_container_is_not_pluralised(self):
        rows = SAMPLE[:1]
        line = visible(render_sample(rows=rows, width=200)).splitlines()[-1]
        self.assertIn("1 container ", line)


class EntryPoint(unittest.TestCase):

    def _with_docker(self, run):
        real = dt._run
        dt._run = run
        self.addCleanup(lambda: setattr(dt, "_run", real))

    def test_details_adds_the_extra_columns(self):
        self._with_docker(runner_for(SAMPLE))
        out = Terminal()
        self.assertEqual(dt.main(["--details", "--width", "220"], out), 0)
        header = visible(out.getvalue()).splitlines()[1]
        for title in ("NAME", "ID", "IMAGE", "COMMAND", "CREATED", "STATUS",
                      "PORTS"):
            self.assertIn(title, header)

    def test_the_basic_view_leaves_the_noisy_columns_out(self):
        self._with_docker(runner_for(SAMPLE))
        out = Terminal()
        self.assertEqual(dt.main(["--width", "200"], out), 0)
        header = visible(out.getvalue()).splitlines()[1]
        self.assertNotIn("COMMAND", header)
        self.assertNotIn("CREATED", header)

    def test_no_colour_flag_is_honoured_on_a_terminal(self):
        self._with_docker(runner_for(SAMPLE))
        out = Terminal(tty=True)
        dt.main(["--no-color", "--width", "200"], out)
        self.assertNotIn("\033[", out.getvalue())

    def test_no_containers_is_a_sentence_not_an_empty_frame(self):
        self._with_docker(lambda _c: (0, "", ""))
        out = Terminal()
        self.assertEqual(dt.main([], out), 0)
        self.assertIn("no containers", out.getvalue())
        self.assertNotIn("┌", out.getvalue())

    def test_a_broken_daemon_exits_with_dockers_code_and_no_traceback(self):
        self._with_docker(runner_for(None, code=1, err="daemon is down"))
        out, errors = Terminal(), io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(dt.main([], out), 1)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("daemon is down", errors.getvalue())


# ==============================================================================
# Images (dpi)
# ==============================================================================

IMAGE_SAMPLE = (
    "odoo/live:latest\t6e0f69d120fa\t2.14GB\t2 days ago\n"
    "myodoo/prepare-v19:26.07.16\t2c97d308cb12\t1.63GB\t4 months ago\n"
    "postgres:16.14\t8a4b04588618\t451MB\tAbout an hour ago\n"
    "<none>:<none>\tdeadbeef1234\t2.14GB\tLess than a second ago\n"
)


class Age(unittest.TestCase):
    """`docker images` on Docker 29 shows DISK USAGE, CONTENT SIZE and EXTRA —
    and no age, which is the question actually asked of an image list."""

    def test_dockers_wording_becomes_a_short_age(self):
        for text, expected in (("2 days ago", "2d"),
                               ("4 months ago", "4mo"),
                               ("About an hour ago", "1h"),
                               ("About a minute ago", "1m"),
                               ("7 minutes ago", "7m"),
                               ("3 weeks ago", "3w"),
                               ("2 years ago", "2y"),
                               ("Less than a second ago", "0s")):
            self.assertEqual(dt.compact_age(text)[0], expected, text)

    def test_the_age_in_days_is_what_decides_the_colour(self):
        self.assertEqual(dt.compact_age("4 months ago")[1], 120)
        self.assertEqual(dt.compact_age("2 weeks ago")[1], 14)
        self.assertEqual(dt.compact_age("5 hours ago")[1], 0)

    def test_wording_it_does_not_know_is_passed_through_not_invented(self):
        """Colouring a row on a guessed number is worse than not colouring it."""
        self.assertEqual(dt.compact_age("since the war"), ("since the war", 0))
        self.assertEqual(dt.compact_age(""), ("", 0))

    def test_a_stale_image_is_marked_and_a_fresh_one_is_not(self):
        self.assertEqual(dt.age_cell("4 months ago").fragments[0][1], "yellow")
        self.assertIsNone(dt.age_cell("2 days ago").fragments[0][1])


class Images(unittest.TestCase):

    def _with_docker(self, out=IMAGE_SAMPLE, code=0, err=""):
        real = dt._run
        dt._run = lambda _c: (code, out, err)
        self.addCleanup(lambda: setattr(dt, "_run", real))

    def render(self, width=100):
        self._with_docker()
        stream = Terminal()
        self.assertEqual(dt.main(["--images", "--width", str(width)], stream), 0)
        return visible(stream.getvalue()).splitlines()

    def test_the_header_is_the_first_row_not_the_last(self):
        lines = self.render()
        self.assertIn("IMAGE", lines[1])
        self.assertIn("AGE", lines[1])

    def test_rows_are_sorted_by_name(self):
        rows = dt.docker_images(dt.IMAGES, runner=lambda _c: (0, IMAGE_SAMPLE, ""))
        self.assertEqual([r[0] for r in rows],
                         ["<none>:<none>", "myodoo/prepare-v19:26.07.16",
                          "odoo/live:latest", "postgres:16.14"])

    def test_the_age_column_is_shortened(self):
        body = " ".join(self.render()[3:])
        self.assertIn("2d", body)
        self.assertIn("4mo", body)
        self.assertNotIn("days ago", body)

    def test_the_summary_counts_stale_and_dangling(self):
        summary = self.render()[-1]
        self.assertIn("4 images", summary)
        self.assertIn("1 older than 90 days", summary)
        self.assertIn("1 dangling", summary)

    def test_an_image_name_is_never_truncated(self):
        """A shortened repository:tag cannot be typed into `docker rmi`."""
        self.assertFalse(dict((t, s) for t, _, s in dt.IMAGES)["IMAGE"])

    def test_no_images_is_a_sentence_not_an_empty_frame(self):
        self._with_docker(out="")
        stream = Terminal()
        self.assertEqual(dt.main(["--images"], stream), 0)
        self.assertIn("no images", stream.getvalue())
        self.assertNotIn("┌", stream.getvalue())

    def test_a_broken_daemon_exits_with_dockers_code_and_no_traceback(self):
        self._with_docker(out="", code=1, err="daemon is down")
        stream, errors = Terminal(), io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(dt.main(["--images"], stream), 1)
        self.assertIn("daemon is down", errors.getvalue())

    def test_the_container_view_is_untouched_by_the_image_columns(self):
        """Same renderer, two shapes — the summary must follow the shape."""
        real = dt._run
        dt._run = runner_for(SAMPLE)
        self.addCleanup(lambda: setattr(dt, "_run", real))
        stream = Terminal()
        self.assertEqual(dt.main(["--width", "200"], stream), 0)
        self.assertIn("running", visible(stream.getvalue()).splitlines()[-1])


if __name__ == "__main__":
    unittest.main()
