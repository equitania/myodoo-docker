# ownERP Console — Design

*13.08.2026 · supersedes building block 1 of 3 · status: implemented,
stages 0–3*

> **Two corrections the implementation forced.** The collector could not live
> in `lib/` (see the note under Architecture). And the Textual pin `>=1.0,<2`
> was already three majors stale — the current release is 8.2.x, so the ship
> pin is `>=8,<9`. Both are recorded where they belong rather than quietly
> fixed, because a spec that disagrees with the code teaches people to stop
> reading it.
>
> One item is **deliberately not done**: `ownerp_tui.py` still ships. Removing
> it is correct only once the console has been used on a real server, and
> until then the TUI is the fallback if the console turns out to have a
> problem this machine could not show.

Written in English like the rest of the repository's documentation. The
conversation that produced it was German; the artefact follows the repo rule.

---

## Why this replaces the TUI

`ownerp_tui.py` (v1.2.0, specified in `2026-08-11-tui-update-runner-design.md`)
was built as a front end for `doup`: a checkbox list of Odoo containers, a mode
letter, a comment, then hand off to the runner. Everything an operator needs
that is *not* an update run was bolted onto that screen as a single keystroke —
`v` validate, `w` edit the YAML, `t` the maintenance cron, `d` make the TUI the
`doup` default. Four foreign objects behind four letters, on a screen that shows
none of their context.

The verdict from the field was that it is not usable. The diagnosis is not that
it is ugly; it is that it answers a question nobody asks. Operators do not need
help *choosing which containers to update* — `doup -s live` has always done
that. They need to see what state the server is in, and they need to change
configuration without hand-editing YAML.

Concretely, measured against what is there today:

| Defect | Evidence |
|---|---|
| Foreign objects behind bare keys | `v`, `w`, `t`, `d` on a screen listing only containers |
| Backup does not exist in it at all | `CONFIG_FILE` is `docker2update.yaml` and nothing else (`ownerp_tui.py:69`) |
| Shows selection, not state | one "last run" column; no backup age, disk headroom, certificate expiry, nginx state |
| Raw input | `curses.getstr`, 120 bytes, no editing (`ownerp_tui.py:361`) |
| No colour, scrollbar, sorting or filtering | `draw()` uses only `A_BOLD` and `A_REVERSE` |

## Scope — what the console does and does not do

| Does | Does not |
|---|---|
| Show server state | Start updates |
| Edit `docker2update.yaml` | Start backups |
| Edit `container2backup.yaml` | Touch containers |
| Edit the maintenance cron | Delete anything |
| Validate both configurations | Renew certificates |

This boundary is the design. A tool that starts nothing long-running needs no
process supervision, no cancellation path, no log pane, no partial-failure
recovery: every action either completes in well under a second or fails with a
message. `doup` and `dobk` stay exactly what they are.

The console is **never the only route to anything**. Every function it offers
also exists as a command (`dostat`, `wiz`, `docron`, `doval`). That is what
makes it safe to depend on a library for it.

## Architecture

Two layers, and the lower one does not know Textual exists.

> **Correction from stage 1 (13.08.2026).** `lib/` is wrong: `copy_scripts()`
> delivers flat files to `$HOME` and has never delivered `scripts/lib/`, which
> exists for getScripts.py's own use inside the cloned repository. A collector
> there would not exist on any server. It ships as `scripts/ownerp_state.py`
> beside its siblings, following the pattern `ownerp_cron.py` and
> `ownerp_validate.py` already prove out. `config_writer` in stage 2 becomes
> part of `ownerp_wizard.py`'s importable surface for the same reason. The
> layering below is unchanged; only the file names are.

```
lib/server_state.py      pure Python, no Textual import, fully unit-testable
   ├─ instances()        docker2update.yaml + docker ps + run history
   ├─ backups()          container2backup.yaml + real files on disk (age, size)
   ├─ maintenance()      ownerp_cron.py
   └─ health()           server-readiness.py + disk headroom + cert expiry

lib/config_writer.py     the write API that does not exist today
   └─ set_field(), add_instance(), add_database()
      backup → temp file in the same directory → ownerp_validate.py → os.replace()

ownerp_console.py        Textual. Renders, delegates, decides nothing.
```

**Why the core carries no Textual import.** Tests run without the library, and
`dostat` — the whole server state as one page of text, usable from cron or
mail — falls out of the same code with no extra work. A UI layer that owns data
access cannot be tested and cannot be reused; this one owns neither.

**The refactor this forces.** `ownerp_wizard.py` is a question-and-answer chain
at the terminal, and its write path is welded into that chain — a form cannot
call it. The write path moves to `lib/config_writer.py`; the wizard keeps its
CLI and calls the same function. This is real work on existing code, and it pays
twice: `container2backup.yaml` has no editor today, in any form.

**Write discipline is inherited, not reinvented.** `config_writer` follows the
sequence `ownerp_wizard.py` and `ownerp_cron.py` already prove out: timestamped
backup, build in memory, temp file *in the same directory*, validate that file,
`os.replace()`. Errors leave the original byte-identical. There is exactly one
write path per file, and the console does not get its own.

