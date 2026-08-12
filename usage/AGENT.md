<!--
  Capability Card — generated/maintained via the `cli-capability-card` skill.
  Audience: an LLM/agent that wants to USE this toolkit. Keep it dense and current.
  Command tables extracted from `--help` output (argparse) and script headers (bash)
  on 16.07.2026 — re-extract after CLI changes. No Click introspection available:
  this repo is a multi-script admin toolkit, flag coverage is taken verbatim from
  each script's --help/usage text.
-->
# myodoo-docker — Agent Capability Card

> Server administration toolkit for Odoo-on-Docker hosts: provision a fresh
> Debian/Ubuntu server, harden it, run nginx/PostgreSQL/Odoo containers, and
> keep them updated, backed up and certificate-renewed.

- **Invoke:** scripts live in `~/myodoo-docker/scripts/`; `getScripts.py` deploys the
  operational ones to `/root/` and installs fish aliases (`dobk`, `doup`, `ngxset`, …)
- **Install:** `curl -fsSL https://raw.githubusercontent.com/equitania/myodoo-docker/2026/scripts/bootstrap.sh -o /opt/myodoo-bootstrap.sh && chmod +x /opt/myodoo-bootstrap.sh && /opt/myodoo-bootstrap.sh`
- **Version:** branch `2026`; each script carries its own version header
- **Framework:** Python argparse + bash (no Click) · **Human docs:** `docs/INSTALLATION_GUIDE.md` = the ten-step thread; the instructions themselves are one file per task in `docs/usage/` (DE/EN)

## Capabilities at a glance
- Initialize a fresh Debian/Ubuntu server: Docker CE (overlay2 pinned), nginx, certbot, UFW, fail2ban, auto-updates
- Install the operator shell environment (fish, aliases, management scripts) idempotently
- Audit and apply server hardening (UFW, fail2ban, SSH, sysctl, auditd, AIDE) with per-module control
- Deploy nginx base files + generate reverse-proxy vhosts for Odoo/other services via wizard + `nginx-set-conf`
- Deploy PostgreSQL and FastReport containers interactively (profiles, optional self-signed SSL)
- Update Odoo containers unattended from YAML (image rebuild, module update, restart)
- Add an Odoo instance to the update configuration through a guided assistant that validates before it writes
- Back up Odoo databases (SQL + filestore) with compression/encryption/streaming, and restore them
- Renew Let's Encrypt certificates without needless nginx downtime; quarantine broken vhosts
- Wire all maintenance jobs (backup, renewal, log GDPR purge, memory cleanup) into one cron drop-in
- Perform guided Debian major-release upgrades

## Command reference

All commands run as **root** on the target server. The interactive login shell is **fish**
(`$status`, not `$?`). Flags below are verbatim from `--help` / script usage headers.

