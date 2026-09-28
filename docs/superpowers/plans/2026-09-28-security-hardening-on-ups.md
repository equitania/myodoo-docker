# Security Hardening Checked on Every `ups` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every `ups` checks the server's security hardening through the readiness report and, on a terminal, offers to apply what is missing — guarded against locking the operator out — while fixing the eight first-setup defects found on 28.09.2026.

**Architecture:** `server_hardening.py` gains a side-effect-free `--json` audit that reports per *area* (a group of its modules). `server-readiness.py` turns each area into one mutable check and adds `.env` and root-login checks. `getScripts.py` reads the same JSON to offer `.env` creation and module application; UFW/SSH/Docker pass a lockout gate first.

**Tech Stack:** Python 3 stdlib + `python3-yaml` (+ optional `python3-dotenv` for `server_hardening.py`), `unittest`, fish on the servers.

**Spec:** `docs/superpowers/specs/2026-09-28-security-hardening-on-ups-design.md`

## Global Constraints

- Delivered scripts run on system Python 3 with `python3-yaml` only — no new dependencies.
- Each changed script: `# Version:`/docstring header, `SCRIPT_VERSION` and (where present) `SCRIPT_DATE` bumped together; date `28.09.2026` in DD.MM.YYYY. Versions: `server_hardening.py` 1.8.0 → **1.9.0**, `server-readiness.py` 1.10.0 → **1.11.0**, `getScripts.py` 9.25.0 → **9.26.0**.
- `upstream` is public GitHub: no IP addresses (use `192.0.2.x` / `198.51.100.x`), no hostnames, no customer or location names in code, tests, comments, docs, release notes. Scan the staged diff before every commit.
- Commit prefixes `[ADD]` / `[CHG]` / `[FIX]`; every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.
- Test command (from repo root): `uv run --with 'textual>=8,<9' --with pyyaml python -m unittest discover -s tests` — plain `python3 -m unittest` silently skips tests.
- Operator-facing text in `getScripts.py` is German (like the existing offers); readiness report text is English (like the existing checks).
- `ups` never changes the SSH port and never restarts Docker while a container runs.
- No test touches a real firewall, sshd, package manager or Docker.

## Review Focus

- An allowlist IP that is a prefix of another (`192.0.2.1` vs `192.0.2.10`) — masking must replace each exactly, never leave `…0` behind. *(Task 3, `test_mask_does_not_cut_a_longer_ip`)*
- The operator's session arrives over IPv6 or as IPv4-mapped `::ffff:192.0.2.10` — the gate must compare the plain address. *(Task 6, `test_peer_host_forms`)*
- `.env` with quoted values, spaces around `=`, CRLF line endings — must read the same as a clean file. *(Task 6, `test_read_env_tolerates_quotes_and_crlf`)*
- The `.env.example` template carries example values in `ALLOWED_IP_2..4` — a generated `.env` must never keep them, or UFW would open SSH to documentation addresses. *(Task 6, `test_render_env_blanks_unused_template_ips`)*
- sshd listens on two ports during a migration (22 and a new one) — `SSH_PORT` matching either is not a port change. *(Task 6, `test_gate_accepts_any_listening_port`)*

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `scripts/server_hardening.py` | audit/apply; now also `--json`, areas, masking, apt helper, UFW order | modify |
| `scripts/hardening_config.yaml` | header note: host values belong in `.env` | modify |
| `scripts/server-readiness.py` | hardening area checks, `.env` check, root-login check, `wiz` hint | modify |
| `getScripts.py` | delivery; `.env` creation; lockout gate; `offer_security_hardening()` | modify |
| `scripts/bootstrap.sh` | closing message points at `ups`/`chk` | modify |
| `tests/test_server_hardening.py` | new — Tasks 1–3 | create |
| `tests/test_server_readiness.py` | Task 5 | modify |
| `tests/test_getscripts_security_offer.py` | new — Tasks 6–7 | create |
| `tests/test_delivered_scripts.py` | Task 4 | modify |
| `usage/AGENT.md`, `docs/usage/01-provisioning.md`, `docs/usage/09-reference.md`, `docs/COMPONENTS.md`, `RELEASE_NOTES.md` | Task 8 | modify |

---

### Task 1: `server_hardening.py` — apt timeout and SSH whitespace

Fixes first-setup defects 5 (30 s timeout on `apt-get install`) and 7 (false `✗` on `Subsystem sftp     /usr/…`).

**Files:**
- Modify: `scripts/server_hardening.py` — `run()` stays; add `APT_INSTALL_TIMEOUT`, `apt_install()`, `_ssh_value_matches()`; replace the five `run("apt-get update -qq && apt-get install …")` call sites (lines ~286, 469, 990, 1081, 1121); use `_ssh_value_matches()` in `audit_ssh()` (line ~649)
- Create: `tests/test_server_hardening.py`

**Interfaces:**
- Produces: `APT_INSTALL_TIMEOUT: int = 600`; `apt_install(packages: str) -> Optional[str]`; `_ssh_value_matches(current: str, expected: str) -> bool`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_server_hardening.py`:

```python
"""
Tests for server_hardening.py.

Written for the first-setup walkthrough of 28.09.2026: every defect found on
that fresh server that lives in this script is pinned here. Nothing in this
file touches a real firewall, sshd or package manager — run() is replaced.

Run from the repository root:

    uv run --with pyyaml python -m unittest tests.test_server_hardening -v
"""

import importlib.util
import io
import json
import os
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "scripts", "server_hardening.py")
_spec = importlib.util.spec_from_file_location("server_hardening", _PATH)
sh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sh)


class AptInstallTest(unittest.TestCase):
    """AIDE timed out after 30 s on a fresh VPS and finished in the background."""

    def test_install_uses_the_long_timeout_and_no_prompts(self):
        with mock.patch.object(sh, "run", return_value="") as fake:
            sh.apt_install("aide aide-common")
        command = fake.call_args.args[0]
        self.assertIn("DEBIAN_FRONTEND=noninteractive", command)
        self.assertIn("apt-get install -y -qq aide aide-common", command)
        self.assertEqual(fake.call_args.kwargs.get("timeout"), sh.APT_INSTALL_TIMEOUT)
        self.assertGreaterEqual(sh.APT_INSTALL_TIMEOUT, 600)

    def test_no_install_bypasses_the_helper(self):
        source = Path(_PATH).read_text(encoding="utf-8")
        body = source.split("def apt_install", 1)[1].split("\ndef ", 1)[1]
        rest = source.split("def apt_install", 1)[0] + body
        # The PyYAML hint in the import guard is a message, not a call.
        calls = [line for line in rest.splitlines()
                 if "apt-get install" in line and "run(" in line]
        self.assertEqual(calls, [])