## Screens

**Overview** (start) — four tiles, each a number and a state:

```
 ownERP  ucore                                    13.08.2026 17:04

 ┌ Instances ────────┐ ┌ Backup ─────────────┐
 │ 2 active          │ │ live_db   4 h  1.2 G│
 │ live   16.0  ok   │ │ test_db   4 h  340 M│
 │ test   16.0  ok   │ │ target: 61 % used   │
 └───────────────────┘ └─────────────────────┘
 ┌ Maintenance ──────┐ ┌ System ─────────────┐
 │ 6 jobs, 1 off     │ │ nginx    ok 12 vhost│
 │ backup  02:00 ok  │ │ certificates 42 days│
 │ cleanup 03:30 ok  │ │ 3 security updates  │
 └───────────────────┘ └─────────────────────┘

 1 instances  2 backup  3 maintenance  4 system  r reload  q quit
```

**Instances / Backup** — a sortable table; Enter opens a form carrying every
field of that entry. Password fields are masked, never echoed, never logged. A
save runs through `config_writer`; a validation error is shown against the field
that caused it and the file on disk is untouched.

**Maintenance** — job list with schedule, last run and an on/off switch;
rescheduling is a form with immediate range checking. `25` for the hour is
rejected at the field, because cron accepts it and then never fires the job —
the exact mistake `ownerp_cron.py` exists to prevent.

**System** — `doval` and `server-readiness.py` in one view, every finding
carrying the command that fixes it.

## Stages

Each stage leaves something usable behind. If stage 3 is abandoned, 1 and 2
still stand on their own.

| Stage | Deliverable | Value on completion |
|---|---|---|
| **0** | `ownerp_migrate.py` review routing (below) | the reconstructed backup file reads correctly |
| **1** | `lib/server_state.py` + `dostat` | server state as a text page, also from cron/mail — no Textual yet |
| **2** | `lib/config_writer.py`, wizard moved onto it, backup config added | `wiz` can finally edit backup entries — a pure CLI gain |
| **3** | `ownerp_console.py` (Textual) | the console |

## Stage 0 — review routing in `ownerp_migrate.py`

`reconstruct()` returns one flat `review` list, and `reconstruct_from_docker()`
hands the same list to both renderers (`ownerp_migrate.py:927` and `:932`). The
header of a reconstructed `container2backup.yaml` therefore carries, verbatim,
notes about `type`, `delay_time`, `translate`, `odoo_version`, port 8072 and the
build folder — six things that do not exist in a backup configuration. The
update header meanwhile carries `retention_days`, which exists only in the
backup one.

Each note gains a target at the point it is raised — `update`, `backup` or
`both` — and `_provenance()` filters on it. Nothing about collection changes,
only delivery.

| Note | Target |
|---|---|
| `db_user could not be read` | both |
| `db_password is not in the container environment` | update — the backup config has no `db_password` key |
| `port 8069 / 8072 is not published` | update |
| `N databases behind X — pick the right one` | both |
| `could not list databases in X` | both |
| `odoo_version could not be determined` | update |
| `build folder does not exist` | update |
| `type, delay_time and translate were operator choices` | update |
| `retention_days is not recoverable` | backup |
| `FastReport container(s) found` | backup |
| `no Odoo container found` / `docker returned nothing` | both |

**A second defect surfaces while fixing the first, and it is the worse one.** A
backup row is only appended when the database name resolved
(`ownerp_migrate.py:735`). When it did not, that instance is missing from
`container2backup.yaml` **silently** — the file looks complete and one
production database is simply not backed up. A wrong header is cosmetic; this
loses data. Stage 0 therefore also raises a backup-targeted note naming every
instance that did not make it into the file.

Tests: that `type`/`delay_time` never appear in a backup header, that
`retention_days` never appears in an update header, and that an unresolved
database produces an explicit backup-targeted note.

## Delivery and risk

The script stays a single file. A PEP 723 header declares the dependency and it
is started with `uv run --with 'textual>=1.0,<2'` — uv resolves once and caches.
`getScripts.py` warms that cache at install time so a customer's first start
does not depend on the network at that moment. If Textual is unavailable
anyway, `konsole` says so in one sentence and names `dostat`, `wiz`, `docron`
and `doval`, all of which keep working on their own.

`uv` is already a prerequisite on every ownERP server (`getScripts.py:1885`,
tool installation from `:4082`), so this adds a package, not a platform.

**Removed:** `ownerp_tui.py`, the `.ownerp_tui_default` marker and the TUI
branch in `doup`. `doup` goes back to being what it was.

**Retained deliberately:** the rule that the console writes only through the
existing validated write paths. It gets no file handle of its own.

## Testing

The state layer and the write API are `unittest`, like everything else in
`tests/`. The interface is tested through Textual's `run_test()` pilot for the
key paths and for behaviour on invalid input — a form that accepts hour `25`
fails the suite rather than the server.