| Command | Alias | Purpose | Args / Flags |
|---|---|---|---|
| `bootstrap.sh` | — | Fresh-server baseline init (idempotent) | env: `REPO_BRANCH=2026` `REPO_URL=…` `INSTALL_NGINX=1` `INSTALL_CERTBOT=1` `INSTALL_DOCKER=1` `INSTALL_UFW=1` `INSTALL_FAIL2BAN=1` `INSTALL_UNATTENDED=1` `INSTALL_PYTHON_DEPS=1` `RUN_GETSCRIPTS=1` `SELF_INSTALL=1` (set `0` to skip) |
| `getScripts.py` | `ups` (re-run) | Deploy fish config, aliases, management scripts to `/root`. Console is lean: without `-v` only server-optimization status, warnings and errors appear; every INFO line and all child output (apt, git, curl) goes to `~/getscripts.log`, and a failed command's output tail comes back on screen | `-v/--verbose` · `--clear-cache` · `--no-cache` · `--debug` · `--dns-check` · `--proxy-check` · `--first-run` · `--reconfigure` |
| `server_hardening.py` | — | Audit (default) / apply server hardening | `-c/--config CONFIG` · `-a/--apply` · `-f/--force` · `-m/--module {ufw,fail2ban,ssh,sysctl,sysctl_persist,kernel_modules,docker,auto_updates,auditd,aide,nginx,ports}…` |
| `deploy-nginx-base.sh` | — | Roll out shared nginx includes + maintenance page + nginx.conf (backup/validate/rollback) | `--no-main-conf` · `--dry-run` · `--src DIR` · `--dest DIR` · `--help` |
| `ngx-conf-wizard.sh` | — | Interactive builder for the `nginx-set-conf` YAML (`$HOME/docker-builds/ngx-conf/`) | interactive only (template, domain, cert, ports, "one more?" loop, optional deploy) |
| `nginx-set-conf` | `ngxset` | Generate + deploy vhosts from the wizard YAML (PyPI tool) | `--config_path=$HOME/docker-builds/ngx-conf/` (alias preset) |
| `pg-local-deploy.sh` | — | Deploy a PostgreSQL container (compose file, network, profile, optional SSL) | interactive only (container name, base dir, db user/name, password, PG version, profile `2cpu4gb|2cpu8gb|4cpu16gb|8cpu32gb`, optional host port, optional self-signed SSL) |
| `fr-local-deploy.sh` | — | Deploy the FastReport API container (`/opt/fast-report/<name>/…`) | interactive only (container name, port, image tag, registry token, optional secrets) |
| `update_docker_odoo.py` | `doup` (config: `edup`) | Update Odoo containers from `~/docker2update.yaml` (rebuild image, update DB, restart). Writes a full run log per container to `<build folder>/update_<YYYYMMDD>_<HHMMSS>.log` regardless of `-v`; the paths are listed at exit. Logs older than `log_retention_days` (YAML `defaults` or per container, 90 days default, `0` = keep forever) are removed on that instance's next run. Each container run also appends one line to `~/update-history.jsonl` (`defaults.history_retention_days`, 365 default, `0` = forever) | `-c/--config CONFIG` · `-v/--verbose` · `-s/--specific-container NAME` (repeatable, also comma-separated; **overrides `active: false`**) · `--type {M,F,N}` (runtime mode override, never written to the YAML) · `--comment TEXT` (into the run log header and the history) · `--validate` · `--dns-optimize` |
| `ownerp_tui.py` | `tui` | curses selection screen for ad-hoc updates: lists every system from `docker2update.yaml` with its mode and its last run, then hands the selection to `update_docker_odoo.py` — one invocation per mode group, sequential, worst exit code wins. **Never writes to the YAML.** Keys: Space select · `a` all/none · `m` mode M→F→N · `c` comment · `Enter` start · `v` validate · `w` add an instance / change a field (runs `ownerp_wizard.py`, then reloads the list) · `d` make it `doup`'s default · `?` help · `q`/`Esc` quit | `-c/--config CONFIG` · `--make-default` · `--no-default` |
| `ownerp_wizard.py` | `wiz` | Guided editing of `docker2update.yaml`: add an instance, or change one scalar field of an existing entry. Suggests from the file itself — next free host port across both port fields of every entry, unanimous `db_user`/`db_host`, shared build-folder pattern and image prefix; Enter takes the value in brackets. **The only tool here that writes to a customer configuration**: backup → temp file in the same directory → `ownerp_validate.py` against it → error means temp file *and* backup removed and the original left byte-identical; clean means `os.replace()`. Warnings never block. **Refuses without a TTY**, without `ownerp_validate.py`, or on an unparseable config. Scalars only; **never removes an entry**; `db_password` never echoed or shown | `--update [PATH]` (default `~/docker2update.yaml`) · `--version` (no flag = menu) |
| `container2backup.py` | `dobk` (config: `edbk`) | Back up Odoo DBs (SQL + filestore) + service dirs per `~/container2backup.yaml` | `--sql-only` · `--validate` |
| `ownerp_validate.py` | `doval` | Read-only schema validation of `docker2update.yaml` and/or `container2backup.yaml` — structure, required fields, types, enums, port form, duplicate container/database names and host ports (active entries only), path existence (warning), unknown keys with a suggestion (warning). Findings name the file and line number; never prints a `*password` value; never writes | `--update [PATH]` (default `~/docker2update.yaml`) · `--backup [PATH]` (default `~/container2backup.yaml`) · `--version` (no flag = both, at default paths) |
| `restore-zip.sh` | — | Restore a backup archive (auto-detects `.zip/.7z/.7z.gpg/.tar.gz/.tar.zst`) | positional: `backup_kind(1\|2)` `runsql(v10…v16)` `orig_dbname` `new_dbname` `drop_db(Y/n)` `zip_file` `odoo_volume` `pg_container` `pg_password` |
| `ssl-renew.sh` | — | `certbot renew`; nginx bounced only when a cert is actually due | no flags (daily cron) |
| `nginx-cert-guard.py` | — | Keep nginx up when one vhost breaks; DNS-drift early warning | mode (required): `--reconcile` \| `--check` \| `--list` \| `--restore DOMAIN` · `--start` (with --reconcile) · `--apply` (with --check) · `--dry-run` · `--nginx-conf-dir DIR` · `--state-file FILE` |
| `cleanup-weblogs.py` | — | Rotate nginx logs, GDPR purge > 7 days | `--clear-cache` (also wipe proxy/FastCGI caches — off by default) |
| `nightly-cleanup.sh` | — | Restart containers over memory threshold (Odoo→PG order) | env: `MEMORY_THRESHOLD=90` · `DRY_RUN=1` |
| `setup-maintenance-cron.sh` | — | Install `/etc/cron.d/myodoo-maintenance` + logrotate (idempotent) | `--remove` · env: `SCRIPT_DIR=/root` |
| `server-readiness.py` | `chk` | Report config drift vs. expected server state; read-only, one fix command per finding | `--brief` (non-OK only) \| `--quiet` (silent unless WARN/FAIL; for cron) · `--root DIR` `--home DIR` `--repo DIR` (testing) |
| `dist-upgrade-debian.sh` | — | Guided Debian major upgrade (bookworm→trixie→…) | `[CODENAME]` optional target · `--yes` |
| `check_docker_volumes.sh` | `dkvol` | List volumes + referencing containers | none |