class SshValueMatchTest(unittest.TestCase):
    """Debian writes `Subsystem sftp     /usr/lib/openssh/sftp-server`."""

    def test_runs_of_whitespace_are_equal(self):
        self.assertTrue(sh._ssh_value_matches(
            "sftp     /usr/lib/openssh/sftp-server",
            "sftp /usr/lib/openssh/sftp-server"))

    def test_case_is_ignored(self):
        self.assertTrue(sh._ssh_value_matches("Yes", "yes"))

    def test_a_different_value_still_differs(self):
        self.assertFalse(sh._ssh_value_matches("LANG LC_* COLORTERM", "LANG LC_*"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --with pyyaml python -m unittest tests.test_server_hardening -v`
Expected: FAIL — `AttributeError: module 'server_hardening' has no attribute 'apt_install'`

- [ ] **Step 3: Implement**

In `scripts/server_hardening.py`, after `run()`:

```python
# apt on a fresh host runs `update` first and may pull in dependencies (AIDE
# brings a mail transport agent). 30 s — run()'s default — was not enough on
# 28.09.2026: the call timed out and the install finished unseen in the
# background. DEBIAN_FRONTEND keeps a debconf prompt from waiting on a
# terminal nobody is looking at.
APT_INSTALL_TIMEOUT = 600


def apt_install(packages):
    """Install Debian packages non-interactively with a timeout that fits apt."""
    return run("DEBIAN_FRONTEND=noninteractive apt-get update -qq && "
               f"DEBIAN_FRONTEND=noninteractive apt-get install -y -qq {packages}",
               timeout=APT_INSTALL_TIMEOUT)


def _ssh_value_matches(current, expected):
    """sshd_config values compared the way sshd reads them: case-insensitive,
    any run of whitespace equal to one space."""
    return " ".join(str(current).split()).lower() == " ".join(str(expected).split()).lower()
```

Replace each install call site, e.g. line ~286:

```python
            apt_install("ufw")
```

and likewise `apt_install("fail2ban python3-systemd")`, `apt_install("unattended-upgrades apt-listchanges")`, `apt_install("auditd audispd-plugins")`, `apt_install("aide aide-common")`.

In `audit_ssh()` replace

```python
            if current.lower() == expected_str.lower():
```

with

```python
            if _ssh_value_matches(current, expected_str):
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run --with pyyaml python -m unittest tests.test_server_hardening -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/server_hardening.py tests/test_server_hardening.py
git commit -m "[FIX] server_hardening: apt installs get 600 s, SSH values compare whitespace-insensitively

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `server_hardening.py` — UFW rules before enable, canonical module order

Fixes first-setup defect 6 and the typed-order problem (`-m ssh ufw` ran SSH first).

**Files:**
- Modify: `scripts/server_hardening.py` — `audit_ufw()` (lines ~290-300 and the end of the function ~455); `main()` module loop (lines ~1500-1520)
- Test: `tests/test_server_hardening.py`

**Interfaces:**
- Produces: `MODULE_ORDER: Tuple[str, ...]` = `("ufw", "fail2ban", "ssh", "sysctl", "sysctl_persist", "kernel_modules", "docker", "auto_updates", "auditd", "aide", "nginx", "ports")`; `module_functions() -> Dict[str, Callable]`; `ordered_modules(requested: Optional[List[str]]) -> List[str]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_server_hardening.py` (before the `if __name__` block):

```python
UFW_CONFIG = {
    "ufw": {
        "defaults": {"incoming": "deny", "outgoing": "allow", "routed": "deny"},
        "ipv6": True,
        "public_ports": [{"port": 80, "proto": "tcp", "comment": "HTTP"}],
        "restricted_ports": [{"port": 22, "proto": "tcp", "comment": "SSH",
                              "allowed_ips": [{"ip": "192.0.2.10", "comment": "Office A"}]}],
    }
}


class UfwOrderTest(unittest.TestCase):
    """For a few seconds on 28.09.2026 new SSH connections were refused:
    UFW was enabled before its allow rules existed."""

    def test_enable_comes_after_every_allow(self):
        calls = []

        def fake_run(cmd, check=False, timeout=30):
            calls.append(cmd)
            if cmd == "ufw status verbose":
                return "Status: inactive"
            if cmd == "cat /etc/default/ufw":
                return "IPV6=yes"
            return ""

        with mock.patch.object(sh, "run", side_effect=fake_run), \
             mock.patch.object(sh.shutil, "which", return_value="/usr/sbin/ufw"), \
             redirect_stdout(io.StringIO()):
            sh.audit_ufw(UFW_CONFIG, apply=True, force=True)

        enable = [i for i, c in enumerate(calls) if "ufw enable" in c]
        allows = [i for i, c in enumerate(calls) if c.startswith("ufw allow")]
        self.assertEqual(len(enable), 1)
        self.assertTrue(allows)
        self.assertGreater(enable[0], max(allows))

    def test_an_active_ufw_is_not_enabled_again(self):
        calls = []

        def fake_run(cmd, check=False, timeout=30):
            calls.append(cmd)
            if cmd == "ufw status verbose":
                return "Status: active"
            return "IPV6=yes" if cmd == "cat /etc/default/ufw" else ""

        with mock.patch.object(sh, "run", side_effect=fake_run), \
             mock.patch.object(sh.shutil, "which", return_value="/usr/sbin/ufw"), \
             redirect_stdout(io.StringIO()):
            sh.audit_ufw(UFW_CONFIG, apply=True, force=True)
        self.assertFalse(any("ufw enable" in c for c in calls))


class ModuleOrderTest(unittest.TestCase):
    def test_typed_order_does_not_matter(self):
        self.assertEqual(sh.ordered_modules(["ssh", "ufw", "fail2ban"]),
                         ["ufw", "fail2ban", "ssh"])

    def test_no_selection_means_all_in_order(self):
        self.assertEqual(sh.ordered_modules(None), list(sh.MODULE_ORDER))

    def test_every_ordered_module_has_a_function(self):
        self.assertEqual(set(sh.module_functions()), set(sh.MODULE_ORDER))
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --with pyyaml python -m unittest tests.test_server_hardening -v`
Expected: FAIL — `UfwOrderTest` (enable index before allows) and `AttributeError: ... 'ordered_modules'`

- [ ] **Step 3: Implement**

In `audit_ufw()` replace the enable block

```python
        fail("UFW ist NICHT aktiv")
        if apply:
            run("echo 'y' | ufw enable")
            ok("UFW aktiviert")
            Stats.fix_count += 1
```

with

```python
        fail("UFW ist NICHT aktiv")
        # Enabled only at the very end, after the defaults and every allow
        # rule exist — enabling first refused new SSH connections for the
        # seconds in between (28.09.2026).
        enable_pending = apply
```

Declare `enable_pending = False` right after `status = run("ufw status verbose")`. At the end of the function, after the `if apply and add_cmds:` block:

```python
    if enable_pending:
        run("echo 'y' | ufw enable")
        ok("UFW aktiviert")
        Stats.fix_count += 1
```

Add at module level (after the last `audit_*` function, before `main()`):

```python
# Apply order is part of the safety story: the firewall rule for a new SSH
# port must exist before sshd moves to it, so `-m ssh ufw` runs ufw first.
MODULE_ORDER = ("ufw", "fail2ban", "ssh", "sysctl", "sysctl_persist",
                "kernel_modules", "docker", "auto_updates", "auditd", "aide",
                "nginx", "ports")


def module_functions():
    """Name -> audit function, looked up at call time so tests can patch them."""
    return {
        "ufw": audit_ufw, "fail2ban": audit_fail2ban, "ssh": audit_ssh,
        "sysctl": audit_sysctl, "sysctl_persist": audit_sysctl_persist,
        "kernel_modules": audit_kernel_modules, "docker": audit_docker,
        "auto_updates": audit_auto_updates, "auditd": audit_auditd,
        "aide": audit_aide, "nginx": audit_nginx, "ports": audit_open_ports,
    }


def ordered_modules(requested):
    """The requested modules in MODULE_ORDER, whatever order they were typed in."""
    wanted = set(requested) if requested else set(MODULE_ORDER)
    return [name for name in MODULE_ORDER if name in wanted]
```

In `main()` replace the `modules = {…}` dict, `selected = …` and its loop with:

```python
    modules = module_functions()
    for mod_name in ordered_modules(args.module):
        modules[mod_name](config, apply=args.apply, force=args.force)
```

Use `choices=list(MODULE_ORDER)` for `--module` (the literal list there is the same set).

- [ ] **Step 4: Run to verify they pass**

Run: `uv run --with pyyaml python -m unittest tests.test_server_hardening -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/server_hardening.py tests/test_server_hardening.py
git commit -m "[FIX] server_hardening: enable UFW after its rules, apply modules in fixed order

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `server_hardening.py` — `--json` audit, areas, IP masking, no writes in audit (1.9.0)

Fixes first-setup defect 4 and makes the audit consumable by readiness and `ups`.

**Files:**
- Modify: `scripts/server_hardening.py` — `ok()/warn()/fail()`, `inject_allowed_ips()`, `main()`; header docstring + `SCRIPT_VERSION = "1.9.0"`, date `28.09.2026`; epilog gains `--json`
- Test: `tests/test_server_hardening.py`

**Interfaces:**
- Consumes: `MODULE_ORDER`, `module_functions()`, `ordered_modules()` (Task 2)
- Produces:
  - `AREAS: Tuple[Tuple[str, Tuple[str, ...], str], ...]` — `(check_id, modules, on_fail)`, ids: `hardening_firewall`, `hardening_fail2ban`, `hardening_ssh`, `hardening_kernel`, `hardening_docker`, `hardening_updates`, `hardening_integrity`
  - `inject_allowed_ips()` entries now `{"n": int, "ip": str, "comment": str}`
  - `mask_ips(text: str, allowed: List[dict]) -> str`
  - `run_json_audit(config: dict, allowed: List[dict], env_info: dict) -> dict`
  - `CENTRAL_DIR: Path`, `REPO_SCRIPTS: Path`, `seed_central_dir(script_dir: Path) -> None`, `load_env(script_dir: Path) -> dict`
  - `main(argv: Optional[List[str]] = None) -> None`
  - JSON document: `{"version": str, "env": {"path": str, "present": bool, "loaded": bool, "ssh_port": Optional[int], "allowed_ips": int}, "areas": [{"check_id": str, "modules": [str], "on_fail": "FAIL"|"WARN", "status": "ok"|"warn"|"fail", "findings": [{"module": str, "level": "warn"|"fail", "text": str}]}], "error": Optional[str]}` — exit 0, or 1 with `error` set and `areas: []`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_server_hardening.py`:

```python
ALLOWED = [{"n": 1, "ip": "192.0.2.1", "comment": "Office A"},
           {"n": 2, "ip": "192.0.2.10", "comment": ""}]


class MaskTest(unittest.TestCase):
    def test_ip_becomes_comment_or_slot(self):
        text = "Port 22 von 192.0.2.1 FEHLT; Port 22 von 192.0.2.10 FEHLT"
        self.assertEqual(sh.mask_ips(text, ALLOWED),
                         "Port 22 von Office A FEHLT; Port 22 von ALLOWED_IP_2 FEHLT")

    def test_mask_does_not_cut_a_longer_ip(self):
        masked = sh.mask_ips("from 192.0.2.10", [ALLOWED[0]])
        self.assertEqual(masked, "from 192.0.2.10")

    def test_allowlist_entries_carry_their_slot(self):
        with mock.patch.dict(os.environ, {"ALLOWED_IP_3": "192.0.2.30"}, clear=True):
            allowed = sh.inject_allowed_ips({"ufw": {"restricted_ports": []}})
        self.assertEqual(allowed, [{"n": 3, "ip": "192.0.2.30", "comment": ""}])


def _fake_module(fail_text=None, warn_text=None, noise=False):
    def audit(config, apply=False, force=False):
        if noise:
            print("stray output that must not reach the JSON")
        sh.ok("fine")
        if warn_text:
            sh.warn(warn_text)
        if fail_text:
            sh.fail(fail_text)
    return audit


class JsonAuditTest(unittest.TestCase):
    def fakes(self, **overrides):
        functions = {name: _fake_module() for name in sh.MODULE_ORDER}
        functions.update(overrides)
        return mock.patch.object(sh, "module_functions", return_value=functions)

    def test_areas_follow_the_worst_module(self):
        env = {"path": "/x/.env", "present": True, "loaded": True,
               "ssh_port": 22, "allowed_ips": 1}
        with self.fakes(ufw=_fake_module(fail_text="UFW ist NICHT aktiv"),
                        sysctl=_fake_module(warn_text="x")):
            result = sh.run_json_audit({}, ALLOWED, env)
        areas = {a["check_id"]: a for a in result["areas"]}
        self.assertEqual([a[0] for a in sh.AREAS], [a["check_id"] for a in result["areas"]])
        self.assertEqual(areas["hardening_firewall"]["status"], "fail")
        self.assertEqual(areas["hardening_kernel"]["status"], "warn")
        self.assertEqual(areas["hardening_ssh"]["status"], "ok")
        self.assertEqual(areas["hardening_firewall"]["findings"],
                         [{"module": "ufw", "level": "fail", "text": "UFW ist NICHT aktiv"}])
        self.assertIsNone(result["error"])

    def test_no_ip_in_the_document(self):
        with self.fakes(ufw=_fake_module(fail_text="Port 22 von 192.0.2.1 FEHLT")):
            result = sh.run_json_audit({}, ALLOWED, {})
        self.assertNotIn("192.0.2.1", json.dumps(result))

    def test_stray_prints_do_not_leak(self):
        out = io.StringIO()
        with self.fakes(ufw=_fake_module(noise=True)), redirect_stdout(out):
            sh.run_json_audit({}, [], {})
        self.assertEqual(out.getvalue(), "")

    # Hermetic: __file__ points into a temp dir, so a developer's own
    # scripts/.env is never loaded; the real YAML is passed with -c.
    REPO_YAML = str(Path(_PATH).resolve().parent / "hardening_config.yaml")

    def hermetic(self, tmp):
        return mock.patch.object(sh, "__file__", str(Path(tmp) / "server_hardening.py"))

    def test_json_mode_writes_nothing_and_prints_one_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            central = Path(tmp) / "cfg"
            out = io.StringIO()
            env = {k: v for k, v in os.environ.items() if not k.startswith("ALLOWED_IP_")}
            env.update(SSH_PORT="22", ALLOWED_IP_1="192.0.2.1")
            with self.fakes(), self.hermetic(tmp), \
                 mock.patch.object(sh, "CENTRAL_DIR", central), \
                 mock.patch.object(sh.os, "geteuid", return_value=0), \
                 mock.patch.dict(os.environ, env, clear=True), \
                 redirect_stdout(out):
                sh.main(["--json", "-c", self.REPO_YAML])
            self.assertFalse(central.exists())
            self.assertEqual(sorted(os.listdir(tmp)), [])
        document = json.loads(out.getvalue())
        self.assertEqual(document["env"]["allowed_ips"], 1)
        self.assertEqual(document["env"]["ssh_port"], 22)
        self.assertFalse(document["env"]["present"])

    def test_json_reports_a_missing_ssh_port_as_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            env = {k: v for k, v in os.environ.items()
                   if k != "SSH_PORT" and not k.startswith("ALLOWED_IP_")}
            with self.fakes(), self.hermetic(tmp), \
                 mock.patch.object(sh, "CENTRAL_DIR", Path(tmp) / "cfg"), \
                 mock.patch.object(sh.os, "geteuid", return_value=0), \
                 mock.patch.dict(os.environ, env, clear=True), \
                 redirect_stdout(out), \
                 self.assertRaises(SystemExit) as exit_:
                sh.main(["--json", "-c", self.REPO_YAML])
        self.assertEqual(exit_.exception.code, 1)
        document = json.loads(out.getvalue())
        self.assertTrue(document["error"])
        self.assertEqual(document["areas"], [])

    def test_json_without_root_is_a_json_error(self):
        out = io.StringIO()
        with mock.patch.object(sh.os, "geteuid", return_value=1000), \
             redirect_stdout(out), self.assertRaises(SystemExit):
            sh.main(["--json"])
        self.assertIn("root", json.loads(out.getvalue())["error"])

    def test_json_and_apply_exclude_each_other(self):
        with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()), \
             self.assertRaises(SystemExit):
            sh.main(["--json", "--apply"])
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --with pyyaml python -m unittest tests.test_server_hardening -v`
Expected: FAIL — `AttributeError: ... 'mask_ips'` / `'run_json_audit'`, and `main()` takes no argument

- [ ] **Step 3: Implement the collector**

Below the `Stats` class:

```python
class Report:
    """What each module found, for --json. Filled by ok()/warn()/fail() while
    Report.current names the running module; outside a module nothing is kept."""
    current = None
    modules = {}

    @classmethod
    def reset(cls):
        cls.current = None
        cls.modules = {}

    @classmethod
    def record(cls, level, text):
        if cls.current is None:
            return
        entry = cls.modules.setdefault(cls.current,
                                       {"ok": 0, "warn": 0, "fail": 0, "findings": []})
        entry[level] += 1
        if level != "ok":
            entry["findings"].append({"level": level, "text": text})
```

Change the three printers (keep their output byte-identical):

```python
def ok(msg):
    Report.record("ok", msg)
    print(f"  {C.OK}✓{C.END} {msg}")

def warn(msg):
    Report.record("warn", msg)
    print(f"  {C.WARN}⚠{C.END} {msg}")

def fail(msg):
    Report.record("fail", msg)
    print(f"  {C.FAIL}✗{C.END} {msg}")
```

- [ ] **Step 4: Implement slots and masking**

In `inject_allowed_ips()` change the list build to keep the slot:

```python
    allowed = [{"n": n, "ip": ip, "comment": comment} for n, ip, comment in entries]
```

Add after it:

```python
def _allowlist_label(entry):
    return entry.get("comment") or f"ALLOWED_IP_{entry['n']}"


def mask_ips(text, allowed):
    """Replace each admin IP with its comment (or ALLOWED_IP_<n>). The audit
    output travels into support chats and tickets; the IPs need not."""
    for entry in sorted(allowed, key=lambda e: len(e["ip"]), reverse=True):
        pattern = rf"(?<![0-9A-Fa-f.:]){re.escape(entry['ip'])}(?![0-9A-Fa-f.:])"
        text = re.sub(pattern, _allowlist_label(entry), text)
    return text
```

In `main()` change the allowlist info line to count plus labels:

```python
        info(f"Allowlist: {len(allowed_ips)} IP(s) aus .env erkannt "
             f"({', '.join(_allowlist_label(a) for a in allowed_ips)})")
```

- [ ] **Step 5: Implement areas and the JSON audit**

After `ordered_modules()`:

```python
# One readiness check per area, so a host that deviates on purpose mutes only
# that part. server-readiness.py mirrors these ids in HARDENING_AREAS; a test
# holds the two lists equal.
AREAS = (
    ("hardening_firewall",  ("ufw",),                                        "FAIL"),
    ("hardening_fail2ban",  ("fail2ban",),                                   "FAIL"),
    ("hardening_ssh",       ("ssh",),                                        "FAIL"),
    ("hardening_kernel",    ("sysctl", "sysctl_persist", "kernel_modules"),  "WARN"),
    ("hardening_docker",    ("docker",),                                     "WARN"),
    ("hardening_updates",   ("auto_updates",),                               "WARN"),
    ("hardening_integrity", ("auditd", "aide"),                              "WARN"),
)


def run_json_audit(config, allowed, env_info):
    """Audit every area module (never applies) and summarise per area.

    stdout is redirected while the modules run: the document must be the only
    thing on stdout, and a stray print in any module would break the parse.
    """
    Report.reset()
    functions = module_functions()
    wanted = [m for _, modules, _ in AREAS for m in modules]
    with contextlib.redirect_stdout(io.StringIO()):
        for name in ordered_modules(wanted):
            Report.current = name
            functions[name](config, apply=False, force=False)
    Report.current = None

    areas = []
    for check_id, modules, on_fail in AREAS:
        fails = warns = 0
        findings = []
        for name in modules:
            result = Report.modules.get(name, {"ok": 0, "warn": 0, "fail": 0, "findings": []})
            fails += result["fail"]
            warns += result["warn"]
            findings += [{"module": name, "level": f["level"],
                          "text": mask_ips(f["text"], allowed)} for f in result["findings"]]
        status = "fail" if fails else "warn" if warns else "ok"
        areas.append({"check_id": check_id, "modules": list(modules),
                      "on_fail": on_fail, "status": status, "findings": findings})
    return {"version": SCRIPT_VERSION, "env": env_info, "areas": areas, "error": None}


def _emit_json(document, code=0):
    print(json.dumps(document, ensure_ascii=False))
    if code:
        sys.exit(code)
```

Add `import contextlib` and `import io` to the imports.

- [ ] **Step 6: Split `.env` handling so the audit writes nothing**

Replace the `.env` block in `main()` (from `script_dir = …` to the `warn("Keine .env gefunden. …")` line) with calls to two functions defined above `main()`:

```python
CENTRAL_DIR = Path("/root/.config/myodoo-docker")
REPO_SCRIPTS = Path("/root/myodoo-docker/scripts")


def seed_central_dir(script_dir):
    """Create the central directory and drop the .env template beside it.
    Only with --apply: an audit — and the readiness check built on it — must
    not write anything."""
    if not CENTRAL_DIR.exists():
        CENTRAL_DIR.mkdir(parents=True, mode=0o700)
        info(f"Verzeichnis erstellt: {CENTRAL_DIR}")
    target = CENTRAL_DIR / ".env.example"
    if target.exists():
        return
    for candidate in (script_dir / ".env.example", REPO_SCRIPTS / ".env.example"):
        if candidate.exists():
            shutil.copy2(candidate, target)
            info(f".env.example kopiert nach {CENTRAL_DIR}")
            return


def load_env(script_dir):
    """Load the first .env found; report what was found. Never writes."""
    central_env = CENTRAL_DIR / ".env"
    info_ = {"path": str(central_env), "present": False, "loaded": False}
    for env_path in (central_env, script_dir / ".env"):
        if not env_path.exists():
            continue
        info_.update(path=str(env_path), present=True)
        if load_dotenv is not None:
            load_dotenv(env_path)
            info(f".env geladen: {env_path}")
            info_["loaded"] = True
        else:
            warn("python-dotenv nicht installiert - .env wird ignoriert")
            warn("Installation: sudo apt install -y python3-dotenv")
        return info_
    warn(f"Keine .env gefunden. Erwartet: {central_env}")
    warn(f"Vorlage anpassen: cp {CENTRAL_DIR / '.env.example'} {central_env}")
    return info_
```

- [ ] **Step 7: Wire `--json` into `main()`**

Change the signature to `def main(argv=None):`, use `args = parser.parse_args(argv)`, and add the flag:

```python
    parser.add_argument("--json", action="store_true",
                        help="Audit als JSON auf stdout (nur ohne --apply; schreibt nichts)")
```

Right after parsing:

```python
    if args.json and args.apply:
        parser.error("--json gibt es nur im Audit-Modus (ohne --apply)")

    if os.geteuid() != 0:
        if args.json:
            _emit_json({"version": SCRIPT_VERSION, "env": {}, "areas": [],
                        "error": "root required"}, code=1)
        print(f"{C.FAIL}Fehler: Root-Rechte erforderlich.{C.END}")
        sys.exit(1)

    script_dir = Path(__file__).resolve().parent
    if args.apply:
        seed_central_dir(script_dir)

    # In --json mode everything printed before the document — .env notes,
    # prerequisite warnings, the allowlist line — is swallowed: stdout must
    # carry exactly one JSON document.
    quiet = (contextlib.redirect_stdout(io.StringIO()) if args.json
             else contextlib.nullcontext())
    with quiet:
        env_info = load_env(script_dir)
        for w in check_prerequisites():
            warn(w)
        config_path = Path(args.config)
        if not config_path.is_absolute():
            config_path = script_dir / config_path
        config = yaml.safe_load(config_path.read_text())
        # ... the existing mapping check, resolve_env_vars(), inject_allowed_ips()
        # and the allowlist info/warn lines stay here unchanged ...
        validation_errors = validate_config(config)

    port = config.get("ssh", {}).get("port")
    env_info["ssh_port"] = port if isinstance(port, int) else None
    env_info["allowed_ips"] = len(allowed_ips)
    if args.json:
        if validation_errors:
            _emit_json({"version": SCRIPT_VERSION, "env": env_info, "areas": [],
                        "error": "; ".join(validation_errors)}, code=1)
        _emit_json(run_json_audit(config, allowed_ips, env_info))
        return
```

Concretely: indent the existing block from `# Prerequisites check` down to and including `validation_errors = validate_config(config)` one level under `with quiet:`, replacing its old `.env` block by the `load_env()` call. The existing `if validation_errors:` print-and-exit and everything after it stay outside the `with`, after the `if args.json:` return.

Bump the header docstring to `Version: 1.9.0 / Date: 28.09.2026`, `SCRIPT_VERSION = "1.9.0"`, and add to the epilog under *AUDIT vs. APPLY*:

```
  --json        : Audit als ein JSON-Dokument (für server-readiness.py und ups);
                  schreibt nichts, Admin-IPs erscheinen nur als Kommentar/Slot.
```

- [ ] **Step 8: Run to verify they pass**

Run: `uv run --with pyyaml python -m unittest tests.test_server_hardening -v`
Expected: PASS (20 tests)

- [ ] **Step 9: Commit**

```bash
git add scripts/server_hardening.py tests/test_server_hardening.py
git commit -m "[ADD] server_hardening 1.9.0: --json audit per area, no writes, admin IPs masked

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Delivery — `server_hardening.py` and its YAML to `/root`

Fixes first-setup defect 1: the documented `/root/server_hardening.py` did not exist.

**Files:**
- Modify: `getScripts.py` — `copy_scripts()` list (~line 4116)
- Modify: `scripts/server-readiness.py` — `DELIVERED_SCRIPTS` (~line 93)
- Modify: `scripts/hardening_config.yaml` — header
- Test: `tests/test_delivered_scripts.py`

**Interfaces:**
- Produces: `/root/server_hardening.py` and `/root/hardening_config.yaml` on every `ups` (Tasks 5 and 7 call `<home>/server_hardening.py`)

- [ ] **Step 1: Write the failing test**

In `tests/test_delivered_scripts.py`, `DeliveredScriptsTest.test_the_new_tools_are_on_the_delivery_list`, extend the tuple:

```python
        for name in ("ownerp_cron.py", "ownerp_migrate.py", "ownerp_mute.py",
                     "nginx-cert-guard.py", "server-readiness.py",
                     "server_hardening.py", "hardening_config.yaml"):
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --with pyyaml python -m unittest tests.test_delivered_scripts -v`
Expected: FAIL — `'server_hardening.py' not found in [...]`

- [ ] **Step 3: Implement**

`getScripts.py` `copy_scripts()` — after `"ownerp_mute.py",`:

```python
        # server_hardening.py reads hardening_config.yaml from its own
        # directory, so both travel together. The documentation always named
        # /root/server_hardening.py; until 9.26.0 nothing put it there.
        "server_hardening.py",
        "hardening_config.yaml",
```

`scripts/server-readiness.py` `DELIVERED_SCRIPTS` — add `"server_hardening.py",` after `"ownerp_migrate.py",`.

`scripts/hardening_config.yaml` header — replace the two comment lines under the title with:

```yaml
# Alle Einstellungen werden von server_hardening.py gelesen.
# Diese Datei wird bei jedem `ups` nach /root ausgeliefert und dabei
# überschrieben: serverspezifische Werte (SSH-Port, Admin-IPs) gehören in
# /root/.config/myodoo-docker/.env, nie hierher.
```

Check `git ls-files -s scripts/server_hardening.py` shows mode `100755` (the executable-bit test covers delivered shebang scripts); if not: `git update-index --chmod=+x scripts/server_hardening.py`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --with pyyaml python -m unittest tests.test_delivered_scripts -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add getScripts.py scripts/server-readiness.py scripts/hardening_config.yaml tests/test_delivered_scripts.py
git commit -m "[FIX] getScripts: deliver server_hardening.py and hardening_config.yaml to /root

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: `server-readiness.py` 1.11.0 — hardening checks, root login, `wiz` hint

Fixes first-setup defects 2 and 8, and puts security into every report.

**Files:**
- Modify: `scripts/server-readiness.py` — new section before *Registry and runner*; `CHECKS`; `check_backup_config()`, `check_update_config()`; header `# Version: 1.11.0`, `# Date: 28.09.2026`, `SCRIPT_VERSION`, `SCRIPT_DATE`
- Test: `tests/test_server_readiness.py`

**Interfaces:**
- Consumes: `<home>/server_hardening.py --json` document (Task 3); `sh.AREAS` ids (Task 3, for the agreement test)
- Produces: `HARDENING_AREAS: Tuple[Tuple[str, str], ...]` (`check_id`, English title); check ids `hardening_env`, the seven area ids, `root_login_locked`; `_hardening_audit(ctx) -> Tuple[Optional[dict], Optional[str]]` cached on `ctx._hardening_cache`; `_container_count() -> Optional[int]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_server_readiness.py` (before the `if __name__` block; add `import sys` and `import subprocess` to the imports):

```python
def _area(check_id, status="ok", findings=(), on_fail="FAIL", modules=("ufw",)):
    return {"check_id": check_id, "modules": list(modules), "on_fail": on_fail,
            "status": status, "findings": list(findings)}


GOOD_ENV = {"path": "/root/.config/myodoo-docker/.env", "present": True,
            "loaded": True, "ssh_port": 22, "allowed_ips": 2}


class HardeningChecksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = sr.HealthContext(root=self.tmp.name, home=self.tmp.name,
                                    repo=self.tmp.name)

    def audit(self, env=GOOD_ENV, areas=(), error=None):
        self.ctx._hardening_cache = ({"version": "1.9.0", "env": env,
                                      "areas": list(areas), "error": error}, None)

    def check(self, check_id):
        return next(c for c in sr.CHECKS if c.__name__ == f"check_{check_id}")(self.ctx)

    def test_all_checks_are_registered(self):
        names = {c.__name__ for c in sr.CHECKS}
        for check_id, _ in sr.HARDENING_AREAS:
            self.assertIn(f"check_{check_id}", names)
        self.assertIn("check_hardening_env", names)
        self.assertIn("check_root_login_locked", names)

    def test_readiness_and_hardening_agree_on_the_areas(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "scripts", "server_hardening.py")
        spec = importlib.util.spec_from_file_location("server_hardening", path)
        sh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sh)
        self.assertEqual([a[0] for a in sh.AREAS], [a[0] for a in sr.HARDENING_AREAS])

    def test_a_failing_firewall_is_a_fail_with_the_command(self):
        self.audit(areas=[_area("hardening_firewall", "fail",
                                [{"module": "ufw", "level": "fail", "text": "UFW ist NICHT aktiv"},
                                 {"module": "ufw", "level": "fail", "text": "x"}])])
        finding = self.check("hardening_firewall")
        self.assertEqual(finding.severity, sr.Severity.FAIL)
        self.assertIn("UFW ist NICHT aktiv (+1 more)", finding.detail)
        self.assertIn("server_hardening.py --apply -m ufw", finding.fix)

    def test_a_warn_area_stays_warn_even_on_fail(self):
        self.audit(areas=[_area("hardening_kernel", "fail", [{"module": "sysctl",
                   "level": "fail", "text": "rp_filter"}], on_fail="WARN",
                   modules=("sysctl", "sysctl_persist", "kernel_modules"))])
        self.assertEqual(self.check("hardening_kernel").severity, sr.Severity.WARN)

    def test_ok_area_is_ok(self):
        self.audit(areas=[_area("hardening_ssh", "ok", modules=("ssh",))])
        self.assertEqual(self.check("hardening_ssh").severity, sr.Severity.OK)

    def test_missing_env_fails_and_areas_skip(self):
        self.audit(env={"path": "/root/.config/myodoo-docker/.env", "present": False,
                        "loaded": False, "ssh_port": None, "allowed_ips": 0},
                   error="ssh.port invalid: ''")
        env = self.check("hardening_env")
        self.assertEqual(env.severity, sr.Severity.FAIL)
        self.assertIn("ups", env.fix)
        self.assertEqual(self.check("hardening_firewall").severity, sr.Severity.SKIP)

    def test_env_without_admin_ips_fails(self):
        self.audit(env=dict(GOOD_ENV, allowed_ips=0))
        self.assertEqual(self.check("hardening_env").severity, sr.Severity.FAIL)

    def test_no_script_is_skip_not_alarm(self):
        finding = self.check("hardening_firewall")
        self.assertEqual(finding.severity, sr.Severity.SKIP)
        self.assertIn("server_hardening.py", finding.detail)

    def test_the_audit_runs_once_per_report(self):
        script = os.path.join(self.tmp.name, "server_hardening.py")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write("import json\nprint(json.dumps({'env': {}, 'areas': [], 'error': None}))\n")
        with unittest.mock.patch.object(sr.subprocess, "run",
                                        wraps=subprocess.run) as spy:
            sr._hardening_audit(self.ctx)
            sr._hardening_audit(self.ctx)
        self.assertEqual(spy.call_count, 1)

    def test_timeout_and_garbage_are_skip(self):
        with unittest.mock.patch.object(sr.os.path, "isfile", return_value=True), \
             unittest.mock.patch.object(sr.subprocess, "run",
                                        side_effect=subprocess.TimeoutExpired("x", 1)):
            data, error = sr._hardening_audit(self.ctx)
        self.assertIsNone(data)
        self.assertIn("timed out", error)
        ctx = sr.HealthContext(root=self.tmp.name, home=self.tmp.name, repo=self.tmp.name)
        with unittest.mock.patch.object(sr.os.path, "isfile", return_value=True), \
             unittest.mock.patch.object(sr.subprocess, "run", return_value=
                                        subprocess.CompletedProcess([], 1, "Traceback", "")):
            data, error = sr._hardening_audit(ctx)
        self.assertIsNone(data)

    def test_a_muted_area_is_muted(self):
        self.audit(areas=[_area("hardening_firewall", "fail",
                                [{"module": "ufw", "level": "fail", "text": "x"}])])
        mutes = os.path.join(self.tmp.name, sr.MUTES_RELATIVE)
        os.makedirs(os.path.dirname(mutes), exist_ok=True)
        with open(mutes, "w", encoding="utf-8") as handle:
            handle.write("hardening_firewall | 28.09.2026 | corporate firewall in front\n")
        with unittest.mock.patch.object(sr, "CHECKS",
                                        (next(c for c in sr.CHECKS
                                              if c.__name__ == "check_hardening_firewall"),)):
            findings = sr.run_checks(self.ctx)
        self.assertEqual(findings[0].severity, sr.Severity.MUTED)


class RootLoginLockedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = sr.HealthContext(root=self.tmp.name, home=self.tmp.name,
                                    repo=self.tmp.name)
        with open(os.path.join(self.tmp.name, "hardening_config.yaml"), "w",
                  encoding="utf-8") as handle:
            handle.write('ssh:\n  settings:\n    PermitRootLogin: "yes"\n')
        os.makedirs(os.path.join(self.tmp.name, "etc", "cloud"))
        with open(os.path.join(self.tmp.name, "etc", "cloud", "cloud.cfg"), "w",
                  encoding="utf-8") as handle:
            handle.write("disable_root: true\n")

    def run_check(self, passwd_output):
        with unittest.mock.patch.object(sr, "_run", return_value=(0, passwd_output)):
            return sr.check_root_login_locked(self.ctx)

    def test_locked_root_on_cloud_image_warns(self):
        finding = self.run_check("root L 2026-07-22 0 99999 7 -1")
        self.assertEqual(finding.severity, sr.Severity.WARN)
        self.assertIn("disable_root", finding.detail)
        self.assertIn("passwd root", finding.fix)

    def test_root_with_password_is_ok(self):
        self.assertEqual(self.run_check("root P 2026-09-28 0 99999 7 -1").severity,
                         sr.Severity.OK)

    def test_config_not_expecting_root_is_skip(self):
        with open(os.path.join(self.tmp.name, "hardening_config.yaml"), "w",
                  encoding="utf-8") as handle:
            handle.write('ssh:\n  settings:\n    PermitRootLogin: "prohibit-password"\n')
        self.assertEqual(self.run_check("root L").severity, sr.Severity.SKIP)


class FreshHostHintTest(unittest.TestCase):
    """A host without any container has nothing --from-docker could rebuild."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = sr.HealthContext(root=self.tmp.name, home=self.tmp.name,
                                    repo=self.tmp.name)
        for patcher in (unittest.mock.patch.object(sr.shutil, "which",
                                                   return_value="/usr/bin/docker"),
                        unittest.mock.patch.object(sr, "_container_count", return_value=0)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_update_config_points_at_wiz(self):
        finding = sr.check_update_config(self.ctx)
        self.assertIn("wizup", finding.fix)
        self.assertNotIn("--from-docker", finding.fix)

    def test_backup_config_points_at_wiz(self):
        finding = sr.check_backup_config(self.ctx)
        self.assertIn("wizup", finding.fix)
        self.assertNotIn("--from-docker", finding.fix)
```

In the existing `UpdateConfigTest.setUp` and `BackupConfigTest.test_the_fix_names_the_docron_alternative_with_docker`, keep the `--from-docker` expectation true by also patching `sr._container_count` to return `2`:

```python
        patcher2 = unittest.mock.patch.object(sr, "_container_count", return_value=2)
        patcher2.start()
        self.addCleanup(patcher2.stop)
```

(for the `BackupConfigTest` method use a `with unittest.mock.patch.object(sr, "_container_count", return_value=2):` around the call).

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --with pyyaml python -m unittest tests.test_server_readiness -v`
Expected: FAIL — `AttributeError: ... 'HARDENING_AREAS'` / `'_container_count'`

- [ ] **Step 3: Implement the container count and the `wiz` hints**

After `_run()`:

```python
def _container_count() -> Optional[int]:
    """How many containers exist (running or not); None when unknown."""
    if not shutil.which("docker"):
        return None
    code, output = _run(["docker", "ps", "-aq"])
    if code != 0:
        return None
    return len([line for line in output.splitlines() if line.strip()])
```

In `check_backup_config()`, inside `if shutil.which("docker"):`:

```python
        if _container_count() == 0:
            # A fresh host: nothing to rebuild from, the first instance comes next.
            fix = ("wizup   # add the first Odoo instance, then: wizbk   # its backup"
                   "  # or, if this host needs no backups: docron --disable container2backup")
        else:
            fix = (f"{ctx.home}/ownerp_migrate.py --from-docker   "
                   f"# rebuild from the running containers, then: edbk"
                   f"  # or, if this host needs no backups: docron --disable container2backup")
```

In `check_update_config()`, the `if error:` branch:

```python
    if error:
        if _container_count() == 0:
            fix = ("wizup   # add the first Odoo instance"
                   "  # or, if this host runs no doup instances: docron --disable odoo_build_cache")
        else:
            fix = (f"{ctx.home}/ownerp_migrate.py --from-docker   "
                   f"# rebuild from the running containers, then: edup"
                   f"  # or, if this host runs no doup instances: docron --disable odoo_build_cache")
        return Finding("update_config", Severity.FAIL, "Update config", error, fix)
```

- [ ] **Step 4: Implement the hardening checks**

New section before `# Registry and runner`:

```python
# ==============================================================================
# Security hardening (server_hardening.py --json)
# ==============================================================================

HARDENING_SCRIPT = "server_hardening.py"
HARDENING_TIMEOUT = 180
# Mirrors server_hardening.AREAS (a test holds them equal). Kept here as well
# because every id must produce a finding even when the script is missing —
# otherwise a mute on it would be reported as stale.
HARDENING_AREAS = (
    ("hardening_firewall",  "Firewall"),
    ("hardening_fail2ban",  "fail2ban"),
    ("hardening_ssh",       "SSH hardening"),
    ("hardening_kernel",    "Kernel hardening"),
    ("hardening_docker",    "Docker hardening"),
    ("hardening_updates",   "Auto updates"),
    ("hardening_integrity", "Audit/integrity"),
)
LOCKOUT_MODULES = ("ufw", "ssh")


def _hardening_audit(ctx: HealthContext) -> Tuple[Optional[dict], Optional[str]]:
    """Run the hardening audit once per report and cache it on the context.

    A subprocess, not an import: server_hardening.py needs PyYAML and this
    script must keep running without it. stdout only — stderr would break the
    parse. Every failure is a reason string for a SKIP, never an exception.
    """
    cached = getattr(ctx, "_hardening_cache", None)
    if cached is not None:
        return cached
    script = os.path.join(ctx.home, HARDENING_SCRIPT)
    if not os.path.isfile(script):
        result = (None, f"{HARDENING_SCRIPT} not deployed — run ups")
    else:
        try:
            proc = subprocess.run([sys.executable, script, "--json"],
                                  capture_output=True, text=True,
                                  timeout=HARDENING_TIMEOUT)
            data = json.loads(proc.stdout) if proc.stdout.strip() else None
            result = ((data, None) if isinstance(data, dict)
                      else (None, f"hardening audit gave no JSON (exit {proc.returncode})"))
        except subprocess.TimeoutExpired:
            result = (None, f"hardening audit timed out after {HARDENING_TIMEOUT}s")
        except (OSError, ValueError) as exc:
            result = (None, f"hardening audit failed: {exc}")
    ctx._hardening_cache = result
    return result


def check_hardening_env(ctx: HealthContext) -> Finding:
    title = "Hardening .env"
    data, error = _hardening_audit(ctx)
    if data is None:
        return _skip("hardening_env", title, error)
    env = data.get("env") or {}
    path = env.get("path") or "/root/.config/myodoo-docker/.env"
    create = (f"ups   # offers to create it  # or: cp {ctx.repo}/scripts/.env.example "
              f"{path}; and mcedit {path}")
    if not env.get("present"):
        return Finding("hardening_env", Severity.FAIL, title,
                       f"no {path} — hardening cannot know the SSH port or the admin IPs",
                       create)
    if not env.get("loaded"):
        return Finding("hardening_env", Severity.FAIL, title,
                       ".env present but python3-dotenv is missing, so it is ignored",
                       "apt install -y python3-dotenv")
    if not env.get("ssh_port"):
        return Finding("hardening_env", Severity.FAIL, title,
                       "SSH_PORT is not set", f"mcedit {path}")
    if not env.get("allowed_ips"):
        return Finding("hardening_env", Severity.FAIL, title,
                       "no ALLOWED_IP_<n> — an enabled UFW would open SSH to nobody",
                       f"mcedit {path}")
    return _ok("hardening_env", title,
               f"SSH_PORT {env['ssh_port']}, {env['allowed_ips']} admin IP(s)")


def _make_hardening_check(check_id: str, title: str) -> Callable[[HealthContext], Finding]:
    def check(ctx: HealthContext) -> Finding:
        data, error = _hardening_audit(ctx)
        if data is None:
            return _skip(check_id, title, error)
        if data.get("error"):
            return _skip(check_id, title, f"audit not run: {data['error']}")
        area = next((a for a in data.get("areas", []) if a.get("check_id") == check_id), None)
        if area is None:
            return _skip(check_id, title, "not reported by this server_hardening.py")
        modules = " ".join(area.get("modules", []))
        if area.get("status") == "ok":
            return _ok(check_id, title, f"{modules}: as configured")
        findings = area.get("findings") or []
        first = findings[0]["text"] if findings else "deviates from hardening_config.yaml"
        more = f" (+{len(findings) - 1} more)" if len(findings) > 1 else ""
        severity = (Severity.FAIL if area.get("status") == "fail"
                    and area.get("on_fail") == "FAIL" else Severity.WARN)
        fix = (f"python3 {ctx.home}/{HARDENING_SCRIPT} --apply -m {modules}"
               f"   # or: ups (offers it, with a lockout check)")
        if set(area.get("modules", [])) & set(LOCKOUT_MODULES):
            fix += "  # keep a second SSH session open"
        return Finding(check_id, severity, title, f"{first}{more}", fix)
    check.__name__ = f"check_{check_id}"
    return check


HARDENING_CHECKS = tuple(_make_hardening_check(check_id, title)
                         for check_id, title in HARDENING_AREAS)


def check_root_login_locked(ctx: HealthContext) -> Finding:
    """Cloud images lock root's password and set disable_root: true. The
    hardening then expects PermitRootLogin yes for a root nobody can log in
    as (28.09.2026). Reported, never fixed: it needs a password."""
    title = "Root login"
    config = (_read(os.path.join(ctx.home, "hardening_config.yaml"))
              or _read(os.path.join(ctx.repo, "scripts", "hardening_config.yaml")))
    if not config or not re.search(r'^\s*PermitRootLogin:\s*"?yes"?\s*$', config, re.M):
        return _skip("root_login_locked", title, "hardening does not expect root login")
    code, output = _run(["passwd", "-S", "root"])
    fields = output.split()
    if code != 0 or len(fields) < 2:
        return _skip("root_login_locked", title, "passwd -S root unavailable")
    if fields[1] != "L":
        return _ok("root_login_locked", title, "root has a usable password")
    cloud = _read(ctx.p("etc/cloud/cloud.cfg")) or ""
    by_cloud = bool(re.search(r"^\s*disable_root:\s*true", cloud, re.M))
    detail = ("root's password is locked"
              + (" and cloud-init sets disable_root: true" if by_cloud else "")
              + " — hardening expects PermitRootLogin yes, but root cannot log in")
    fix = ("passwd root; printf '%s\\n' 'disable_root: false' > "
           "/etc/cloud/cloud.cfg.d/99-ownerp-root.cfg")
    return Finding("root_login_locked", Severity.WARN, title, detail, fix)
```

Extend `CHECKS` after `check_odoo_capacity,`:

```python
    check_hardening_env,
    *HARDENING_CHECKS,
    check_root_login_locked,
```

Bump header `# Version: 1.11.0`, `# Date: 28.09.2026`, `SCRIPT_VERSION = "1.11.0"`, `SCRIPT_DATE = "28.09.2026"`. In the module docstring's list of checks, add the hardening areas in one line.

- [ ] **Step 5: Run to verify they pass**

Run: `uv run --with 'textual>=8,<9' --with pyyaml python -m unittest tests.test_server_readiness tests.test_readiness_mute tests.test_ownerp_state tests.test_ownerp_mute -v`
Expected: PASS — the last three still pass because a temp `home` has no `server_hardening.py` (SKIP findings, no subprocess)

- [ ] **Step 6: Commit**

```bash
git add scripts/server-readiness.py tests/test_server_readiness.py
git commit -m "[ADD] server-readiness 1.11.0: security hardening, .env and root-login checks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `getScripts.py` — `.env` rendering, SSH facts, lockout gate (pure helpers)

The testable half of the offer. No prompt, no apply yet.

**Files:**
- Modify: `getScripts.py` — new helpers next to `_docker_storage_driver_muted()` (~line 4485); `_docker_storage_driver_muted()` rewritten on top of `_muted_check_ids()`
- Create: `tests/test_getscripts_security_offer.py`

**Interfaces:**
- Produces:
  - `HARDENING_ENV_RELATIVE = os.path.join(".config", "myodoo-docker", ".env")`
  - `GUARDED_MODULES = ("ufw", "ssh", "docker")`
  - `_muted_check_ids(_myhome: str) -> Set[str]`
  - `_read_env_file(path: str) -> Dict[str, str]`
  - `_allowed_ips(env: Dict[str, str]) -> List[str]`
  - `_render_env(template: str, ssh_port: int, ips: List[str]) -> str`
  - `_write_env(path: str, text: str) -> bool` (False when the file exists)
  - `_peer_host(peer: str) -> str`
  - `_ssh_listen_ports() -> List[int]`, `_ssh_peers(ports: List[int]) -> Optional[List[str]]`, `_ssh_socket_active() -> bool`, `_running_containers() -> Optional[int]`
  - `_is_port_change(env: Dict[str, str], listen_ports: List[int]) -> bool`
  - `_lockout_blockers(env: Dict[str, str], listen_ports: List[int], peers: Optional[List[str]], socket_active: bool) -> List[str]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_getscripts_security_offer.py`:

```python
"""
Tests for the security-hardening offer in getScripts.py.

On 28.09.2026 a freshly provisioned server passed bootstrap, getScripts and
the maintenance cron and was still wide open: UFW off, no .env, SSH on port 22
reachable from the internet. `ups` now offers the hardening — and must never
lock the operator out doing it. The gate is tested as a pure function; nothing
here touches a real firewall, sshd or Docker.

Standard library only. See test_getscripts_output.py for why HOME is
redirected around the import and why a placeholder stands in for `requests`.

Run from the repository root:

    python3 -m unittest tests.test_getscripts_security_offer -v
"""

import os
import stat
import sys
import tempfile
import types
import unittest
from unittest import mock

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

TEMPLATE = """\
# comment
BACKUP_PASSWORD=
SSH_PORT=22
ALLOWED_IP_1=203.0.113.1
ALLOWED_IP_1_COMMENT=Example
ALLOWED_IP_2=203.0.113.2
ALLOWED_IP_2_COMMENT=
"""

ENV = {"SSH_PORT": "22", "ALLOWED_IP_1": "192.0.2.10", "ALLOWED_IP_2": "192.0.2.11"}


class EnvFileTest(unittest.TestCase):
    def test_read_env_tolerates_quotes_and_crlf(self):
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".env",
                                         newline="") as handle:
            handle.write('SSH_PORT = "16667"\r\n# x\r\nALLOWED_IP_1=\'192.0.2.10\'\r\n')
        self.addCleanup(os.unlink, handle.name)
        self.assertEqual(gs._read_env_file(handle.name),
                         {"SSH_PORT": "16667", "ALLOWED_IP_1": "192.0.2.10"})

    def test_allowed_ips_in_slot_order_with_gaps(self):
        self.assertEqual(gs._allowed_ips({"ALLOWED_IP_3": "192.0.2.3",
                                          "ALLOWED_IP_1": "192.0.2.1",
                                          "ALLOWED_IP_2": "",
                                          "ALLOWED_IP_1_COMMENT": "x"}),
                         ["192.0.2.1", "192.0.2.3"])

    def test_render_env_fills_port_and_ips(self):
        text = gs._render_env(TEMPLATE, 16667, ["192.0.2.10"])
        self.assertIn("SSH_PORT=16667\n", text)
        self.assertIn("ALLOWED_IP_1=192.0.2.10\n", text)
        self.assertIn("# comment\n", text)
        self.assertIn("BACKUP_PASSWORD=\n", text)

    def test_render_env_blanks_unused_template_ips(self):
        text = gs._render_env(TEMPLATE, 22, ["192.0.2.10"])
        self.assertNotIn("203.0.113", text)
        self.assertIn("ALLOWED_IP_2=\n", text)
        self.assertIn("ALLOWED_IP_1_COMMENT=\n", text)

    def test_render_env_appends_slots_the_template_lacks(self):
        text = gs._render_env("SSH_PORT=\n", 22, ["192.0.2.1", "192.0.2.2"])
        self.assertIn("ALLOWED_IP_2=192.0.2.2\n", text)

    def test_write_env_is_private_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cfg", ".env")
            self.assertTrue(gs._write_env(path, "SSH_PORT=22\n"))
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode), 0o700)
            self.assertFalse(gs._write_env(path, "SSH_PORT=99\n"))
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "SSH_PORT=22\n")


