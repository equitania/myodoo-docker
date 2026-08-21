# Muting a readiness check — Design

*21.08.2026 · status: specified, not yet implemented*

Written in English like the rest of the repository's documentation. The
conversation that produced it was German; the artefact follows the repo rule.

---

## Why this exists

Two servers, one shape of complaint.

A customer host runs its own certificates — bought, or issued by an internal
CA, not by Let's Encrypt. `certbot` is nevertheless installed, so its timer
exists and fires on the distribution's stock schedule. `check_certbot_timer_window()`
duly reports:

```
[WARN] certbot timer    stock schedule — a renewal can land in the 06:00-07:00 apt window
                        Fix: bash /root/myodoo-docker/scripts/bootstrap.sh --harden
```

The finding is **correct**. The check is not broken — it already SKIPs where no
`certbot.timer` is present (`server-readiness.py:722`). It simply describes a
risk this host does not carry, because nothing here ever renews a certificate.

A test server has no backups by design. `check_backup_recency()` reports:

```
[FAIL] Backup recency   last backup activity 34.9 d ago
                        Fix: dobk   # run a backup now, then check the cron schedule
```

Also correct, also irrelevant, and worse than the first: it is a `FAIL`, so
`server-readiness.py` exits 1, and the Monday cron mails about it every week
forever.

Both appear in four places at once, because all four run the same checks:
`chk`, `dostat`/`konsole`, the block `getScripts.py` prints after every `ups`,
and the weekly cron.

The failure mode is not the noise itself. It is what the noise does to the
report: an operator who has learned that two lines are always there stops
reading the block, and the third line — the one that matters — goes with them.
The same reasoning is already written into this repository twice, for
`BENIGN_CHILD_NOISE` in `update_docker_odoo.py` and for `OPTIONAL_INSTRUCTIONS`
in `odoo_build_cache.py`: *a warning for a correct state is silenced, not
hidden*. This design extends that principle from two hard-coded lists to a
per-host decision.

## What it is not

Not a way to turn checks off. A muted check still runs, still produces its
finding, and still shows it in the full report — with the reason it does not
count here. What changes is its weight: it drops out of `--brief`, out of
`--quiet`, and out of the exit code.

The distinction matters for the server nobody has looked at in a year. A check
that was *removed* leaves a report that looks complete while a whole class of
faults goes unwatched. A check that is *muted* leaves a line saying so, with a
date and a sentence explaining why.

---

## The `MUTED` severity

`Severity` (`server-readiness.py:126`) gains a fifth member. `Finding` is
unchanged; muting rewrites a finding's severity and appends its reason to
`detail`, leaving `title` and the original text intact.

| Channel | Behaviour |
|---|---|
| `mode="full"` | shown, with the reason on the finding's own line |
| `mode="brief"` | not shown — treated exactly like `OK` |
| `mode="quiet"` | not shown, and does not by itself cause output |
| exit code | never contributes; only `FAIL` still returns 1 |
| summary line | `· N muted`, **always**, in every mode |

The summary counter is not decoration. A report that quietly omits part of
itself is lying about its own coverage; the count is what keeps `[MUTED]` an
honest state rather than a hiding place. It is the one part of muting that
`--brief` may not suppress.

`--quiet` keeps its existing rule that only `WARN`/`FAIL` trigger output.
`MUTED` therefore never wakes the Monday mail, which is the point.

### Rendering

Two mechanical consequences in `print_report()` that are easy to miss and will
misalign every line if they are:

- `label = f"[{finding.severity.value}]".ljust(6)` (`server-readiness.py:892`)
  assumes a four-character name. `[MUTED]` is seven characters — `ljust(7)`.
- The fix-continuation indent `" " * (11 + width)` (`server-readiness.py:896`)
  is derived from that width and becomes `12 + width`.

`_palette()` gives `MUTED` the dim attribute, not a colour: it is deliberately
the quietest thing on the page.

---

## Two sources for a mute

### Explicit — `readiness-mutes.conf`

`/root/.config/myodoo-docker/readiness-mutes.conf`, one muted check per line:

```
# Managed by ownerp_mute.py — one muted readiness check per line.
# Format:  <check_id> | <YYYY-MM-DD> | <reason>

certbot_timer_window | 2026-08-21 | customer runs their own certificates
```

The directory is the one `container2backup.py`, `server_hardening.py` and
`nginx-cert-guard.py` already read from, so nothing new has to be created or
documented as a location.