Notation: `[ARG]` optional positional · `ARG` required positional · `a|b` choice · `--flag` boolean.

## Recipes

### Provision a brand-new server end to end
```bash
curl -fsSL https://raw.githubusercontent.com/equitania/myodoo-docker/2026/scripts/bootstrap.sh \
  -o /opt/myodoo-bootstrap.sh && chmod +x /opt/myodoo-bootstrap.sh && /opt/myodoo-bootstrap.sh
mcedit /root/.config/myodoo-docker/.env          # SSH_PORT, ALLOWED_IP_1..n
sudo python3 /root/server_hardening.py           # audit first — changes nothing
sudo python3 /root/server_hardening.py --apply   # then apply (ssh module last, keep a 2nd session open)
```
Full step-by-step walkthrough: `docs/usage/01-provisioning.md`.

### Deploy PostgreSQL + first Odoo container (live)
```bash
~/myodoo-docker/scripts/pg-local-deploy.sh       # interactive: name 'live-db', profile, version 16.x
docker run -d -p 127.0.0.1:11000:8069 -p 127.0.0.1:12000:8072 --restart=always \
  --network live-db-net -v /opt/odoo/live:/opt/odoo/data --name=live-odoo odoo/live:latest start
curl -sI http://127.0.0.1:11000/web/health       # expect HTTP/1.1 200 OK
```
Container entrypoint accepts exactly `start | update | neutralize`.

### Add an nginx vhost for a new domain
```bash
~/myodoo-docker/scripts/deploy-nginx-base.sh     # once per server, before the first vhost
~/myodoo-docker/scripts/ngx-conf-wizard.sh       # append an entry, template eq_odoo_ssl
ngxset && nginx -t && systemctl status nginx     # deploy + verify (start manually if inactive)
```
Behind NAT: bind the **local** IP (wizard lists them), never the public DNS IP.