class MutesTest(unittest.TestCase):
    def test_reads_every_muted_id(self):
        with tempfile.TemporaryDirectory() as home:
            path = os.path.join(home, gs.STORAGE_DRIVER_MUTES_RELATIVE)
            os.makedirs(os.path.dirname(path))
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("# h\nhardening_firewall | 28.09.2026 | fw in front\n"
                             "docker_storage_driver | 15.09.2026 | kept\nbroken line\n")
            self.assertEqual(gs._muted_check_ids(home),
                             {"hardening_firewall", "docker_storage_driver"})
            self.assertTrue(gs._docker_storage_driver_muted(home))


class PeerHostTest(unittest.TestCase):
    def test_peer_host_forms(self):
        self.assertEqual(gs._peer_host("192.0.2.10:51234"), "192.0.2.10")
        self.assertEqual(gs._peer_host("[2001:db8::5]:51234"), "2001:db8::5")
        self.assertEqual(gs._peer_host("[::ffff:192.0.2.10]:51234"), "192.0.2.10")


class LockoutGateTest(unittest.TestCase):
    def test_clean_state_has_no_blockers(self):
        self.assertEqual(gs._lockout_blockers(ENV, [22], ["192.0.2.10"], False), [])

    def test_no_admin_ip_blocks(self):
        blockers = gs._lockout_blockers({"SSH_PORT": "22"}, [22], ["192.0.2.10"], False)
        self.assertTrue(any("ALLOWED_IP" in b for b in blockers))

    def test_a_session_outside_the_allowlist_blocks(self):
        blockers = gs._lockout_blockers(ENV, [22], ["192.0.2.10", "198.51.100.7"], False)
        self.assertTrue(any("außerhalb der Allowlist" in b for b in blockers))

    def test_unreadable_sessions_block(self):
        self.assertTrue(gs._lockout_blockers(ENV, [22], None, False))

    def test_port_change_blocks_and_is_detected(self):
        env = dict(ENV, SSH_PORT="16667")
        self.assertTrue(any("Portwechsel" in b
                            for b in gs._lockout_blockers(env, [22], ["192.0.2.10"], False)))
        self.assertTrue(gs._is_port_change(env, [22]))

    def test_gate_accepts_any_listening_port(self):
        env = dict(ENV, SSH_PORT="16667")
        self.assertEqual(gs._lockout_blockers(env, [22, 16667], ["192.0.2.10"], False), [])
        self.assertFalse(gs._is_port_change(env, [22, 16667]))

    def test_socket_activation_blocks(self):
        blockers = gs._lockout_blockers(ENV, [22], ["192.0.2.10"], True)
        self.assertTrue(any("ssh.socket" in b for b in blockers))


