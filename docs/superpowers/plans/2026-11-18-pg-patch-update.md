# PostgreSQL Patch Update (`pgup`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A delivered tool `ownerp_pg_update.py` (alias `pgup`) that shows every PostgreSQL container with its Odoo instances, available patch release and a recommendation, and updates selected containers safely — backup first, legacy containers converted to compose, one-command rollback.

**Architecture:** One new single-file script in `scripts/`, like the other delivered tools. Every `docker` call goes through an injected runner (`Runner = Callable[[List[str]], Tuple[int, str]]`, the type `ownerp_sizing.py` already uses), so the whole flow is unit-tested with a fake runner. Container pairing comes from `ownerp_migrate.py`, memory values and the `postgresql.conf` writer from `ownerp_sizing.py`; both are loaded from the script's own folder the way `update_docker_odoo.py:2001-2020` loads the sizing module. The backup uses `container2backup.py` through a new `--only-db` option.

**Tech Stack:** Python 3 standard library + `python3-yaml`, `unittest`, Docker CLI, fish alias.

**Spec:** `docs/superpowers/specs/2026-11-18-pg-patch-update-design.md` — read it first; this plan does not repeat its reasoning.

## Global Constraints

- No new dependency: standard library and `yaml` only. No Textual.
- `# Version:` header, `SCRIPT_VERSION` and `SCRIPT_DATE` agree in every touched script; the date is today's date from the environment in `DD.MM.YYYY`, never copied from this plan.
- Tool output, code, comments and docs in English.
- Every command printed for the operator is a plain `docker …` / `pgup …` line that works in fish: no `VAR=value`, no heredoc, no `$?`.
- Public mirror: no customer names, hostnames, IPs or domains in code, tests or docs. Test fixtures use `live-db`, `test-db`, `demo-db`, `live-odoo`.
- A file that holds the database password is created with mode 0600 (`os.open(..., 0o600)` or umask), never chmod-ed afterwards.
- The tool never removes the parked container and never deletes a dump.
- `initdb` must never run: no step may start a container whose data mount lacks `PG_VERSION`.
- Tests: `uv run --with 'textual>=8,<9' --with pyyaml python -m unittest discover -s tests -q` must stay green. Single module: `… python -m unittest tests.test_ownerp_pg_update -q`.
- Commit prefixes `[ADD]` / `[CHG]` / `[FIX]`. Commit only when the Captain has asked for commits in the executing session; otherwise leave the commit step open and report the changed files. Never push without being asked.

## Review Focus

1. **Data directory not at `/var/lib/postgresql/data`** (PGDATA env set differently, PostgreSQL 18 layout): `ownerp_sizing.find_pgdata` finds nothing. Expected: the container is shown in the overview, an update or conversion stops in phase 1 with "data directory not found", nothing is stopped. → Task 5, test `test_unknown_pgdata_blocks_before_anything_stops`.
2. **Password or other env value containing `$`**: compose would interpolate it. Expected: written as `$$`, the container gets the original value. → Task 4, test `test_dollar_in_environment_is_escaped`.
3. **Docker Hub unreachable** (proxy customer, offline): Expected: overview still lists everything, update column says `unknown (no registry access)`, `--to` still works. → Task 2, test `test_overview_without_registry`.
4. **Odoo container that was already stopped before the run**: Expected: it stays stopped afterwards; only containers that were running are started. → Task 6, test `test_only_previously_running_odoo_is_started`.
5. **Compose file with several services**: Expected: only the image of the service that owns this container changes; every other line of the file is byte-identical. → Task 4, test `test_patch_touches_one_service_only`.

---

### Task 1: `container2backup.py --only-db`

**Files:**
- Modify: `scripts/container2backup.py` (argument parser ~line 1717, main loop ~lines 1840-1900 and everything after the database loop; header line 6, `SCRIPT_VERSION`/`SCRIPT_DATE` lines 76-77 → 4.14.0)
- Test: `tests/test_container2backup.py`

**Interfaces:**
- Produces: CLI `container2backup.py --sql-only --only-db NAME [--only-db NAME …]`; exit 0 when every named database was dumped, 1 otherwise. Helper `select_databases(databases: list, only: list) -> Tuple[list, list]` returning `(selected_entries, unknown_names)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_container2backup.py`

```python
class OnlyDbTest(unittest.TestCase):
    DBS = [{"name": "live_db", "sql_container": "live-db", "data_container": "live-odoo"},
           {"name": "test_db", "sql_container": "test-db", "data_container": "test-odoo"}]

    def test_selects_named_entries_in_config_order(self):
        selected, unknown = c2b.select_databases(self.DBS, ["test_db", "live_db"])
        self.assertEqual([d["name"] for d in selected], ["live_db", "test_db"])
        self.assertEqual(unknown, [])

    def test_unknown_name_is_reported(self):
        selected, unknown = c2b.select_databases(self.DBS, ["nope"])
        self.assertEqual((selected, unknown), ([], ["nope"]))

    def test_empty_only_means_everything(self):
        self.assertEqual(c2b.select_databases(self.DBS, [])[0], self.DBS)
```

Use the module alias the file already uses for the script under test.

- [ ] **Step 2: Run** `… python -m unittest tests.test_container2backup -q` — expected: 3 errors, `select_databases` missing.