### Update all active Odoo containers
```bash
python3 ~/update_docker_odoo.py --validate       # config sanity check, no changes
python3 ~/update_docker_odoo.py                  # or: doup — rebuilds image, updates DB, restarts
python3 ~/update_docker_odoo.py -s live-odoo -v  # single container, verbose
```
Per-container `type`: `F` full update · `M` modules only · `N` neutralize then update.

### Update one system ad hoc, without editing the YAML
```bash
tui                                              # pick systems, mode and comment on screen
# the same thing typed out, which is what the screen runs:
python3 ~/update_docker_odoo.py -s live-odoo,test-odoo --type F --comment "eq_stock"
tail -3 ~/update-history.jsonl                   # what ran where, and why
```
Changing the mode on screen changes nothing on disk — `active:` and `type:` in the YAML are
only the pre-selection. `-s` beats `active: false`, so a parked system runs when it is named.
`doup` keeps starting the runner directly until `~/.ownerp_tui_default` exists (`d` in the
screen, or `ownerp_tui.py --make-default`), and even then only for an interactive shell
with no arguments.

### Validate configuration after editing either YAML
```bash
doval                                            # both configs at their default paths
python3 ~/ownerp_validate.py --update ~/docker2update.yaml
python3 ~/ownerp_validate.py --backup ~/container2backup.yaml
echo $status                                     # fish; 0 = no errors, 1 = error(s), 2 = unreadable
```
Read-only, never writes. Check the exit code, not the presence of output — warnings print on a
clean (`0`) exit too.

### Add an Odoo instance to the update configuration
```bash
wiz                                              # menu: 1) add an instance  2) change a field
python3 ~/ownerp_wizard.py --update ~/docker2update.yaml
```
Interactive only — it refuses without a terminal. Enter takes the suggestion in brackets; the
build folder, ports and image name are proposed from the entries already in the file. Nothing is
written until the summary is confirmed *and* the result validates; a rejection leaves the file
byte-identical and names the field to correct. Inside the TUI the same wizard is the `w` key,
after which the list reloads.

### Run / restrict a backup
```bash
python3 ~/container2backup.py                    # or: dobk — full SQL+filestore per YAML
python3 ~/container2backup.py --sql-only         # SQL dumps only, all databases
ls -lah /opt/backups/docker                      # or: llbk
```

### Restore a live backup as a test database
```bash
env PGPASSWORD='<pg-password>' ~/myodoo-docker/scripts/restore-zip.sh 2 v16 \
  live_odoo test_odoo Y /opt/backups/docker/live_odoo-….tar.zst vol-odoo-test test-db
docker exec test-odoo /app/bin/boot neutralize   # disable mails/cron on the copy
```
Prefer `PGPASSWORD` env over the 9th positional arg — the latter is visible in `ps aux`/history.

### Enable unattended maintenance (after backup YAML is configured)
```bash
~/myodoo-docker/scripts/setup-maintenance-cron.sh
```
Installs: backups 02:00+14:00 · ssl-renew 00:00 · cert-guard 23:50 · weblog purge 03:00 · nightly cleanup 04:30.

### Configure a server behind an HTTP proxy
```bash
python3 ~/getScripts.py --proxy-check   # writes fish conf.d, /etc/environment, marker, docker daemon drop-in
systemctl restart docker                # maintenance window — restarts ALL containers
```
Optionally pin the proxy in `docker2update.yaml` (`defaults.proxy`) so cron `doup` runs are
independent of the shell environment. Full walkthrough: `docs/usage/07-proxy.md`.

## Guardrails & gotchas
- **Destructive:** `doup` (type `F`) **stops, removes and re-creates** the target container and
  removes its image before rebuilding — a failed run leaves the system down until re-run.
  `restore-zip.sh` with `drop_db=Y` drops the target DB. Fish aliases `dkprfa`/`dkrmv` wipe
  Docker volumes (data loss) — never use them for cleanup.