class SshFactsTest(unittest.TestCase):
    def run_result(self, stdout, code=0):
        return types.SimpleNamespace(returncode=code, stdout=stdout, stderr="")

    def test_listen_ports_from_sshd_t(self):
        with mock.patch.object(gs.subprocess, "run",
                               return_value=self.run_result("port 22\nport 16667\nx 1\n")):
            self.assertEqual(gs._ssh_listen_ports(), [22, 16667])

    def test_peers_from_ss(self):
        out = ("0 0 192.0.2.5:22 192.0.2.10:51000\n"
               "0 0 192.0.2.5:22 [::ffff:192.0.2.11]:51001\n")
        with mock.patch.object(gs.subprocess, "run", return_value=self.run_result(out)):
            self.assertEqual(gs._ssh_peers([22]), ["192.0.2.10", "192.0.2.11"])

    def test_ss_failure_is_none(self):
        with mock.patch.object(gs.subprocess, "run", side_effect=OSError("no ss")):
            self.assertIsNone(gs._ssh_peers([22]))

    def test_running_containers(self):
        with mock.patch.object(gs.shutil, "which", return_value="/usr/bin/docker"), \
             mock.patch.object(gs.subprocess, "run", return_value=self.run_result("")):
            self.assertEqual(gs._running_containers(), 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --with pyyaml python -m unittest tests.test_getscripts_security_offer -v`
Expected: FAIL — `AttributeError: module 'getScripts' has no attribute '_read_env_file'`

- [ ] **Step 3: Implement**

Ensure `import shutil` is at module level in `getScripts.py` (it is imported locally in `offer_storage_driver_mute()`; add `import shutil` to the top-level imports if absent; the tests patch `gs.shutil`).

Replace the body of `_docker_storage_driver_muted()` and add `_muted_check_ids()` above it:

```python
def _muted_check_ids(_myhome: str) -> Set[str]:
    """Every check_id muted on this host, from the file server-readiness.py's
    parse_mutes() reads: '<check_id> | <date> | <reason>', '#' comments and
    blank lines ignored. Unreadable propagates, like before: the callers treat
    it as "skip", never as "nothing muted"."""
    path = os.path.join(_myhome, STORAGE_DRIVER_MUTES_RELATIVE)
    muted: Set[str] = set()
    if not os.path.isfile(path):
        return muted
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|", 2)
            if len(parts) == 3:
                muted.add(parts[0].strip())
    return muted


def _docker_storage_driver_muted(_myhome: str) -> bool:
    """Whether docker_storage_driver is already muted on this host."""
    return STORAGE_DRIVER_CHECK_ID in _muted_check_ids(_myhome)
```

(keep the existing docstring's reasoning paragraph on `_muted_check_ids`; add `Set` and `Dict` to the `typing` import if missing).

Add the helpers after them:

```python
# ---------------------------------------------------------------------------
# Security hardening offer: facts and gate (see offer_security_hardening)
# ---------------------------------------------------------------------------

HARDENING_ENV_RELATIVE = os.path.join(".config", "myodoo-docker", ".env")
# Modules that can lock the operator out (ufw, ssh) or stop every container
# (docker needs a daemon restart). Applied only behind _lockout_blockers().
GUARDED_MODULES = ("ufw", "ssh", "docker")


def _read_env_file(path: str) -> Dict[str, str]:
    """KEY=VALUE lines of a .env, tolerant of quotes, spaces and CRLF."""
    values: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key.strip()] = value
    return values


