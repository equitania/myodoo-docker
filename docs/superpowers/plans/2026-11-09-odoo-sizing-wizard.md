# Odoo Sizing Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One shared calculation sets Odoo workers, memory limits, connection counts and PostgreSQL memory per host hardware and per instance role, persisted as a `sizing` block in `docker2update.yaml` and applied by `doup`.

**Architecture:** A new delivered module `scripts/ownerp_sizing.py` holds the pure calculation, the state file, the `odoo.conf` / `postgresql.conf` writers (siblings of `odoo_build_cache.ensure_odoo_conf_current`: allow-list, `.bak`, regression gate) and the `dosize` CLI. `update_docker_odoo.py`, `ownerp_wizard.py`/`ownerp_console.py`, `server-readiness.py` and `pg-local-deploy.sh` are thin callers, so every tool sees the same numbers. Nothing aborts an update: sizing problems become `ERROR`/`WARNING` lines and exit status 1.

**Tech Stack:** Python 3 stdlib (+ `python3-yaml` where the repo already needs it), `unittest`, bash for `pg-local-deploy.sh`, fish for aliases.

**Spec:** `docs/superpowers/specs/2026-11-09-odoo-sizing-wizard-design.md` (authoritative). Executors read the spec and this plan.

**Commits:** Commit steps are local commits on the worktree branch `sizing-wizard` (merged into 2026 and pushed only on the captain's command). Executors commit per task. Every commit message ends with the two trailer lines under Global Constraints.

## Global Constraints

- Delivered scripts run on system Python 3 + `python3-yaml` only; no new dependencies. (Spec: "delivered scripts run on system Python 3 + `python3-yaml` only, with no new dependencies".)
- Version header and `SCRIPT_VERSION`/`SCRIPT_DATE` must agree in every touched script (`tests/test_delivered_scripts.py` enforces it); date for all bumps: `09.11.2026`.
- Tests run with: `uv run --with 'textual>=8,<9' --with pyyaml python -m unittest discover -s tests -q` (single modules: `... python -m unittest tests.<module> -q`). A plain `python3 -m unittest` silently skips the Textual tests.
- Public GitHub mirror (`upstream`): no customer names, hosts, IPs or domains in code, tests, comments, docs or release notes. Use `live-odoo`, `live-db`, `test-odoo`, `test-db`, `192.0.2.x`.
- Every command an operator is meant to type is fish syntax (no `VAR=x cmd`, no heredocs, no `$?`).
- Operator text is English (Captain's decision 09.11.2026, overriding the spec's earlier "German"): every sentence produced by `ownerp_sizing.py` (reasons, deviation lines, report, review prompts, wizard questions) is English, matching the surrounding `doup`/`chk`/`wizup` output. Technical keys stay as in the config files.
- The sizing never refuses for lack of RAM (Captain's decision 09.11.2026): when even the minimal staffing does not fit, the minimal staffing is computed, applied like any other plan, and carried by `plan.over_budget = True` plus a warning naming need and budget. `doup` prints it as a `WARNING` (not an error, exit status unaffected), `chk` as WARN, `dosize`/`wizup`/`pg-local-deploy` show it before confirming.
- `scripts/lib/` is dead code; never edit it.
- Commit subjects are prefixed `[ADD]`, `[CHG]` or `[FIX]`. Every commit message ends with these two lines:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01BJ4ETV9TvyZQYFBvADT7Rb
  ```
- `doup` never aborts because of sizing; a sizing failure (unreadable state or conf, PostgreSQL rollback) is an `ERROR`/`WARNING` line (run output + run log), the update continues with the unchanged config, and the run exits 1.
- Pinned numbers (spec values, exact): official guide 325 MiB per process; floor 629145600 / 1677721600 bytes, cap 2147483648 / 2684354560 bytes for live `limit_memory_soft`/`hard`; test 512 MiB / 1200 MiB; demo 384 MiB / 1024 MiB; `db_maxconn` 16; `max_connections = max(100, (processes + gevent) × 16 + 20)`; OS reserve 1 GiB + 10 % RAM; PostgreSQL 25 % RAM split by weight live 3 / test 1 / demo 1.

## Review Focus

Failure modes the spec implies but no spec sentence tests; each has a test in the named task.

1. A blockless instance whose `odoo.conf` says `workers = 0`, `False`, is empty or missing: counts as one process (threaded) or the shipped defaults, never raises (Task 1, Task 5).
2. `odoo_version` as `18`, `"18"`, `18.0`, empty or `20` (no `Dockerfiles/v20-odoo`): right key set, no crash, v20 behaves like v19 (Task 1).
3. `postgresql.conf` with a setting twice or mixed units (`4GB` vs `4096MB`): last wins, no false "hand edit" (Task 4).
4. Parked (`active: false`) entries consume no budget unless named with `-s` (Task 1, Task 5).
5. Host facts unreadable (no `/proc/meminfo`) or `ownerp_sizing.py` missing/unimportable on a host with a `sizing` block: `doup` reports an ERROR and updates anyway; `chk` SKIPs; neither raises (Task 5, Task 8).

## File Structure

- Create `scripts/ownerp_sizing.py` (v1.0.0): sections in order: constants, hardware, parsing, calculation, state + decisions, `odoo.conf` writer, `postgresql.conf` writer, report/review/CLI. One module, as the spec suggests; it is imported by four callers and called as a CLI by one.
- Modify `scripts/ownerp_validate.py` (schema), `scripts/update_docker_odoo.py` (steps + exit status), `scripts/ownerp_wizard.py` + `scripts/ownerp_console.py` (questions), `scripts/server-readiness.py` (check), `scripts/pg-local-deploy.sh` (role prompt), `getScripts.py`, `fish/conf.d/33-aliases-backup.fish`, `fish/functions/linux/ownerp-help.fish`, `scripts/docker2update.yaml`, docs.
- Create tests: `tests/test_ownerp_sizing.py` (calculation, tasks 1), `tests/test_ownerp_sizing_apply.py` (state and writers, tasks 3-4), `tests/test_ownerp_sizing_cli.py` (task 6); extend existing test files elsewhere.

---

### Task 1: Calculation core

**Files:**
- Create: `scripts/ownerp_sizing.py` (header: shebang `#!/usr/bin/python3`, `# Version: 1.0.0`, `# Date: 09.11.2026`, `SCRIPT_VERSION = "1.0.0"`, `SCRIPT_DATE = "09.11.2026"`; `chmod +x`)
- Test: `tests/test_ownerp_sizing.py`

**Interfaces:**
- Produces (later tasks import these; names are fixed):
  - `MIB = 1048576`; `class SizingError(Exception)`
  - `@dataclass(frozen=True) Hardware(cpus: int, ram_mib: int)`; `probe_hardware(root: str = "/") -> Hardware` (reads `<root>/proc/cpuinfo` `processor` lines and `<root>/proc/meminfo` `MemTotal`; raises `SizingError` when unreadable)
  - `odoo_major(version) -> Optional[int]`; `odoo_keys(version) -> Tuple[str, ...]`
  - `parse_conf_values(text: str) -> Dict[str, str]` (`key = value` lines of an `odoo.conf`, comments and `[sections]` skipped; empty value kept as `""`)
  - `@dataclass Instance(name, version: Optional[int], role: Optional[str], users: Optional[int], overrides: Dict[str, int], db_container: Optional[str], build_dir: str, conf: Dict[str, str])`
  - `OVERRIDE_KEYS` = `("workers", "max_cron_threads", "limit_memory_soft_mb", "limit_memory_hard_mb", "db_maxconn", "pg_shared_buffers_mb", "pg_max_connections")`
  - `instances_from_config(containers: List[dict], selected: Optional[str] = None, read_text=read_text) -> List[Instance]` (skips `active: false` unless `container_name == selected`)
  - `@dataclass InstanceResult(name, role: Optional[str], sized: bool, workers: int, cron: int, processes: int, odoo: Dict[str, str], pg: Dict[str, str], reasons: List[str], warnings: List[str])` (`processes` = workers + cron + gevent)
  - `@dataclass Plan(hardware: Hardware, budget_mib: int, need_mib: int, pg_total_mib: int, results: List[InstanceResult], over_budget: bool, warnings: List[str])`
  - `compute_plan(hw: Hardware, instances: List[Instance]) -> Plan`
  - `pg_base_profile(hw: Hardware) -> str` (`"2cpu4gb"`, `"2cpu8gb"`, `"4cpu16gb"`, `"8cpu32gb"`)

**Calculation (integer MiB, floor everywhere) — the algorithm the tests pin:**

```
P        = 2*cpus + 1
reserve  = 1024 + ram//10 ; pg_total = ram//4 ; budget = ram - reserve - pg_total
cron_live = 2 if cpus >= 8 else 1
fixed:   test -> (workers 2, cron 1, soft 512, hard 1200) ; demo -> (1, 1, 384, 1024)
others   = sum(workers+cron) of every non-live instance (blockless: from its conf; workers=0 or
           unparseable -> 1 process / shipped defaults 3 + 2)
n_live   = number of live instances
workers  = max(2, (P - others - n_live*cron_live) // n_live)         # per live instance
users u  : workers = max(2, min(workers, ceil(u/6))) ; if ceil(u/6) > host workers -> warning
need(w,c)= (w + c + 1) * 325                                            # +1 = gevent process
fit      : while sum(need) > budget and the largest live workers > 2: reduce that live by 1
           still > budget -> every non-live instance with workers > 1 drops to 1 worker (minimal staffing)
           still > budget -> plan.over_budget = True, warning "over budget: minimal staffing needs <need> MiB, budget <budget> MiB"
                       (the plan is still complete and applied; there is no refusal)
live soft= clamp(live_share // (n_live*(w + cron + 1)), 600, 2048) MiB, live_share = budget - need(non-live)
           (bytes: floor/cap values from Global Constraints)
live hard= clamp(soft*5//4, 1600, 2560) MiB
override : keys of Instance.overrides replace the computed value (MB -> bytes for memory); an override that makes
           sum(need) > budget -> plan.warnings "Override ... exceeds the RAM budget" and over_budget = True
warning  : sum(workers+cron) > P -> plan.warnings "<n> processes > <P> (2 x CPU + 1)"
PG       : share = pg_total * weight // sum(weights) (blockless instance weight 1)
           processes_i = workers + cron + 1 ; max_connections = max(100, processes_i*16 + 20)
           shared_buffers = share ; effective_cache_size = 3*share ;
           work_mem = clamp(share // (max_connections*2), 4, 64) ; maintenance_work_mem = clamp(share//8, 64, 1024)
           values are strings with unit "MB" (max_connections without unit)
Odoo keys: workers, max_cron_threads, limit_memory_soft, limit_memory_hard, db_maxconn ("16"); version >= 18 adds
           limit_memory_soft_gevent, limit_memory_hard_gevent (= soft/hard), db_maxconn_gevent ("16");
           version 19 keeps only db_maxconn_gevent of those three (the v19 template has no gevent memory keys);
           versions above the table (20) use the highest entry <= version; unknown/None -> base five.
reasons  : English, one per number, e.g. "5 workers: 4 CPU -> 9 processes, other instances use 3, cron 1"
```

- [ ] **Step 1: Write the failing tests** in `tests/test_ownerp_sizing.py` (stdlib only; `sys.path.insert` on `scripts/`, plain `import ownerp_sizing as sz`). Helper `inst(name, role, version=18, users=None, overrides=None, conf=None)` and `hw(cpus, gib) = sz.Hardware(cpus, gib*1024)`. Tests (names and assertions):

```python
def test_four_cpu_16gib_live_and_test(self):
    p = sz.compute_plan(hw(4, 16), [inst("live-odoo", "live"), inst("test-odoo", "test")])
    live, test = p.results
    self.assertEqual((p.budget_mib, p.need_mib, p.pg_total_mib), (9626, 3575, 4096))
    self.assertFalse(p.over_budget)
    self.assertEqual((live.workers, live.cron, live.processes), (5, 1, 7))
    self.assertEqual(live.odoo["workers"], "5"); self.assertEqual(live.odoo["max_cron_threads"], "1")
    self.assertEqual(live.odoo["limit_memory_soft"], str(1189 * sz.MIB))
    self.assertEqual(live.odoo["limit_memory_hard"], str(1600 * sz.MIB))
    self.assertEqual(live.odoo["db_maxconn"], "16")
    self.assertEqual(live.pg, {"shared_buffers": "3072MB", "effective_cache_size": "9216MB",
        "max_connections": "132", "work_mem": "11MB", "maintenance_work_mem": "384MB"})
    self.assertEqual((test.workers, test.cron), (2, 1))
    self.assertEqual(test.odoo["limit_memory_soft"], str(512 * sz.MIB))
    self.assertEqual(test.odoo["limit_memory_hard"], str(1200 * sz.MIB))
    self.assertEqual(test.pg, {"shared_buffers": "1024MB", "effective_cache_size": "3072MB",
        "max_connections": "100", "work_mem": "5MB", "maintenance_work_mem": "128MB"})
    self.assertTrue(any("5 workers: 4 CPU -> 9 processes" in r and "3" in r for r in live.reasons))

def test_two_cpu_4gib_live_and_test_gets_minimal_staffing_and_a_warning(self):
    p = sz.compute_plan(hw(2, 4), [inst("live-odoo", "live"), inst("test-odoo", "test")])
    live, test = p.results
    self.assertTrue(p.over_budget)
    self.assertEqual((p.budget_mib, p.need_mib), (1639, 2275))
    self.assertEqual((live.workers, live.cron, test.workers, test.cron), (2, 1, 1, 1))
    self.assertEqual((live.odoo["limit_memory_soft"], live.odoo["limit_memory_hard"]), ("629145600", "1677721600"))  # floor
    self.assertTrue(any("over budget" in w and "2275" in w and "1639" in w for w in p.warnings))

def test_two_cpu_4gib_live_only_squeezes_workers_and_fits(self):
    p = sz.compute_plan(hw(2, 4), [inst("live-odoo", "live")])
    self.assertFalse(p.over_budget); r = p.results[0]
    self.assertEqual(r.workers, 3); self.assertEqual(p.need_mib, 1625)
    self.assertEqual((r.odoo["limit_memory_soft"], r.odoo["limit_memory_hard"]), ("629145600", "1677721600"))  # floor

def test_eight_cpu_32gib_live_and_test(self):
    p = sz.compute_plan(hw(8, 32), [inst("live-odoo", "live"), inst("test-odoo", "test")])
    live = p.results[0]
    self.assertEqual((live.workers, live.cron), (12, 2)); self.assertEqual(p.need_mib, 6175)
    self.assertEqual(live.odoo["limit_memory_soft"], str(1265 * sz.MIB))
    self.assertEqual(live.pg["max_connections"], "260")

def test_live_limits_reach_the_cap_on_a_large_host(self):
    p = sz.compute_plan(hw(16, 128), [inst("live-odoo", "live")]); r = p.results[0]
    self.assertEqual(r.workers, 31)
    self.assertEqual((r.odoo["limit_memory_soft"], r.odoo["limit_memory_hard"]), ("2147483648", "2684354560"))

def test_users_cap_workers_and_warn_when_the_host_is_smaller(self):
    # 4 CPU / 16 GiB: users=12 -> 2 workers, soft capped at 2048 MiB; users=4 -> still 2 (minimum);
    # users=60 -> 5 workers and a warning "60 users need 10 workers, the host allows 5"
def test_two_cpu_8gib_exceeds_the_cpu_rule_with_a_warning(self):
    # live+test: live 2 workers (minimum), limits 750/1600 MiB, not over budget, plan.warnings has "6 processes > 5"
def test_demo_and_test_and_live_share_the_budget(self):
    # 4/16 live+test+demo -> live 3 workers, soft 1470 MiB, hard 1837 MiB, live pg shared_buffers "2457MB"
def test_blockless_instance_counts_with_its_conf(self):
    # 4/16, live + blockless conf {"workers":"3","max_cron_threads":"2"} -> live 3 workers; need_mib 3575; blockless result .sized False
def test_blockless_odd_conf_values_never_raise(self):
    # conf {"workers":"0"} counts as 1 process; {"workers":"False"} / {} count as the shipped 3 + 2
def test_two_live_instances_split_the_remainder(self):   # 4/16 live+live -> 3 workers each, need 3250
def test_an_override_wins_and_a_budget_breaking_override_only_warns(self):
    # overrides {"workers": 8} -> "8"; {"workers": 40} -> "40", plan.over_budget True, a warning containing "Override"
def test_odoo_keys_per_version(self):
    # 16: the five base keys; 18: + the three *_gevent keys; 19: base + "db_maxconn_gevent" only;
    # 20 == 19; 18.0 / "18" / 18 equal; "" / None -> base five. odoo_major(18.0) == 18, odoo_major("") is None
def test_pg_base_profile(self):   # (2,4)->"2cpu4gb" (2,8)->"2cpu8gb" (4,16)->"4cpu16gb" (8,32)->"8cpu32gb"
def test_probe_hardware_reads_proc_under_a_root(self):
    # tmp root with proc/cpuinfo (4 'processor' lines) and proc/meminfo 'MemTotal: 16777216 kB' -> Hardware(4, 16384);
    # missing meminfo -> SizingError
def test_instances_from_config_skips_parked_entries_unless_selected(self):
    # tmp build dirs with odoo.conf; entry with "sizing: {profile: live, users: 30, workers: 6}" -> role "live",
    # users 30, overrides {"workers": 6}; active:false skipped; same entry with selected=its name included;
    # odoo_version 18.0 -> 18; missing odoo.conf -> conf == {}
```

- [ ] **Step 2: Run to verify failure.** `uv run --with pyyaml python -m unittest tests.test_ownerp_sizing -q`. Expected: `ModuleNotFoundError: No module named 'ownerp_sizing'`.
- [ ] **Step 3: Implement** the interfaces above in `scripts/ownerp_sizing.py`, following the algorithm block exactly (integer arithmetic, floor). `read_text(path) -> Optional[str]` returns `None` on `OSError`/`UnicodeError`. `instances_from_config` expands `~`/`$VARS` in `dockerfile_path`; `db_container` = `db_host`; only keys in `OVERRIDE_KEYS` are taken from the block. YAML is not imported in this task.
- [ ] **Step 4: Run tests.** Same command. Expected: `Ran 16 tests ... OK`.
- [ ] **Step 5: Commit.** `chmod +x scripts/ownerp_sizing.py`; `git add scripts/ownerp_sizing.py tests/test_ownerp_sizing.py`; subject `[ADD] ownerp_sizing.py 1.0.0: one host-wide calculation for Odoo workers, memory limits and PostgreSQL memory`.

---

### Task 2: Validator schema and template docs for the `sizing` block

**Files:**
- Modify: `scripts/ownerp_validate.py` (`CONTAINER_FIELDS`, version 1.2.0 -> 1.3.0, header + `SCRIPT_VERSION`, date 09.11.2026)
- Modify: `scripts/docker2update.yaml` (parameter comment + commented `#sizing:` example under `live-odoo`)
- Test: `tests/test_ownerp_validate.py`

**Interfaces:**
- Consumes: `OVERRIDE_KEYS` names from Task 1 (the schema repeats the names; Step 1 asserts they agree).
- Produces: `ownerp_validate.SIZING_FIELDS` and `CONTAINER_FIELDS["sizing"] = {"type": dict, "fields": SIZING_FIELDS}`. `profile`: `required`, `type: str`, `enum: ["live","test","demo"]`; `users`: `int`, `min 1`; `workers`, `max_cron_threads`, `db_maxconn`, `pg_max_connections`: `int`, `min 1`; `limit_memory_soft_mb`, `limit_memory_hard_mb`, `pg_shared_buffers_mb`: `int`, `min 64`. Unknown keys inside the block already get the "did you mean" warning from `validate_mapping`.

- [ ] **Step 1: Write the failing tests** in `tests/test_ownerp_validate.py` (real PyYAML, helper `write`/`ov.validate_update`):

```python
def test_sizing_block_is_accepted(self):   # profile: live, users: 30, workers: 6 -> no findings
def test_sizing_profile_is_an_enum(self):  # profile: prod -> ERROR path "containers[0].sizing.profile", message contains "is not one of live, test, demo"
def test_sizing_users_must_be_a_whole_number_of_at_least_one(self):  # users: 0 -> "must be at least 1"; users: "30" and users: true -> ERROR
def test_sizing_unknown_key_gets_a_suggestion(self):  # "profil: live" -> WARNING containing 'did you mean "profile"'
def test_sizing_without_profile_is_an_error(self):    # sizing: {users: 5} -> ERROR "is missing"
def test_sizing_in_flow_style_keeps_line_numbers(self):  # "sizing: {profile: live, users: 0}" -> the finding's line == the sizing line
def test_the_template_with_the_sizing_example_uncommented_validates(self):
    # read scripts/docker2update.yaml, uncomment the '#sizing:' lines, validate_update -> assert_clean (mirror test_the_proxy_example_validates)
def test_schema_names_match_the_calculation_overrides(self):
    # set(ov.SIZING_FIELDS) - {"profile","users"} == set(ownerp_sizing.OVERRIDE_KEYS)
```

- [ ] **Step 2: Run to verify failure.** `uv run --with pyyaml python -m unittest tests.test_ownerp_validate -q`. Expected: the new tests FAIL (`unknown key` warnings / missing `SIZING_FIELDS`).
- [ ] **Step 3: Implement** `SIZING_FIELDS` and the `sizing` entry in `CONTAINER_FIELDS`; bump version/date. In `scripts/docker2update.yaml` add the parameter line `sizing:` to the parameter comment block (role `live|test|demo`, optional `users`, optional overrides, "applied by doup; see dosize"), and under `live-odoo` a commented `#sizing:` block with `profile: "live"`, `users: 30`, `#workers: 6` — nothing active, so the shipped template keeps meaning "opt-in".
- [ ] **Step 4: Run tests.** Same command. Expected: `OK`.
- [ ] **Step 5: Commit.** Subject `[ADD] ownerp_validate 1.3.0: sizing block schema; docker2update.yaml documents it`.

---

### Task 3: State file, key decisions and the `odoo.conf` writer

**Files:**
- Modify: `scripts/ownerp_sizing.py` (sections "state + decisions" and "`odoo.conf` writer")
- Test: `tests/test_ownerp_sizing_apply.py`

**Interfaces:**
- Consumes: `parse_conf_values`, `MIB` (Task 1).
- Produces:
  - `STATE_NAME = ".sizing_state.json"`; `load_state(build_dir) -> Tuple[dict, Optional[str]]` (missing file -> `({}, None)`; corrupt JSON -> `({}, "<message>")`); `save_state(build_dir, state: dict) -> Optional[str]` (error text or `None`; write to temp file + `os.replace`); `ensure_dockerignore(build_dir, pattern=STATE_NAME) -> None` (append the pattern if no stripped line equals it; never raises).
  - State shape: `{"odoo": {key: {"status": "accepted"|"hand", "known": [str, ...]}}, "pg": {...same...}}`.
  - `@dataclass KeyDecision(key, action, current: Optional[str], recommended: str, note: str)` with `action` in `"write" | "same" | "keep"`.
  - `decide_key(key, current, recommended, entry: Optional[dict], is_default: bool, override: bool = False, equal=lambda a, b: a == b) -> KeyDecision` — the rule table below.
  - `format_decision(d: KeyDecision) -> str`; for `keep`: `"workers: hand 8, recommended 5 - unchanged"`; for `write`: `"workers: 3 -> 5"`; for `same`: `"workers: 5 (ok)"`.
  - `patch_conf_text(text, changes: Dict[str, str]) -> str`; `conf_regression(original, patched, allowed_keys, values_of=parse_conf_values) -> Optional[str]` (reason text or `None`; same contract as `odoo_build_cache._conf_regression`: no key dropped, no value changed outside `allowed_keys`, no key added outside them).
  - `@dataclass ConfSync(changed: bool, decisions: List[KeyDecision], error: Optional[str], backup: Optional[str])`; `sync_odoo_conf(build_dir, recommended: Dict[str, str], overrides: Set[str], template_values: Dict[str, str], now=None) -> ConfSync`.
- The module deliberately does not import `odoo_build_cache` (optional on a server); the small parser and gate are copies of its pattern.

**`decide_key` rules (first match wins):** 1 override and differs -> `write` ("Override"); 2 `equal(current, recommended)` -> `same`; 3 `entry.status == "hand"` -> `keep`; 4 `current is None` (key absent) -> `write`; 5 `entry.status == "accepted"` and `current in entry.known` -> `write`; 6 no entry and `is_default` -> `write`; 7 otherwise `keep` (note adds "not reviewed: dosize --review NAME" when there is no entry). `is_default` for `odoo.conf` = value equals the repo template's value for that key.

- [ ] **Step 1: Write the failing tests** (`tests/test_ownerp_sizing_apply.py`, tmp dirs, no YAML). Fixtures: a v18-shaped `odoo.conf` with `workers = 3`, `max_cron_threads = 2`, `limit_memory_soft = 2147483648`, `limit_memory_hard = 2684354560`, `db_maxconn = 100`, `db_password = secret`, a comment line and `dbfilter =`; `recommended` = the 4 CPU / 16 GiB live set from Task 1.

```python
def test_decide_key_table(self):   # one assert per rule 1-7 above, incl. action and that rule 7 note mentions "dosize --review" only without an entry
def test_template_default_values_are_rewritten_and_everything_else_is_byte_identical(self):
    # sync -> changed True; workers = 5, soft/hard/db_maxconn updated; db_password/comment/dbfilter lines identical;
    # a backup file "odoo.conf.bak_<ts>" holds the original text
def test_a_hand_edit_is_kept_and_reported(self):   # workers = 8 -> unchanged on disk; decisions has keep; format_decision == "workers: hand 8, recommended 5 - unchanged"
def test_an_accepted_value_follows_the_recommendation_and_is_remembered(self):
    # state accepted/known ["8"] -> workers 8 gets rewritten to 5; afterwards state known contains "5"; a later hand edit to 7 is kept
def test_a_hand_status_is_never_overwritten_even_at_the_template_default(self)
def test_an_override_writes_over_a_hand_value(self)
def test_missing_gevent_key_is_appended_for_v19(self):   # recommended has db_maxconn_gevent, file lacks it -> "db_maxconn_gevent = 16" appended
def test_a_corrupt_state_file_blocks_the_write(self):   # load_state error -> ConfSync.error contains "state"; odoo.conf bytes unchanged; no .bak
def test_missing_odoo_conf_is_an_error_not_an_exception(self)
def test_conf_regression_refuses_a_changed_foreign_key(self):   # patched with db_password changed -> reason "would change setting: db_password"; dropped key -> "would drop setting"
def test_sync_is_idempotent(self):   # second run: changed False, no new .bak
def test_state_roundtrip_and_dockerignore(self):   # save/load equal; ensure_dockerignore twice -> one line; existing file without trailing newline handled
```

- [ ] **Step 2: Run to verify failure.** `uv run --with pyyaml python -m unittest tests.test_ownerp_sizing_apply -q`. Expected: `AttributeError: module 'ownerp_sizing' has no attribute 'decide_key'` (errors).
- [ ] **Step 3: Implement** the interfaces above. `sync_odoo_conf` order: read file -> load state (error: return, write nothing) -> `decide_key` per recommended key -> build `changes` from `write` decisions -> `patch_conf_text` (replace the existing line in place as `key = value`; append absent keys at the end) -> `conf_regression(original, patched, allowed=changed keys)` (reason: return error, write nothing) -> backup `<odoo.conf>.bak_<YYYYmmdd_HHMMSS>` (failure: return error) -> temp file + `os.replace`, keeping the file mode -> update and `save_state` (a state-save failure is returned in `error` after the conf was written) -> `ensure_dockerignore`.
- [ ] **Step 4: Run tests.** Same command. Expected: `OK`.
- [ ] **Step 5: Commit.** Subject `[ADD] ownerp_sizing: state file, hand-edit decisions and the odoo.conf writer with backup and regression gate`.

---

### Task 4: `postgresql.conf` writer with restart, verification and rollback

**Files:**
- Modify: `scripts/ownerp_sizing.py` (section "`postgresql.conf` writer")
- Test: `tests/test_ownerp_sizing_apply.py`

**Interfaces:**
- Consumes: `decide_key`, `KeyDecision`, `conf_regression`, `load_state`/`save_state` (Task 3).
- Produces:
  - `PG_RESTART_KEYS = ("shared_buffers", "max_connections")`; `PG_PROFILE_VALUES: Dict[str, Tuple[str, ...]]` (the four shipped profiles' values: `shared_buffers` 1GB/2GB/4GB/8GB, `effective_cache_size` 3GB/6GB/12GB/24GB, `work_mem` 4MB/8MB/16MB/32MB, `maintenance_work_mem` 512MB/1GB/2GB/4GB, `max_connections` 100/150/200/300 — read from `pg-local-deploy.sh`, they are what an untouched deployment holds).
  - `pg_size_mib(text: str) -> Optional[int]` (`kB`, `MB`, `GB`, `TB`, case as PostgreSQL accepts, plain number = MB is NOT assumed: returns `None` without unit); `pg_equal(key, a, b) -> bool` (memory keys compared as MiB, `max_connections` as int); `parse_pg_conf_values(text) -> Dict[str, str]` (inline `#` comments and single quotes stripped; the last active occurrence wins); `patch_pg_conf_text(text, changes) -> str` (the last active line of a key becomes `key = value   # ownerp_sizing (was: <old>)`; absent keys are appended under one header comment); `find_pgdata(mounts_json: str) -> Optional[str]` (Source of the mount with Destination `/var/lib/postgresql/data`, trailing slash tolerated).
  - `Runner = Callable[[List[str]], Tuple[int, str]]`; `container_running(name, run) -> Optional[bool]`.
  - `@dataclass PgSync(changed: bool, decisions: List[KeyDecision], restarted: bool, verified: Optional[bool], rolled_back: bool, error: Optional[str], skipped: Optional[str])`; `sync_postgres(db_container, recommended, overrides, state_entry, run, db_user, now=None, sleep=time.sleep, retries=6) -> PgSync`.

**Flow of `sync_postgres` (the order is the safety):** `docker inspect -f {{json .Mounts}} <db>` -> `find_pgdata`; `None` -> `skipped="db_host is not a local container"` (not an error) -> read `<pgdata>/postgresql.conf` -> decisions (`is_default` = current equals a `PG_PROFILE_VALUES` entry via `pg_equal`) -> patched text + `conf_regression(parse=parse_pg_conf_values)` -> backup `postgresql.conf.bak_<ts>` (mode and owner copied) -> atomic replace (owner/mode of the original kept; `chown` failures ignored when not root) -> if any changed key in `PG_RESTART_KEYS`: `docker restart <db>`, else `docker kill --signal=HUP <db>` -> wait with `docker exec <db> pg_isready -U <db_user> -d postgres` (`retries` x `sleep(5)`) -> verify every changed key with `docker exec <db> psql -U <db_user> -d postgres -tAc "SHOW <key>"` via `pg_equal`. Not ready or mismatch: restore the backup (atomic replace), `docker restart <db>`, wait again, return `rolled_back=True` and an `error` that says the old values are active again; if the second wait also fails the `error` says the database is not answering.

- [ ] **Step 1: Write the failing tests** (same file; a fake `run` records argv lists and answers from a script; the "mount" is a tmp dir holding `postgresql.conf` with the 4cpu16gb profile values `shared_buffers = 4GB   # 25% of total RAM`, `max_connections = 200`, `work_mem = 16MB`, `maintenance_work_mem = 2GB`, `effective_cache_size = 12GB` plus an unrelated `random_page_cost = 1.1`):

```python
def test_size_parsing_and_equality(self):   # pg_size_mib("4GB")==4096, ("512MB")==512, ("8192kB")==8, ("1TB")==1048576, ("100") is None; pg_equal("shared_buffers","4GB","4096MB") True; pg_equal("max_connections","200","200") True
def test_parse_takes_the_last_occurrence_and_strips_comments(self)   # duplicate shared_buffers lines -> last wins; "shared_buffers = '1GB' # x" -> "1GB"
def test_find_pgdata_from_inspect_json(self)   # destination with and without trailing slash; no matching mount -> None
def test_profile_values_are_rewritten_and_unrelated_settings_survive(self):
    # recommended = live set of Task 1 -> file has shared_buffers = 3072MB etc.; random_page_cost line identical; bak exists
def test_restart_keys_restart_and_other_keys_only_reload(self):
    # a change including shared_buffers -> argv contains ["docker","restart","live-db"]; recommended differing only in work_mem -> ["docker","kill","--signal=HUP","live-db"], no restart
def test_verification_reads_show_for_each_changed_key(self)   # SHOW calls for shared_buffers, max_connections ... ; PgSync.verified True
def test_unit_mixed_values_are_not_a_hand_edit(self)   # file "4096MB", recommended "4GB" -> action "same"
def test_a_hand_value_is_kept_and_reported(self)   # work_mem = 99MB -> keep; file unchanged for that key
def test_database_that_does_not_come_up_is_rolled_back(self):
    # pg_isready always 1 after the first restart, then 0 after the rollback restart -> rolled_back True, file == original text, error mentions "rolled back"; sleep injected (no real waiting)
def test_a_value_the_server_did_not_take_is_rolled_back(self)   # SHOW returns the old value -> rolled_back True
def test_an_external_database_is_skipped_not_failed(self)   # inspect rc 1 -> skipped set, error None, no file touched
def test_the_regression_gate_protects_foreign_settings(self)   # conf_regression with parse_pg_conf_values: changed random_page_cost -> reason
```

- [ ] **Step 2: Run to verify failure.** `uv run --with pyyaml python -m unittest tests.test_ownerp_sizing_apply -q`. Expected: errors `no attribute 'sync_postgres'` / `pg_size_mib`.
- [ ] **Step 3: Implement** per the flow above. The caller (Task 5) guarantees the Odoo container is stopped; `sync_postgres` itself never decides that.
- [ ] **Step 4: Run tests.** Same command. Expected: `OK` (Task 3 tests still pass).
- [ ] **Step 5: Commit.** Subject `[ADD] ownerp_sizing: postgresql.conf writer with restart, SHOW verification and rollback`.

---

### Task 5: `doup` integration

**Files:**
- Modify: `scripts/update_docker_odoo.py` (version 5.25.0 -> 5.26.0, header + `SCRIPT_VERSION`, date 09.11.2026): `process_container`/`_process_container` gain `all_containers=None`; `main()` passes `config['containers']`
- Test: `tests/test_update_docker_odoo.py`

**Interfaces:**
- Consumes: `compute_plan`, `instances_from_config`, `probe_hardware`, `sync_odoo_conf`, `sync_postgres`, `container_running`, `format_decision` (Tasks 1, 3, 4).
- Produces (module level in `update_docker_odoo.py`):
  - `SIZING_ERRORS = 0` (reset at the start of `main()`); `sizing_module() -> Optional[module]` (imports `ownerp_sizing` from the script's own folder; `None` when missing or broken)
  - `run_sizing_odoo(container, all_containers, path, dockerfiles_source, hardware=None) -> Tuple[int, int, int]` (info, warnings, errors), stores the plan for the second step in `SIZING_PLAN`
  - `run_sizing_postgres(container, db_user, runner=None) -> Tuple[int, int, int]`
  - `exit_code_for(failure_count: int, sizing_errors: int) -> int` (0 only when both are 0)
- Call sites inside `_process_container`: `run_sizing_odoo` right after the "cache release archives" step (so `http_interface` is synced first) and before the stop block; `run_sizing_postgres` right after the stop/remove/rmi loop and before the Dockerfile check and build (Odoo is down for the whole build, so the restart window is free). A container without a `sizing` block: both return `(0, 0, 0)` and print nothing.

Behaviour: the plan is computed for the whole host (`instances_from_config(all_containers, selected=container name)`, parked entries excluded) and applied only to `container`. Output uses `print_step("sizing odoo.conf", "<n> written, <m> unchanged")` plus one indented line per `format_decision` of kept/written keys, mirrored with `run_log_write`. Hand-edit reports are info lines (no warning, no exit change). An unreadable state, a failed write, unreadable hardware, a missing module, a missing `odoo.conf` or a PostgreSQL rollback are `note_issue("ERROR"/"WARNING", ...)`, `SIZING_ERRORS += 1` for errors, and never raise out of the step (wrap in `try/except Exception`). An over-budget plan is applied and reported as one `note_issue("WARNING", ...)` naming need and budget (no error count). An "unreadable" `odoo.conf` in the tests is one with invalid UTF-8 bytes (`read_text` returns `None`). Reference template: `join(dockerfiles_source or DEFAULT_DOCKERFILES_SOURCE, f"v{version}-odoo", "odoo.conf")` read with `parse_conf_values`. `run_sizing_postgres` first checks `container_running(container_name, runner)`: running or unknown -> WARNING "Odoo container still running, PostgreSQL change skipped" and no restart. The default `runner` wraps `subprocess.run` for `docker ...` argv lists.

- [ ] **Step 1: Write the failing tests** (add `class SizingStepsTest` to `tests/test_update_docker_odoo.py`; tmp build dirs with a v18-shaped `odoo.conf`; capture stdout; `hardware=` injected; fake runner for the PostgreSQL step):

```python
def test_no_sizing_block_prints_nothing_and_changes_nothing(self)    # (0,0,0), odoo.conf bytes identical, stdout empty
def test_template_values_are_rewritten_for_the_named_instance_only(self):
    # two containers with blocks (live, test), run for live on 4 CPU/16 GiB -> live conf workers 5; test conf untouched
def test_hand_edit_is_reported_and_kept(self)    # workers = 8 -> unchanged; stdout contains "workers: hand 8, recommended 5 - unchanged"; errors == 0
def test_over_budget_is_a_warning_and_still_applies(self):   # 2 CPU/4 GiB live+test -> conf written with the minimal staffing (workers 2), errors 0, SIZING_ERRORS == 0, stdout contains "over budget", issue recorded with level WARNING
def test_unreadable_conf_is_an_error_line_not_an_abort(self):   # conf not parseable -> errors 1, conf unchanged, SIZING_ERRORS == 1, issue recorded with level ERROR
def test_unreadable_hardware_is_an_error_not_an_exception(self)   # hardware probe raising SizingError -> (…,1), no raise
def test_missing_odoo_conf_and_missing_module_are_errors_not_exceptions(self)
def test_parked_entries_do_not_consume_budget(self)    # 4/16, live + parked test -> live workers 8
def test_sizing_runs_between_cache_sync_and_stop(self)    # source-order guard: in _process_container's source text, 'run_sizing_odoo(' lies after '"cache release archives"' and before 'f"stop {container_name}"'; 'run_sizing_postgres(' after the 'remove image' step and before "Verify Dockerfile exists"
def test_postgres_step_never_restarts_while_odoo_still_runs(self)   # container_running True -> no 'docker restart' argv, warnings 1
def test_postgres_step_restarts_verifies_and_reports(self)   # fake runner, mount tmp dir -> conf rewritten, ["docker","restart","live-db"] seen, stdout has "sizing postgresql.conf"
def test_postgres_rollback_is_an_error_and_the_run_continues(self)   # rolled back -> errors 1, SIZING_ERRORS incremented
def test_a_sizing_error_alone_makes_the_exit_status_one(self)   # exit_code_for(0, 1) == 1, (1, 0) == 1, (0, 0) == 0; and main() with a real YAML file and --validate stays 0 (guard against regressions in the existing MainAgainstARealConfigFileTest)
```

- [ ] **Step 2: Run to verify failure.** `uv run --with 'textual>=8,<9' --with pyyaml python -m unittest tests.test_update_docker_odoo -q`. Expected: new tests error with `AttributeError: ... 'run_sizing_odoo'`.
- [ ] **Step 3: Implement** the interfaces; add `all_containers=None` as a trailing keyword of both container functions so existing positional callers keep working; `main()` returns `exit_code_for(failure_count, SIZING_ERRORS)` and, when `SIZING_ERRORS > 0`, adds `print_step("sizing errors", str(SIZING_ERRORS))` to the summary.
- [ ] **Step 4: Run tests.** Same command. Expected: `OK`; then the full suite (command under Global Constraints). Expected: final line `OK`.
- [ ] **Step 5: Commit.** Subject `[ADD] update_docker_odoo 5.26.0: apply the sizing block to odoo.conf and PostgreSQL, never abort, exit 1 on sizing errors`.

---

### Task 6: `dosize` report, per-value review and the `pg` subcommand

**Files:**
- Modify: `scripts/ownerp_sizing.py` (section "report / review / CLI")
- Test: `tests/test_ownerp_sizing_cli.py`

**Interfaces:**
- Consumes: Tasks 1, 3, 4.
- Produces:
  - `load_host(config_path, hardware=None, selected=None) -> Tuple[Plan, List[Instance], List[dict]]` (YAML imported lazily here; raises `SizingError` with a sentence for an unreadable file or missing PyYAML)
  - `render_report(plan, instances, states: Dict[str, dict]) -> str` (plain English text, no ANSI)
  - `pending_values(instance, result, state, pg_current: Optional[Dict[str, str]]) -> List[Tuple[str, str, str, str]]` ((`odoo`|`pg`, key, current, recommended) for every key whose current value differs from the recommendation and has no state entry yet)
  - `review(instance, result, state, ask=input, out=print, pg_current=None) -> dict` (returns the new state; prompt per value: `workers: current 3 -> recommended 5 - accept? (y/N/q)`; `y` -> `status accepted`, `known=[current]`; Enter/`n` -> `status hand`; `q` stops and keeps what was decided so far; never writes a config file)
  - `pg_current_values(db_container, run) -> Optional[Dict[str, str]]`
  - `main(argv=None) -> int` — forms: `ownerp_sizing.py [report] [--config PATH] [--json] [--cpus N --ram-mib M]`, `--review NAME`, `pg --role ROLE --container NAME [--users N] [--json] [--config PATH] [--cpus N --ram-mib M]`, `--version`. `--cpus/--ram-mib` replace the probe (deterministic tests, what-if). Exit codes of the report: 0 fits, 1 over budget or warnings, 2 config unreadable (like `doval`). `pg` JSON: `{"role","container","base_profile","values":{...},"reasons":[...],"warnings":[...],"over_budget":false}`; an over-budget plan still prints the JSON, writes its warning to stderr and exits 0 (pg-local-deploy needs the values). The instance whose `db_host` equals `--container` takes role/users from the YAML block (YAML wins); otherwise a synthetic instance is appended to the host.

- [ ] **Step 1: Write the failing tests** (`tests/test_ownerp_sizing_cli.py`, real PyYAML, tmp YAML + build dirs; module skips itself without PyYAML like `test_ownerp_validate`):

```python
def test_report_shows_hardware_budget_and_reasons(self):   # 4 CPU/16 GiB live+test -> text contains "4 CPU", "16.0 GiB", "9626 MiB", "5 workers", "other instances use 3"
def test_report_for_a_host_without_blocks_says_how_to_opt_in(self)   # contains "without sizing block" and the fish line "wizup"
def test_report_marks_kept_hand_values(self)   # conf workers 8 + state hand -> line "workers: hand 8, recommended 5 - unchanged"
def test_report_exit_codes(self)   # fits -> 0; 2 CPU/4 GiB live+test (over budget) -> 1 and "over budget"; missing YAML -> 2
def test_report_json_roundtrip(self)   # --json parses; results[0]["odoo"]["workers"] == "5"
def test_pending_values_lists_only_differing_unreviewed_keys(self)
def test_review_asks_per_value_and_records_accept_and_keep(self):
    # scripted ask: "y" for workers, "" for db_maxconn, "q" afterwards -> state odoo.workers accepted known ["3"],
    # odoo.db_maxconn hand known ["100"], remaining keys untouched; no conf file modified
def test_review_with_a_corrupt_state_stops_with_a_message(self)
def test_pg_subcommand_uses_the_yaml_role_over_the_flag(self)   # YAML says test, --role live -> values equal the test result
def test_pg_subcommand_for_a_new_container_uses_the_flag(self)   # empty host, --role live --container live-db --cpus 4 --ram-mib 16384 -> shared_buffers "4096MB" (live alone: pg_total 4096, weight 3 of 3)
def test_pg_subcommand_over_budget_exits_zero_and_warns(self)   # --role live --cpus 2 --ram-mib 4096 with an existing test instance in YAML -> 0, JSON over_budget true, stderr contains "over budget"
def test_review_flag_without_terminal_is_refused(self)   # review needs a tty; main returns 2 with a message when stdin is not a tty
```

- [ ] **Step 2: Run to verify failure.** `uv run --with pyyaml python -m unittest tests.test_ownerp_sizing_cli -q`. Expected: `AttributeError: ... 'render_report'`.
- [ ] **Step 3: Implement** the interfaces. `render_report`: header lines `Hardware: <n> CPU, <x.x> GiB RAM`, `Budget: <budget> MiB for Odoo (RAM - <reserve> MiB system - <pg> MiB PostgreSQL), need: <need> MiB`; per instance `<name> (<role>): <w> workers, cron <c>, ...` followed by its reasons, warnings, and the `format_decision` lines against the current conf; blockless instances are listed as `without sizing block (counted with its current configuration)`. Entry point guard `if __name__ == "__main__": sys.exit(main())`.
- [ ] **Step 4: Run tests.** Same command. Expected: `OK`.
- [ ] **Step 5: Commit.** Subject `[ADD] ownerp_sizing: dosize report, per-value review of the first call, pg subcommand`.

---

### Task 7: `wizup` and `konsole` questions (role, users)

**Files:**
- Modify: `scripts/ownerp_wizard.py` (1.2.0 -> 1.3.0, header + constants, date 09.11.2026); `scripts/ownerp_console.py` (1.2.0 -> 1.3.0)
- Test: `tests/test_ownerp_wizard.py`, `tests/test_ownerp_console.py`

**Why this task exists:** `set_fields()` refuses a mapping (`"... is not a scalar"`) and `format_value()` would write a dict as a quoted string, and the console form hides mapping fields. The `sizing` block is a mapping, so the single write path is extended, not bypassed.

**Interfaces:**
- Consumes: `Field` namedtuple, `set_fields`, validator schema (Task 2), `ownerp_sizing.review`/`load_host` (Task 6, imported guarded: `None` when absent).
- Produces in `ownerp_wizard`:
  - `format_value(value)` renders a dict as a one-line flow mapping: `{profile: "live", users: 30}`.
  - `set_fields` accepts a `dict` value for a field whose current value is absent or a dict that sits on one line as a flow mapping; a multi-line block mapping still returns the error `sizing is not a scalar - edit it with mcedit`.
  - `SIZING_FORM = [Field("sizing_profile", "Role", "live, test or demo", None), Field("sizing_users", "Concurrent users", "empty = from hardware (live only)", None)]`
  - `flatten_sizing(entry: dict) -> dict` (copy with `sizing_profile`/`sizing_users` taken from the block); `fold_sizing(entry: dict, changes: dict) -> dict` (replaces those two pseudo keys by a `sizing` dict that keeps existing override keys; `coerce("sizing_users", text)` -> `int`).
  - `ask_sizing(path, index, ask=input, out=print) -> int` — the `wizup` flow: asks "Role? (live/test/demo)" and, for live, "Concurrent users (empty = from hardware)?", writes through `set_fields`, prints "The values take effect with the next `doup`. Preview: `dosize`", and offers "Review the single values now? (Y/n)" which runs `ownerp_sizing.review`. New menu entry `3) Set role/sizing` in `main()` for the update kind.
- In `ownerp_console`: `_open_form` appends `SIZING_FORM` to the update form and passes `flatten_sizing(current)`; `_save_changes` runs `fold_sizing` before `set_fields`; after a sizing change it notifies "Role set - confirm the single values: dosize --review NAME" (the per-value review needs a terminal; the console does not run it).

- [ ] **Step 1: Write the failing tests:**

```python
# tests/test_ownerp_wizard.py
def test_format_value_renders_a_flow_mapping(self)   # {"profile":"live","users":30} -> '{profile: "live", users: 30}'
def test_set_fields_adds_a_sizing_block_in_one_line_and_validates(self)   # new key appended inside the entry; reload -> entry["sizing"] == {"profile":"live","users":30}; one backup; file otherwise identical
def test_set_fields_replaces_a_one_line_sizing_block_and_keeps_overrides(self)   # fold_sizing keeps workers: 6
def test_set_fields_refuses_a_multi_line_sizing_block(self)   # error contains "not a scalar"
def test_an_invalid_role_is_rejected_by_the_validator_and_nothing_is_written(self)   # profile "prod" -> ok False, file unchanged
def test_ask_sizing_flow(self)   # scripted input "live","30","n" -> writes sizing; out text contains "role" and "next doup"; users prompt is skipped for "test"
def test_flatten_and_fold_roundtrip(self)
# tests/test_ownerp_console.py (follow the existing EntryForm tests; Textual present via --with)
def test_update_form_offers_role_and_users(self)   # the form built for an update entry contains labels "Role" and "Concurrent users", prefilled from the block
def test_saving_the_sizing_fields_writes_the_block(self)
```

- [ ] **Step 2: Run to verify failure.** `uv run --with 'textual>=8,<9' --with pyyaml python -m unittest tests.test_ownerp_wizard tests.test_ownerp_console -q`. Expected: new tests fail (`AttributeError`/`not a scalar`).
- [ ] **Step 3: Implement** as described. The sizing questions are English like the wizard's existing prompts (Global Constraints).
- [ ] **Step 4: Run tests.** Same command. Expected: `OK`.
- [ ] **Step 5: Commit.** Subject `[ADD] wizup/konsole: ask role and users for the sizing block; set_fields writes a one-line mapping`.

---

### Task 8: `chk` check `odoo_sizing`

**Files:**
- Modify: `scripts/server-readiness.py` (1.17.0 -> 1.18.0, header + constants, date 09.11.2026; `CHECKS` after `check_odoo_capacity`; `DELIVERED_SCRIPTS` gets `"ownerp_sizing.py"`)
- Test: `tests/test_server_readiness.py`

**Interfaces:**
- Consumes: `_load_config(ctx, UPDATE_CONFIG)`, `_skip`, `_ok`, `Finding`, `Severity` (existing); `ownerp_sizing.probe_hardware(ctx.root)`, `instances_from_config`, `compute_plan`, `decide_key`, `load_state` (loaded from `ctx.home/ownerp_sizing.py` with `importlib.util`, like the nginx guard, `None` when absent).
- Produces: `check_odoo_sizing(ctx: HealthContext) -> Finding`, id `odoo_sizing`, title `Odoo sizing`.

Severity table (the existing `check_odoo_capacity` stays untouched; it keeps judging every host):
- no `sizing` block anywhere -> SKIP "no instance has a sizing block" (decision 5: no nagging); module missing/unimportable, hardware unreadable, PyYAML missing -> SKIP with the reason
- `current_need_mib + pg_total_mib > ram_mib` (current conf values × 325 MiB, hand values included) -> FAIL
- `plan.over_budget`, or `current_need_mib > budget_mib`, or `plan.warnings` -> WARN
- only deviations (hand values, or values waiting for the next `doup`) -> OK with `note` listing them
- every non-OK finding carries one fish fix line: `dosize   # shows reasons and deviations` (FAIL/WARN) or, for a missing review, `dosize --review <name>`

- [ ] **Step 1: Write the failing tests** (tmp `HealthContext(root=..., home=...)` with `docker2update.yaml`, build dirs and `ownerp_sizing.py` copied into `home`; `/proc` files under the tmp root; `shutil.which("docker")` patched as the neighbouring tests do):

```python
def test_no_sizing_block_is_a_skip(self)
def test_matching_conf_is_ok(self)    # conf at the 4 CPU/16 GiB live+test recommendation -> OK, detail mentions "5"
def test_hand_value_is_an_ok_with_a_note(self)   # workers = 8 + state hand -> Severity.OK, note contains "workers: hand 8, recommended 5"
def test_over_budget_is_warn(self)    # 2 CPU/4 GiB live+test -> WARN naming need and budget, fix starts with "dosize"
def test_conf_above_budget_is_warn(self)   # 4/16 with conf workers = 12 -> WARN
def test_total_above_ram_is_fail(self)    # 4/16 with workers = 60 -> FAIL
def test_missing_module_hardware_or_yaml_support_is_a_skip_not_a_crash(self)   # no ownerp_sizing.py in home; no proc/meminfo
def test_check_is_registered_after_the_capacity_check(self)   # CHECKS.index(check_odoo_sizing) == CHECKS.index(check_odoo_capacity) + 1
def test_delivered_scripts_lists_the_module(self)
```

- [ ] **Step 2: Run to verify failure.** `uv run --with 'textual>=8,<9' --with pyyaml python -m unittest tests.test_server_readiness -q`. Expected: `AttributeError: ... 'check_odoo_sizing'`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run tests.** Same command, then `tests.test_delivered_scripts` (`DELIVERED_SCRIPTS` must be a subset of `copy_scripts`: this fails until Task 10 adds the delivery line, so run it after Task 10 and note the dependency in the commit). Expected for this module: `OK`.
- [ ] **Step 5: Commit.** Subject `[ADD] server-readiness 1.18.0: odoo_sizing check for instances with a sizing block`.

---

### Task 9: `pg-local-deploy.sh` role prompt with fallback

**Files:**
- Modify: `scripts/pg-local-deploy.sh` (version 1.4.0 -> 1.5.0 in the header line 5 style, date 09.11.2026)
- Test: `tests/test_deploy_scripts.py`

**Interfaces:**
- Consumes: `ownerp_sizing.py pg ... --json` (Task 6).
- Produces in the script: `_pg_sizing_block <role> <container> [users]` — runs `python3 "${OWNERP_SIZING:-$HOME/ownerp_sizing.py}" pg --role ... --container ... --json`, prints the override block (`# --- ownerp_sizing override ---` followed by `key = value` lines) and the base profile name separated by a marker line, returns non-zero when the module is absent, the call fails or JSON is unusable; an over-budget plan still prints the block and returns 0, its warning goes to stderr.
- Dialog change (before the existing profile menu): "Role of this instance? 1) live 2) test 3) demo 4) not specified (fixed profiles)"; for live "Concurrent users [from hardware]". With a role and a working `_pg_sizing_block`: `conf_func` = the base profile named by the CLI, and Step 4 appends the override block to `postgresql.conf.src` exactly as the SSL override is appended (PostgreSQL takes the last setting). Any failure: print "Sizing not available - fixed profiles" and show the existing four-profile menu unchanged.

- [ ] **Step 1: Write the failing tests** (`source_and_run(PG, "PG_DEPLOY_NO_MAIN", ...)` with `OWNERP_SIZING` pointing at `scripts/ownerp_sizing.py` and a nonexistent `--config` so no host YAML is read; the helper also forwards `OWNERP_SIZING_ARGS` (extra CLI flags) to the call so tests can pass `--cpus 4 --ram-mib 16384`):

```python
def test_sizing_block_for_a_new_live_container(self)   # role live, container live-db, 4 CPU/16 GiB -> stdout contains "shared_buffers = 4096MB" and the base profile "4cpu16gb"; returncode 0
def test_missing_module_means_fallback(self)    # OWNERP_SIZING=/nonexistent -> returncode != 0, stdout empty
def test_over_budget_still_prints_the_block_and_warns(self)   # --cpus 1 --ram-mib 1024 -> zero, override block printed, stderr contains "over budget"
def test_script_still_parses_and_sources_without_running(self)   # existing SyntaxTests stay green
```

- [ ] **Step 2: Run to verify failure.** `uv run --with pyyaml python -m unittest tests.test_deploy_scripts -q`. Expected: new tests fail (`_pg_sizing_block: command not found`).
- [ ] **Step 3: Implement** the function and the dialog wiring; keep the four embedded profiles and their text byte-identical. `bash -n scripts/pg-local-deploy.sh` must stay clean.
- [ ] **Step 4: Run tests.** Same command. Expected: `OK`.
- [ ] **Step 5: Commit.** Subject `[CHG] pg-local-deploy 1.5.0: PostgreSQL memory from the shared sizing calculation, fixed profiles as fallback`.

---

### Task 10: Delivery, alias and documentation

**Files:**
- Modify: `getScripts.py` (9.37.0 -> 9.38.0, header + constants, date 09.11.2026): `copy_scripts()` list gets `"ownerp_sizing.py"` (next to `ownerp_state.py`), `RESTRICTED_DOCKER_SCRIPTS` gets `"ownerp_sizing.py",  # dosize, imported by doup`
- Modify: `fish/conf.d/33-aliases-backup.fish` (2.0.0 -> 2.1.0 | 09.11.2026): `alias dosize='$HOME/ownerp_sizing.py'` with a comment (read-only report; `--review NAME` asks per value); `fish/functions/linux/ownerp-help.fish`: `dosize "sizing report"` in the free slot after `edup`; `fish/README.md` alias row
- Modify docs: `docs/COMPONENTS.md` (new entry "20. ownerp_sizing.py (v1.0.0)"; version/feature bullets in the entries for `update_docker_odoo.py`, `ownerp_validate.py`, `ownerp_wizard.py`, `ownerp_console.py`, `server-readiness.py`, `pg-local-deploy`, `getScripts.py`), `docs/usage/04-updates.md` (German and English section "Sizing: Worker, Speicher, PostgreSQL"), `docs/usage/09-reference.md` (script table + alias table, both languages), `usage/AGENT.md` (script row, `dosize`, the `sizing` block, exit status, "a hand edit wins", "kept by hand" re-adoption via an explicit override), `RELEASE_NOTES.md` (newest first, existing English style), `scripts/README_pg-local-deploy.md` (dialog)
- Test: `tests/test_delivered_scripts.py`, `tests/test_getscripts_restricted.py`, `tests/test_fish_help.py`

**Interfaces:** consumes everything above; produces nothing new.

- [ ] **Step 1: Write the failing tests:**

```python
# tests/test_delivered_scripts.py
def test_the_sizing_module_is_delivered_and_committed_executable(self)   # "ownerp_sizing.py" in delivered_names(); existing exec-bit test covers the mode
# tests/test_getscripts_restricted.py
def test_restricted_docker_tier_gets_the_sizing_module(self)   # in gs.RESTRICTED_DOCKER_SCRIPTS and in the copy_scripts list
# tests/test_fish_help.py
def test_dosize_is_defined_and_advertised(self)   # "dosize" in defined_names() and in advertised_commands()
```

- [ ] **Step 2: Run to verify failure.** `uv run --with 'textual>=8,<9' --with pyyaml python -m unittest tests.test_delivered_scripts tests.test_getscripts_restricted tests.test_fish_help -q`. Expected: 3 new FAIL.
- [ ] **Step 3: Implement** the delivery and alias changes. Then write the docs: each document states the same facts — the `sizing` block (`profile`, `users`, override keys), "a hand edit wins" and how to re-adopt a recommendation (put the value in the block as an override), the first-call review (`dosize --review NAME`; until then `doup` writes only values that still equal the repo template and reports the rest), `doup` never aborts because of sizing but exits 1, `-s NAME` recomputes the host and applies one instance, the restart window, PostgreSQL skipped for external databases, `pg-local-deploy` fallback. All examples fish syntax, no customer data.
- [ ] **Step 4: Run the full suite.** `uv run --with 'textual>=8,<9' --with pyyaml python -m unittest discover -s tests -q`. Expected: final line `OK` with the same skip count as before the work started. Then `git status --short` shows only the files listed in this plan; `git diff --cached | grep -iE "github|@|10\.[0-9]+\.[0-9]+\.[0-9]+"` returns nothing customer-specific (public-mirror scan before any commit).
- [ ] **Step 5: Commit.** Subject `[ADD] getScripts 9.38.0: deliver ownerp_sizing.py, dosize alias; docs and release notes`.

---

## Self-review notes (resolved inline)

- **Spec coverage:** decisions 1-7 -> Tasks 1 (hardware, roles), 2/7 (YAML block, questions), 3/4 (hand edit wins, state, PostgreSQL tuned), 5 (opt-in, applied by `doup`), 8 (`chk` only with a block), 1 (live limits scale), 6 (first-call review). Goals: one budget/reasons/same result (Tasks 1, 6, 8, 9 share one module), survives rebuild (Task 5). Anti-goals: no overwrite (Task 3), fit check (Task 1/8), no restart while serving (Task 5), no silent change (Task 5 output + run log). Per-version keys (Task 1), settled points (connections, never abort, `-s`, overrides, `pg-local-deploy` CLI: Tasks 1, 5, 6, 9).
- **Type consistency:** `KeyDecision`/`decide_key`/`format_decision` (Task 3) are the only decision vocabulary used in Tasks 4-8; `Plan`/`InstanceResult` fields are used by name in Tasks 5, 6, 8; `OVERRIDE_KEYS` is asserted equal to the validator schema (Task 2).
- **Proportion:** code bodies appear only for the calculation algorithm, which the signatures do not determine.
