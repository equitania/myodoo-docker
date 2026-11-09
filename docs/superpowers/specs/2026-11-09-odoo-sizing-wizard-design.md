# Sizing Wizard: Odoo workers, memory limits and PostgreSQL per hardware and role

Date: 09.11.2026 · Status: approved 09.11.2026 (decisions 1–7 and the settled points)

## Why

Every instance gets the same `odoo.conf` from `Dockerfiles/v16-odoo|v18-odoo|v19-odoo/`.
Operators change `db_host`, the passwords and the admin password and leave the rest
alone, so every live, test and demo instance runs with:

| key | value in all three templates |
|---|---|
| `workers` | 3 |
| `max_cron_threads` | 2 |
| `limit_memory_soft` | 2147483648 (2 GiB) |
| `limit_memory_hard` | 2684354560 (2.5 GiB) |
| `db_maxconn` | 100 |

That is wrong in both directions. A live system on a big host is held at 3 workers.
A small host with live + test lets five processes grow to 2 GiB each before Odoo
recycles them, which is several times what the official sizing guide assumes.
And `db_maxconn = 100` is **per process** while each PostgreSQL container allows
100 connections in total.

On the PostgreSQL side `scripts/pg-local-deploy.sh` (1.4.0) offers four fixed
profiles (`2cpu4gb`, `2cpu8gb`, `4cpu16gb`, `8cpu32gb`). It writes one of them as
`PGDATA/postgresql.conf` when the container is created, and nothing touches it
again. Each profile assumes one database has the host to itself (`shared_buffers`
= 25 % of RAM), so live-db and test-db together take 50 % of the RAM next to Odoo.

The captain's request (09.11.2026): a small assistant that sets the configuration
once for the **hardware** and once for the **role**. A demo or a test/staging
instance does not need the performance of the live system.

## Source: the official sizing rules

The deploy guide is word for word the same for Odoo 16, 18, 19 and 20
(odoo.com/documentation/<v>/administration/on_premise/deploy.html, read 09.11.2026):

