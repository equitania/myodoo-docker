"""
Tests for odoo_build_cache.py.

Standard library only (unittest, http.server) — these scripts run on customer
servers with the system Python, so the repository deliberately has no test
framework dependency.

Run from the repository root:

    python3 -m unittest tests.test_odoo_build_cache -v
"""

import http.server
import io
import os
import sys
import tempfile
import threading
import time
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import odoo_build_cache as obc  # noqa: E402


def write(path, text):
    with open(path, "w", encoding="utf8") as handle:
        handle.write(text)
    return path


def make_zip_bytes():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("payload.txt", "content")
    return buffer.getvalue()


DOCKERFILE = """FROM registry.invalid/prepare:1.0
LABEL maintainer=info@example.invalid
# comment
# Date 01.01.2026

COPY build_odoo.py /opt/odoo/
COPY release.file /opt/odoo/

RUN cd /opt/odoo/ && \\
    python3 build_odoo.py
"""


class ParseReleaseFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_returns_base_url_and_archives_in_order(self):
        path = write(os.path.join(self.tmp, "release.file"), "\n".join([
            "https://example.invalid/19.0/",
            "registry.invalid/prepare:1.0",
            "kernel-a.zip",
            "mod_b.zip",
            "mod_c.zip",
            "",
        ]))
        base_url, names = obc.parse_release_file(path)
        self.assertEqual(base_url, "https://example.invalid/19.0/")
        self.assertEqual(names, ["kernel-a.zip", "mod_b.zip", "mod_c.zip"])

    def test_skips_line_two_and_blank_lines(self):
        path = write(os.path.join(self.tmp, "release.file"), "\n".join([
            "https://example.invalid/19.0/",
            "registry.invalid/prepare:1.0",
            "",
            "kernel-a.zip",
            "",
            "mod_b.zip",
        ]))
        _, names = obc.parse_release_file(path)
        self.assertEqual(names, ["kernel-a.zip", "mod_b.zip"])

    def test_rejects_unsafe_names(self):
        path = write(os.path.join(self.tmp, "release.file"), "\n".join([
            "https://example.invalid/19.0/",
            "registry.invalid/prepare:1.0",
            "kernel-a.zip",
            "../../etc/passwd",
            "mod_b.zip",
        ]))
        _, names = obc.parse_release_file(path)
        self.assertEqual(names, ["kernel-a.zip", "mod_b.zip"])

    def test_raises_when_url_missing(self):
        path = write(os.path.join(self.tmp, "release.file"), "False\nx\ny.zip\n")
        with self.assertRaises(ValueError):
            obc.parse_release_file(path)


class CachePathTest(unittest.TestCase):
    def test_path_includes_host_and_url_path(self):
        path = obc.cache_path_for("/cache", "https://example.invalid/19.0/", "mod_b.zip")
        self.assertEqual(path, "/cache/example.invalid/19.0/mod_b.zip")

    def test_versions_do_not_collide(self):
        a = obc.cache_path_for("/cache", "https://example.invalid/19.0/", "same.zip")
        b = obc.cache_path_for("/cache", "https://example.invalid/16.0/", "same.zip")
        self.assertNotEqual(a, b)

    def test_url_without_trailing_slash(self):
        path = obc.cache_path_for("/cache", "https://example.invalid/19.0", "mod_b.zip")
        self.assertEqual(path, "/cache/example.invalid/19.0/mod_b.zip")

    def test_traversal_in_name_is_refused(self):
        with self.assertRaises(ValueError):
            obc.cache_path_for("/cache", "https://example.invalid/19.0/", "../escape.zip")

    def test_absolute_name_is_refused(self):
        with self.assertRaises(ValueError):
            obc.cache_path_for("/cache", "https://example.invalid/19.0/", "/etc/passwd")

    def test_root_env_override(self):
        os.environ["ODOO_BUILD_CACHE"] = "/tmp/xyz"
        try:
            self.assertEqual(obc.cache_root(), "/tmp/xyz")
        finally:
            del os.environ["ODOO_BUILD_CACHE"]


