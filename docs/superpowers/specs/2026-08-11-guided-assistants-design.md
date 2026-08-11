# Guided Assistants — Design

*11.08.2026 · building block 3 of 3 · status: specified*

Written in English like the rest of the repository's documentation. The
conversation that produced it was German; the artefact follows the repo rule.

## Problem

Adding a new Odoo instance to `docker2update.yaml` today means opening the file
in mcedit, copying an existing container block, and changing twelve values by
hand. Ten of the sixteen keys are mandatory, two are host ports that must not
collide with anything already in the file, one is a path that must exist, and
one is a password.

Nothing checks the result until `doup` runs. Building block 2 changed that —
`doval` now reports what is wrong, with a line number. But it reports *after*
the mistake has been made and saved.

The same applies to `container2backup.yaml`, where the consequence is worse:
a badly configured backup looks like it worked until someone needs a restore.

## The rule this block breaks

Building blocks 1 and 2 were emphatically read-only. The TUI's design says
*"No write path from the TUI into any YAML. None, no exception."* The
validator's says *"Read-only, without exception."*

This block writes. That is its entire purpose, and it is why the safety
mechanics below are the substance of this design rather than an appendix.

## Decisions

**1. A script of its own, in Python, that imports the validator.** Building
block 2 deliberately rejected an import — a missing file must not stop the
runner from starting. The argument inverts here: an assistant that cannot
validate must not write at all, so it has nothing to degrade to. And it needs
more than a verdict — it needs the **schema itself** to know which fields
exist, which are mandatory, and which values are allowed. A subprocess returns
text and an exit code; an import returns `CONTAINER_FIELDS`.

**2. Line-wise editing via the positioned loader.** `PositionedDict.key_lines`
already maps every key of every mapping to its line. A field edit is therefore
"replace exactly line N, preserve the indentation" — not a text search.

The alternative in the repository, `save_updated_config()`, scans forward from
`container_name: "X"` for the next line containing `volume:`. Its own docstring
admits the approach: *"SIMPLE and WORKING approach: Replace volume lines
directly using string replacement. This avoids complex YAML parsing issues."*
If a container's `volume:` sits above its `container_name:`, the value lands in
the **next** container. Building block 1's design pointed at this function as
the model to follow; that was wrong, and this design does not follow it.

**3. Write to a temporary file, validate, then replace atomically.** The
customer's file is never opened for writing. A rejected result leaves it
untouched, byte for byte.

**4. Scalars only.** `pre_build_files` and `proxy` are a list and a mapping.
Editing those line-wise is a different class of problem — a value that spans
lines has no single line to replace. They are shown, never edited. mcedit keeps
that job.

**5. Create, edit, never remove.** Removing an entry is the one operation a
backup does not make harmless, because the operator may not notice for weeks.
It stays manual.

## Architecture

```
                    ┌───────────────────────────┐
ownerp_tui.py ─ w ─►│                           │  imports (same directory)
                    │   ownerp_wizard.py        ├──────────► ownerp_validate.py
alias `wiz` ───────►│                           │            CONTAINER_FIELDS
                    │   asks, suggests, writes  │            load_positioned()
                    └─────────────┬─────────────┘            validate_update()
                    ┌─────────────▼─────────────┐
                    │  <config>.tmp             │
                    │  validate_update(tmp)     │
                    │       │            │      │
                    │   findings      clean     │
                    │       │            │      │
                    │   discard    os.replace() │
                    └───────────────────────────┘
```

The wizard executes nothing else. It does not run Docker, does not start a
container, does not touch the build folder beyond the one directory it offers
to create.

### Components

| Component | Responsibility |
|---|---|
| `scripts/ownerp_wizard.py` (new, v1.0.0) | prompts, suggestions, the write mechanics |
| `UPDATE_FORM` (inside it) | what to ask, in what order, with what help and default |
| `safe_write(path, new_text)` | temp file → validate → `os.replace`, or discard |
| `append_container(...)` / `patch_field(...)` | the two write operations |
| `scripts/ownerp_validate.py` | unchanged — imported for its schemas and its checks |
| `scripts/ownerp_tui.py` (→ v1.1.0) | one new key, `w`, launching the wizard |

