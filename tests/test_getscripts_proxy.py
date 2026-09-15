"""
Tests for the intranet defaults of the getScripts.py proxy setup.

Standard library only, like the rest of the suite. See
test_getscripts_output.py for why HOME is redirected around the import and why
a placeholder stands in for `requests`.

Run from the repository root:

    python3 -m unittest tests.test_getscripts_proxy -v
"""

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


class IntranetNoProxyTest(unittest.TestCase):
    """The host gets the same intranet exceptions as the containers do, so a
    shell, a cron job and doup agree on what bypasses the proxy."""

    def setUp(self):
        self._addresses = gs.host_ipv4_addresses
        self._domains = gs.host_search_domains
        gs.host_ipv4_addresses = lambda: ["192.168.1.50"]
        gs.host_search_domains = lambda: ["intra.example"]

    def tearDown(self):
        gs.host_ipv4_addresses = self._addresses
        gs.host_search_domains = self._domains

    def test_an_empty_answer_yields_the_full_intranet_default(self):
        entries = gs.intranet_no_proxy("").split(",")
        for entry in ("localhost", "127.0.0.1", "::1", ".local",
                      "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                      "192.168.1.50", ".intra.example"):
            self.assertIn(entry, entries)

    def test_the_operators_entries_come_first_and_are_not_duplicated(self):
        entries = gs.intranet_no_proxy("fr-server,localhost,.intra.example").split(",")
        self.assertEqual(entries[:2], ["fr-server", "localhost"])
        self.assertEqual(entries.count("localhost"), 1)
        self.assertEqual(entries.count(".intra.example"), 1)

    def test_the_result_passes_the_injection_guard(self):
        self.assertTrue(gs.validate_no_proxy(gs.intranet_no_proxy("")))


if __name__ == "__main__":
    unittest.main()
