# Odoo Build Cache — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Image builds download only the release archives that actually changed, sharing one host-side cache across every Odoo instance and version on the server.

**Architecture:** A new standalone CLI (`scripts/odoo_build_cache.py`) runs on the host before `docker build`. It parses the build folder's `release.file`, downloads missing archives into `/opt/odoo-build-cache` (partitioned by release URL), and hardlinks them into `<build-dir>/zips/`. `build_odoo.py` extracts from `zips/` when present and downloads whatever is missing, so an absent or broken cache degrades to today's behaviour.

**Tech Stack:** Python 3 standard library only (`urllib.request`, `ssl`, `zipfile`, `csv`, `shutil`, `unittest`). No new dependencies — these scripts run on customer servers with system Python.

**Spec:** `docs/specs/2026-08-04-odoo-build-cache-design.md`

## Global Constraints

- **Cache root:** `/opt/odoo-build-cache` (override via `ODOO_BUILD_CACHE` for tests).
- **GC threshold:** 30 days since last use, tracked as the file's `mtime`.
- **Release URL structure must not be documented.** Tests use a local HTTP server and synthetic names. Never write a real release host or archive name into code comments, docs, commit messages, or test fixtures.
- **No new runtime dependency.** Standard library only. `urllib3` is deliberately not used in the new script.
- **The cache must never block a build.** Every failure path returns control to `build_odoo.py`, which downloads what is missing. `odoo_build_cache.py sync` exits 0 even when it achieved nothing.
- **Version headers:** every modified script gets its version incremented and the date set to the day of the change, format `DD.MM.YYYY` (repo convention).
- **The three `build_odoo.py` are byte-identical** (`4b98ac28f27eb2b70a0afd76401f88cd`) and must stay that way. Same for `.dockerignore`.
- **Commit prefixes:** `[ADD]` new features, `[CHG]` modifications, `[FIX]` bug fixes.
- **Comments and code in English**, per repo convention.

## File Structure

| File | Responsibility |
|------|----------------|
| `scripts/odoo_build_cache.py` (new) | The whole cache: parse, fetch, populate, patch, gc, stats. One file — it is one concern and stays under ~450 lines. |
| `tests/test_odoo_build_cache.py` (new) | `unittest` suite with a local HTTP server fixture. First tests in this repo. |
| `Dockerfiles/v{16,18,19}-odoo/build_odoo.py` | Gains local-zip support. Identical in all three. |
| `Dockerfiles/v{16,18,19}-odoo/Dockerfile` | Gains `COPY zips/ /opt/odoo/zips/`. |
| `Dockerfiles/v{16,18,19}-odoo/.dockerignore` (new) | Keeps filestore copies and release archives out of the build context. |
| `scripts/update_docker_odoo.py` | Calls `sync` before the build; moves the filestore backup under `filestore-backup/`. |
| `getScripts.py` | Delivers `odoo_build_cache.py` to `/root`. |
| `scripts/myodoo-maintenance.cron` | Weekly `gc`. |

---

### Task 1: Release file parsing

**Files:**
- Create: `scripts/odoo_build_cache.py`
- Test: `tests/test_odoo_build_cache.py`

**Interfaces:**
- Produces: `parse_release_file(path) -> tuple[str, list[str]]` returning `(base_url, archive_names)`. Archive names are in file order, kernel first. Raises `ValueError` on a missing/empty URL. Also `SAFE_NAME = re.compile(r'^[A-Za-z0-9._/-]+$')`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_odoo_build_cache.py
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import odoo_build_cache as obc


def write(path, text):
    with open(path, "w", encoding="utf8") as handle:
        handle.write(text)
    return path


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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_odoo_build_cache -v` from the repo root.
Expected: FAIL — `ModuleNotFoundError: No module named 'odoo_build_cache'`.

- [ ] **Step 3: Write minimal implementation**

Create `scripts/odoo_build_cache.py` with the repo's standard header block (copy the header style from `scripts/server-readiness.py`: title, description, `# Version: 1.0.0`, `# Date: <today DD.MM.YYYY>`, author Equitania Software GmbH), then:

```python
import csv
import re

SAFE_NAME = re.compile(r'^[A-Za-z0-9._/-]+$')


def parse_release_file(path):
    """Return (base_url, archive_names) from a release.file.

    Layout: line 1 is the base URL, line 2 the Docker image (ignored here),
    line 3 the kernel archive, everything after that a module archive.
    Names failing SAFE_NAME are dropped — the CSV is downloaded input, and a
    manipulated entry must not be able to escape the cache directory.
    """
    base_url = None
    names = []
    with open(path, encoding="utf8") as handle:
        for index, row in enumerate(csv.reader(handle, delimiter=","), start=1):
            if not row:
                continue
            column = row[0].replace(" ", "")
            if index == 1:
                base_url = column
            elif index == 2:
                continue
            elif column:
                if SAFE_NAME.match(column):
                    names.append(column)
                else:
                    print(f"Ignoring unsafe entry in release file: '{column}'")
    if not base_url or base_url == "False":
        raise ValueError(f"{path}: no base URL in line 1")
    return base_url, names
```

