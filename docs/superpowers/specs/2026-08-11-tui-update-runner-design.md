# TUI Update Runner — Design

*11.08.2026 · building block 1 of 3 · status: implemented*

Written in English like the rest of the repository's documentation. The
conversation that produced it was German; the artefact follows the repo rule.

## Problem

An update is selected in `docker2update.yaml` and run with `doup`. Two fields
decide what happens: `active:` (does this system take part) and `type:`
(`M`odules / `F`ull / `N`eutralize — what the operator calls "the mode"). Both
live in a file that is otherwise touched once, at setup.

So an ad-hoc update today is: `edup` → mcedit → toggle `active`, change `type`
→ save → `doup` → afterwards edit the file back. With three systems that is
tedious. With twenty it is a source of mistakes — the file is left in a state
nobody intended, and the next scheduled run acts on it.

Nothing about the selection is configuration. It is a decision made per run.

## Decisions

Four questions were settled before design, each against alternatives:

**1. Stdlib `curses`, in a script of its own.** Not Textual, not a uv tool. The
root-run scripts on customer servers use system Python with `python3-yaml` and
`python3-dotenv` from apt — PEP 668 makes `pip install` as root fail, and
`python3-textual` is not available across all target distributions. A TUI that
cannot start on a server behind a proxy is worse than no TUI. `curses` ships
with Python itself and costs nothing to deploy.

**2. The TUI never writes to the YAML.** Selection, mode and comment are passed
to the runner as arguments. Nothing has to be turned back afterwards, and the
heavily commented config — which *is* the documentation for these files — is
never at risk. `active:` and `type:` remain the pre-selection.

**3. Run comments go to a central history and into the run log header.** One
line per container run in `~/update-history.jsonl`, plus a header line in the
run log the runner already writes. The central file is what lets the TUI answer
"what happened where, and why" while the operator is choosing.

**4. Three building blocks, TUI first.** TUI runner (this spec) → schema
validation → guided assistants. The daily pain first, so the TUI can be proven
in real use before it is made the default for `doup`.

## Architecture

The TUI executes nothing. It selects, leaves curses, and runs
`update_docker_odoo.py` as a subprocess.

```
ownerp_tui.py (curses)          update_docker_odoo.py         ~/update-history.jsonl
      │                                   │                            │
  reads docker2update.yaml (read-only)    │                            │
  reads history ────────────────────────────────────────────────────── ┤
      │                                   │                            │
  selection + mode + comment              │                            │
      │                                   │                            │
      └─ endwin() ─► subprocess ─────────►│                            │
                                    runs, writes ────────────────────► │
                                    run log + history line
      ◄──── exit code, back to list ──────┘
```

The runner keeps its logging, its per-instance run log, its lean console output
and its exit code. Wrapping a twenty-minute build in a curses window would mean
rebuilding all of that inside a pad the operator cannot scroll normally.

### Components

| Component | Responsibility |
|---|---|
| `scripts/ownerp_tui.py` (new, v1.0.0) | curses frontend: list, keys, dialogs. Deliberately thin. |
| `UpdateSelection` (class inside it) | Pure state: which systems, which mode, the comment. No curses call — this is what the tests drive. |
| `scripts/update_docker_odoo.py` (→ v5.11.0) | New flags, history writer, `-s` precedence fix |
| `~/update-history.jsonl` | One JSON line per container run |

The state/rendering split is the point of the design: everything worth testing
sits in `UpdateSelection`, and the drawing code stays small enough that there is
nothing in it to test.

## The screen

```
 ownERP Update                                    ~/docker2update.yaml
 ┌────────────────────────────────────────────────────────────────────┐
 │ [x] live-odoo    F   v18   03.08. F  ok        "eq_stock nachgez." │
 │ [ ] test-odoo    M   v18   28.07. M  ok                            │
 │ [ ] demo-odoo    N   v16   —                                       │
 │ [ ] alt-odoo     F   v16   11.07. F  2 errors                      │
 └────────────────────────────────────────────────────────────────────┘
 Space select   m mode   c comment   Enter start   v validate   q quit
```

Columns: selection, container name, mode, Odoo version, and the last run from
the history (date, mode, result, comment — truncated to the available width).