- **`--type N` on the command line asks nothing.** Neutralizing rewrites the database's mail
  servers, cron jobs and outgoing interfaces; on a live system that is an outage of everything
  that sends. The second confirmation exists only inside the TUI, which names the affected
  databases before it starts. `update_docker_odoo.py -s live-odoo --type N` runs immediately.
  Never pass `--type N` against a production database without the operator saying so in that turn.
- **`ownerp_wizard.py` (`wiz`) is the only tool in this set that writes to a customer
  configuration.** It refuses without a TTY, so it cannot be driven from a cron job or a
  non-interactive session — for unattended edits use `mcedit`/an editor plus `doval`, not the
  wizard. It never removes an entry, and it edits scalars only: `pre_build_files` and `proxy`
  stay manual. A rejected write leaves the file byte-identical and removes its own backup, so
  the absence of a `.bak-*` after a wizard run means nothing was changed.
- **`-s` overrides `active: false`.** A container parked in the YAML runs when it is named — that
  is deliberate, and it means `-s` is not a filter over the active set but a selection in its own
  right. Check the name against `docker2update.yaml` before running, not against what is running.
- **Prerequisites:** run everything as root on the server. `deploy-nginx-base.sh` must run before
  the first vhost. `container2backup.yaml`/`docker2update.yaml` live in `/root/` (edit via
  `edbk`/`edup`). Hardening needs `/root/.config/myodoo-docker/.env` with `SSH_PORT` (mandatory).
- **Interactive prompts:** `ngx-conf-wizard.sh`, `pg-local-deploy.sh`, `fr-local-deploy.sh` are
  interactive-only (no non-interactive mode) — do not call them from cron/CI.
  `server_hardening.py --apply` prompts unless `-f/--force`; `dist-upgrade-debian.sh` unless `--yes`.
