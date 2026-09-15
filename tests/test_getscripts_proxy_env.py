"""
Tests for ensure_proxy_environment() in getScripts.py.

Standard library only, like the rest of the suite. See test_getscripts_output.py
for why HOME is redirected around the import and why a placeholder stands in
for `requests`.

Background: on Debian, `Defaults env_reset` strips http_proxy/https_proxy/
no_proxy from a sudo child, and /etc/pam.d/sudo has no pam_env line, so
/etc/environment is not re-read under sudo either. A proxy-only server's `ups`
(which runs getScripts.py via sudo) then loses the proxy that its own fish
session and /etc/environment both carry, and every network call inside the
script (git pull first) goes direct and is silently dropped by the firewall.
ensure_proxy_environment() recovers it from the marker file apply_proxy_
settings() writes, or from /etc/environment, before anything else runs.

Run from the repository root:

    python3 -m unittest tests.test_getscripts_proxy_env -v
"""

import inspect
import os
import sys
import tempfile
import types
import unittest

_REAL_HOME = os.environ.get("HOME")
os.environ["HOME"] = tempfile.mkdtemp(prefix="getscripts-test-home-")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
try:
    import requests  # noqa: F401
except ImportError:
    sys.modules["requests"] = types.ModuleType("requests")
import getScripts as gs  # noqa: E402

if _REAL_HOME is not None:
    os.environ["HOME"] = _REAL_HOME

_PROXY_ENV_NAMES = ("http_proxy", "https_proxy", "no_proxy",
                    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")


class ProxyEnvironmentTestCase(unittest.TestCase):
    """Base class: isolates os.environ's proxy keys and PROXY_CONFIG_FILE /
    ETC_ENVIRONMENT so a test never touches the real system files."""

    def setUp(self):
        self._saved_env = {name: os.environ.get(name) for name in _PROXY_ENV_NAMES}
        for name in _PROXY_ENV_NAMES:
            os.environ.pop(name, None)

        self._tmpdir = tempfile.mkdtemp(prefix="getscripts-test-proxyenv-")
        self._orig_marker = gs.PROXY_CONFIG_FILE
        self._orig_etc_env = gs.ETC_ENVIRONMENT
        # Point both sources at paths that do not exist yet by default -
        # individual tests create the files they need.
        gs.PROXY_CONFIG_FILE = os.path.join(self._tmpdir, ".getscripts_proxy")
        gs.ETC_ENVIRONMENT = os.path.join(self._tmpdir, "environment")

    def tearDown(self):
        gs.PROXY_CONFIG_FILE = self._orig_marker
        gs.ETC_ENVIRONMENT = self._orig_etc_env
        for name, value in self._saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def _write(self, path, content):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)


class MarkerFileTest(ProxyEnvironmentTestCase):
    def test_marker_file_sets_both_case_variants(self):
        self._write(gs.PROXY_CONFIG_FILE,
                     "# Proxy configuration - managed by getScripts.py\n"
                     "http_proxy=http://proxy.example.com:8080\n"
                     "https_proxy=http://proxy.example.com:8080\n"
                     "no_proxy=localhost,127.0.0.1\n")

        gs.ensure_proxy_environment()

        self.assertEqual(os.environ["http_proxy"], "http://proxy.example.com:8080")
        self.assertEqual(os.environ["HTTP_PROXY"], "http://proxy.example.com:8080")
        self.assertEqual(os.environ["https_proxy"], "http://proxy.example.com:8080")
        self.assertEqual(os.environ["HTTPS_PROXY"], "http://proxy.example.com:8080")
        self.assertEqual(os.environ["no_proxy"], "localhost,127.0.0.1")
        self.assertEqual(os.environ["NO_PROXY"], "localhost,127.0.0.1")


