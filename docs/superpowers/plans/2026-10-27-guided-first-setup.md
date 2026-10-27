# Guided First Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A fresh server run installs the maintenance cron itself, treats "Docker but no Odoo yet" as normal, and ends with one question that applies the hardening including a safe SSH port change.

**Architecture:** server_hardening.py owns sshd_config and gains a two-port *transition* (marker file next to the `.env`, `--ssh-transition begin|finish|status`, `--no-reboot`); its ufw/fail2ban/ssh modules read the marker through one config patch. getScripts.py orchestrates: installs the cron, detects the fresh state, asks one question, calls `begin`, and finishes the transition on later runs. server-readiness.py and ownerp_migrate.py learn the fresh state.

**Tech Stack:** Python 3 stdlib (+ PyYAML/dotenv already required by server_hardening), unittest.

**Spec:** `docs/superpowers/specs/2026-10-27-guided-first-setup-design.md`

## Global Constraints

- Delivered scripts: system Python 3, `python3-yaml` only; `# Version:` header and `SCRIPT_VERSION`/`SCRIPT_DATE` agree (`tests/test_delivered_scripts.py`). Dates DD.MM.YYYY from the environment (27.10.2026).
- Edit `getScripts.py` itself, never `scripts/lib/`.
- Operator-facing lines of the `ups` run are German; code, comments, docs English. Commands an operator types are fish syntax.
- No real IPs/hostnames anywhere (`upstream` is public); tests use 192.0.2.x / 198.51.100.x / 203.0.113.x.
- Suite: `uv run --with 'textual>=8,<9' --with pyyaml python -m unittest discover -s tests -q` must stay green (1457 tests before this plan).
- Commits per task, `[ADD]/[CHG]/[FIX]`, `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. No push.
- Versions: getScripts 9.35.0, server_hardening 1.12.0, server-readiness 1.16.0, ownerp_migrate 1.6.0.

## Review Focus

1. `begin` on a host where sshd already listens on OLD and NEW (half-done manual change): must not refuse and must not add a third Port line. → Task 2 test `test_begin_accepts_sshd_already_on_both_ports`.
2. `finish` when the only session on NEW is from an address not in `ALLOWED_IP_n`: the old port must stay open. → Task 2 test `test_finish_ignores_unlisted_peer`.
3. `.env` SSH_PORT edited while a transition is pending: audit reports the conflict as fail, `begin`/`finish` refuse. → Task 1 test `test_marker_conflicting_with_env_is_a_fail_finding`, Task 2 `test_begin_refuses_marker_env_mismatch`.
4. The question on a host with only muted areas pending: not asked at all. → Task 6 test `test_only_muted_areas_asks_nothing`.
5. A configured host whose containers are all gone (YAML present, zero containers): readiness keeps FAIL, no fresh-server line. → Task 5 test `test_config_present_zero_containers_stays_fail`, Task 4 test `test_not_fresh_when_yaml_exists`.

---

### Task 1: server_hardening.py — transition marker and transition-aware modules

**Files:**
- Modify: `scripts/server_hardening.py` (header `# Version:` + `SCRIPT_VERSION = "1.12.0"`, date; `audit_ssh`, `main`)
- Test: `tests/test_server_hardening_transition.py` (new)

**Interfaces:**
- Produces: `TRANSITION_MARKER = CENTRAL_DIR / "ssh-transition"`; `read_transition() -> Optional[Tuple[int, int]]` (file holds `"<old> <new>"`, None when missing or malformed); `write_transition(old: int, new: int) -> None` (0600); `clear_transition() -> None`; `_rewrite_ports(content: str, ports: List[int]) -> str` (pure: every active or commented `Port` line removed, the `Port` lines for `ports` inserted where the first one was, appended when there was none); `expected_ssh_ports(config) -> List[int]`; `apply_transition_to_config(config, transition, allowed_ips) -> None` (sets `fail2ban.jails.sshd.port = "OLD,NEW"` and appends `{"port": OLD, "allowed_ips": <copy of the SSH_PORT entry's>, "comment": "ssh-transition"}` to `ufw.restricted_ports`); argparse flag `--no-reboot` → `config["auto_updates"]["auto_reboot"] = False`.
- Consumes: existing `audit_ssh`, `backup_file`, `run`, `inject_allowed_ips`, `CENTRAL_DIR`.