def _allowed_ips(env: Dict[str, str]) -> List[str]:
    """ALLOWED_IP_<n> values in slot order, empty slots skipped."""
    slots = []
    for key, value in env.items():
        match = re.match(r"^ALLOWED_IP_(\d+)$", key)
        if match and value.strip():
            slots.append((int(match.group(1)), value.strip()))
    return [ip for _, ip in sorted(slots)]


def _render_env(template: str, ssh_port: int, ips: List[str]) -> str:
    """The template with SSH_PORT and the admin IPs filled in.

    Every ALLOWED_IP_<n> slot not given here is blanked, comments included: a
    template example address left in place would be an open SSH port for it.
    """
    lines, seen = [], set()
    for line in template.splitlines():
        match = re.match(r"^(SSH_PORT|ALLOWED_IP_(\d+)(_COMMENT)?)=", line)
        if not match:
            lines.append(line)
            continue
        key = match.group(1)
        seen.add(key)
        if key == "SSH_PORT":
            lines.append(f"SSH_PORT={ssh_port}")
        elif match.group(3):
            lines.append(f"{key}=")
        else:
            slot = int(match.group(2))
            lines.append(f"{key}={ips[slot - 1] if slot <= len(ips) else ''}")
    if "SSH_PORT" not in seen:
        lines.append(f"SSH_PORT={ssh_port}")
    for slot, ip in enumerate(ips, 1):
        if f"ALLOWED_IP_{slot}" not in seen:
            lines.append(f"ALLOWED_IP_{slot}={ip}")
    return "\n".join(lines) + "\n"


