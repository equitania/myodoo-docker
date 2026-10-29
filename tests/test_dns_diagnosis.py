"""
Tests for the DNS outage diagnosis (12.10.2026): getScripts.diagnose_dns_failure()
after a failed `git pull`, server-readiness.py's check_dns_resolution(), and the
hand-built direct DNS query both of them carry.

The query is exercised against a throwaway UDP server on 127.0.0.1, so no test
here touches the network.

Run from the repository root:

    python3 -m unittest tests.test_dns_diagnosis -v
"""

import importlib.util
import os
import socket
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

_REAL_HOME = os.environ.get("HOME")
os.environ["HOME"] = tempfile.mkdtemp(prefix="getscripts-test-home-")

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, REPO)
try:
    import requests  # noqa: F401
except ImportError:
    sys.modules["requests"] = types.ModuleType("requests")
import getScripts as gs  # noqa: E402

if _REAL_HOME is not None:
    os.environ["HOME"] = _REAL_HOME

_spec = importlib.util.spec_from_file_location(
    "server_readiness", os.path.join(REPO, "scripts", "server-readiness.py"))
sr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sr)

QUERIES = (gs.direct_dns_query, sr._direct_dns_query)
_REAL_SENDTO = socket.socket.sendto


class FakeDnsServer:
    """Answers one query on 127.0.0.1 with a header built by `reply(query)`."""

    def __init__(self, reply):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.received = None
        self.thread = threading.Thread(target=self._serve, args=(reply,), daemon=True)
        self.thread.start()

    def _serve(self, reply):
        self.sock.settimeout(3)
        try:
            data, peer = self.sock.recvfrom(512)
        except OSError:
            return
        self.received = data
        # The test redirects socket.sendto for the client; the reply must not be.
        _REAL_SENDTO(self.sock, reply(data), peer)

    def close(self):
        self.thread.join(3)
        self.sock.close()


def _header(query, rcode=0, answers=1, same_id=True):
    qid = query[:2] if same_id else bytes([query[0] ^ 0xFF, query[1]])
    return qid + bytes([0x81, 0x80 | rcode]) + b"\x00\x01" + answers.to_bytes(2, "big") + b"\x00\x00\x00\x00"


class DirectQueryTest(unittest.TestCase):

    def ask(self, query_function, reply):
        server = FakeDnsServer(reply)
        self.addCleanup(server.close)
        # Both implementations always send to port 53; redirect to the fake.
        def sendto(sock, data, address):
            return _REAL_SENDTO(sock, data, ("127.0.0.1", server.port))

        with mock.patch.object(socket.socket, "sendto", sendto):
            result = query_function("github.com", server="127.0.0.1", timeout=2)
        return result, server

    def test_an_answer_with_records_counts(self):
        for query in QUERIES:
            with self.subTest(query=query.__module__):
                result, server = self.ask(query, lambda q: _header(q))
                self.assertTrue(result)
                server.close()
                # A record (1), class IN (1), name encoded as labels
                self.assertTrue(server.received.endswith(b"\x06github\x03com\x00\x00\x01\x00\x01"))

    def test_nxdomain_and_servfail_do_not(self):
        for query in QUERIES:
            for rcode in (2, 3):
                with self.subTest(query=query.__module__, rcode=rcode):
                    result, _ = self.ask(query, lambda q, r=rcode: _header(q, rcode=r, answers=0))
                    self.assertFalse(result)

    def test_a_reply_to_another_query_does_not(self):
        for query in QUERIES:
            with self.subTest(query=query.__module__):
                result, _ = self.ask(query, lambda q: _header(q, same_id=False))
                self.assertFalse(result)

    def test_no_answer_at_all_is_false_not_an_exception(self):
        for query in QUERIES:
            with self.subTest(query=query.__module__):
                with mock.patch.object(socket.socket, "recv", side_effect=socket.timeout):
                    self.assertFalse(query("github.com", server="127.0.0.1", timeout=0.1))


class DiagnoseDnsFailureTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def dropin(self, value):
        path = os.path.join(self.tmp.name, "etc/systemd/resolved.conf.d/dns-optimization.conf")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(f"[Resolve]\nDNSSEC={value}\n")
        return path

    def diagnose(self, direct, tcp=False):
        with mock.patch.object(gs, "direct_dns_query", return_value=direct), \
                mock.patch.object(gs, "direct_tcp_probe", return_value=tcp):
            return "\n".join(gs.diagnose_dns_failure("github.com", root=self.tmp.name))

    def test_dnssec_on_and_direct_answer_names_the_file_and_the_fix(self):
        path = self.dropin("allow-downgrade")
        text = self.diagnose(direct=True)
        self.assertIn("DNSSEC (allow-downgrade", text)
        self.assertIn(f"sed -i 's/^DNSSEC=.*/DNSSEC=no/' {path}; and systemctl restart", text)

    def test_direct_answer_without_dnssec_points_at_the_local_resolver(self):
        self.dropin("no")
        text = self.diagnose(direct=True)
        self.assertIn("lokale", text)
        self.assertIn("journalctl -u systemd-resolved", text)
        self.assertNotIn("sed -i", text)

    def test_no_direct_answer_points_at_the_network(self):
        self.dropin("allow-downgrade")
        text = self.diagnose(direct=False, tcp=False)
        self.assertIn("UDP 53", text)
        self.assertIn("ufw status verbose", text)
        self.assertNotIn("sed -i", text)

    def test_udp_dead_but_tcp_alive_names_the_firewall_in_front(self):
        # netcup SCP, 29.10.2026: TCP tracked, UDP replies dropped - DNS dead,
        # curl to 1.1.1.1 fine, and the old text sent the operator to UFW.
        self.dropin("no")
        text = self.diagnose(direct=False, tcp=True)
        self.assertIn("VOR dem", text)
        self.assertIn("Quellport 53", text)
        self.assertIn("123", text)
        self.assertIn("curl -4", text)
        self.assertNotIn("ufw status verbose", text)
        self.assertNotIn("sed -i", text)

    def test_direct_answer_never_runs_the_tcp_probe(self):
        self.dropin("no")
        with mock.patch.object(gs, "direct_dns_query", return_value=True), \
                mock.patch.object(gs, "direct_tcp_probe", side_effect=AssertionError("probed")):
            gs.diagnose_dns_failure("github.com", root=self.tmp.name)

    def test_tcp_probe_is_false_not_an_exception_when_nothing_answers(self):
        with mock.patch.object(socket, "create_connection", side_effect=OSError("unreachable")):
            self.assertFalse(gs.direct_tcp_probe(timeout=0.1))

    def test_the_pull_failure_path_calls_it(self):
        with open(os.path.join(REPO, "getScripts.py"), encoding="utf-8") as handle:
            source = handle.read()
        block = source[source.index("git pull fehlgeschlagen"):][:900]
        self.assertIn("Could not resolve host", block)
        self.assertIn("diagnose_dns_failure(", block)


class CheckDnsResolutionTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = sr.HealthContext(root=self.tmp.name, home=self.tmp.name, repo=self.tmp.name)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
            os.environ.pop(name, None)

    def write(self, relative, content):
        path = self.ctx.p(relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    def check(self, getent_code, direct=False):
        with mock.patch.object(sr, "_run", return_value=(getent_code, "")) as run, \
             mock.patch.object(sr, "_direct_dns_query", return_value=direct) as query:
            finding = sr.check_dns_resolution(self.ctx)
        return finding, run, query

    def test_it_is_registered(self):
        self.assertIn(sr.check_dns_resolution, sr.CHECKS)

    def test_resolving_is_ok_and_asks_nobody_directly(self):
        finding, _, query = self.check(0)
        self.assertEqual(finding.severity, sr.Severity.OK)
        query.assert_not_called()

    def test_without_getent_it_is_skipped(self):
        finding, _, _ = self.check(127)
        self.assertEqual(finding.severity, sr.Severity.SKIP)

    def test_dnssec_rejecting_answers_fails_with_the_sed(self):
        self.write("etc/systemd/resolved.conf.d/dns-optimization.conf", "[Resolve]\nDNSSEC=allow-downgrade\n")
        finding, _, _ = self.check(2, direct=True)
        self.assertEqual(finding.severity, sr.Severity.FAIL)
        self.assertIn("DNSSEC=allow-downgrade", finding.detail)
        self.assertIn("sed -i 's/^DNSSEC=.*/DNSSEC=no/' /etc/systemd/resolved.conf.d/dns-optimization.conf", finding.fix)

    def test_local_resolver_at_fault_without_dnssec(self):
        finding, _, _ = self.check(2, direct=True)
        self.assertEqual(finding.severity, sr.Severity.FAIL)
        self.assertIn("local resolver", finding.detail)
        self.assertIn("journalctl", finding.fix)

    def test_no_dns_at_all_fails(self):
        finding, _, _ = self.check(2, direct=False)
        self.assertEqual(finding.severity, sr.Severity.FAIL)
        self.assertIn("udp/53", finding.detail)

    def test_behind_a_proxy_no_dns_is_only_a_warning(self):
        self.write("etc/environment", 'http_proxy="http://proxy.example.com:3128"\n')
        finding, _, _ = self.check(2, direct=False)
        self.assertEqual(finding.severity, sr.Severity.WARN)
        self.assertIn("proxy", finding.detail)


if __name__ == "__main__":
    unittest.main()