- [ ] **Step 1: Write the failing tests** (`tests/test_server_hardening_transition.py`, class `MarkerTest`, `RewritePortsTest`, `ConfigPatchTest`, `AuditSshTransitionTest`, `NoRebootTest`): load the module with `CENTRAL_DIR` patched to a temp dir; tests: `test_read_missing_marker_is_none`, `test_write_then_read_roundtrip`, `test_malformed_marker_is_none`, `test_rewrite_replaces_single_port_with_two`, `test_rewrite_removes_commented_port_lines`, `test_rewrite_appends_when_no_port_line`, `test_rewrite_keeps_other_directives_in_place`, `test_patch_sets_jail_port_and_transitional_ufw_rule`, `test_expected_ports_without_marker_is_config_port`, `test_expected_ports_with_marker_is_old_and_new`, `test_marker_conflicting_with_env_is_a_fail_finding` (marker `22 2200`, config port 16667 → `audit_ssh` records a fail whose text contains both `2200` and `16667`), `test_audit_ok_when_sshd_config_has_both_ports_during_transition` (sshd_config temp text with `Port 22` and `Port 16667`, marker `22 16667` → no Port fail, one warn `Portwechsel läuft: anmelden über 16667, dann ups`), `test_apply_during_transition_writes_two_port_lines`, `test_no_reboot_flag_forces_auto_reboot_false` (patch `module_functions` to capture the config `audit_auto_updates` receives).
- [ ] **Step 2: Run them** — `uv run --with pyyaml python -m unittest tests.test_server_hardening_transition -q` — Expected: FAIL/ERROR (names missing).
- [ ] **Step 3: Implement.** `audit_ssh` reads `Path("/etc/ssh/sshd_config")` via a module constant `SSHD_CONFIG` (patchable); collects `current_ports = [int(p) for p in re.findall(r"^\s*Port\s+(\d+)", effective, re.M)] or [22]`; compares `set(current_ports)` with `set(expected_ssh_ports(config))`; with a marker emits the warn line first; on mismatch `changes_needed.append(("Port", expected))` and the apply path uses `_rewrite_ports` for the Port entry and the existing regex for the other keys. In `main()`, after `inject_allowed_ips`: `transition = read_transition(); if transition: apply_transition_to_config(config, transition, allowed_ips)`; `--no-reboot` handled right after config load.
- [ ] **Step 4: Run the new tests and `tests/test_server_hardening.py`** — Expected: PASS.
- [ ] **Step 5: Commit** `[ADD] server_hardening 1.12.0: SSH transition marker, two-port sshd config, --no-reboot`.

### Task 2: server_hardening.py — `--ssh-transition begin|finish|status`

**Files:**
- Modify: `scripts/server_hardening.py` (`main`, new functions)
- Test: `tests/test_server_hardening_transition.py` (classes `BeginTest`, `FinishTest`, `StatusTest`)

**Interfaces:**
- Produces: `ssh_transition_status(config) -> str` prints/returns `none` | `pending OLD -> NEW`; `ssh_transition_begin(config, allowed_ips) -> int` (0 ok / 0 no-op when OLD == NEW / 1 refused or failed, reason printed with `fail()`); `ssh_transition_finish(config, allowed_ips) -> int` prints exactly one stdout line: `closed OLD -> NEW` | `pending OLD -> NEW` | `none`, exit 0 (1 only on a failed rewrite). Helpers: `_sshd_listen_ports() -> List[int]` (`sshd -T`), `_established_peers(port) -> Optional[List[str]]` (`ss -tnH state established ( sport = :PORT )`, IPv4-mapped reduced), `_dropin_port_files() -> List[Path]`, `_port_in_use_by_other(port) -> bool` (`ss -tlnH sport = :PORT` non-empty while sshd does not list it), `_ssh_banner_ok(host, port, timeout=5) -> bool`, `_switch_off_ssh_socket() -> None`.
- `begin` order: refuse on marker/env mismatch, on no `allowed_ips`, on unreadable sshd ports, on a drop-in `Port` (names the file), on NEW in use by another process, on an established peer outside `allowed_ips`; no-op when `set(listen) == {NEW}`; if `ssh.socket` active → switch; rewrite sshd_config to `[OLD, NEW]` (unless sshd already lists both), `sshd -t -f tmp`, backup, replace, `systemctl reload ssh`, verify `sshd -T` lists both and banner on `127.0.0.1` (or first `ListenAddress`) → on any failure restore the backup, reload, return 1; `write_transition`; `apply_transition_to_config`; run `audit_ufw`, `audit_fail2ban`, `audit_ssh` with `apply=True, force=True`; return 0.
- `finish`: `read_transition()` None → `none`; peers on NEW ∩ allowed empty → `pending`; else rewrite to `[NEW]`, validate, replace, reload, `ufw delete allow from <ip> to any port OLD proto tcp` per allowed ip, `clear_transition()`, print `closed`.
- Consumes: Task 1 helpers.

