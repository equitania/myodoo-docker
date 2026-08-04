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

    def test_stale_archive_from_previous_release_is_removed(self):
        os.makedirs(os.path.join(self.build, "zips"))
        stale = os.path.join(self.build, "zips", "old_release.zip")
        with open(stale, "wb") as handle:
            handle.write(b"x")
        self._put("mod_b.zip")
        obc.populate_build_dir(self.build, self.cache, self.base_url, ["mod_b.zip"])
        self.assertFalse(os.path.exists(stale))


class DockerfilePatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = write(os.path.join(self.tmp, "Dockerfile"), DOCKERFILE)

    def test_inserts_copy_line_before_run(self):
        self.assertTrue(obc.ensure_dockerfile_copy_line(self.path))
        with open(self.path, encoding="utf8") as handle:
            lines = handle.read().splitlines()
        copy_index = lines.index(obc.COPY_LINE)
        run_index = next(i for i, line in enumerate(lines) if line.startswith("RUN cd /opt/odoo/"))
        self.assertLess(copy_index, run_index)

    def test_is_idempotent(self):
        obc.ensure_dockerfile_copy_line(self.path)
        first = open(self.path, encoding="utf8").read()
        self.assertFalse(obc.ensure_dockerfile_copy_line(self.path))
        self.assertEqual(open(self.path, encoding="utf8").read(), first)

    def test_leaves_from_line_untouched(self):
        obc.ensure_dockerfile_copy_line(self.path)
        with open(self.path, encoding="utf8") as handle:
            self.assertTrue(handle.readline().startswith("FROM registry.invalid/prepare:1.0"))

    def test_reports_false_when_no_run_line(self):
        path = write(os.path.join(self.tmp, "Other"), "FROM x\n")
        self.assertFalse(obc.ensure_dockerfile_copy_line(path))


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
        self.assertIn(obc.COPY_LINE, open(os.path.join(build, "Dockerfile"), encoding="utf8").read())

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