- **Workers:** the rule of thumb is (#CPU × 2) + 1. Cron workers need CPU too, and
  1 worker serves about 6 concurrent users.
- **Memory:** 80 % of requests are light at about 150 MB and 20 % are heavy at
  about 1 GB. Needed RAM = #workers × (0.8 × 150 MB + 0.2 × 1024 MB), which is
  about 325 MB per worker.
- **Sample:** 4 CPU and 60 users give 8 workers + 1 cron and about 3 GB.
  `limit_memory_soft = 629145600`, `limit_memory_hard = 1677721600`,
  `limit_time_cpu = 600`, `limit_time_real = 1200`, `max_cron_threads = 1`.

## Facts about the current system

- **Typical host:** live and test instance on one host, each with its own
  PostgreSQL container next to it (`live-db`, `test-db`). Confirmed by the captain.
  Hosts with an external database server or several live instances are rare. They
  must not break, but they get no special logic.
- **`odoo.conf` path:** it is baked into the image. The Dockerfile has
  `COPY odoo.conf /opt/odoo/etc/`. The shipped `volume` lines mount only
  `/opt/odoo/data`. So changing the build folder's `odoo.conf` before `doup` builds
  is what reaches the running container.
- **Existing safe write path:** `scripts/odoo_build_cache.py`
  `ensure_odoo_conf_current()` already edits the build folder's `odoo.conf`, limited
  to `MANAGED_CONF_KEYS`, with a `.bak` and `_conf_regression()` as the last gate.
  Its contract is "fill in only where nothing is set". Sizing needs a different
  contract (see below), so it is a sibling function with the same safety pattern,
  not an extension of that list.
- **Instance metadata:** `docker2update.yaml` carries `odoo_version`, `db_host`
  (the database container name on the typical host) and `container_name`.
  PostgreSQL containers are not in any YAML.
- **Wizard API:** `ownerp_wizard.py` `set_fields()` / `add_entry()` are the only
  write path for a customer YAML. The validator (`ownerp_validate.py`) checks
  everything before it is written.

## Decisions taken with the captain

1. **Hardware + role.** The assistant asks for the role of each instance and,
   for live, optionally the number of concurrent users. It reads CPU and RAM from
   the host itself.
2. **Persisted in `docker2update.yaml`, applied by `doup`.** A per-container block
   such as `sizing: {profile: live, users: 30}` with optional explicit overrides.
   A container without the block is untouched, so the feature is opt-in.
3. **A hand edit wins.** When the value in `odoo.conf` (or `postgresql.conf`) was
   changed by hand, `doup` keeps it and only reports the deviation, e.g.
   `workers: hand 8, recommended 5 – unchanged`. `chk` shows the same deviation.
4. **PostgreSQL is tuned too, not just checked.**
5. **Only when called on purpose.** No `ups`/`chk` nagging on hosts without a
   `sizing` block. `chk` reports only for instances that have one.
6. **Live memory limits scale with free RAM.** The floor is the guide sample,
   640 MiB soft / 1.6 GiB hard. Where the RAM allows, the limits grow up to
   today's template values, 2 GiB / 2.5 GiB, and never beyond. Large hosts
   therefore keep today's limits, and small hosts are protected. Test and demo keep
   their fixed values from the table.
7. **First conscious call: show each deviation and ask per value.** On the first
   assistant run for an instance, every current value in `odoo.conf` and the
   database's `postgresql.conf` that differs from the recommendation is listed as
   "current → recommended" and confirmed or kept one by one. Confirmed values go
   into the `sizing` state as "accepted". Kept values are recorded as "kept by
   hand", so `doup` never asks about them again and only reports them. From then
   on rule 3 applies. This replaces any guessing about historic template values:
   the baseline is what the operator confirmed, not what a template once said.

## Goals

- **One budget per host.** The guide's rule holds for the host, not for each
  instance. Live, test, demo and their databases share CPU and RAM, so the
  calculation distributes one budget over everything on the host.
- **A visible reason.** Every number comes with its reason, e.g. "5 workers: 4 CPU
  → 9 processes, test takes 3".
- **Same result everywhere.** `doup`, the assistant, `chk` and `pg-local-deploy.sh`
  use one calculation, so their numbers always agree.
- **Survives a rebuild.** The result lives in the YAML and is applied on every
  `doup`.

## Non-goals

- No monitoring, no load measurement, no auto-scaling.
- No PostgreSQL tuning beyond memory/connection basics: no WAL, checkpoint or
  autovacuum tuning, and no changes to the existing `pg-local-deploy.sh` values for
  those.
- No support logic for external DB servers. If `db_host` is not a local container,
  the PostgreSQL part is skipped and said so.

## Anti-goals (failure even if it "works")

- **Overwriting a customer's hand tuning.**
- **Making a running host worse than before.** A recommendation that fits the host
  less well than the old defaults would count. The calculated total must fit into
  the RAM, and the wizard and `chk` refuse or warn otherwise.
- **Extra downtime.** No database restart while Odoo is serving.
- **A silent change.** Every applied or skipped value appears in the `doup` output
  and in its run log.

## The calculation (my proposal; numbers are starting values, not the captain's)

Input: `nproc`, `MemTotal`, and every container entry of `docker2update.yaml` with
its `sizing` block. An instance without a block counts with its current
`odoo.conf` values, so it still consumes budget.

**Processes.** P = 2 × CPU + 1 Odoo processes (HTTP workers + cron) for the host.

| role | HTTP workers | cron | `limit_memory_soft` / `hard` |
|---|---|---|---|
| live | P − (all other instances) − its cron; minimum 2; with `users`: min(that, ⌈users/6⌉) — warn if ⌈users/6⌉ is larger | 1 (2 when CPU ≥ 8) | scales with free RAM: floor 640 MiB / 1.6 GiB (guide sample), cap 2 GiB / 2.5 GiB (today's template) — decision 6 |
| test / staging | 2 | 1 | 512 MiB / 1.2 GiB |
| demo | 1 | 1 | 384 MiB / 1 GiB |

**RAM split.**
- OS and services: reserve 1 GiB + 10 % of RAM.
- PostgreSQL: all databases together get 25 % of RAM for `shared_buffers`, split
  by role weight (live 3, test 1, demo 1).
- Odoo: the rest. The expected need is Σ processes × 325 MB from the guide, plus
  one gevent process per instance.
- Check: if the expected Odoo need does not fit, the live workers are reduced
  first. If live would drop below 2, the result is a refusal with the reason,
  never a silent squeeze.

**Connections.**
- `db_maxconn` per instance is a small fixed value (e.g. 16).
- That database's `max_connections` = (that instance's processes + gevent) ×
  `db_maxconn` + 10 reserve.
- This is consistent because each instance has its own database container.

**PostgreSQL memory.**
- `shared_buffers`: the share above.
- `effective_cache_size`: about 3 × `shared_buffers`.
- `work_mem`: clamp(the RAM share ÷ (`max_connections` × 2), 4 MB, 64 MB).
- `maintenance_work_mem`: clamp(the RAM share ÷ 8, 64 MB, 1 GB).

**Per version.** `odoo_version` selects which keys exist. 16 has `gevent_port`; 18
adds `limit_memory_soft_gevent`/`limit_memory_hard_gevent` and
`db_maxconn_gevent`; 19 adds `limit_time_worker_cron`. Odoo 20 has no
`Dockerfiles/v20-odoo` yet, so the key table must take a new version without new
logic. The formula is the same for all versions.

## Applying it

**Odoo (`doup`, before the build).**
- **Which keys:** the managed sizing keys are `workers`, `max_cron_threads`,
  `limit_memory_soft`, `limit_memory_hard`, the gevent variants where they exist,
  and `db_maxconn`.
- **Comparison values:** for each key `doup` knows the value it last wrote and the
  repo template's default.
- **Write or report:** if the file still holds one of those, the new value is
  written. Anything else is a hand edit, which is kept and reported.
- **Safety:** `.bak` before the write, plus a regression gate like
  `_conf_regression()` that refuses the write if any other line would change.

**PostgreSQL (`doup`, while the Odoo container is stopped for the update).**
- **Where:** only when `db_host` is a container on this host. The target is
  `postgresql.conf` in that container's data directory, found via
  `docker inspect` mounts, as `pg-local-deploy.sh` writes it today.
- **How:** same compare-write-or-report rule and `.bak` as on the Odoo side.
- **Restart:** a value that needs a restart (`shared_buffers`, `max_connections`)
  restarts the database container in the window where Odoo is down anyway.
- **Verify and roll back:** afterwards `SHOW <key>` checks the values. If the
  database does not come up, the `.bak` is restored, the container is restarted,
  and the update continues with the old values and an error line. It does not
  continue against a dead database.

**`pg-local-deploy.sh`** uses the same calculation for a new container instead of
its four fixed profiles. It falls back to the profiles when the calculation is not
available.

## The assistant (operator view)

- **Entry points:**
  - `wizup` gets the questions "Rolle?" (live / test / demo) and, for live,
    "Gleichzeitige Benutzer (leer = aus Hardware)?".
  - `konsole` gets the same fields in its update form.
  - A standalone read-only report shows the whole host: hardware, budget,
    per-instance result with reasons and deviations. Name it like the other aliases,
    e.g. `dosize`; that is the builder's call.
- **Write path:** writing goes only through `ownerp_wizard.set_fields()`, so
  validation and the atomic replace come for free.
- **What gets written:** the operator confirms the shown result, then the
  `sizing` block is written. The values take effect on the next `doup`, and the
  assistant says so.
- **Language:** German for operator text, like the existing wizard. Every command
  it prints is fish syntax.

## `chk`

A new check, only for instances with a `sizing` block. It reports a deviation (hand
value vs recommendation) as a note. When the host no longer fits the calculation,
for example after a RAM downgrade or a new instance, it reports a WARN. When the
total exceeds the RAM, it reports a FAIL. Each finding gets one fish fix line.

## Constraints

- **Runtime:** delivered scripts run on system Python 3 + `python3-yaml` only, with
  no new dependencies. Version headers and `SCRIPT_VERSION`/`SCRIPT_DATE` must
  agree.
- **Validator:** `ownerp_validate.py` learns the `sizing` block. `profile` is an
  enum, `users` is an int ≥ 1, overrides are typed, and unknown keys get a
  suggestion.
- **Public repo:** `upstream` is public GitHub. No customer names, hosts or IPs in
  code, tests or docs.
- **Docs:** `docs/COMPONENTS.md`, `docs/usage/09-reference.md`,
  `docs/usage/04-updates.md`, `usage/AGENT.md`, `RELEASE_NOTES.md` and the commented
  `scripts/docker2update.yaml` template.

## Settled by Claude after the builder check (09.11.2026; captain may override)

- **Connections.**
  - `db_maxconn` = 16 per process. Odoo needs one or two connections per request,
    so 16 is margin.
  - `max_connections` = max(100, (processes + gevent) × `db_maxconn` + 20). Never
    below today's 100. The reserve of 20 covers `container2backup`, `odoodev`,
    `psql` and the like.
- **`doup` never aborts because of sizing.**
  - A refusal or failure (budget does not fit, unreadable state, PostgreSQL rollback)
    is an `ERROR`/`WARNING` line in the run output and run log. The update continues
    with the unchanged config.
  - The run's exit status follows the existing rules. A sizing error alone makes it
    exit 1, so it is not overlooked. The update itself still happens.
- **`doup -s NAME` recomputes the whole host** (the budget is shared), but
  **applies** only to the named instance. The other instances are read from the
  YAML and their current conf files.
- **Explicit overrides in the `sizing` block are conscious decisions.**
  - They are written even over a differing hand value, because writing them in
    the YAML is the act of deciding.
  - An override that breaks the RAM budget is applied with a `WARNING` in `doup` and
    a WARN in `chk`. The operator decided, the tools make it visible.
  - The assistant refuses to *propose* an over-budget result, but does not block an
    explicit override.
- **Plan-time corrections (09.11.2026).**
  - The guide's sample values are 629145600 / 1677721600 bytes (600 MiB / 1600
    MiB). "640 MiB / 1.6 GiB" above means exactly these bytes, and test's
    "1.2 GiB" means 1200 MiB.
  - "Minimum 2" workers for live holds even with `users` ≤ 12.
  - Before the first review (decision 7), `doup` writes only values that equal
    today's repo template. Every other value is reported as "not reviewed:
    `dosize --review`". After the review, the state file
    (`.sizing_state.json` in the build folder, kept out of the image) governs.