- [ ] **Step 3: Implement**
  - `select_databases` as above (module level, pure).
  - Parser: `--only-db`, `action='append'`, `default=[]`, `metavar='NAME'`.
  - Main: after loading the YAML, call `select_databases`. Any unknown name → print `ERROR: --only-db: not in the databases section: <names>` and `exit(1)` **before** the run lock is taken and before anything is created.
  - With `--only-db` given: iterate only the selected entries, and skip the `services` backups, the rsync step and every retention cleanup (`cleanup_backups`, `cleanup_backups_by_pattern`). Print one line `--only-db: services, off-site sync and retention cleanup skipped`. The run lock stays in force.
  - Bump version to 4.14.0, date from the environment.

- [ ] **Step 4: Run** the module tests and `tests.test_delivered_scripts` — expected: OK.

- [ ] **Step 5: Commit** `[ADD] container2backup: --only-db restricts a run to named databases`

---

### Task 2: Discovery, version, base and available update

**Files:**
- Create: `scripts/ownerp_pg_update.py` (shebang `#!/usr/bin/env python3`, header block like `ownerp_sizing.py:1-38`, version 1.0.0, executable bit set and committed)
- Test: `tests/test_ownerp_pg_update.py` (create; import like `tests/test_ownerp_sizing_apply.py:1-20`, alias `pg`)

**Interfaces:**
- Consumes: `ownerp_migrate.is_postgres`, `is_odoo`, `_pair_database_container`, `_env_of`, `_name_of`, `_image_of`, `_networks`, `databases_in`, `odoo_version_in`, `DB_HOST_ENV`; `ownerp_sizing.find_pgdata`, `Runner`, `default_runner`, `DEFAULT_CONFIG`.
- Produces:

```python
Runner = Callable[[List[str]], Tuple[int, str]]
Fetch = Callable[[str], Optional[str]]          # url -> body, None on any failure

@dataclass
class Base:
    libc: str                 # "glibc 2.36" or "musl 1.2.5"
    codename: Optional[str]   # "bookworm", "trixie"; None for alpine/unknown

@dataclass
class OdooInfo:
    name: str; image: str; running: bool
    version: Optional[str]; database: Optional[str]
    workers: Optional[int]; has_sizing: bool

@dataclass
class PgTarget:
    name: str; image: str; inspect: dict
    version: Optional[Tuple[int, int]]      # (16, 8) from the running server
    base: Optional[Base]
    kind: str                               # "compose" | "legacy"
    compose_file: Optional[str]; compose_service: Optional[str]
    db_user: Optional[str]; pgdata: Optional[str]
    odoo: List[OdooInfo]; others: List[str]
    shared: bool; vector: bool; foreign: bool

@dataclass
class Choice:
    tag: Optional[str]          # full image reference to switch to, None = nothing
    version: Optional[Tuple[int, int]]
    note: str                   # one line for the plan / overview
    blocked: Optional[str]      # reason the update cannot run

def load_sibling(name: str)                                   # module or None
def db_user_for(inspect: dict, update_cfg: dict, cli_user: Optional[str], run: Runner) -> Optional[str]
def server_version(name: str, user: str, run: Runner) -> Optional[Tuple[int, int]]
def base_of_container(name: str, run: Runner) -> Optional[Base]
def base_of_image(image: str, run: Runner) -> Optional[Base]
def discover(run: Runner, update_cfg: dict, cli_user: Optional[str] = None) -> List[PgTarget]
def hub_tags(major: int, fetch: Fetch) -> Optional[Set[str]]
def choose(target: PgTarget, tags: Optional[Set[str]], to: Optional[str]) -> Choice
```

Decisions the tests pin:

- `server_version` runs `docker exec NAME psql -U USER -d postgres -Atc "SHOW server_version"` and parses the leading `major.minor` (`"16.8 (Debian 16.8-1.pgdg120+1)"` → `(16, 8)`).
- `db_user_for` order: CLI value, `POSTGRES_USER` in the container env, `db_user` of a `docker2update.yaml` entry whose `db_host` is this container, `postgres`. The first one for which `server_version` answers wins; none → `None`.
- Base: `cat /etc/os-release` (`VERSION_CODENAME`, `ID`) and the first line of `ldd --version` (glibc, e.g. `"glibc 2.36"`); for `ID=alpine` there is no usable `ldd --version`, there libc is `"musl " + VERSION_ID`. Container: `docker exec`; image: `docker run --rm --entrypoint sh IMAGE -c "cat /etc/os-release; ldd --version 2>&1 | head -n1"`.
- `kind`: label `com.docker.compose.project.config_files` present → `"compose"`, `compose_file` is its first entry, `compose_service` is label `com.docker.compose.service`.
- `vector`: image repository is `postgres-pgvector`. `foreign`: repository is neither `postgres` nor `postgres-pgvector`.
- `odoo`: every Odoo container whose `_pair_database_container` result is this target, plus entries of `docker2update.yaml` with `db_host == name`. `has_sizing`: that entry has a `sizing` mapping. `workers`: from the entry's sizing block or `None`. `shared`: more than one Odoo container. `others`: non-Odoo containers sharing a user-defined network.
- `hub_tags`: pages through `https://hub.docker.com/v2/repositories/library/postgres/tags?name=<major>.&page_size=100` (follow `next`, at most 10 pages), returns all tag names; `None` when the first page fails. `fetch` default uses `urllib.request` with a 15 s timeout; proxy variables apply through urllib's defaults.
- `choose` (target version `(M, n)`, codename `C`, tag suffix of the running image `S`):
  1. `foreign` → `blocked="image <image> is not maintained by this tool"`.
  2. `--to X.Y[-suffix]` with another major → `blocked="major upgrades are not supported"`.
  3. `tags is None` and no `--to` → `tag=None`, `note="unknown (no registry access)"`.
  4. Candidates are tags `M.k` with `k > n`. Pinned name for `k`: `M.k-C` when `C` is known, else `M.k + S`. Pick the highest `k` whose pinned name is in `tags`. If none exists but a plain `M.k` does: choose plain `M.k`, `note` says the base must be confirmed after the pull (Task 5 does it).
  5. No `k > n` → `tag=None`, `note="current"`.
  6. For `vector`, the returned tag is `postgres-pgvector:<pinned version>`; otherwise `postgres:<pinned version>`.