- [ ] **Step 1: Write the failing tests** with `run`, `subprocess.run`, `socket.create_connection`, `SSHD_CONFIG`, `CENTRAL_DIR` patched; a recorder captures every `run()` command. Tests: `test_status_none_and_pending`, `test_begin_noop_when_only_new_port` (no run calls, exit 0, no marker), `test_begin_refuses_without_allowed_ips`, `test_begin_refuses_dropin_port_and_names_file`, `test_begin_refuses_port_in_use`, `test_begin_refuses_unlisted_peer`, `test_begin_refuses_marker_env_mismatch`, `test_begin_switches_off_ssh_socket_when_active`, `test_begin_writes_both_ports_marker_and_applies_ufw_fail2ban_ssh` (order of run calls: `sshd -t`, `systemctl reload ssh`, then ufw/fail2ban/ssh module functions called with apply=True — patch `module_functions`), `test_begin_accepts_sshd_already_on_both_ports`, `test_begin_restores_backup_when_banner_fails` (marker absent afterwards, sshd_config content equals original), `test_finish_none_without_marker`, `test_finish_pending_without_peer_on_new`, `test_finish_ignores_unlisted_peer`, `test_finish_closes_old_port_and_deletes_rules` (sshd_config ends with a single `Port 16667`, two `ufw delete allow from … port 22 proto tcp` calls for two IPs, marker gone, stdout `closed 22 -> 16667`).
- [ ] **Step 2: Run** — Expected: FAIL (functions missing).
- [ ] **Step 3: Implement** the functions and the argparse: `--ssh-transition {begin,finish,status}` (mutually exclusive with `--apply`/`--json`; `status` needs no root). In `main()` after config/env load: dispatch and `sys.exit(code)`.
- [ ] **Step 4: Run the file and the full suite** — Expected: PASS.
- [ ] **Step 5: Commit** `[ADD] server_hardening: --ssh-transition begin/finish/status performs the port change safely`.

### Task 3: getScripts.py — install the maintenance cron during the run

**Files:**
- Modify: `getScripts.py` (new `ensure_maintenance_cron`, `main()` order; `SCRIPT_VERSION = "9.35.0"`, `SCRIPT_DATE = "27.10.2026"`)
- Test: `tests/test_getscripts_guided_setup.py` (new, class `MaintenanceCronTest`, `MainOrderTest`)

**Interfaces:**
- Produces: `MAINTENANCE_CRON_PATH = "/etc/cron.d/myodoo-maintenance"`; `ensure_maintenance_cron(_myhome: str) -> None`.
- Consumes: `run_command`, `record_install`, `shutil.which`.

- [ ] **Step 1: Tests**: `test_silent_without_docker` (no run_command, no record), `test_silent_when_cron_file_exists`, `test_runs_script_and_records_installed` (run_command called with `bash <home>/setup-maintenance-cron.sh`, record_install("maintenance cron", "installed", …)), `test_records_failed_with_rerun_hint` (returncode 1 → "failed", detail contains the script path), `test_silent_when_script_missing`; `MainOrderTest.test_cron_runs_after_install_packages_before_migrate` (source positions of `run_install_packages(`, `ensure_maintenance_cron(_myhome)`, `migrate_legacy_csv(_myhome)` inside `main`).
- [ ] **Step 2: Run** — Expected: FAIL. **Step 3: Implement.** **Step 4: Run file + suite** — PASS.
- [ ] **Step 5: Commit** `[ADD] getScripts installs the maintenance cron itself on a host with Docker`.

### Task 4: Fresh-server mode (getScripts + ownerp_migrate 1.6.0)