The reader resolves it as `os.path.join(ctx.home, ".config/myodoo-docker",
"readiness-mutes.conf")`, not as an absolute constant. `HealthContext` exists so
the checks can be exercised against a throwaway directory tree
(`server-readiness.py:144`); a hard-coded `/root/...` would make every mute test
depend on the real machine, and the tests listed below would be unwritable.

**Why not YAML**, against the repository's own "YAML as the primary
configuration format" rule: `server-readiness.py` runs today without PyYAML —
it imports `yaml` locally inside `_load_backup_config()` and SKIPs that one
check when the import fails. A YAML mute file would invert that: on a host
without PyYAML every mute would silently stop applying and the operator would
get back precisely the messages they had switched off, with no line anywhere
saying why. A three-field line format cannot fail that way. Robustness beats
format consistency for a file whose whole job is to stay quiet.

**Why not the existing `.env`**: it holds `ALERT_SMTP_PASS` at mode 0600. A
switch operators are meant to touch regularly does not belong in the file that
holds credentials, and `KEY=value` has no room for a date and a reason.

### Derived — a deliberately disabled cron job

`check_backup_recency()` first asks whether `container2backup` is switched off
in `/etc/cron.d/myodoo-maintenance`. `ownerp_cron.py` parks a disabled job
behind `#OWNERP-DISABLED#` rather than deleting it, and `server-readiness.py`
can already read that: `_disabled_cron_lines()` (`:234`) and
`_normalise_cron_line()` (`:244`, reduces script paths to their basename) exist
and need no change.

If the job is off, the finding becomes:

```
[MUTED] Backup recency  last backup activity 34.9 d ago
                        cron job disabled on this host
```

No entry in `readiness-mutes.conf`, and no second place to keep the same fact.
The cron file *is* the truth about that case; an operator who re-enables the
job gets the check back in the same keystroke, with nothing left behind to
clean up.

Derivation exists only where an ownERP-managed job's absence explains the
finding. There is exactly one such pair today (`container2backup` →
`backup_recency`). It is expressed as a small table next to `MANAGED_JOBS`
rather than as an `if` inside the check, so a second pair is a line of data.

For `certbot_timer_window` there is no ownERP job to disable — that is why the
explicit route has to exist at all.

---

## `ownerp_mute.py` — the write path

`server-readiness.py` states in its header that it **never writes**, and that
promise is worth more than the convenience of a `--mute` flag on it. Ownership
splits the way it already does elsewhere in this repo: `ownerp_state.py` reads
and `ownerp_wizard.py` / `ownerp_cron.py` write.

New module, `ownerp_mute.py` v1.0.0, following `ownerp_cron.py`'s write path
step for step:

1. timestamped backup
2. build the new content in memory
3. temp file **in the same directory**
4. re-read and validate that file
5. `os.replace()`

Mode `0600` is set **before** the rename, not after — the same ordering
`ownerp_cron.py` uses for its 0644, and for the same reason: a file must never
exist at the destination with the wrong mode, however briefly.

On a validation failure the temp file and the backup are removed and the
original is left byte-identical. There is no partial write.

### Interface

```
ownerp_mute.py --list
ownerp_mute.py <check_id> --reason "<text>"
ownerp_mute.py --unmute <check_id>
```

Plus an API with no terminal in it — `load()`, `mute()`, `unmute()`, each
returning a result object — so the console drives the same code the CLI does.
`ownerp_wizard.py` was given the same shape for the same reason: the path used
less often must not be a second implementation that can rot unnoticed.

### What it refuses rather than guesses

**No `--reason`, no mute.** An entry without a justification is a puzzle a year
later, and puzzles get deleted rather than understood — which brings the
message back on a host where somebody once decided it should not appear. The
reason is the only field that makes the entry survivable, so it is mandatory.

**Unknown `check_id`** is rejected at the prompt, listing the valid ids.

Getting that list is the one non-obvious mechanic here. A `check_id` does not
exist until its check has run — `CHECKS` (`server-readiness.py:804`) is a tuple
of functions, and the id lives in the `Finding` each one returns. So
`ownerp_mute.py` loads `server-readiness.py` by path (the `_load_module()`
pattern from `ownerp_state.py:274`; these scripts carry hyphens and are not on
the import path) and calls `run_checks()`, collecting `f.check_id`. That costs a
second or two of `systemctl` and `docker` calls on an interactive command, which
is the right price: every alternative — a `CHECK_IDS` constant, an id argument
on the registration — is a second list that can drift away from the findings the
report actually produces, and a mute pointing at an id nothing emits is exactly
the silent failure this section is about.