- [ ] **Step 1: Write the failing tests** — a `FakeRunner` class (dict from command tuple prefix to `(code, output)`, records calls) and:

```python
def test_version_is_read_from_the_server_not_the_tag(self): ...   # image postgres:16, server says 16.8 -> (16, 8)
def test_db_user_falls_back_in_order(self): ...                   # POSTGRES_USER fails to connect, yaml db_user works
def test_compose_label_decides_kind(self): ...
def test_pairing_by_env_and_by_yaml_db_host(self): ...            # one Odoo found by HOST env, one only by yaml
def test_choose_pins_the_running_base(self):
    t = target(version=(16, 8), base=pg.Base("glibc 2.36", "bookworm"), image="postgres:16.8")
    c = pg.choose(t, {"16.16", "16.16-bookworm", "16.16-trixie", "16.9"}, None)
    self.assertEqual(c.tag, "postgres:16.16-bookworm")
def test_choose_falls_back_to_highest_pinned_tag(self): ...       # 16.16-bookworm missing, 16.15-bookworm present -> 16.15-bookworm
def test_choose_refuses_another_major(self): ...                  # --to 17.2 -> blocked
def test_choose_current(self): ...                                # version (16, 16) -> tag None, note "current"
def test_choose_for_pgvector_keeps_our_repository(self): ...      # -> "postgres-pgvector:16.16-bookworm"
def test_overview_without_registry(self): ...                     # tags None -> note "unknown (no registry access)", no exception
def test_foreign_image_is_blocked(self): ...
```

- [ ] **Step 2: Run** — expected: import error, module missing.
- [ ] **Step 3: Implement** the dataclasses and functions above.
- [ ] **Step 4: Run** `tests.test_ownerp_pg_update` — expected: OK.
- [ ] **Step 5: Commit** `[ADD] ownerp_pg_update: discovery, running version, base and update choice`

---

### Task 3: Recommendations, overview, JSON, selection

**Files:**
- Modify: `scripts/ownerp_pg_update.py`
- Test: `tests/test_ownerp_pg_update.py`

**Interfaces:**
- Consumes: Task 2 types; `ownerp_sizing.pg_current_values`, `compute_plan`, `instances_from_config`, `Instance`, `probe_hardware`, `pg_equal`, `PG_WEIGHTS`, `shared_db_partners`.
- Produces:

```python
@dataclass
class Rec:
    id: str; text: str

@dataclass
class SizingView:
    recommended: Dict[str, str]; current: Dict[str, str]
    differs: Dict[str, Tuple[str, str]]     # key -> (current, recommended)
    skipped: Optional[str]                  # e.g. "shared container", "role unknown"

EOL = {12: "11/2024", 13: "11/2025", 14: "11/2026", 15: "11/2027",
       16: "11/2028", 17: "11/2029", 18: "11/2030"}

def sizing_view(target: PgTarget, update_cfg: dict, role: Optional[str], run: Runner, hardware=None) -> SizingView
def backup_routes(databases: List[str], backup_cfg: Optional[dict], container: str) -> Tuple[List[str], List[str]]   # (listed, unlisted)
def recommend(target: PgTarget, choice: Choice, sizing: SizingView, unlisted: List[str], today: datetime.date, collation_mismatch: List[str]) -> List[Rec]
def render_overview(rows: List[Tuple[PgTarget, Choice, List[Rec]]]) -> str
def overview_json(rows: List[Tuple[PgTarget, Choice, List[Rec]]]) -> dict
def parse_selection(text: str, count: int, recommended: Set[int]) -> Optional[List[int]]
def collation_mismatches(target: PgTarget, run: Runner) -> List[str]
```

Decisions:

- `sizing_view`: an Odoo entry with a `sizing` block → that instance's plan from `compute_plan` (as `ownerp_sizing._run_pg`, lines 1313-1338, does); no block → the role-based instance (`Instance(name=target.name, version=None, role=role, …)`), and `skipped="role unknown"` when `role` is `None`. `target.shared` → `skipped="shared container"`, `differs` stays empty. `differs` uses `pg_equal` so `1GB` equals `1024MB`.
- `backup_routes`: listed = databases with a `databases` entry whose `sql_container == container`; `backup_cfg is None` → all unlisted.
- Recommendation ids and their trigger, in this output order: `foreign_image` (choice blocked by foreign), `major_eol` (EOL month of the major is not after `today`; text names the month and "plan a major upgrade separately"), `patch_update` (`choice.tag`; text names the tag and, when pinned, "stays on <codename>"), `convert_compose` (`kind == "legacy"`), `sizing_differs` (non-empty `differs`; text lists `key cur -> rec`), `shared_db` (`target.shared`), `backup_missing` (non-empty `unlisted`), `collation_mismatch`. No recommendation → the overview prints `nothing to do`.
- `collation_mismatches`: major ≥ 15 only: `SELECT datname FROM pg_database WHERE datcollversion IS DISTINCT FROM pg_database_collation_actual_version(oid) AND datcollversion IS NOT NULL`; older majors → `[]`.
- `render_overview`: the table and the per-number recommendation lines exactly in the layout of the spec section "Overview, recommendation and selection" (columns `#`, `PostgreSQL`, `Version`, `Update`, `Kind`, `Odoo`; Odoo cell `name (version, db NAME, N workers)`, `(shared)` appended when shared).
- `overview_json` shape (keys fixed, an agent reads this):