class ServeFiles(http.server.BaseHTTPRequestHandler):
    """Serves whatever the test put into self.server.files; counts requests."""

    def do_GET(self):
        self.server.hits.append(self.path)
        body = self.server.files.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class HttpFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cache = os.path.join(self.tmp, "cache")
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ServeFiles)
        self.server.files = {}
        self.server.hits = []
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/19.0/"

    def tearDown(self):
        self.server.shutdown()


class FetchTest(HttpFixture):
    def test_downloads_missing_archive(self):
        self.server.files["/19.0/mod_b.zip"] = make_zip_bytes()
        self.assertTrue(obc.fetch_into_cache(self.base_url, "mod_b.zip", self.cache))
        self.assertTrue(os.path.isfile(obc.cache_path_for(self.cache, self.base_url, "mod_b.zip")))

    def test_second_call_does_not_hit_the_server(self):
        self.server.files["/19.0/mod_b.zip"] = make_zip_bytes()
        obc.fetch_into_cache(self.base_url, "mod_b.zip", self.cache)
        self.server.hits.clear()
        self.assertTrue(obc.fetch_into_cache(self.base_url, "mod_b.zip", self.cache))
        self.assertEqual(self.server.hits, [])

    def test_hit_refreshes_mtime(self):
        self.server.files["/19.0/mod_b.zip"] = make_zip_bytes()
        obc.fetch_into_cache(self.base_url, "mod_b.zip", self.cache)
        path = obc.cache_path_for(self.cache, self.base_url, "mod_b.zip")
        os.utime(path, (1000, 1000))
        obc.fetch_into_cache(self.base_url, "mod_b.zip", self.cache)
        self.assertGreater(os.path.getmtime(path), 1000)

    def test_html_error_page_is_refused(self):
        self.server.files["/19.0/mod_b.zip"] = b"<html>error</html>"
        self.assertFalse(obc.fetch_into_cache(self.base_url, "mod_b.zip", self.cache))
        self.assertFalse(os.path.exists(obc.cache_path_for(self.cache, self.base_url, "mod_b.zip")))

    def test_404_is_not_retried(self):
        self.assertFalse(obc.fetch_into_cache(self.base_url, "absent.zip", self.cache))
        self.assertEqual(len(self.server.hits), 1)

    def test_no_partial_file_left_behind(self):
        self.server.files["/19.0/mod_b.zip"] = b"<html>error</html>"
        obc.fetch_into_cache(self.base_url, "mod_b.zip", self.cache)
        leftovers = []
        for current, _dirs, files in os.walk(self.cache):
            leftovers.extend(os.path.join(current, name) for name in files)
        self.assertEqual(leftovers, [])


class PopulateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cache = os.path.join(self.tmp, "cache")
        self.build = os.path.join(self.tmp, "build")
        os.makedirs(self.build)
        self.base_url = "https://example.invalid/19.0/"

    def _put(self, name):
        path = obc.cache_path_for(self.cache, self.base_url, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(make_zip_bytes())
        return path

    def test_links_cached_archives(self):
        self._put("mod_b.zip")
        linked, missing = obc.populate_build_dir(self.build, self.cache, self.base_url, ["mod_b.zip"])
        self.assertEqual((linked, missing), (1, 0))
        self.assertTrue(os.path.isfile(os.path.join(self.build, "zips", "mod_b.zip")))

    def test_counts_missing_without_failing(self):
        linked, missing = obc.populate_build_dir(self.build, self.cache, self.base_url, ["absent.zip"])
        self.assertEqual((linked, missing), (0, 1))

    def test_creates_zips_dir_even_when_empty(self):
        obc.populate_build_dir(self.build, self.cache, self.base_url, [])
        self.assertTrue(os.path.isdir(os.path.join(self.build, "zips")))

    def test_custom_module_archives_are_linked_too(self):
        """They are not part of a release and never enter the cache, but they
        must reach the build through the mount so no COPY has to keep them in
        an image layer."""
        self._put("mod_b.zip")
        for name in ("custom_modules.zip", "xy_custom_modules.zip"):
            with open(os.path.join(self.build, name), "wb") as handle:
                handle.write(make_zip_bytes())
        obc.populate_build_dir(self.build, self.cache, self.base_url, ["mod_b.zip"])
        listed = sorted(os.listdir(os.path.join(self.build, "zips")))
        self.assertEqual(listed, ["custom_modules.zip", "mod_b.zip", "xy_custom_modules.zip"])

    def test_custom_archives_do_not_count_as_release_archives(self):
        with open(os.path.join(self.build, "custom_modules.zip"), "wb") as handle:
            handle.write(make_zip_bytes())
        linked, missing = obc.populate_build_dir(self.build, self.cache, self.base_url, [])
        self.assertEqual((linked, missing), (0, 0))

    def test_stale_archive_from_previous_release_is_removed(self):
        os.makedirs(os.path.join(self.build, "zips"))
        stale = os.path.join(self.build, "zips", "old_release.zip")
        with open(stale, "wb") as handle:
            handle.write(b"x")
        self._put("mod_b.zip")
        obc.populate_build_dir(self.build, self.cache, self.base_url, ["mod_b.zip"])
        self.assertFalse(os.path.exists(stale))


class DockerfileMountTest(unittest.TestCase):
    """The build step must bind-mount zips/ rather than COPY it: Docker layers
    are additive, so a COPY of ~270MB stays in the image whatever a later RUN
    deletes."""

    LEGACY = """FROM registry.invalid/prepare:1.0
USER odoo

# Archives pre-fetched by odoo_build_cache.py on the host. The folder is created
# by 'odoo_build_cache.py sync' even when empty.
COPY --chown=odoo:odoo zips/ /opt/odoo/zips/

RUN cd /opt/odoo/ && \\
    python3 build_odoo.py
"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = write(os.path.join(self.tmp, "Dockerfile"), DOCKERFILE)

    def _lines(self):
        with open(self.path, encoding="utf8") as handle:
            return handle.read().splitlines()

    def test_adds_mount_to_the_run_step(self):
        self.assertTrue(obc.ensure_dockerfile_mount(self.path))
        lines = self._lines()
        run_index = next(i for i, l in enumerate(lines) if l.startswith("RUN "))
        self.assertIn(obc.MOUNT_FLAG, lines[run_index])
        self.assertTrue(lines[run_index].endswith("\\"))
        self.assertEqual(lines[run_index + 1], "    cd /opt/odoo/ && \\")

    def test_is_idempotent(self):
        obc.ensure_dockerfile_mount(self.path)
        first = open(self.path, encoding="utf8").read()
        self.assertFalse(obc.ensure_dockerfile_mount(self.path))
        self.assertEqual(open(self.path, encoding="utf8").read(), first)

    def test_original_run_body_survives(self):
        obc.ensure_dockerfile_mount(self.path)
        self.assertIn("python3 build_odoo.py", "\n".join(self._lines()))

    def test_removes_legacy_copy_and_its_comments(self):
        path = write(os.path.join(self.tmp, "Legacy"), self.LEGACY)
        self.assertTrue(obc.ensure_dockerfile_mount(path))
        content = open(path, encoding="utf8").read()
        self.assertNotIn("zips/ /opt/odoo/zips/", content)
        self.assertNotIn("Archives pre-fetched", content)
        self.assertIn(obc.MOUNT_FLAG, content)

    def test_leaves_from_line_untouched(self):
        obc.ensure_dockerfile_mount(self.path)
        self.assertTrue(self._lines()[0].startswith("FROM registry.invalid/prepare:1.0"))

    def test_reports_false_when_no_run_line(self):
        path = write(os.path.join(self.tmp, "Other"), "FROM x\n")
        self.assertFalse(obc.ensure_dockerfile_mount(path))

    # --- the Dockerfile belongs to the customer -------------------------------

    CUSTOMISED = """FROM registry.invalid/prepare:1.0
USER odoo
COPY requirements-custom.txt /opt/odoo/

# Customer note: extra packages for the interface
RUN cd /opt/odoo/ && pip install --user -r requirements-custom.txt && python3 build_odoo.py
"""

    def test_extra_command_inside_the_run_step_survives(self):
        """The customer may add to this very RUN. Only the 'RUN ' keyword is
        replaced; everything after it is carried over verbatim."""
        path = write(os.path.join(self.tmp, "Custom"), self.CUSTOMISED)
        self.assertTrue(obc.ensure_dockerfile_mount(path))
        content = open(path, encoding="utf8").read()
        self.assertIn("pip install --user -r requirements-custom.txt", content)
        self.assertIn("python3 build_odoo.py", content)
        self.assertIn(obc.MOUNT_FLAG, content)

    def test_customer_comment_above_a_legacy_copy_is_kept(self):
        path = write(os.path.join(self.tmp, "Commented"), """FROM x:1
USER odoo

# Customer note: do not remove
COPY zips/ /opt/odoo/zips/

RUN cd /opt/odoo/ && \\
    python3 build_odoo.py
""")
        self.assertTrue(obc.ensure_dockerfile_mount(path))
        content = open(path, encoding="utf8").read()
        self.assertIn("# Customer note: do not remove", content)
        self.assertNotIn("zips/ /opt/odoo/zips/", content.replace(obc.MOUNT_FLAG, ""))

    def test_a_backup_is_written(self):
        obc.ensure_dockerfile_mount(self.path)
        backups = [n for n in os.listdir(self.tmp) if n.startswith("Dockerfile.bak_")]
        self.assertEqual(len(backups), 1)
        self.assertEqual(open(os.path.join(self.tmp, backups[0]), encoding="utf8").read(),
                         DOCKERFILE)

    def test_every_other_instruction_is_preserved(self):
        path = write(os.path.join(self.tmp, "Many"), """FROM x:1
USER odoo
COPY a.py /opt/odoo/
RUN cd /opt/odoo/ && python3 build_odoo.py
RUN mkdir -p /opt/odoo/extra
VOLUME ["/opt/odoo/data"]
EXPOSE 8069
""")
        before = obc._instructions(open(path, encoding="utf8").read())
        obc.ensure_dockerfile_mount(path)
        after = obc._instructions(open(path, encoding="utf8").read())
        self.assertEqual(len(before), len(after))
        for instruction in ("COPY a.py /opt/odoo/", "RUN mkdir -p /opt/odoo/extra",
                            'VOLUME ["/opt/odoo/data"]', "EXPOSE 8069"):
            self.assertIn(instruction, after)


class DockerfileReferenceTest(unittest.TestCase):
    """update_docker_odoo.py never overwrites a build folder's Dockerfile — it
    is the customer's file. So a directive added to the repository afterwards,
    HEALTHCHECK being the case that prompted this, has to be filled in here or
    it never arrives on an existing installation."""

    REFERENCE = """FROM registry.invalid/prepare:9.9
LABEL maintainer=info@ownerp.com

USER odoo
COPY build_odoo.py /opt/odoo/
RUN cd /opt/odoo/ && \\
    python3 build_odoo.py

USER 0
WORKDIR /app
VOLUME ["/opt/odoo/var", "/opt/odoo/data"]
# Healthcheck: Verify Odoo responds on /web/health
HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=3 \\
    CMD wget -q --spider http://localhost:8069/web/health || exit 1

ENTRYPOINT ["/app/bin/boot"]
CMD ["help"]

EXPOSE 8069 8072
COPY bin /app/bin/
"""

    # An installation from before HEALTHCHECK existed, with the customer's own
    # additions: a second COPY, an extra command in the build RUN, and ADD
    # where the repository has since moved to COPY.
    LEGACY_INSTALL = """FROM registry.invalid/prepare:1.0
LABEL maintainer=info@ownerp.com

USER odoo
COPY build_odoo.py /opt/odoo/
COPY xy_custom_modules.zip /opt/odoo/
# customer: extra package for our reports
RUN cd /opt/odoo/ && python3 build_odoo.py && pip3 install --no-cache-dir openpyxl

USER 0
WORKDIR /app
VOLUME ["/opt/odoo/var", "/opt/odoo/data"]

ENTRYPOINT ["/app/bin/boot"]
CMD ["help"]

EXPOSE 8069 8072
ADD bin /app/bin/
"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.reference = write(os.path.join(self.tmp, "reference"), self.REFERENCE)
        self.path = write(os.path.join(self.tmp, "Dockerfile"), self.LEGACY_INSTALL)

    def _content(self):
        return open(self.path, encoding="utf8").read()

    def test_missing_healthcheck_is_added(self):
        self.assertTrue(obc.ensure_dockerfile_current(self.path, self.reference))
        content = self._content()
        self.assertIn("HEALTHCHECK --interval=60s", content)
        self.assertIn("wget -q --spider http://localhost:8069/web/health", content)

    def test_healthcheck_lands_before_the_entrypoint(self):
        obc.ensure_dockerfile_current(self.path, self.reference)
        lines = self._content().splitlines()
        health = next(i for i, l in enumerate(lines) if l.startswith("HEALTHCHECK"))
        entry = next(i for i, l in enumerate(lines) if l.startswith("ENTRYPOINT"))
        self.assertLess(health, entry)

    def test_the_explaining_comment_comes_along(self):
        obc.ensure_dockerfile_current(self.path, self.reference)
        self.assertIn("# Healthcheck: Verify Odoo responds on /web/health", self._content())

    def test_customer_additions_survive(self):
        obc.ensure_dockerfile_current(self.path, self.reference)
        content = self._content()
        self.assertIn("COPY xy_custom_modules.zip /opt/odoo/", content)
        self.assertIn("pip3 install --no-cache-dir openpyxl", content)
        self.assertIn("# customer: extra package for our reports", content)

    def test_base_image_is_left_alone(self):
        """check_dockerimage_odoo.py owns the FROM line; this must not race it."""
        obc.ensure_dockerfile_current(self.path, self.reference)
        self.assertTrue(self._content().startswith("FROM registry.invalid/prepare:1.0"))

    def test_a_present_directive_is_not_duplicated(self):
        obc.ensure_dockerfile_current(self.path, self.reference)
        content = self._content()
        self.assertEqual(content.count("VOLUME "), 1)
        self.assertEqual(content.count("EXPOSE "), 1)

    def test_is_idempotent(self):
        obc.ensure_dockerfile_current(self.path, self.reference)
        first = self._content()
        self.assertFalse(obc.ensure_dockerfile_current(self.path, self.reference))
        self.assertEqual(self._content(), first)

    def test_reference_against_itself_changes_nothing(self):
        path = write(os.path.join(self.tmp, "Same"), self.REFERENCE)
        obc.ensure_dockerfile_current(path, self.reference)   # only the mount
        self.assertFalse(obc.ensure_dockerfile_current(path, self.reference))

    def test_a_run_the_customer_extended_is_not_reported_missing(self):
        """Their build RUN carries an extra pip3 install. Reporting that as a
        missing instruction would teach everyone to ignore these warnings."""
        lines = self.LEGACY_INSTALL.splitlines()
        _added, missing = obc._apply_reference(lines, self.REFERENCE.splitlines())
        self.assertFalse([m for m in missing if "build_odoo.py" in m])

    def test_an_instruction_that_really_differs_is_reported(self):
        """ADD was replaced by COPY for bin/ in July 2026 (tar auto-extraction).
        That cannot be patched in safely, so it has to be said out loud."""
        lines = self.LEGACY_INSTALL.splitlines()
        _added, missing = obc._apply_reference(lines, self.REFERENCE.splitlines())
        self.assertIn("COPY bin /app/bin/", missing)

    def test_nothing_is_reported_for_a_matching_file(self):
        lines = self.REFERENCE.splitlines()
        _added, missing = obc._apply_reference(lines, self.REFERENCE.splitlines())
        self.assertEqual(missing, [])

    def test_a_file_that_only_lacks_the_healthcheck_is_still_patched(self):
        """The common case on a server updated last week: the mount is already
        in place, so the mount patch has nothing to do — the directive still
        has to be inserted."""
        obc.ensure_dockerfile_current(self.path)              # mount only
        self.assertIn(obc.MOUNT_FLAG, self._content())
        self.assertNotIn("HEALTHCHECK", self._content())
        self.assertTrue(obc.ensure_dockerfile_current(self.path, self.reference))
        self.assertIn("HEALTHCHECK --interval=60s", self._content())

    def test_no_reference_leaves_the_old_behaviour(self):
        self.assertTrue(obc.ensure_dockerfile_current(self.path))
        self.assertNotIn("HEALTHCHECK", self._content())
        self.assertIn(obc.MOUNT_FLAG, self._content())

    def test_an_unreadable_reference_is_not_fatal(self):
        missing_ref = os.path.join(self.tmp, "does-not-exist")
        self.assertTrue(obc.ensure_dockerfile_current(self.path, missing_ref))
        self.assertIn(obc.MOUNT_FLAG, self._content())

    def test_the_repository_dockerfiles_are_already_complete(self):
        """Guards the reference itself: if a repository Dockerfile were missing
        one of these directives, every server would silently inherit the gap."""
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "Dockerfiles")
        for version in ("16", "18", "19"):
            path = os.path.join(root, f"v{version}-odoo", "Dockerfile")
            if not os.path.isfile(path):
                continue
            content = open(path, encoding="utf8").read()
            for keyword in obc.ADDITIVE_KEYWORDS:
                self.assertIn(keyword, content, f"v{version} lacks {keyword}")


