# Release Notes

## A Version Header Lagged Its Constant, for the Second Time (15.08.2026)

*scripts/docker_table.py v1.1.0 · tests/test_delivered_scripts.py · ReadMe.md ·
docs/usage/09-reference.md*

### Fixed

- **`docker_table.py` announced 1.0.0 in its header while `SCRIPT_VERSION` said
  1.1.0.** Cosmetic with an operational cost: the header is what a reader sees
  when they open the file, the constant is what lands in a pasted log, and when
  the two disagree a support conversation starts from the wrong version.
- **A test now guards it**, because this is the second time — `ownerp_cron.py`
  had the same defect (commit aa29034). `VersionHeaderTest` compares every
  script's `# Version` header against its `SCRIPT_VERSION`, checks only files
  that carry both, and comes with a test asserting the check can actually fail.
  Verified by reintroducing the mismatch.

### Changed

- **Documentation caught up with what shipped this week.** `ReadMe.md` still
  described `dpi` as "Images anzeigen" and `bootstrap.sh` as v1.6.x;
  `docs/usage/09-reference.md` listed `dpi` as plain `docker images` and
  bootstrap as 1.7.0. Both language versions of both files now carry the age
  column, the overlay2 measurement and the post-install build check.

## The overlay2 Pin Comes Back — for a Different Reason (15.08.2026)

*scripts/bootstrap.sh v1.14.0 · docs/usage/01-provisioning.md*

Yesterday the pin was removed because its justification (a broken image export
on the containerd store) did not survive measurement. Today the *real* Odoo build
was measured on the same throwaway box — Docker 29.7.2, 394 module archives
pre-fetched exactly as `odoo_build_cache.py` does in production — and the pin
comes back on entirely different grounds.

| | overlay2 | containerd |
|---|---|---|
| cold build | **14 s** | 37 s (2.6×) |
| of which export | 3.5 s | 19.7 s (5.6×) |
| warm build | **0–1 s** | 35–36 s |

### Changed

- **`DOCKER_STORAGE_DRIVER` defaults to `overlay2` again**, with speed as the
  stated reason. `DOCKER_STORAGE_DRIVER=""` leaves Docker's default in place —
  note the `${VAR-default}` form rather than `${VAR:-default}`, so an explicit
  empty value really means "Docker's choice" instead of falling back.
- **The warm row is why.** On the containerd store the build cache does not
  survive the `docker system prune -f` that `update_docker_odoo.py` runs after
  every update: the warm build takes as long as the cold one and its longest
  step is `build_odoo.py` running again. Every `doup` there would be a full
  rebuild. (Observed, not explained — the mechanism was not chased down.)
- **The mechanism check passed**: the totals moved *and* the export step moved
  with them, 5.6×. Had the totals differed while the export step did not, the
  storage driver would not have been the cause and the explanation offered for
  it — content blob plus snapshot, i.e. the data written twice — would have been
  wrong.
- **Nothing is switched on a running server.** That hides existing images until
  a restart and a reboot. `report_storage_driver()` states the cost and the
  manual steps, and leaves the timing to a human.
- `docs/usage/01-provisioning.md` carries the table in both languages, including
  what the containerd store buys — multi-platform images, attestations,
  encrypted images, lazy pulls — and why none of it applies here: these images
  are built locally, never pushed, single-platform.

### Correction

The benchmark's first `use-containerd` step was wrong and cost an arm: removing
`daemon.json` only removes the *pin*. The containerd store is the default for
**fresh installs**; once an installation holds state in the classic store Docker
stays there rather than making every image invisible. The switch is
`{"features": {"containerd-snapshotter": true}}`. The bench script now asserts
the live driver matches the arm's name before recording anything — mislabelled
numbers would have compared an arm against itself.

## The overlay2 Pin Was Measured Away (14.08.2026)

*scripts/bootstrap.sh v1.13.0 · docs/usage/01-provisioning.md ·
docs/usage/08-troubleshooting.md*