Checkboxes are pre-filled from `active:`, the mode column from `type:`. Both are
proposals; changing them changes nothing on disk.

### Keys

| Key | Action |
|---|---|
| `↑` `↓` / `j` `k` | Move the cursor |
| `Space` | Toggle selection |
| `a` | Select all / clear selection |
| `m` | Rotate the mode of the cursor row: `M` → `F` → `N` → `M` |
| `c` | Enter the run comment (applies to the whole run) |
| `Enter` | Start (confirmation dialog first) |
| `v` | Validate the configuration (leaves curses, runs `--validate`, returns on a keypress) |
| `d` | Toggle "use the TUI as the default for `doup`" |
| `?` / `h` | Help |
| `q` / `Esc` | Quit |

### Confirmation dialog

Before starting: the selected systems with their mode, the comment, and the
number of systems. **A selection containing `N` (Neutralize) requires a second,
explicit confirmation** naming the affected databases — neutralizing a live
database is destructive and must never be one keystroke away from a typo.

An empty selection cannot start; `Enter` reports that instead.

## Runner changes (`update_docker_odoo.py` → v5.11.0)

```
-s, --specific-container CONTAINER   repeatable, and accepts a comma-separated list
--type {M,F,N}                       runtime override of `type:` for the selected containers
--comment TEXT                       written to the run log header and the history
```

`-s live-odoo` keeps working exactly as before. Internally `-s` becomes a list;
the comparison at the container loop is adjusted accordingly.

**`-s` now overrides `active: false`.** Today the loop checks `active` *before*
the `-s` match, so an explicitly named but inactive container is skipped without
comment. That is wrong for a named selection — from the TUI and from the command
line alike. An unknown container name is an error with a non-zero exit, not a
silent no-op.

`--type` and `--comment` never touch the YAML.

### One run per mode

`--type` applies to every container of that invocation, but the TUI lets each
row carry its own mode. The TUI therefore **groups the selection by mode and
starts one runner invocation per group**, in the order the modes appear in the
list:

```
ownerp_tui.py → update_docker_odoo.py -s live-odoo,demo-odoo --type F --comment "..."
              → update_docker_odoo.py -s test-odoo            --type M --comment "..."
```

The alternative — a per-container syntax like `-s live-odoo:F` — was rejected:
it would complicate a flag that operators also type by hand, to save a process
start in a workflow that already runs for twenty minutes.

Consequences, specified so the implementation does not have to guess:

- The groups run **sequentially**, never in parallel.
- The comment is identical across groups; it describes the run, not the system.
- **The worst exit code wins.** A failing group does not stop the following
  ones — the operator selected them — but the TUI reports each group's result
  separately and returns the worst code when it exits.

## History (`~/update-history.jsonl`)

One JSON object per line, written by the **runner** — not by the TUI, so runs
started classically or from cron appear as well:

```json
{"ts": "2026-08-11T14:32:07", "container": "live-odoo", "database": "live_db",
 "mode": "F", "comment": "eq_stock nachgezogen", "result": "ok",
 "warnings": 0, "errors": 0, "duration_s": 812,
 "log": "/opt/odoo/live/update_20260811_143207.log", "script_version": "5.11.0"}
```

`result` is one of `ok`, `warnings`, `errors`, `failed`.

- **Written after each container**, not at the end of the run, so an interrupted
  run still leaves behind what it did.
- **Written atomically** (temp file + rename): a crash must not truncate the
  file.
- **Retention** via `defaults.history_retention_days` in `docker2update.yaml`,
  default 365, `0` keeps everything. Applied on write. Deliberately consistent
  with `log_retention_days`.
- **Never fatal.** A history that cannot be written costs a log line, not the
  update. Malformed lines are skipped on read.

## Making the TUI the default

A marker file, `~/.ownerp_tui_default`, toggled from inside the TUI (`d`) or
with `ownerp_tui.py --make-default` / `--no-default`. Per server, in the style of
the existing `~/.getscripts_configured` and `~/.dns_optimized_by_getscripts`.

`doup` becomes a Fish function with two hard exceptions:

```fish
function doup --description "Update Odoo containers (TUI when enabled)"
    if test (count $argv) -eq 0; and status is-interactive; and test -f $HOME/.ownerp_tui_default
        $HOME/ownerp_tui.py
    else
        $HOME/update_docker_odoo.py $argv
    end
end
```

Called with arguments → always the classic runner. **No TTY → always the classic
runner**, so no cron job can ever end up waiting inside a TUI. `ownerp_tui.py`
checks for a TTY itself as well; the belt does not rely on the braces.

The existing `doup` alias in `fish/conf.d/33-aliases-backup.fish` is removed —
in Fish an alias *is* a function, and one defined in `conf.d` would win over the
autoloaded one.

## Error handling

| Situation | Behaviour |
|---|---|
| No TTY | Refuses to start: message + exit 2, pointing at the classic invocation |
| `TERM=dumb`, curses fails to initialise | Same, with the actual curses error |
| Terminal below 80×20 | "Window too small (currently 71×18)", no half-drawn screen |
| Terminal resized | `KEY_RESIZE` handled, list redrawn |
| Broken YAML | Parser error **with line number** in a dialog, offering to open it at that line in mce. No traceback |
| Missing YAML | Clear message naming the expected path (building block 3 takes over here later) |
| Ctrl-C / any exception | `curses.wrapper` restores the terminal in every case — a wrecked terminal after a crash is what operators hold against TUIs |
| Broken history | Malformed lines skipped, never fatal |
| Runner fails | Exit code passed through; result shown per mode group, then a keypress returns to the list — the runner's output stays on screen until then |

## Tests

Stdlib `unittest`, discovered by `python3 -m unittest discover -s tests` like the
rest of the suite.

`tests/test_ownerp_tui.py` (new), driving `UpdateSelection` with no curses on
screen:

- Pre-selection from `active:`, mode from `type:`
- Toggle selection, select-all / clear
- Mode rotation `M` → `F` → `N` → `M`
- An empty selection cannot start
- Building the runner argument lists from a selection (the arguments are the
  contract between the two scripts, so they get asserted verbatim): one list per
  mode group, mixed modes produce several, a single mode produces exactly one
- A selection containing `N` is flagged as requiring extra confirmation

`tests/test_update_history.py` (new) and `tests/test_update_docker_odoo.py`
(extended):

- `-s` repeated and comma-separated
- `--type` overrides the YAML value, and the YAML file is byte-identical
  afterwards
- `--comment` reaches both the run log header and the history line
- `-s` overrides `active: false`; an unknown name exits non-zero
- History: write, read, ordering, malformed line skipped, retention by days,
  `0` keeps everything, atomic replacement

The curses drawing layer is not tested.

## Files

| File | Change |
|---|---|
| `scripts/ownerp_tui.py` | new, v1.0.0 |
| `scripts/update_docker_odoo.py` | v5.11.0: flags, history, `-s` precedence |
| `getScripts.py` | distribute `ownerp_tui.py` via `copy_scripts()` |
| `fish/functions/linux/doup.fish` | new: the TTY/argument switch |
| `fish/conf.d/33-aliases-backup.fish` | remove the `doup` alias, add `tui` |
| `tests/test_ownerp_tui.py` | new |
| `tests/test_update_docker_odoo.py` | extended |
| `RELEASE_NOTES.md`, `CLAUDE.md`, `docs/INSTALLATION_GUIDE.md` (DE + EN) | documented |

## Out of scope for this building block

- No backup TUI — `dobk` is untouched. That is building block 3.
- No schema validation. `v` calls the existing `--validate` for now; real
  checking is building block 2.
- No write path from the TUI into any YAML. None, no exception.
- No live progress inside the curses window. The runner writes to the terminal.

## Where the next two blocks attach

**Block 2 (validation)** replaces what `v` calls: required fields, types, port
collisions, paths that must exist, duplicate container names. It is usable from
the command line without the TUI, and it is the check the assistants run against
what they are about to write.

**Block 3 (assistants)** adds a second menu to the TUI: onboard a new server,
maintain the backup configuration. It writes by appending a fully commented
block to the list, and by patching individual fields line-wise — the approach
`save_updated_config()` already uses, so comments and formatting survive intact.