**Files:**
- Modify: `getScripts.py` (`is_fresh_server`, `offer_noconfig_recovery`, `main()` next-step line), `scripts/ownerp_migrate.py` (header 1.6.0, `main` no-CSV branch, new `_container_count() -> Optional[int]` via `docker ps -aq`)
- Test: `tests/test_getscripts_guided_setup.py` (class `FreshServerTest`), `tests/test_ownerp_migrate.py` (class `FreshServerTest` extended)

**Interfaces:**
- Produces: `is_fresh_server(_myhome: str) -> bool` (docker binary, `_any_containers() is False`, both YAMLs absent); status line text `Noch keine Odoo-Instanz. Nächster Schritt: wizup`.

- [ ] **Step 1: Tests**: `test_fresh_when_docker_zero_containers_no_yaml`, `test_not_fresh_when_yaml_exists`, `test_not_fresh_when_docker_unreadable` (`_any_containers` → None), `test_not_fresh_without_docker`, `test_noconfig_offer_silent_on_fresh_server` (no stdout, no prompt), `test_main_prints_next_step_after_readiness` (source order: `print_readiness_report(_myhome)` then `is_fresh_server(` then `"Script completed successfully!"`); migrate: `test_zero_containers_names_wizup` (docker present, `_container_count` → 0, not quiet → output contains `wizup`, not `--from-docker`), `test_zero_containers_quiet_prints_nothing`, `test_containers_present_keeps_from_docker_hint_under_quiet`.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run + suite** — PASS.
- [ ] **Step 5: Commit** `[CHG] A host with Docker and no Odoo yet is a fresh server: no recovery dialog, next step wizup (migrate 1.6.0)`.

### Task 5: server-readiness.py 1.16.0 — fresh state and transition

**Files:**
- Modify: `scripts/server-readiness.py` (header/version; `check_backup_config`, `check_update_config`, `check_backup_recency`, `_check_backup_recency_from_log` fix text)
- Test: `tests/test_server_readiness.py` (class `FreshServerSkipsTest`, `TransitionWarnTest`)

- [ ] **Step 1: Tests**: `test_backup_config_skips_on_zero_containers_without_file` (detail `no Odoo instance yet — wizup`), `test_update_config_skips_on_zero_containers_without_file`, `test_backup_recency_skips_on_zero_containers_without_file`, `test_config_present_zero_containers_stays_fail` (file present but names a missing container → FAIL as today), `test_recency_log_missing_fix_names_wizbk_when_cron_installed`, `test_ssh_transition_pending_is_warn_with_the_audit_line` (audit JSON: ssh area status `warn`, first finding `Portwechsel läuft: anmelden über 16667, dann ups` → WARN, detail equals that line without `(+N more)` when it is the only finding).
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement** (the "not found" error string from `_load_config` is the trigger; `_container_count() == 0` required). **Step 4: Run + suite** — PASS.
- [ ] **Step 5: Commit** `[CHG] server-readiness 1.16.0: missing configs on a host without an Odoo instance are SKIP, not FAIL`.

### Task 6: getScripts.py — the single hardening question and the transition

**Files:**
- Modify: `getScripts.py` (`offer_security_hardening`, `_apply_hardening`, `_lockout_blockers`, new `_hardening_question`, new `finish_ssh_transition`, `configure_ssh_access` texts, delete `PORT_CHANGE_STEPS`, `_ssh_socket_active`, `_print_hardening_commands` usage, `_mute_hardening_area` usage; `main()` calls `finish_ssh_transition(_myhome)` right after `run_install_packages()`)
- Test: `tests/test_getscripts_guided_setup.py` (classes `QuestionTextTest`, `OfferTest`, `ApplyTest`, `FinishTest`, `BlockersTest`), adjust `tests/test_getscripts_security_offer.py` (menu/blocker tests), `tests/test_getscripts_firstrun_ssh.py` (texts)