## Schema and form are not the same thing

`CONTAINER_FIELDS` says a `port` must parse as a port and is required. It does
not say what to call it on screen, in what order to ask, what to suggest, or
why it matters. That is a **form**, and it is separate:

```python
UPDATE_FORM = [
    Field("container_name",   "Container name",
          help="Docker container name, e.g. live-odoo",
          suggest=suggest_container_name),
    Field("database_name",    "Database name",
          help="The Odoo database this container serves"),
    Field("type",             "Update mode",
          help="M = modules only, F = full, N = neutralize first"),
    Field("port",             "HTTP port",
          help="Host port, mapped to 8069 inside the container",
          suggest=suggest_free_port),
    ...
]
```

**The form is checked against the schema by a test**: every field the schema
marks `required` must appear in `UPDATE_FORM`, and every field the form asks
for must exist in the schema. This is the same guard that keeps the shipped
templates honest in building block 2 — the place drift appears when nobody is
looking.

## What makes it an assistant

The wizard reads the existing configuration before it asks anything, and
proposes values from it. The operator mostly confirms.

| Field | Suggestion |
|---|---|
| `port`, `longpolling_port` | the next free host port — it knows every port already used, across **both** fields, because they share one namespace |
| `db_user`, `db_host` | the value used by the existing entries, when they agree |
| `dockerfile_path` | the shared pattern of the existing paths, with the new container name substituted |
| `docker_image_name` | the shared prefix of the existing image names |
| `odoo_version`, `delay_time`, `translate`, `db_password_via_env` | the majority value among existing entries, else the shipped default |
| `type` | `F` |
| `active` | `true` |

A suggestion is shown in brackets and taken by pressing Enter. An empty
configuration falls back to the shipped template's values, so the first
container on a fresh server is still a guided walk rather than a blank form.

`db_password` is never suggested, never echoed (`getpass`), and never appears
in the confirmation summary — it is shown as `********`.

## The two write operations

### Appending a new container

The new entry is appended to the end of the `containers:` list as a **fully
commented block**, matching the shape of the shipped template — the operator
who opens the file next should not be able to tell whether a block was typed or
generated.

The insertion point is the end of the file when `containers:` is the last
top-level key, which it is in every shipped layout. When it is not, the
insertion point is the line before the next top-level key, found through the
positioned loader rather than by pattern.

Appending cannot damage an existing entry: no existing line is touched.

### Patching one field

```
load_positioned(path)  →  containers[3].key_lines["port"]  →  line 107
line 107: '    port: "127.0.0.1:11000"'
          └── indentation preserved, key preserved, value replaced
```

Only the value is rewritten. Any trailing comment on that line is preserved —
an operator's note about why a value is what it is must survive an edit of that
value.

A field that is absent from the entry has no line to patch. It is inserted
after the last line of that entry's mapping, at the entry's indentation.

## Safety mechanics

This is the part that matters, so it is stated as a sequence with no branches
left implicit:

1. Read the current file. If it does not parse, refuse — the wizard will not
   edit a file it cannot understand, and `doval` already reports why.
2. Copy it to `<path>.bak-<YYYYmmdd_HHMMSS>`. Every run, before anything.
   Timestamped, like `ngx-conf-wizard.sh` — never a single `.backup` that the
   next run overwrites.
3. Build the new text in memory.
4. Write it to `<path>.tmp-<pid>` in the same directory — same filesystem, so
   the replacement is atomic.
5. Run `validate_update()` on the temporary file.
6. **Errors → discard the temporary file, keep the original, show the
   findings.** The operator's input is retained so they can correct it rather
   than start over.
7. **Clean → `os.replace(tmp, path)`.** Warnings do not block: a path that does
   not exist yet is the normal state for a container being created.
8. Report what was written and where the backup is.

An interruption at any point before step 7 leaves the original file untouched.

**The backup is kept only when the original was actually replaced.** A backup
identical to a file nobody changed is litter, and litter in the operator's home
directory trains people to ignore `.bak-*` files — which is exactly the wrong
habit for the one case where the backup matters. So: step 7 taken → backup
stays; validation rejected, operator aborted, or the wizard crashed → the
backup and the temporary file are both removed.

