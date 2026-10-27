# First Run on a Fresh Server — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `getScripts.py` on an empty Debian 13 host recognises Fish under any locale, works as root without `sudo`, asks for SSH port and admin addresses in the first-run dialogue, offers and runs `bootstrap.sh` when Docker is missing, and runs its checks only after the packages they need are installed.

**Architecture:** Everything lives in the single self-contained `getScripts.py` (never `scripts/lib/`, which is dead code), plus two one-line guards in `scripts/ownerp_migrate.py` and `scripts/server-readiness.py`. New behaviour is added as small pure functions (`probe_output`, `strip_sudo_for_root`, `parse_admin_addresses`, `render_minimal_env`, `resolve_install_home`) that `main()`/`run_first_time_setup()` call, so each is unit-testable with mocked `subprocess.run` and `input`.

**Tech Stack:** Python 3 stdlib only (system Python on Debian/Ubuntu), `unittest`, existing test-loading pattern (`tests/test_getscripts_security_offer.py` header: redirect HOME, stub `requests`, `import getScripts as gs`).

**Spec:** `docs/superpowers/specs/2026-10-27-first-run-fresh-server-design.md`

## Global Constraints

- No new dependencies: delivered scripts run on system Python 3 with `python3-yaml` only.
- Versions: `getScripts.py` 9.33.0 → **9.34.0**; `scripts/ownerp_migrate.py` 1.5.0 → **1.5.1**; `scripts/server-readiness.py` 1.14.2 → **1.15.0**; `bootstrap.sh` unchanged. Header comment `# Version:` and `SCRIPT_VERSION`/`SCRIPT_DATE` must agree; date **27.10.2026**.
- Operator-facing prompt text is German (as the existing dialogue), code/comments/docs English; German typography „…“ in German prose.
- Commit prefixes `[ADD]`/`[CHG]`/`[FIX]`; every commit ends with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. No push unless the operator asks (both remotes then; `upstream` is public — no hostnames, IPs or customer data in code, tests or docs; use `192.0.2.x`/`203.0.113.x`).
- Tests: `uv run --with 'textual>=8,<9' --with pyyaml python -m unittest discover -s tests -q` must stay green; new tests are stdlib `unittest`.
- Never put anything on a cleanup/delete list; never run `sudo` stripping for a non-root user.

## Review Focus

1. **IPv6 and IPv4-mapped peers** as the default address list (`[::ffff:192.0.2.1]:5000`): the default must show plain addresses and `ipaddress.ip_address()` must accept them — test in Task 4.
2. **Port equal to the live port** must print no "sshd lauscht derzeit …" note; only a different port does — test in Task 4.
3. **First run before the clone** (README path): template absent → minimal `.env`; the later hardening offer in the same run must not create a second one (`_write_env` never overwrites) — test in Task 4.
4. **`bootstrap.sh` fails midway** (apt lock, network): the run must continue, the install report shows `bootstrap failed`, Docker still absent → migrate wording and readiness SKIPs hold — tests in Tasks 5 and 6.
5. **`sudo` inside a quoted argument** (`echo "sudo x"`) must not be touched by the stripping; only command-position `sudo` — test in Task 2.

---

### Task 1: Locale-safe version probes and a visible Fish outcome

**Files:**
- Modify: `getScripts.py` — `is_fish_installed()` (~417), `is_zsh_installed()`, `is_starship_installed()` (~804), `get_bat_version()` (~2172), `get_7zip_version()` (~2378), `check_7zip_version()` (~2446), `install_fish_if_needed()` (~568–775)
- Test: `tests/test_getscripts_fresh_server.py` (create; copy the module-loading header from `tests/test_getscripts_security_offer.py`)

**Interfaces:**
- Produces: `probe_output(argv: List[str], timeout: float = 10) -> Optional[str]` — runs `subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=<os.environ copy with LC_ALL="C", LANG="C">)`; returns `stdout + stderr` on exit 0, `""` on non-zero exit, `None` on `FileNotFoundError`/`OSError`/`TimeoutExpired`.
- All version regexes compiled with `re.IGNORECASE`.

- [ ] **Step 1: Write the failing tests**