```json
{"tool": "ownerp_pg_update", "version": "1.0.0", "containers": [
  {"name": "live-db", "image": "postgres:16.8", "version": "16.8",
   "base": {"libc": "glibc 2.36", "codename": "bookworm"},
   "kind": "legacy", "compose_file": null,
   "update": {"available": true, "image": "postgres:16.16-bookworm", "version": "16.16",
              "note": "stays on bookworm", "blocked": null},
   "odoo": [{"name": "live-odoo", "image": "…", "running": true, "version": "18.0",
             "database": "live_db", "workers": 4, "has_sizing": true}],
   "other_clients": [], "shared": false,
   "recommendations": [{"id": "patch_update", "text": "…"}]}]}
```

- `parse_selection`: `""` → `[]`; `"a"` → sorted `recommended`; `"1,3"` / `"1 3"` → `[1, 3]` (1-based, deduplicated, in input order); anything out of range or not a number → `None` (caller asks again).

- [ ] **Step 1: Write the failing tests**

```python
def test_recommendation_order_and_ids(self): ...            # legacy + update + differing shared_buffers -> ["patch_update","convert_compose","sizing_differs"]
def test_major_eol_on_and_after_the_month(self): ...        # major 14, today 2026-11-18 -> present; major 15 -> absent
def test_shared_container_keeps_sizing_out(self): ...       # shared -> skipped == "shared container", no "sizing_differs", "shared_db" present
def test_equal_sizes_in_other_units_do_not_differ(self): ...
def test_backup_routes_split(self): ...                     # ["a","b"], cfg lists only "a" for this container -> (["a"], ["b"]); cfg None -> ([], ["a","b"])
def test_json_carries_version_update_recommendation_and_odoo(self): ...   # asserts the keys above per container
def test_overview_text_shows_pairing(self): ...             # "live-db" row contains "live-odoo (18.0, db live_db, 4 workers)"
def test_parse_selection(self):
    self.assertEqual(pg.parse_selection("1,3", 3, {1}), [1, 3])
    self.assertEqual(pg.parse_selection("a", 3, {1, 3}), [1, 3])
    self.assertEqual(pg.parse_selection("", 3, {1}), [])
    self.assertIsNone(pg.parse_selection("4", 3, set()))
    self.assertIsNone(pg.parse_selection("x", 3, set()))
```

- [ ] **Step 2: Run** — expected: failures for missing names.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — expected: OK.
- [ ] **Step 5: Commit** `[ADD] ownerp_pg_update: recommendations, overview, JSON output, selection`

---

### Task 4: Compose file from a running container

**Files:**
- Modify: `scripts/ownerp_pg_update.py`
- Test: `tests/test_ownerp_pg_update.py`

**Interfaces:**
- Produces:

```python
def deploy_dir_for(name: str, pgdata_mount: dict, home: str) -> str
def compose_from_inspect(inspect: dict, image_inspect: dict, new_image: str,
                         db_user: str, vector_context: Optional[str] = None) -> Tuple[Optional[dict], List[str]]
def render_compose(document: dict, name: str) -> str        # header comment + yaml.safe_dump(sort_keys=False)
def mask_compose(text: str) -> str                          # for --dry-run: password values -> "***"
def write_private(path: str, text: str) -> None             # creates with 0600
def patch_compose_image(text: str, service: str, new_image: str, pg_version: Optional[str]) -> str   # raises ValueError
VECTOR_DOCKERFILE: str                                      # identical text to pg-local-deploy.sh lines 572-580
```

`compose_from_inspect` returns `(document, blockers)`; a non-empty `blockers` means `document` is `None`.

Carried over (source in `docker inspect` → compose key of service `postgres`):

| Inspect | Compose |
|---|---|
| `new_image` | `image` (+ `build: {context, args: {PG_VERSION}}` when `vector_context`) |
| `Name` | `container_name` |
| `Config.User` (non-empty) | `user` |
| `HostConfig.RestartPolicy` | `restart` (`on-failure:N` kept) |
| `HostConfig.ShmSize` (≠ 64 MiB default) | `shm_size` (bytes) |
| `HostConfig.Memory`, `NanoCpus` (non-zero) | `mem_limit`, `cpus` |
| `Config.Env` minus the image's `Config.Env` | `environment` (mapping; every `$` written as `$$`) |
| — | `environment.PGDATA` = destination of the data mount, always set |
| `Mounts` type `bind` | `volumes: "src:dst[:ro]"` |
| `Mounts` type `volume` | `volumes: "name:dst"` + top-level `volumes: {name: {external: true}}` |
| `HostConfig.PortBindings` | `ports` (`"hostip:hostport:containerport"`, host IP kept) |
| `NetworkSettings.Networks` | `networks: {net: {aliases, ipv4_address}}` + top-level `networks: {net: {external: true}}`; aliases without the container id and name |
| `HostConfig.ExtraHosts`, `Dns`, `DnsSearch` | `extra_hosts`, `dns`, `dns_search` |
| `HostConfig.LogConfig` (non-default) | `logging` |
| `Config.Cmd` / `Entrypoint` when different from the image | `command` / `entrypoint` |
| `Config.Healthcheck` | `healthcheck`; absent → `test: ["CMD-SHELL", "pg_isready -U <db_user> -d postgres"]`, `interval: 10s`, `timeout: 5s`, `retries: 5`, `start_period: 30s` |
| `Config.Labels` minus image labels and `com.docker.compose.*` | `labels` |