### Refusals

| Situation | Behaviour |
|---|---|
| No TTY | Refuse, exit 2, naming the classic invocation. A wizard has no business in a cron job |
| `ownerp_validate.py` not importable | Refuse, exit 2, naming `ups`. Writing without validating is exactly what this block exists to prevent |
| The configuration does not parse | Refuse, exit 2, pointing at `doval` for the line number |
| A duplicate container name is entered | Rejected at the prompt, not at validation — the wizard knows the existing names |
| The operator aborts | Nothing is written; the backup made in step 2 is removed again, so an aborted run leaves no litter |

### The one filesystem write

When `dockerfile_path` does not exist, the wizard says so and offers to create
the empty directory. On confirmation it does, and nothing else — no Dockerfile,
no `odoo.conf`, no `bin/`. Populating a build folder belongs to
`odoo_build_cache.py` and `sync_build_scripts()`, and a wizard that started
copying build scripts would be a second, competing deployment path.

## Command line

```
ownerp_wizard.py                    # menu: add a server / edit a field
ownerp_wizard.py --update [PATH]    # docker2update.yaml   (default ~/docker2update.yaml)
ownerp_wizard.py --version
```

Alias `wiz`. `--backup` is specified in "Out of scope" below.

`ownerp_tui.py` gains one key, `w`, which leaves curses, runs the wizard as a
subprocess, and reloads the container list on return — the same shape its `v`
key already uses for validation.

## Tests

Stdlib `unittest`, discovered by `python3 -m unittest discover -s tests`.
`tests/test_ownerp_wizard.py` (new). The prompting layer is not tested; every
prompt is a thin call around one pure function, and those are what the tests
drive.

- **Form ⇄ schema**: every `required` field of `CONTAINER_FIELDS` appears in
  `UPDATE_FORM`; every field in `UPDATE_FORM` exists in `CONTAINER_FIELDS`
- **Suggestions**: next free port skips both `port` and `longpolling_port` of
  every entry, active or not; a unanimous `db_host` is suggested, a split one
  is not; the path pattern substitutes the new name; an empty configuration
  falls back to the template defaults
- **Appending**: the result parses; the new entry is present with every entered
  value; **every pre-existing line is byte-identical**; the file still validates
- **Patching**: the target line changes and no other line does; indentation is
  preserved; a trailing comment on that line survives; an absent field is
  inserted at the right indentation
- **Safety**: a rejected result leaves the original byte-identical; the backup
  exists and matches the original; an abort leaves no `.tmp` and no backup;
  `os.replace` is used rather than a copy
- **Refusals**: no TTY, unparseable configuration, duplicate container name
- **Passwords**: `db_password` never appears in the summary or in any log line

The append and patch tests operate on the shipped `scripts/docker2update.yaml`
as their fixture, so the tests fail if the template's shape changes in a way
the wizard cannot handle.

## Files

| File | Change |
|---|---|
| `scripts/ownerp_wizard.py` | new, v1.0.0 |
| `scripts/ownerp_tui.py` | v1.1.0: the `w` key |
| `getScripts.py` | distribute `ownerp_wizard.py` |
| `fish/conf.d/33-aliases-backup.fish` | `wiz` alias |
| `tests/test_ownerp_wizard.py` | new |
| `RELEASE_NOTES.md`, `CLAUDE.md`, `ReadMe.md`, `usage/AGENT.md`, `docs/INSTALLATION_GUIDE.md` (DE + EN) | documented |

## Out of scope

- **The backup assistant.** `container2backup.yaml` gets the same treatment in
  a follow-up, reusing `safe_write`, `append_*` and `patch_field` unchanged.
  Splitting it out keeps this block to one testable deliverable, and the update
  configuration is where the field count and the collision risk are.
- **Removing entries.** Manual, deliberately.
- **Editing lists and nested mappings** (`pre_build_files`, `proxy`).
- **Anything outside the YAML** except the one offered directory.
- **Reformatting.** The wizard changes the lines it was asked to change and
  nothing else. It is not a formatter.