**Interfaces:**
- Produces: `_hardening_question(pending: List[dict], env: Dict[str,str], listen: List[int]) -> str` (pure; header `Sicherheits-Härtung: <titles> weichen ab.`; "Anwenden heißt:" clauses: `SSH-Port NEW statt OLD` only when `_is_port_change`, `Zugriff nur von <ips>` when ufw or ssh pending, `Firewall an`, `fail2ban`, `automatische Sicherheitsupdates (ohne nächtlichen Neustart)` per pending module; the Port-22-stays-open sentence and the provider-firewall sentence only on a port change; closing `Diese Sitzung offen lassen.`); prompt `Härtung jetzt anwenden? (j/N): ` default `n`; later line `Später: ups fragt beim nächsten Mal erneut · Details: chk · Befehle: python3 ~/server_hardening.py --help · Bereich stummschalten: python3 ~/ownerp_mute.py <id> · Nächtlicher Neustart bei Updates: python3 ~/server_hardening.py --apply -m auto_updates`.
- `_lockout_blockers(env, listen_ports, peers) -> List[str]` (drops `socket_active`; keeps no-IPs, no SSH_PORT, unreadable ports, unreadable peers, unlisted peer).
- `_apply_hardening(_myhome, script, pending)`: blockers → print `Härtung NICHT angewendet:` + reasons, `record_install("hardening", "failed", reasons[0])`, return. Port change → `run_command(f"{py} {script} --ssh-transition begin", interactive=True)`; rc ≠ 0 → record failed `begin scheiterte – ups fragt beim nächsten Mal erneut`, return. Else guarded modules via `--apply -f -m ufw fail2ban ssh` as before. Then harmless (with `--no-reboot` appended by `_hardening_command` when `auto_updates` in modules; no reboot question), docker (restart logic unchanged), aide. Ends with `record_install("hardening", "installed", ", ".join(titles))`.
- `finish_ssh_transition(_myhome) -> None`: marker at `<home>/.config/myodoo-docker/ssh-transition` absent or script missing → return; runs `--ssh-transition finish` captured; stdout `closed OLD -> NEW` → `record_install("ssh port", "updated", f"{OLD} geschlossen, sshd lauscht auf {NEW}")`; `pending` → `record_install("ssh port", "ok", f"Portwechsel läuft – anmelden über {NEW}, dann ups")`; other/rc≠0 → `"failed"`.
- `configure_ssh_access`: replace the two sentences per spec component 4.

- [ ] **Step 1: Tests**: `test_question_lists_ips_and_port_change`, `test_question_without_port_change_has_no_port_sentence`, `test_question_updates_clause_says_without_reboot`, `test_only_muted_areas_asks_nothing`, `test_j_with_port_change_runs_begin_first` (recorded commands: `--ssh-transition begin` before any `--apply`), `test_j_without_port_change_runs_apply_guarded`, `test_other_answer_prints_later_line_with_four_hints`, `test_begin_failure_records_failed_and_stops`, `test_auto_updates_gets_no_reboot_and_no_question`, `test_blockers_no_longer_mention_port_change_or_socket`, `test_unlisted_peer_still_blocks`, `test_finish_records_updated_on_closed`, `test_finish_records_ok_on_pending`, `test_finish_silent_without_marker`, `test_main_calls_finish_after_install_packages`, `test_port_change_steps_gone` (`not hasattr(gs, "PORT_CHANGE_STEPS")`), `test_ssh_block_text_names_the_question_at_the_end`.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement**; update the existing tests that assert the menu or the dropped blockers. **Step 4: Run + full suite** — PASS.
- [ ] **Step 5: Commit** `[CHG] getScripts 9.35.0: one question applies the hardening, the SSH port change included`.

### Task 7: Documentation, release notes, container smoke test

**Files:**
- Modify: `docs/usage/01-provisioning.md`, `docs/INSTALLATION_GUIDE.md`, `docs/COMPONENTS.md`, `usage/AGENT.md`, `RELEASE_NOTES.md`, `ReadMe.md` (only if the six steps are mentioned), design doc (settled details: transitional rules are deleted by address+port, no ufw comment; `begin` applies ufw/fail2ban/ssh, getScripts applies the rest).

- [ ] **Step 1:** grep the docs for `PORT_CHANGE`, `sechs Schritte`, `six steps`, `nie selbst`, `never changes the port`, `setup-maintenance-cron.sh` (as an operator step), `--from-docker` on fresh hosts; replace per spec component 6.
- [ ] **Step 2:** RELEASE_NOTES top entry `Guided First Setup (27.10.2026)` with Added/Changed/Fixed per script and version.
- [ ] **Step 3:** `tests/test_delivered_scripts.py` + full suite — PASS.
- [ ] **Step 4:** Smoke test in `gs-trixie-2` (no systemd): `python3 getScripts.py --help`, `python3 scripts/server_hardening.py --ssh-transition status` prints `none`, `python3 scripts/server-readiness.py --brief` runs. Expected: no traceback.
- [ ] **Step 5: Commit** `[CHG] Docs and release notes for the guided first setup`.