def _write_env(path: str, text: str) -> bool:
    """Create the .env (0600, directory 0700) atomically; never overwrite one."""
    if os.path.exists(path):
        return False
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    tmp = f"{path}.tmp-{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    if os.path.exists(path):
        os.unlink(tmp)
        return False
    os.replace(tmp, path)
    return True


def _peer_host(peer: str) -> str:
    """'192.0.2.1:5000', '[2001:db8::1]:5000', '[::ffff:192.0.2.1]:5000' -> the address."""
    peer = peer.strip()
    if peer.startswith("["):
        host = peer[1:peer.index("]")]
    else:
        host = peer.rsplit(":", 1)[0]
    return host[7:] if host.lower().startswith("::ffff:") else host


def _ssh_listen_ports() -> List[int]:
    """The ports sshd is configured to listen on (`sshd -T`); [] when unknown."""
    try:
        result = subprocess.run(["sshd", "-T"], capture_output=True, text=True, timeout=10)
    except Exception:
        return []
    ports = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == "port" and parts[1].isdigit():
            ports.append(int(parts[1]))
    return ports


def _ssh_peers(ports: List[int]) -> Optional[List[str]]:
    """Source addresses of every established connection to sshd.

    Read from the socket table, not from SSH_CONNECTION: sudo strips that, and
    the session that runs `ups` is not the only one that must survive.
    """
    hosts = set()
    for port in ports:
        try:
            result = subprocess.run(["ss", "-tnH", "state", "established",
                                     f"( sport = :{port} )"],
                                    capture_output=True, text=True, timeout=10)
        except Exception:
            return None
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            columns = line.split()
            if len(columns) >= 4:
                hosts.add(_peer_host(columns[3]))
    return sorted(hosts)


def _ssh_socket_active() -> bool:
    try:
        result = subprocess.run(["systemctl", "is-active", "ssh.socket"],
                                capture_output=True, text=True, timeout=10)
    except Exception:
        return False
    return result.stdout.strip() == "active"


def _running_containers() -> Optional[int]:
    if not shutil.which("docker"):
        return None
    try:
        result = subprocess.run(["docker", "ps", "-q"], capture_output=True,
                                text=True, timeout=20)
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return len([line for line in result.stdout.splitlines() if line.strip()])


def _is_port_change(env: Dict[str, str], listen_ports: List[int]) -> bool:
    port = env.get("SSH_PORT", "").strip()
    return port.isdigit() and bool(listen_ports) and int(port) not in listen_ports


def _lockout_blockers(env: Dict[str, str], listen_ports: List[int],
                      peers: Optional[List[str]], socket_active: bool) -> List[str]:
    """Why ufw/ssh must not be applied now; [] means it is safe."""
    blockers = []
    ips = _allowed_ips(env)
    if not ips:
        blockers.append("keine ALLOWED_IP_<n> in der .env – UFW würde SSH für niemanden öffnen")
    port = env.get("SSH_PORT", "").strip()
    if not port.isdigit():
        blockers.append("SSH_PORT fehlt in der .env")
    elif not listen_ports:
        blockers.append("sshd-Port nicht lesbar (sshd -T)")
    elif _is_port_change(env, listen_ports):
        blockers.append(f"SSH_PORT={port}, sshd lauscht auf "
                        f"{', '.join(map(str, listen_ports))} – das wäre ein Portwechsel, "
                        f"den ups nie selbst macht")
    if socket_active:
        blockers.append("ssh.socket ist aktiv – dort wird der Port festgelegt, nicht in sshd_config")
    if peers is None:
        blockers.append("aktive SSH-Verbindungen nicht lesbar (ss)")
    else:
        outside = [peer for peer in peers if peer not in ips]
        if outside:
            blockers.append(f"{len(outside)} aktive SSH-Verbindung(en) von IPs "
                            f"außerhalb der Allowlist")
    return blockers
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run --with pyyaml python -m unittest tests.test_getscripts_security_offer tests.test_getscripts_driver_offer -v`
Expected: PASS (the driver-offer tests still pass on the rewritten `_docker_storage_driver_muted()`)

- [ ] **Step 5: Commit**

```bash
git add getScripts.py tests/test_getscripts_security_offer.py
git commit -m "[ADD] getScripts: .env rendering, SSH facts and lockout gate for the hardening offer

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: `getScripts.py` 9.26.0 — `offer_security_hardening()` and wiring

**Files:**
- Modify: `getScripts.py` — new functions after `offer_storage_driver_mute()`; call in `main()` after `offer_storage_driver_mute(_myhome)` (~line 4880); `SCRIPT_VERSION = "9.26.0"`, `SCRIPT_DATE = "28.09.2026"`
- Test: `tests/test_getscripts_security_offer.py`