`bootstrap.sh` pinned `storage-driver: overlay2` from 1.7.0 to 1.12.0, because
Docker ≥29 puts fresh installs on the containerd image store whose export failed
for large builds (moby/moby#52431). The Captain challenged the thesis rather than
the symptom, and the challenge held.

The evidence against it, before any test was run:

- The upstream issue describes a **failed** build (`ref … locked`), not a hollow
  image. The link to hollow images was our own inference from one server.
- That server produced a hollow image on 14.08.2026 **while pinned to
  overlay2**. The pin was not sufficient.
- "Other Debian and Ubuntu servers never showed it" decides nothing — they were
  installed on Docker ≤28 and were on overlay2 anyway.

### Changed

- **A/B test on a throwaway Debian 13 box, Docker 29.7.2, containerd store
  active** (`driver: overlayfs`): five rounds building a 2.2 GB image of 22
  layers — cold, warm, and after `docker system prune -f`, the sequence `doup`
  runs. **5/5 clean, zero overlayfs kernel messages.** The workload was not a
  toy: same size as the real `odoo/staging` image (2.14 GB) and twice its layer
  count. The pass/fail rules were fixed in writing before the run.
- **The control arm was run too**, and it is the more interesting half: the same
  box with `overlay2` pinned and rebooted was **5/5 clean as well**. Had it
  failed, our own pin would have been the cause of what we blamed on the store.
  It did not — so by elimination the hollow images on that one server come from
  neither store. They come from the machine: overlapping overlay mounts reported
  there since 12.08.2026, and the build cache that grew out of them. Nothing
  reproduces on a fresh host with either setting.
- **Observed, not acted on:** `overlay2` built 44% faster (20s vs 36s), evenly
  across all rounds, so not a warm-up artefact. On a workload where the export
  is nearly the whole runtime. Whether any of that reaches a real Odoo build —
  dominated by downloading and unpacking modules — this test does not say, so it
  is not a reason to change the default.
- **The pin is now opt-in**: `DOCKER_STORAGE_DRIVER=overlay2 ./bootstrap.sh`
  for a host where a store fault is actually observed. Fresh installs get
  Docker's own default. Existing servers keep their pin — `bootstrap.sh` removes
  nothing.
- **The "Docker already present" branch no longer warns about the containerd
  store** or stages a pin behind the operator's back. It reports the driver in
  effect and moves on.
- `ensure_overlay2_pin()` → `ensure_storage_driver_pin(<driver>)`,
  `verify_overlay2_active()` → `report_storage_driver()`. A test asserts there is
  exactly one call site and that it is guarded by the variable: reintroducing a
  default pin has to be a decision, not a leftover.
- **The smoke test's limit is now written down** where it belongs, in the
  function and in both language versions of the docs: a two-line busybox image
  is a coarse probe, and the July observation on that server was that a 1-layer
  image built fine while the 22-layer one did not. It catches a comprehensively
  broken daemon, not a selectively broken one.
- Troubleshooting no longer calls the hollow image an "aftermath of the store
  bug". The cause is not established, and the row says so.

## bootstrap.sh: the Pin Was Written, Never Verified (14.08.2026)

*scripts/bootstrap.sh v1.12.0 · tests/test_bootstrap.py (new)*

`bootstrap.sh` has pinned `storage-driver: overlay2` before the daemon's first
start since 1.7.0. The incident of the same day showed the two things
that pin does not cover.

### Fixed

- **An existing `daemon.json` skipped the pin entirely.** The check was
  `if [ ! -f /etc/docker/daemon.json ]`, with a warning in the else branch. That
  file is on plenty of hosts for reasons unrelated to the storage driver —
  `log-opts`, a registry mirror, a DNS list — and every one of them came up on
  the containerd store while the install log said nothing was wrong. One server
  behaving unlike all the others is exactly the shape of fault that costs a day
  to find. `ensure_overlay2_pin()` now merges the single key in and keeps every
  other setting; a file that already names a *different* driver is reported and
  left alone, because overriding a deliberate choice unattended is worse than
  the bug being guarded against; a file that cannot be parsed is never written
  over, since a half-written `daemon.json` stops docker from starting at all.

### Added

- **`verify_overlay2_active()`** — "we wrote the file" is not "it is in effect".
  A pin that lands after the first daemon start, a typo, or a hand-edit never
  followed by a restart all leave it inert, and the host looks healthy right up
  to the first large build.
- **`verify_docker_can_build()`** — builds a two-line image and runs it. A
  Docker ≥29 host can build, tag and report success for an image with no
  filesystem at all; every other check in this script passes on such a host, and
  the fault surfaces days later as an Odoo container restart-looping on
  `exec /app/bin/boot: no such file or directory`. Sixty seconds here against an
  afternoon there. Never fatal — an unreachable registry is not a broken daemon,
  and the message says so. `DOCKER_SMOKE_TEST=0` switches it off. It also runs
  in the "Docker already present" branch, which is what `--harden` takes on an
  existing server — precisely where a daemon has had time to start doing this.
- **`tests/test_bootstrap.py`** — the script had no tests at all. `main "$@"` is
  now behind `BOOTSTRAP_NO_MAIN`, so the suite can source the file and exercise
  the merge against a temp file instead of provisioning the machine it runs on.

## `dpi` Now Says How Old an Image Is (14.08.2026)

*scripts/docker_table.py v1.1.0 · fish/functions/linux/dpi.fish (new) ·
fish/conf.d/32-aliases-docker.fish v1.3.0*

`dpi` was `docker images`, and Docker 29 answers that with DISK USAGE, CONTENT
SIZE and EXTRA — and no age at all, which is the one question actually asked of
an image list on a server.

### Added

- **An AGE column**, in the same renderer as `dps`/`dpsall` rather than a second
  half-built one. Ages are shortened the way the port column is (`4 months ago`
  → `4mo`) and turn amber past 90 days, because a base image that has not moved
  in a quarter has missed several security updates.
- **Dangling images are greyed out** and counted separately in the summary line:
  `4 images · 1 older than 90 days · 1 dangling`.
- Wording the age parser does not recognise is passed through unchanged and
  counts as zero days. A row coloured on a guessed number is worse than an
  uncoloured one.

### Changed

- `dpi` is a **function** now, not an alias — an alias would shadow the
  function fish has already autoloaded. Like `dps`, it falls back to
  `docker images` + `awk` (header held back, rows sorted) on a server where
  `ups` has not run yet.

## A Build Reported Success and Shipped an Image With No Filesystem (14.08.2026)

*scripts/update_docker_odoo.py v5.13.0*

On a customer server a `doup` finished with `build image odoo/staging ... ok (2s)` and left
the instance in a restart loop:

```
exec /app/bin/boot: no such file or directory
```

The Dockerfile was fine. The image had no filesystem at all — not even
`/bin/sh`. Docker ≥29 can export a hollow image from the build cache
(moby/moby#52431, open): every step reports `CACHED`, the export takes 0.0s, the
image carries a plausible size, and every file is missing at runtime. Same
server, same fault as 16.07.2026.

### Added

- **`verify_built_image()` runs after every build**, before the update step. It
  reads the image's own entrypoint and probes it with
  `docker run --rm --entrypoint /bin/sh <image> -c "test -x <entrypoint>"`,
  which catches both shapes of the fault: a hollow image has no shell and
  `docker run` refuses outright, an image that merely lost its last `COPY` has a
  shell and fails the test. Three seconds per run.
- **The failure message carries the way out** — `docker builder prune -af`,
  rebuild, and `dmesg -T | grep -i overlayfs` if it recurs — because the error
  that surfaces without it points at the wrong file and costs an hour.
- **An image without an absolute entrypoint is not condemned.** An installation
  may drive its container through `CMD` alone; failing that build would be a
  worse failure than the one being guarded against.
- **`--no-cache`** on `doup`, so the fix for a poisoned build cache does not
  require typing `docker build` by hand in the build folder.

### Fixed

- Nothing here can roll back: the previous image is removed *before* the build
  (`docker rmi {image}:latest`), together with the container. That is why a
  hollow build is an outage rather than an inconvenience, and why the check has
  to speak at the moment it happens.

## The Command Overview Never Appeared on a Customer Server (14.08.2026)

*fish/conf.d/50-prompt.fish v1.2.0*

`fastfetch` printed, the panel below it did not. The two hang on different
conditions, and the second one was wrong for the way these servers are actually
used.

### Fixed

- **`status is-login` is not the boundary it looked like.** Operators reach root
  with `sudo su`, and `su` without `-` starts an interactive shell that is *not*
  a login shell — so the test was false on every one of those sessions and the
  panel was skipped in silence. Measured on the affected server: `is-login` no,
  `is-interactive` yes, function present, configuration current.
- **The gate is now an exported marker, `OWNERP_HELP_SHOWN`.** It keeps what the
  login test was for — a tmux session with six panes must not print fifteen
  lines six times — because everything started from that shell inherits it. A
  fresh ssh session starts without it, and so does `sudo`, which resets the
  environment: arriving as root is a new session and gets the panel.
- The marker must stay `set -gx`. A `set -g` would not reach a child shell, and
  every pane would print the panel again — pinned by a test, as is the absence
  of `status is-login` from the executable lines.

## The Documentation Still Sent Operators to `tui` (14.08.2026)

*ReadMe.md · docs/INSTALLATION_GUIDE.md · docs/usage/04-updates.md ·
docs/usage/05-backup-restore.md · docs/usage/09-reference.md*

`ownerp_tui.py` was withdrawn on 13.08.2026 and removed from every server by
`RETIRED_SCRIPTS`. The operating documentation kept advertising it in fourteen
places, including a step-by-step section with commands to type. `tests/test_fish_help.py`
guards the login panel against exactly this kind of rot; nothing guards prose.

### Fixed

- **Fourteen references to a command that no longer exists**, across both language
  versions: the component list, the alias tables, the "TUI mode" section of the
  update guide, the script reference table, and the two documentation indexes. The
  update guide now documents what actually replaces it — `-s`, `--type` and
  `--comment` on `doup`, which is what the screen was a front end for — and says
  plainly that the screen is gone and where the overview lives now.

### Changed

- **`konsole`, `dostat` and `docron` are documented at all.** They have been the
  central tools since 13.08.2026 and appeared in `ReadMe.md` exactly zero times,
  while a withdrawn curses screen had its own paragraph. `dps`/`dpsall` and
  `cleandlog` describe what they now do rather than what they used to, including
  `cleandlog --dry-run`.

## One Word Made Every Console Start Fail (14.08.2026)

*getScripts.py v9.20.1 · scripts/ownerp_console.py v1.1.2*

`ups` reported `✓ console (konsole): ok — textual>=8,<9, pyyaml>=6`, and thirty
seconds later `konsole` on the same machine answered that Textual could not be
fetched. Both were telling the truth.

### Fixed

- **`uv run --with textual sys.executable` cannot see what uv just installed.**
  The re-exec handed uv an absolute path to the system interpreter. uv builds the
  environment correctly and then starts something that is not its Python: a
  virtualenv takes effect through its own binary, not through `PATH`. Writing
  `python3` instead lets uv resolve the interpreter inside the environment it just
  built. Reproduced in one line, off the affected server entirely:

      uv run --with 'textual>=8,<9' python3       -c 'import textual'   # ok
      uv run --with 'textual>=8,<9' /usr/bin/python3 -c 'import textual'   # fails

- **The warm-up rebuilt the console's command instead of running it**, and that is
  why nothing caught the above. Two spellings of the same intention, one in
  getScripts.py and one in the console, differing in exactly that word — the
  warm-up tested the spelling that worked while the console used the other. The
  command now has one builder (`uv_command()`), and `ups` no longer approximates
  anything: it runs `ownerp_console.py --check`, which *is* the console starting
  and confirming its own import. A check that does not exercise the real path
  proves nothing about it, however carefully it is written.

- **The message printed twice.** Parent and child are the same script, and both
  explained the same failure. The child's exit code says "already reported"; the
  parent stays quiet.

## The Console Was Never Installed (14.08.2026)

*getScripts.py v9.20.0 · scripts/ownerp_console.py v1.1.1 ·
scripts/ownerp_migrate.py v1.4.0*

`konsole` answered "The console needs Textual, and it is not available" on a server
that had been updated many times. Everything built for it was unreachable, and the
update that was supposed to install it reported success.

### Fixed

- **The warm-up verified nothing.** `warm_console_cache()` ran

      uv run --with textual --with pyyaml python3 -c pass

  which proves an environment can be built and never imports a single thing the
  console needs. A check that cannot fail is not a check. It now imports what the
  console imports — `textual` and `yaml`, the latter under its module name rather
  than its distribution name.

- **Every failure was a logger call.** Under the lean output policy those go to
  `~/getscripts.log`, so an operator watching `ups` scroll past saw a clean update
  and met the missing library days later, in a different context, with no reason to
  connect the two. The outcome is an entry in the install report now — the part that
  is actually read — and a failure names what it means: `konsole` will not start,
  `dostat` and `wiz` still work.

- **A missing uv was skipped in silence**, with `install_uv()` sitting in the same
  file. uv is a prerequisite of this project, not an optional extra; it is installed
  and the result recorded.

- **The console's own message pointed at `pip install --user`.** That is wrong twice
  over: Debian 12 and later refuse it outright (externally-managed-environment), and
  nothing else on an ownERP server arrives by hand. It names `ups`, and it separates
  the two causes — a missing uv, which an update fixes, from an unreachable PyPI,
  which nothing the operator types here will fix. A non-zero exit from `uv run`
  falls through to that message instead of exiting on uv's error alone.

### Changed

- **`ups` no longer says "Nothing to migrate" on every run.** `print_results()`
  already stayed silent when there was nothing to convert; `main()` printed two
  lines underneath it anyway. It runs from every update, so a server whose CSVs were
  converted long ago — or never existed — was told forever, which is how a block
  stops being read on the one server where it matters. `--quiet` (used by `ups`)
  suppresses only the empty case; a real conversion still prints in full, and typed
  by hand the answer is still there.

## The Console Gets a Menu and a Form (14.08.2026)

*scripts/ownerp_console.py v1.1.0 · scripts/ownerp_wizard.py v1.2.0*

The console could already edit a configuration. It did it by asking which field, then
asking for the value — the prompt wizard's logic wearing a nicer coat, and an operator
told us plainly that changing the YAML by hand was faster.

### Added

- **Select a row, get a menu.** ctop's shape: a small box at the top left, over the
  table it acts on, one letter per action. It is placed there rather than centred so
  the row it belongs to stays visible. What each tab offers is data (`ACTIONS`), and
  the System tab offers nothing — readiness findings are facts, not settings.

- **`[e]` opens the whole entry as a form.** Every field at once, booleans as a switch
  instead of a box you type `true` into, and the focused field's help at the bottom.
  The prompt wizard printed that help per question; a form that dropped it would be
  prettier and less informative.

- **`ownerp_wizard.set_fields()` — a whole form in one write.** This is what makes the
  form permissible at all. The two modals existed because a form that writes field by
  field can half-apply: reject the third of five changes and the entry is left in a
  state nobody asked for, with a `.bak-*` per keystroke-session. `set_fields()`
  validates the whole set once and replaces the file once. `set_field()` is now that
  call with one entry in the dict, so both paths cannot drift apart.

  The order inside it is the substance rather than tidiness. A recorded line number
  describes the file as it was *read*: replacing a line keeps every other number
  valid, while inserting one shifts everything below it. Fields that already have a
  line are patched first, and only then are absent ones appended, each recomputing the
  entry's end against the lines as they now stand. The regression test uses **two**
  absent fields — with one, the wrong order passes just as well.

- **New entries are suggested in two passes.** A sequential prompt knows the container
  name by the time it reaches the build folder; a form showing every field at once does
  not. So whatever can be known up front is filled in at open time, and whatever the
  operator left blank is suggested once the name exists — which is what turns an empty
  build folder into `$HOME/docker-builds/<name>/`, exactly as the prompt does.

### Fixed

- **The action menu rendered without its keys.** `[e]` is valid Rich markup for a style
  tag, so a Textual `Label` renders it as nothing at all: every line lost the letter
  that reaches it, which is the entire point of the menu. Forty-five green tests said
  nothing, because they asserted on the `ACTIONS` constant instead of on the screen.
  Found by looking at a rendered screenshot. `markup=False`, and the test now reads
  what is displayed.

- **A menu label ran past the box.** "database only, no filest" is not a shorter way of
  saying the same thing — it is a different sentence, and the menu clips rather than
  wraps. Labels are held under `MENU_LABEL_WIDTH` by a test.

### Unchanged on purpose

- **The console still starts nothing.** "Run backup now" is deliberately not in any
  menu. Having no process supervision, no cancel path and no log pane is what a tool
  that starts nothing may do; a twenty-minute backup behind a keystroke would need all
  three.

- **`wizup`/`wizbk` stay**, because a terminal that cannot run Textual still needs
  them. They now say so in their first line: the console edits the same file as a form,
  and this prompt is the fallback.

## `dps` Puts Its Header Back on Top (14.08.2026)

*scripts/docker_table.py v1.0.0 (new) · getScripts.py v9.19.0 ·
fish/conf.d/32-aliases-docker.fish v1.2.0 ·
fish/conf.d/30-aliases-system.linux.fish v1.1.0 ·
fish/functions/linux/ownerp-help.fish v1.5.0 · dps/dpsall/cleandlog (new functions)*

### Added

- **Containers as a table.** `dps` and `dpsall` are rendered by a new
  `docker_table.py`: a framed table, colour by state, and a count of what is running
  underneath it. They are fish **functions** now — an alias in conf.d would shadow the
  function, so nothing may reintroduce one under either name.

- **Ports are shortened, but never quietly.** `127.0.0.1:11600->8069/tcp` becomes
  `11600→8069` because loopback is the norm on these hosts. Every other bind keeps a
  visible, coloured marker — `*:8080→80` for a wildcard, the literal address for a
  specific one. A shortened port must never hide that a port is reachable from
  outside. A dual-stack publish, which Docker prints twice, is listed once.

- **It degrades instead of failing.** No colour off a terminal, ASCII box characters
  when the output encoding cannot carry the frame, no truncation into a pipe (a pipe
  has no width, and truncating for a guessed one throws away information nobody asked
  to lose). Docker's own error text and exit code are passed through — never a
  traceback. `__ownerp_docker_ps` falls back to `docker ps` + `awk` where the renderer
  is not installed yet, because `dps` gets typed on servers where `ups` has not run.

### Fixed

- **The column titles arrived at the bottom of every listing.** Both aliases piped
  `docker ps --format table` into `sort`, which sorted the header line along with the
  containers — and under a UTF-8 locale `NAMES` collates after `ivy-odoo`. Sorting
  the rows without the header is the whole reason the renderer exists; the frame and
  the colours are what it does afterwards.

- **`cleandlog` could never truncate a single log.** It was

      sudo sh -c "cat /dev/null > /var/lib/docker/containers/*/*-json.log"

  A redirect takes exactly one target while a glob yields many, so at best one file was
  emptied and the rest were handed to `cat` as arguments. Where the pattern matched
  nothing — a relocated data-root, or the `local` log driver, whose files are not named
  `*-json.log` — the shell answered "Directory nonexistent" and trimmed nothing at all.
  It is a function now: it reads the data-root from `docker info`, finds both drivers'
  files, truncates them with `find -exec` and reports how much it freed. `--dry-run`
  says what it would do. It truncates and never deletes — the file belongs to the
  daemon, and unlinking it under a running container leaves a writer holding a handle
  to nothing.

### Changed

- **The login panel lists `dpi`, `dkvol` and `ct`**, and no longer advertises
  `odoodev`: that CLI is workstation tooling, and this panel is what an operator needs
  on a server.

## The TUI Is Withdrawn (13.08.2026)

*scripts/ownerp_tui.py removed · getScripts.py v9.18.0 ·
scripts/ownerp_cron.py v1.0.2 · fish/functions/linux/doup.fish v2.0.0 ·
fish/conf.d/33-aliases-backup.fish v2.0.0 ·
fish/functions/linux/ownerp-help.fish v1.4.0 · cleanup_legacy.txt v1.1.0*

### Removed

- **`ownerp_tui.py` and its `tui` alias.** `konsole` replaces it for the full-screen
  version and `dostat` for the text one. The `.ownerp_tui_default` marker and the branch
  in `doup` go with it — `doup` is a plain call to the runner again.

### Fixed

- **Withdrawing a delivered script did not reach existing servers.** Taking a name off
  `copy_scripts()` stops it being delivered; it does not remove the copy already sitting in
  `$HOME`. `cleanup_legacy.txt` does not close that gap either — it runs **only on a fresh
  Fish installation**, so on every server that already had Fish, `ownerp_tui.py` would have
  outlived its replacement indefinitely, with an alias that may still point at it.

  `RETIRED_SCRIPTS` in getScripts.py removes withdrawn scripts on **every** pass, and logs
  what replaced each one. Strictly limited to files this project delivered: a customer's own
  file must never appear there. That distinction is the whole lesson of the CSV loss — a
  deletion list that named the customer's configuration destroyed it during the upgrade
  meant to convert it.

- **`restore-zip.sh` was delivered and then deleted by the same run.** It appeared on the
  `copy_scripts()` list *and* in `cleanup_legacy.txt`, and the cleanup runs afterwards — so
  every fresh Fish installation set the server up and removed its restore tool again. Found
  while adding the entry above, and it is the same shape as the CSV loss: a list that
  deletes what the same run just produced. It is off the cleanup list, and
  `tests/test_delivered_scripts.py` now fails if any delivered script is ever listed there
  again.

## The ownERP Console (13.08.2026)

*scripts/ownerp_console.py v1.0.0 (new) · getScripts.py v9.17.0 ·
fish/conf.d/33-aliases-backup.fish v1.7.0 ·
fish/functions/linux/ownerp-help.fish v1.3.0*

Stage 3, the last one. `konsole` starts it.

### Added

- **A full-screen console** with five tabs — overview tiles, instances, backup, maintenance,
  system — mouse support, sortable tables and real input fields. Selecting a row opens the
  entry's fields; selecting a field edits it. Cron jobs can be switched off and rescheduled.

- **It owns no data and no write path.** Every fact comes from `ownerp_state.py`, every
  configuration change from `ownerp_wizard.py`, every cron change from `ownerp_cron.py` —
  which already back up, validate and refuse on regression. The test suite fails if a
  write call appears in the console itself.

- **It starts nothing.** No updates, no backups, no container operations. That boundary is
  the design: a tool that starts nothing long-running needs no process supervision, no
  cancel path, no log pane and no partial-failure recovery. Every action finishes in well
  under a second or fails with a message. `doup` and `dobk` stay what they are.

- **Never the only route to anything.** `dostat`, `wiz`, `docron` and `doval` do everything
  the console does, without Textual — which is what makes it safe to depend on a library
  for the comfortable version. If Textual is missing, the console re-executes itself
  through `uv run --with` once; if that fails too, it names those four commands and stops.

- **`getScripts.py` warms the console's uv cache** at install time, so the first start does
  not wait on the network at the moment somebody wants to look at a misbehaving server.
  Never fatal — a machine with no network keeps working, and the console says so itself.
  The specs are parsed out of `ownerp_console.py` rather than duplicated: a warm-up for the
  wrong version looks exactly like a successful one.

### Fixed before it shipped

- **`uv run --with` builds an isolated environment.** The re-executed console found no
  PyYAML and reported *every* section as unknown — which looks precisely like a broken
  server, the worst way for a status tool to be wrong. PyYAML is now declared alongside
  Textual, and a test reads the source to keep both in the list and both passed to uv.
  This only surfaced in a live run; no unit test would have caught it.

### Not done, deliberately

- **`ownerp_tui.py` still ships.** The design has it removed, and that is right — but only
  after the console has run on a real server. Until then the TUI is the fallback for a
  problem this machine could not show. `tui` is unchanged.

### A note on running the tests

The console's 17 interface tests need Textual and skip without it. The full suite:

```bash
uv run --with 'textual>=8,<9' --with pyyaml python3 -m unittest $(ls tests/test_*.py | sed 's|/|.|; s|\.py$||')
```

The eight that always run are the ones that catch what reaches a customer: the dependency
list, the write-path ownership, and the wording of the refusals.

## The Backup Configuration Gets an Editor (13.08.2026)

*scripts/ownerp_wizard.py v1.1.0 · fish/conf.d/33-aliases-backup.fish v1.6.0 ·
fish/functions/linux/ownerp-help.fish v1.2.0*

Stage 2 of the ownERP console design.

### Added

- **`container2backup.yaml` can be edited.** It had no editor at all — not in the wizard,
  not in the TUI, only `edbk` and mcedit. `wizbk` now adds a database or changes a field
  through the same validated write path the update configuration has always used:
  timestamped backup, temp file in the same directory, validation of that file,
  `os.replace()`. A rejected result leaves the original byte for byte.

  `safe_write()` picks the schema from the kind. Validating a backup configuration against
  the update schema would reject every field it has and accept none it lacks — the wrong
  one there is not a near miss but a tool that can never write that file.

- **The backup form suggests from `docker2update.yaml`.** A backup entry needs to know
  which Postgres container holds the database and which Odoo container holds the
  filestore — and both are already written down as `db_host` and `container_name`. Type
  `test_db` and the remaining three fields arrive filled in. Asking an operator to retype
  a pairing they have already recorded is asking them to introduce a typo into a backup.

  Two update entries naming one database suggests nothing rather than picking one: that is
  a configuration error the validator reports, and a guess in front of someone mid-way
  through fixing it is worse than a blank field.

- **A write API with no terminal in it** — `load_config()`, `add_entry()`, `set_field()`,
  each returning a `WriteResult`. This is what stage 3's console consumes, and the
  interactive wizard now runs on it too. One write path per file, exercised by both
  callers, so the one used less often cannot rot unnoticed. Duplicate names and the
  localhost bind address of a port are handled there rather than in the prompts, where the
  console would have had to repeat them.

### Changed

- The wizard asks which configuration to edit when started without a flag. Defaulting
  silently to the update file would keep the backup side invisible to anyone who does not
  read `--help` — and that is the side that had no editor until now.

- `render_container`, `containers_end`, `append_container` and `patch_field` are now thin
  update-shaped wrappers over generic equivalents. Same signatures, same behaviour, and the
  91 existing tests pass unchanged.

## The Whole Server on One Page (13.08.2026)

*scripts/ownerp_state.py v1.0.0 (new) · getScripts.py v9.16.0 ·
fish/conf.d/33-aliases-backup.fish v1.5.0 ·
fish/functions/linux/ownerp-help.fish v1.1.0*

Stage 1 of the ownERP console design.

### Added

- **`dostat`** — instances, backup ages, maintenance jobs and the readiness checks in one
  page of text. Every fact was already on the machine, spread across five tools with five
  output formats; nothing put it together. Exit code `0` clean / `1` needs attention /
  `2` broken, so a cron job can act on it without parsing anything, and `--json` for
  anything that would otherwise parse the text.

  The module carries no interface import at all. Stage 3 puts a Textual console on top of
  the same collectors — a data layer that knew about its interface could neither be tested
  without it nor produce `dostat`.

- **A status tool has to work on a broken server**, because that is where it is read. Every
  source is optional: Docker down, PyYAML absent, a YAML that does not parse, `/etc`
  unreadable — each costs exactly one section, states its reason in a sentence, and leaves
  the other three standing.

  One distinction is load-bearing and cost a test to get right: **"not asked" is not
  "down"**. Skipping the Docker query left an empty status string, which read as a stopped
  container — the report would have announced every instance as down on a machine where
  nobody had looked. Container state is now genuinely three-valued.

- **`ownerp_state.py` never writes.** It opens files for reading, runs `docker ps`, and
  calls the read-only entry points of its siblings. Configuration changes stay with
  `ownerp_wizard.py`, cron changes with `ownerp_cron.py` — one write path per file, and
  this is not one. `tests/test_ownerp_state.py` fails the suite if a write call or a UI
  import ever appears in it.

- **The readiness checks are not reimplemented.** `collect_health()` calls
  `server-readiness.py` through its own `run_checks()`; a second opinion that drifted from
  the first would be worse than none.

### Changed

- The design places the collector in `lib/`, which turned out to be wrong: `copy_scripts()`
  delivers flat files to `$HOME` and has never delivered `scripts/lib/`, so a collector
  there would not exist on any server. It ships as `ownerp_state.py` beside its siblings
  instead — the pattern `ownerp_cron.py` and `ownerp_validate.py` already prove out.

- `dostat` heads the login panel. It is what an operator wants first after logging in.

## A Backup Header That Talks About Backups (13.08.2026)

*scripts/ownerp_migrate.py v1.3.0 ·
docs/superpowers/specs/2026-08-13-ownerp-console-design.md (new)*

### Fixed

- **The reconstructed `container2backup.yaml` opened with the update program's questions.**
  `reconstruct_from_docker()` collected one flat list of review points and handed the same list
  to both renderers, so a backup configuration was topped with notes about `type`, `delay_time`,
  `translate`, `odoo_version`, port 8072 and the build folder — six things a backup configuration
  does not have. The update file meanwhile carried `retention_days`, which only the backup one
  has. On the ucore stack both files listed the same seven points; they now list three and two,
  with no overlap.

  Each point now declares which file it concerns at the moment it is raised (`update`, `backup`
  or `both`) and `_provenance()` filters on it. Collection is unchanged — only delivery. The
  per-file count changed with it: a header stating seven points while listing three sends the
  reader hunting for four that were never printed.

- **An instance whose database could not be identified was left out of the backup configuration
  silently.** A backup entry needs a database name, and without one no row was written — but
  nothing said so. The generated file looked complete while one production database was not
  backed up at all. That is worse than any header defect: a missing update entry means nobody
  updates the instance, a missing backup entry means nobody notices until a restore is needed.
  Every instance that does not make it into the file is now named in the backup header and in
  the `--dry-run` output, in those words.

### Added

- **`docs/superpowers/specs/2026-08-13-ownerp-console-design.md`** — the design for the ownERP
  console that replaces `ownerp_tui.py`. The TUI was built as a front end for `doup` and answers
  a question operators do not ask; what they need is server state and a way to change
  configuration without hand-editing YAML. The console shows state and edits configuration, and
  deliberately starts nothing: no updates, no backups, no container operations. Four stages, each
  leaving something usable behind — this release is stage 0. The superseded design is marked as
  such rather than deleted.

## Getting the Deleted Configuration Back, and a Login That Says What to Type (13.08.2026)

*scripts/ownerp_migrate.py v1.1.0 · scripts/server-readiness.py v1.4.1 ·
fish/functions/linux/ownerp-help.fish v1.0.1 (new) · fish/conf.d/50-prompt.fish v1.1.0 ·
fish/conf.d/30-aliases-system.fish v1.1.0*

### Fixed

- **`docron` and `ownerp_migrate.py` arrived on the server unexecutable.** Both were committed
  `100644`, so the alias died with `exists but is not an executable file` — on the customer's
  terminal, at the moment the reconstruction was needed. `odoo_build_cache.py` had the same mode
  and only got away with it because cron invokes it through `/usr/bin/python3`.

  Correcting the committed mode is **not** sufficient, and assuming it was cost a round trip:
  `cp` takes the source's mode only when it *creates* the target. Onto a file that already exists
  it truncates and writes, leaving the old mode untouched — so a script that once landed as `0644`
  would have stayed `0644` on that server forever. The fix is in `copy_scripts()`, which now sets
  the execute bit on any delivered file starting with `#!`: a shebang is the file declaring it is
  meant to be run, a property of the content rather than of whoever last touched the permissions.
  Data files delivered by the same loop (`myodoo-maintenance.cron`, `.logrotate`) have none and
  keep their mode. The three committed modes are corrected as well, for fresh installs, and
  `tests/test_delivered_scripts.py` fails the suite if a shebang script is ever committed without
  the bit again.

  **On a server already updated past this point:** the repair ships *inside* getScripts.py, and
  `ups` runs the copy in `$HOME` that was loaded before the pull — so it lands one run late. Either
  run `ups` a second time, or:
  `chmod +x /root/ownerp_cron.py /root/ownerp_migrate.py /root/odoo_build_cache.py`

- **`--from-docker --dry-run` reported the number of review points while withholding the points.**
  The REVIEW block lives in the generated file's header, and a dry run writes no file — so the one
  moment an operator is deciding whether to run it for real was the one moment the reasons were
  invisible. The review list is printed to the console now, in both modes.

### Added

- **`ownerp_migrate.py --from-docker` reconstructs both configs from the running containers.**
  For the servers whose CSVs were deleted before the previous release existed. The configuration
  is off the disk but not off the machine: `docker inspect` still knows the ports, the image, the
  network, the volumes and — because the Odoo images take them that way — the database
  credentials.

  Twelve of the fourteen `docker2update.csv` columns come back exactly: `container_name`,
  `database_name` (via `psql -l` in the paired Postgres container), `port`, `longpolling_port`,
  `docker_image_name`, `db_user`, `db_password`, `db_host`, `volume` (network + binds),
  `odoo_version`, `dockerfile_path`. The backup config gets the database, its SQL container and
  its data container from the same pairing.

  What cannot come back is **named rather than guessed**. `type` (M/F/N), `delay_time`,
  `translate` and `retention_days` were operator choices stored nowhere on the machine;
  documented defaults are used and a `REVIEW BEFORE USE` block at the top of each generated file
  lists every one of them, plus anything that had to be left as `REVIEW_ME` — an unpublished
  port, an unreadable password, several databases behind one container. A guess that looks like
  a fact would quietly update the wrong database.

  Same install path as the CSV conversion, so the same refusals: never overwrites an existing
  YAML, never installs what does not validate, mode `0600`. **Opt-in only — it never runs from
  `ups`.** `server-readiness.py` now points at it when the backup config is missing and Docker is
  present, because on such a machine that is far more likely to be the deleted CSV than a server
  nobody ever configured.

- **A command overview at login.** `fastfetch` keeps running on every interactive shell; the new
  panel prints once per *login* shell — an ssh session gets it, a new tmux window does not — and
  `help` shows it again on demand. It names the dozen commands that matter: `doup`, `tui`, `wiz`,
  `dobk`, `edbk`, `doval`, `docron`, `ups`, `ngxset`, `dps` and friends.

  Curated by hand rather than generated: a listing of all ninety aliases is forty lines nobody
  reads. Curation rots, so `tests/test_fish_help.py` checks that every command the panel
  advertises still exists as an alias or function — a renamed alias fails the suite instead of
  sending an operator to type something that is gone.

## The Upgrade Deleted the Configuration It Was Supposed to Convert (13.08.2026)

*scripts/ownerp_migrate.py v1.0.0 (new) · cleanup_legacy.txt · getScripts.py v9.15.0 ·
scripts/ownerp_cron.py v1.0.1*

### Fixed

- **`cleanup_legacy.txt` listed the customer's configuration for deletion.** The four legacy
  CSV files — `container2backup.csv`, `container2backup_path.csv`, `docker2update.csv`,
  `rsync_targets.csv` — were on the cleanup list, and `cleanup_legacy_files()` removes what that
  list names on a fresh Fish installation. That is precisely the run which lifts an old server
  onto the new stack. The configuration was therefore destroyed by the upgrade that needed to read
  it, and the first sign was a readiness report saying `container2backup.yaml not found`, with no
  CSV left to convert. Every affected customer had to rebuild their backup and update
  configuration by hand.

  The four files are off that list. `ownerp_migrate.py` owns them now — one file, one owner, and
  this owner archives instead of deleting.

- **The cron overview showed a schedule nobody could act on.** `ups` prints the table in `--brief`
  mode, which suppressed the editing hint — so the only place most operators ever see the schedule
  was the one place that did not say how to change it. A schedule you cannot act on is a schedule
  you edit by hand in `mcedit`, which is exactly the unvalidated write `ownerp_cron.py` exists to
  replace. Both modes carry the hint now.

### Added

- **`ownerp_migrate.py` (new): the CSV to YAML migration happens by itself.** It runs from every
  `ups`, before the legacy cleanup, and stays completely silent once there is nothing left to
  convert.

  | legacy file | becomes |
  |---|---|
  | `container2backup.csv` | `databases:` in `container2backup.yaml` |
  | `container2backup_path.csv` | `defaults.backup_path` |
  | `rsync_targets.csv` | `rsync.commands` |
  | `docker2update.csv` | `containers:` in `docker2update.yaml` |

  What it refuses to do is the substance:
  - **Never overwrites an existing YAML.** A server that already has one is already migrated, or
    was configured by hand; either way the CSV is not the authority. The conversion is written
    beside it as `<name>.yaml.from-csv` and the CSV stays put for comparison.
  - **Never installs a config that does not validate.** `ownerp_validate.py` runs against the
    generated file first, with the right schema flag per config. Errors block installation and
    keep the file as `.from-csv`; warnings never block, because a build folder that does not exist
    yet is a finding, not a reason to withhold the whole configuration.
  - **Never deletes.** Consumed CSVs move to `$HOME/legacy-csv/<timestamp>/`, created `0700`
    because `docker2update.csv` holds database passwords in clear text. The generated YAML is
    written `0600` for the same reason.

  A row commented out in the CSV meant "switched off", and it still does: in `docker2update.yaml`
  it becomes `active: false`; `container2backup.yaml` has no such key, so those rows are emitted
  as a commented-out block. Dropping them would lose configuration, and activating them would
  silently start backing up a database somebody deliberately turned off.

  Two details the conversion adds rather than copies, both flagged in the generated file: the
  `services:` block (nginx, letsencrypt, docker-builds — the CSV format had no equivalent) and
  `db_password_via_env: true`, the current runner's secure default, because an argv password is
  visible to every local user through `ps aux`.

## One Customer's DNS Edit Took Ten Sites Down, and Nothing Saw It Coming (13.08.2026)

*scripts/nginx-cert-guard.py v1.2.0 · scripts/server-readiness.py v1.4.0 ·
scripts/ownerp_cron.py v1.0.0 (new) · scripts/ownerp_tui.py v1.2.0 ·
getScripts.py v9.14.0 · fish/conf.d/33-aliases-backup.fish v1.4.0*

### Fixed

- **A guard built for exactly this scenario watched it happen and said nothing.**
  A customer moved the A record of `assistedhome.de` to another provider. Ten vhosts
  on the host still carried the pre-1.11.0 form `listen <hostname>:443`; nginx resolves
  a listen hostname at config-parse time, got the new owner's IP, and refused to start
  with `bind() to 94.130.186.22:443 failed (99: Cannot assign requested address)`. Every
  site on the machine went down over one DNS edit somebody else made.

  `nginx-cert-guard.py` was supposed to catch this. It checked whether a listen hostname
  **resolved** — and this one resolved perfectly, just not to us. IP literals were skipped
  outright, on the reasoning that "those always resolve"; they do, and it was never the
  property that mattered. `unbindable_listen_target()` replaces the resolvability test with
  a bindability test: every listen target, hostname or literal, must be an address this
  machine actually holds. When `ip addr` cannot be read the check is skipped rather than
  failed, because "unknown" must never be rendered as "nothing is bindable".

- **The proactive check treated a total outage as a customer slowly drifting away.**
  `--check` confirmed a departed domain over `GUARD_FAIL_THRESHOLD` (3) runs before acting
  — right for a domain that merely appears in `server_name`, wrong for one in a `listen`
  directive, where every day of confirmation is a day the whole host is one reload from
  darkness. Listen-bound domains now act on the first failing run; everything else keeps
  the confirmation counter.

- **The mass-failure guard counted instead of measuring scope.** Both `--reconcile` and
  `--check` escalated only above `GUARD_MAX_DISABLE` (5), so a three-vhost server whose own
  IP had changed would slip under the limit and be emptied one file at a time. "All of them"
  is now a mass failure regardless of the count, and when every candidate shares one cause
  the alert names that cause instead of listing the same sentence ten times.

### Added

- **`server-readiness.py` checks that every `listen` target is bindable** (`nginx listen
  targets`). This is the check that would have reported the outage days before the deploy
  hit it. It imports the guard rather than re-implementing the rule — two copies of
  "what can nginx bind" would disagree exactly when it counts — and reports SKIP with a
  pointer to `ups` when the guard is absent or predates v1.2.0.

- **`ownerp_cron.py` (new): the maintenance cron is visible and editable.** The jobs an
  ownERP server depends on — backup, cert renewal, DNS guard, log cleanup — were invisible
  unless somebody opened `/etc/cron.d/myodoo-maintenance`, and a job never installed looked
  exactly like a job running nightly.
  - `ups` now prints the schedule after the install summary: job, when it runs, when it
    last ran. Read-only and non-interactive, because `ups` also runs unattended.
  - `tui` key `t` reschedules jobs and switches them on and off. Same write discipline as
    `ownerp_wizard.py`: timestamped backup → temp file in the same directory → re-parse and
    validate → `os.replace()`, with mode 0644 set before the rename (cron silently ignores
    a group-writable `cron.d` file). Only the named job's line is rewritten; a regression
    check refuses the write if anything else moved, and the template's column alignment on
    untouched lines survives.
  - Range validation is strict on purpose: cron accepts `0 25 * * *` at write time and then
    simply never fires it.
  - A job switched off keeps its line behind `#OWNERP-DISABLED#` rather than being deleted,
    so the schedule is there for whoever switches it back on.
  - An edit stamps the file, and `server-readiness.py` reads that stamp — a deliberate
    schedule change reports as "customised locally" instead of nagging as drift forever.
    Re-running `setup-maintenance-cron.sh` still restores the repository schedule.
  - New alias `docron` for the report on its own.

**Companion release:** `nginx-set-conf` v1.18.0 stops blaming the base configs for
environmental faults. Its pre-flight had been aborting the very redeploy that rewrites
hostname-bound listens into IP-bound ones — the repair for this outage.

## A PostgreSQL Healthcheck That Stops Writing FATAL Every Ten Seconds (12.08.2026)

*scripts/pg-local-deploy.sh v1.2.2 · semaphore playbooks/odoo/pg/pb_pg_docker_start.yaml*

### Fixed
- **Every deployed PostgreSQL container logged `FATAL: database "ownerp" does not
  exist` every ten seconds, forever.** The generated healthcheck ran
  `pg_isready -U <user>` without `-d`. libpq then falls back to the database named
  after the connecting user, so a cluster created with `POSTGRES_DB=postgres`
  rejected every single check — while the check itself kept reporting healthy,
  because `PQping` counts a FATAL reply as "server is up and accepting
  connections".

  Nothing was broken, which is exactly the problem: the container was fine, the
  database was fine, and the log of a production database filled with FATAL lines
  that bury the errors worth reading. On a customer server the noise arrives
  wrapped in a `docker logs` excerpt that looks like a database outage.

  Fixed in all four places the call appears: the Compose healthcheck, the
  `docker run` fallback's `--health-cmd`, and both `pg_isready` wait loops. The
  same two calls in the Ansible playbook the script mirrors were pulled along —
  that playbook sets no healthcheck, so its noise was limited to deploy time, but
  the two deployment paths have to stay comparable line by line.

  The check targets `postgres`, not the configured `$pg_db`: the maintenance
  database exists after every initdb, whereas `$pg_db` is never created on a
  re-deploy over existing PGDATA (`POSTGRES_DB` only takes effect during initdb)
  — which would have reproduced the same failure under a different name.

  **Existing containers keep the old check.** A healthcheck is frozen into the
  container configuration when it is created, and `docker container update` cannot
  change it; it knows only resource limits. Correct the `pg_isready` line in
  `{base}/{name}-deploy/docker-compose.yml` and run `docker compose -f … up -d`,
  or re-run the script — either way the container is recreated, and PGDATA lives
  on the host and is untouched.

## The v19 Container Resolves Visitor Countries Again (12.08.2026)

*v19-odoo/bin/boot v2.5.0*

### Fixed
- **The visitor country stayed "Unknown" in every Odoo 19 website statistic.**
  Odoo reads geolocation data through `geoip2`, which understands the MaxMind DB
  format (`.mmdb`) and nothing else. The base image installed the Debian package
  `geoip-database`, which ships the discontinued legacy format — in Trixie exactly
  `GeoIP.dat` and `GeoIPv6.dat`. GeoIP therefore looked installed in every
  container while Odoo found nothing at the path configured in `odoo.conf`, with
  no message above debug level to show for it.

  The base image `prepare-19` now carries `geoip-refresh` instead, and `boot`
  calls it in `start` before handing over to `odoo-bin`. The order matters: Odoo
  opens the database once during start-up and caches the reader, so a later
  refresh would not take effect until the next restart. It runs while we are
  still root, which the write to `/usr/share/GeoIP` needs.

  Databases come from DB-IP by default, which needs no account. Setting
  `GEOIPUPDATE_ACCOUNT_ID` and `GEOIPUPDATE_LICENSE_KEY` in the container
  environment switches to MaxMind GeoLite2 and its weekly instead of monthly
  refresh; there is no separate switch to remember. `odoo.conf` stays unchanged
  either way.

  Two prerequisites remain on the operator: `/usr/share/GeoIP` should be a
  persistent volume, or the database is downloaded again on every start, and
  `proxy_mode = True` has to be set, or Odoo only sees the reverse proxy's own
  address and finds no country regardless of the database.

  The call is guarded, so a container still built on an older base image starts
  exactly as before, and a failing refresh never keeps the server down — without
  a database Odoo simply leaves the country empty.

  Requires a base image built after this change; bump the `FROM` tag in
  `Dockerfiles/v19-odoo/Dockerfile` once the `prepare-19` pipeline has published it.

## A Guided Assistant for docker2update.yaml (12.08.2026)

*ownerp_wizard.py v1.0.0, ownerp_tui.py v1.1.0, getScripts.py v9.13.0*

### Added
- **`ownerp_wizard.py`**, started with `wiz`. Walks an operator through adding
  an Odoo instance to `docker2update.yaml`, and through changing a single
  field of an existing entry. It reads the configuration before it asks
  anything and proposes values from it — the next free host port (across
  **both** port fields of **every** entry, active or not), a `db_user` the
  existing entries agree on, the shared build-folder pattern with the new
  container name substituted, the shared image-name prefix. A suggestion sits
  in brackets and is taken with Enter.
  ```
  ownerp_wizard.py                    # menu: add an instance / change a field
  ownerp_wizard.py --update [PATH]    # default ~/docker2update.yaml
  ownerp_wizard.py --version
  ```
  This is the **only tool in the ownERP set that writes to a customer's
  configuration**, so the write path is the substance:

  1. the file is copied to `<path>.bak-<YYYYmmdd_HHMMSS>`,
  2. the new text is built in memory and written to `<path>.tmp-<pid>` **in the
     same directory**, so the later replacement is atomic,
  3. `ownerp_validate.py` runs against that temporary file,
  4. **any error → the temporary file and the backup are both removed and the
     original is left byte-identical**,
  5. **clean → `os.replace()`**, and the backup stays.

  Warnings do not block a write: a build folder that does not exist yet is the
  normal state for an instance being created. A backup is therefore kept only
  when the original was actually replaced — a backup of a file nobody changed
  is litter, and litter teaches operators to ignore `.bak-*` files.

  It **refuses** rather than guesses: without a terminal (naming `edup`),
  without `ownerp_validate.py` beside it (naming `ups`), and on a configuration
  that does not parse (pointing at `doval` for the line). A duplicate container
  or database name is rejected at the prompt, where the operator is still
  typing, rather than five prompts later at validation.

  It edits **scalars only** — `pre_build_files` and `proxy` are a list and a
  mapping, and a value spanning several lines has no single line to replace.
  It **never removes an entry**. `db_password` is never suggested, never
  echoed (`getpass`), and appears as `********` in every summary. Its one write
  outside the YAML is the empty build folder it offers to create; nothing is
  copied into it, because populating a build folder belongs to
  `odoo_build_cache.py`.
- **`ownerp_tui.py` v1.1.0**: the new key **`w`** leaves curses, runs the
  wizard, and **reloads the container list on return** — unlike `v`
  (validate), which only reads, the wizard may have added an entry, and a
  stale list would send the next Enter against a system that no longer looks
  that way. The wizard's exit code is deliberately not folded into the run's:
  a cancelled wizard is not a failed update.
- **`wiz` alias** and distribution via `getScripts.py` v9.13.0.

### Fixed
- **`ownerp_wizard.py`**: a `Ctrl-C` between the backup and the replacement
  left the `.bak-*` and `.tmp-*` behind. `KeyboardInterrupt` does not inherit
  from `Exception`, so the cleanup clause walked straight past it — an operator
  abort must leave no trace, and now does not.
- **`ownerp_wizard.py`**: `Ctrl-D` at a prompt ended in an `EOFError`
  traceback. Closing the input is an operator's decision, not a fault, and it
  now reads like one.

## One Validator for Both Configurations (11.08.2026)

*ownerp_validate.py v1.0.0, update_docker_odoo.py v5.12.0,
container2backup.py v4.8.0, getScripts.py v9.12.0*

### Added
- **`ownerp_validate.py`**, started with `doval`. Read-only validation of both
  `docker2update.yaml` and `container2backup.yaml` against their declared
  schemas — structure, required fields, types, enums, port form (`11000`,
  `"11000"`, `"127.0.0.1:11000"`, `"[::1]:11000"`), duplicate container/database
  names and duplicate host ports **among active entries only**, whether
  configured paths exist, and unknown keys with a suggestion from the closest
  known name. Findings name the file and the line number. A block with
  `active: false` is checked in full, but its findings are downgraded to
  warnings prefixed `(inactive)`, so a parked block never turns the exit code
  red. It never writes, and never prints the value of a key whose name ends in
  `password`.
  ```
  ownerp_validate.py                  # both configurations at their default paths
  ownerp_validate.py --update [PATH]  # only docker2update.yaml
  ownerp_validate.py --backup [PATH]  # only container2backup.yaml
  ownerp_validate.py --version
  ```
  Exit codes: `0` no errors (**warnings may be present and do not affect the
  exit code**), `1` at least one error, `2` a file is missing, unreadable,
  unparseable, or PyYAML is absent.
- **`container2backup.py --validate`** delegates to `ownerp_validate.py`.

### Changed
- **`update_docker_odoo.py --validate`** now delegates to `ownerp_validate.py`
  instead of the old built-in per-container check. When the validator is not
  yet installed beside the script (older installation), it falls back to the
  built-in check rather than failing hard — run `ups` to install it.
- **`update_docker_odoo.py --validate` is read-only again.** The DNS
  optimisation step used to rewrite `volume:` entries in the YAML even during
  a validation-only run; it is now skipped under `--validate`.

### Fixed
- **`container2backup.py`**: `service_config['backup_path']` no longer raises
  `KeyError` mid-backup when a `services` entry omits it — a config problem
  that `doval`/`--validate` now catches before a backup run gets there.
- **`container2backup.py`**: a `services` entry without `source_path` is now
  skipped with a message naming the service, instead of raising `KeyError`.
  `check_paths()` already warned about it before the run, but an operator who
  answered `y` to its "continue anyway?" prompt reached the crash anyway. No
  fallback path is guessed here — backing up the wrong directory is worse than
  backing up nothing.
- **`ownerp_validate.py`**: a YAML file containing an unhashable mapping key is
  now reported as a syntax error with its line number and exit 2. It used to be
  dropped silently, so the validator could report "no findings" for a file that
  `update_docker_odoo.py` itself refuses to load.

### Notes
- `getScripts.py` 9.12.0 distributes `ownerp_validate.py` alongside the other
  management scripts.

## Picking Systems Instead of Editing YAML (11.08.2026)

*ownerp_tui.py v1.0.0, update_docker_odoo.py v5.11.0, getScripts.py v9.11.0*

### Added
- **A TUI for ad-hoc updates**, started with `tui`. It lists every system from
  `docker2update.yaml` with its mode and its last run, and hands the selection
  to `update_docker_odoo.py`. Selecting a system for one run used to mean
  editing `active:` and `type:` with mcedit and editing them back afterwards —
  with twenty systems that is where mistakes come from, because the file is
  left in a state nobody intended and the next scheduled run acts on it.
- **The TUI never writes to the YAML.** Ticks and modes are read from `active:`
  and `type:` as a starting point; the run itself is passed as arguments. There
  is nothing to turn back afterwards, and the heavily commented config — which
  is the documentation for these files — is never at risk.
- **`~/update-history.jsonl`**: one line per container run — what ran when, in
  which mode, with which result, duration, log path and comment. Written by the
  runner, so classic and cron runs are recorded too, which is the whole point of
  a central file. Retention via `defaults.history_retention_days`, 365 days by
  default, `0` keeps everything.
- **`--comment TEXT`** is recorded in the history and in the run log header,
  where whoever opens that log a month later reads why the run happened.
- **`--type M|F|N`** overrides the YAML mode for one run without touching it.
  Since it applies per invocation, a selection with mixed modes becomes one
  runner call per mode, run in order.

### Changed
- **`-s` takes several names**, repeated or comma-separated. `-s live-odoo`
  keeps working exactly as before.
- **`doup` becomes a function** that starts the TUI only when all three
  conditions hold: no arguments, an interactive shell, and
  `~/.ownerp_tui_default` present (toggled with `d` in the TUI, or
  `ownerp_tui.py --make-default`). Arguments and non-interactive shells always
  reach the runner directly — no cron job can end up waiting inside a TUI.

### Fixed
- **`-s` now overrides `active: false`.** The container loop checked `active`
  before the `-s` match, so an explicitly named but parked container was skipped
  without a word. Naming a container is a deliberate act. An unknown name is now
  an error instead of a run that silently updates nothing.

### Notes
- Stdlib `curses`, no new dependency: the root-run scripts use system Python,
  PEP 668 makes `pip install` as root fail, and `python3-textual` is not
  available across all target distributions.
- Blocks two and three of the design — schema validation and the guided
  assistants for onboarding and backup configuration — are specified in
  `docs/superpowers/specs/2026-08-11-tui-update-runner-design.md` and not yet
  built. `v` in the TUI calls the existing `--validate` until then.

## `ups` Says Only What Matters (11.08.2026)

*getScripts.py v9.10.0, fish/functions/linux/ups.fish v1.1.0*

### Changed
- **The console output is now lean, like `update_docker_odoo.py`'s.** An `ups`
  run touches a dozen tools and every one of them has something to say — apt,
  git, curl, tar and uv all write straight to the terminal, none of it through
  the logger — which buried the handful of lines an operator actually needs.
  Without `-v` the console keeps three things: the status of server
  optimizations (DNS, proxy, repository, phase markers), warnings, and errors.
  Everything else moves to `~/getscripts.log`.
- **Nothing is lost, only moved.** The file handler is untouched and still
  records the whole run at INFO, including the child output the console no
  longer shows — that is what makes dropping lines from the screen safe. The
  header of every run names its mode and the log path, so a pasted excerpt says
  what was left out.
- **A failed command puts its output back on screen.** In lean mode a child's
  output is captured rather than streamed; on a non-zero exit the tail of it
  (capped at 20 lines, the rest pointed at in the log) is appended to the
  warning that reports the failure. Silence is for commands that worked.
- **`ups` forwards its arguments**, so `ups -v` reaches the script instead of
  being swallowed by the function.

### Added
- **`-v` / `--verbose`** restores the old behaviour: every INFO line on screen
  and every child process streaming live. `--debug` implies it, and
  `GETSCRIPTS_DEBUG=1` still works — the flag handling reads
  `getEffectiveLevel()` so it cannot reset what the environment variable set.
- **A `STATUS` log level (25)**, between INFO and WARNING, so a single handler
  level selects status lines together with warnings and errors — no filter, no
  second output channel.
- **`tests/test_getscripts_output.py`** — 15 tests covering the level split,
  the log file's completeness, the failure excerpt and its cap.

### Notes
- **Commands that may prompt are never swallowed.** A captured password prompt
  is an invisible prompt: sudo still reads from the terminal, so the run only
  appears to hang. `chsh` is marked `interactive=True`, and a `sudo …` command
  is streamed whenever passwordless sudo is unavailable.
- The change lives in `getScripts.py` itself. `scripts/lib/` carries a
  near-identical copy of the logging setup and was left untouched: nothing
  imports it, so a change applied there would pass every check and reach no
  server. See the dead-code note under v9.9.0.

## The Keyring apt Was Not Allowed to Read (10.08.2026)

*getScripts.py v9.9.1*

### Fixed
- **The Fish signing key is now readable by `_apt`.** apt drops privileges to
  the unprivileged `_apt` user before it verifies repository signatures, and it
  silently ignores any keyring that user cannot read — warning about it once per
  *configured repository*, so a single unreadable key produced seven warnings on
  every `apt update` and pointed at the innocent Debian mirrors rather than at
  itself. The key is staged through `tempfile.mkstemp()`, which always creates
  its file with `0600` regardless of umask, and the `sudo mv` into
  `/etc/apt/trusted.gpg.d/` preserves that mode. The hardening that made the
  temp file unpredictable (a deliberate fix against symlink races) is what made
  the keyring unreadable — every installation on this code path was affected,
  not just hardened hosts.
- **Existing installations repair themselves.** `fix_apt_keyring_permissions()`
  runs on every invocation, not only when the key is imported, because the hosts
  that already have the wrong mode are precisely the ones that never re-import.
  It touches only keys that are actually unreadable and never aborts the Fish
  setup — a failed `chmod` costs cosmetic warnings, not the install.

### Notes
- The fix lives in `getScripts.py` itself. `scripts/lib/fish_setup.py` carries a
  near-identical copy of the same code and was left untouched: nothing imports
  `scripts/lib/`, so a fix applied there would pass every check and reach no
  server. See the dead-code note under v9.9.0.

## Every Run Leaves a Log Behind (06.08.2026)

*update_docker_odoo.py v5.10.0*

### Added
- **update_docker_odoo.py v5.9.0: a full run log per container**, written to the
  instance's own build folder as `update_<YYYYMMDD>_<HHMMSS>.log`. The console
  output is deliberately lossy — without `-v` every INFO line of a twenty-minute
  update is dropped, and what survives scrolls away. That is the right trade-off
  while watching a run and the wrong one the morning after, when the question is
  what the cron job did at three. The file is written regardless of `-v` and
  keeps what the screen dropped: the section header, every step with its
  timing, and **every** child line at every level, recorded before the filter
  rather than after it.
- **The paths are named at exit**, via `atexit` rather than from the summary
  block — a run that was interrupted or died is exactly the one whose log
  matters, and it never reaches the summary.
- **`.dockerignore` is kept in shape.** The build folder *is* the build context,
  so a year of daily logs would be shipped to the daemon on every build. The
  repository's own `.dockerignore` has excluded `*.log` for a while, but that
  file is the customer's and is distributed by nothing, so an installation may
  have none at all. Opening a log now makes sure the pattern is present —
  appended, never replacing what is there, and a commented-out `# *.log` does
  not count as covered.
- Losing the log never costs the update: a build folder that has vanished or
  cannot be written to produces one warning and the run continues. Every
  function in the block swallows its own I/O errors for that reason, and a test
  pins each case down.
- The suite grew from 110 to 144 cases, 16 of them on the retention alone. The new file is the first coverage
  `update_docker_odoo.py` has ever had; PyYAML is imported at module level but
  used by nothing under test, so a placeholder stands in where it is absent
  rather than adding a dependency to a repository that has none.

- **Retention, configurable in `docker2update.yaml`.** A daily `doup` would
  otherwise leave a file per instance per day forever. Old logs are removed on
  that instance's next run: `defaults.log_retention_days` for the installation,
  `log_retention_days` on a container to override it, `0` to keep everything,
  90 days when nothing says otherwise. An unusable value falls back to the
  default with a warning instead of raising — a typo in the YAML must not be
  able to stop an update, and refusing to delete is the safe direction.
- **The deletion is deliberately narrow**, because the folder is the customer's
  and this is the one part of the feature that destroys something. Only names
  matching `update_<YYYYMMDD>_<HHMMSS>.log` exactly are candidates — not a glob
  on `*.log`, so a `build.log` of their own survives. Directories with a
  matching name are skipped, subfolders are not searched, the log of the running
  update is excluded by path no matter what the clock says, and the age comes
  from the name rather than the mtime: the name records when the run happened,
  an mtime records when something last touched the file.

## Corrections That No Longer Need a Human (06.08.2026)

Both changes close the same gap from the other side: v1.3.0 made the repository's
Dockerfile improvements reach existing installations, but only for directives it
could *add*. Anything that merely differed was reported — correctly, and then
forever, on every single `doup`. A warning that nobody can act on without opening
an editor is a warning everybody learns to scroll past.

### Added
- **odoo_build_cache.py v1.4.0: `ADD` is aligned with the reference's `COPY`.**
  The repository moved `bin/` from `ADD` to `COPY` in July 2026 (`ADD`
  auto-extracts tar archives), and every installation older than that reported
  `missing a repository instruction, add it by hand: COPY bin /app/bin/` on every
  run. The two are the same operation for a plain local path, which makes this
  the one rewrite of a line's content whose effect on the build is provably nil —
  so it is applied instead of reported. Deliberately narrow: the source must not
  be a remote URL (`ADD` fetches it), a local archive (`ADD` unpacks it), a
  wildcard (may be either) or carry a flag beyond `--chown`/`--chmod`/`--link`,
  and the reference must carry *exactly* that `COPY`. An `ADD` the customer added
  themselves is never touched. `_dockerfile_regression()` has to be told about the
  rewrite and accepts only that exact pair — an unannounced one still counts as a
  dropped instruction and refuses the write.
- **odoo_build_cache.py v1.5.0: the build folder's `odoo.conf` is maintained too.**
  It is never distributed for the same reason as the Dockerfile — it carries
  `admin_passwd` and `db_password` — so a setting added to the repository template
  never arrives either. `sync --reference` now also reads the `odoo.conf` beside
  that Dockerfile and fills in `MANAGED_CONF_KEYS`, currently `http_interface`.
  Only where the customer set no value of their own, and an **empty value counts
  as none**: Odoo's `config.py` deletes an empty entry and falls through to its
  default, which is precisely why the warning appeared despite the key being
  present. The value always comes from the template, never hardcoded, and the
  comments explaining it come along — a setting that arrives without the sentence
  saying why it is there invites the next person to remove it.

### Fixed
- **`http_interface` is not cosmetic — it is an Odoo 20 time bomb.** Odoo 19 logs
  `missing --http-interface/http_interface, using 0.0.0.0 by default, will change
  to 127.0.0.1 in 20.0` on every start (v16 and v18 do not: they have no such
  check). The warning names the real problem: on Odoo 20 a container that sets
  nothing will listen on loopback *inside its own namespace*, so the published
  port `127.0.0.1:<port>:8069` leads nowhere and the instance is simply
  unreachable. All three repository templates set the value explicitly since
  03.08.2026; from now on existing installations get it as well, v16 and v18
  included, so the upgrade to Odoo 20 does not walk into a dead instance.
- **A config file is worse to get wrong than a Dockerfile**, because a silently
  changed `db_password` takes the instance down at runtime with no build failing
  first. `_conf_regression()` therefore compares every setting before and after
  and refuses the write if any of them would change, vanish or appear; a
  `.bak_<timestamp>` is taken first, as with the Dockerfile. Keys outside the
  managed list are never added — what else the template contains (`workers`,
  `list_db`) are examples, not policy.
- **v19-odoo/bin/boot v2.4.0: the warning in the `doup` report came from
  somewhere else entirely.** `odoo.conf` only reaches the process that `start`
  launches — `update` and `neutralize` run `odoo-bin` bare, on purpose, so they
  cannot inherit the customer's `addons_path`, `db_host` or worker count. That
  run therefore kept reporting the missing `http_interface` no matter what the
  config said, which is what made the correction look like it had not worked.
  Both now pass `--http-interface=0.0.0.0` explicitly, ahead of the caller's own
  arguments so an explicit one still wins. Nothing about the run changes: with
  `--stop-after-init` there is no HTTP server to bind. Adding `-c "$file"`
  instead would have been the tempting fix and the wrong one — it would hand the
  update run the customer's configuration, a real behaviour change to buy a
  cosmetic line. v16 and v18 keep their boot scripts unchanged; neither version
  emits the warning, so the argument would be a change to a customer image for
  nothing.
- The test suite grew from 60 to 110 cases, all stdlib `unittest`. Beyond the
  happy paths they pin down what must *not* happen: a tar/URL/wildcard source
  stays an `ADD`, an unknown flag stays an `ADD`, a customer's own `ADD` and their
  own config values stay untouched, passwords are never written. Two guards check
  the repository's own files — that every `Dockerfiles/v*/Dockerfile` carries the
  additive directives, and that every `Dockerfiles/v*/odoo.conf` has a value for
  each managed key. Without the second one, a managed key missing from a template
  would quietly do nothing on every server. The nine `boot` cases run the script
  for real against a recording stand-in for `odoo-bin`, rather than grepping it:
  they pin down that `update` gained the argument, that `start` did not (its
  config supplies it), that `update` still does *not* read the config file, and
  that the v16/v18 scripts stayed clean.

## The Dockerfile Update Reaches Existing Installations (04.08.2026)

### Fixed
- **A build folder's Dockerfile never received anything added to the repository since it was created.** `sync_build_scripts()` distributes `build_odoo.py`, `check_dockerimage_odoo.py` and `bin/`, but deliberately not the Dockerfile — that file is the customer's and may carry its own `COPY` and `RUN` steps. The consequence went unnoticed: the `HEALTHCHECK` added to all three repository Dockerfiles in March 2026 is present on no installation commissioned before that date, and no amount of `ups`/`doup` would ever have changed that. The same holds for the July 2026 `ADD` → `COPY` hardening of `bin/`.
  `odoo_build_cache.py sync` now takes `--reference <repository Dockerfile>` and fills in the image directives that are entirely absent — `VOLUME`, `HEALTHCHECK`, `EXPOSE`, inserted ahead of the `ENTRYPOINT` where the reference keeps them, with their explaining comment. These describe the finished image and change no other instruction's behaviour, which is exactly why they are safe to insert. `update_docker_odoo.py` v5.8.0 passes the reference for the container's Odoo version.
- **Everything else is reported, never applied.** An instruction that differs rather than being absent — the customer's `ADD bin /app/bin/` against the repository's `COPY bin /app/bin/`, an extra `RUN` — is printed as a warning naming the exact line and left alone, so it lands in the closing `warnings & errors` block of `doup` for a human to decide on. A step the customer *extended* (`RUN cd /opt/odoo/ && python3 build_odoo.py && pip3 install …`) is not reported: warning about that would train everyone to skip these lines, which is how the one that matters gets missed.
- **The guards from v1.1.1 still hold.** `_dockerfile_regression()` now knows which additions were intended and refuses the write when anything else changed; a `.bak_<timestamp>` copy is still taken first; the `FROM` line stays untouched, since `check_dockerimage_odoo.py` owns it. Running the repository Dockerfile against itself is a no-op, and a second run changes nothing — verified for v16, v18 and v19.
- The Dockerfile step no longer depends on the cache: it runs before the `release.file` check, so a build folder without one is still brought up to date. `ensure_dockerfile_mount()` remains as a thin wrapper for callers that have no reference.
- **Two scripts reported a version they were not.** `bootstrap.sh` carried `1.9.0 — 31.07.2026` in its header while `SCRIPT_VERSION` — the one it prints and the one that appears in a support log — said `1.11.0`. `container2backup.py` had it the other way round: header `4.7.1`, constant `4.7.0 / 19.06.2026`, so `--version` on a customer server named a build from three weeks before the code it was running. Both now agree.
- **Documentation caught up with the code.** The script tables in `docs/INSTALLATION_GUIDE.md` still listed `update_docker_odoo.py` at 5.3.1, `deploy-nginx-base.sh` at 1.1.0 and `server-readiness.py` at 1.0.0, and `odoo_build_cache.py` was absent from every document. Both language sections of the guide and the ReadMe now describe the cache and what it does to the Dockerfile.

## Archives Bind-Mounted Instead of Copied (04.08.2026)

### Added
- **Customer module archives take the same route.** `COPY *custom_modules.* /opt/odoo/` has the identical layer problem as the release archives, only smaller: the archives stay in the image no matter that `build_odoo.py` deletes them after extracting. `populate_build_dir()` (odoo_build_cache.py v1.2.0) now links every `*custom_modules.zip` from the build folder into `zips/` as well, and `build_odoo.py` v2.7.2 looks for them in the working directory **and** in `zips/`. The working directory keeps precedence, so an existing `COPY` behaves exactly as before — but it can now be commented out, and the modules stop inflating the image. That last step stays manual: the patch never removes a line the customer put there.

### Fixed
- **odoo_build_cache.py v1.1.1: the Dockerfile patch destroyed customer changes.** It replaced the content of the `RUN` line with a fixed string, so a step the customer had extended — `RUN cd /opt/odoo/ && pip install --user -r requirements-custom.txt && python3 build_odoo.py` — lost everything after `cd /opt/odoo/ &&`. On a customer server that would have produced an image missing their packages, silently. Only the `RUN ` keyword is replaced now; the rest of the line is carried over verbatim. Three further guards: a customer comment above a legacy `COPY` is no longer swept away with it (only comments this script wrote itself are, recognised by marker), a `.bak_<timestamp>` copy is written before any change, and `_dockerfile_regression()` compares the instructions before and after and refuses to write when anything but the intended mount would change. The Dockerfile belongs to the customer — an extra `COPY`, a different base image or an additional command must all survive.

- **The build cache inflated every image by the size of the release (~270 MB).** `COPY zips/` created its own layer, and Docker layers are additive: the `rm -rf zips` in `build_odoo.py` could only add a deletion marker in a *later* layer, so the archives stayed in the image regardless. The `Permission denied` that made the cleanup visible (`COPY` writes as root, `build_odoo.py` runs as odoo) was the symptom; the cleanup had been pointless from the start.
  The build step now bind-mounts the folder instead: `RUN --mount=type=bind,source=zips,target=/opt/odoo/zips`. The archives are readable for the duration of that step, leave no layer behind, and need neither `--chown` nor a cleanup — the image comes out smaller than before the cache existed.
- **scripts/update_docker_odoo.py v5.7.0**: sets `DOCKER_BUILDKIT=1` for the build (the mount requires BuildKit) and creates `zips/` before building, so a server whose `odoo_build_cache.py` never ran can still build — a bind mount fails on a missing source directory.
- **scripts/odoo_build_cache.py v1.1.0**: `ensure_dockerfile_mount()` replaces `ensure_dockerfile_copy_line()`. It rewrites the `RUN` step and removes a legacy `COPY zips/` line together with the comment block belonging to it. Without this the correction would never reach an existing server: `sync_build_scripts()` does not distribute Dockerfiles.
- **build_odoo.py v2.7.1**: the `rm -rf zips` cleanup is gone — the mount is read-only, and there is nothing left to clean.

## Quiet Runs and a Closing Problem Block (04.08.2026)

### Added
- **update_docker_odoo.py v5.6.2**: prints `update_docker_odoo.py <version> (<date>) · quiet, -v for details` as the first line of every run. A pasted log now says which version produced it, and whether the output was filtered — the two things always asked back first when a report comes in from a server. The constants are kept next to the header comment they mirror.

### Fixed
- **odoo_build_cache.py v1.0.1**: `ensure_dockerfile_copy_line()` also *updates* an outdated form of the line, not just inserts a missing one. The `--chown` correction below would otherwise never reach an existing installation: `sync_build_scripts()` does not distribute Dockerfiles, and the old line was already present, so the insert branch never ran.
- **scripts/update_docker_odoo.py v5.6.1**, from the first live run: `should_filter` was **always false**, with or without `-v`, so the whole verbosity distinction had been dead for as long as it existed. `logging.basicConfig()` configures the *root* logger; the module's own `logger.level` stays at `NOTSET` (0), and `0 > logging.INFO` is false. The `-v` path fared no better: it sets the level to `INFO`, and `20 > 20` is false too. Every `logger.level` comparison now uses `logger.getEffectiveLevel()`, which resolves through the root logger and returns the 30 that was intended. Wiring `docker build` into the same condition in v5.6.0 therefore changed nothing visible — this is what actually makes it quiet.
- **Dockerfiles/v{16,18,19}-odoo**: `COPY zips/` now carries `--chown=odoo:odoo`. `COPY` writes as root even after `USER odoo`, while `build_odoo.py` runs as odoo, so its cleanup `rm -rf zips` failed with `Permission denied` on every archive — and all 273 MB of them stayed in the finished image.
- **scripts/update_docker_odoo.py v5.6.0**: there was effectively no non-verbose mode left. `docker build` was the one long-running step invoked without `filter_output`, so a plain `doup` streamed every line of a ten-to-twenty-minute build — several hundred `Downloaded: …` lines per container — while the Odoo update runs next to it already honoured the setting. It now filters like the rest: without `-v` only warnings and errors appear, with `-v` the full stream as before.
- update_docker_odoo.py: a filtered long-running step keeps its spinner. Previously the first emitted line stopped it for good, on the reasoning that "once output flows, the output is the progress indicator" — true for an unfiltered stream, but with filtering a single warning would leave the remaining twenty minutes of a build without any sign of life. Both writers hold the same lock, so the frame is cleared before a line is written and redrawn afterwards.

### Added
- **update_docker_odoo.py: closing `warnings & errors` block.** Warnings were counted but never collected, and errors only got a short recap when a command failed. So the only way to find out whether a run across a dozen containers had problems was scrolling back through the whole log — and the filtered output above makes that worse, not better, because the interesting lines sit between the step lines of every other container. Every warning and error is now listed once at the end, grouped by container and step, errors first within each group. Repeats of the same message are collapsed with a count (`(3x)`) — the key ignores the leading timestamp columns, otherwise the same warning would count as new on every repetition. Capped at 40 entries with a pointer to `-v` for the rest. Printed before the summary, so its counts refer to the block right above them.

## Build Cache for Release Archives (04.08.2026)

### Added
- **scripts/odoo_build_cache.py v1.0.0**: image builds download only what changed. Until now every build fetched all several hundred archives named in `release.file` — ten to twenty minutes each time, even for a single changed module — because `build_odoo.py` runs *inside* the container, deletes the archives in its cleanup step, and the layer that held them is removed by the `docker system prune -f` that `update_docker_odoo.py` runs after each pass. A BuildKit cache mount would meet the same prune.
  The archive names carry their version (`<modul>_<odoo-version>.<modul-version>.zip`), so the file name is a valid cache key: a name that is present is by definition the right content. No revalidation, no conditional GET, no metadata. `sync <build-dir>` reads the release file, fetches what is missing into `/opt/odoo-build-cache` — partitioned by release URL, so instances on the same release share every archive and two Odoo versions cannot collide — and hardlinks everything into `<build-dir>/zips/`.
  Downloads are atomic (`.tmp` + `os.replace`) and verified with `zipfile.is_zipfile()` before entering the cache. A release server answering an error with a 200 HTML page would otherwise poison it permanently; today such a file dies with the build container.
  Standard library only (`urllib.request` honours `http_proxy`/`https_proxy` by itself, which `build_odoo.py` had to build by hand for urllib3), so nothing new has to be installed on a customer server.
- odoo_build_cache.py: `gc` drops archives unused for 30 days — tracked as the file's `mtime`, refreshed on every hit, so there is no index to keep consistent between parallel runs. Deliberately not "absent from the current release.file": another instance on the same server may still run an older release. It also prunes the `release.file-<timestamp>` copies that `check_dockerimage_odoo.py` has been creating on every run since commissioning and never deleting. Scheduled Sundays 03:30 via the maintenance cron; `stats` shows size per release.
- **Dockerfiles/v{16,18,19}-odoo/.dockerignore**: none existed. The build context is the instance's build folder, which for instances without a volume holds **two** complete filestore copies — the `docker cp` backup and its `.bak` rotation — so both were shipped to the Docker daemon on every build, gigabytes for a large instance. Together with the accumulated `release.file-*` archives they are excluded now.
- **tests/test_odoo_build_cache.py**: the first tests in this repository. `unittest` from the standard library rather than a new framework, with a local `http.server` fixture for the download paths. Run with `python3 -m unittest tests.test_odoo_build_cache`.

### Changed
- **Dockerfiles/v{16,18,19}-odoo/build_odoo.py v2.7.0**: extracts `zips/<name>` when the host provided it, downloads it otherwise. `download_and_extract()` returns `(ok, from_cache)` so the closing summary reports what the cache carried. A missing archive is not an error — the cache is an optimisation, and the existing completeness check stays the authority on whether an image is complete. All three copies remain byte-identical.
- **scripts/update_docker_odoo.py v5.5.0**: runs `odoo_build_cache.py sync` before `docker build` when the script is present, and moves the filestore backup from `<build-dir>/<db_name>` to `<build-dir>/filestore-backup/<db_name>` (with its `.bak` rotation) so the `.dockerignore` above can exclude it by a fixed name.
- **scripts/server-readiness.py v1.3.0**: reports the cache size. Its absence is SKIP, not a warning — a server that never built one simply has none.

### Fixed
- **build_odoo.py: path traversal in the release CSV.** `_validate_csv_filename()` checked `^[A-Za-z0-9._/-]+$`, which permits both `.` and `/` — so `../../etc/passwd` matched it. The value is the target of `open()` and the argument of `unzip -d`, i.e. a manipulated or compromised release file could write outside the build directory. Traversal segments and absolute paths are rejected explicitly now. Found by the parser tests written for the cache, which inherited the same pattern.

## Fix Hints You Can Actually Paste (04.08.2026)

### Added
- **scripts/nginx/ is now the single source for the nginx base files.** `nginx-set-conf` embedded its own copies of `nginx.conf`, `general.conf` and `security.conf`, two revisions behind these. Each tool declared the other's work "drift" and overwrote it on every run, and since nginx-set-conf v1.16.0 that ping-pong had teeth: its pre-flight replaced a working `nginx.conf` with its older copy, `nginx -t` failed on the missing `limit_req`/`proxy_cache` zones (and on the njs `load_module` both copies dropped), and the deploy aborted — leaving the tool unable to deploy anything on such a host. nginx-set-conf ≥ 1.17.0 generates its constants byte-identically from these files (`tools/sync_base_templates.py`, guarded by a test), so both tools now write the same bytes and neither sees drift. Changing a file here means regenerating there and releasing the package.
- **scripts/bootstrap.sh v1.11.0**: `--harden` runs only the two systemd hardening steps and nothing else. It exists because of the mistake below: a report can now name one short command instead of printing a `printf` that has to survive copy & paste. `--help` documents both modes; an unknown option is refused instead of silently starting a full bootstrap.
- **scripts/server-readiness.py v1.2.0**: the multi-line fixes introduced earlier the same day were the wrong answer and are gone. Written out, the `nginx unit` fix ran to roughly 180 characters per line including the indent — it wrapped in every terminal, and the wrapped fragments ran back together when copied, which is worse than the one-line hint it replaced. Both fixes are now `bash <repo>/scripts/bootstrap.sh --harden`, and the detail texts were cut to match: the longest line in the report went from ~180 to 89 characters. The lesson is recorded in `print_report()` — a fix that needs several commands belongs in a script that can be named in one line, not spelled out in the report.
- **scripts/bootstrap.sh v1.10.0**: `harden_nginx_service()` also writes `/etc/systemd/system/nginx.service.d/10-reload-mainpid.conf` (`ExecReload=/bin/kill -s HUP $MAINPID`). Until now no script installed it — it existed only as a manual command in the installation guide, so `server-readiness.py` reported `nginx unit` as WARN on every server indefinitely. The stock nginx.org unit reloads via `kill -s HUP $(cat /run/nginx.pid)`, and a preceding `nginx -t` truncates that pid file to zero bytes: the command degenerates to a bare `kill -s HUP`, the reload reports failure, and the old config silently stays live while the new one looks deployed. The empty `ExecReload=` reset line is mandatory — without it systemd appends to the original command instead of replacing it, and the broken `kill` still runs first. Applied to pre-existing installs too, like the other hardening steps.
- bootstrap.sh: the version header said 1.8.0 while carrying the v1.9.0 changes (the bump was missed on 31.07.2026); it now reads 1.10.0.

### Fixed
- **scripts/nginx/nginxconfig.io/security.conf v1.4**: the Content-Security-Policy allowed `'unsafe-inline'` but not `'unsafe-eval'`. Odoo 17 and later compile their OWL templates at runtime via `new Function()`, which that CSP blocks — the login page renders blank, client-side, with nothing in the nginx log to explain it. This file is deployed by `deploy-nginx-base.sh`, so the header was live on every server that ran it. `nginx-set-conf` had independently arrived at the same conclusion and shipped its copy with the CSP commented out entirely; its whole v1.16.0 pre-flight exists to heal servers carrying this line.
- **scripts/nginx/nginx.conf v1.6**: ends with `include /etc/nginx/conf.local.d/*.conf;`. Carrying `load_module` lines over is not enough for njs — the matching `js_import` lives in the `http` block, which a base-config sync replaces wholesale, so a vhost using `js_access` failed with `no imports defined for "js_access" …`. Rather than chase individual directives, this is a directory no tool writes to, where host-specific http-level directives (js_import, custom maps, upstreams, extra zones) survive every sync. `deploy-nginx-base.sh` v1.3.0 creates it. On an affected host the `js_import` line has to be moved out of `nginx.conf` into e.g. `conf.local.d/njs.conf` once — until then the base config cannot be synced, so the CSP and `http2 on;` fixes do not reach that server.
- **scripts/nginx/nginx.conf v1.5**: `http2 on;` was missing. Since nginx 1.25.1 that directive is the only way to enable HTTP/2 — the `listen ... http2` parameter is deprecated and ignored — and the vhost templates emit a plain `listen <ip>:443 ssl;`. Every vhost on a server using this config was therefore serving HTTP/1.1 only. Found by nginx-set-conf's test suite when the two versions of the file were merged.
- **scripts/deploy-nginx-base.sh v1.2.0**: the main `nginx.conf` deploy no longer drops host-specific `load_module` lines. On a server running njs, `nginx -t` failed straight after the deploy with `unknown directive "js_periodic"` — the versioned template carries no `load_module` line (it cannot: dynamic modules like njs, brotli or geoip2 are installed per host), so overwriting `/etc/nginx/nginx.conf` unloaded the module while the vhost using its directives stayed in place. The rollback worked as designed, which means the deploy was simply impossible to complete on that host. `build_main_conf()` now reads the `load_module` lines out of the existing config and prepends them to the template, deduplicated by `.so` path so a re-run does not stack them.
- deploy-nginx-base.sh: a pre-flight `nginx -t` runs before the first write. A config that was already broken beforehand is now reported as such, and the post-deploy failure says so explicitly instead of pointing at an `nginx.conf` that was never the fault.
- **scripts/server-readiness.py v1.1.0**: the `certbot timer` fix hint was pasted verbatim into a drop-in — parenthetical prose and all. It read `systemctl edit certbot.timer   # OnCalendar=*-*-* 03:00:00 (clear OnCalendar= first)`, which squeezes a four-line file, an editor session and a caveat into one comment; what landed in the drop-in was the literal line `OnCalendar=*-*-* 03:00:00 (clear OnCalendar= first)`, without the `[Timer]` header, which breaks the unit. The hint now spells out the exact file content as commands that can be pasted as they stand, states why the empty `OnCalendar=` line is mandatory, and names `bootstrap.sh` as the alternative.
- server-readiness.py: the `nginx unit` fix named `/root/deploy-nginx-base.sh`, which writes no unit drop-in at all — it only repairs an empty `/run/nginx.pid` at runtime. Neither does `bootstrap.sh` write the `ExecReload=$MAINPID` one (it writes only the `Restart=on-failure` drop-in). The hint now emits the `printf` command for whichever of the two drop-ins is actually missing.
- server-readiness.py: `print_report()` renders a multi-line fix with its continuation lines aligned under the first. A fix that has to state a file's exact content cannot be folded into one line without inviting exactly the paste error above.
- **scripts/server-readiness.py v1.1.1**: the two backup checks read a config schema that does not exist. `check_backup_config()` looked for `odoo_instances` and reported "the backup would do nothing" on a server with five databases configured and backing up nightly; `check_backup_disk_space()` looked for `defaults.backup_folder` and fell back to `/home/backup/`, a path no installation uses, so it reported SKIP instead of checking the disk that actually fills up. `container2backup.py` reads `databases` and `defaults.backup_path` (default `/opt/backups`) — the checks now do the same, including the `expandvars`/`expanduser` the backup applies. The wrong keys came from the example in CLAUDE.md, not from the code.
- **CLAUDE.md**: the `container2backup.yaml` example documented `odoo_instances`, `backup_folder`, `db_pass`, `filestore_paths` and `additional_paths` — none of which container2backup.py ever reads (encryption credentials come from `.env`). Replaced with the keys that are real, plus a pointer to `scripts/container2backup.yaml` as the authoritative commented template.

## Readable Update Output (03.08.2026)

### Changed
- **scripts/update_docker_odoo.py v5.4.0**: the update log is legible again. Three defects compounded each other. `read_pipe()` wrote an 80-blank spinner-clear sequence before *every* line, whether a spinner was running or not — in a customer log that shows up as `update odoo...` followed by a field of padding and only then the next entry. Each passed-through container line was additionally stamped with this script's own timestamp on top of the one Odoo already emits, which with a UTC container and a local host reads like a two-hour clock drift. And in filtered mode errors and warnings were printed live *and* repeated in full at the end.
  Child output now passes through verbatim (`classify_line()`): one timestamp — the child's, redundant date dropped, level column aligned. The spinner only runs on a TTY (`IS_TTY`) and erases itself with `\033[K` instead of blank padding. A failure repeats its errors only once at least `ERROR_RECAP_DISTANCE` lines have scrolled past; otherwise the recap would sit directly beneath the line it repeats.
- update_docker_odoo.py: log-level detection no longer guesses. The old cascade searched the entire line for `" ERROR "` and consequently needed a special case for "INFO line that happens to contain the word error". `classify_line()` reads the level from the actual level field of the Odoo (`<ts> <pid> LEVEL <db> …`) or python (`<ts> - LEVEL - …`) format and only falls back to a content check for lines with no recognisable format.
- update_docker_odoo.py: `clean_docker_system()` follows the same step schema. Its prune listing (deleted containers, untagged images) is suppressed and collapsed into `docker system prune ....... ok, 1.207GB reclaimed (4s)` — the reclaimed space is the only part of that output anyone reads.
- update_docker_odoo.py: the closing summary uses the same schema, under a `══ summary ══` header that is distinguishable from a container section at a glance. It previously went through a local helper inside `main()` that hand-assembled `<timestamp> - INFO - <message>` lines with `time.strftime` — the very double-prefix pattern this release removes, only built by hand to dodge the logger's level prefix. That helper is gone, and with it a second function named `print_summary()` carrying a different signature than the module-level one. The redundant `if not args.validate:` guard around the final cleanup (unreachable when false, being inside the `else` of that same condition) is gone too.
- update_docker_odoo.py: per-container output is structured — a `── <container> ──` section header, compact one-line steps (`stop equitania ....... ok (2s)`) for the short docker calls, streamed blocks for `docker build` and the Odoo update runs, and a closing `→ <db>: N warning(s), M error(s), <duration>`. The startup countdown only counts down on a TTY; under cron it sleeps silently instead of writing carriage returns into the log file. `original_level`/`show_full_output` (assigned, never read) are gone.

### Fixed
- **scripts/update_docker_odoo.py v5.4.2**: the update and neutralize runs no longer ask for a terminal (`docker run -it --rm` → `docker run --rm`). This is the cause of the mangled output seen on the server, where every line began in the column the previous one ended in. Only stdout and stderr of the child are redirected into pipes — its stdin stays attached to the real terminal, so `-t` made the docker client put *that* terminal into raw mode for the duration of the run. Raw mode disables ONLCR, the translation of `\n` into CR+LF, so every `\n` written by this script became a bare line feed and the output walked diagonally down the screen. These are one-shot `--rm` batch containers; nobody types into them, and neither `-i` nor `-t` was ever needed.
- update_docker_odoo.py: as a safety net every write to a terminal is now prefixed with a carriage return (`CR`), which repairs the staircase should any other child leave the terminal in raw mode. It is a no-op in normal cooked mode and is never emitted into a log file, where it would only leave stray `^M` bytes. Verified by replaying the raw byte stream through a raw-mode terminal model: 6 staircased lines without the prefix, 0 with it.
- **scripts/update_docker_odoo.py v5.4.1**, from the first verbose run on a live server: `-v` printed `Command completed successfully with no warnings or errors` in front of *every* step line that already said `ok`, plus `Running command: …` in front of every streamed one. Both are gone (the latter moved to `logger.debug`). The wrapper's own log lines now use `HH:MM:SS LEVEL message` indented to the step column when writing to a terminal — the date repeated on every line of a run that takes minutes; a log file still gets the full timestamp, where the date does matter.
- update_docker_odoo.py: the spinner now stops the moment the child produces its first line, instead of continuing to redraw underneath the streamed output. Two writers competing for the same cursor is a race with no upside — once output flows, the output *is* the progress indicator. The spinner's exit path no longer re-clears a line `emit()` has already taken over.
- update_docker_odoo.py: `read_pipe()` reads to EOF instead of polling with `select()`. The old loop gave up as soon as `process.poll()` reported an exit, so lines still sitting in the text buffer at that moment were dropped — and its `raise TimeoutError` ran on a reader thread where nothing could catch it. The real timeout was, and remains, `process.wait(timeout=…)`; the readers now get 5s to drain instead of 1s.
- **Dockerfiles/v18-odoo/odoo.conf, v16-odoo/odoo.conf**: `http_interface` is now set explicitly to `0.0.0.0` instead of being left empty. Behaviourally identical on those versions, but Odoo 19 warns about the unset value (`missing --http-interface/http_interface, using 0.0.0.0 by default, will change to 127.0.0.1 in 20.0`) — and configs get carried over on upgrades. `127.0.0.1` would be fatal in a container: published ports would stop reaching Odoo. Host-side exposure stays restricted by publishing as `127.0.0.1:<port>:8069`, not by the container's bind address. v19-odoo/odoo.conf already had the value; it gained the comment explaining why it must stay.
- Note for existing servers: `sync_build_scripts()` deliberately never syncs `odoo.conf` (it holds per-instance secrets), so these template changes do **not** reach a running system. A server built before this change keeps the old conf in its build folder and must have the line added there by hand before the next `doup`.

## Server Readiness Report (02.08.2026)

### Added
- **scripts/server-readiness.py v1.0.0**: answers "is this server up to date, and what is still missing?" instead of leaving the administrator to check known problems one by one from memory. Runs 13 read-only checks and prints a traffic-light report in which every non-OK finding carries exactly one copy-paste fix command. The gap it closes: `copy_scripts()` in getScripts.py delivers `setup-maintenance-cron.sh` and its two templates to `/root` but never runs or even mentions them — so on servers still driving the backup from a hand-written `crontab -e` entry, `/etc/logrotate.d/myodoo-maintenance` was never installed and `/var/log/container2backup.log` had been growing unbounded since commissioning, with nothing surfacing it.
  Checks: maintenance cron present/current, logrotate present/coverage, duplicate cron entries (root crontab *and* stray `/etc/cron.d` files — with the managed cron active, a leftover entry means two concurrent dumps of the same database), oversized logs, backup recency, backup config, backup disk space, Docker storage driver (moby#52431), nginx systemd drop-in, certbot timer window, script staleness vs. the repository checkout.
  Modes: full report (default), `--brief` (non-OK only), `--quiet` (silent unless WARN/FAIL — for cron). Exit code 1 on any FAIL. `--root/--home/--repo` allow running it against a fixture tree instead of a live server. A check that raises becomes a SKIP finding rather than costing the whole report.
- **fish/functions/linux/chk.fish v1.0.0**: `chk` runs the full report on demand.
- myodoo-maintenance.cron: weekly readiness report Mondays 06:00 via `--quiet`, deliberately **without** a logfile redirect — `MAILTO=root` delivers it only on actual drift, and appending it to an unwatched logfile would repeat the very mistake the report exists to catch.

### Changed
- **getScripts.py v9.9.0**: delivers `server-readiness.py` and prints the readiness report (`--brief`) after the install summary, so every `ups` run ends with the server's actual state. The readiness exit code deliberately does not propagate — an `ups` run that installed its packages correctly must not fail because a maintenance cron is missing.
- setup-maintenance-cron.sh v1.3.0: `server-readiness.py` added to `MANAGED_SCRIPTS` so its absence is reported at install time.
- docs/INSTALLATION_GUIDE.md v1.2.0, ReadMe.md, usage/AGENT.md, fish/README.md: `chk`/`server-readiness.py` documented (DE/EN).

### Known issue (not addressed here)
- `scripts/lib/` (7451 lines) is dead code: no file in the repository imports it, `getScripts.py` uses only the standard library plus `requests`, and the versions have drifted apart (`lib/constants.py` 9.5.0 vs. getScripts.py 9.9.0). The v8.0 modularisation was apparently never wired up. Left untouched deliberately; its fate needs a separate decision.

## nginx Survives apt Upgrades (31.07.2026)

### Added
- **bootstrap.sh v1.9.0**: installs two systemd drop-ins that close a real outage path found on a release server (two outages in two days, 29./31.07.2026). `harden_nginx_service()` writes `Restart=on-failure` + `RestartSec=10` for nginx — the nginx.org unit ships `Restart=no`, so a start failing transiently while `apt-daily-upgrade` swapped glibc resp. openssl left nginx down until someone noticed; a three-second library swap became an outage of hours. `StartLimitBurst=5`/`StartLimitIntervalSec=300` keep it bounded so a genuinely broken config still fails visibly instead of restart-looping. `harden_certbot_timer()` pins the distro `certbot.timer` to 03:00–03:30 — its stock randomized delay of up to 12 h is what put a renewal at 06:51, inside the apt window, and standalone renewals stop nginx. The empty `OnCalendar=` reset line is mandatory: without it systemd *adds* the schedule to the unit's original one instead of replacing it.
- bootstrap.sh: both hardening steps also run on the "already installed" paths of `install_nginx()` / `install_certbot()`, so re-running bootstrap against an existing production server applies them — those are the hosts that need it most.

### Changed
- docs/INSTALLATION_GUIDE.md v1.1.3: the nginx-outage troubleshooting entry (DE/EN) now notes that bootstrap.sh ≥ 1.9.0 sets both drop-ins automatically.
- usage/AGENT.md: new "nginx dies during apt upgrades" guardrail with the symptom (`Connection refused` on 80 *and* 443 while SSH answers) and the automated remedy.

## No More Silently Incomplete Images (31.07.2026)

### Changed
- **build_odoo.py v2.6.0 (v16/v18/v19)**: a module archive that cannot be installed now fails the build instead of only printing a line. Previously the image was built regardless and shipped silently missing that module — a defect that typically surfaces much later as a puzzling `ImportError` or a menu entry that never appears in Odoo. All failed archives are collected and listed together at the end, so one run reveals every problem rather than exposing them one rerun at a time; filenames rejected by the release-file validator are tracked as failures too, since they are just as absent from the image. A circuit breaker aborts the run after 3 consecutive failures (`BUILD_ODOO_FAILURE_LIMIT`) — without it, a release server that disappears mid-build would burn the full ~45 s retry budget on each of several hundred remaining archives. `BUILD_ODOO_ALLOW_PARTIAL=1` is the deliberate opt-out for builds that knowingly tolerate missing modules.
- build_odoo.py: the closing statistic counts successful downloads only. It previously incremented per *attempt*, so `Files downloaded: 407/407` was printed even when archives had failed.
- docs/INSTALLATION_GUIDE.md v1.1.2: new troubleshooting entry (DE/EN) for the aborted build with the archive list, incl. `BUILD_ODOO_FAILURE_LIMIT` and the `BUILD_ODOO_ALLOW_PARTIAL` opt-out.
- usage/AGENT.md: new "Incomplete images" guardrail; the kernel-vs-module asymmetry noted earlier no longer applies.

## Build Resilience Against Release-Server Downtime (31.07.2026)

### Added
- **build_odoo.py v2.5.0 (v16/v18/v19)**: downloads now survive a briefly unavailable release server instead of aborting the whole image build. Transient failures (connection refused/reset, timeouts, HTTP 408/425/429/5xx) are retried up to 5× with exponential backoff (3 s, 6 s, 12 s, 24 s, capped at 60 s — ~45 s total), which comfortably covers a systemd restart of the web service on the release host. Permanent failures (404/403) still fail immediately rather than wasting four retries on a file that does not exist. Every attempt is logged with its cause and the pending delay (flushed immediately), so a waiting build is visible in the Docker build output instead of appearing to hang; the final message names the unreachable host and points at `systemctl status nginx`. Tunable via `BUILD_ODOO_RETRIES` and `BUILD_ODOO_RETRY_BACKOFF`. urllib3's own retry layer is disabled for these requests so the logged attempt count matches reality.

### Changed
- docs/INSTALLATION_GUIDE.md v1.1.1: two new troubleshooting entries (DE/EN) — aborted builds with `Release server '…' could not be reached` (incl. the caveat that only a failed *kernel* download aborts, while a failed *module* download silently yields an incomplete image), and nginx staying dead after an apt upgrade because it was restarted mid-swap of glibc/openssl while the nginx.org unit ships `Restart=no`, with the `Restart=on-failure` and `certbot.timer` drop-ins as the fix.
- usage/AGENT.md: new "Release-server downtime" guardrail covering the retry behaviour, both env vars, and the kernel-vs-module abort asymmetry.

## Proxy Customer Support & Multi-ZIP Builds (16.–17.07.2026)

### Added
- **docs/INSTALLATION_GUIDE.md v1.1.0**: new chapter 18 "Operation Behind an HTTP Proxy" (DE/EN) — initial installation behind a proxy (session env before bootstrap), the four locations `--proxy-check` writes with their activation points, `docker2update.yaml` `defaults.proxy` + `pre_build_files`, proxy peculiarities (fastfetch, uv, `no_proxy` for internal domains), verification block and troubleshooting table. Distilled from a real proxy-customer deployment.
- usage/AGENT.md: agent capability card for the admin toolkit (LLM-facing usage reference).

### Changed
- Repo hygiene: untrack internal planning artifacts, prune legacy `.gitignore` entries.

### Fixed
- getScripts.py v9.8.0: `--proxy-check` now really writes the Docker daemon systemd drop-in (`docker.service.d/http-proxy.conf` + daemon-reload; deliberately no automatic restart — that restarts all containers) as long documented by update_docker_odoo.py. fastfetch deploy is proxy-aware: the `publicip` module (raw sockets, ignores `http_proxy`, hung every login behind silently-dropping firewalls) gets a 1 s timeout globally and is stripped entirely on hosts with a configured proxy marker; `--proxy-check` re-deploys the config immediately.
- getScripts.py v9.8.1/v9.8.2: no more warning noise from `uv self update` on package-manager installs — the command result is classified instead of guessing from the binary path (unreliable: `pip install --user uv` lands in `~/.local/bin`, the standalone installer's location; pip-wheel and homebrew builds also word the refusal differently). Known "cannot self-update" messages log as INFO skip; real failures keep the WARNING with stderr.
- bootstrap.sh v1.8.0: stage the overlay2 pin on existing Docker installs too (previously fresh installs only).
- build_odoo.py v2.4.0 (v16/v18/v19): extract **all** `*custom_modules.zip` archives from the build context — a second customer-specific archive (e.g. `xy_custom_modules.zip`) was copied into the image but silently never extracted. The generic `custom_modules.zip` is processed first so customer-specific archives can override its modules. Dockerfile template comment widened to `*custom_modules.*`.

## Deployment Tooling, Docker-29 Hardening & Installation Guide (15.–16.07.2026)

### Added
- **docs/INSTALLATION_GUIDE.md**: bilingual (DE/EN) step-by-step guide for system administrators — fresh server → two production Odoo systems (live/test) behind nginx with Let's Encrypt, updates (`edup`/`doup`) and backups (`edbk`/`dobk`). Covers all repository scripts (reference table with usages), the complete fish alias/function reference, and a troubleshooting section built from real rollout lessons (Docker ≥ 29 containerd-store export bug incl. orphaned-overlay-mount aftermath, nginx pid-file reload trap, NAT bind-IP, split-horizon DNS, `db_sslmode`, `127.0.0.1:` port binding). ReadMe.md links the guide prominently and gains a "Scripts at a Glance" usage table (DE + EN).
- ngx-conf-wizard.sh v1.0.0/v1.1.0: interactive YAML config builder for nginx-set-conf — all 19 templates, entry-by-entry loop with validation, append/overwrite with backup, local-IP display with warning on non-local bind IPs (NAT), optional deploy at the end.
- pg-local-deploy.sh v1.2.0: optional self-signed SSL for the PostgreSQL container (server.crt/server.key in PGDATA, RSA-4096, 10 years, idempotent) — mirrored in the Semaphore playbook (`pg_ssl` extra var).

### Changed
- pg-local-deploy.sh v1.2.1: version prompt shows a current example (16.14) plus the Docker Hub tag-search URL.
- fr-local-deploy.sh: default volume base `/opt/fast-report`, current image-tag example.

### Fixed
- bootstrap.sh v1.7.0: pin the classic overlay2 storage driver on fresh Docker ≥ 29 installs (`/etc/docker/daemon.json`) — the containerd image store's export is broken for large builds (moby/moby#52431: `ref … locked: unavailable`, or hollow images missing even `/bin/sh`). Existing installs are never switched automatically; a warning with the manual remediation path is printed instead.
- odoo.conf v16/v18/v19: revert `db_sslmode` to `prefer` — `require` (from the 14.07 security review) broke database creation against every standard PostgreSQL container without SSL.
- getScripts.py v9.7.3: install for root in sudo-spawned root shells (`SUDO_COMMAND` detection) — operators working via `sudo su` previously got the fish config installed into the admin user's home instead of `/root`.
- deploy-nginx-base.sh v1.1.0: surface nginx reload failures (previously swallowed — old config silently stayed live) and repair an empty `/run/nginx.pid` from systemd's MainPID before reloading; internal `SCRIPT_VERSION` aligned with the header.

## Repository Security Review & Hardening (14.07.2026)

Full-repository security review (Python, Shell/Fish, Docker/config) with fixes applied across all severities.

### Added
- pg-local-deploy.sh / fr-local-deploy.sh: password input now shows one `*` per typed character (with backspace), so the number of entered characters is visible while the secret itself stays hidden (`_read_masked`). Same masking added to fr-local-deploy.sh registry-token input and restore-zip.sh password fallback.

### Changed
- fr-local-deploy.sh **[CRITICAL]**: removed the shared "baked default" secrets (JWT signing key, MD5 admin hash, bcrypt superuser hash) — they were identical across all deployments and would be an auth-bypass if the repo is readable. When no override and no existing appsettings.json is present, admin/superuser passwords and the JWT key are now generated **randomly per deployment** (`secrets`) and shown once in the final banner. When the superuser hash is needed and `bcrypt` is missing from the system Python, the script now provisions it automatically in a cached **uv venv** (`~/.cache/fr-local-deploy/venv`) instead of aborting.
- update_docker_odoo.py v5.3.1 **[HIGH]**: `db_password_via_env` now defaults to **true** — the DB password goes via `-e PGPASSWORD` instead of the `docker run` argv (previously visible in `ps aux`). Example YAMLs document the flag.
- bin/boot v2.2.0/v2.3.0 (v16/v18/v19): container entrypoint now whitelists `start|update|neutralize`; arbitrary arguments are no longer executed as root.
- build_odoo.py v2.3.0 (v16/v18/v19): `unzip` runs without `shell=True` (+ CSV filename validation); TLS downloads enforce `cert_reqs=CERT_REQUIRED` with certifi.
- odoo.conf (v16/v18/v19): `db_sslmode = require`; v19 gains a `proxy_access_token` placeholder. Dockerfiles: `ADD` → `COPY`.
- syspatch.fish v1.3.0: dropped the unconfirmed `docker volume prune -f` (could irreversibly delete data volumes of stopped containers); prunes only dangling images now.

### Fixed
- fr-local-deploy.sh **[CRITICAL/HIGH]**: appsettings.json (contains the JWT key in cleartext) now `chmod 0600`; `docker login --password-stdin` and stdin/WGETRC-based basic auth instead of credentials in argv; whitelist validation for container name and image tag (Compose-YAML injection).
- pg-local-deploy.sh v1.1.0 **[MEDIUM]**: whitelist validation for DB user/name; compose file created via `umask 077` (no world-readable TOCTOU window); docker-run fallback uses `--env-file` instead of `-e` for the password.
- container2backup.py v4.7.1 **[HIGH]**: the backup password is masked in log output — the gpg-less 7z fallback no longer writes the cleartext password into the cron log.
- restore-zip.sh v2.1.0: DB password resolved from `PGPASSWORD` env → positional arg (warns) → masked prompt, instead of a plain positional argument visible in `ps aux`; GPG-decrypted dump written with `umask 077`.
- getScripts.py v9.7.2 / proxy_config.py: `no_proxy` is validated before being written into the sourced fish startup file (command-injection); missing `requests.get` timeouts added; predictable `/tmp` download paths replaced with `tempfile.mkstemp`; jammy APT repo over HTTPS.

## Live Version Checks & Fail2Ban Audit Polish (11.06.2026)

### Changed
- getScripts.py v9.5.0: all GitHub/PyPI latest-version lookups (ctop, fastfetch, zoxide, bat, 7zip, pypi_*) now query the live API first; the 24h cache is only used as a fallback when the API is unreachable. Previously `ups` was blind to releases published within a day (e.g. ctop 0.8.7 was ignored while 0.8.6 was still cached). Resilience preserved, freshness restored; GitHub calls without a timeout now use `timeout=15`.
- server_hardening.py v1.8.0: Fail2Ban UFW bans (banaction=ufw, rules commented `by Fail2Ban`) are now reported as **info** with banned IP and jail name instead of "Unbekannte Regel" warnings — the per-ban noise was hiding real configuration drift. All other unexpected UFW rules keep warning as before.

### Fixed
- hardening_config: the four nginx Fail2Ban jails pointed at `/var/log/fail2ban_nginx-*.log` — files nothing ever writes. `--apply` therefore auto-disabled them on every run while the audit kept counting them as errors (unfixable loop). They now parse the real host-nginx logs (`error.log` / `access.log` for bad-request). security_headers: dropped deprecated `X-XSS-Protection` (removed from security.conf v1.3), added `Content-Security-Policy` + `Permissions-Policy` so the audit matches the deployed header policy.

## nightly-cleanup in Standard-Cron (11.06.2026)

### Changed
- nightly-cleanup.sh is now part of the standard maintenance setup: deployed to `/root` by getScripts.py (v9.4.0) and scheduled daily at **04:30** in `/etc/cron.d/myodoo-maintenance` (setup-maintenance-cron.sh v1.2.0) — deliberately after the 02:00 backup window so a container restart can never hit a running backup. Log rotation was already in place. The installer now also warns when the legacy standalone `/etc/cron.d/nightly-cleanup` (old manual instructions, 03:00) is present, which would cause duplicate runs. NIGHTLY_CLEANUP.md (DE+EN) rewritten for the standard path; the manual `/usr/local/bin` install remains documented as an alternative.

## Script Review Follow-up (11.06.2026)

### Added
- restore-zip.sh v2.0.0: Multi-format restore with automatic detection — supports every format container2backup.py produces: `.zip`, `.7z`, `.7z.gpg` (GPG decrypt with passphrase prompt), `.tar.gz`, `.tar.zst`. Previously only `.zip` was supported although `7z` is the backup default. New guards: required inputs are rejected when empty (an empty DB name could previously expand `rm -rf` to the backup root), and the cleanup step can no longer delete `/opt/backups/docker/` itself.

### Fixed
- nginx-cert-guard.py v1.1.0: bracketed IPv6 listeners (`[::1]:443`) are no longer misreported as unresolvable (would have quarantined healthy vhosts); rollback now matches quarantined files by exact path instead of `server_name` (a duplicate server_name could restore vhosts quarantined manually before the run); quarantine report now reads the domain from the renamed file (was read from the no-longer-existing pre-rename path).
- server_hardening.py v1.7.0: banner printed v1.5.0 while the header said v1.6.0 (now a single `SCRIPT_VERSION` constant); defective/empty YAML config now exits with a clear message instead of an `AttributeError` traceback; changing the SSH port now warns loudly when the new port is missing from the UFW rules (lockout guard).
- ssl-renew.sh v1.3.0: if even the final nginx fallback start fails, the script now exits 2 with a clear error instead of exiting 0 with nginx down.
- nightly-cleanup.sh v1.1.0: `POSTGRES_PATTERN` anchors the `db` tokens (`^db-`, `-db$`) — bare `-db`/`db-` also matched containers like `redis-db-cache`; `/var/log/nightly-cleanup.log` added to myodoo-maintenance.logrotate (grew unbounded).
- getScripts.py v9.3.1: removed ghost entry `container2backup_zstd.py` from `copy_scripts()` (file no longer exists).

### Removed (orphaned)
- `config/backup_config.yaml`, `config/backup_credentials.yaml`(+`.example`): leftovers of a pre-`.env` architecture, read by no script; the credentials file was tracked despite its own "NEVER commit" notice (placeholder only, no leak). `.gitignore` now blocks `config/backup_credentials.yaml` permanently.
- `scripts/docker-clean-logs.sh`: unversioned 4-liner with unquoted `rm $(...)`; the `cleandlog` alias never used it (truncates log files directly).

### Docs
- README_BackUp.md, ReadMe.md, .env.example: encryption sections rewritten for GPG/`.7z.gpg` (incl. `gpg -d` restore steps and gnupg dependency), version references refreshed, `db_password_via_env` documented, `pip3 install` replaced with PEP-668-compliant apt packages.

## Security Hardening & IONOS Compatibility (11.06.2026)

### Fixed
- getScripts.py v9.2.0: Fish OBS repo setup no longer requires gnupg (minimal images like IONOS Debian 13 ship without it). The signing key is written as ASCII-armored `.asc`; a failed key download no longer leaves apt broken system-wide (rollback + self-healing of half-configured repos + fallback to the Debian fish package).
- bootstrap.sh v1.6.0: Generates the `en_US.UTF-8` locale on minimal images (IONOS) — eliminates the perl/apt `setlocale` warnings on every command.
- Dockerfiles/v18-odoo: `FROM` pointed at `myodoo/prepare-v16:25.02.24-3.11.11` (copy-paste error). Now `myodoo/prepare-v18:26.05.19-3.13.13`; v19 raised to `myodoo/prepare-v19:26.05.19-3.13.13`.

### Security (project audit follow-up)
- getScripts.py v9.3.0 + scripts/lib: starship, zoxide and uv are no longer installed via `curl … | sh` pipes running unreviewed remote code as root — they now use official GitHub release binaries/.deb packages (same pattern as ctop/fastfetch/7zz). Fisher bootstrap is pinned to the latest tagged release instead of the moving main branch. Fish OBS repo URL switched to https (existing http `.list` files are migrated on the next run).
- container2backup.py v4.6.0: Encrypted backups now use GPG (AES-256, passphrase via fd) producing `.7z.gpg` — the former `7zz -p<password>` exposed the backup password in the process list. Decrypt: `gpg -d backup.7z.gpg > backup.7z`. Falls back to 7z AES (with a loud warning) when gnupg is missing. The `rsync.commands` YAML list now only accepts the rsync binary (no generic root command runner).
- update_docker_odoo.py v5.2.0: New per-container option `db_password_via_env: true` passes the DB password via `PGPASSWORD` environment (docker `-e` forwarding) instead of `--db_password=` in argv (visible in `ps`). Requires images built from 11.06.2026 (boot scripts now whitelist PGPASSWORD across `su`); default remains the legacy argv mode for older images.
- restore-zip.sh v1.4.0: `PGPASSWORD` is forwarded via the environment instead of appearing in the `docker exec` argv.
- requirements: CVE-affected pins raised in prepare-18/prepare-19 (Jinja2 3.1.6, Werkzeug 3.0.6, Pillow 10.4.0/11.3.0, requests 2.32.5, urllib3 1.26.20/2.5.0) and custom libs modernized (pycryptodome 3.23.0, oauthlib 3.3.1, bleach 6.4.0, pandas 2.2.3, numpy 1.26.4, holidays 0.69, xmltodict 0.15.1, pypandoc 1.17, python-docx 1.2.0, pdfminer.six 20260107, msal 1.37.0). Root requirements.txt: requests>=2.32.0, PyYAML>=6.0.2.

## nginx OCSP Stapling Removal (28.05.2026)

### Changed
- nginx/nginx.conf v1.4: Disabled `ssl_stapling` / `ssl_stapling_verify` (with explanatory comment). Let's Encrypt retired OCSP in May 2025; renewed LE certificates no longer carry an OCSP responder URL, so `nginx -t` started logging one warning per certificate at every startup/reload and stapling did nothing useful. Re-enable only if switching to a CA that still issues OCSP-bearing certificates. To apply on a server: `ups` + `sudo /root/deploy-nginx-base.sh` (which will back up the prior nginx.conf before installing the new one).

## Maintenance Cron Follow-up (28.05.2026)

### Changed
- setup-maintenance-cron.sh v1.1.0: After installing `/etc/cron.d/myodoo-maintenance` the script now scans root's user-crontab (`crontab -l -u root`) for legacy entries referencing the managed scripts (`container2backup.py`, `ssl-renew.sh`, `cleanup-weblogs.py`, `nginx-cert-guard.py`) and warns about them — these would otherwise run **in addition** to the cron.d jobs (e.g. backups firing twice a day). Read-only: the script never edits the user crontab (it may contain unrelated operator entries); removal is left to the operator via `sudo crontab -e -u root`. README_BackUp.md updated accordingly.

## nginx Base Rollout & Config Hygiene (27.05.2026)

### Added
- deploy-nginx-base.sh v1.0.0: Rolls out the shared nginx files every vhost depends on — `nginxconfig.io/security.conf`, `nginxconfig.io/general.conf`, `html/custom_50x.html` — to `/etc/nginx`, so a missing `include` can no longer make `nginx -t` fail and take the whole server down on rollout. Also replaces `nginx.conf` safely: backup + `nginx -t` + automatic rollback on failure. Idempotent; `--no-main-conf`, `--dry-run`, `--src`/`--dest`. Deployed to /root by getScripts.py; referenced as a next step in bootstrap.sh (v1.4.2).

### Changed
- nginx/nginxconfig.io/security.conf v1.3: removed deprecated `X-XSS-Protection`; activated an Odoo-tuned `Content-Security-Policy` (ws/wss for longpolling, `frame-ancestors 'self'`). This file is now the single source of truth for security headers.
- nginx/nginx.conf v1.3: removed the duplicate security-header block (headers are not inherited once a child block sets its own — the http-level copy was dead and divergent) and the dead `error_page /404.html` / `/50x.html` directives (vhosts set `/custom_50x.html` themselves).
- nginx/nginxconfig.io/general.conf v1.1: removed the redundant per-vhost `gzip` (it is configured globally in nginx.conf).

## nginx Outage Protection (27.05.2026)

### Added
- nginx-cert-guard.py v1.0.0: Prevents a full nginx outage when a customer's (sub)domain stops pointing at the server. `--reconcile [--start]` brings nginx up at renewal and quarantines only the broken vhost (missing `ssl_certificate` file, or an old `listen <domain>:443` whose host no longer resolves) instead of letting one bad vhost block the whole server; includes a mass-failure guard with rollback so a global fault never causes a blind shutdown. `--check [--apply]` proactively detects drifted domains via DNS and disables them after `GUARD_FAIL_THRESHOLD` confirmed runs (guards against DNS glitches / Cloudflare-fronted domains via a confirmation counter + `GUARD_IGNORE_DOMAINS`). `--list` / `--restore <domain>` for inspection and recovery. SMTP alert mail via `smtplib`.
- Maintenance cron: daily proactive `nginx-cert-guard.py --check --apply` at 23:50, just before the cert renewal; `/var/log/nginx-cert-guard.log` added to logrotate.
- `.env.example`: `ALERT_*` (SMTP relay) and `GUARD_*` (server IPs, ignore list, thresholds) keys.

### Changed
- ssl-renew.sh v1.2.0: nginx is restarted via `nginx-cert-guard.py --reconcile --start` (post-hook + safety net) instead of a bare `systemctl start nginx`, so a single broken vhost can no longer take the whole server down. Falls back to `systemctl start nginx` when the guard is absent.
- getScripts.py: deploys `nginx-cert-guard.py` to /root.

## Server Provisioning & Hardening (27.05.2026)

### Added
- bootstrap.sh v1.4.x: Out-of-the-box initializer for fresh Debian 12/13 and Ubuntu 20.04/22.04/24.04/26.04 — installs Docker CE, nginx, certbot, UFW (disabled), fail2ban baseline, and unattended-upgrades; self-installs to `/opt`, idempotent, every stage toggleable via env var
- server_hardening.py v1.5.0: Config-driven audit/apply hardening tool (`hardening_config.yaml`) covering UFW, fail2ban, SSH, sysctl, sysctl_persist, kernel module blacklist, Docker daemon, auto-updates, auditd, AIDE, nginx, and port modules; lockout-safe SSH swap (atomic after `sshd -t`), dynamic `ALLOWED_IP_<n>` allowlist, detailed `--help`
- dist-upgrade-debian.sh v1.0.0: Guided, phased Debian major release upgrade (e.g. bookworm → trixie) with apt-source backup and reboot prompt; refuses to run on Ubuntu
- setup-maintenance-cron.sh v1.0.0 + myodoo-maintenance.cron/.logrotate: Declarative `/etc/cron.d/` maintenance jobs (backup 02:00/14:00, daily cert renewal, daily DSGVO weblog purge) plus weekly logrotate; idempotent with `--remove`
- bootstrap.sh: certbot (Let's Encrypt client) installation step

### Changed
- ssl-renew.sh v1.1.0: Renew via certbot `--pre-hook/--deploy-hook/--post-hook` — nginx is only bounced when a certificate is actually due (no more unconditional weekly downtime); own logging and an "nginx never left down" safety net
- syspatch.fish v1.2.0: Rebuild the AIDE baseline after a system update; pass `--config` explicitly (AIDE 0.18+ on Debian trixie ships no compiled-in default config)
- getScripts.py v9.0.8/v9.0.9: Switch the 7-Zip download to the `ip7z/7zip` GitHub mirror (fixes 404 on stale pinned URLs), robust 7zz version parsing, and restore the default-shell prompt
- getScripts.py: copy_scripts deploys the new maintenance scripts/templates to `/root`

### Fixed
- container2backup.py v4.5.1: Guard the path-issue confirmation prompt with `sys.stdin.isatty()` — under cron (no TTY) it now aborts cleanly instead of raising `EOFError`
- .gitignore: Remove a corrupted line so `scripts/.env` is reliably ignored
- dist-upgrade-debian.sh: Validate codenames against `^[a-z][a-z0-9]*$` before interpolating into the sed rewrite
- server_hardening.py v1.4.1: Apply AIDE excludes even when a database already exists (prevents the 30+ min Docker-host scan); literal numeric strings no longer int-cast into Docker daemon.json

## Security Hardening (21.04.2026)

### Added
- cleanup-weblogs.py v2.0.0: Atomic log rotation via `nginx -s reopen` (SIGUSR1), fcntl lock against concurrent runs, opt-in cache clearing via `--clear-cache`, backup cleanup restricted to `*.bak` files

### Changed
- container2backup.py v4.5.0: Validate `db_name`, `db_user`, `sql_container`, `data_container` against `[A-Za-z0-9_.-]+` at config-load time; skip invalid entries instead of aborting
- getScripts.py v9.0.7: Cache layer migrated from pickle to JSON

### Fixed
- [H1] container2backup.py: Eliminate all `shell=True` subprocess calls (filestore extract, zip/gzip/zstd compression) — replace with list-form arguments, `Popen` pipelines, and `cwd=` parameter. Closes command-injection vector via YAML-controlled identifiers.
- [H2] scripts/lib/cache.py + getScripts.py: Replace unsafe `pickle.load` with `json.load`; enforce cache-key allowlist (`[A-Za-z0-9._-]+`) to prevent path traversal from cache directory. Existing pickle caches self-heal on first read.

## Security Hardening (17.03.2026)

### Added
- HEALTHCHECK directive for all Odoo Dockerfiles (v16, v18, v19) using wget --spider on /web/health

### Fixed
- [H1] restore-zip.sh: Fix shell injection via unquoted variables, broken bash syntax on lines 205/233, add input validation and set -euo pipefail
- [H2] check_dockerimage_odoo.py: Replace os.system() with subprocess.run() argument lists, add regex validation for Docker image references
- [H3] container2backup.py: Replace shell=True rsync execution with shlex.split() argument parsing
- [H4] getScripts.py, proxy_config.py, dns_optimizer.py: Replace all `echo | sudo tee` shell injection patterns with subprocess.run(input=) (8 locations)

## Version 9.0.0 (26.02.2026)

### Changed
- Migrate CLI tool manager from pipx to uv (`uv tool install/upgrade`)
- Auto-update uv on every run (`uv self update`)
- Auto-upgrade all installed uv tools on every run (`uv tool upgrade --all`)
- Replace all pipx functions with uv equivalents in getScripts.py and package_manager.py
- Rename packages.txt section header from `# PIPX packages` to `# UV tool packages`
- Remove pipx from system packages (uv is installed via curl, not apt)

### Fixed
- Backward compatibility: parser still accepts legacy `# PIPX packages` section header

### Migration
- pipx is automatically uninstalled if still present (after uv tools are installed)
- All pipx-managed tools are migrated to uv tool management
