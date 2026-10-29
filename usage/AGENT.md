<!--
  Capability Card — generated/maintained via the `cli-capability-card` skill.
  Audience: an LLM/agent that wants to USE this toolkit. Keep it dense and current.
  Command tables extracted from `--help` output (argparse) and script headers (bash)
  on 28.09.2026 — re-extract after CLI changes. No Click introspection available:
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
- Let the release manager schedule an update that the server pulls itself (`ownerp_pull_update.py`, no inbound connection)
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
| `getScripts.py` | `ups` (self-updates and restarts mid-run when the repo pull brings a newer version, so one `ups` is enough) | Deploy fish config, aliases, management scripts to `/root`. Console is lean: without `-v` only server-optimization status, warnings and errors appear; every INFO line and all child output (apt, git, curl) goes to `~/getscripts.log`, and a failed command's output tail comes back on screen. On a terminal it also checks the security hardening and offers to close the gaps: if `/root/.config/myodoo-docker/.env` is missing (and no legacy `/root/.env` exists), it offers to create it (`SSH_PORT` from `sshd -T`, `ALLOWED_IP_1` from the current SSH session); then, if any hardening area is off, a menu — fix now / show the commands / later / mute one area. UFW and SSH are only applied when every established SSH connection comes from an allowlist IP, sshd listens on `SSH_PORT` and nothing else, and `ssh.socket` is inactive; otherwise it prints the commands and, on a port mismatch, the six-step port-change sequence. Docker is not subject to this gate — its `daemon.json` is written either way, but the daemon restart only runs when that apply succeeded and no container exists at all (running or stopped). Never changes the SSH port. **First run (≥ 9.34.0):** the first-run dialogue has three blocks — proxy, DNS, SSH access (fixed port + comma-separated admin addresses, writes the `.env` at once; networks rejected). When `docker` is missing right after the clone, it offers `bash <repo>/scripts/bootstrap.sh` (runs it with `RUN_GETSCRIPTS=0`; without a TTY it prints only that one command line and continues; a decline is remembered in `~/.config/myodoo-docker/bootstrap-declined` and silences the offer). As root it needs no `sudo` package; version probes run under `LC_ALL=C` | `-v/--verbose` · `--clear-cache` · `--no-cache` · `--debug` · `--dns-check` · `--proxy-check` · `--first-run` · `--reconfigure` · `--restricted` (no root: only the user's own Fish environment + the Debian packages the admin must install; asked automatically without root/passwordless sudo, remembered in `~/.getscripts_restricted`, Debian 13+ only; DNS/proxy flags exit 1 there) |
| `server_hardening.py` | — | Audit (default) / apply server hardening. Delivered to `/root/server_hardening.py` since getScripts 9.26.0 — that path in the recipes below is now literal, not aspirational | `-c/--config CONFIG` · `-a/--apply` · `-f/--force` · `-m/--module {ufw,fail2ban,ssh,sysctl,sysctl_persist,kernel_modules,docker,auto_updates,auditd,aide,nginx,ports}…` · `--json` (audit only, exclusive with `--apply`: one JSON document on stdout, writes nothing, admin IPs appear only as their `.env` comment or `ALLOWED_IP_<n>` — never the address; consumed by `server-readiness.py` and by `ups`'s offer). Modules always run in a fixed order (`ufw` before `fail2ban` before `ssh`) regardless of the order given to `-m` · `--ssh-transition begin / finish / status` (1.12.0: safe port change — the old port stays open until a login on the new one; `finish` runs on every `ups`) · `--no-reboot` |
| `deploy-nginx-base.sh` | — | Roll out shared nginx includes + maintenance page + nginx.conf (backup/validate/rollback) | `--no-main-conf` · `--dry-run` · `--src DIR` · `--dest DIR` · `--help` |
| `ngx-conf-wizard.sh` | — | Interactive builder for the `nginx-set-conf` YAML (`$HOME/docker-builds/ngx-conf/`) | interactive only (template, domain, cert, ports, "one more?" loop, optional deploy) |
| `nginx-set-conf` | `ngxset` | Generate + deploy vhosts from the wizard YAML (PyPI tool) | `--config_path=$HOME/docker-builds/ngx-conf/` (alias preset) |
| `pg-local-deploy.sh` | — | Deploy a PostgreSQL container (compose file, network, profile, optional SSL) | interactive only (container name, base dir, db user/name, password, PG version — suggests the newest from Docker Hub, Enter accepts, profile `2cpu4gb|2cpu8gb|4cpu16gb|8cpu32gb`, optional host port, optional self-signed SSL, optional pgvector — default off, `y` builds `postgres-pgvector:<version>` from `postgres:<version>` + `postgresql-<major>-pgvector`; a re-deploy without pgvector exits 1 when a database already uses `vector`). Since 1.4.0 a NEW instance runs as `postgres:5432` (compose `user:`, host user created); a re-deploy keeps the PGDATA owner, older instances stay at 999. `PGDATA` is set explicitly so `postgres:18+` works with the `/var/lib/postgresql/data` mount |
| `fr-local-deploy.sh` | — | Deploy the FastReport API container (`/opt/fast-report/<name>/…`) | interactive only (container name, port, registry token, image tag — suggested from the registry's tag list after the token, optional secrets). The image runs as `frapi` UID 10000 (fixed at build time, entrypoint drops privileges via gosu — never add `user:`); the script only creates the host user `frapi:10000` |
| `update_docker_odoo.py` | `doup` (config: `edup`) | Update Odoo containers from `~/docker2update.yaml` (rebuild image, update DB, restart). Writes a full run log per container to `<build folder>/update_<YYYYMMDD>_<HHMMSS>.log` regardless of `-v`; the paths are listed at exit. Logs older than `log_retention_days` (YAML `defaults` or per container, 90 days default, `0` = keep forever) are removed on that instance's next run. Each container run also appends one line to `~/update-history.jsonl` (`defaults.history_retention_days`, 365 default, `0` = forever) | `-c/--config CONFIG` · `-v/--verbose` · `-s/--specific-container NAME` (repeatable, also comma-separated; **overrides `active: false`**) · `--type {M,F,N}` (runtime mode override, never written to the YAML) · `--comment TEXT` (into the run log header and the history) · `--validate` · `--dns-optimize` · `--release-file PATH` (install exactly this release instead of asking the release manager; needs exactly one `-s`) |
| `ownerp_tui.py` | `tui` | curses selection screen for ad-hoc updates: lists every system from `docker2update.yaml` with its mode and its last run, then hands the selection to `update_docker_odoo.py` — one invocation per mode group, sequential, worst exit code wins. **Never writes to the YAML.** Keys: Space select · `a` all/none · `m` mode M→F→N · `c` comment · `Enter` start · `v` validate · `w` add an instance / change a field (runs `ownerp_wizard.py`, then reloads the list) · `d` make it `doup`'s default · `?` help · `q`/`Esc` quit | `-c/--config CONFIG` · `--make-default` · `--no-default` |
| `ownerp_wizard.py` | `wiz` | Guided editing of `docker2update.yaml`: add an instance, or change one scalar field of an existing entry. Suggests from the file itself — next free host port across both port fields of every entry, unanimous `db_user`/`db_host`, shared build-folder pattern and image prefix; Enter takes the value in brackets. **The only tool here that writes to a customer configuration**: backup → temp file in the same directory → `ownerp_validate.py` against it → error means temp file *and* backup removed and the original left byte-identical; clean means `os.replace()`. Warnings never block. **Refuses without a TTY**, without `ownerp_validate.py`, or on an unparseable config. Scalars only; **never removes an entry**; `db_password` never echoed or shown | `--update [PATH]` (default `~/docker2update.yaml`) · `--version` (no flag = menu) |
| `container2backup.py` | `dobk` (config: `edbk`) | Back up Odoo DBs (SQL + filestore) + service dirs per `~/container2backup.yaml`. Exit 1 + `Backup FAILED for …` when any database got no archive (container name not found, dump failed); that database's old archives are kept | `--sql-only` · `--validate` |
| `ownerp_validate.py` | `doval` | Read-only schema validation of `docker2update.yaml` and/or `container2backup.yaml` — structure, required fields, types, enums, port form, duplicate container/database names and host ports (active entries only), path existence (warning), unknown keys with a suggestion (warning). Findings name the file and line number; never prints a `*password` value; never writes | `--update [PATH]` (default `~/docker2update.yaml`) · `--backup [PATH]` (default `~/container2backup.yaml`) · `--version` (no flag = both, at default paths) |
| `ssl-renew.sh` | — | `certbot renew`; nginx bounced only when a cert is actually due | no flags (daily cron) |
| `nginx-cert-guard.py` | — | Keep nginx up when one vhost breaks; DNS-drift early warning | mode (required): `--reconcile` \| `--check` \| `--list` \| `--restore DOMAIN` · `--start` (with --reconcile) · `--apply` (with --check) · `--dry-run` · `--nginx-conf-dir DIR` · `--state-file FILE` |
| `cleanup-weblogs.py` | — | Rotate nginx logs, GDPR purge > 7 days | `--clear-cache` (also wipe proxy/FastCGI caches — off by default) |
| `nightly-cleanup.sh` | — | Restart containers over memory threshold (Odoo→PG order) | env: `MEMORY_THRESHOLD=90` · `DRY_RUN=1` |
| `setup-maintenance-cron.sh` | — | Install `/etc/cron.d/myodoo-maintenance` + logrotate (idempotent) | `--remove` · env: `SCRIPT_DIR=/root` · `ups` runs it once by itself when the cron file is missing and Docker is present (getScripts 9.35.0) |
| `ownerp_cron.py` | `docron` (edit: `konsole`) | Report + guided editing of `/etc/cron.d/myodoo-maintenance`. **Bare call on a real terminal is interactive**: report, then a German numbered on/off menu (a script name is one entry even when it is two cron lines, e.g. `container2backup`). **Agents must never rely on that prompt** — always pass `--brief`/`--json`/`--set`/`--enable`/`--disable`, or `--no-input` for the plain report; every one of those (and any non-TTY invocation) skips the menu exactly as before | `--path FILE` · `--brief` · `--json` · `--no-input` (suppress the menu on a terminal) · `--set JOB --schedule EXPR` · `--enable JOB` \| `--disable JOB` (script name, with or without `.py`, switches every line of it) |
| `ownerp_pull_update.py` | — | Pull-update agent (cron, every 5 min): asks the release manager (`GET <RM_PULL_URL>/rm/api/v1/job`, Bearer token per instance) whether an update is due for an instance here, checks the job against this server, runs `update_docker_odoo.py -s <container> --release-file <file> --comment "pull update run <id>"`, reports start and finish back. Does nothing and prints nothing without `RM_PULL_URL` and a token. Delivered to `/root` by `getScripts.py` ≥ 9.33.0; config in `/root/.config/myodoo-docker/.env` | `--check` (list configured instances, contact nobody) · exit 0 nothing to do / all done, 1 job failed or refused, 2 config error |
| `server-readiness.py` | `chk` | Report config drift vs. expected server state; read-only, one fix command per finding. A host with `docron --disable container2backup` or `docron --disable odoo_build_cache` mutes the checks that job explains (`backup_recency`+`backup_config`, or `update_config`) instead of failing on a config that is missing on purpose; `resolved_dnssec` FAILs when systemd-resolved validates DNSSEC (`yes`/`allow-downgrade`), because a root key change unknown to the installed systemd turns every lookup into SERVFAIL (happened 11.10.2026 on Ubuntu 22.04); `dns_resolution` is the one check that touches the network — one `getent ahosts github.com`, and only on failure one direct query to `1.1.1.1` (FAIL; WARN on a proxy host when neither answers); `dostat`/`konsole` show the same host as `off`, not as an error. Nine checks run `server_hardening.py --json` once per report and share its result: `hardening_env`, `hardening_firewall`, `hardening_fail2ban`, `hardening_ssh` (FAIL when off) and `hardening_kernel`, `hardening_docker`, `hardening_updates`, `hardening_integrity`, `root_login_locked` (WARN when off) — each mutable on its own (`ownerp_mute.py hardening_firewall --reason "…"`), so a server that deviates on purpose (e.g. behind a corporate firewall) mutes only that part. SKIP when `server_hardening.py` is missing or its audit fails, never a false alarm | `--brief` (non-OK only) \| `--quiet` (silent unless WARN/FAIL; for cron) \| `--muted` (list this host's muted checks) · `--root DIR` `--home DIR` `--repo DIR` (testing) |
| `dist-upgrade-debian.sh` | — | Guided Debian major upgrade (bookworm→trixie→…) | `[CODENAME]` optional target · `--yes` |
| `check_docker_volumes.sh` | `dkvol` | List volumes + referencing containers | none |

Notation: `[ARG]` optional positional · `ARG` required positional · `a|b` choice · `--flag` boolean.

## Recipes

### Provision a brand-new server end to end
```bash
curl -fsSL https://raw.githubusercontent.com/equitania/myodoo-docker/2026/scripts/bootstrap.sh \
  -o /opt/myodoo-bootstrap.sh && chmod +x /opt/myodoo-bootstrap.sh && /opt/myodoo-bootstrap.sh
ups   # on a terminal: first-run dialogue (proxy, DNS, SSH port + admin IPs), bootstrap offer, cron, ONE hardening question
```
Since getScripts 9.35.0 the hardening is one question — `Härtung jetzt anwenden? (j/N)` — preceded by
what applying means (new SSH port instead of the live one, access only from `ALLOWED_IP_n`, firewall,
fail2ban, security updates *without* the nightly reboot: `--no-reboot` is always passed). A pending
port change runs `server_hardening.py --ssh-transition begin`: sshd listens on old+new port, UFW admits
both for the admin IPs, the old port closes on a later `ups` once a login over the new port from an
admin IP exists (`--ssh-transition finish`; `chk` reports "Portwechsel läuft" until then). The lockout
check keeps: every established SSH session on the allowlist, at least one `ALLOWED_IP_n`, readable
`sshd -T`/`ss`; when it blocks, firewall/fail2ban/SSH wait with one status line and the other areas are
still offered. `docker` is not subject to this check — its `daemon.json` is applied, but the daemon
restart needs that apply to have succeeded and no container to exist at all (running or stopped).
A provider firewall (Hetzner Cloud Firewall, security group) must open the new port — nothing on the
host can do that. Manual alternative, e.g. from cron/CI or to control the order by hand:
```bash
mcedit /root/.config/myodoo-docker/.env                         # SSH_PORT, ALLOWED_IP_1..n
sudo python3 /root/server_hardening.py                          # audit first — changes nothing
sudo python3 /root/server_hardening.py --ssh-transition begin   # port change + ufw/fail2ban/ssh, both ports open
sudo python3 /root/server_hardening.py --ssh-transition status  # none | pending OLD -> NEW
sudo python3 /root/server_hardening.py --ssh-transition finish  # after a login on the new port: close the old one
sudo python3 /root/server_hardening.py --apply --no-reboot      # everything else (ssh module last, keep a 2nd session open)
```
Full step-by-step walkthrough: `docs/usage/01-provisioning.md`.

### Deploy PostgreSQL + first Odoo container (live)
```bash
~/myodoo-docker/scripts/pg-local-deploy.sh       # interactive: name 'live-db', profile, version (newest suggested)
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
# Exit 1 = at least one container failed. Since 5.22.0 that includes an Odoo run that exits 0
# but logs "Failed to initialize database"/"Failed to load registry" (entrypoint before
# bin/boot 2.5.0/2.8.0 dropped Odoo's status). After a failed update the container is NOT running.
# Since 5.23.0 a container also fails - BEFORE anything is stopped - when odoo_version in
# docker2update.yaml names another Odoo version than the release (kernel archive in release.file).
# Since 5.24.0 the image's odoo user is UID/GID 8069 (was the base image's first free UID, mostly
# 1000). The first doup after that change chowns /opt/odoo/data to 8069 once, before the new image
# starts ("data owner uid 1000 -> 8069"); a 100+ GB filestore takes minutes. Do not chown back.
# getScripts >= 9.29.0 (ups, as root) creates the matching host user odoo:8069 (nologin, locked);
# an existing odoo with another UID or another owner of 8069 is left alone (install summary).
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
Use the odoodev playbooks in `~/myodoo-docker/Dockerfiles/playbooks` (odoodev ≥ 0.75.7; they
replace the withdrawn `restore-zip.sh`). Target `test-odoo`/`test-db`, source the newest
`live-odoo` backup; every state ends neutralized, EBICS uninstalled, verified.
```bash
cd ~/myodoo-docker/Dockerfiles/playbooks
python3 generate.py --version 18 --out ~/playbooks   # values from docker2update/container2backup YAML
mkdir -p /opt/backups/prerestore /opt/backups/restore-tmp
cd ~/playbooks && odoodev run neutral.yaml --dry-run && odoodev run neutral.yaml
# states: neutral anonym anonym-leer stammdaten vorlage · wiederherstellen · passwoerter
```
Never mark modules `to remove` via SQL and run `-u` — doup's `-u all` resets them and
`odoo-bin -u` next to the running server deadlocks; use odoodev `server.uninstall`.

### Enable unattended maintenance (after backup YAML is configured)
```bash
~/myodoo-docker/scripts/setup-maintenance-cron.sh
```
Installs: backups 02:00+14:00 · ssl-renew 00:00 · cert-guard 23:50 · weblog purge 03:00 · nightly cleanup 04:30.

### Switch on the pull update for an instance
```fish
# 1. In the release manager: instance form, tab Update, "New update token" (shown once). Copy it.
# 2. On the server, as root: add two lines to the central .env with an editor
mcedit /root/.config/myodoo-docker/.env
#      RM_PULL_URL=https://releasemanager.example.com
#      RM_PULL_TOKEN_WEB1=<token>      # container_name upper-cased, every other character "_"
# 3. Fetch the scripts, then install the cron template (ups alone only delivers it)
ups
docron --no-input              # note which jobs are switched off
/root/setup-maintenance-cron.sh
docron                         # the template restores the repository schedule: switch those jobs off again
# 4. Check: lists the configured instances, contacts nobody
~/ownerp_pull_update.py --check
# 5. In the release manager: enable the pull update for the instance.
```
Optional in the same `.env`: `RM_PULL_MODULE_HOST` (host the zip files may come from, default the
release manager's host), `RM_PULL_IMAGE_PREFIX` (default `myodoo/`). The log is
`/var/log/ownerp-pull-update.log`.

### Set up a customer user without root (restricted mode, getScripts ≥ 9.27.0)
```bash
python3 ~/getScripts.py --restricted   # as the ordinary user; no sudo anywhere
```
Missing packages → prints `apt-get update` / `apt-get upgrade` / `apt-get install fish git` (+ optional
`starship zoxide fastfetch`) for the admin and exits 1; installs nothing itself. Then copies Fish/Starship/
fastfetch config into the user's home and offers `chsh`. `ups` for that user runs without sudo.
Second tier (≥ 9.28.0): if `docker info` works for the user (member of `docker`), it also copies
`update_docker_odoo.py`, `container2backup.py`, `ownerp_validate/wizard/state/migrate.py`, `docker_table.py`
to `$HOME` → `doup`, `dobk`, `edup`, `edbk`, `dostat`, `doval`, `wiz`, `dps` work; names missing
`mc python3-yaml python3-dotenv 7zip zstd gnupg` and an unwritable `/opt/backups`. Never recommend
`usermod -aG docker` without saying the group is root-equivalent. `docron`, nginx, hardening, build
cache stay root-only.

### Configure a server behind an HTTP proxy
```bash
python3 ~/getScripts.py --proxy-check   # writes fish conf.d, /etc/environment, marker, docker daemon drop-in;
                                        # no_proxy gets the same intranet defaults as doup (≥ 9.22.0)
systemctl restart docker                # maintenance window — restarts ALL containers
```
Pin the proxy in `docker2update.yaml` (`defaults.proxy`): it drives `wget`, `docker build` AND
the container itself (`docker run -e`, update_docker_odoo ≥ 5.19.0 with bin/boot ≥ 2.4.0/2.7.0) —
without it the running Odoo has no proxy and cannot register the database. The intranet bypasses
the proxy by itself (≥ 5.20.0, `bypass_intranet` default true): `no_proxy` is extended at run time
with loopback, `.local`, 10/8, 172.16/12, 192.168/16, the host's own IPv4s and the DNS search
domains (host resolv.conf + `--dns-search` in `volume`). Hand-list only short hostnames and zones
outside the search list — a domain suffix never matches an IP, and only `requests` understands
CIDR (wget/apt/urllib do not). Full walkthrough: `docs/usage/07-proxy.md`.

## Guardrails & gotchas

- **Pull update: jobs carry data, never commands.** `ownerp_pull_update.py` checks every job against this
  server (database name = the container's `database_name`, same Odoo major version, image under
  `RM_PULL_IMAGE_PREFIX`, every download a plain `*.zip` under one https base address). A job that fails is
  reported with exit code 2 and never run. A lock prevents parallel runs; the token is shown once in the
  release manager. `--release-file` needs exactly one `-s` (else exit 1) and the file is validated before
  anything is touched. Without `RM_PULL_URL` or a token the agent is silent by design.
- **pgvector is a decision, not a default.** Odoo 19 Enterprise's `ai_auto_install` installs the AI
  module `ai` in every new database whenever the server offers the `vector` extension. Never swap
  a customer's DB image for `pgvector/pgvector` "to be safe"; deploy with `pg-local-deploy.sh`
  (`y` at pgvector) or Ansible `pg_vector=true` only when the customer wants AI or a restored DB
  already uses `vector`. Ansible update/rollback inherit it from the running server.
- **Destructive:** `doup` (type `F`) **stops, removes and re-creates** the target container and
  removes its image before rebuilding — a failed run leaves the system down until re-run.
  Fish aliases `dkprfa`/`dkrmv` wipe
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
- **Hollow Docker images are an on-access virus scanner, not a Docker defect.** A scanner (e.g.
  Sophos's `soapd`) watching `/var/lib/docker` holds a BuildKit mount open past its unmount and
  leaks it; the next build step reuses a snapshot still in use — `exec /app/bin/boot: no such file
  or directory` at start, or `stat /bin/sh: no such file or directory` mid-build. Fix at the
  source: exclude `/var/lib/docker/` (trailing slash) in the scanner policy; `server-readiness.py`
  checks it (`av_docker_exclusion`). `systemctl restart docker` only releases mounts already
  leaked; `doup` already retries once with an emptied builder cache.
- **The shipped `odoo.conf` is sized for one instance per host:** `workers = 3` +
  `max_cron_threads = 2` = 5 processes at 2 GB `limit_memory_soft` each. Live + test on 4 CPU / 16 GB
  exceeds Odoo's `2 x cores + 1` and 80 % of RAM; `server-readiness.py` warns (`odoo_capacity`,
  running containers only). Lower those keys in the instance's `odoo.conf` (volume `/opt/odoo/etc`).
- **overlay2 is pinned by `bootstrap.sh` for SPEED, not safety:** the containerd store is slower
  (2.6x cold build) and its build cache does not survive `doup`'s prune. A non-overlay2 driver is a
  readiness **WARN**. After a storage-driver switch reboot the server — that is about the switch,
  unrelated to the scanner.
- **nginx pid trap:** `nginx -t` can truncate `/run/nginx.pid`; the stock nginx.org unit then fails
  `reload` (kill usage text) while the old config stays live. Use the `$MAINPID` ExecReload drop-in.
- **`pg_isready` always needs `-d`:** without it libpq falls back to the database named after the
  connecting user, and every check logs `FATAL: database "<user>" does not exist` while still
  reporting success (`PQping` counts a FATAL reply as "server accepts connections"). Use
  `-d postgres` — it exists after every initdb, whereas the configured DB does not on a re-deploy
  over existing PGDATA. Containers deployed by `pg-local-deploy.sh` < 1.2.2 carry the old check;
  a healthcheck is frozen in at creation time, so fixing it means **recreating** the container
  (`docker compose -f <deploy-dir>/docker-compose.yml up -d`) — `docker container update` cannot.
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
- **Cloud images lock root.** `disable_root: true` in `/etc/cloud/cloud.cfg` plus a locked
  password (`passwd -S root` reports `L`) is deliberate on most cloud images, and conflicts with
  a `hardening_config.yaml` that expects `PermitRootLogin yes` — `root_login_locked` WARNs, never
  fixes it automatically (it needs a password). Fix: `passwd root` and a drop-in
  `/etc/cloud/cloud.cfg.d/99-ownerp-root.cfg` with `disable_root: false`.
- **Changing the SSH port is a transition** (getScripts 9.35.0 / server_hardening 1.12.0). When
  `SSH_PORT` in `.env` differs from the port sshd listens on, the hardening question names the
  change and `j` runs `server_hardening.py --ssh-transition begin`: sshd listens on old AND new
  port, UFW admits both for the admin IPs, fail2ban watches both. The old port closes on a later
  `ups` (or `--ssh-transition finish`) only after an established session on the new port from an
  admin IP exists. What no script can see: a provider firewall/security group in front must have
  the new port open first. `begin` refuses on a `Port` line in `sshd_config.d/`, a busy new port,
  a foreign live SSH session, no admin IPs, or a marker that contradicts `SSH_PORT`.
- **Proxy hosts:** the Docker daemon drop-in written by `--proxy-check` (getScripts ≥ 9.8.0) only
  takes effect after `systemctl restart docker` — maintenance window, restarts all containers.
  fastfetch's `publicip` module ignores `http_proxy` and is stripped automatically on proxy hosts;
  ~1 s fastfetch runtime is normal (NetIO/DiskIO sampling). Corporate firewalls often drop
  outbound traffic silently — "hangs" usually means missing proxy env, not a slow server.
  "Fehler bei der Kommunikation mit dem Wartungsserver" on database registration = the Odoo
  process has no proxy: check `docker inspect <c> --format '{{.Config.Env}}'` for `http_proxy`;
  an image built before boot 2.4.0/2.7.0 drops it at `su - odoo` even when docker run sets it.
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
