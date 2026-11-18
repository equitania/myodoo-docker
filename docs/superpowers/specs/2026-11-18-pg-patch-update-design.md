# PostgreSQL patch update (`pgup`) — design

Date: 18.11.2026
Status: draft, waiting for approval

## Intent

PostgreSQL publishes patch releases inside a major version (16.11 → 16.12). They
replace the binaries only; the data directory stays as it is. Today nobody on our
servers has a safe, repeatable way to take such a release:

- `pg-local-deploy.sh` can re-deploy onto an existing data directory, but it asks
  every question again, rewrites `postgresql.conf`, takes no backup and does not
  know that an Odoo instance depends on the database.
- Many older servers run the database container from a plain `docker run`. There is
  no compose file to edit.

The operator wants one command that stops Odoo, backs up the database, raises the
image to the newest patch release, brings everything back and proves that it worked.
On the way it should offer the hardware-based memory settings that `doup` and
`pg-local-deploy.sh` already compute.

## Goals

- Update one PostgreSQL container to the newest patch release of its major version.
- Work on compose-managed instances and on legacy `docker run` instances.
- A legacy instance is converted to the compose layout as part of the update
  (decided by the Captain: afterwards every updated server looks the same).
- A backup of every database in the cluster exists before the database container is
  touched.
- The way back is one command, and the tool prints it.
- Show current versus recommended memory settings; change them only on request.
- Usable from a terminal (dialog) and from scripts or agents (flags, no prompts).

## Non-goals

- Major upgrades (16 → 17). The tool refuses them. That is a separate project
  (`pg_upgrade` or dump and restore).
- Images we do not build or that are not the official `postgres` image (for example
  a third-party pgvector image). The tool names the image and stops.
- A database that is not a local container (`db_host` pointing to another machine).
- Moving the data directory, changing its owner (999 stays 999), or changing
  `postgresql.conf` beyond the sizing keys.
- Updating several database containers in parallel. A selection is worked through
  one container at a time.

## Anti-goals

- Odoo comes back up on a database that was not verified.
- A second, empty cluster gets initialised because the new container mounts the
  wrong path. The tool must never let `initdb` run.
- The old container is removed before the operator has confirmed the new one. The
  tool never deletes it; it prints the command for later.
- A silent change of the text sort order (see "Collation guard").

## Constraints

- Delivered script: system Python 3 plus `python3-yaml`, no new dependency.
  `# Version:` header and `SCRIPT_VERSION` / `SCRIPT_DATE` agree
  (`tests/test_delivered_scripts.py`).
- Tool output and documentation in English, like the other Python tools.
- Operators work as root via `sudo su` in fish. Every command the tool prints for
  the operator is fish-compatible (in practice: plain `docker …` lines, no `VAR=…`,
  no heredoc, `$status` instead of `$?`).
- The repository is mirrored to a public GitHub remote: no customer names, hosts or
  addresses in code, tests or docs.
- A compose file that carries the database password is written with mode 0600 from
  the start (umask, not chmod afterwards), as `pg-local-deploy.sh` does.

## Approaches considered

1. **Own Python tool `ownerp_pg_update.py`, alias `pgup`** — chosen. It imports the
   sizing module and the container detection that exist and are tested, calls the
   backup script, and gets unit tests with a fake command runner like
   `ownerp_sizing.py`. Cost: compose files are now produced in two places —
   `pg-local-deploy.sh` for a new instance from answers, this tool from a running
   container. The two have different inputs, so sharing a template would not remove
   much.
2. **Update mode inside `pg-local-deploy.sh`** — rejected. Everything about
   PostgreSQL would stay in one file, but the 2000-line bash script would have to
   parse `docker inspect` and re-implement the `postgresql.conf` patching that
   exists in Python. It is also built around a German dialog and has no flag
   interface.
3. **A switch in `doup`** — rejected. Odoo is down there anyway, but `doup` works
   per Odoo instance while database containers are shared, two unrelated risks
   would land in one run, and legacy hosts without a `docker2update.yaml` entry
   would be left out.

## How it behaves

### Command surface

```
pgup                         # terminal: table of PostgreSQL containers, pick one
pgup --container live-db     # update this one to the newest patch release
pgup --container live-db --to 16.12
pgup --container live-db --dry-run
pgup --container live-db --no-input [--sizing apply|show|skip] [--role live|test|demo]
pgup --container live-db --skip-backup
pgup --rollback live-db
```

Further flags: `--container` is repeatable; `--json` prints the overview below as
JSON and never changes anything.

### Overview, recommendation and selection

The bare call is the entry point (requested by the Captain). For every running
PostgreSQL container it shows:

