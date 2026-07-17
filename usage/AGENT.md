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
- **Framework:** Python argparse + bash (no Click) · **Human docs:** `docs/INSTALLATION_GUIDE.md` (DE/EN)

## Capabilities at a glance
- Initialize a fresh Debian/Ubuntu server: Docker CE (overlay2 pinned), nginx, certbot, UFW, fail2ban, auto-updates
- Install the operator shell environment (fish, aliases, management scripts) idempotently
- Audit and apply server hardening (UFW, fail2ban, SSH, sysctl, auditd, AIDE) with per-module control
- Deploy nginx base files + generate reverse-proxy vhosts for Odoo/other services via wizard + `nginx-set-conf`
- Deploy PostgreSQL and FastReport containers interactively (profiles, optional self-signed SSL)
- Update Odoo containers unattended from YAML (image rebuild, module update, restart)
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
| `getScripts.py` | `ups` (re-run) | Deploy fish config, aliases, management scripts to `/root` | `--clear-cache` · `--no-cache` · `--debug` · `--dns-check` · `--proxy-check` · `--first-run` · `--reconfigure` |
| `server_hardening.py` | — | Audit (default) / apply server hardening | `-c/--config CONFIG` · `-a/--apply` · `-f/--force` · `-m/--module {ufw,fail2ban,ssh,sysctl,sysctl_persist,kernel_modules,docker,auto_updates,auditd,aide,nginx,ports}…` |
| `deploy-nginx-base.sh` | — | Roll out shared nginx includes + maintenance page + nginx.conf (backup/validate/rollback) | `--no-main-conf` · `--dry-run` · `--src DIR` · `--dest DIR` · `--help` |
| `ngx-conf-wizard.sh` | — | Interactive builder for the `nginx-set-conf` YAML (`$HOME/docker-builds/ngx-conf/`) | interactive only (template, domain, cert, ports, "one more?" loop, optional deploy) |
| `nginx-set-conf` | `ngxset` | Generate + deploy vhosts from the wizard YAML (PyPI tool) | `--config_path=$HOME/docker-builds/ngx-conf/` (alias preset) |
| `pg-local-deploy.sh` | — | Deploy a PostgreSQL container (compose file, network, profile, optional SSL) | interactive only (container name, base dir, db user/name, password, PG version, profile `2cpu4gb|2cpu8gb|4cpu16gb|8cpu32gb`, optional host port, optional self-signed SSL) |
| `fr-local-deploy.sh` | — | Deploy the FastReport API container (`/opt/fast-report/<name>/…`) | interactive only (container name, port, image tag, registry token, optional secrets) |
| `update_docker_odoo.py` | `doup` (config: `edup`) | Update Odoo containers from `~/docker2update.yaml` (rebuild image, update DB, restart) | `-c/--config CONFIG` · `-v/--verbose` · `-s/--specific-container NAME` · `--validate` · `--dns-optimize` |
| `container2backup.py` | `dobk` (config: `edbk`) | Back up Odoo DBs (SQL + filestore) + service dirs per `~/container2backup.yaml` | `--sql-only` |
| `restore-zip.sh` | — | Restore a backup archive (auto-detects `.zip/.7z/.7z.gpg/.tar.gz/.tar.zst`) | positional: `backup_kind(1\|2)` `runsql(v10…v16)` `orig_dbname` `new_dbname` `drop_db(Y/n)` `zip_file` `odoo_volume` `pg_container` `pg_password` |
| `ssl-renew.sh` | — | `certbot renew`; nginx bounced only when a cert is actually due | no flags (daily cron) |
| `nginx-cert-guard.py` | — | Keep nginx up when one vhost breaks; DNS-drift early warning | mode (required): `--reconcile` \| `--check` \| `--list` \| `--restore DOMAIN` · `--start` (with --reconcile) · `--apply` (with --check) · `--dry-run` · `--nginx-conf-dir DIR` · `--state-file FILE` |
| `cleanup-weblogs.py` | — | Rotate nginx logs, GDPR purge > 7 days | `--clear-cache` (also wipe proxy/FastCGI caches — off by default) |
| `nightly-cleanup.sh` | — | Restart containers over memory threshold (Odoo→PG order) | env: `MEMORY_THRESHOLD=90` · `DRY_RUN=1` |
| `setup-maintenance-cron.sh` | — | Install `/etc/cron.d/myodoo-maintenance` + logrotate (idempotent) | `--remove` · env: `SCRIPT_DIR=/root` |
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
Full step-by-step walkthrough: `docs/INSTALLATION_GUIDE.md`.

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
independent of the shell environment. Full walkthrough: INSTALLATION_GUIDE chapter 18.

## Guardrails & gotchas
- **Destructive:** `doup` (type `F`) **stops, removes and re-creates** the target container and
  removes its image before rebuilding — a failed run leaves the system down until re-run.
  `restore-zip.sh` with `drop_db=Y` drops the target DB. Fish aliases `dkprfa`/`dkrmv` wipe
  Docker volumes (data loss) — never use them for cleanup.
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
- **Custom modules:** every `*custom_modules.zip` in the build folder is extracted into the image
  (build_odoo ≥ 2.4.0; the generic `custom_modules.zip` first, customer-specific archives
  override). Stage archives via `pre_build_files` in `docker2update.yaml`.

## Machine-readable outputs
- None of the tools emit JSON. Use exit codes: `update_docker_odoo.py --validate` (0 = config OK),
  `nginx -t`, `deploy-nginx-base.sh` (non-zero on failed reload). Logs land in
  `/var/log/{container2backup,ssl-renew,cleanup-weblogs,nightly-cleanup,nginx-cert-guard}.log`.

## Deeper docs
- `docs/INSTALLATION_GUIDE.md` — full fresh-server → Odoo live/test walkthrough (DE/EN, troubleshooting matrix)
- `scripts/README_BackUp.md` — backup formats, encryption, per-format restore
- `scripts/README_pg-local-deploy.md` — PostgreSQL deploy details, conf profiles, SSL
- `scripts/NIGHTLY_CLEANUP.md` — memory-threshold restart logic
- `docs/MANUAL_DOCKER_UPDATE_GUIDE.md` — manual container update fallback
- `fish/README.md` — complete alias/function reference
