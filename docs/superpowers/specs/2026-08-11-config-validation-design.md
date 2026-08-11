# Configuration Validation — Design

*11.08.2026 · building block 2 of 3 · status: specified*

Written in English like the rest of the repository's documentation. The
conversation that produced it was German; the artefact follows the repo rule.

## Problem

Two YAML files drive everything an operator does on an ownERP server:
`~/docker2update.yaml` for `doup` and `~/container2backup.yaml` for `dobk`.
Both are hand-edited in mcedit. Neither is meaningfully checked.

What `update_docker_odoo.py --validate` does today:

| | |
|---|---|
| Writes the file | The DNS optimisation runs **before** the validation and calls `save_updated_config()`. `--validate` — and with it the TUI's `v` key — can change the customer's file. |
| Skips inactive blocks | The loop `continue`s on `active: false`, so a parked block is never checked. It breaks on the day someone activates it. |
| Checks ten fields | Required fields, `type`, that `dockerfile_path` is a directory, and the shape of `pre_build_files` / `proxy`. |
| No type checks | `delay_time: "zehn"` passes. |
| No collisions | Duplicate `container_name`, duplicate ports, duplicate `database_name` — none of it is noticed. |
| Nothing about `defaults` | `log_retention_days: "90 days"` reaches the run. |
| No typo detection | `retention_day` instead of `retention_days` is silently ignored, and the default applies as if the operator had written nothing. |

`container2backup.py` has no validation at all. `check_paths()` runs at backup
time and covers exactly two things: `services.*.source_path` and
`fast_report.path`. Everything else is read with bare subscripts —
`service_config['backup_path']` is a `KeyError` in the middle of a backup run.

The typo case is the expensive one. A misspelled key is not an error anywhere
in the current code; it is a setting that silently does not exist.

## Decisions

**1. A script of its own, called as a subprocess.** `ownerp_validate.py`, next
to the other scripts in `$HOME`. Not a shared importable module: every script
on a customer server is standalone today, and an import would mean that a
missing file stops the runner from starting at all. A subprocess boundary is
the same one `ownerp_tui.py` already uses to reach the runner, and it degrades
to a warning instead of a traceback.

**2. Line numbers, via a positioned loader.** Findings name the file and the
line, so the operator can go straight there in mcedit. `yaml.safe_load()`
discards positions, so the loader is subclassed.

**3. Unknown keys are a warning with a suggestion, never an error.** A customer
may keep a note field, and a newer script may read a key this validator has not
learned yet. A validator that goes red on our own omission gets ignored, and an
ignored validator is worse than none.

**4. The file and the filesystem, not Docker.** Structure, types, collisions
and path existence. No `docker ps`, no port probing, no database lookups: the
check must produce the same verdict on a server whose containers happen to be
stopped, and it must be fast enough to run on every keystroke of `v`.

**5. Read-only, without exception.** The validator opens files for reading and
nothing else. The existing write path under `--validate` is fixed as part of
this block, because building block 1 promised that `v` cannot touch the
customer's configuration.

## Architecture

```
                       ┌─────────────────────────┐
ownerp_tui.py  ── v ──►│                         │
                       │  ownerp_validate.py     │──► reads docker2update.yaml
update_docker_odoo.py  │                         │──► reads container2backup.yaml
   --validate ────────►│  (read-only, stdlib     │
                       │   + PyYAML)             │──► findings on stdout
container2backup.py    │                         │──► exit 0 / 1 / 2
   --validate ────────►└─────────────────────────┘
```

Both callers locate the script beside themselves
(`os.path.dirname(os.path.abspath(__file__))`) and fall back to their previous
behaviour, with a warning, when it is absent.

### Components

| Component | Responsibility |
|---|---|
| `scripts/ownerp_validate.py` (new, v1.0.0) | CLI, report rendering, exit code |
| `PositionedDict` / `PositionedLoader` (inside it) | YAML loading that keeps the line of every mapping and every key |
| `UPDATE_SCHEMA`, `BACKUP_SCHEMA` (inside it) | The two schemas, declared as data |
| `validate_mapping()` and the collision/path checks | Pure functions over loaded data → list of `Finding` |
| `scripts/update_docker_odoo.py` (→ v5.12.0) | `--validate` delegates; the DNS write path is skipped under `--validate` |
| `scripts/container2backup.py` (→ next version) | `--validate` delegates; `backup_path` read defensively |
| `getScripts.py` (→ v9.12.0) | distributes `ownerp_validate.py`, adds the `doval` alias |