- **`pg-local-deploy.sh` input.**
  - It calls the shared module as a CLI, e.g. `python3 ~/ownerp_sizing.py pg --role
    live --container live-db --json`.
  - The module reads `docker2update.yaml` when present (for the other instances),
    plus `--role`/`--users` from the deploy dialog, which asks for the role.
  - The YAML's `sizing` block wins when both exist.
  - Without the module (old server), the script falls back to its four profiles.

## Left to the builder

- Module layout: a new `scripts/ownerp_sizing.py` for the calculation and report is
  the obvious shape, imported by `update_docker_odoo.py`, `ownerp_wizard.py`,
  `server-readiness.py`, and called from `pg-local-deploy.sh`.
- Where "the value doup last wrote" is stored: a state file in the build folder
  (kept out of the image by `.dockerignore`) or a marker comment in the file
  itself.
- Exact override key names in the `sizing` block, the alias name, rounding of
  memory values.
- Test layout, following `tests/` conventions (stand-in PyYAML, no real Docker).
- **Captain's decisions after the plan (09.11.2026).**
  - **Language:** all sizing output is English, like the surrounding `doup`, `chk`
    and `wizup` lines. This replaces "German for operator text" above.
  - **No refusal for lack of RAM:** when even the minimum (live 2 workers, other
    instances 1 worker) does not fit, the assistant sets this minimal staffing
    anyway and warns with need and budget. `doup` prints a `WARNING` (exit status
    unaffected), `chk` a WARN. This replaces "refuse" in the anti-goals and in
    "The assistant refuses to *propose* an over-budget result".