Blockers (each one sentence naming the setting): `HostConfig.Links`, `VolumesFrom`, `Devices`, `CapAdd`, `CapDrop`, `Privileged`, `SecurityOpt`, `Tmpfs`, `Ulimits`, `PidMode`/`IpcMode`/`UTSMode` other than empty/`private`/`shareable`, `NetworkMode` `host` or `container:…`, a network named `bridge` (the default bridge cannot be declared external), a mount of a type other than `bind`/`volume`, no data mount found. An anonymous volume (name is 64 hex characters) is carried over by name like a named one; the warning for the plan goes into the document under the top-level extension key `x-pgup-warnings` (a list of strings), which compose ignores and `render_plan` prints.

`patch_compose_image` (for instances that are already compose-managed): locate the block of `service` under `services:` by indentation, replace the value of its `image:` line and, when `pg_version` is given, of a `PG_VERSION:` line inside that block; keep the quoting style. Parse before and after with `yaml.safe_load`; the two documents must be equal once the expected values are set in the old one — otherwise `ValueError`.

`deploy_dir_for`: data mount of type `bind` → `<dirname(Source)>/<name>-deploy`; otherwise `<home>/pg-deploy/<name>`.

- [ ] **Step 1: Write the failing tests** (fixture `INSPECT_LEGACY`: bind mount `/opt/pg/live-db:/var/lib/postgresql/data`, network `live-db-net`, env `POSTGRES_PASSWORD=pa$word`, restart `always`, no healthcheck; fixture `TWO_SERVICES`: a compose text with services `postgres` and `adminer`, each with an `image:` line)

```python
def test_roundtrip_of_a_plain_legacy_container(self):
    doc, blockers = pg.compose_from_inspect(INSPECT_LEGACY, IMAGE, "postgres:16.16-bookworm", "ownerp")
    svc = doc["services"]["postgres"]
    self.assertEqual(blockers, [])
    self.assertEqual(svc["image"], "postgres:16.16-bookworm")
    self.assertEqual(svc["container_name"], "live-db")
    self.assertEqual(svc["volumes"], ["/opt/pg/live-db:/var/lib/postgresql/data"])
    self.assertEqual(svc["environment"]["PGDATA"], "/var/lib/postgresql/data")
    self.assertEqual(doc["networks"], {"live-db-net": {"external": True}})
def test_image_environment_is_not_copied(self): ...        # PG_MAJOR, PATH, GOSU_VERSION absent
def test_dollar_in_environment_is_escaped(self):           # Review Focus 2
    self.assertEqual(svc["environment"]["POSTGRES_PASSWORD"], "pa$$word")
def test_named_volume_becomes_external(self): ...
def test_anonymous_data_volume_is_kept_by_name_with_warning(self): ...
def test_unknown_settings_block_instead_of_being_dropped(self): ...   # Links, CapAdd -> two blockers, doc None
def test_default_bridge_blocks(self): ...
def test_missing_healthcheck_gets_ours(self): ...          # "pg_isready -U ownerp -d postgres"
def test_deploy_dir(self): ...                             # bind -> "/opt/pg/live-db-deploy"; volume -> "<home>/pg-deploy/live-db"
def test_written_file_is_0600(self): ...                   # tempdir, stat mode == 0o600
def test_mask_hides_passwords(self): ...                   # no "pa$$word" in mask_compose(render_compose(...))
def test_rendered_text_parses_back_to_the_document(self): ...
def test_patch_touches_one_service_only(self):                     # Review Focus 5
    out = pg.patch_compose_image(TWO_SERVICES, "postgres", "postgres:16.16-bookworm", None)
    changed = [b for a, b in zip(TWO_SERVICES.splitlines(), out.splitlines()) if a != b]
    self.assertEqual(changed, ['    image: "postgres:16.16-bookworm"'])
def test_patch_also_sets_the_pgvector_build_argument(self): ...
def test_patch_refuses_a_file_it_cannot_follow(self): ...          # service missing -> ValueError
```

- [ ] **Step 2: Run** — expected: failures.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — expected: OK.
- [ ] **Step 5: Commit** `[ADD] ownerp_pg_update: compose file derived from docker inspect`

---

### Task 5: Phase 1 — plan, pull, guards, backup

**Files:**
- Modify: `scripts/ownerp_pg_update.py`
- Test: `tests/test_ownerp_pg_update.py`

**Interfaces:**
- Consumes: Tasks 2-4.
- Produces:

```python
@dataclass
class Options:
    to: Optional[str] = None; dry_run: bool = False; no_input: bool = False
    sizing: str = "show"            # "apply" | "show" | "skip"
    role: Optional[str] = None; db_user: Optional[str] = None
    skip_backup: bool = False; force: bool = False
    home: str = os.path.expanduser("~")
    update_config: str = ""; backup_config: str = ""   # default <home>/docker2update.yaml, <home>/container2backup.yaml

@dataclass
class UpdatePlan:
    target: PgTarget; choice: Choice
    deploy_dir: str; compose_file: str
    compose_text: Optional[str]            # legacy: new file; compose: patched text
    databases: List[str]; listed: List[str]; unlisted: List[str]
    stop_odoo: List[str]                   # running Odoo containers only
    sizing: SizingView
    parked_name: Optional[str]             # legacy: "<name>-pre-<M.n>"
    problems: List[str]                    # non-empty -> the update must not start

def compose_cmd(run: Runner) -> Optional[List[str]]          # ["docker","compose"] | ["docker-compose"] | None
def prepare(target: PgTarget, choice: Choice, opts: Options, run: Runner) -> UpdatePlan
def render_plan(plan: UpdatePlan) -> str
def backup(plan: UpdatePlan, opts: Options, run: Runner, stream: Runner, out) -> Tuple[bool, List[str]]   # (ok, locations)
```