```python
class ProbeTest(unittest.TestCase):
    def test_probe_sets_c_locale(self):
        with mock.patch.object(gs.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(["x"], 0, "fish, version 4.9.3", "")
            gs.probe_output(["fish", "--version"])
        env = run.call_args.kwargs["env"]
        self.assertEqual(env["LC_ALL"], "C")
        self.assertEqual(env["LANG"], "C")
        self.assertIn("PATH", env)

    def test_probe_missing_binary_is_none(self):
        with mock.patch.object(gs.subprocess, "run", side_effect=FileNotFoundError):
            self.assertIsNone(gs.probe_output(["nope"]))

    def test_fish_version_localised_capital_v(self):
        with mock.patch.object(gs, "probe_output", return_value="fish, Version 4.9.3"):
            self.assertEqual(gs.is_fish_installed(), (True, "4.9.3"))

    def test_fish_version_english(self):
        with mock.patch.object(gs, "probe_output", return_value="fish, version 4.9.3"):
            self.assertEqual(gs.is_fish_installed(), (True, "4.9.3"))

    def test_fish_install_without_version_is_recorded_as_failed(self):
        # Debian branch: apt "succeeds", probe still finds nothing.
        gs._install_report.clear()
        with mock.patch.object(gs, "is_fish_installed", return_value=(False, None)), \
             mock.patch.object(gs, "is_root_or_has_sudo", return_value=True), \
             mock.patch.object(gs, "get_os_info", return_value=("debian", "13")), \
             mock.patch.object(gs, "cleanup_duplicate_fish_repo"), \
             mock.patch.object(gs, "is_fish_repo_configured", return_value=True), \
             mock.patch.object(gs, "is_fish_repo_key_present", return_value=True), \
             mock.patch.object(gs, "fix_apt_keyring_permissions"), \
             mock.patch.object(gs, "run_command"), \
             mock.patch.object(gs.os.path, "exists", return_value=False):
            self.assertEqual(gs.install_fish_if_needed(), (False, False))
        names = [(n, s) for n, s, _ in gs._install_report]
        self.assertIn(("fish", "failed"), names)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tests.test_getscripts_fresh_server -v`
Expected: FAIL — `probe_output` does not exist; the install report stays empty.

- [ ] **Step 3: Implement `probe_output()` and switch the probes to it**

`is_fish_installed()`: `output = probe_output(["fish", "--version"])`; `None` → log "Fish shell not found" (INFO), return `(False, None)`; match `re.search(r"version (\d+\.\d+\.\d+)", output, re.IGNORECASE)`. Same shape for zsh (`zsh (\d+\.\d+(?:\.\d+)?)`), starship (`starship (\S+)` — keep the existing split if simpler), bat (`bat (\d+\.\d+\.\d+)`) and the 7zz probe (`re.IGNORECASE` on its `(\d+)\.(\d+)`). Put the comment next to `probe_output()`: Fish 4.9 prints „fish, Version 4.9.3“ under a German locale; found 27.10.2026.

- [ ] **Step 4: Make `install_fish_if_needed()` report its outcome**

In both the Ubuntu and the Debian branch: after the verify step, `record_install("fish", "installed" if new_version != current_version else "ok", f"v{new_version}")` on success. Replace the trailing `return False, False` with `record_install("fish", "failed", "apt reported success, but `fish --version` gave no version — see ~/getscripts.log"); return False, False`, and add the same record in the two `except` paths (`detail=str(e)`).

- [ ] **Step 5: Run the tests**