- the running version (asked from the server) and the Debian base of the image
- the available update: the newest patch release on that base, or "current"
- whether it is compose-managed or legacy
- the Odoo containers that use it and how each is built: Odoo version, image,
  database name, worker count, whether it has a `sizing:` block, and whether the
  database container is shared with other instances
- a recommendation that takes the host into account

```
 #  PostgreSQL  Version  Update           Kind     Odoo
 1  live-db     16.8     16.16-bookworm   legacy   live-odoo (18.0, db live_db, 4 workers)
 2  test-db     16.16    current          compose  test-odoo (18.0, db test_db)
 3  demo-db     15.6     15.x available   legacy   demo-odoo, demo2-odoo (shared)

 1  update recommended; convert to compose; shared_buffers 1GB -> 4GB
 2  nothing to do
 3  update recommended; memory settings stay (shared container)

Select (e.g. 1,3 - a for all recommended - Enter to leave):
```

Recommendations are a fixed set, each with a stable identifier for the JSON output
and one line of plain text: patch update available (with the base it stays on),
conversion to compose, memory settings that differ from the calculation, database
not covered by `container2backup.yaml`, shared database container, major version
out of support (a hint to a separate project, never an action of this tool),
collation version already mismatched, foreign image the tool cannot update.
A recommendation only informs; nothing runs because of it.

Pairing of PostgreSQL and Odoo containers: `pg-local-deploy.sh` has no such logic.
It is taken from `ownerp_migrate.py` (host named in the Odoo container's
environment, then a shared user-defined network) and extended by `db_host` from
`docker2update.yaml`.

Modes:

- **Terminal, no parameters:** overview, then selection by number — one, several
  (`1,3`) or all recommended. Plain input, no additional library. The selected
  containers then go through phases 1 and 2 one after the other: all plans are shown
  together, one confirmation covers them, and the first failure ends the series;
  containers not yet started stay untouched.
- **`--json`:** the same facts as one JSON document — per container: name, version,
  base, available update, kind, Odoo containers with their build, recommendations
  (identifier and text). No prompt, no change. This is the output an agent reads.
- **No terminal, no `--json`:** the overview as text, then exit.
- **`--container …` with `--no-input`:** runs the update for exactly the named
  containers, in the order given.

`--dry-run` runs every read-only check and prints the plan, including the compose
file it would write (password masked), and changes nothing. `--skip-backup` exists
only as a flag and is never offered in the dialog. Exit codes: 0 done or nothing to
do, 1 failed and rolled back, 2 failed and needs the operator.

(Flag names are a proposal of this document; see "Left to the builder".)

### Phase 1 — look, change nothing

1. Find the container, confirm it is PostgreSQL (`ownerp_migrate.is_postgres`) and
   running. Read the running version from the server itself (`SHOW server_version`),
   not from the image tag.
2. Find the target: newest tag `<major>.<n>` on Docker Hub, same logic as
   `_pg_latest_per_major` in `pg-local-deploy.sh` (plain version tags only, proxy
   variables honoured). Without network, `--to` is required. A different major is
   refused. Already newest: say so and exit 0 — unless the instance is legacy, then
   offer the conversion alone.
3. Keep the image variant. A tag suffix such as `-bookworm` or `-alpine` stays. Our
   own pgvector build (`postgres-pgvector:<version>`) is rebuilt with the new
   version from the Dockerfile in the deploy directory; if that file is missing
   (legacy host), the tool writes the same Dockerfile `pg-local-deploy.sh` writes.
   The version of the `vector` extension is recorded before and after; if the new
   image offers a newer one, the report says so and names
   `ALTER EXTENSION vector UPDATE` — the tool does not run it. Any other foreign
   image stops the run.

   Database user for every `psql`, `pg_isready` and dump call: `--db-user`, else
   `POSTGRES_USER` of the container, else `db_user` of a paired entry in
   `docker2update.yaml`, else `postgres`. If none of them can connect, the run stops
   in phase 1.
4. Pull (or build) the new image **now**, while everything is still running. A slow
   registry must not extend the downtime.
5. Collation guard, first half (see below).
6. Find the dependants: Odoo containers paired with this database container
   (`ownerp_migrate` pairing, plus `db_host` entries in `docker2update.yaml`). They
   will be stopped. Other containers on the same network are listed as "will lose
   their connection for a moment" and are left alone.
7. Legacy instance: build the compose file in memory and check that every setting of
   the running container can be carried over (see "Conversion"). If not, stop here.
   `docker compose` (or `docker-compose`) must be present.
8. Backup route per database and free space for it (see "Backup").
9. Sizing: show current versus recommended values.
10. Print the plan, including the expected order and the rollback command. Ask once
    (or continue with `--no-input`).

### Phase 2 — the update

1. Stop the dependent Odoo containers; remember which ones were running.
2. Back up. A failed backup ends the run: Odoo is started again, exit 1.
3. Record the facts to compare later: server version, list of databases, collation
   versions, owner of the data directory.