`prepare` is read-only except for `docker pull` / `docker build`. It fills `problems` (and then stops collecting further steps that need the failed fact) for:

- `choice.blocked`, container not running, `db_user` unknown, `pgdata` unknown → `"data directory not found (PGDATA is not at /var/lib/postgresql/data)"`, `PG_VERSION` file missing in `pgdata`.
- `compose_cmd` is `None` → `"docker compose is not installed"`.
- Pull failed. For `vector`: write `VECTOR_DOCKERFILE` to `<deploy_dir>/pgvector/Dockerfile` if missing, then `docker build --build-arg PG_VERSION=<pinned version> -t <tag> <context>`; build failure is a problem.
- Collation guard: `base_of_image(choice.tag)` must have the same `libc` string as `target.base`; otherwise `"base system would change (<old> -> <new>) and no <major>.x-<codename> image exists"`.
- Legacy: `compose_from_inspect` blockers; a container named `parked_name` already exists → `"<parked_name> exists from an earlier update; remove it or roll back first"`.
- Compose-managed: `compose_file` unreadable, or `patch_compose_image` (Task 4) raises.

Conversion without an update: a legacy target whose `choice.note` is `"current"` is still a valid plan. `prepare` then keeps the running image reference as `new_image`, skips pull and base comparison, and `render_plan` starts with `conversion to compose only, version stays <M.n>`. A compose-managed target that is current yields the problem `"nothing to do"`.
- Own-dump free space: for every unlisted database, free bytes of `<deploy_dir>` must be ≥ `pg_database_size(db)`; otherwise a problem naming the database and both sizes. Skipped with `opts.skip_backup`.

`backup` (called in phase 2, Odoo already stopped):

- `opts.skip_backup` → `(True, [])` and one warning line through `out`.
- listed non-empty → `stream([<home>/container2backup.py, "--sql-only", "--only-db", n1, "--only-db", n2 …])`; non-zero → `(False, …)`. Location reported: `defaults.backup_path` from the backup YAML.
- each unlisted → `docker exec NAME pg_dump -U USER -Fc -d DB`, streamed into `<deploy_dir>/pre-update/<YYYYmmdd-HHMMSS>/<db>.dump` (directory 0700, file 0600; use `subprocess` with `stdout=file`, not the text runner — binary data); a non-zero exit removes nothing and returns `False`.
- always: `docker exec NAME pg_dumpall -U USER --globals-only` → `<deploy_dir>/globals-<timestamp>.sql` (0600).

- [ ] **Step 1: Write the failing tests**

```python
def test_unknown_pgdata_blocks_before_anything_stops(self):      # Review Focus 1
    plan = pg.prepare(target(pgdata=None), choice_ok(), pg.Options(), runner)
    self.assertIn("data directory not found", plan.problems[0])
    self.assertFalse(any(c[:2] == ["docker", "stop"] for c in runner.calls))
def test_image_is_pulled_in_phase_one(self): ...                 # ["docker","pull","postgres:16.16-bookworm"] in calls
def test_libc_change_is_a_problem(self): ...                     # target glibc 2.36, image reports glibc 2.41
def test_missing_compose_is_a_problem(self): ...
def test_existing_parked_container_is_a_problem(self): ...
def test_current_legacy_container_gets_a_conversion_only_plan(self): ...   # no pull, compose_text set, new image == running image
def test_current_compose_container_has_nothing_to_do(self): ...
def test_only_running_odoo_is_listed_for_stop(self): ...
def test_free_space_rule_for_own_dump(self): ...                 # db 10 GiB, free 5 GiB -> problem; with skip_backup -> none
def test_pgvector_dockerfile_is_written_when_missing(self): ...
def test_backup_uses_dobk_for_listed_and_dump_for_unlisted(self): ...   # stream called with --only-db a; dump file for b exists, mode 0600
def test_failed_dobk_fails_the_backup(self): ...
def test_dry_run_plan_masks_the_password(self): ...              # render_plan output has no password
```

- [ ] **Step 2: Run** — expected: failures.
- [ ] **Step 3: Implement.** `render_plan` prints, in this order: target and versions, base line, Odoo containers to stop, other clients, backup route per database, compose file path (and the masked file under `--dry-run`), sizing lines, and the rollback command `pgup --rollback <name>`.
- [ ] **Step 4: Run** — expected: OK.
- [ ] **Step 5: Commit** `[ADD] ownerp_pg_update: phase 1 checks, image pull, backup routes`

---

### Task 6: Phase 2 — switch, verify, rollback

**Files:**
- Modify: `scripts/ownerp_pg_update.py`
- Test: `tests/test_ownerp_pg_update.py`

**Interfaces:**
- Consumes: Task 5 `UpdatePlan`, `backup`, `compose_cmd`; `ownerp_sizing.sync_postgres`, `load_state`, `save_state`, `override_conf_keys` (model: `update_docker_odoo.py:2140-2215`).
- Produces:

```python
STATE_DIR = "pg-deploy/state"                         # under opts.home
def state_path(home: str, name: str) -> str           # <home>/pg-deploy/state/<name>.json
def facts(name: str, user: str, pgdata: str, run: Runner) -> dict    # version, databases (sorted), owner "uid:gid"
def wait_ready(name: str, user: str, run: Runner, sleep=time.sleep, retries: int = 60) -> bool
def update_one(plan: UpdatePlan, opts: Options, run: Runner, stream: Runner, out, sleep=time.sleep) -> int
def rollback(name: str, opts: Options, run: Runner, out, now=None, ask=None, sleep=time.sleep) -> int
```

State file (JSON, 0600), written **before** the first change to the database container:
`{"name", "kind", "old_image", "new_image", "old_version", "new_version", "parked_name", "parked_restart", "compose_file", "compose_backup", "stopped_odoo", "time"}`.

`update_one` order (exit code in brackets on failure):

1. `plan.problems` → print them, return 2. `opts.dry_run` → print `render_plan`, return 0.
2. `docker stop` each `plan.stop_odoo`.
3. `backup(...)`; failure → start the stopped Odoo containers again [1].
4. `before = facts(...)`; write the state file.
5. `docker stop <name>`.
6. Legacy: `docker rename <name> <parked_name>`, `docker update --restart=no <parked_name>`, `write_private(compose_file, compose_text)`.
   Compose: copy the file to `<compose_file>.bak-<timestamp>` (0600), write the patched text.
7. `<compose> -f <compose_file> up -d`, then `wait_ready`.
8. `after = facts(...)`: version equals `choice.version`, `databases` equal, `owner` equal. Any failure in 5-8 → `_undo(state)` (legacy: `<compose> -f … down`, rename back, restore restart policy, `docker start`; compose: restore the `.bak`, `up -d`), `wait_ready`, start Odoo [1]. If the undo itself fails: say exactly which container is in which state, leave Odoo stopped [2].
9. `collation_mismatches` non-empty → Odoo stays down, print both ways forward (rollback command; reindex + `ALTER DATABASE … REFRESH COLLATION VERSION`) [2].
10. `opts.sizing == "apply"` and `plan.sizing.skipped is None`: `sync_postgres`. State entry: instance with a `sizing` block → that instance's build-dir state via `load_state`/`save_state`; otherwise `<home>/pg-deploy/state/<name>.sizing.json` holding `{"pg": {...}}`. Its outcome is a report line, never an exit code.
11. `docker start` each of `stop_odoo`. For `vector`: compare `SELECT extversion FROM pg_extension WHERE extname='vector'` per database with `default_version` from `pg_available_extensions`; a newer default is reported with `ALTER EXTENSION vector UPDATE` (not executed).
12. Report (old/new version, backup locations, compose file, `pgup --rollback <name>`, and for legacy: parked container and the line `docker rm <parked_name>` "once you are satisfied"; and when older directories exist under `<deploy_dir>/pre-update/`, their number and total size — the tool deletes none). Return 0.

`rollback`: load the state (missing → message, 2). Legacy needs the parked container to exist, compose needs `compose_backup` to exist; otherwise say what is missing, 2. `time` older than 7 days: `ask` for confirmation; with `no_input` require `opts.force`, else 2. Then: stop the Odoo containers that are running and paired, `_undo(state)`, `wait_ready`, check the version equals `old_version`, start those Odoo containers, rename the state file to `<name>.json.rolled-back-<timestamp>`. Return 0, or 2 when the old server does not come up.

- [ ] **Step 1: Write the failing tests** (FakeRunner with scripted answers; assert on the ordered call list)

```python
def test_legacy_happy_path_order(self):
    # stop odoo -> dobk -> stop db -> rename -> update --restart=no -> compose up -> start odoo
def test_state_file_exists_before_the_rename(self): ...
def test_only_previously_running_odoo_is_started(self): ...        # Review Focus 4
def test_failed_backup_restarts_odoo_and_touches_no_database(self): ...   # return 1, no "docker stop live-db"
def test_new_server_not_ready_is_undone(self): ...                 # compose down, rename back, restart policy restored, old started, return 1
def test_database_list_changed_is_undone(self): ...
def test_collation_mismatch_keeps_odoo_down(self): ...             # return 2, no "docker start live-odoo"
def test_compose_managed_path_backs_up_and_patches_the_file(self): ...
def test_sizing_refusal_does_not_change_the_exit_code(self): ...
def test_rollback_legacy(self): ...                                # down, rename back, restart restored, start, return 0
def test_rollback_without_parked_container_stops(self): ...        # return 2, nothing changed
def test_rollback_after_seven_days_needs_force_without_terminal(self): ...
def test_dry_run_changes_nothing(self): ...                        # no stop/rename/up in calls
```

- [ ] **Step 2: Run** — expected: failures.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — expected: OK.
- [ ] **Step 5: Commit** `[ADD] ownerp_pg_update: update run with verification and rollback`

---

### Task 7: Command line and modes