Run: `python3 -m unittest tests.test_getscripts_fresh_server -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add getScripts.py tests/test_getscripts_fresh_server.py
git commit -m "[FIX] Version probes run under LC_ALL=C; Fish install outcome in the report

Fish 4.9 localises its version line (Version with a capital V under a German
locale), so a correctly installed Fish counted as missing and the run went on
without a word.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Root without `sudo`, and the base packages

**Files:**
- Modify: `getScripts.py` — `run_command()` (~1569), the `["sudo", "tee", repo_list_path]` call in `install_fish_if_needed()` (~690), new `write_system_file()`, new `ensure_base_packages()`, `main()` (call before the Fish setup)
- Test: `tests/test_getscripts_fresh_server.py`

**Interfaces:**
- Produces: `_SUDO_PREFIX_RE = re.compile(r"(^|[;&|]\s*)sudo\s+")`; `strip_sudo_for_root(command: str) -> str` (pure; returns `command` unchanged when `os.geteuid() != 0`); `write_system_file(path: str, content: str) -> None` (root: open/write; else `sudo tee` via `subprocess.run(["sudo", "tee", path], input=content.encode(), check=True, stdout=DEVNULL)`); `ensure_base_packages() -> None`.

- [ ] **Step 1: Write the failing tests**

```python
class SudoStripTest(unittest.TestCase):
    def test_root_strips_leading_and_chained_sudo(self):
        with mock.patch.object(gs.os, "geteuid", return_value=0):
            self.assertEqual(gs.strip_sudo_for_root("sudo apt update"), "apt update")
            self.assertEqual(gs.strip_sudo_for_root("curl -o k && sudo mv k /etc/k"),
                             "curl -o k && mv k /etc/k")
            self.assertEqual(gs.strip_sudo_for_root("a; sudo b | sudo c"), "a; b | c")
            self.assertEqual(gs.strip_sudo_for_root('echo "sudo x"'), 'echo "sudo x"')

    def test_non_root_keeps_sudo(self):
        with mock.patch.object(gs.os, "geteuid", return_value=1000):
            self.assertEqual(gs.strip_sudo_for_root("sudo apt update"), "sudo apt update")

    def test_run_command_applies_stripping(self):
        with mock.patch.object(gs.os, "geteuid", return_value=0), \
             mock.patch.object(gs.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(["apt"], 0, b"", b"")
            gs.run_command("sudo apt update", capture_output=True)
        self.assertEqual(run.call_args.args[0], ["apt", "update"])

class BasePackagesTest(unittest.TestCase):
    def test_installs_curl_when_missing(self):
        with mock.patch.object(gs.shutil, "which", return_value=None), \
             mock.patch.object(gs, "install_system_package") as inst:
            gs.ensure_base_packages()
        self.assertEqual([c.args[0] for c in inst.call_args_list], ["curl", "ca-certificates"])

    def test_silent_when_curl_present(self):
        with mock.patch.object(gs.shutil, "which", return_value="/usr/bin/curl"), \
             mock.patch.object(gs, "install_system_package") as inst:
            gs.ensure_base_packages()
        inst.assert_not_called()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tests.test_getscripts_fresh_server -v`
Expected: FAIL — names not defined.

- [ ] **Step 3: Implement**

`strip_sudo_for_root()` as specified; in `run_command()` apply it as the first statement (`command = strip_sudo_for_root(command)`), before the shell-operator detection. Replace the `subprocess.run(["sudo", "tee", repo_list_path], …)` with `write_system_file(repo_list_path, repo_list_content)`. `ensure_base_packages()`: when `shutil.which("curl")` is None → `install_system_package("curl")`, `install_system_package("ca-certificates")`, `record_install("base packages", "installed", "curl, ca-certificates")`; `InstallationError` → `record_install("base packages", "failed", str(e))`. Call it in `main()` directly before the `FISH SHELL SETUP` block.

- [ ] **Step 4: Run the tests**

Run: `python3 -m unittest tests.test_getscripts_fresh_server -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add getScripts.py tests/test_getscripts_fresh_server.py
git commit -m "[FIX] getScripts runs as root without the sudo package; installs curl first

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Checks after the packages they need

**Files:**
- Modify: `getScripts.py` — `main()` (~6210–6260: the block `migrate_legacy_csv` … `cleanup_legacy_files`/misplaced-log cleanup, and the `install_packages(package_info)` call)
- Test: `tests/test_getscripts_fresh_server.py`

- [ ] **Step 1: Write the failing test**

```python
class MainOrderTest(unittest.TestCase):
    def test_offers_run_after_install_packages(self):
        source = inspect.getsource(gs.main)
        install = source.index("install_packages(")
        for call in ("migrate_legacy_csv(", "offer_noconfig_recovery(",
                     "offer_storage_driver_mute(", "offer_security_hardening(",
                     "cleanup_legacy_files("):
            self.assertLess(install, source.index(call), call)
        self.assertLess(source.index("offer_security_hardening("),
                        source.index("print_install_report("))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest tests.test_getscripts_fresh_server.MainOrderTest -v`
Expected: FAIL (`install_packages(` currently comes after the offers).

- [ ] **Step 3: Move the block**

Cut the block from the comment `# Convert leftover CSV configurations to YAML` through the `else: logger.warning("Fish is not installed - skipping legacy cleanup")` and paste it directly after `install_packages(package_info)`, before `# SHELL SETUP COMPLETION`. Update the three docstring/comment sentences that say "must run BEFORE the legacy cleanup" (still true) and "Runs before the readiness report" (still true); add one comment line on the moved block: the migration needs PyYAML and the hardening audit needs python3-dotenv, both delivered by `install_packages()`.

- [ ] **Step 4: Run the whole suite**

Run: `uv run --with 'textual>=8,<9' --with pyyaml python -m unittest discover -s tests -q`
Expected: OK (the `test_getscripts_proxy_env` call-order test still holds).

- [ ] **Step 5: Commit**

```bash
git add getScripts.py tests/test_getscripts_fresh_server.py
git commit -m "[FIX] Migration, no-config and hardening offers run after the packages they need

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: First-run dialogue — SSH access block

**Files:**
- Modify: `getScripts.py` — `setup_environment()` (~3725: extract the home resolution), `FIRST_RUN_MARKER`/`PROXY_CONFIG_FILE` (~6336: keep as module constants, but `is_first_run()`/`mark_configured()` use `resolve_install_home()`), `run_first_time_setup()` (~6870), new functions below
- Test: `tests/test_getscripts_firstrun_ssh.py` (create; same header)

**Interfaces:**
- Produces:
  - `resolve_install_home() -> str` — the SUDO_USER/SUDO_COMMAND logic lifted verbatim out of `setup_environment()`, which then calls it.
  - `parse_admin_addresses(text: str) -> Tuple[List[str], List[str]]` — splits on commas and whitespace; returns `(accepted, rejected)`, accepted via `ipaddress.ip_address()` with `::ffff:`-mapped addresses reduced to IPv4 (`_peer_host` already does this for peers; apply `ipaddress.ip_address(x).ipv4_mapped` when not None), duplicates dropped, order kept.
  - `render_minimal_env(ssh_port: int, ips: List[str], template_path: str) -> str` — header comment naming `template_path` for every other key, then `SSH_PORT=<port>` and `ALLOWED_IP_<n>=<ip>` lines, trailing newline.
  - `configure_ssh_access(home: str) -> bool` — the block; True when a `.env` was written. Uses `_prompt()`, `_ssh_listen_ports()`, `_ssh_peers()`, `_render_env()`/`render_minimal_env()`, `_write_env()`. Template path `os.path.join(home, "myodoo-docker", "scripts", ".env.example")`; env path `os.path.join(home, HARDENING_ENV_RELATIVE)`.
  - `run_first_time_setup()` calls `configure_ssh_access(resolve_install_home())` after the DNS block and before `mark_configured()`.
- Consumes: `_prompt`, `_ssh_listen_ports`, `_ssh_peers`, `_render_env`, `_write_env`, `HARDENING_ENV_RELATIVE`, `PORT_CHANGE_STEPS` (unchanged).

Exact copy (German, operator-facing):

```
SSH-Zugang für die Härtung                                   (block title, framed like the other two)
Die Firewall lässt SSH später nur von diesen Adressen auf diesem Port zu.
Der Port wird hier nur festgelegt, nicht geändert.
Admin-Adressen und Port jetzt festlegen? (J/n):              default j
SSH-Port [<default>]:
Admin-IPs, kommagetrennt [<default list>]:
'<entry>' ist keine einzelne IP-Adresse (ALLOWED_IP erlaubt nur einzelne Adressen, keine Netze).
Ohne Admin-IP keine .env – UFW würde SSH für niemanden öffnen
.env angelegt: <path> (nur für root lesbar)
sshd lauscht derzeit auf <live>. Die Härtung wartet mit UFW und SSH, bis sshd auf <port> lauscht – die sechs Schritte zeigt ups dann an.
Später: ups fragt beim nächsten Mal nach den Werten, oder: cp <template> <env>; and mcedit <env>
.env vorhanden: SSH_PORT=<p>, ALLOWED_IP: <a, b> – ändern mit: mcedit <env>
```

- [ ] **Step 1: Write the failing tests**

```python
class ParseAddressesTest(unittest.TestCase):
    def test_commas_spaces_ipv6_and_mapped(self):
        ok, bad = gs.parse_admin_addresses("192.0.2.10, 198.51.100.7 2001:db8::1 ::ffff:192.0.2.11")
        self.assertEqual(ok, ["192.0.2.10", "198.51.100.7", "2001:db8::1", "192.0.2.11"])
        self.assertEqual(bad, [])

    def test_network_and_garbage_rejected_duplicates_dropped(self):
        ok, bad = gs.parse_admin_addresses("192.0.2.0/24, host, 192.0.2.1, 192.0.2.1")
        self.assertEqual(ok, ["192.0.2.1"])
        self.assertEqual(bad, ["192.0.2.0/24", "host"])

class MinimalEnvTest(unittest.TestCase):
    def test_only_the_hardening_keys_are_active(self):
        text = gs.render_minimal_env(2222, ["192.0.2.10", "198.51.100.7"], "/root/myodoo-docker/scripts/.env.example")
        active = [l for l in text.splitlines() if l and not l.startswith("#")]
        self.assertEqual(active, ["SSH_PORT=2222", "ALLOWED_IP_1=192.0.2.10", "ALLOWED_IP_2=198.51.100.7"])
        self.assertIn("/root/myodoo-docker/scripts/.env.example", text)

class ConfigureSshAccessTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.env = os.path.join(self.home, gs.HARDENING_ENV_RELATIVE)
        self.ports = mock.patch.object(gs, "_ssh_listen_ports", return_value=[22]); self.ports.start()
        self.peers = mock.patch.object(gs, "_ssh_peers", return_value=["203.0.113.5"]); self.peers.start()
    def tearDown(self):
        self.ports.stop(); self.peers.stop()

    def run_block(self, answers):
        out = io.StringIO()
        with mock.patch("builtins.input", side_effect=answers), \
             mock.patch("sys.stdout", out):
            result = gs.configure_ssh_access(self.home)
        return result, out.getvalue()

    def test_defaults_write_minimal_env_without_template(self):
        ok, out = self.run_block(["", "", ""])          # j, port 22, session peer
        self.assertTrue(ok)
        text = open(self.env).read()
        self.assertIn("SSH_PORT=22\n", text); self.assertIn("ALLOWED_IP_1=203.0.113.5\n", text)
        self.assertNotIn("sshd lauscht derzeit", out)
        self.assertEqual(stat.S_IMODE(os.stat(self.env).st_mode), 0o600)

    def test_other_port_prints_the_waiting_note(self):
        ok, out = self.run_block(["j", "2222", "192.0.2.10, 198.51.100.7"])
        self.assertTrue(ok)
        self.assertIn("sshd lauscht derzeit auf 22", out)
        self.assertIn("ALLOWED_IP_2=198.51.100.7", open(self.env).read())

    def test_template_is_rendered_when_present(self):
        tpl = os.path.join(self.home, "myodoo-docker", "scripts"); os.makedirs(tpl)
        open(os.path.join(tpl, ".env.example"), "w").write("BACKUP_PASSWORD=x\nSSH_PORT=22\nALLOWED_IP_1=203.0.113.1\n")
        self.run_block(["", "", ""])
        text = open(self.env).read()
        self.assertIn("# BACKUP_PASSWORD=x", text); self.assertIn("ALLOWED_IP_1=203.0.113.5", text)

    def test_network_rejected_then_accepted(self):
        ok, out = self.run_block(["", "", "192.0.2.0/24", "192.0.2.10"])
        self.assertTrue(ok); self.assertIn("keine einzelne IP-Adresse", out)

    def test_three_bad_attempts_write_nothing(self):
        ok, _ = self.run_block(["", "", "x", "y", "z"])
        self.assertFalse(ok); self.assertFalse(os.path.exists(self.env))

    def test_decline_writes_nothing(self):
        ok, out = self.run_block(["n"])
        self.assertFalse(ok); self.assertFalse(os.path.exists(self.env)); self.assertIn("Später", out)

    def test_existing_env_is_shown_not_rewritten(self):
        os.makedirs(os.path.dirname(self.env)); open(self.env, "w").write("SSH_PORT=2200\nALLOWED_IP_1=192.0.2.9\n")
        ok, out = self.run_block([])
        self.assertFalse(ok); self.assertIn("SSH_PORT=2200", out); self.assertIn("192.0.2.9", out)

    def test_first_run_setup_calls_the_block(self):
        source = inspect.getsource(gs.run_first_time_setup)
        self.assertLess(source.index("configure_ssh_access("), source.index("mark_configured()"))

class ResolveHomeTest(unittest.TestCase):
    def test_sudo_su_targets_root(self):
        with mock.patch.dict(os.environ, {"SUDO_USER": "debian", "SUDO_COMMAND": "/usr/bin/su"}):
            self.assertEqual(gs.resolve_install_home(), os.path.expanduser("~"))
    def test_setup_environment_uses_it(self):
        self.assertIn("resolve_install_home()", inspect.getsource(gs.setup_environment))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tests.test_getscripts_firstrun_ssh -v`
Expected: FAIL — names not defined.

- [ ] **Step 3: Implement**

`resolve_install_home()` is the moved code (keep the three `logger.info` lines). `configure_ssh_access()`: existing `.env` → print the current values (parse `SSH_PORT=` and `ALLOWED_IP_\d+=` lines) and return False; else ask the J/n question; port via `_prompt(f"SSH-Port [{default}]: ", str(default))`, invalid → one retry then give up with the later hint; addresses via `_prompt(f"Admin-IPs, kommagetrennt [{', '.join(peers)}]: ", ", ".join(peers))`, up to three attempts, each rejected entry named; empty accepted list → the "Ohne Admin-IP" line, return False; write via `_render_env(template_text, port, ips)` when the template is a file, else `render_minimal_env(port, ips, template_path)`; `_write_env()` False → print "existiert bereits", return False; print the created line; when `port != live_port` and `live_port` is known print the waiting note. Wrap in `try/except (EOFError, KeyboardInterrupt)` → later hint, False.

- [ ] **Step 4: Run the tests and the suite**

Run: `python3 -m unittest tests.test_getscripts_firstrun_ssh -v && uv run --with 'textual>=8,<9' --with pyyaml python -m unittest discover -s tests -q`
Expected: PASS / OK

- [ ] **Step 5: Commit**

```bash
git add getScripts.py tests/test_getscripts_firstrun_ssh.py
git commit -m "[ADD] First-run dialogue asks for the SSH port and the admin addresses

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: `offer_bootstrap()` on a fresh server

**Files:**
- Modify: `getScripts.py` — new `offer_bootstrap()`, `main()` (call after `update_repository()`, before `ensure_base_packages()`), `offer_noconfig_recovery()` (~4626: Docker guard)
- Test: `tests/test_getscripts_fresh_server.py`

**Interfaces:**
- Produces: `BOOTSTRAP_RELATIVE = os.path.join("scripts", "bootstrap.sh")`; `offer_bootstrap(_myhome: str, myodoo_docker: str) -> None`.
- Consumes: `run_command(command, interactive=True, env={"RUN_GETSCRIPTS": "0"})` (Task 2 stripping is irrelevant: the command is `bash <path>`), `record_install`, `status`, `_prompt`.

Exact copy:

```
Frischer Server ohne Docker – Grundausstattung einrichten mit: bash <path>        (non-TTY status line; also the "Später:" line)
Dieser Server hat noch kein Docker. bootstrap.sh richtet die Grundausstattung ein:
  Docker CE (overlay2), nginx, certbot, UFW (installiert, aus), fail2ban,
  automatische Sicherheitsupdates, python3-yaml/python3-dotenv, curl/git, UTF-8-Locale.
Grundausstattung jetzt einrichten? (J/n):                                          default j
```

- [ ] **Step 1: Write the failing tests**

```python
class BootstrapOfferTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(); self.repo = os.path.join(self.home, "myodoo-docker")
        os.makedirs(os.path.join(self.repo, "scripts")); open(os.path.join(self.repo, "scripts", "bootstrap.sh"), "w").write("#!/bin/bash\n")
        gs._install_report.clear()

    def offer(self, which, tty, answers=()):
        with mock.patch.object(gs.shutil, "which", return_value=which), \
             mock.patch.object(gs.sys.stdin, "isatty", return_value=tty), \
             mock.patch.object(gs.sys.stdout, "isatty", return_value=tty), \
             mock.patch("builtins.input", side_effect=list(answers)), \
             mock.patch.object(gs, "run_command") as run, \
             mock.patch.object(gs, "status") as st:
            run.return_value = subprocess.CompletedProcess("bash", 0, "", "")
            gs.offer_bootstrap(self.home, self.repo)
        return run, st

    def test_docker_present_is_silent(self):
        run, st = self.offer("/usr/bin/docker", True)
        run.assert_not_called(); st.assert_not_called()

    def test_no_tty_prints_one_line_and_runs_nothing(self):
        run, st = self.offer(None, False)
        run.assert_not_called()
        self.assertIn("bootstrap.sh", st.call_args.args[0]); self.assertEqual(st.call_count, 1)

    def test_accepted_runs_bootstrap_with_recursion_guard(self):
        run, _ = self.offer(None, True, [""])
        self.assertEqual(run.call_args.args[0], f"bash {os.path.join(self.repo, 'scripts', 'bootstrap.sh')}")
        self.assertTrue(run.call_args.kwargs["interactive"])
        self.assertEqual(run.call_args.kwargs["env"], {"RUN_GETSCRIPTS": "0"})
        self.assertNotIn("timeout", run.call_args.kwargs)
        self.assertIn(("bootstrap", "installed"), [(n, s) for n, s, _ in gs._install_report])

    def test_failed_bootstrap_is_recorded_and_run_continues(self):
        with mock.patch.object(gs.shutil, "which", return_value=None), \
             mock.patch.object(gs.sys.stdin, "isatty", return_value=True), \
             mock.patch.object(gs.sys.stdout, "isatty", return_value=True), \
             mock.patch("builtins.input", return_value=""), \
             mock.patch.object(gs, "run_command", return_value=subprocess.CompletedProcess("bash", 100, "", "")):
            gs.offer_bootstrap(self.home, self.repo)        # must not raise
        self.assertIn(("bootstrap", "failed"), [(n, s) for n, s, _ in gs._install_report])

    def test_declined_is_skipped_with_the_command(self):
        run, _ = self.offer(None, True, ["n"])
        run.assert_not_called()
        entry = [e for e in gs._install_report if e[0] == "bootstrap"][0]
        self.assertEqual(entry[1], "skipped"); self.assertIn("bootstrap.sh", entry[2])

    def test_missing_script_is_silent(self):
        os.remove(os.path.join(self.repo, "scripts", "bootstrap.sh"))
        run, st = self.offer(None, True)
        run.assert_not_called(); st.assert_not_called()

    def test_main_calls_it_before_fish_and_after_the_clone(self):
        source = inspect.getsource(gs.main)
        self.assertLess(source.index("update_repository("), source.index("offer_bootstrap("))
        self.assertLess(source.index("offer_bootstrap("), source.index("install_fish_if_needed("))

class NoconfigDockerGuardTest(unittest.TestCase):
    def test_offer_returns_without_docker(self):
        with mock.patch.object(gs.shutil, "which", return_value=None), \
             mock.patch.object(gs, "_active_noconfig_jobs") as jobs:
            gs.offer_noconfig_recovery(tempfile.mkdtemp())
        jobs.assert_not_called()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tests.test_getscripts_fresh_server -v`
Expected: FAIL — `offer_bootstrap` not defined; the no-config guard test fails on `jobs` being called.

- [ ] **Step 3: Implement `offer_bootstrap()` and the guard**

Guard order: Docker present → return; script missing → return; non-TTY → one `status()` line, return; TTY → print the four copy lines, `_prompt("Grundausstattung jetzt einrichten? (J/n): ", "j")`; `None`/`n` → `record_install("bootstrap", "skipped", f"bash {path}")`, `status("Später: …")`; else `result = run_command(f"bash {path}", interactive=True, env={"RUN_GETSCRIPTS": "0"})`, `record_install("bootstrap", "installed" if result.returncode == 0 else "failed", …)` with detail "Docker, nginx, certbot, UFW, fail2ban …" / f"exit {result.returncode} – see output above". Whole body in `try/except Exception` → `logger.debug`, like the other offers. In `offer_noconfig_recovery()` add `if not shutil.which("docker"): return` after the YAML existence check.

- [ ] **Step 4: Run the tests and the suite**

Run: `uv run --with 'textual>=8,<9' --with pyyaml python -m unittest discover -s tests -q`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add getScripts.py tests/test_getscripts_fresh_server.py
git commit -m "[ADD] getScripts offers and runs bootstrap.sh on a server without Docker

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Fresh-server wording in the delivered scripts

**Files:**
- Modify: `scripts/ownerp_migrate.py:1116-1122` (the unconfigured branch), header `# Version:` line 6, `SCRIPT_VERSION`/`SCRIPT_DATE` lines 86–87
- Modify: `scripts/server-readiness.py` — `check_backup_recency()` (~781), `check_backup_config()` (~882), header line 7, `SCRIPT_VERSION`/`SCRIPT_DATE` lines 82–83
- Test: `tests/test_ownerp_migrate.py` (extend; `self.run_main([...])` pattern), `tests/test_server_readiness.py` (extend; module `sr`)

**Interfaces:**
- Exact copy (English, like the rest of the file): `Docker is not installed — run bootstrap.sh first (ups offers it), then wizup.` replaces the `--from-docker` line only when `shutil.which("docker")` is None.
- Readiness: both checks start with `if not shutil.which("docker"): return _skip("<check_id>", "<title>", "docker not installed")` — titles as the existing findings use (`"Backup recency"`, `"Backup config"`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ownerp_migrate.py
def test_unconfigured_without_docker_points_at_bootstrap(self):
    with mock.patch.object(migrate.shutil, "which", return_value=None):
        _code, output = self.run_main(["--home", self.home, "--quiet"])
    self.assertIn("bootstrap.sh", output); self.assertNotIn("--from-docker", output)

def test_unconfigured_with_docker_keeps_from_docker(self):
    with mock.patch.object(migrate.shutil, "which", return_value="/usr/bin/docker"):
        _code, output = self.run_main(["--home", self.home, "--quiet"])
    self.assertIn("--from-docker", output)

# tests/test_server_readiness.py
def test_backup_checks_skip_without_docker(self):
    with mock.patch.object(sr.shutil, "which", return_value=None):
        for check in (sr.check_backup_config, sr.check_backup_recency):
            finding = check(self.ctx)          # use the fixture the file already builds
            self.assertEqual(finding.status, "SKIP"); self.assertIn("docker not installed", finding.detail)
```

(Adapt attribute names `status`/`detail` to the `Finding` dataclass as `_skip()` fills it.)

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tests.test_ownerp_migrate tests.test_server_readiness -q`
Expected: the three new tests FAIL.

- [ ] **Step 3: Implement, bump versions**

`ownerp_migrate.py` 1.5.1 / 27.10.2026; `server-readiness.py` 1.15.0 / 27.10.2026 (header and constants).

- [ ] **Step 4: Run the suite**

Run: `uv run --with 'textual>=8,<9' --with pyyaml python -m unittest discover -s tests -q`
Expected: OK (`test_delivered_scripts` checks header/constant agreement).

- [ ] **Step 5: Commit**

```bash
git add scripts/ownerp_migrate.py scripts/server-readiness.py tests/test_ownerp_migrate.py tests/test_server_readiness.py
git commit -m "[CHG] A host without Docker is a fresh server, not a broken one (migrate 1.5.1, readiness 1.15.0)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Noise on a fresh host

**Files:**
- Modify: `getScripts.py` — `get_bat_version()`, `check_bat_version()` (~2172–2195), `install_or_update_bat()` (~2225: the "older than latest … manual update" warning), `check_7zip_version()` (~2446–2470: the "7zz command not found" line)
- Test: `tests/test_getscripts_fresh_server.py`

**Interfaces:**
- Produces: module flag `_SEVEN_ZZ_MISSING_REPORTED = False`; the "7zz command not found" line is logged once per run at INFO.

- [ ] **Step 1: Write the failing tests**

```python
class NoiseTest(unittest.TestCase):
    def test_missing_bat_is_not_an_error(self):
        with mock.patch.object(gs, "probe_output", return_value=None), \
             self.assertLogs(gs.logger, level="DEBUG") as logs:
            self.assertIsNone(gs.get_bat_version()); self.assertFalse(gs.check_bat_version())
        self.assertFalse([r for r in logs.records if r.levelno >= logging.WARNING])

    def test_missing_7zz_reported_once_at_info(self):
        gs._SEVEN_ZZ_MISSING_REPORTED = False
        with mock.patch.object(gs.shutil, "which", return_value=None), \
             mock.patch.object(gs.os.path, "isfile", return_value=False), \
             self.assertLogs(gs.logger, level="DEBUG") as logs:
            gs.check_7zip_version(); gs.check_7zip_version(); gs.check_7zip_version()
        hits = [r for r in logs.records if "7zz" in r.getMessage() and "not found" in r.getMessage()]
        self.assertEqual(len(hits), 1); self.assertEqual(hits[0].levelno, logging.INFO)

    def test_bat_older_than_upstream_is_info(self):
        source = inspect.getsource(gs.install_or_update_bat)
        self.assertNotIn('logger.warning(f"Installed bat', source)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tests.test_getscripts_fresh_server.NoiseTest -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

`get_bat_version()`: `probe_output(["batcat", "--version"])` → `None` → `logger.debug("bat (batcat) not installed")`, return None; `check_bat_version()` → `logger.info("bat is not installed")`. `install_or_update_bat()`: the "older than latest … Consider manual update from source" line → `logger.info`. `check_7zip_version()`: when no binary, log INFO once (guard with the flag), return False.

- [ ] **Step 4: Run the tests**

Run: `python3 -m unittest tests.test_getscripts_fresh_server -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add getScripts.py tests/test_getscripts_fresh_server.py
git commit -m "[CHG] A missing bat or 7zz on a fresh host is INFO, not ERROR

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Version, docs, release notes, live check

**Files:**
- Modify: `getScripts.py` — header `# Version:` comment and `SCRIPT_VERSION = "9.34.0"`, `SCRIPT_DATE = "27.10.2026"`
- Modify: `README.md:204-210` and the second one-liner (~455–461): `apt install git python3-requests`, chain ends in `exec fish`; one sentence in the fresh-server section that `getScripts.py` offers `bootstrap.sh` when Docker is missing
- Modify: `docs/usage/01-provisioning.md:145` and `:453` (`exec fish` for a bash session), plus one paragraph each (DE/EN) in the getScripts section: the third first-run block and the bootstrap offer (non-TTY: one line)
- Modify: `docs/INSTALLATION_GUIDE.md` steps 1/2 (DE ~64–77, EN ~228–241): either order works
- Modify: `docs/COMPONENTS.md` (getScripts 9.34.0, ownerp_migrate 1.5.1, server-readiness 1.15.0, features), `usage/AGENT.md` (first-run dialogue has three blocks; `offer_bootstrap` non-TTY line; `RUN_GETSCRIPTS=0`), `RELEASE_NOTES.md` (new top entry `## First Run on a Fresh Server (27.10.2026)` with `### Added` / `### Changed` / `### Fixed`, existing English style)

- [ ] **Step 1: Bump the version and check the headers**

Run: `grep -n "^# Version\|^SCRIPT_VERSION\|^SCRIPT_DATE" getScripts.py scripts/ownerp_migrate.py scripts/server-readiness.py`
Expected: 9.34.0 / 1.5.1 / 1.15.0, all dated 27.10.2026, header and constant equal.

- [ ] **Step 2: Write the docs**

Release-note content, one bullet per item: Fish localisation fix; root without sudo; curl/ca-certificates base step; order of `main()`; first-run SSH block (port, address list, minimal/template `.env`, waiting note); bootstrap offer (trigger, non-TTY line, `RUN_GETSCRIPTS=0`, install-report entry); migrate/readiness without Docker; bat/7zz noise; README `exec fish`.

- [ ] **Step 3: Full suite and public-data scan**

Run: `uv run --with 'textual>=8,<9' --with pyyaml python -m unittest discover -s tests -q && git diff --cached --stat`
Then scan the staged diff for hostnames, IPs outside the documentation ranges and e-mail addresses: `git diff --cached | grep -nE "[0-9]{1,3}(\.[0-9]{1,3}){3}" | grep -vE "192\.0\.2\.|198\.51\.100\.|203\.0\.113\.|127\.0\.0\.1|0\.0\.0\.0|1\.1\.1\.1|8\.8\.8\.8|9\.9\.9\.9|10\.0\.0\.0|172\.16\.0\.0|192\.168\.0\.0"`
Expected: OK; the grep prints nothing.

- [ ] **Step 4: Live check in the fresh container**

```bash
container delete gs-trixie   # only after the operator confirmed — the container is theirs to keep
container run -d --name gs-trixie --mount type=bind,source=/Users/picard/gitbase/myodoo-docker,target=/mnt/repo,readonly debian:13 sleep infinity
container exec gs-trixie bash -c 'export DEBIAN_FRONTEND=noninteractive LANG=de_DE.UTF-8; apt-get update -qq >/dev/null && apt-get install -y -qq git python3 python3-requests >/dev/null 2>&1; cd /root && cp /mnt/repo/getScripts.py . && printf "n\n3\nn\n" | python3 getScripts.py 2>&1 | tail -40; grep -c "No such file or directory: .sudo." /root/getscripts.log'
```

Expected: the install summary lists `fish … installed`, the non-TTY bootstrap line appears (stdin is a pipe, so no prompt), no `Fish is not installed`, the grep prints `0`. The running script is the local working copy; the clone step still pulls the committed branch from GitHub, which is exactly the shape of the README path.

- [ ] **Step 5: Commit**

```bash
git add getScripts.py README.md docs/usage/01-provisioning.md docs/INSTALLATION_GUIDE.md docs/COMPONENTS.md usage/AGENT.md RELEASE_NOTES.md
git commit -m "[CHG] getScripts 9.34.0: first run on a fresh server (docs, release notes)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

Push only on the operator's word: `git push origin 2026 && git push upstream 2026`. The accepted-bootstrap path is then verified by the operator on the demo server (re-run of the 27.10.2026 roll-out).
