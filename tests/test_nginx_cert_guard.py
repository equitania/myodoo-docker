"""
Tests for nginx-cert-guard.py — the listen-target guard added in v1.2.0.

These exist because of a real outage (13.08.2026): a customer repointed one A
record, and every vhost on the host went down. The pre-1.2.0 guard skipped IP
literals outright and only asked whether a hostname resolved — a question the
broken hostname answered with a cheerful "yes, to somebody else". The tests
below pin the distinction that was missing: resolvable is not bindable.

The module has hyphens in its filename and cannot be imported normally, so it
is loaded by path.

Run from the repository root:

    python3 -m unittest tests.test_nginx_cert_guard -v
"""

import importlib.util
import os
import socket
import tempfile
import unittest
from pathlib import Path

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
_spec = importlib.util.spec_from_file_location(
    "nginx_cert_guard", os.path.join(SCRIPTS, "nginx-cert-guard.py")
)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

HOST_IP = "91.107.223.250"
FOREIGN_IP = "94.130.186.22"

VHOST = """\
server {{
    listen {host}:80;
    listen {host}:443 ssl;
    server_name {domain};
    ssl_certificate     {cert};
    ssl_certificate_key {cert};
}}
"""


class VhostFixture(unittest.TestCase):
    """Builds a throwaway conf.d with real files on disk."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conf_dir = Path(self.tmp.name)
        # A cert file that exists, so cert checks never mask listen findings.
        self.cert = self.conf_dir / "fullchain.pem"
        self.cert.write_text("dummy", encoding="utf-8")

    def vhost(self, domain, listen_host=None):
        path = self.conf_dir / f"{domain}.conf"
        path.write_text(
            VHOST.format(host=listen_host or domain, domain=domain, cert=self.cert),
            encoding="utf-8",
        )
        return path

    def fake_dns(self, mapping):
        """Patch getaddrinfo with a fixed name -> IP map; unknown names fail."""
        def _resolve(host, *_args, **_kwargs):
            if host not in mapping:
                raise socket.gaierror(-2, "Name or service not known")
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (mapping[host], 0))]

        original = guard.socket.getaddrinfo
        guard.socket.getaddrinfo = _resolve
        self.addCleanup(lambda: setattr(guard.socket, "getaddrinfo", original))


class ListenHostsTest(VhostFixture):
    def test_hostnames_and_ips_are_extracted(self):
        path = self.vhost("example.de")
        self.assertEqual(guard.listen_hosts(path), ["example.de"])

    def test_bare_port_and_wildcards_carry_no_host(self):
        path = self.conf_dir / "wild.conf"
        path.write_text(
            "server {\n"
            "    listen 80;\n"
            "    listen 443 ssl;\n"
            "    listen 0.0.0.0:8080;\n"
            "    listen [::]:8443 ssl;\n"
            "}\n",
            encoding="utf-8",
        )
        self.assertEqual(guard.listen_hosts(path), [])

    def test_ipv6_literal_is_unbracketed(self):
        path = self.conf_dir / "v6.conf"
        path.write_text("server {\n    listen [2001:db8::1]:443 ssl;\n}\n",
                        encoding="utf-8")
        self.assertEqual(guard.listen_hosts(path), ["2001:db8::1"])

    def test_duplicates_collapse(self):
        path = self.vhost("example.de")  # :80 and :443 on the same host
        self.assertEqual(len(guard.listen_hosts(path)), 1)


class UnbindableListenTargetTest(VhostFixture):
    def test_local_ip_literal_is_fine(self):
        path = self.vhost("example.de", listen_host=HOST_IP)
        self.assertIsNone(guard.unbindable_listen_target(path, {HOST_IP}))

    def test_foreign_ip_literal_is_flagged(self):
        """The pre-1.2.0 guard skipped IP literals — this is that gap."""
        path = self.vhost("example.de", listen_host=FOREIGN_IP)
        found = guard.unbindable_listen_target(path, {HOST_IP})
        self.assertIsNotNone(found)
        self.assertEqual(found[0], FOREIGN_IP)
        self.assertIn("not assigned to this host", found[1])

    def test_hostname_pointing_at_us_is_fine(self):
        self.fake_dns({"example.de": HOST_IP})
        path = self.vhost("example.de")
        self.assertIsNone(guard.unbindable_listen_target(path, {HOST_IP}))

    def test_hostname_resolving_elsewhere_is_flagged(self):
        """The ucore outage in one assertion: resolves perfectly, just not to us."""
        self.fake_dns({"assistedhome.de": FOREIGN_IP})
        path = self.vhost("assistedhome.de")
        found = guard.unbindable_listen_target(path, {HOST_IP})
        self.assertIsNotNone(found)
        self.assertEqual(found[0], "assistedhome.de")
        self.assertIn(FOREIGN_IP, found[1])
        self.assertIn("not an address of this host", found[1])

    def test_unresolvable_hostname_is_still_flagged(self):
        self.fake_dns({})
        path = self.vhost("gone.example")
        found = guard.unbindable_listen_target(path, {HOST_IP})
        self.assertIsNotNone(found)
        self.assertIn("does not resolve", found[1])

    def test_unknown_local_ips_skip_the_bindability_half(self):
        """An unreadable `ip addr` must not condemn every vhost on the box."""
        self.fake_dns({"assistedhome.de": FOREIGN_IP})
        path = self.vhost("assistedhome.de")
        self.assertIsNone(guard.unbindable_listen_target(path, set()))

    def test_unknown_local_ips_still_catch_a_dead_name(self):
        """Skipping bindability is not skipping the check entirely."""
        self.fake_dns({})
        path = self.vhost("gone.example")
        self.assertIsNotNone(guard.unbindable_listen_target(path, set()))


class DetectBrokenTest(VhostFixture):
    def test_only_the_departed_domains_are_candidates(self):
        """Reproduces ucore: ten vhosts, one customer moved, eight stay healthy."""
        ours = ["ahs.ownerp.app", "ahs-fr.ownerp.app", "ahs-test.ownerp.app",
                "ahs-test-fr.ownerp.app", "ahs-vs.ownerp.app", "lisa.ownerp.app",
                "lisa-assistenz.com", "www.lisa-assistenz.com"]
        theirs = ["assistedhome.de", "www.assistedhome.de"]
        dns = {d: HOST_IP for d in ours}
        dns.update({d: FOREIGN_IP for d in theirs})
        self.fake_dns(dns)
        for domain in ours + theirs:
            self.vhost(domain)

        broken = guard.detect_broken(self.conf_dir, local_ips={HOST_IP})
        self.assertEqual(sorted(p.name for p, _ in broken),
                         ["assistedhome.de.conf", "www.assistedhome.de.conf"])

    def test_missing_cert_takes_precedence_over_listen(self):
        self.fake_dns({"example.de": HOST_IP})
        path = self.vhost("example.de")
        path.write_text(
            path.read_text(encoding="utf-8").replace(str(self.cert), "/nope/x.pem"),
            encoding="utf-8",
        )
        broken = guard.detect_broken(self.conf_dir, local_ips={HOST_IP})
        self.assertEqual(len(broken), 1)
        self.assertIn("missing cert file", broken[0][1])


class SharedCauseTest(unittest.TestCase):
    def test_one_reason_across_all_candidates_is_reported(self):
        candidates = [(Path("a.conf"), "same"), (Path("b.conf"), "same")]
        self.assertEqual(guard.shared_cause(candidates), "same")

    def test_differing_reasons_report_nothing(self):
        candidates = [(Path("a.conf"), "one"), (Path("b.conf"), "other")]
        self.assertIsNone(guard.shared_cause(candidates))

    def test_no_candidates_report_nothing(self):
        self.assertIsNone(guard.shared_cause([]))


class ListenBoundClassificationTest(VhostFixture):
    """The hard/soft split mode_check uses to pick its threshold."""

    def test_domain_in_listen_is_hard(self):
        path = self.vhost("assistedhome.de")
        self.assertIn(guard.domain_of(path), guard.listen_hosts(path))

    def test_domain_only_in_server_name_is_soft(self):
        path = self.vhost("assistedhome.de", listen_host=HOST_IP)
        self.assertNotIn(guard.domain_of(path), guard.listen_hosts(path))


if __name__ == "__main__":
    unittest.main()