Note: blank rows are skipped without consuming an index, so a blank line between the image and the kernel does not shift the kernel into the "ignored" slot. Verify this against the second test.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_odoo_build_cache -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/odoo_build_cache.py tests/test_odoo_build_cache.py
git commit -m "[ADD] odoo_build_cache.py: release file parsing"
```

---

### Task 2: Cache paths

**Files:**
- Modify: `scripts/odoo_build_cache.py`
- Test: `tests/test_odoo_build_cache.py`

**Interfaces:**
- Consumes: `SAFE_NAME` from Task 1.
- Produces: `CACHE_ROOT_DEFAULT = "/opt/odoo-build-cache"`, `cache_root() -> str` (honours `ODOO_BUILD_CACHE`), `cache_path_for(root, base_url, name) -> str`.

- [ ] **Step 1: Write the failing test**

```python
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

    def test_root_env_override(self):
        os.environ["ODOO_BUILD_CACHE"] = "/tmp/xyz"
        try:
            self.assertEqual(obc.cache_root(), "/tmp/xyz")
        finally:
            del os.environ["ODOO_BUILD_CACHE"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_odoo_build_cache.CachePathTest -v`
Expected: FAIL — `module 'odoo_build_cache' has no attribute 'cache_path_for'`.

- [ ] **Step 3: Write minimal implementation**

```python
import os
from urllib.parse import urlsplit

CACHE_ROOT_DEFAULT = "/opt/odoo-build-cache"


def cache_root():
    """Cache location. The env override exists so tests never touch /opt."""
    return os.environ.get("ODOO_BUILD_CACHE") or CACHE_ROOT_DEFAULT


def cache_path_for(root, base_url, name):
    """Absolute path of one archive inside the cache.

    Partitioned by host and URL path, so two Odoo versions can ship an archive
    of the same name without overwriting each other, while two instances on the
    same release share every file.
    """
    if not SAFE_NAME.match(name) or ".." in name.split("/"):
        raise ValueError(f"unsafe archive name: {name!r}")
    split = urlsplit(base_url)
    parts = [part for part in split.path.split("/") if part]
    return os.path.join(root, split.netloc, *parts, name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_odoo_build_cache -v`
Expected: 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/odoo_build_cache.py tests/test_odoo_build_cache.py
git commit -m "[ADD] odoo_build_cache.py: cache path mapping"
```

---

### Task 3: Downloading into the cache

**Files:**
- Modify: `scripts/odoo_build_cache.py`
- Test: `tests/test_odoo_build_cache.py`

**Interfaces:**
- Consumes: `cache_path_for` from Task 2.
- Produces: `fetch_into_cache(base_url, name, root) -> bool` (True when the archive is in the cache afterwards, whether it was already there or just fetched), and the retry knobs `MAX_ATTEMPTS`, `BACKOFF_BASE`, `FAILURE_LIMIT` read from `BUILD_ODOO_RETRIES`, `BUILD_ODOO_RETRY_BACKOFF`, `BUILD_ODOO_FAILURE_LIMIT`.

- [ ] **Step 1: Write the failing test**

```python
import http.server
import io
import threading
import zipfile


def make_zip_bytes():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("payload.txt", "content")
    return buffer.getvalue()


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_odoo_build_cache.FetchTest -v`
Expected: FAIL — `has no attribute 'fetch_into_cache'`.

- [ ] **Step 3: Write minimal implementation**

```python
import shutil
import ssl
import sys
import time
import urllib.error
import urllib.request
import zipfile

MAX_ATTEMPTS = max(1, int(os.environ.get("BUILD_ODOO_RETRIES", "5")))
BACKOFF_BASE = max(0.5, float(os.environ.get("BUILD_ODOO_RETRY_BACKOFF", "3")))
BACKOFF_CAP = 60.0
FAILURE_LIMIT = max(1, int(os.environ.get("BUILD_ODOO_FAILURE_LIMIT", "3")))
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
TIMEOUT = 300


def _retry_delay(attempt):
    return min(BACKOFF_BASE * (2 ** (attempt - 1)), BACKOFF_CAP)


def _download(url, destination):
    """Fetch url to destination. Returns (ok, error, retryable)."""
    try:
        # urllib.request honours http_proxy/https_proxy from the environment on
        # its own — unlike urllib3, which needs an explicit ProxyManager.
        context = ssl.create_default_context()
        with urllib.request.urlopen(url, timeout=TIMEOUT, context=context) as response:
            with open(destination, "wb") as handle:
                shutil.copyfileobj(response, handle)
        return True, None, False
    except urllib.error.HTTPError as error:
        return False, f"HTTP status {error.code}", error.code in RETRYABLE_STATUS
    except Exception as error:                       # URLError, socket, ssl
        return False, f"{type(error).__name__}: {error}", True


def fetch_into_cache(base_url, name, root):
    """Ensure `name` is present in the cache. True when it is, afterwards.

    A hit costs no network round trip at all: the archive names carry their
    version, so a name that is present is by definition the right content.
    """
    target = cache_path_for(root, base_url, name)
    if os.path.isfile(target):
        os.utime(target, None)                       # mtime == last used, drives gc
        return True

    os.makedirs(os.path.dirname(target), exist_ok=True)
    url = base_url.rstrip("/") + "/" + name
    temporary = target + ".tmp"
    last_error = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        ok, last_error, retryable = _download(url, temporary)
        if ok:
            # A release server answering an error with a 200 HTML page would
            # otherwise poison the cache permanently — unlike today, where the
            # bad file dies with the build container.
            if not zipfile.is_zipfile(temporary):
                os.remove(temporary)
                print(f"Refused {name}: not a valid zip archive")
                return False
            os.replace(temporary, target)            # atomic; no half file on abort
            print(f"Cached: {name}")
            return True
        if not retryable:
            break
        if attempt < MAX_ATTEMPTS:
            delay = _retry_delay(attempt)
            print(f"Attempt {attempt}/{MAX_ATTEMPTS} for {name} failed "
                  f"({last_error}) — retrying in {delay:.0f}s...")
            sys.stdout.flush()
            time.sleep(delay)

    if os.path.exists(temporary):
        os.remove(temporary)
    print(f"Failed to cache {name}: {last_error}")
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_odoo_build_cache -v`
Expected: 15 tests PASS. The 404 test must show exactly one request — if it shows five, the `retryable` branch is wrong.

- [ ] **Step 5: Commit**

```bash
git add scripts/odoo_build_cache.py tests/test_odoo_build_cache.py
git commit -m "[ADD] odoo_build_cache.py: atomic, verified downloads into the cache"
```

---

### Task 4: Populating the build folder

**Files:**
- Modify: `scripts/odoo_build_cache.py`
- Test: `tests/test_odoo_build_cache.py`

**Interfaces:**
- Consumes: `cache_path_for` (Task 2).
- Produces: `populate_build_dir(build_dir, root, base_url, names) -> tuple[int, int]` returning `(linked, missing)`. Creates `<build_dir>/zips/` unconditionally, empties it first.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_odoo_build_cache.PopulateTest -v`
Expected: FAIL — `has no attribute 'populate_build_dir'`.

- [ ] **Step 3: Write minimal implementation**

```python
ZIP_DIR = "zips"


def populate_build_dir(build_dir, root, base_url, names):
    """Link every cached archive into <build_dir>/zips/. Returns (linked, missing).

    Emptied first so a leftover from a previous release cannot travel into the
    image. Hardlinks cost no space; a cache on a different filesystem falls back
    to a copy.
    """
    target_dir = os.path.join(build_dir, ZIP_DIR)
    if os.path.isdir(target_dir):
        shutil.rmtree(target_dir)
    os.makedirs(target_dir, exist_ok=True)

    linked = missing = 0
    for name in names:
        source = cache_path_for(root, base_url, name)
        if not os.path.isfile(source):
            missing += 1
            continue
        destination = os.path.join(target_dir, os.path.basename(name))
        try:
            os.link(source, destination)
        except OSError:                              # EXDEV: different filesystem
            shutil.copy2(source, destination)
        linked += 1
    return linked, missing
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_odoo_build_cache -v`
Expected: 19 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/odoo_build_cache.py tests/test_odoo_build_cache.py
git commit -m "[ADD] odoo_build_cache.py: populate the build folder from the cache"
```

---

### Task 5: Idempotent Dockerfile patch

**Files:**
- Modify: `scripts/odoo_build_cache.py`
- Test: `tests/test_odoo_build_cache.py`

**Interfaces:**
- Produces: `ensure_dockerfile_copy_line(path) -> bool` (True when the file was changed). Inserts `COPY zips/ /opt/odoo/zips/` directly before the first line starting with `RUN cd /opt/odoo/`.

- [ ] **Step 1: Write the failing test**

```python
DOCKERFILE = """FROM registry.invalid/prepare:1.0
LABEL maintainer=info@example.invalid
# comment
# Date 01.01.2026

COPY build_odoo.py /opt/odoo/
COPY release.file /opt/odoo/

RUN cd /opt/odoo/ && \\
    python3 build_odoo.py
"""


class DockerfilePatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = write(os.path.join(self.tmp, "Dockerfile"), DOCKERFILE)

    def test_inserts_copy_line_before_run(self):
        self.assertTrue(obc.ensure_dockerfile_copy_line(self.path))
        with open(self.path, encoding="utf8") as handle:
            lines = handle.read().splitlines()
        copy_index = lines.index("COPY zips/ /opt/odoo/zips/")
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_odoo_build_cache.DockerfilePatchTest -v`
Expected: FAIL — `has no attribute 'ensure_dockerfile_copy_line'`.

- [ ] **Step 3: Write minimal implementation**

```python
COPY_LINE = "COPY zips/ /opt/odoo/zips/"


def ensure_dockerfile_copy_line(path):
    """Insert the COPY for the zip folder if it is not there yet.

    sync_build_scripts() in update_docker_odoo.py distributes build_odoo.py but
    not the Dockerfile, so on existing servers this line would never arrive and
    the cache would stay silently ineffective. check_dockerimage_odoo.py already
    patches this file (FROM line and date), so patching it is established here.
    """
    if not os.path.isfile(path):
        return False
    with open(path, encoding="utf8") as handle:
        lines = handle.read().splitlines()
    if any(line.strip() == COPY_LINE for line in lines):
        return False
    for index, line in enumerate(lines):
        if line.startswith("RUN cd /opt/odoo/"):
            lines.insert(index, COPY_LINE)
            lines.insert(index + 1, "")
            with open(path, "w", encoding="utf8") as handle:
                handle.write("\n".join(lines) + "\n")
            print(f"Patched {path}: added '{COPY_LINE}'")
            return True
    print(f"Could not patch {path}: no 'RUN cd /opt/odoo/' line found")
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_odoo_build_cache -v`
Expected: 23 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/odoo_build_cache.py tests/test_odoo_build_cache.py
git commit -m "[ADD] odoo_build_cache.py: idempotent Dockerfile patch"
```

---

### Task 6: Garbage collection

**Files:**
- Modify: `scripts/odoo_build_cache.py`
- Test: `tests/test_odoo_build_cache.py`

**Interfaces:**
- Produces: `gc_cache(root, days) -> tuple[int, int]` returning `(removed, freed_bytes)`; `gc_release_archives(build_dir, keep) -> int` returning the number removed.

- [ ] **Step 1: Write the failing test**

```python
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
        remaining = sorted(n for n in os.listdir(self.tmp) if n.startswith("release.file-"))
        self.assertEqual(len(remaining), 5)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "release.file")))

    def test_nothing_to_do(self):
        write(os.path.join(self.tmp, "release.file"), "current")
        self.assertEqual(obc.gc_release_archives(self.tmp, keep=5), 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_odoo_build_cache.GcTest -v`
Expected: FAIL — `has no attribute 'gc_cache'`.

- [ ] **Step 3: Write minimal implementation**

```python
GC_DAYS_DEFAULT = 30
RELEASE_ARCHIVES_KEPT = 5


def gc_cache(root, days):
    """Drop archives unused for `days`. Returns (removed, freed_bytes).

    Deliberately not "absent from the current release.file": another instance on
    this server may still run an older release and need exactly that archive.
    """
    if not os.path.isdir(root):
        return 0, 0
    cutoff = time.time() - days * 86400
    removed = freed = 0
    for current, _dirs, files in os.walk(root, topdown=False):
        for name in files:
            path = os.path.join(current, name)
            try:
                stat = os.stat(path)
                if stat.st_mtime < cutoff:
                    os.remove(path)
                    removed += 1
                    freed += stat.st_size
            except OSError:
                continue
        try:
            if current != root and not os.listdir(current):
                os.rmdir(current)
        except OSError:
            pass
    return removed, freed


def gc_release_archives(build_dir, keep=RELEASE_ARCHIVES_KEPT):
    """Remove all but the newest `keep` release.file-<timestamp> archives.

    check_dockerimage_odoo.py renames the previous release.file on every run and
    never deletes one, so these accumulate for the life of the server.
    """
    prefix = "release.file-"
    try:
        entries = [name for name in os.listdir(build_dir) if name.startswith(prefix)]
    except OSError:
        return 0
    paths = [os.path.join(build_dir, name) for name in entries]
    paths = [path for path in paths if os.path.isfile(path)]
    paths.sort(key=os.path.getmtime, reverse=True)
    removed = 0
    for path in paths[keep:]:
        try:
            os.remove(path)
            removed += 1
        except OSError:
            continue
    return removed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_odoo_build_cache -v`
Expected: 28 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/odoo_build_cache.py tests/test_odoo_build_cache.py
git commit -m "[ADD] odoo_build_cache.py: cache and release archive garbage collection"
```

---

### Task 7: CLI

**Files:**
- Modify: `scripts/odoo_build_cache.py`
- Test: `tests/test_odoo_build_cache.py`

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces: `main(argv=None) -> int` with subcommands `sync <build-dir>`, `gc [--days N] [build-dir ...]`, `stats`. **`sync` returns 0 even on total failure** — the build must never be blocked by the cache.

- [ ] **Step 1: Write the failing test**

```python
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
```

Note: `BUILD_ODOO_RETRIES` is read at import time, so the second test only shortens the retry loop if the module re-reads it. Make `MAX_ATTEMPTS` a module-level function call `_attempts()` instead of a constant, or accept the longer runtime. Prefer `_attempts()` — the test must stay fast.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_odoo_build_cache.CliTest -v`
Expected: FAIL — `has no attribute 'main'`.

- [ ] **Step 3: Write minimal implementation**

Replace the `MAX_ATTEMPTS` constant with `def _attempts(): return max(1, int(os.environ.get("BUILD_ODOO_RETRIES", "5")))` and use it in `fetch_into_cache`. Then:

```python
import argparse


def cmd_sync(build_dir):
    root = cache_root()
    release = os.path.join(build_dir, "release.file")
    if not os.path.isfile(release):
        print(f"No release.file in {build_dir} — nothing to cache.")
        return 0
    try:
        base_url, names = parse_release_file(release)
    except (ValueError, OSError) as error:
        print(f"Cannot read {release}: {error}")
        return 0

    fetched = failed = consecutive = 0
    for name in names:
        if fetch_into_cache(base_url, name, root):
            fetched += 1
            consecutive = 0
        else:
            failed += 1
            consecutive += 1
            if consecutive >= FAILURE_LIMIT:
                print(f"Stopping cache sync: {consecutive} downloads failed back to "
                      f"back. The build will fetch the rest itself.")
                break

    linked, missing = populate_build_dir(build_dir, root, base_url, names)
    ensure_dockerfile_copy_line(os.path.join(build_dir, "Dockerfile"))
    print(f"Cache: {linked}/{len(names)} archives ready, {missing} left for the build "
          f"({failed} download(s) failed).")
    return 0                                        # never block the build


def cmd_gc(days, build_dirs):
    removed, freed = gc_cache(cache_root(), days)
    print(f"Cache: removed {removed} archive(s), freed {freed / 1024 ** 2:.1f} MB "
          f"(unused for more than {days} days).")
    for build_dir in build_dirs:
        count = gc_release_archives(build_dir)
        if count:
            print(f"{build_dir}: removed {count} old release.file archive(s).")
    return 0


def cmd_stats():
    root = cache_root()
    if not os.path.isdir(root):
        print(f"No cache at {root}.")
        return 0
    per_partition = {}
    for current, _dirs, files in os.walk(root):
        for name in files:
            try:
                size = os.path.getsize(os.path.join(current, name))
            except OSError:
                continue
            key = os.path.relpath(current, root)
            count, total = per_partition.get(key, (0, 0))
            per_partition[key] = (count + 1, total + size)
    grand_count = sum(count for count, _ in per_partition.values())
    grand_size = sum(size for _, size in per_partition.values())
    for key in sorted(per_partition):
        count, size = per_partition[key]
        print(f"  {key}: {count} archive(s), {size / 1024 ** 2:.1f} MB")
    print(f"Total: {grand_count} archive(s), {grand_size / 1024 ** 2:.1f} MB in {root}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Zip cache for Odoo image builds")
    sub = parser.add_subparsers(dest="command", required=True)
    sync = sub.add_parser("sync", help="fill the cache and the build folder")
    sync.add_argument("build_dir")
    collect = sub.add_parser("gc", help="remove archives unused for a while")
    collect.add_argument("--days", type=int, default=GC_DAYS_DEFAULT)
    collect.add_argument("build_dir", nargs="*")
    sub.add_parser("stats", help="show cache size per release")

    args = parser.parse_args(argv)
    if args.command == "sync":
        return cmd_sync(args.build_dir)
    if args.command == "gc":
        return cmd_gc(args.days, args.build_dir)
    return cmd_stats()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_odoo_build_cache -v`
Expected: 31 tests PASS, whole suite under 10 seconds.

- [ ] **Step 5: Commit**

```bash
git add scripts/odoo_build_cache.py tests/test_odoo_build_cache.py
git commit -m "[ADD] odoo_build_cache.py: sync/gc/stats CLI"
```

---

### Task 8: build_odoo.py uses local archives

**Files:**
- Modify: `Dockerfiles/v19-odoo/build_odoo.py:212-222` (`download_and_extract`), `:302-323` (module loop), `:283-300` (kernel), `:369-377` (cleanup)
- Copy to: `Dockerfiles/v18-odoo/build_odoo.py`, `Dockerfiles/v16-odoo/build_odoo.py`

**Interfaces:**
- Produces: `_local_zip(filename) -> str | None` and a changed `download_and_extract(url, filename, destination) -> bool` that prefers a local archive.

- [ ] **Step 1: Add the counters and the lookup**

Edit `Dockerfiles/v19-odoo/build_odoo.py`. Below `_release_file = 'release.file'` add:

```python
# Archives pre-fetched on the host by odoo_build_cache.py. Absent on servers
# without the cache, in which case every archive is downloaded as before.
_local_zip_dir = 'zips'
```

Replace `download_and_extract` with:

```python
def _local_zip(filename):
    """Path of a host-provided archive, or None when it has to be downloaded."""
    candidate = os.path.join(_local_zip_dir, os.path.basename(filename))
    return candidate if os.path.isfile(candidate) else None


def download_and_extract(url, filename, destination):
    """Extract an archive, downloading it first unless the host provided it."""
    local = _local_zip(filename)
    if local:
        if extract_zip(local, destination):
            return True, True
        print(f"Failed to extract cached {filename}")
        return False, True
    if download_file(url, filename):
        if extract_zip(filename, destination):
            return True, False
        print(f"Failed to extract {filename}")
        return False, False
    print(f"Failed to download {filename}")
    return False, False
```

- [ ] **Step 2: Update both call sites**

The function now returns a tuple. Kernel (was line ~295):

```python
                ok, from_cache = download_and_extract(_zip_url, _column, 'odoo-server')
                if ok:
                    downloaded_files += 1
                    if from_cache:
                        cached_files += 1
                    print(f"kernel: {_column} loaded and installed.."
                          f"{' (cached)' if from_cache else ''}")
                else:
                    print(f'Failed to process kernel: {_column}')
                    sys.exit(1)
```

Modules (was line ~310):

```python
                ok, from_cache = download_and_extract(_zip_url, _column, 'odoo-server/addons')
                if ok:
                    downloaded_files += 1
                    if from_cache:
                        cached_files += 1
                    consecutive_failures = 0
                    print(f"file: {_column} loaded and installed.."
                          f"{' (cached)' if from_cache else ''}")
                else:
```

Add `cached_files = 0` next to `downloaded_files = 0` (line ~241), and extend the closing summary (line ~331):

```python
    print(f"\nAll entries from release file processed! Files downloaded: "
          f"{downloaded_files}/{total_zip_files} "
          f"({cached_files} from cache, {downloaded_files - cached_files} fetched)")
```

Extend the cleanup list (line ~371) so the archives never land in the image:

```python
files_to_remove = ['*.zip', 'build_myodoo.py', 'release.file']
```

becomes

```python
files_to_remove = ['*.zip', 'build_myodoo.py', 'release.file']
run_command(f"rm -rf {_local_zip_dir}")
```

placed directly after the existing loop over `files_to_remove`.

- [ ] **Step 3: Bump the version header**

`# Version 2.7.0` and `# Date <today DD.MM.YYYY>` at the top of the file.

- [ ] **Step 4: Verify the fallback path still works**

```bash
cd /tmp && rm -rf cachetest && mkdir -p cachetest/odoo-server/addons && cd cachetest
cp ~/gitbase/myodoo-docker/Dockerfiles/v19-odoo/build_odoo.py .
python3 -c "
import ast, sys
tree = ast.parse(open('build_odoo.py').read())
names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
assert '_local_zip' in names, 'missing _local_zip'
print('structure ok')
"
```

Expected: `structure ok`. A full run needs a release server and is covered by the live build in Task 12.

- [ ] **Step 5: Mirror to v18 and v16, then commit**

```bash
cd ~/gitbase/myodoo-docker/Dockerfiles
cp v19-odoo/build_odoo.py v18-odoo/build_odoo.py
cp v19-odoo/build_odoo.py v16-odoo/build_odoo.py
md5sum v1*-odoo/build_odoo.py   # must show three identical sums
git add v16-odoo/build_odoo.py v18-odoo/build_odoo.py v19-odoo/build_odoo.py
git commit -m "[CHG] build_odoo.py v2.7.0: extract host-cached archives instead of downloading"
```

---

### Task 9: Dockerfile and .dockerignore

**Files:**
- Modify: `Dockerfiles/v{16,18,19}-odoo/Dockerfile`
- Create: `Dockerfiles/v{16,18,19}-odoo/.dockerignore`

- [ ] **Step 1: Add the COPY line to all three Dockerfiles**

Directly above `RUN cd /opt/odoo/ && \`:

```dockerfile
# Archives pre-fetched by odoo_build_cache.py on the host. The folder is created
# by 'odoo_build_cache.py sync' even when empty, because COPY fails on a missing
# source. build_odoo.py downloads whatever is not in here.
COPY zips/ /opt/odoo/zips/
```

- [ ] **Step 2: Create the .dockerignore (identical in all three)**

```
# The build context is the instance's build folder. Without this file the two
# filestore copies update_docker_odoo.py keeps there (the docker cp backup and
# its .bak rotation) are shipped to the daemon on every build.
filestore-backup/
release.file-*
__pycache__/
*.log
*.tmp
```

- [ ] **Step 3: Verify the context shrinks**

```bash
cd ~/gitbase/myodoo-docker/Dockerfiles/v19-odoo
mkdir -p /tmp/ctxtest && cp Dockerfile .dockerignore /tmp/ctxtest/
mkdir -p /tmp/ctxtest/filestore-backup/db /tmp/ctxtest/zips
dd if=/dev/zero of=/tmp/ctxtest/filestore-backup/db/blob bs=1M count=50 2>/dev/null
touch /tmp/ctxtest/release.file-2026-01-01_10-00-00
cd /tmp/ctxtest && du -sh . && docker build --no-cache -t ctxtest . 2>&1 | head -3
```

Expected: the `transferring context` line reports kilobytes, not ~50 MB. The build itself will fail on the `FROM` — only the context size matters here.

- [ ] **Step 4: Commit**

```bash
cd ~/gitbase/myodoo-docker
git add Dockerfiles/v16-odoo Dockerfiles/v18-odoo Dockerfiles/v19-odoo
git commit -m "[ADD] Dockerfiles: copy host-cached archives, add .dockerignore"
```

---

### Task 10: Wire the sync into update_docker_odoo.py

**Files:**
- Modify: `scripts/update_docker_odoo.py:1074-1096` (filestore backup path), `:1141-1152` (after the release manager), `:1337-1352` (backup rotation)

**Interfaces:**
- Consumes: `odoo_build_cache.py sync <build-dir>` from Task 7.

- [ ] **Step 1: Move the filestore backup under filestore-backup/**

At line 1076 replace:

```python
        filestore_path = join(path, db_name)
```

with:

```python
        # Under a fixed folder name so .dockerignore can exclude it — otherwise
        # the whole filestore travels into the build context on every build.
        filestore_root = join(path, "filestore-backup")
        filestore_path = join(filestore_root, db_name)
```

and the `docker cp` at line 1089 with:

```python
        success, _, info, warn, err = run_command(
            f"docker cp {container_name}:/opt/odoo/data/filestore/{db_name} {filestore_root}")
```

At lines 1338–1349 replace the two paths:

```python
    backup_path = join(path, "filestore-backup", f"{db_name}.bak")
    ...
    if isdir(join(path, "filestore-backup", db_name)):
        logger.info(f"Moving current filestore to backup: {join(path, 'filestore-backup', db_name)} -> {backup_path}")
        _, _, info, warn, err = run_step(
            "move filestore to backup",
            f"mv {join(path, 'filestore-backup', db_name)} {backup_path}")
```

- [ ] **Step 2: Call the cache sync before the build**

After the release manager block (line ~1152) and before the stop/remove loop, insert:

```python
    # Pre-fetch the release archives on the host so the build only downloads what
    # changed. Never fatal: whatever is missing, build_odoo.py fetches itself.
    cache_script = join(expanduser("~"), "odoo_build_cache.py")
    if isfile(cache_script):
        _, _, info, warn, err = run_step(
            "cache release archives", f"python3 {cache_script} sync {path}", env=proxy_env)
        total_info += info
        total_warnings += warn
        total_errors += err
    else:
        logger.debug("odoo_build_cache.py not present — build downloads every archive")
```

Check the imports at the top of the file: `expanduser` and `isfile` must be imported from `os.path` — add them to the existing import if missing.

- [ ] **Step 3: Bump the version header**

Increment `SCRIPT_VERSION` to `5.5.0` and set the date. Locate it with `grep -n "SCRIPT_VERSION\|^# Version" scripts/update_docker_odoo.py`.

- [ ] **Step 4: Verify it still parses and the paths are consistent**

```bash
cd ~/gitbase/myodoo-docker
python3 -m py_compile scripts/update_docker_odoo.py && echo "COMPILE OK"
grep -n "filestore-backup" scripts/update_docker_odoo.py
```

Expected: `COMPILE OK` and four hits — backup root, `docker cp` target, `.bak` path, rotation source. If any code still joins `path` with `db_name` directly for the filestore, it was missed.

- [ ] **Step 5: Commit**

```bash
git add scripts/update_docker_odoo.py
git commit -m "[CHG] update_docker_odoo.py v5.5.0: pre-fetch release archives, isolate filestore backup"
```

---

### Task 11: Delivery and scheduled cleanup

**Files:**
- Modify: `getScripts.py` (the `scripts` list in `copy_scripts()`, ~line 3670)
- Modify: `scripts/myodoo-maintenance.cron`
- Modify: `scripts/server-readiness.py` (new check)

- [ ] **Step 1: Deliver the script**

In `copy_scripts()` add `"odoo_build_cache.py",` to the list, next to `"server-readiness.py"`. Bump `getScripts.py`'s version header.

- [ ] **Step 2: Schedule the garbage collection**

Read `scripts/myodoo-maintenance.cron` first and match its existing formatting exactly. Add a weekly entry, Sundays 03:30, that runs `gc` for the cache and for every build folder:

```cron
# Weekly: drop cached release archives unused for 30 days
30 3 * * 0 root /usr/bin/python3 /root/odoo_build_cache.py gc >> /var/log/odoo-build-cache.log 2>&1
```

Add `odoo-build-cache` to the log list in `scripts/myodoo-maintenance.logrotate`, matching the existing entries.

- [ ] **Step 3: Add a readiness check**

In `scripts/server-readiness.py`, next to the other checks, add one that reports cache size and whether the script is present. Follow the existing shape exactly (`_ok`, `_skip`, `Finding`, registration in the check list — find it with `grep -n "check_backup_disk_space" scripts/server-readiness.py`):

```python
def check_build_cache(ctx: HealthContext) -> Finding:
    """The cache is pure optimisation, so its absence is informational, not a
    warning. Its size, however, is worth seeing before a disk fills up."""
    root = ctx.p("opt/odoo-build-cache")
    if not os.path.isdir(root):
        return _skip("build_cache", "Build cache", "not in use")
    count = total = 0
    for current, _dirs, files in os.walk(root):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(current, name))
                count += 1
            except OSError:
                continue
    return _ok("build_cache", "Build cache",
               f"{count} archive(s), {_human(total)}")