**Interfaces:**
- Consumes: everything Task 6 produces; the JSON document of Task 3; `run_command(command, shell=True, interactive=True)`, `status(message)`
- Produces: `HARDENING_AUDIT_TIMEOUT = 180`; `PORT_CHANGE_STEPS: Tuple[str, ...]`; `_hardening_audit(script: str) -> Optional[dict]`; `_offer_env_creation(_myhome: str, env_path: str) -> bool`; `_apply_hardening(_myhome: str, script: str, pending: List[dict], env_path: str) -> None`; `offer_security_hardening(_myhome: str) -> None`

The spec sketched letter keys (`[b]/[z]/[s]/[m]`); this uses the numbered menu of the two existing offers (1–4) so every question in one `ups` reads the same.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_getscripts_security_offer.py` (before `if __name__`):

```python
def _audit(*areas, error=None, env=None):
    return {"version": "1.9.0", "env": env or {"present": True}, "error": error,
            "areas": [{"check_id": c, "modules": m, "on_fail": "FAIL",
                       "status": s, "findings": []} for c, m, s in areas]}


class OfferTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="getscripts-test-home-hardening-")
        open(os.path.join(self.home, "server_hardening.py"), "w").close()
        self.env_path = os.path.join(self.home, gs.HARDENING_ENV_RELATIVE)
        os.makedirs(os.path.dirname(self.env_path))
        with open(self.env_path, "w", encoding="utf-8") as handle:
            handle.write("SSH_PORT=22\nALLOWED_IP_1=192.0.2.10\n")
        self.commands = []
        self.answers = []
        patches = [
            mock.patch.object(gs.sys.stdin, "isatty", return_value=True),
            mock.patch.object(gs.sys.stdout, "isatty", return_value=True),
            mock.patch.object(gs, "run_command",
                              side_effect=lambda c, **k: self.commands.append(c)
                              or types.SimpleNamespace(returncode=0)),
            mock.patch("builtins.input", side_effect=lambda _p="": self.answers.pop(0)),
            mock.patch("builtins.print"),
            mock.patch.object(gs, "status"),
            mock.patch.object(gs, "_ssh_listen_ports", return_value=[22]),
            mock.patch.object(gs, "_ssh_peers", return_value=["192.0.2.10"]),
            mock.patch.object(gs, "_ssh_socket_active", return_value=False),
            mock.patch.object(gs, "_running_containers", return_value=0),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def offer(self, audit):
        with mock.patch.object(gs, "_hardening_audit", return_value=audit):
            gs.offer_security_hardening(self.home)

    def applied(self):
        return [c.split(" -m ", 1)[1] for c in self.commands if " --apply " in c]

    def test_silent_without_a_terminal(self):
        with mock.patch.object(gs.sys.stdin, "isatty", return_value=False):
            self.offer(_audit(("hardening_firewall", ["ufw"], "fail")))
        self.assertEqual(self.commands, [])

    def test_silent_when_everything_is_ok_or_muted(self):
        mutes = os.path.join(self.home, gs.STORAGE_DRIVER_MUTES_RELATIVE)
        with open(mutes, "w", encoding="utf-8") as handle:
            handle.write("hardening_firewall | 28.09.2026 | fw in front\n")
        self.offer(_audit(("hardening_firewall", ["ufw"], "fail"),
                          ("hardening_ssh", ["ssh"], "ok")))
        self.assertEqual(self.commands, [])

    def test_fix_now_applies_harmless_then_guarded_then_aide(self):
        self.answers = ["1"]
        self.offer(_audit(("hardening_integrity", ["auditd", "aide"], "fail"),
                          ("hardening_firewall", ["ufw"], "fail"),
                          ("hardening_kernel", ["sysctl"], "warn")))
        self.assertEqual(self.applied(), ["auditd sysctl", "ufw", "aide"])

    def test_a_blocked_gate_applies_nothing_guarded(self):
        self.answers = ["1"]
        with mock.patch.object(gs, "_ssh_peers", return_value=["198.51.100.7"]):
            self.offer(_audit(("hardening_firewall", ["ufw"], "fail"),
                              ("hardening_ssh", ["ssh"], "fail")))
        self.assertEqual(self.applied(), [])

    def test_port_change_is_never_applied(self):
        with open(self.env_path, "w", encoding="utf-8") as handle:
            handle.write("SSH_PORT=16667\nALLOWED_IP_1=192.0.2.10\n")
        self.answers = ["1"]
        self.offer(_audit(("hardening_ssh", ["ssh"], "fail")))
        self.assertEqual(self.applied(), [])

    def test_fail2ban_waits_for_a_pending_port_change(self):
        with open(self.env_path, "w", encoding="utf-8") as handle:
            handle.write("SSH_PORT=16667\nALLOWED_IP_1=192.0.2.10\n")
        self.answers = ["1"]
        self.offer(_audit(("hardening_fail2ban", ["fail2ban"], "fail"),
                          ("hardening_kernel", ["sysctl"], "warn")))
        self.assertEqual(self.applied(), ["sysctl"])

    def test_docker_restart_only_without_containers(self):
        self.answers = ["1"]
        self.offer(_audit(("hardening_docker", ["docker"], "warn")))
        self.assertIn("systemctl restart docker", self.commands)
        self.commands.clear()
        self.answers = ["1"]
        with mock.patch.object(gs, "_running_containers", return_value=3):
            self.offer(_audit(("hardening_docker", ["docker"], "warn")))
        self.assertEqual(self.applied(), ["docker"])
        self.assertNotIn("systemctl restart docker", self.commands)

    def test_show_commands_applies_nothing(self):
        self.answers = ["2"]
        self.offer(_audit(("hardening_firewall", ["ufw"], "fail")))
        self.assertEqual(self.commands, [])

    def test_mute_one_area_calls_ownerp_mute(self):
        open(os.path.join(self.home, "ownerp_mute.py"), "w").close()
        self.answers = ["4", "1", "Firmen-Firewall davor"]
        self.offer(_audit(("hardening_firewall", ["ufw"], "fail")))
        self.assertEqual(len(self.commands), 1)
        self.assertIn("hardening_firewall --reason", self.commands[0])

    def test_missing_env_is_offered_with_the_session_ip(self):
        os.unlink(self.env_path)
        template = os.path.join(self.home, "myodoo-docker", "scripts", ".env.example")
        os.makedirs(os.path.dirname(template))
        with open(template, "w", encoding="utf-8") as handle:
            handle.write("SSH_PORT=\nALLOWED_IP_1=\n")
        # create? yes, port: default, ip 1: default, ip 2: done; then "later"
        self.answers = ["", "", "", "", "3"]
        self.offer(_audit(("hardening_firewall", ["ufw"], "fail")))
        values = gs._read_env_file(self.env_path)
        self.assertEqual(values["SSH_PORT"], "22")
        self.assertEqual(values["ALLOWED_IP_1"], "192.0.2.10")
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --with pyyaml python -m unittest tests.test_getscripts_security_offer -v`
Expected: FAIL — `AttributeError: ... 'offer_security_hardening'`

- [ ] **Step 3: Implement**

After `offer_storage_driver_mute()`:

```python
HARDENING_AUDIT_TIMEOUT = 180
HARDENING_CHECK_TITLES = {
    "hardening_firewall": "Firewall (UFW)",
    "hardening_fail2ban": "fail2ban",
    "hardening_ssh": "SSH",
    "hardening_kernel": "Kernel-Parameter und -Module",
    "hardening_docker": "Docker-Daemon",
    "hardening_updates": "Automatische Sicherheitsupdates",
    "hardening_integrity": "auditd / AIDE",
}
# The sequence proven on 28.09.2026. Printed, never run: step 1 happens in the
# provider's panel, which nothing on this host can see.
PORT_CHANGE_STEPS = (
    "1. Neuen Port in der Firewall/Security Group des Anbieters für die Admin-IPs öffnen (alten offen lassen)",
    "2. SSH_PORT in /root/.config/myodoo-docker/.env auf den neuen Port setzen",
    "3. python3 /root/server_hardening.py --apply -f -m ufw fail2ban ssh",
    "4. In einem zweiten Terminal auf dem neuen Port anmelden – die alte Sitzung offen lassen",
    "5. Alte UFW-Regeln löschen: ufw delete allow from <IP> to any port <alter Port>",
    "6. Alten Port beim Anbieter schließen",
)


def _hardening_audit(script: str) -> Optional[dict]:
    """The JSON audit of server_hardening.py, or None on any failure."""
    try:
        result = subprocess.run([sys.executable, script, "--json"], capture_output=True,
                                text=True, timeout=HARDENING_AUDIT_TIMEOUT)
        data = json.loads(result.stdout)
    except Exception as e:
        logger.debug(f"Hardening audit unavailable: {e}")
        return None
    return data if isinstance(data, dict) else None


def _prompt(text: str, default: str = "") -> Optional[str]:
    """input() with a default; None on EOF/Ctrl-C."""
    try:
        answer = input(text).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    return answer or default


def _offer_env_creation(_myhome: str, env_path: str) -> bool:
    """Create the missing .env from the repository template, with the current
    SSH port and the current session's address as suggestions."""
    template_path = os.path.join(_myhome, "myodoo-docker", "scripts", ".env.example")
    if not os.path.isfile(template_path):
        status(f"Keine .env und keine Vorlage ({template_path}) – bitte ups erneut ausführen")
        return False
    listen = _ssh_listen_ports()
    peers = _ssh_peers(listen) if listen else None
    print(f"\nDie Härtung braucht {env_path} (SSH-Port und Admin-IPs) – die Datei fehlt.")
    create = _prompt("Jetzt anlegen? [J/n]: ", "j")
    if create is None or create.lower() not in ("j", "ja", "y", "yes"):
        status(f"Später: cp {template_path} {env_path}; und mcedit {env_path}")
        return False
    port = _prompt(f"SSH_PORT [{listen[0] if listen else 22}]: ",
                   str(listen[0] if listen else 22))
    if port is None or not port.isdigit() or not 1 <= int(port) <= 65535:
        status("Ungültiger Port – keine .env angelegt")
        return False
    ips: List[str] = []
    while True:
        suggestion = peers[0] if (not ips and peers) else ""
        hint = f" [{suggestion}]" if suggestion else ""
        ip = _prompt(f"ALLOWED_IP_{len(ips) + 1}{hint} (leer = fertig): ", suggestion)
        if not ip:
            break
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            print(f"'{ip}' ist keine IP-Adresse.")
            continue
        ips.append(ip)
    if not ips:
        status("Ohne Admin-IP keine .env – UFW würde SSH für niemanden öffnen")
        return False
    with open(template_path, "r", encoding="utf-8") as handle:
        text = _render_env(handle.read(), int(port), ips)
    if not _write_env(env_path, text):
        status(f"{env_path} existiert bereits – nichts überschrieben")
        return False
    status(f".env angelegt: {env_path} (nur für root lesbar)")
    return True


def _hardening_command(script: str, modules: List[str]) -> str:
    return (f"{shlex.quote(sys.executable)} {shlex.quote(script)} "
            f"--apply -f -m {' '.join(modules)}")


def _print_hardening_commands(script: str, pending: List[dict]) -> None:
    for area in pending:
        title = HARDENING_CHECK_TITLES.get(area["check_id"], area["check_id"])
        print(f"  {title}: {_hardening_command(script, area['modules'])}")
    if any(set(a["modules"]) & {"ufw", "ssh"} for a in pending):
        print("  Bei UFW/SSH eine zweite SSH-Sitzung offen halten.")


def _apply_hardening(_myhome: str, script: str, pending: List[dict], env_path: str) -> None:
    """Harmless modules first, then ufw/ssh behind the lockout gate, then
    Docker, and AIDE last so its database records the finished state."""
    modules = [m for area in pending for m in area["modules"]]
    env = _read_env_file(env_path) if os.path.isfile(env_path) else {}
    listen = _ssh_listen_ports()
    port_change = _is_port_change(env, listen)
    harmless = [m for m in modules if m not in GUARDED_MODULES and m != "aide"
                # The sshd jail follows SSH_PORT: moved ahead of sshd it would
                # watch a port nobody logs in on. It belongs to the manual
                # port-change sequence (step 3) then.
                and not (m == "fail2ban" and port_change)]
    guarded = [m for m in modules if m in ("ufw", "ssh")]

    if harmless:
        run_command(_hardening_command(script, harmless), shell=True, interactive=True)

    if port_change and "fail2ban" in modules and not guarded:
        print("\nfail2ban wartet auf den Portwechsel:")
        for step in PORT_CHANGE_STEPS:
            print(f"  {step}")

    if guarded:
        blockers = _lockout_blockers(env, listen, _ssh_peers(listen) if listen else None,
                                     _ssh_socket_active())
        if blockers:
            print("\nFirewall/SSH werden NICHT angewendet:")
            for reason in blockers:
                print(f"  – {reason}")
            if port_change:
                print("Portwechsel von Hand, in dieser Reihenfolge:")
                for step in PORT_CHANGE_STEPS:
                    print(f"  {step}")
            else:
                print(f"Von Hand: {_hardening_command(script, guarded)}")
        else:
            run_command(_hardening_command(script, guarded), shell=True, interactive=True)

    if "docker" in modules:
        run_command(_hardening_command(script, ["docker"]), shell=True, interactive=True)
        if _running_containers() == 0:
            run_command("systemctl restart docker", shell=True, interactive=True)
        else:
            status("daemon.json geschrieben. Docker-Neustart im Wartungsfenster: "
                   "systemctl restart docker (startet alle Container neu)")

    if "aide" in modules:
        run_command(_hardening_command(script, ["aide"]), shell=True, interactive=True)


def _mute_hardening_area(_myhome: str, pending: List[dict]) -> None:
    mute_script = os.path.join(_myhome, "ownerp_mute.py")
    if not os.path.isfile(mute_script):
        status("ownerp_mute.py fehlt – bitte ups erneut ausführen")
        return
    for number, area in enumerate(pending, 1):
        print(f"  {number}) {HARDENING_CHECK_TITLES.get(area['check_id'], area['check_id'])}")
    choice = _prompt("Welchen Bereich stummschalten? ")
    if not choice or not choice.isdigit() or not 1 <= int(choice) <= len(pending):
        return
    reason = _prompt("Begründung (Pflicht): ")
    if not reason:
        status("Ohne Begründung wird nichts stummgeschaltet")
        return
    check_id = pending[int(choice) - 1]["check_id"]
    run_command(f"{shlex.quote(sys.executable)} {shlex.quote(mute_script)} "
                f"{check_id} --reason {shlex.quote(reason)}", shell=True, interactive=True)


def offer_security_hardening(_myhome: str) -> None:
    """Ask once per interactive run to close the hardening gaps readiness reports.

    Silent unless stdin and stdout are a terminal, ~/server_hardening.py
    exists, its --json audit ran, and at least one area is off and not muted.
    A missing .env is offered first. Any failure is "skip", never a broken ups.
    """
    try:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return
        script = os.path.join(_myhome, "server_hardening.py")
        if not os.path.isfile(script):
            return
        audit = _hardening_audit(script)
        if audit is None:
            return
        muted = _muted_check_ids(_myhome)
        env_path = os.path.join(_myhome, HARDENING_ENV_RELATIVE)
        if not os.path.isfile(env_path) and "hardening_env" not in muted:
            if _offer_env_creation(_myhome, env_path):
                audit = _hardening_audit(script) or audit
        if audit.get("error"):
            status(f"Härtungs-Audit nicht möglich: {audit['error']}")
            return
        pending = [area for area in audit.get("areas", [])
                   if area.get("status") != "ok" and area.get("check_id") not in muted]
        if not pending:
            return

        print("\nSicherheits-Härtung: diese Bereiche weichen ab")
        for area in pending:
            print(f"  – {HARDENING_CHECK_TITLES.get(area['check_id'], area['check_id'])}")
        print("  1) Jetzt beheben (Firewall/SSH nur nach Aussperr-Prüfung)")
        print("  2) Befehle anzeigen")
        print("  3) Später")
        print("  4) Einen Bereich dauerhaft stummschalten")
        choice = _prompt("Auswahl [3]: ", "3")
        if choice == "1":
            _apply_hardening(_myhome, script, pending, env_path)
        elif choice == "2":
            _print_hardening_commands(script, pending)
        elif choice == "4":
            _mute_hardening_area(_myhome, pending)
        else:
            status("Später: chk zeigt die offenen Bereiche, ups fragt beim nächsten Mal erneut")
    except Exception as e:
        logger.debug(f"Security hardening offer skipped: {e}")
```

Ensure `import ipaddress` and `import shlex` exist at module level (add if absent).

In `main()`, after `offer_storage_driver_mute(_myhome)`:

```python
        # The hardening that bootstrap deliberately leaves off. Runs before the
        # readiness report so the report shows the state after the choice.
        offer_security_hardening(_myhome)
```

Bump `SCRIPT_VERSION = "9.26.0"`, `SCRIPT_DATE = "28.09.2026"`.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run --with pyyaml python -m unittest tests.test_getscripts_security_offer -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add getScripts.py tests/test_getscripts_security_offer.py
git commit -m "[ADD] getScripts 9.26.0: ups offers the security hardening, guarded against lockout

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Documentation, bootstrap message, release notes

**Files:**
- Modify: `scripts/bootstrap.sh` (closing message ~line 893-895; bump its version header by a patch level and set the date)
- Modify: `usage/AGENT.md`, `docs/usage/01-provisioning.md`, `docs/usage/09-reference.md`, `docs/COMPONENTS.md`, `RELEASE_NOTES.md`
- Test: `tests/test_bootstrap.py` (existing — must stay green)

**Interfaces:**
- Consumes: final flags and check ids from Tasks 3, 5, 7

- [ ] **Step 1: Bootstrap closing message**

Replace

```bash
    echo "  • Apply full hardening: fill /root/.config/myodoo-docker/.env, then run"
    echo "    'sudo python3 ${TARGET_HOME}/myodoo-docker/scripts/server_hardening.py' (audit),"
    echo "    then add --apply.  See --help for what each module changes."
```

with

```bash
    echo "  • Security hardening is NOT applied yet (UFW is off). Run 'ups' in a terminal:"
    echo "    it creates /root/.config/myodoo-docker/.env and offers the hardening,"
    echo "    firewall and SSH only after a lockout check. 'chk' lists what is open."
```

- [ ] **Step 2: `usage/AGENT.md`**

- `server_hardening.py` row: flags add `--json` (audit as one JSON document, never writes, admin IPs masked; exclusive with `--apply`); note modules always run in fixed order; path `/root/server_hardening.py` (delivered since getScripts 9.26.0).
- `getScripts.py` row: `ups` on a terminal offers `.env` creation and hardening; UFW/SSH only when every SSH session comes from an allowlist IP, `SSH_PORT` equals sshd's port and `ssh.socket` is inactive; Docker restarted only without containers; never changes the SSH port.
- `server-readiness.py` row: new check ids `hardening_env`, `hardening_firewall`, `hardening_fail2ban`, `hardening_ssh`, `hardening_kernel`, `hardening_docker`, `hardening_updates`, `hardening_integrity`, `root_login_locked`; each mutable.
- Recipe *Provision a brand-new server*: replace the three hardening lines by `ups` (offers `.env` + hardening) and the manual alternative.
- New guardrail bullet: cloud images lock root (`passwd -S root` = `L`, `disable_root: true`); fix `passwd root` + `/etc/cloud/cloud.cfg.d/99-ownerp-root.cfg`.
- New guardrail bullet: SSH port change sequence (the six `PORT_CHANGE_STEPS`).

- [ ] **Step 3: `docs/usage/01-provisioning.md`** (both languages)

Step 3 *Server-Härtung / Server Hardening*: lead with "`ups` fragt nach" — what it asks, the lockout check, what it never does (port change, Docker restart with running containers). Keep the manual `server_hardening.py` commands as the alternative, now with `/root/server_hardening.py`. Add subsections: *SSH-Port wechseln / Changing the SSH port* (six steps) and *Cloud-Images: root gesperrt / Cloud images: root locked*. Placeholders only (`192.0.2.10`, "Office A").

- [ ] **Step 4: `docs/usage/09-reference.md`, `docs/COMPONENTS.md`**

Versions (`getScripts.py` 9.26.0, `server-readiness.py` 1.11.0, `server_hardening.py` 1.9.0) and one feature paragraph each, in the style of the neighbouring entries: why (the 28.09.2026 walkthrough), what, and the non-obvious rule (audit writes nothing; areas mirror `AREAS`; gate reads the socket table because sudo strips `SSH_CONNECTION`).

- [ ] **Step 5: `RELEASE_NOTES.md`**

New entry at the top, existing English style:

```markdown
## `ups` Checks and Offers the Security Hardening (28.09.2026)

*getScripts.py v9.26.0 · server-readiness.py v1.11.0 · server_hardening.py v1.9.0 ·
bootstrap.sh · tests · docs*
```

Sections *Added* (JSON audit, nine readiness checks, the offer and its gate, `.env` creation), *Fixed* (the eight first-setup defects, one line each), and **Upgrade note**: every server where the hardening never ran shows new FAILs after its first `ups` with this version — in the block after `ups`, in `chk` and in the Monday mail. A server that deviates on purpose mutes the area once: `ownerp_mute.py hardening_firewall --reason "..."`.

- [ ] **Step 6: Run the full suite**

Run: `uv run --with 'textual>=8,<9' --with pyyaml python -m unittest discover -s tests`
Expected: `OK` (no failures, no errors)

Run: `bash -n scripts/bootstrap.sh && echo syntax-ok`
Expected: `syntax-ok`

- [ ] **Step 7: Data-protection scan and commit**

```bash
git add scripts/bootstrap.sh usage/AGENT.md docs/usage/01-provisioning.md docs/usage/09-reference.md docs/COMPONENTS.md RELEASE_NOTES.md
git diff --cached | grep -nE '([0-9]{1,3}\.){3}[0-9]{1,3}' | grep -vE '192\.0\.2\.|198\.51\.100\.|203\.0\.113\.|127\.0\.0\.1|0\.0\.0\.0'
```

Expected: no output (only documentation ranges and loopback). Then:

```bash
git commit -m "[CHG] Docs: ups offers the hardening; port change and cloud-image root lock documented

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Whole-branch verification

- [ ] **Step 1: Full suite and version agreement**

Run: `uv run --with 'textual>=8,<9' --with pyyaml python -m unittest discover -s tests`
Expected: `OK`

Run: `grep -nE '^SCRIPT_VERSION|^SCRIPT_DATE|Version:' getScripts.py scripts/server-readiness.py scripts/server_hardening.py | head`
Expected: 9.26.0 / 1.11.0 / 1.9.0, all dated 28.09.2026

- [ ] **Step 2: Spec walk-through**

Read `docs/superpowers/specs/2026-09-28-security-hardening-on-ups-design.md` section by section and tick each requirement against the diff (`git diff 114311c..HEAD --stat` for the scope). Anything missing becomes a follow-up task, not a silent gap.

- [ ] **Step 3: Whole-repo data-protection scan**

Run: `git diff 114311c..HEAD | grep -nE '([0-9]{1,3}\.){3}[0-9]{1,3}' | grep -vE '192\.0\.2\.|198\.51\.100\.|203\.0\.113\.|127\.0\.0\.1|0\.0\.0\.0|[0-9]+\.[0-9]+\.[0-9]+ '`
Expected: no customer addresses. Version strings like `1.9.0` are not IPs.

No push — the Captain decides when both remotes get it.