class DockerfileGuardTest(unittest.TestCase):
    """_dockerfile_regression is the last line of defence: it compares the
    instructions before and after and refuses anything but the intended change."""

    STOCK = "FROM x:1\nRUN cd /opt/odoo/ && python3 build_odoo.py\n"

    def test_accepts_the_intended_change(self):
        patched = f"FROM x:1\nRUN {obc.MOUNT_FLAG} \\\n    cd /opt/odoo/ && python3 build_odoo.py\n"
        self.assertIsNone(obc._dockerfile_regression(self.STOCK, patched))

    def test_refuses_a_dropped_command(self):
        patched = f"FROM x:1\nRUN {obc.MOUNT_FLAG} \\\n    cd /opt/odoo/ && \\\n"
        self.assertIn("would drop", obc._dockerfile_regression(self.STOCK, patched))

    def test_refuses_a_dropped_unrelated_instruction(self):
        stock = self.STOCK + "EXPOSE 8069\n"
        patched = f"FROM x:1\nRUN {obc.MOUNT_FLAG} \\\n    cd /opt/odoo/ && python3 build_odoo.py\n"
        self.assertIn("would drop", obc._dockerfile_regression(stock, patched))

    def test_refuses_an_unexpected_addition(self):
        patched = (f"FROM x:1\nRUN {obc.MOUNT_FLAG} \\\n"
                   "    cd /opt/odoo/ && python3 build_odoo.py\nRUN rm -rf /\n")
        self.assertIn("would add", obc._dockerfile_regression(self.STOCK, patched))

    def test_allows_the_legacy_copy_to_disappear(self):
        stock = "FROM x:1\nCOPY zips/ /opt/odoo/zips/\nRUN cd /opt/odoo/ && python3 build_odoo.py\n"
        patched = f"FROM x:1\nRUN {obc.MOUNT_FLAG} \\\n    cd /opt/odoo/ && python3 build_odoo.py\n"
        self.assertIsNone(obc._dockerfile_regression(stock, patched))


class GcTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cache = os.path.join(self.tmp, "cache")
        os.makedirs(os.path.join(self.cache, "example.invalid", "19.0"))

    def _archive(self, name, age_days):
        path = os.path.join(self.cache, "example.invalid", "19.0", name)
        with open(path, "wb") as handle:
            handle.write(b"0123456789")
        stamp = time.time() - age_days * 86400
        os.utime(path, (stamp, stamp))
        return path

    def test_removes_only_files_past_the_threshold(self):
        old = self._archive("old.zip", 40)
        fresh = self._archive("fresh.zip", 5)
        removed, freed = obc.gc_cache(self.cache, 30)
        self.assertEqual(removed, 1)
        self.assertEqual(freed, 10)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(fresh))

    def test_removes_emptied_directories(self):
        self._archive("old.zip", 40)
        obc.gc_cache(self.cache, 30)
        self.assertFalse(os.path.isdir(os.path.join(self.cache, "example.invalid", "19.0")))

    def test_missing_cache_is_not_an_error(self):
        self.assertEqual(obc.gc_cache(os.path.join(self.tmp, "absent"), 30), (0, 0))


class ReleaseArchiveGcTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_keeps_the_newest_n(self):
        for index in range(8):
            path = write(os.path.join(self.tmp, f"release.file-2026-08-0{index}_10-00-00"), "x")
            os.utime(path, (1000 + index, 1000 + index))
        write(os.path.join(self.tmp, "release.file"), "current")
        removed = obc.gc_release_archives(self.tmp, keep=5)
        self.assertEqual(removed, 3)
        remaining = [n for n in os.listdir(self.tmp) if n.startswith("release.file-")]
        self.assertEqual(len(remaining), 5)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "release.file")))

    def test_nothing_to_do(self):
        write(os.path.join(self.tmp, "release.file"), "current")
        self.assertEqual(obc.gc_release_archives(self.tmp, keep=5), 0)