Everything worth testing is a pure function from loaded data to findings. The
rendering layer holds no logic.

## Positioned loading

`yaml.safe_load()` returns plain dicts and loses every position. The loader is
therefore subclassed so mappings come back as a `dict` subclass carrying their
own position and the position of each of their keys:

```python
class PositionedDict(dict):
    """A dict that remembers where it came from."""
    line = 0          # 1-based line of the mapping itself
    key_lines = None  # {key: 1-based line of that key}
```

`PositionedLoader(yaml.SafeLoader)` overrides `construct_mapping()` to build
one of these, reading `node.start_mark.line` for the mapping and
`key_node.start_mark.line` for each key (both 0-based in PyYAML, so `+ 1`).

No key is smuggled into the data — every consumer downstream treats the result
as an ordinary dict, and `getattr(obj, "key_lines", None)` is the only thing
the validator needs to know. Lists are left alone: a finding about a list item
is reported at the line of the item's own mapping.

A `yaml.YAMLError` is caught and reported as a single finding carrying
`error.problem_mark.line`, which is what makes "broken YAML, with a line
number" — promised in building block 1 — real.

## Schemas

Declared as data, one per file, so a new key is one line rather than a new
branch:

```python
UPDATE_SCHEMA = {
    "defaults": {
        "type": dict,
        "fields": {
            "dockerfiles_source":      {"type": str, "path": "dir"},
            "log_retention_days":      {"type": int, "min": 0},
            "history_retention_days":  {"type": int, "min": 0},
            "proxy": {"type": dict, "fields": {
                "http_proxy":  {"type": str},
                "https_proxy": {"type": str},
                "no_proxy":    {"type": str},
            }},
        },
    },
    "containers": {
        "type": list, "required": True, "min_items": 1,
        "item": {
            "type": dict,
            "fields": {
                "active":              {"type": bool},
                "type":                {"required": True, "enum": ["M", "F", "N"]},
                "delay_time":          {"type": int, "min": 0},
                "container_name":      {"type": str, "required": True},
                "database_name":       {"type": str, "required": True},
                "port":                {"required": True, "port": True},
                "longpolling_port":    {"required": True, "port": True},
                "dockerfile_path":     {"type": str, "required": True, "path": "dir"},
                "docker_image_name":   {"type": str, "required": True},
                "db_user":             {"type": str, "required": True},
                "db_password":         {"type": str, "required": True},
                "db_host":             {"type": str, "required": True},
                "volume":              {"type": str},
                "odoo_version":        {"type": (str, int)},
                "translate":           {"enum": ["Y", "N"]},
                "db_password_via_env": {"type": bool},
                "log_retention_days":  {"type": int, "min": 0},
                "proxy":               {"type": dict, "fields": {
                    "http_proxy":  {"type": str},
                    "https_proxy": {"type": str},
                    "no_proxy":    {"type": str},
                }},
                "pre_build_files":     {"type": list, "item": {
                    "type": dict,
                    "fields": {
                        "source": {"type": str, "required": True, "path": "any"},
                        "target": {"type": str},
                    },
                }},
            },
        },
    },
}
```

`BACKUP_SCHEMA` covers `defaults` (`retention_days`, `db_user`, `backup_path`,
`temp_path`, `stream`, `compression.format` ∈ `7z|zip|gzip|zstd`,
`compression.level` 0–9), `services.*` (`enabled`, `source_path`,
`backup_path`, `retention_days`) and `databases[]` (`name`, `sql_container`,
`data_container`, `retention_days`, `only_sql_dump`, `stream`,
`fast_report.enabled`, `fast_report.path`).

The exact key list is derived from two sources during implementation and both
must agree: the shipped template files, and the keys the scripts actually read.
A key present in one but not the other is a finding to raise, not to paper over.

### Ports are strings

`port: "127.0.0.1:11000"` is the shipped form. A naive `"type": int` would
flag every real customer configuration. The `"port": True` rule accepts:

| Form | Example |
|---|---|
| bare integer | `11000` |
| bare string | `"11000"` |
| bind address and port | `"127.0.0.1:11000"` |
| IPv6 bind address | `"[::1]:11000"` |

and extracts the trailing port number for the range check (1–65535) and for
collision detection. Anything else is an error naming the accepted forms.

