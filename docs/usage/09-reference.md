# Skript- und Shell-Referenz / Script and Shell Reference

Teil der [Server-Installationsanleitung](../INSTALLATION_GUIDE.md) · Part of the [server installation guide](../INSTALLATION_GUIDE.md)

[🇩🇪 Deutsch](#deutsch) | [🇬🇧 English](#english)

---

<a id="deutsch"></a>
# Skript- und Shell-Referenz

<a id="de-14-skript-referenz"></a>
## Skript-Referenz

Alle Skripte des Repos (`scripts/`, Stand 16.07.2026):

| Skript | Zweck | Aufruf |
|---|---|---|
| `bootstrap.sh` (1.7.0) | Grundausstattung frischer Server (Docker, nginx, certbot, UFW, fail2ban) | `curl … bootstrap.sh -o /opt/… && /opt/myodoo-bootstrap.sh` |
| `getScripts.py` (9.7.3) | fish-Shell, Aliase, Verwaltungsskripte nach `/root` | `./getScripts.py [--dns-check\|--proxy-check\|--reconfigure]` |
| `server_hardening.py` (1.8.0) | Audit + Härtung (UFW, fail2ban, SSH, sysctl, auditd, AIDE) | `sudo python3 server_hardening.py [--apply] [-m MODUL …]` |
| `deploy-nginx-base.sh` (1.3.0) | nginx-Basis: Includes, Wartungsseite, nginx.conf (mit Rollback) | `./deploy-nginx-base.sh [--dry-run] [--no-main-conf]` |
| `ngx-conf-wizard.sh` (1.1.0) | Interaktiver YAML-Assistent für nginx-set-conf | `./ngx-conf-wizard.sh` |
| `pg-local-deploy.sh` (1.2.2) | PostgreSQL-Container interaktiv deployen (Profile, optional SSL) | `./pg-local-deploy.sh` |
| `fr-local-deploy.sh` | FastReport-API-Container deployen (Default `/opt/fast-report`) | `./fr-local-deploy.sh` |
| `update_docker_odoo.py` (5.12.0) | Odoo-Container-Updates per YAML | `doup` bzw. `python3 update_docker_odoo.py [-s NAME] [--validate]` |
| `ownerp_tui.py` (1.1.0) | Curses-Auswahlmaske für Odoo-Container-Updates, übergibt an `update_docker_odoo.py` | `tui` bzw. `python3 ownerp_tui.py [-c DATEI]` |
| `odoo_build_cache.py` (1.5.0) | Release-Archiv-Cache aller Instanzen; pflegt zusätzlich Dockerfile und `odoo.conf` des Build-Ordners | von `doup` aufgerufen; `~/odoo_build_cache.py stats\|gc [--days 30]` |
| `container2backup.py` (4.8.0) | SQL+Filestore-Backups, Kompression/Verschlüsselung/Streaming | `dobk` bzw. `~/container2backup.py [--sql-only\|--validate]` |
| `ownerp_validate.py` (1.0.0) | Rein lesende Schema-Prüfung von `docker2update.yaml`/`container2backup.yaml` | `doval` bzw. `~/ownerp_validate.py [--update PATH\|--backup PATH]` |
| `ownerp_wizard.py` (1.0.0) | Geführtes Aufnehmen einer Instanz bzw. Ändern eines Feldes in `docker2update.yaml`; prüft, bevor er ersetzt, und entfernt nie einen Eintrag | `wiz` bzw. `~/ownerp_wizard.py [--update PATH]` |
| `restore-zip.sh` (2.1.0) | Backup-Restore (DB + Filestore) in Docker | siehe [Kapitel 13](05-backup-restore.md#de-13-restore--notfall) |
| `ssl-renew.sh` (1.3.0) | certbot-Renewal, nginx nur bei Bedarf angehalten | `./ssl-renew.sh` (Cron) |
| `nginx-cert-guard.py` (1.1.0) | Defekte Vhosts quarantänisieren statt nginx zu blockieren | `--reconcile [--start]`, `--check [--apply]`, `--list`, `--restore DOMAIN` |
| `setup-maintenance-cron.sh` (1.3.0) | Wartungs-Cron + logrotate installieren | `./setup-maintenance-cron.sh [--remove]` |
| `server-readiness.py` (1.3.0) | Konfigurations-Drift prüfen (rein lesend) | `chk` bzw. `~/server-readiness.py [--brief\|--quiet]` |
| `nightly-cleanup.sh` (1.1.0) | Container-Neustart bei Speicherdruck | Cron; `MEMORY_THRESHOLD=90 DRY_RUN=1 ./nightly-cleanup.sh` |
| `cleanup-weblogs.py` (2.0.0) | nginx-Log-Rotation, DSGVO-Löschung nach 7 Tagen | Cron; `python3 cleanup-weblogs.py` |
| `dist-upgrade-debian.sh` (1.0.0) | Geführtes Debian-Major-Upgrade (z.B. bookworm→trixie) | `./dist-upgrade-debian.sh [CODENAME] [--yes]` |
| `check_docker_volumes.sh` (1.0.0) | Volumes und referenzierende Container auflisten | `dkvol` |

<a id="de-15-shell-referenz-fish"></a>
## Shell-Referenz (fish)

Vollständige Referenz mit Definitionen: [fish/README.md](../../fish/README.md).
Die wichtigsten Aliase/Funktionen nach Kategorie:

**Backup & Update** (`33-aliases-backup.fish`)

| Alias | Befehl / Zweck |
|---|---|
| `dobk` | `$HOME/container2backup.py` — Backup ausführen |
| `edbk` | `mcedit $HOME/container2backup.yaml` — Backup-Config |
| `llbk` / `cdbk` | Backup-Verzeichnis listen / betreten (`/opt/backups/docker`) |
| `doup` | `$HOME/update_docker_odoo.py` — Container-Update |
| `edup` | `mcedit $HOME/docker2update.yaml` — Update-Config |

**nginx** (`34-aliases-nginx.fish`)

| Alias | Befehl / Zweck |
|---|---|
| `ngxset` | `nginx-set-conf --config_path=$HOME/docker-builds/ngx-conf/` — Vhosts deployen |
| `ngx+` / `ngx-` / `ngx#` / `ngxr` | nginx start / stop / restart / reload |
| `ngx!` / `ngxs` | `nginx -t` / Service-Status |
| `cdngx` | `cd /etc/nginx/conf.d/` |
| `showcerts` | `certbot certificates` |

**Docker** (`32-aliases-docker.fish`)

| Alias | Befehl / Zweck |
|---|---|
| `dps` / `dpsall` | Container-Übersicht (formatiert, sortiert) |
| `dpi` | `docker images` |
| `dkvol` | Volumes + referenzierende Container |
| `dkstop` | Alle Container stoppen |
| `exec-live` / `exec-test` | Shell im live-/test-Container |
| `dco` / `dcup` / `dcdown` / `dclogs` / `dcps` | docker-compose-Kurzformen |
| `ct` | `ctop` — Container-Monitor |
| ⚠️ `dkprs` / `dkprv` / `dkprf` / `dkprfa` | `docker system/volume prune`-Varianten — **`dkprfa` löscht auch Volumes!** |

**System** (`30-aliases-system*.fish`)

| Alias | Befehl / Zweck |
|---|---|
| `ll` / `hg` / `mce` / `lg` | `ls -alh` / History-Grep / mcedit / lazygit |
| `rm` / `chmod` / `chown` | Safety-Wrapper (`rm -I`, `-c` verbose) |
| `cleandlog` | Docker-JSON-Logs leeren |
| `dusort` | Plattenbelegung sortiert |
| `f2b` | fail2ban-Status |
| `prepatch` | Update-Screen-Session öffnen (`screen -S sysupdate`) |

**Funktionen** (`fish/functions/linux/`)

| Funktion | Zweck |
|---|---|
| `syspatch` | Komplettes Systemupdate: journalctl-Vacuum → apt dist-upgrade → AIDE-Baseline → `docker image prune -f` |
| `ups` | ownERP-Skripte aktualisieren (getScripts.py neu ausführen) |
| `chk` | Readiness-Report: ist der Server auf Stand, was fehlt noch? (rein lesend) |
| `dkrm` / `dkrmi` / `dkrmv` | Alle Container/Images/Volumes löschen — mit Sicherheitsabfrage, `dkrmv` verlangt wörtlich `DELETE` |

**Odoo** (`35-aliases-odoo.fish`): `odoo-shell`, `odoo-logs`, `odoo-restart`,
`pg-shell` — Platzhalter-Container-Namen, pro Server anpassen.

---

<a id="english"></a>
# Script and Shell Reference

<a id="en-14-script-reference"></a>
## Script Reference

All scripts in this repository (`scripts/`, as of 16.07.2026):

| Script | Purpose | Invocation |
|---|---|---|
| `bootstrap.sh` (1.7.0) | Baseline for fresh servers (Docker, nginx, certbot, UFW, fail2ban) | `curl … bootstrap.sh -o /opt/… && /opt/myodoo-bootstrap.sh` |
| `getScripts.py` (9.7.3) | fish shell, aliases, management scripts into `/root` | `./getScripts.py [--dns-check\|--proxy-check\|--reconfigure]` |
| `server_hardening.py` (1.8.0) | Audit + hardening (UFW, fail2ban, SSH, sysctl, auditd, AIDE) | `sudo python3 server_hardening.py [--apply] [-m MODULE …]` |
| `deploy-nginx-base.sh` (1.3.0) | nginx base: includes, maintenance page, nginx.conf (with rollback) | `./deploy-nginx-base.sh [--dry-run] [--no-main-conf]` |
| `ngx-conf-wizard.sh` (1.1.0) | Interactive YAML wizard for nginx-set-conf | `./ngx-conf-wizard.sh` |
| `pg-local-deploy.sh` (1.2.2) | Deploy a PostgreSQL container interactively (profiles, optional SSL) | `./pg-local-deploy.sh` |
| `fr-local-deploy.sh` | Deploy the FastReport API container (default `/opt/fast-report`) | `./fr-local-deploy.sh` |
| `update_docker_odoo.py` (5.12.0) | Odoo container updates via YAML | `doup` or `python3 update_docker_odoo.py [-s NAME] [--validate]` |
| `ownerp_tui.py` (1.1.0) | Curses selection screen for Odoo container updates, hands off to `update_docker_odoo.py` | `tui` or `python3 ownerp_tui.py [-c FILE]` |
| `odoo_build_cache.py` (1.5.0) | Release archive cache shared by all instances; also maintains the build folder's Dockerfile and `odoo.conf` | called by `doup`; `~/odoo_build_cache.py stats\|gc [--days 30]` |
| `container2backup.py` (4.8.0) | SQL+filestore backups, compression/encryption/streaming | `dobk` or `~/container2backup.py [--sql-only\|--validate]` |
| `ownerp_validate.py` (1.0.0) | Read-only schema validation of `docker2update.yaml`/`container2backup.yaml` | `doval` or `~/ownerp_validate.py [--update PATH\|--backup PATH]` |
| `ownerp_wizard.py` (1.0.0) | Guided adding of an instance / changing a field in `docker2update.yaml`; validates before it replaces, and never removes an entry | `wiz` or `~/ownerp_wizard.py [--update PATH]` |
| `restore-zip.sh` (2.1.0) | Backup restore (DB + filestore) into Docker | see [chapter 13](05-backup-restore.md#en-13-restore--emergency) |
| `ssl-renew.sh` (1.3.0) | certbot renewal, nginx stopped only when needed | `./ssl-renew.sh` (cron) |
| `nginx-cert-guard.py` (1.1.0) | Quarantine broken vhosts instead of blocking nginx | `--reconcile [--start]`, `--check [--apply]`, `--list`, `--restore DOMAIN` |
| `setup-maintenance-cron.sh` (1.3.0) | Install maintenance cron + logrotate | `./setup-maintenance-cron.sh [--remove]` |
| `server-readiness.py` (1.3.0) | Check configuration drift (read-only) | `chk` or `~/server-readiness.py [--brief\|--quiet]` |
| `nightly-cleanup.sh` (1.1.0) | Container restart under memory pressure | cron; `MEMORY_THRESHOLD=90 DRY_RUN=1 ./nightly-cleanup.sh` |
| `cleanup-weblogs.py` (2.0.0) | nginx log rotation, GDPR purge after 7 days | cron; `python3 cleanup-weblogs.py` |
| `dist-upgrade-debian.sh` (1.0.0) | Guided Debian major upgrade (e.g. bookworm→trixie) | `./dist-upgrade-debian.sh [CODENAME] [--yes]` |
| `check_docker_volumes.sh` (1.0.0) | List volumes and referencing containers | `dkvol` |

<a id="en-15-shell-reference-fish"></a>
## Shell Reference (fish)

Complete reference with definitions: [fish/README.md](../../fish/README.md).
The most important aliases/functions by category:

**Backup & update** (`33-aliases-backup.fish`)

| Alias | Command / purpose |
|---|---|
| `dobk` | `$HOME/container2backup.py` — run a backup |
| `edbk` | `mcedit $HOME/container2backup.yaml` — backup config |
| `llbk` / `cdbk` | List / enter the backup directory (`/opt/backups/docker`) |
| `doup` | `$HOME/update_docker_odoo.py` — container update |
| `edup` | `mcedit $HOME/docker2update.yaml` — update config |

**nginx** (`34-aliases-nginx.fish`)

| Alias | Command / purpose |
|---|---|
| `ngxset` | `nginx-set-conf --config_path=$HOME/docker-builds/ngx-conf/` — deploy vhosts |
| `ngx+` / `ngx-` / `ngx#` / `ngxr` | nginx start / stop / restart / reload |
| `ngx!` / `ngxs` | `nginx -t` / service status |
| `cdngx` | `cd /etc/nginx/conf.d/` |
| `showcerts` | `certbot certificates` |

**Docker** (`32-aliases-docker.fish`)

| Alias | Command / purpose |
|---|---|
| `dps` / `dpsall` | Container overview (formatted, sorted) |
| `dpi` | `docker images` |
| `dkvol` | Volumes + referencing containers |
| `dkstop` | Stop all containers |
| `exec-live` / `exec-test` | Shell into the live/test container |
| `dco` / `dcup` / `dcdown` / `dclogs` / `dcps` | docker compose shortcuts |
| `ct` | `ctop` — container monitor |
| ⚠️ `dkprs` / `dkprv` / `dkprf` / `dkprfa` | `docker system/volume prune` variants — **`dkprfa` also wipes volumes!** |

**System** (`30-aliases-system*.fish`)

| Alias | Command / purpose |
|---|---|
| `ll` / `hg` / `mce` / `lg` | `ls -alh` / history grep / mcedit / lazygit |
| `rm` / `chmod` / `chown` | Safety wrappers (`rm -I`, `-c` verbose) |
| `cleandlog` | Truncate Docker JSON logs |
| `dusort` | Disk usage, sorted |
| `f2b` | fail2ban status |
| `prepatch` | Open an update screen session (`screen -S sysupdate`) |

**Functions** (`fish/functions/linux/`)

| Function | Purpose |
|---|---|
| `syspatch` | Full system update: journalctl vacuum → apt dist-upgrade → AIDE baseline → `docker image prune -f` |
| `ups` | Update the ownERP scripts (re-run getScripts.py) |
| `chk` | Readiness report: is the server up to date, what is missing? (read-only) |
| `dkrm` / `dkrmi` / `dkrmv` | Delete all containers/images/volumes — confirmation-gated, `dkrmv` requires typing `DELETE` |

**Odoo** (`35-aliases-odoo.fish`): `odoo-shell`, `odoo-logs`, `odoo-restart`,
`pg-shell` — placeholder container names, adapt per server.