class CliTest(HttpFixture):
    def test_sync_fills_cache_and_build_dir(self):
        self.server.files["/19.0/kernel-a.zip"] = make_zip_bytes()
        self.server.files["/19.0/mod_b.zip"] = make_zip_bytes()
        build = os.path.join(self.tmp, "build")
        os.makedirs(build)
        write(os.path.join(build, "release.file"), "\n".join([
            self.base_url, "registry.invalid/prepare:1.0", "kernel-a.zip", "mod_b.zip",
        ]))
        write(os.path.join(build, "Dockerfile"), DOCKERFILE)
        os.environ["ODOO_BUILD_CACHE"] = self.cache
        try:
            self.assertEqual(obc.main(["sync", build]), 0)
        finally:
            del os.environ["ODOO_BUILD_CACHE"]
        self.assertTrue(os.path.isfile(os.path.join(build, "zips", "mod_b.zip")))
        self.assertIn(obc.MOUNT_FLAG, open(os.path.join(build, "Dockerfile"), encoding="utf8").read())

    def test_sync_returns_zero_when_server_is_gone(self):
        build = os.path.join(self.tmp, "build")
        os.makedirs(build)
        write(os.path.join(build, "release.file"), "\n".join([
            "http://127.0.0.1:1/19.0/", "registry.invalid/prepare:1.0", "mod_b.zip",
        ]))
        os.environ["ODOO_BUILD_CACHE"] = self.cache
        os.environ["BUILD_ODOO_RETRIES"] = "1"
        try:
            self.assertEqual(obc.main(["sync", build]), 0)
        finally:
            del os.environ["ODOO_BUILD_CACHE"]
            del os.environ["BUILD_ODOO_RETRIES"]

    def test_sync_without_release_file_returns_zero(self):
        build = os.path.join(self.tmp, "build")
        os.makedirs(build)
        self.assertEqual(obc.main(["sync", build]), 0)


if __name__ == "__main__":
    unittest.main()