```

Bump `server-readiness.py` to `1.2.0`.

- [ ] **Step 4: Verify**

```bash
cd ~/gitbase/myodoo-docker
python3 -m py_compile getScripts.py scripts/server-readiness.py && echo "COMPILE OK"
grep -n "odoo_build_cache" getScripts.py scripts/myodoo-maintenance.cron
python3 -m unittest tests.test_odoo_build_cache -v
```

Expected: `COMPILE OK`, one hit per file, all tests still passing.

- [ ] **Step 5: Commit**

```bash
git add getScripts.py scripts/myodoo-maintenance.cron scripts/myodoo-maintenance.logrotate scripts/server-readiness.py
git commit -m "[ADD] deliver odoo_build_cache.py, schedule its gc, report cache size"
```

---

### Task 12: Documentation and live verification

**Files:**
- Modify: `RELEASE_NOTES.md`, `CLAUDE.md` (component table), `docs/INSTALLATION_GUIDE.md`

- [ ] **Step 1: Write the release notes entry**

Add a dated section at the top of `RELEASE_NOTES.md`, matching the existing style (cause before remedy, no marketing). Cover: why every build re-downloaded everything (`docker system prune -f` removing the build cache, the layer cache being all-or-nothing), why the filename is a sufficient cache key, the fallback guarantee, the `.dockerignore` finding with both filestore copies, and the filestore move as the one non-additive change. **Do not name the release host or any real archive name.**

- [ ] **Step 2: Update the component tables**

In `CLAUDE.md`, add `odoo_build_cache.py` to the scripts overview. In `docs/INSTALLATION_GUIDE.md`, add a short bilingual note on the cache location, the `gc` schedule, and `stats` for inspection.

- [ ] **Step 3: Live verification on one instance**

On a server, against a single instance (`doup` for one container):

```fish
python3 /root/odoo_build_cache.py stats
time python3 /root/odoo_build_cache.py sync /root/docker-builds/<instance>
python3 /root/odoo_build_cache.py stats
```

Expected: first `stats` empty or small, `sync` downloads everything once, second `stats` shows the archives. Then run it a second time — expected: no downloads, the summary reports every archive ready. Then a full `doup` for that instance and confirm in the build output that the count of cached archives matches.

- [ ] **Step 4: Record the numbers**

Add the measured figures (context size before/after, build duration before/after, cache size) to the "Offene Punkte" section of the spec, which explicitly asks for them. Then remove the point from that list.

- [ ] **Step 5: Commit and push**

```bash
git add RELEASE_NOTES.md CLAUDE.md docs/
git commit -m "[ADD] docs: build cache rollout notes and measured numbers"
git push origin 2026 && git push upstream 2026
```

---

## Self-Review

**Spec coverage:** Cache layout → Task 2. mtime as last-used → Tasks 3, 6. Atomic write and `is_zipfile` → Task 3. Hardlink with copy fallback → Task 4. `zips/` always created → Task 4. Dockerfile patch with the `sync_build_scripts` rationale → Task 5. GC of archives and `release.file-*` → Task 6. Retry/backoff/circuit breaker from `build_odoo.py` → Tasks 3, 7. Never blocking the build → Task 7 plus the fallback in Task 8. `.dockerignore` with the filestore move → Tasks 9, 10. Delivery via `getScripts.py`, cron, readiness → Task 11. Rollout order and the open measurement → Task 12.

**Non-goals honoured:** no change to the release manager or the CSV format; nothing tries to speed up a first build.

**Type consistency:** `parse_release_file -> (str, list)`, `cache_path_for(root, base_url, name)` — argument order identical at all four call sites. `populate_build_dir -> (linked, missing)`, `gc_cache -> (removed, freed)`, `download_and_extract -> (ok, from_cache)` in both call sites of Task 8. `COPY_LINE` is referenced by the Task 7 test and defined in Task 5.

**Known sharp edge, deliberately left in:** Task 7's test needs `MAX_ATTEMPTS` to be re-read per call; the step says so explicitly and prescribes `_attempts()`. Implementing Task 3 with a constant and Task 7 with the function is the intended sequence.