**A stale entry** — a `check_id` in the file that no longer exists, because a
check was renamed or withdrawn — produces its own `WARN` in the report:

```
[WARN] Mute registry    1 entry names an unknown check: backup_freshness
                        Fix: ownerp_mute.py --unmute backup_freshness
```

Without this the failure is silent and confusing in the worst way: the message
simply returns one day and the file still looks like it should be preventing
it.

---

## Operating it

`chk --muted` lists the entries with reason and date. Display only —
`server-readiness.py` still never writes, and the flag is a report mode like
`--brief`.

`konsole` → System tab → `[m]` mute, `[u]` unmute. Three concrete changes:

- `_fill_system()` (`ownerp_console.py:640`) must populate `self._rows["system"]`,
  which it does not today; row selection is what the action menu hangs off.
- Its severity marker dict gains `"MUTED": "off"`.
- `ACTIONS` (`:661`) gains a `"system"` entry.

Muting from the console needs a reason, exactly as the CLI does — a modal with
one field, not a bare toggle.

**This reverses a documented decision.** `CLAUDE.md` records that the System
tab deliberately has no actions, *"because readiness findings are facts, not
settings."* With this feature they are both: the finding stays a fact, and its
relevance **on this host** becomes a setting. The `CLAUDE.md` entry is rewritten
to say that, rather than the old sentence being quietly dropped — a design note
that disagrees with the code teaches people to stop reading the notes.

`ownerp_state.py` needs no change to `worst()`: it collects
`finding.severity.value` into a list and asks only whether `"FAIL"` or
`"WARN"` is in it (`:748`), so an unknown `"MUTED"` string is already ignored.
`_system_lines()` already filters on `("WARN", "FAIL")` (`:959`), so the
Overview tile already excludes muted findings. Both are covered by tests rather
than by assumption — they work by accident today and should keep working on
purpose.

---

## Deliberately out of scope

**No expiry date.** Both driving cases are permanent: a test server that will
never have backups, a customer who will never use Let's Encrypt. An `expires`
field would mean a field to maintain, an expiry check to run, and an "expired
mute" finding to report — for a need that does not currently exist. The risk it
would guard against, a mute nobody remembers, is already covered by the visible
`[MUTED]` line and the `· N muted` counter that appears in every mode.

**No wildcard or category mutes.** One id, one line, one reason.

**No mute for anything outside the readiness report.** If certificate noise
also reaches the customer by mail from `ssl-renew.sh` or `nginx-cert-guard.py`,
that is a second channel with its own delivery path and its own design; it is
not folded in here on suspicion. `nginx-cert-guard.py` already has
`GUARD_IGNORE_DOMAINS` for its own case.

---

## Delivery, tests, versions

`ownerp_mute.py` must be added to **both** lists or the result is silently
inconsistent:

- `copy_scripts()` in `getScripts.py:3898` — otherwise `ups` never installs it.
- `DELIVERED_SCRIPTS` in `server-readiness.py:88` — otherwise the script-version
  check never notices a server running a stale copy.

`tests/test_delivered_scripts.py` holds that pairing.

New `tests/test_ownerp_mute.py`. The cases worth writing, each corresponding to
a way this can actually fail:

| Case | What it protects |
|---|---|
| validation failure leaves the original byte-identical | the write path's whole purpose |
| mode 0600 is set before the rename | the file is never briefly world-readable |
| `--brief` hides a muted finding but never the count | muting cannot become hiding |
| a muted `FAIL` does not produce exit 1 | the Monday mail actually stops |
| derived mute fires when the cron job is disabled, and only then | no accidental blanket muting |
| a stale entry produces a `WARN` | the silent-return failure mode |
| an unknown `check_id` is rejected at the prompt | ids cannot drift from `CHECKS` |
| `worst()` and `_system_lines()` ignore `MUTED` | they work by accident today |

Version bumps, all dated 21.08.2026:

| File | From | To |
|---|---|---|
| `ownerp_mute.py` | — | 1.0.0 |
| `server-readiness.py` | 1.4.1 | 1.5.0 |
| `ownerp_console.py` | 1.1.0 | 1.2.0 |
| `fish/functions/linux/chk.fish` | 1.0.0 | 1.1.0 |
| `getScripts.py` | 9.20.1 | 9.21.0 |

`CLAUDE.md` gains section 15 for `ownerp_mute.py` and has its
`ownerp_console.py` section corrected as described above.

The customer server receives all of it with one `ups`.