**Files:**
- Modify: `scripts/ownerp_pg_update.py`
- Test: `tests/test_ownerp_pg_update.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `build_parser() -> argparse.ArgumentParser`, `main(argv=None, run=None, stream=None, fetch=None, stdin=None, out=print) -> int`.

Flags: `--container NAME` (append), `--to VERSION`, `--dry-run`, `--json`, `--no-input`, `--sizing {apply,show,skip}`, `--role {live,test,demo}`, `--db-user USER`, `--skip-backup`, `--rollback NAME`, `--force`, `--config PATH`, `--backup-config PATH`, `--version`.

Mode table (first match wins):

| Call | Behaviour | Exit |
|---|---|---|
| `--rollback NAME` | `rollback` | its code |
| `--json` | print `overview_json`, change nothing (ignores `--container` for execution; filters the list when given) | 0, or 2 when Docker cannot be asked |
| `--container …` | `prepare` all named, print all plans, one confirmation (skipped with `--no-input` / `--dry-run`), then `update_one` in the given order; the first non-zero code ends the series and is returned; the report names the containers not started | code of the last run |
| no flags, stdin is a terminal | overview, `Select (e.g. 1,3 - a for all recommended - Enter to leave):`, re-ask on `None`, empty → 0; then as the row above | |
| no flags, no terminal | overview text | 0 |

Rules: `--to` with more than one container → argparse error. Unknown container name → message listing the PostgreSQL containers found, 2. Without a terminal and without `--no-input`, a `--container` call prints the plans and exits 2 with `needs --no-input to run without a terminal`. Not root → one warning line (sizing and the data-directory owner check need root); the run continues.

Sizing in the dialog (terminal only, after the plans are shown): a selected target without a `sizing` block and without `--role` gets the question `Role of <name> (live/test/demo, Enter to skip):`, and its plan is prepared again with the answer. If `--sizing` was not given and any selected plan has differing values, ask once `Apply the recommended memory settings? (y/N)`; yes sets `sizing="apply"` for this run. Without a terminal nothing is asked and the default `show` stands.

- [ ] **Step 1: Write the failing tests**

```python
def test_json_mode_prints_one_document_and_runs_nothing(self): ...     # json.loads(output) works; no stop/pull calls
def test_bare_call_without_terminal_prints_the_overview(self): ...     # returns 0, contains "PostgreSQL" header, no prompt
def test_interactive_selection_runs_the_selected_in_order(self): ...   # stdin "2,1\ny\n" -> update of #2 before #1
def test_series_ends_at_the_first_failure(self): ...                   # first returns 1 -> second never stopped; message names it
def test_container_without_no_input_and_without_terminal_exits_2(self): ...
def test_to_with_two_containers_is_rejected(self): ...
def test_dialog_yes_applies_sizing_and_no_input_never_asks(self): ...  # stdin "1\ny\ny\n" -> sync_postgres called; --no-input -> not called
def test_unknown_container_lists_the_known_ones(self): ...
def test_version_flag(self): ...                                       # prints SCRIPT_VERSION
```

- [ ] **Step 2: Run** — expected: failures.
- [ ] **Step 3: Implement**; end the file with `if __name__ == "__main__": sys.exit(main())`.
- [ ] **Step 4: Run** the module, then the whole suite — expected: OK.
- [ ] **Step 5: Commit** `[ADD] ownerp_pg_update: command line, interactive selection, JSON mode`

---

### Task 8: Delivery and documentation

**Files:**
- Modify: `getScripts.py` (both lists that carry `"ownerp_sizing.py"`, ~lines 4314 and 6376; comment `# pgup`; bump `SCRIPT_VERSION` minor, header and date)
- Modify: `fish/conf.d/33-aliases-backup.fish` (after the `dosize` alias, line 34): `alias pgup='$HOME/ownerp_pg_update.py'` with a comment block in the style of the one above `dosize`
- Modify: `fish/functions/linux/ownerp-help.fish` (a row for `pgup`, text `PostgreSQL update`, in both layouts where `dosize` appears), `fish/README.md` (alias table and file comment)
- Modify: `tests/test_delivered_scripts.py`, `tests/test_fish_help.py`
- Modify: `docs/COMPONENTS.md`, `docs/usage/09-reference.md` (German and English tables, script row and alias row), `usage/AGENT.md` (script table row and a command block like the `dosize` one at lines 149-153), `scripts/README_pg-local-deploy.md` (German and English: one paragraph "to update an existing instance use `pgup`"), `RELEASE_NOTES.md` (new entry on top, existing style), `CLAUDE.md` (one row in "Server commands that cannot be guessed")

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_delivered_scripts.py
def test_the_pg_update_tool_is_delivered_and_committed_executable(self):
    self.assertIn("ownerp_pg_update.py", delivered_names())
# tests/test_fish_help.py
def test_pgup_is_defined_and_advertised(self):
    self.assertIn("pgup", defined_names())
    self.assertIn("pgup", advertised_commands())
```

- [ ] **Step 2: Run** both modules — expected: 2 failures.
- [ ] **Step 3: Implement** the wiring and write the docs. `usage/AGENT.md` must state: `pgup --json` is read-only; execution needs `--container NAME --no-input`; exit codes 0 / 1 (failed, rolled back) / 2 (needs the operator); `--rollback NAME`; the tool never removes the parked container. `RELEASE_NOTES.md` entry covers the new tool and `container2backup --only-db`, and states the Docker Hub finding (plain `16.x` tags moved from bookworm to trixie with 16.9) in two sentences.
- [ ] **Step 4: Run** the whole suite — expected: OK. Scan the diff for customer data (`git diff --cached` after staging; the public-repo guard applies).
- [ ] **Step 5: Commit** `[ADD] pgup: delivery, fish alias, documentation`

---

### After the last task (needs the Captain)

Real run on the demo server, one step at a time with the result reported back before the next: `pgup --json` (compare with `docker ps`), `pgup --container <legacy> --dry-run`, the update of one legacy container, `pgup --rollback`, the update again, then one compose-managed and one pgvector instance. Unit tests cannot show whether a converted container really starts on the old data directory.