class EtcEnvironmentFallbackTest(ProxyEnvironmentTestCase):
    def test_missing_marker_falls_back_to_etc_environment_quoted_and_unquoted(self):
        # gs.PROXY_CONFIG_FILE deliberately left absent (set up by setUp()).
        self._write(gs.ETC_ENVIRONMENT,
                     '# comment line, ignored\n'
                     'PATH="/usr/bin:/bin"\n'
                     'http_proxy="http://proxy.example.com:8080"\n'
                     "https_proxy=http://proxy.example.com:8080\n"
                     'no_proxy="localhost,127.0.0.1,.local"\n')

        gs.ensure_proxy_environment()

        self.assertEqual(os.environ["http_proxy"], "http://proxy.example.com:8080")
        self.assertEqual(os.environ["https_proxy"], "http://proxy.example.com:8080")
        self.assertEqual(os.environ["no_proxy"], "localhost,127.0.0.1,.local")
        self.assertEqual(os.environ["NO_PROXY"], "localhost,127.0.0.1,.local")

    def test_marker_file_wins_over_etc_environment(self):
        self._write(gs.PROXY_CONFIG_FILE,
                     "http_proxy=http://marker.example.com:8080\n"
                     "https_proxy=http://marker.example.com:8080\n")
        self._write(gs.ETC_ENVIRONMENT,
                     'http_proxy="http://etc-environment.example.com:8080"\n')

        gs.ensure_proxy_environment()

        self.assertEqual(os.environ["http_proxy"], "http://marker.example.com:8080")


class ExistingEnvironmentTest(ProxyEnvironmentTestCase):
    def test_existing_proxy_env_is_never_overwritten(self):
        os.environ["http_proxy"] = "http://already-set.example.com:3128"
        self._write(gs.PROXY_CONFIG_FILE,
                     "http_proxy=http://marker.example.com:8080\n"
                     "https_proxy=http://marker.example.com:8080\n")

        gs.ensure_proxy_environment()

        # Any of the four gate variables already set means the function does
        # not touch the environment at all - not even https_proxy, which was
        # not set beforehand.
        self.assertEqual(os.environ["http_proxy"], "http://already-set.example.com:3128")
        self.assertNotIn("https_proxy", os.environ)


class InvalidValueTest(ProxyEnvironmentTestCase):
    def test_invalid_proxy_url_is_ignored_valid_ones_still_applied(self):
        self._write(gs.PROXY_CONFIG_FILE,
                     "http_proxy=not-a-url\n"
                     "https_proxy=http://proxy.example.com:8080\n"
                     "no_proxy=localhost\n")

        gs.ensure_proxy_environment()

        self.assertNotIn("http_proxy", os.environ)
        self.assertNotIn("HTTP_PROXY", os.environ)
        self.assertEqual(os.environ["https_proxy"], "http://proxy.example.com:8080")
        self.assertEqual(os.environ["no_proxy"], "localhost")

    def test_invalid_no_proxy_is_ignored(self):
        self._write(gs.PROXY_CONFIG_FILE,
                     "http_proxy=http://proxy.example.com:8080\n"
                     'no_proxy=localhost";touch /tmp/pwned;"\n')

        gs.ensure_proxy_environment()

        self.assertEqual(os.environ["http_proxy"], "http://proxy.example.com:8080")
        self.assertNotIn("no_proxy", os.environ)
        self.assertNotIn("NO_PROXY", os.environ)


class NothingConfiguredTest(ProxyEnvironmentTestCase):
    def test_nothing_configured_means_no_change_and_no_output(self):
        # Neither gs.PROXY_CONFIG_FILE nor gs.ETC_ENVIRONMENT exists (default
        # from setUp()).
        import logging
        stream_records = []

        class _Collector(logging.Handler):
            def emit(self, record):
                stream_records.append(record)

        handler = _Collector()
        gs.logger.addHandler(handler)
        try:
            gs.ensure_proxy_environment()
        finally:
            gs.logger.removeHandler(handler)

        for name in _PROXY_ENV_NAMES:
            self.assertNotIn(name, os.environ)
        self.assertEqual(stream_records, [])


class CallOrderTest(unittest.TestCase):
    """ensure_proxy_environment() must run before the first network call in
    main() - a proxy recovered after update_repository()'s git pull already
    hung/timed out is too late."""

    def test_ensure_proxy_environment_runs_before_setup_environment_in_main(self):
        source = inspect.getsource(gs.main)
        ensure_pos = source.index("ensure_proxy_environment()")
        setup_pos = source.index("setup_environment()")
        update_repo_pos = source.index("update_repository(")
        self.assertLess(ensure_pos, setup_pos)
        self.assertLess(ensure_pos, update_repo_pos)


if __name__ == "__main__":
    unittest.main()