- **Docker ≥ 29:** fresh installs must pin `{"storage-driver": "overlay2"}` (bootstrap ≥ 1.7.0 does).
  After any storage-driver switch **reboot the server** — orphaned overlay mounts otherwise yield
  non-deterministically hollow images (`exec /app/bin/boot: no such file or directory`,
  moby/moby#52431). Cure: reboot → `docker builder prune -af` → `docker build --no-cache --pull`.
- **nginx pid trap:** `nginx -t` can truncate `/run/nginx.pid`; the stock nginx.org unit then fails
  `reload` (kill usage text) while the old config stays live. Use the `$MAINPID` ExecReload drop-in.
- **nginx dies during apt upgrades:** the nginx.org unit ships `Restart=no`, so a start that fails
  mid-library-swap (glibc/openssl under `apt-daily-upgrade`) leaves nginx down until a human
  notices — `Connection refused` on 80 *and* 443 while SSH still answers. `bootstrap.sh` ≥ 1.9.0
  installs a `Restart=on-failure` drop-in and pins `certbot.timer` to 03:00 (its stock ≤12h jitter
  drifts into the 06:00–07:00 apt window, and standalone renewals stop nginx). Both are applied to
  pre-existing installs when bootstrap is re-run.
- **Port bindings:** always map Odoo ports with the `127.0.0.1:` prefix — without it the LAN
  bypasses nginx/SSL. Odoo ≥ 16 uses `/websocket` (templates handle it).
- **Shell:** interactive shell is fish — `$status` not `$?`, no heredocs; run bash snippets via
  `bash -c '…'`. Scripts themselves are bash/python and run normally.
- **Hardening order:** apply the `ssh` module last, with a second open SSH session as safety net.
  `docker` module never auto-restarts the daemon; UFW rules only take effect once UFW is enabled.
- **Proxy hosts:** the Docker daemon drop-in written by `--proxy-check` (getScripts ≥ 9.8.0) only
  takes effect after `systemctl restart docker` — maintenance window, restarts all containers.
  fastfetch's `publicip` module ignores `http_proxy` and is stripped automatically on proxy hosts;
  ~1 s fastfetch runtime is normal (NetIO/DiskIO sampling). Corporate firewalls often drop
  outbound traffic silently — "hangs" usually means missing proxy env, not a slow server.
- **`doval`/`ownerp_validate.py` warnings never flip the exit code.** Exit `0`
  means zero *errors* — warnings (missing path, unknown key, an `(inactive)`
  finding inside a parked `active: false` block) can still be printed on a
  clean exit. A script or cron job that gates on the validator must check
  `$status`/`$?` `!= 0`, never "no output" or "output contains nothing
  alarming". Exit `1` is at least one error; exit `2` means the file itself
  could not be read (missing, unparseable, or PyYAML absent) — nothing was
  actually checked.
- **Custom modules:** every `*custom_modules.zip` in the build folder is extracted into the image
  (build_odoo ≥ 2.4.0; the generic `custom_modules.zip` first, customer-specific archives
  override). Stage archives via `pre_build_files` in `docker2update.yaml`.
- **Release-server downtime:** downloads retry transient failures (connection refused/reset,
  timeouts, 5xx) 5× with exponential backoff, ~45 s total (build_odoo ≥ 2.5.0); 404/403 fail
  immediately. Tune via `BUILD_ODOO_RETRIES` / `BUILD_ODOO_RETRY_BACKOFF`. If the build still
  aborts with `Release server '…' could not be reached`, the web service on the release host is
  down — check `systemctl status nginx` there, then rerun.
- **Incomplete images:** missing module archives fail the build (build_odoo ≥ 2.6.0). All failed
  archives are listed at the end instead of surfacing one rerun at a time; 3 consecutive failures
  abort the run early (`BUILD_ODOO_FAILURE_LIMIT`) so a dead release server cannot burn the retry
  budget on hundreds of archives. `BUILD_ODOO_ALLOW_PARTIAL=1` is the deliberate opt-out and the
  only way to ship an image with modules missing.

## Machine-readable outputs
- `~/update-history.jsonl` is the one machine-readable artefact: JSON Lines, one object per
  container run, newest last. Keys: `ts` (`%Y-%m-%dT%H:%M:%S`, local time), `container`,
  `database`, `mode` (`M`/`F`/`N`), `comment`, `result` (`ok`/`warnings`/`errors`/`failed`),
  `warnings`, `errors`, `duration_s`, `log` (path of that run's log, empty when it could not be
  written), `script_version`. Written after each container, so an interrupted run still leaves
  behind what it did. Read it with `jq` or `python3 -c` — never parse the console output.
- Everything else: use exit codes. `ownerp_validate.py`/`doval` (0 = no errors,
  1 = at least one error, 2 = file missing/unreadable/unparseable or PyYAML
  absent — **warnings never affect the exit code**), `update_docker_odoo.py
  --validate` and `container2backup.py --validate` (both delegate to it and
  inherit that contract), `nginx -t`, `deploy-nginx-base.sh` (non-zero on
  failed reload), `server-readiness.py` (0 = no FAIL, 1 = at least one FAIL;
  WARN/SKIP do not affect it).
  Logs land in
  `/var/log/{container2backup,ssl-renew,cleanup-weblogs,nightly-cleanup,nginx-cert-guard}.log`.
  `server-readiness.py` deliberately writes no log — it reports to stdout so cron mails it.

## Deeper docs
- `docs/INSTALLATION_GUIDE.md` — the ten-step thread from a fresh server to Odoo live/test (DE/EN); each step links into the guide that covers it
- `docs/usage/` — one guide per task, each bilingual and readable on its own:
  `01-provisioning.md` · `02-nginx-certs.md` · `03-postgres-odoo.md` · `04-updates.md` (incl. `wiz`) ·
  `05-backup-restore.md` · `06-maintenance.md` · `07-proxy.md` · `08-troubleshooting.md` · `09-reference.md`
- `scripts/README_BackUp.md` — backup formats, encryption, per-format restore
- `scripts/README_pg-local-deploy.md` — PostgreSQL deploy details, conf profiles, SSL
- `scripts/NIGHTLY_CLEANUP.md` — memory-threshold restart logic
- `docs/MANUAL_DOCKER_UPDATE_GUIDE.md` — manual container update fallback
- `fish/README.md` — complete alias/function reference