4. Stop the database container.
5. Legacy: park the old container — rename it to `<name>-pre-<oldversion>` and set
   its restart policy to `no`, so that a reboot cannot start two servers on one data
   directory. Write the compose file.
   Compose-managed: copy the compose file to `docker-compose.yml.bak-<timestamp>`,
   then change the image (and the pgvector build argument) of that one service.
6. `docker compose -f <file> up -d`, wait until the server accepts connections
   (`pg_isready -d postgres`, as in `ownerp_sizing._wait_ready`).
7. Verify: version is the target, the list of databases is identical, the data
   directory owner is unchanged, collation guard second half.
8. Sizing, if requested (the server restarts once more; Odoo is still down).
9. Start exactly the Odoo containers that were running before.
10. Report: old and new version, where the backup is, where the compose file is, the
    rollback command, and for a converted instance the parked container and the
    command to remove it once the operator is satisfied.

If step 6 or the version or database check in step 7 fails, the tool rolls back by
itself and starts Odoo on the old server (exit 1). If only the collation check
fails, the database is fine but its indexes may not be: Odoo stays down, the new
server stays up, and the tool explains the two ways forward (exit 2).

### Rollback

`pgup --rollback NAME` reverses the last update of that container.

- Converted instance: `compose down` for the new container, rename the parked
  container back, restore its restart policy, start it.
- Compose-managed instance: restore the `.bak` compose file, `up -d`.

Going back one patch release inside a major is supported by PostgreSQL, so no
restore from the dump is needed for this — also after Odoo has written to the new
server. The dump is the protection against damage, not the normal way back.

What the rollback needs is kept in a state file at a fixed place that does not
depend on the conversion: `~/pg-deploy/state/<name>.json` (old and new image, parked
container name and its restart policy, compose file and its backup copy, time).
A rollback is possible as long as the parked container, respectively the backup
copy of the compose file, still exists; otherwise the tool says what is missing and
stops. It follows the same order as the update (stop Odoo, switch, wait, verify,
start Odoo). If the update is older than seven days the tool says so and asks for
confirmation (`--no-input` then needs `--force`).

Order and the window in between, for a converted instance: stop the old container →
rename it → set its restart policy to `no` → write the compose file → `up -d`. The
compose service takes the old container name, so the rename has to come first. The
state file is written before the rename. Every failure after the rename is undone
the same way: remove the new container if it was created, rename the old one back,
restore its restart policy, start it.

### Collation guard

The official image tag `16.x` is not tied to one Debian release. If the base system
changes between two patch releases, glibc changes, and with it the sort order of
text. Indexes on text columns built under the old order can then return wrong
results without any error.

- Before: compare the C library of the running container with that of the new image
  (`docker run --rm --entrypoint … <image>`; glibc version, or musl for alpine). If
  they differ, look for a tag that keeps the old base (`16.12-bookworm`) and propose
  it. If there is none, stop and explain.
- After: on PostgreSQL 15 and newer compare `datcollversion` with
  `pg_database_collation_actual_version()` for every database; on older versions the
  comparison before is the only check.

This is not theoretical. Checked against Docker Hub on 18.11.2026: up to 16.8 the
plain tag `16.x` is the bookworm image; from 16.9 on it is the trixie image, and
`16.x-bookworm` is published separately (still available for 16.16). The plain tag
`16.9` itself was moved, so two servers "on 16.9" can sit on different bases — the
base is therefore read from the running container, never derived from the tag.

Consequence for the first version: the tool stays on the base the container has. A
bookworm container on `postgres:16.8` goes to `postgres:16.16-bookworm`, and the
plan says so in one line. Moving a cluster to the newer base (update, then reindex
every database and refresh the collation version) is **not** part of this tool; if
no tag for the old base exists any more, the run stops in phase 1 with that
explanation, also under `--no-input`, and there is no override flag.

### Conversion of a legacy container

The compose file is derived from `docker inspect`, not from a template with
defaults, so the new container is the old one with a different image:

- image, container name, user, restart policy, shm size, memory and CPU limits
- environment: only the variables set on the container, not those of the image
- bind mounts and named volumes as they are; named volumes and networks are declared
  `external: true` so compose adopts them instead of creating new ones; network
  aliases and fixed addresses are kept
- published ports, extra hosts, DNS settings, log options
- command and entrypoint if they differ from the image
- healthcheck: the container's own if it has one, otherwise
  `pg_isready -U <user> -d postgres`

The data directory mount is the critical part. The tool identifies it
(`ownerp_sizing.find_pgdata`), requires `PG_VERSION` to exist in it, and sets
`PGDATA` explicitly so that the image does not choose another path. A data
directory in an anonymous volume is carried over by naming that volume explicitly
as external, with a warning in the plan.