## Checks

| Class | What it catches | Severity |
|---|---|---|
| Parse | Broken YAML, top level not a mapping | error (exit 2) |
| Structure | `containers` not a list, an empty `containers`, `databases` not a list, `services` not a mapping | error |
| Required | A required field missing or empty | error |
| Type | `delay_time: "zehn"`, `active: "yes"`, a `retention_days` below 0 | error |
| Enum | `type: "X"`, `compression.format: "rar"`, `translate: "J"` | error |
| Port form | A port that is not one of the four forms, or outside 1–65535 | error |
| Collision | Duplicate `container_name`, `database_name`, `port`, `longpolling_port`, `databases[].name` | error |
| Path | A configured path that does not exist | warning |
| Unknown key | A key no schema knows, with the closest known name from `difflib.get_close_matches` | warning |

**A booking on `active: false` is checked in full, but its findings are
warnings.** A parked block is not stopping any run; keeping the exit code red
for it would train operators to ignore the exit code. The finding still says
what is wrong, prefixed `(inactive)`.

**Collision detection considers active entries only.** Two containers sharing a
port is only a conflict if both can run. For backups the equivalent is
`databases[]`, which has no `active` flag — every entry counts.

## Output

```
ownerp_validate.py 1.0.0 (11.08.2026)

/root/docker2update.yaml
  ✗  83  containers[0].port: 11000 collides with test-odoo (line 107)
  ✗  79  containers[0].type: "X" is not one of M, F, N
  ⚠  91  containers[0].odoo_versoin: unknown key — did you mean "odoo_version"?
  ⚠  85  containers[0].dockerfile_path: /root/docker-builds/live-odoo/ does not exist

/root/container2backup.yaml — no findings

2 errors, 2 warnings
```

Findings are sorted by line within a file, and the files appear in the order
they were checked. A file with nothing to report gets one line, not a block —
the point of the report is what is wrong.

Findings never contain a value from `db_password`, `admin_passwd` or any key
whose name ends in `password`. A missing password is reported by key name; a
wrongly typed one is reported as "must be a string". The value itself is never
echoed, because this output gets pasted into support tickets.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | No errors. Warnings may be present. |
| 1 | At least one error in at least one file. |
| 2 | A file is missing, unreadable, or does not parse. |

Warnings deliberately do not affect the exit code — a path that does not exist
yet is a normal state during onboarding, which is exactly when building block 3
will run this validator against what it is about to write.

## CLI

```
ownerp_validate.py                  # both files at their default paths
ownerp_validate.py --update [PATH]  # only docker2update.yaml
ownerp_validate.py --backup [PATH]  # only container2backup.yaml
ownerp_validate.py --version
```

Default paths are `~/docker2update.yaml` and `~/container2backup.yaml`, matching
what the two scripts use. With no flag both are checked; a file that is absent
without having been asked for by name is reported as a skipped line, not as
exit 2 — a server that runs updates but not backups is a legitimate
installation.

## Integration

**`update_docker_odoo.py --validate`** delegates:

```
--validate → ownerp_validate.py --update <config path>   → that exit code
             (script absent) → today's per-container check, plus a warning
```

`validate_container_config()` is untouched and stays the runtime gate for every
container the run processes — it also performs the `expand_path()` the run
depends on. The two are not redundant: one is the offline view of the whole
file, the other is the last check before a container is acted upon.

**`container2backup.py --validate`** is new and delegates the same way.
A normal backup run is unchanged, with one exception: `service_config['backup_path']`
becomes a `.get()` with the service name as the fallback, so a missing key can
no longer raise `KeyError` in the middle of a backup.

**`ownerp_tui.py`** needs no change beyond what already exists — `v` builds
`argv += ["--validate"]` against the runner, and the runner now delegates.

**The read-only fix.** In `update_docker_odoo.py`, the DNS optimisation block
that runs before the container loop is skipped when `--validate` is set. What
it *would* have changed is reported as an informational line, so the operator
still learns that a `doup` would adjust the DNS options — the information
survives, the write does not.

**Distribution.** `getScripts.py` copies `ownerp_validate.py` in
`copy_scripts()` and gains the alias `doval` in
`fish/conf.d/33-aliases-backup.fish`, beside `dobk`, `doup` and `tui`.

## Error handling