Anything the tool finds in `docker inspect` and does not know how to carry over
(links, devices, added capabilities, …) stops the conversion in phase 1 with the
name of the setting. It never drops a setting silently.

Location of the files: for a bind-mounted data directory `<parent>/<name>-deploy/`,
the layout `pg-local-deploy.sh` and the Ansible playbook already use; otherwise
`~/pg-deploy/<name>/`.

### Backup

Every database of the cluster is covered, by one of two routes:

- **Listed in `container2backup.yaml`** with this container as `sql_container`: the
  normal backup runs for exactly these entries, SQL dump only. This needs a new
  option in `container2backup.py`, `--only-db NAME` (repeatable), which restricts the
  run to the named `databases` entries and skips services, off-site sync and the
  retention cleanup. The result is encrypted and stored where every other backup of
  this server is. The run lock applies: if the nightly backup is running, `pgup`
  stops before it has changed anything beyond stopping Odoo, and starts Odoo again.
- **Not listed** (test and development servers without a backup configuration):
  `pg_dump -Fc` per database into `<deploy dir>/pre-update/<timestamp>/`, directory
  0700, files 0600, after a free-space check against the database size.

`pgup` decides the route, not the backup script: it reads `container2backup.yaml`
(same default path as `dobk`), lists the databases of the cluster and sorts each
one into a route. A missing or unreadable file means every database takes the
second route, and the plan says so. A cluster with listed and unlisted databases
uses both routes in one run. `--only-db` with a name that is not in the `databases`
section is an error (non-zero exit, nothing backed up). Success is the exit code of
the backup run; the report names the configured backup directory.

In both cases `pg_dumpall --globals-only` is written next to the compose file,
because roles are in no per-database dump.

The filestore is not backed up: a PostgreSQL update does not touch it.

### Sizing

The run shows current against recommended values and applies them only after a
"yes" in the dialog or with `--sizing apply`. Default without a terminal: `show`.

- An Odoo instance on this database with a `sizing:` block in `docker2update.yaml`:
  the same plan `doup` uses.
- No such block (the usual case on a legacy host): the role-based calculation
  `pg-local-deploy.sh` uses (`ownerp_sizing.py pg --role …`); the role is asked or
  given with `--role`.

Writing goes through `ownerp_sizing.sync_postgres`, so the existing rules hold
without new code: a value set by hand wins, a database container shared by several
instances is left unchanged, and a change that does not verify is taken back.
A skipped or refused sizing step is a notice in the report, not a failure: the
update itself decides the exit code.

## Delivery

- `scripts/ownerp_pg_update.py` (new, 1.0.0), `scripts/container2backup.py`
  (`--only-db`, minor version bump), both with tests in `tests/`.
- `getScripts.py`: add the script to both file lists that carry `ownerp_sizing.py`.
- fish: alias `pgup` next to `dosize` in `33-aliases-backup.fish`, a row in
  `ownerp-help.fish` (`tests/test_fish_help.py`).
- Docs: `docs/COMPONENTS.md`, `docs/usage/09-reference.md`, `usage/AGENT.md`,
  `RELEASE_NOTES.md`, and a pointer in `scripts/README_pg-local-deploy.md`
  ("to update an existing instance use `pgup`").
- First real run on the demo server: one legacy container, one compose-managed one,
  one with pgvector.

## Calls made in this document (not decided by the Captain)

- Old container is parked, never removed by the tool.
- All Odoo containers on a database container are stopped, other containers on the
  network only listed.
- A selection of several containers runs in sequence and ends at the first failure.
- Selection by typed numbers, no Textual screen.
- With parameters nothing is executed unless containers are named with
  `--container`.
- Sizing is shown by default and applied on request.
- Automatic rollback on a failed start or version check; no automatic action on a
  collation mismatch.
- `--skip-backup` exists as a flag only.
- The tool stays on the Debian base the container already has; moving to the newer
  base with a reindex is a later project.
- Rollback stays possible as long as the parked container or the compose backup
  exists; after seven days it asks again.
- A legacy pgvector instance gets its Dockerfile regenerated; a newer extension
  version is reported, not applied.
- Own dumps are never deleted by the tool; it reports how much space older
  `pre-update/` directories use.
- Tool output in English.

## Left to the builder

- Final flag names (`--dry-run` versus the `--validate` spelling used elsewhere).
- How the script imports `ownerp_migrate` and `ownerp_sizing` (follow what
  `update_docker_odoo.py` does for the sizing module).
- Where the sizing state lives for an instance without a build directory.
- How the image of a compose service is changed without losing comments in the file
  (text patch of one line, guarded by a parse before and after).
- Exact free-space rule for the own dump.