| Situation | Behaviour |
|---|---|
| YAML does not parse | One finding with the parser's line number, exit 2. No traceback. |
| File missing, named explicitly | Error naming the expected path, exit 2 |
| File missing, not named | One skipped line, does not affect the exit code |
| File unreadable (permissions) | Error naming the path and the OS error, exit 2 |
| Top level is not a mapping | Error, exit 2 — no further check would be meaningful |
| PyYAML missing | Error pointing at `apt install python3-yaml`, exit 2 |
| `ownerp_validate.py` absent when delegated to | Warning plus the caller's previous behaviour, never a hard failure |

## Tests

Stdlib `unittest`, discovered by `python3 -m unittest discover -s tests` like
the rest of the suite. As with every other test module in this repository, a
PyYAML stand-in is installed before the module under test is imported, so the
suite runs on a machine without PyYAML — except for the template tests below,
which need a real parser and skip themselves when it is absent.

`tests/test_ownerp_validate.py` (new):

- **Positioned loading**: a mapping reports its own line; each key reports its
  own line; a nested mapping reports its own, not its parent's
- **Every check class** from the table above, one test per class, each
  asserting the severity, the path in the finding, and the line
- **Ports**: all four accepted forms, a bare `0` and a `70000` rejected, a
  non-numeric form rejected
- **Collisions**: two active containers sharing a port collide; the same pair
  with one `active: false` does not; duplicate names collide
- **Inactive downgrade**: a structurally broken inactive block yields warnings
  and exit 0; the same block active yields errors and exit 1
- **Unknown keys**: reported as a warning with the closest match; a key that is
  nothing like a known one is reported without a suggestion
- **Passwords**: a finding about `db_password` never contains its value
- **Exit codes**: 0 / 1 / 2 for clean, error, and unparseable input
- **Missing file**: named explicitly → exit 2; not named → skipped, exit 0

**The template cross-check** — the test that keeps the schema honest:

- `scripts/docker2update.yaml`, `scripts/docker2update-proxy-example.yaml` and
  `scripts/container2backup.yaml` validate **without a single error and without
  a single unknown-key warning**

Path warnings are expected there (the templates point at paths that exist only
on a real server) and are not asserted against. Without this test, a key added
to a template a year from now would silently become a false "unknown key" on
every customer server, and the typo check would be the first thing operators
learned to ignore.

`tests/test_update_docker_odoo.py` (extended):

- `--validate` leaves the configuration file byte-identical even when the DNS
  optimisation would have changed it
- `--validate` delegates to `ownerp_validate.py` when it is present beside the
  script, and passes the configured path through
- With the validator absent, `--validate` still works and warns

## Files

| File | Change |
|---|---|
| `scripts/ownerp_validate.py` | new, v1.0.0 |
| `scripts/update_docker_odoo.py` | v5.12.0: delegation, read-only `--validate` |
| `scripts/container2backup.py` | `--validate`, defensive `backup_path` read |
| `getScripts.py` | v9.12.0: distribute `ownerp_validate.py` |
| `fish/conf.d/33-aliases-backup.fish` | `doval` alias |
| `tests/test_ownerp_validate.py` | new |
| `tests/test_update_docker_odoo.py` | extended |
| `RELEASE_NOTES.md`, `CLAUDE.md`, `ReadMe.md`, `usage/AGENT.md`, `docs/INSTALLATION_GUIDE.md` (DE + EN) | documented |

## Out of scope for this building block

- **No Docker checks.** No `docker ps`, no port probing, no image lookup.
- **No `--json`.** Building block 3 adds it when it has a consumer.
- **No write path.** The validator opens files read-only. Nothing it finds is
  ever fixed automatically — that is building block 3.
- **No `--strict`.** Warnings do not fail the run, and nothing in the current
  workflow needs them to.
- **No schema for the other YAML files** in the repository
  (`hardening_config.yaml`, the nginx wizard's files). They have their own
  tools; adding them here would make the schema a dumping ground.

## Where building block 3 attaches

The assistants write a fully commented block into a list, or patch a single
field line-wise, and then run this validator against the result before they
save. The two things they need from block 2 are already here: findings that
carry a line number, and an exit code that separates "wrong" from "not there
yet".

The likely additions at that point are `--json` for a machine-readable finding
list, and a `--quiet` that prints nothing and only sets the exit code. Both are
small once the finding objects exist; neither is built now, because nothing
calls them yet.
