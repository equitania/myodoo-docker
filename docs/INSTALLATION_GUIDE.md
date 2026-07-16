# Server Installation Guide — Odoo live/test under Docker

Version 1.0.0 — 16.07.2026

[🇩🇪 Deutsche Version](#deutsche-version) | [🇬🇧 English Version](#english-version)

---

<a id="deutsche-version"></a>
# Deutsche Version

Schritt-für-Schritt-Leitfaden für Systemadministratoren: von einem frisch
installierten Debian-/Ubuntu-Server bis zu zwei produktiv laufenden
Odoo-Systemen (live/test) hinter nginx mit Let's-Encrypt-SSL, automatischen
Updates (`doup`) und Backups (`dobk`). Alle Beispiele sind neutral gehalten —
ersetze Domains, IPs und Passwörter durch eure Werte.

**Verwendete Platzhalter:**

| Platzhalter | Bedeutung |
|---|---|
| `erp-live.example.com` / `erp-test.example.com` | Öffentliche Domains der beiden Systeme |
| `203.0.113.10` | Öffentliche IP (DNS-A-Record) |
| `192.168.1.50` | Interne Server-IP (nur bei NAT relevant) |
| `live-odoo` / `test-odoo`, `live-db` / `test-db` | Container-Namen |
| `odoo/live`, `odoo/test` | Docker-Image-Namen |

## Inhalt

1. [Überblick & Architektur](#de-1-überblick--architektur)
2. [Voraussetzungen](#de-2-voraussetzungen)
3. [Schritt 1: Bootstrap](#de-3-schritt-1-bootstrap)
4. [Schritt 2: getScripts.py](#de-4-schritt-2-getscriptspy)
5. [Schritt 3: Server-Härtung](#de-5-schritt-3-server-härtung)
6. [Schritt 4: nginx-Basis + Vhosts](#de-6-schritt-4-nginx-basis--vhosts)
7. [Schritt 5: PostgreSQL](#de-7-schritt-5-postgresql-live-dbtest-db)
8. [Schritt 6: Odoo-Container erststarten](#de-8-schritt-6-odoo-container-erststarten)
9. [Schritt 7: Let's Encrypt & Erreichbarkeit](#de-9-schritt-7-lets-encrypt--erreichbarkeit)
10. [Schritt 8: Updates einrichten (edup/doup)](#de-10-schritt-8-updates-einrichten-edupdoup)
11. [Schritt 9: Backups einrichten (edbk/dobk)](#de-11-schritt-9-backups-einrichten-edbkdobk)
12. [Schritt 10: Wartung automatisieren](#de-12-schritt-10-wartung-automatisieren)
13. [Restore & Notfall](#de-13-restore--notfall)
14. [Skript-Referenz](#de-14-skript-referenz)
15. [Shell-Referenz (fish)](#de-15-shell-referenz-fish)
16. [Troubleshooting](#de-16-troubleshooting)
17. [Optionale Komponenten](#de-17-optionale-komponenten)

<a id="de-1-überblick--architektur"></a>
## 1. Überblick & Architektur

Zielbild nach diesem Leitfaden:

```
Internet ──443/80──▶ nginx (Host, SSL-Terminierung, Security-Header)
                       │
        ┌──────────────┴───────────────┐
        ▼                              ▼
 erp-live.example.com          erp-test.example.com
 127.0.0.1:11000/12000         127.0.0.1:13000/14000
        │                              │
 ┌──────┴──────┐                ┌──────┴──────┐
 │  live-odoo  │                │  test-odoo  │   (Docker, --restart=always)
 │ 8069 / 8072 │                │ 8069 / 8072 │
 └──────┬──────┘                └──────┬──────┘
        │ live-db-net                  │ test-db-net
 ┌──────┴──────┐                ┌──────┴──────┐
 │   live-db   │                │   test-db   │   (PostgreSQL, Host-Bind-Mount)
 └─────────────┘                └─────────────┘
```

**Port-Konvention** (aus `docker2update.yaml`):

| System | Web (→ 8069) | Websocket/Longpolling (→ 8072) |
|---|---|---|
| live | `127.0.0.1:11000` | `127.0.0.1:12000` |
| test | `127.0.0.1:13000` | `127.0.0.1:14000` |

Alle Odoo-Ports sind bewusst an `127.0.0.1` gebunden — erreichbar nur über
nginx. Odoo ≥ 16 nutzt die Route `/websocket` (nicht mehr `/longpolling`);
die nginx-Templates von `nginx-set-conf` berücksichtigen das automatisch.

<a id="de-2-voraussetzungen"></a>
## 2. Voraussetzungen

- **OS:** Debian 12/13 oder Ubuntu 20.04–26.04, frisch installiert, Root-Zugang
- **DNS:** A-Records für `erp-live.example.com` / `erp-test.example.com` auf die öffentliche IP
- **Bei NAT** (Server steht hinter einer Firewall mit privater IP):
  - Firewall-Forwarding **TCP 443 und TCP 80** auf die interne Server-IP.
    Port 80 muss **dauerhaft** offen bleiben (Let's-Encrypt-Renewal!)
  - Interne Clients: siehe [Troubleshooting → Split-DNS](#de-16-troubleshooting)
- **Odoo-Image:** eigenes Registry-Image oder Build-Verzeichnis nach
  `Dockerfiles/v19-odoo/ReadMe.md` (Dockerfile, `build_odoo.py`, `release.file`,
  `odoo.conf`, `bin/boot`)

> ℹ️ **Die Server-Shell ist fish.** `getScripts.py` installiert fish als
> Standard-Shell. Für Copy-Paste-Blöcke gilt: `$status` statt `$?`,
> `set VAR wert` statt `VAR=wert`, keine Heredocs. Bash-Skripte laufen
> natürlich weiterhin per `./script.sh` oder `bash -c '…'`.

<a id="de-3-schritt-1-bootstrap"></a>
## 3. Schritt 1: Bootstrap

`bootstrap.sh` bringt einen frischen Server in einen definierten Grundzustand —
idempotent, gefahrlos wiederholbar.

```bash
# Als root auf dem frischen Server:
curl -fsSL https://raw.githubusercontent.com/equitania/myodoo-docker/2026/scripts/bootstrap.sh \
  -o /opt/myodoo-bootstrap.sh && chmod +x /opt/myodoo-bootstrap.sh && /opt/myodoo-bootstrap.sh
```

Installiert: Docker CE (offizielles Repo), nginx (nginx.org), certbot, UFW
(installiert, aber **bewusst deaktiviert** — siehe Härtung), fail2ban,
unattended-upgrades, Python-Abhängigkeiten; klont das Repo und ruft am Ende
`getScripts.py` auf. Einzelne Schritte lassen sich per ENV abschalten
(`INSTALL_NGINX=0`, `INSTALL_DOCKER=0`, `RUN_GETSCRIPTS=0`, …).

> ⚠️ **Erfahrungswert (Docker ≥ 29):** Neuinstallationen von Docker ≥ 29
> aktivieren standardmäßig den containerd Image Store, dessen Image-Export
> für große Builds kaputt ist ([moby/moby#52431](https://github.com/moby/moby/issues/52431)).
> `bootstrap.sh` ≥ 1.7.0 pinnt deshalb den klassischen `overlay2`-Treiber in
> `/etc/docker/daemon.json`. Auf Servern, die **ohne** aktuelles Bootstrap
> aufgesetzt wurden: Symptome und Heilung siehe [Troubleshooting](#de-16-troubleshooting).

<a id="de-4-schritt-2-getscriptspy"></a>
## 4. Schritt 2: getScripts.py

Installiert die fish-Shell-Konfiguration, alle Aliase/Funktionen und die
Verwaltungsskripte (inkl. `container2backup.py`, `update_docker_odoo.py`)
nach `/root`. Wird vom Bootstrap automatisch ausgeführt; manuell:

```bash
/root/getScripts.py                 # Installation / Update
/root/getScripts.py --dns-check     # DNS-Konfiguration pruefen/optimieren
/root/getScripts.py --proxy-check   # Docker-Daemon-Proxy einrichten (Proxy-Kunden)
/root/getScripts.py --reconfigure   # First-Run-Einstellungen erneut abfragen
```

Danach neue Shell öffnen (oder `source ~/.config/fish/config.fish`) — die
Aliase aus [Kapitel 15](#de-15-shell-referenz-fish) stehen bereit. Später
aktualisieren mit `ups`.

> ⚠️ **Erfahrungswert (sudo su):** Wer sich mit einem persönlichen
> Admin-Account anmeldet und per `sudo su` zu root wird, braucht
> getScripts.py ≥ 9.7.3 — ältere Versionen installierten in diesem Fall ins
> falsche Home-Verzeichnis (Aliase fehlten für root).

<a id="de-5-schritt-3-server-härtung"></a>
## 5. Schritt 3: Server-Härtung

1. Secrets-Datei pflegen (Vorlage: `scripts/.env.example`):

```bash
mcedit /root/.config/myodoo-docker/.env   # SSH_PORT, ALLOWED_IP_1..n, Alert-Mail
```

2. Erst **Audit** (ändert nichts), dann anwenden:

```bash
sudo python3 /root/server_hardening.py            # Audit / Dry-Run
sudo python3 /root/server_hardening.py --apply    # UFW, fail2ban, SSH, sysctl, auditd, AIDE, ...
```

UFW wird erst hier aktiviert — nach konfiguriertem SSH-Port und erlaubten
IPs, damit man sich nicht aussperrt. Einzelne Module gezielt:
`--apply --module ufw` bzw. `-m fail2ban ssh sysctl`. Konfiguration:
`scripts/hardening_config.yaml`.

<a id="de-6-schritt-4-nginx-basis--vhosts"></a>
## 6. Schritt 4: nginx-Basis + Vhosts

### 6.1 Basis-Dateien ausrollen

Jeder generierte Vhost referenziert gemeinsame Include-Dateien
(`nginxconfig.io/security.conf`, `general.conf`) und die Wartungsseite.
Ohne sie schlägt `nginx -t` fehl — deshalb **vor** dem ersten Vhost:

```bash
~/myodoo-docker/scripts/deploy-nginx-base.sh            # inkl. nginx.conf (Backup + Validierung + Rollback)
~/myodoo-docker/scripts/deploy-nginx-base.sh --dry-run  # nur anzeigen
```

> ⚠️ **Erfahrungswert (PID-File-Falle):** `nginx -t` kann `/run/nginx.pid`
> leer (neu) anlegen. Die Standard-Unit von nginx.org reloaded über
> `kill -s HUP $(cat /run/nginx.pid)` — mit leerer Datei schlägt der Reload
> fehl (kill-Usage-Text im Journal) und **die alte Config bleibt still aktiv**.
> `deploy-nginx-base.sh` ≥ 1.1.0 repariert die PID-Datei automatisch.
> Dauerhafte Absicherung per systemd-Drop-in:
>
> ```bash
> mkdir -p /etc/systemd/system/nginx.service.d
> printf '[Service]\nExecReload=\nExecReload=/bin/kill -s HUP $MAINPID\n' \
>   > /etc/systemd/system/nginx.service.d/10-reload-mainpid.conf
> systemctl daemon-reload
> ```

### 6.2 Vhost-Konfiguration erzeugen

Der interaktive Assistent baut die YAML-Datei für `nginx-set-conf` — Eintrag
für Eintrag („noch eine Domain?"-Schleife), mit Validierung und optionalem
Deploy am Ende:

```bash
~/myodoo-docker/scripts/ngx-conf-wizard.sh
```

Für die beiden Odoo-Systeme: Template `eq_odoo_ssl`, Domain, Zertifikatsname,
Port `11000` (live) bzw. `13000` (test), Pollport `12000` bzw. `14000`.
Die YAML landet in `$HOME/docker-builds/ngx-conf/`; deployen jederzeit mit:

```bash
ngxset        # = nginx-set-conf --config_path=$HOME/docker-builds/ngx-conf/
ngx!          # nginx -t
ngxs          # Status
```

> ⚠️ **Erfahrungswerte:**
> - **Die Bind-IP muss LOKAL sein.** Hinter NAT gehört die **interne** IP
>   (`192.168.1.50`) in die Config, nicht die öffentliche DNS-IP — sonst
>   `bind() failed (99: Cannot assign requested address)`. Der Wizard zeigt
>   die lokalen IPs an und warnt bei Fremd-IPs.
> - `nginx-set-conf` **reloaded** nur — ein gestoppter nginx wird nicht
>   gestartet. Nach dem ersten Deploy prüfen: `ngxs`, ggf. `ngx+`.

<a id="de-7-schritt-5-postgresql-live-dbtest-db"></a>
## 7. Schritt 5: PostgreSQL (live-db/test-db)

Pro System ein eigener PostgreSQL-Container — interaktiv per:

```bash
~/myodoo-docker/scripts/pg-local-deploy.sh   # Lauf 1: live-db
~/myodoo-docker/scripts/pg-local-deploy.sh   # Lauf 2: test-db
```

Abgefragt werden u.a. Container-Name (`live-db`), Basis-Verzeichnis,
DB-User/-Passwort, PostgreSQL-Version (aktuelle Tags:
<https://hub.docker.com/_/postgres/tags?name=16.>), Performance-Profil
(2cpu4gb … 8cpu32gb) und optional **Self-Signed-SSL**. Das Skript erzeugt
Netzwerk (`live-db-net`), Compose-File (`<basis>/live-db-deploy/docker-compose.yml`)
und startet den Container. Details: [scripts/README_pg-local-deploy.md](../scripts/README_pg-local-deploy.md).

> ⚠️ **Erfahrungswert (db_sslmode):** In der `odoo.conf` des Odoo-Images muss
> `db_sslmode = prefer` stehen. Mit `require` verweigert Odoo die Verbindung
> zu einem PostgreSQL ohne SSL („server does not support SSL, but SSL was
> required"). Vor dem ersten Start prüfen:
>
> ```fish
> docker run --rm --entrypoint grep odoo/live db_sslmode /opt/odoo/etc/odoo.conf
> # Erwartung: db_sslmode = prefer
> ```

<a id="de-8-schritt-6-odoo-container-erststarten"></a>
## 8. Schritt 6: Odoo-Container erststarten

### 8.1 Image bereitstellen

Entweder aus eurer Registry ziehen oder auf dem Server bauen. Beim Build
liegt pro System ein Build-Verzeichnis vor (z.B. `$HOME/docker-builds/live-odoo/`
mit Dockerfile, `build_odoo.py`, `release.file`, `odoo.conf`, `bin/boot` —
siehe `Dockerfiles/v19-odoo/ReadMe.md`):

```fish
cd $HOME/docker-builds/live-odoo
docker build -t odoo/live .
```

### 8.2 Container starten

```fish
# LIVE
docker run -d -p 127.0.0.1:11000:8069 -p 127.0.0.1:12000:8072 \
  --restart=always --network live-db-net \
  -v /opt/odoo/live:/opt/odoo/data --name="live-odoo" odoo/live:latest start

# TEST
docker run -d -p 127.0.0.1:13000:8069 -p 127.0.0.1:14000:8072 \
  --restart=always --network test-db-net \
  -v /opt/odoo/test:/opt/odoo/data --name="test-odoo" odoo/test:latest start
```

Das Boot-Skript im Container akzeptiert genau drei Kommandos:
`start` (Normalbetrieb), `update` (Modul-Update, genutzt von `doup`),
`neutralize` (DB neutralisieren, z.B. nach Restore auf test).

### 8.3 Verifizieren

```fish
dps                                                # beide Container "Up"?
curl -sI http://127.0.0.1:11000/web/health         # HTTP/1.1 200 OK
docker logs --tail 20 live-odoo                    # Fehler im Log?
```

Danach im Browser `https://erp-live.example.com` → Datenbank anlegen.
Die `odoo.conf` je Instanz zeigt per `db_host` auf den DB-Container
(`live-db` bzw. `test-db`) — die Namensauflösung übernimmt das Docker-Netz.

> ⚠️ **Erfahrungswerte:**
> - **Immer mit `127.0.0.1:`-Prefix mappen.** Ohne Prefix lauschen 11000/12000
>   auf allen Interfaces — jeder im LAN umgeht dann nginx, SSL und
>   Security-Header.
> - Schlägt der Start mit `exec /app/bin/boot: no such file or directory`
>   fehl, obwohl das Build-Verzeichnis korrekt ist → fast immer der
>   Docker-29-Store-Bug, siehe [Troubleshooting](#de-16-troubleshooting).

<a id="de-9-schritt-7-lets-encrypt--erreichbarkeit"></a>
## 9. Schritt 7: Let's Encrypt & Erreichbarkeit

Die Zertifikate erzeugt `nginx-set-conf`/certbot beim Vhost-Deploy
(HTTP-01 über Port 80). Die automatische Erneuerung übernimmt später der
Wartungs-Cron ([Kapitel 12](#de-12-schritt-10-wartung-automatisieren)) über
`ssl-renew.sh` — nginx wird nur angehalten, wenn tatsächlich ein Zertifikat
fällig ist. Sicherheitsnetz: `nginx-cert-guard.py` quarantänisiert einen
einzelnen defekten Vhost (Zertifikat/DNS), statt den ganzen Server zu blockieren.

```bash
showcerts                 # certbot certificates — Laufzeiten pruefen
/root/ssl-renew.sh        # manueller Renewal-Lauf
```

> ⚠️ **Erfahrungswerte (NAT):**
> - Das **Port-80-Forwarding muss dauerhaft** bestehen bleiben — ohne HTTP-01
>   kein Renewal, das Zertifikat läuft nach 90 Tagen ab.
> - **Interne Clients erreichen die Domain nicht, extern geht alles?**
>   Klassisches Split-DNS-Problem: intern wird die öffentliche IP aufgelöst,
>   das Gateway kann kein Hairpin-NAT. Lösung: auf dem internen DNS-Server
>   eine Pinpoint-Zone `erp-live.example.com` mit A-Record auf die interne
>   Server-IP (`192.168.1.50`) anlegen — **nicht** an der Firewall drehen.

<a id="de-10-schritt-8-updates-einrichten-edupdoup"></a>
## 10. Schritt 8: Updates einrichten (edup/doup)

`update_docker_odoo.py` aktualisiert die Odoo-Container automatisiert
(Image-Rebuild, Container-Neuanlage, Modul-Update) — gesteuert über
`~/docker2update.yaml`:

```bash
edup    # YAML bearbeiten (mcedit)
doup    # Update-Lauf starten
```

Beispiel-Eintrag pro Container (Vorlage: `scripts/docker2update.yaml`):

```yaml
containers:
  - active: true
    type: "F"                        # [M]odules | [F]ull | [N]eutralize
    delay_time: 10
    container_name: "live-odoo"
    database_name: "live_odoo"
    port: "127.0.0.1:11000"
    longpolling_port: "127.0.0.1:12000"
    dockerfile_path: "$HOME/docker-builds/live-odoo/"
    docker_image_name: "odoo/live"
    db_user: "ownerp"
    db_password: "***"
    db_host: "live-db"
    volume: "--network live-db-net -v /opt/odoo/live:/opt/odoo/data"
    odoo_version: "19"
    translate: "Y"
```

Nützliche Optionen: `doup --validate` (Config prüfen), `-s CONTAINER`
(einzelner Container), `-v` (verbose). **Proxy-Kunden:** `defaults.proxy` und
`pre_build_files` in der YAML, Daemon-Proxy via `getScripts.py --proxy-check`.

<a id="de-11-schritt-9-backups-einrichten-edbkdobk"></a>
## 11. Schritt 9: Backups einrichten (edbk/dobk)

`container2backup.py` sichert SQL-Dump + Filestore je Datenbank sowie
Service-Verzeichnisse (nginx, letsencrypt, docker-builds) — gesteuert über
`~/container2backup.yaml`:

```bash
edbk    # YAML bearbeiten
dobk    # Voll-Backup ausfuehren
dobk --sql-only
llbk    # Backup-Verzeichnis ansehen (/opt/backups/docker)
```

Beispiel (Vorlage: `scripts/container2backup.yaml`):

```yaml
defaults:
  retention_days: 14
  db_user: ownerp
  backup_path: /opt/backups
  compression: { format: "7z", level: 5 }
  stream: false          # true = Streaming .tar.zst (grosse Filestores!)

databases:
  - name: live_odoo
    sql_container: live-db
    data_container: live-odoo
  - name: test_odoo
    sql_container: test-db
    data_container: test-odoo
    only_sql_dump: true
```

> 💡 **Erfahrungswert:** Bei großen Filestores (≫ 50 GB) `stream: true`
> setzen — das Backup läuft ohne unkomprimierte Zwischenkopie direkt in ein
> `.tar.zst`. Kompressionslevel 3 genügt (Filestore-Medien sind bereits
> komprimiert). Details, Verschlüsselung (AES-256/GPG) und Restore je Format:
> [scripts/README_BackUp.md](../scripts/README_BackUp.md).

<a id="de-12-schritt-10-wartung-automatisieren"></a>
## 12. Schritt 10: Wartung automatisieren

Sobald `container2backup.yaml` steht, verdrahtet ein Aufruf alle
Wartungsjobs als `/etc/cron.d/myodoo-maintenance` (inkl. logrotate):

```bash
~/myodoo-docker/scripts/setup-maintenance-cron.sh
```

| Zeit | Job |
|---|---|
| 02:00 / 14:00 | `container2backup.py` — Backups |
| 23:50 | `nginx-cert-guard.py --check --apply` — DNS-Drift/Zertifikats-Wache |
| 00:00 | `ssl-renew.sh` — Let's-Encrypt-Renewal |
| 03:00 | `cleanup-weblogs.py` — DSGVO-Weblog-Rotation (7 Tage) |
| 04:30 | `nightly-cleanup.sh` — speicherbasierter Container-Neustart |

Entfernen mit `--remove`. Details zum Nightly-Cleanup:
[scripts/NIGHTLY_CLEANUP.md](../scripts/NIGHTLY_CLEANUP.md).

<a id="de-13-restore--notfall"></a>
## 13. Restore & Notfall

Backup zurückspielen (Archiv aus `container2backup.py`, erkennt
`.zip/.7z/.7z.gpg/.tar.gz/.tar.zst` automatisch):

```bash
env PGPASSWORD='<pg_password>' ~/myodoo-docker/scripts/restore-zip.sh \
  <backup_kind 1|2> <run_sql> <orig_dbname> <new_dbname> <drop_db Y/n> \
  <archiv> <odoo_volume> <pg_container>
```

Das Passwort per `PGPASSWORD`-Umgebungsvariable übergeben — als 9. Argument
wäre es in `ps aux` und der Shell-History sichtbar (das Skript warnt dann).

Typischer Anwendungsfall: Live-Backup als Test-DB einspielen, danach im
Container `neutralize` ausführen (Mails/Cron deaktivieren). Für manuelle
Container-Updates ohne `doup` (Fallback):
[docs/MANUAL_DOCKER_UPDATE_GUIDE.md](MANUAL_DOCKER_UPDATE_GUIDE.md).

<a id="de-14-skript-referenz"></a>
## 14. Skript-Referenz

Alle Skripte des Repos (`scripts/`, Stand 16.07.2026):

| Skript | Zweck | Aufruf |
|---|---|---|
| `bootstrap.sh` (1.7.0) | Grundausstattung frischer Server (Docker, nginx, certbot, UFW, fail2ban) | `curl … bootstrap.sh -o /opt/… && /opt/myodoo-bootstrap.sh` |
| `getScripts.py` (9.7.3) | fish-Shell, Aliase, Verwaltungsskripte nach `/root` | `./getScripts.py [--dns-check\|--proxy-check\|--reconfigure]` |
| `server_hardening.py` (1.8.0) | Audit + Härtung (UFW, fail2ban, SSH, sysctl, auditd, AIDE) | `sudo python3 server_hardening.py [--apply] [-m MODUL …]` |
| `deploy-nginx-base.sh` (1.1.0) | nginx-Basis: Includes, Wartungsseite, nginx.conf (mit Rollback) | `./deploy-nginx-base.sh [--dry-run] [--no-main-conf]` |
| `ngx-conf-wizard.sh` (1.1.0) | Interaktiver YAML-Assistent für nginx-set-conf | `./ngx-conf-wizard.sh` |
| `pg-local-deploy.sh` (1.2.1) | PostgreSQL-Container interaktiv deployen (Profile, optional SSL) | `./pg-local-deploy.sh` |
| `fr-local-deploy.sh` | FastReport-API-Container deployen (Default `/opt/fast-report`) | `./fr-local-deploy.sh` |
| `update_docker_odoo.py` (5.3.1) | Odoo-Container-Updates per YAML | `doup` bzw. `python3 update_docker_odoo.py [-s NAME] [--validate]` |
| `container2backup.py` (4.7.1) | SQL+Filestore-Backups, Kompression/Verschlüsselung/Streaming | `dobk` bzw. `~/container2backup.py [--sql-only]` |
| `restore-zip.sh` (2.1.0) | Backup-Restore (DB + Filestore) in Docker | siehe [Kapitel 13](#de-13-restore--notfall) |
| `ssl-renew.sh` (1.3.0) | certbot-Renewal, nginx nur bei Bedarf angehalten | `./ssl-renew.sh` (Cron) |
| `nginx-cert-guard.py` (1.1.0) | Defekte Vhosts quarantänisieren statt nginx zu blockieren | `--reconcile [--start]`, `--check [--apply]`, `--list`, `--restore DOMAIN` |
| `setup-maintenance-cron.sh` (1.2.0) | Wartungs-Cron + logrotate installieren | `./setup-maintenance-cron.sh [--remove]` |
| `nightly-cleanup.sh` (1.1.0) | Container-Neustart bei Speicherdruck | Cron; `MEMORY_THRESHOLD=90 DRY_RUN=1 ./nightly-cleanup.sh` |
| `cleanup-weblogs.py` (2.0.0) | nginx-Log-Rotation, DSGVO-Löschung nach 7 Tagen | Cron; `python3 cleanup-weblogs.py` |
| `dist-upgrade-debian.sh` (1.0.0) | Geführtes Debian-Major-Upgrade (z.B. bookworm→trixie) | `./dist-upgrade-debian.sh [CODENAME] [--yes]` |
| `check_docker_volumes.sh` (1.0.0) | Volumes und referenzierende Container auflisten | `dkvol` |

<a id="de-15-shell-referenz-fish"></a>
## 15. Shell-Referenz (fish)

Vollständige Referenz mit Definitionen: [fish/README.md](../fish/README.md).
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
| `dkrm` / `dkrmi` / `dkrmv` | Alle Container/Images/Volumes löschen — mit Sicherheitsabfrage, `dkrmv` verlangt wörtlich `DELETE` |

**Odoo** (`35-aliases-odoo.fish`): `odoo-shell`, `odoo-logs`, `odoo-restart`,
`pg-shell` — Platzhalter-Container-Namen, pro Server anpassen.

<a id="de-16-troubleshooting"></a>
## 16. Troubleshooting

| Symptom | Ursache | Lösung |
|---|---|---|
| `docker build` scheitert bei „exporting to image" mit `ref moby/1/… locked … unavailable` | Docker ≥ 29 mit containerd Image Store ([moby#52431](https://github.com/moby/moby/issues/52431)) | `/etc/docker/daemon.json`: `{"storage-driver": "overlay2"}` → `systemctl restart docker` → **Server rebooten** → Images neu ziehen, Container neu erzeugen (Volumes bleiben) |
| `exec /app/bin/boot: no such file or directory` beim Container-Start, Build lief „durch" | Hohles Image aus vergiftetem BuildKit-Cache (Folge des Store-Bugs). Gegenprobe: fehlt sogar `/bin/sh` im Image? | Nach dem Store-Wechsel: `docker builder prune -af`, dann `docker build --no-cache --pull` |
| Builds liefern **nichtdeterministisch** hohle Images; Kernel-Log: `overlayfs: lowerdir is in-use as upperdir/workdir of another mount` | Verwaiste Overlay-Mounts des alten Stores nach einem Store-Wechsel ohne Reboot — zwei Overlay-Welten teilen sich Verzeichnisse | **Server rebooten**, danach `docker builder prune -af` + `docker build --no-cache --pull` |
| nginx: `bind() to 203.0.113.10:443 failed (99: Cannot assign requested address)` | Öffentliche DNS-IP ist hinter NAT nicht lokal | In der Vhost-Config die **interne** IP verwenden; `ngx-conf-wizard.sh` zeigt die lokalen IPs an |
| `systemctl reload nginx` schlägt fehl, Journal zeigt kill-Usage-Text; alte Config bleibt aktiv | Leere `/run/nginx.pid` (durch `nginx -t` erzeugt), Standard-Unit vertraut der Datei | `$MAINPID`-Drop-in installieren ([Kapitel 6.1](#de-6-schritt-4-nginx-basis--vhosts)); tritt auch bei nginx-**Paket-Updates** auf (postinst) — danach `systemctl daemon-reload && systemctl restart nginx` |
| Odoo: „server does not support SSL, but SSL was required" beim DB-Anlegen | `db_sslmode = require` in der odoo.conf, PostgreSQL ohne SSL | `db_sslmode = prefer` setzen (oder PG-SSL aktivieren via `pg-local-deploy.sh`) |
| Domain extern erreichbar, intern nicht | Split-DNS: interne Clients bekommen die öffentliche IP, Gateway kann kein Hairpin-NAT | Pinpoint-Zone auf dem internen DNS: `erp-live.example.com` → interne Server-IP |
| Zertifikat läuft ab, Renewal schlägt fehl | Port-80-Forwarding wurde entfernt | TCP 80 → Server dauerhaft forwarden (HTTP-01) |
| `fish: $? is not the exit status …` | Bash-Syntax in der fish-Shell | `$status` statt `$?`; Bash-Blöcke via `bash -c '…'` |
| Odoo-Weboberfläche direkt über `IP:11000` aus dem LAN erreichbar | Port-Mapping ohne `127.0.0.1:`-Prefix | Container mit `-p 127.0.0.1:11000:8069 …` neu erzeugen |

<a id="de-17-optionale-komponenten"></a>
## 17. Optionale Komponenten

**FastReport-API** (PDF-Rendering für Odoo): interaktiv per
`~/myodoo-docker/scripts/fr-local-deploy.sh` — Standard-Basis
`/opt/fast-report`, ein Container je System (z.B. `fr-live`, `fr-test`),
Registry-Zugang erforderlich. Die Backup-Einbindung erfolgt über den
`fast_report:`-Block in `container2backup.yaml` ([Kapitel 11](#de-11-schritt-9-backups-einrichten-edbkdobk)).

**Debian-Major-Upgrade:** `dist-upgrade-debian.sh` führt geführt durch ein
In-Place-Upgrade (Quellen umschreiben, phasenweises Upgrade, Reboot-Abfrage).

---

<a id="english-version"></a>
# English Version

Step-by-step guide for system administrators: from a freshly installed
Debian/Ubuntu server to two production Odoo systems (live/test) behind nginx
with Let's Encrypt SSL, automated updates (`doup`) and backups (`dobk`).
All examples are vendor/customer-neutral — replace domains, IPs and passwords
with your values.

**Placeholders used:**

| Placeholder | Meaning |
|---|---|
| `erp-live.example.com` / `erp-test.example.com` | Public domains of the two systems |
| `203.0.113.10` | Public IP (DNS A record) |
| `192.168.1.50` | Internal server IP (only relevant behind NAT) |
| `live-odoo` / `test-odoo`, `live-db` / `test-db` | Container names |
| `odoo/live`, `odoo/test` | Docker image names |

## Contents

1. [Overview & Architecture](#en-1-overview--architecture)
2. [Prerequisites](#en-2-prerequisites)
3. [Step 1: Bootstrap](#en-3-step-1-bootstrap)
4. [Step 2: getScripts.py](#en-4-step-2-getscriptspy)
5. [Step 3: Server Hardening](#en-5-step-3-server-hardening)
6. [Step 4: nginx Base + Vhosts](#en-6-step-4-nginx-base--vhosts)
7. [Step 5: PostgreSQL](#en-7-step-5-postgresql-live-dbtest-db)
8. [Step 6: First Start of the Odoo Containers](#en-8-step-6-first-start-of-the-odoo-containers)
9. [Step 7: Let's Encrypt & Reachability](#en-9-step-7-lets-encrypt--reachability)
10. [Step 8: Set Up Updates (edup/doup)](#en-10-step-8-set-up-updates-edupdoup)
11. [Step 9: Set Up Backups (edbk/dobk)](#en-11-step-9-set-up-backups-edbkdobk)
12. [Step 10: Automate Maintenance](#en-12-step-10-automate-maintenance)
13. [Restore & Emergency](#en-13-restore--emergency)
14. [Script Reference](#en-14-script-reference)
15. [Shell Reference (fish)](#en-15-shell-reference-fish)
16. [Troubleshooting](#en-16-troubleshooting)
17. [Optional Components](#en-17-optional-components)

<a id="en-1-overview--architecture"></a>
## 1. Overview & Architecture

Target picture after completing this guide:

```
Internet ──443/80──▶ nginx (host, SSL termination, security headers)
                       │
        ┌──────────────┴───────────────┐
        ▼                              ▼
 erp-live.example.com          erp-test.example.com
 127.0.0.1:11000/12000         127.0.0.1:13000/14000
        │                              │
 ┌──────┴──────┐                ┌──────┴──────┐
 │  live-odoo  │                │  test-odoo  │   (Docker, --restart=always)
 │ 8069 / 8072 │                │ 8069 / 8072 │
 └──────┬──────┘                └──────┬──────┘
        │ live-db-net                  │ test-db-net
 ┌──────┴──────┐                ┌──────┴──────┐
 │   live-db   │                │   test-db   │   (PostgreSQL, host bind mount)
 └─────────────┘                └─────────────┘
```

**Port convention** (from `docker2update.yaml`):

| System | Web (→ 8069) | Websocket/longpolling (→ 8072) |
|---|---|---|
| live | `127.0.0.1:11000` | `127.0.0.1:12000` |
| test | `127.0.0.1:13000` | `127.0.0.1:14000` |

All Odoo ports are deliberately bound to `127.0.0.1` — reachable only through
nginx. Odoo ≥ 16 uses the `/websocket` route (no longer `/longpolling`); the
nginx templates generated by `nginx-set-conf` handle this automatically.

<a id="en-2-prerequisites"></a>
## 2. Prerequisites

- **OS:** Debian 12/13 or Ubuntu 20.04–26.04, freshly installed, root access
- **DNS:** A records for `erp-live.example.com` / `erp-test.example.com` pointing to the public IP
- **Behind NAT** (server has a private IP behind a firewall):
  - Firewall forwarding of **TCP 443 and TCP 80** to the internal server IP.
    Port 80 must stay open **permanently** (Let's Encrypt renewal!)
  - Internal clients: see [Troubleshooting → split DNS](#en-16-troubleshooting)
- **Odoo image:** your own registry image or a build directory following
  `Dockerfiles/v19-odoo/ReadMe.md` (Dockerfile, `build_odoo.py`, `release.file`,
  `odoo.conf`, `bin/boot`)

> ℹ️ **The server shell is fish.** `getScripts.py` installs fish as the
> default shell. For copy-paste blocks: `$status` instead of `$?`,
> `set VAR value` instead of `VAR=value`, no heredocs. Bash scripts still run
> fine via `./script.sh` or `bash -c '…'`.

<a id="en-3-step-1-bootstrap"></a>
## 3. Step 1: Bootstrap

`bootstrap.sh` brings a fresh server into a defined baseline state —
idempotent and safe to re-run.

```bash
# As root on the fresh server:
curl -fsSL https://raw.githubusercontent.com/equitania/myodoo-docker/2026/scripts/bootstrap.sh \
  -o /opt/myodoo-bootstrap.sh && chmod +x /opt/myodoo-bootstrap.sh && /opt/myodoo-bootstrap.sh
```

Installs: Docker CE (official repo), nginx (nginx.org), certbot, UFW
(installed but **deliberately disabled** — see hardening), fail2ban,
unattended-upgrades, Python dependencies; clones the repo and finally runs
`getScripts.py`. Individual steps can be disabled via env vars
(`INSTALL_NGINX=0`, `INSTALL_DOCKER=0`, `RUN_GETSCRIPTS=0`, …).

> ⚠️ **Lesson learned (Docker ≥ 29):** Fresh installs of Docker ≥ 29 default
> to the containerd image store, whose image export is broken for large
> builds ([moby/moby#52431](https://github.com/moby/moby/issues/52431)).
> `bootstrap.sh` ≥ 1.7.0 therefore pins the classic `overlay2` driver in
> `/etc/docker/daemon.json`. For servers set up **without** a current
> bootstrap: symptoms and cure in [Troubleshooting](#en-16-troubleshooting).

<a id="en-4-step-2-getscriptspy"></a>
## 4. Step 2: getScripts.py

Installs the fish shell configuration, all aliases/functions and the
management scripts (including `container2backup.py`, `update_docker_odoo.py`)
into `/root`. Executed automatically by bootstrap; manually:

```bash
/root/getScripts.py                 # install / update
/root/getScripts.py --dns-check     # check/optimize DNS configuration
/root/getScripts.py --proxy-check   # set up Docker daemon proxy (proxy customers)
/root/getScripts.py --reconfigure   # re-run first-run configuration
```

Then open a new shell (or `source ~/.config/fish/config.fish`) — the aliases
from [chapter 15](#en-15-shell-reference-fish) are available. Update later
with `ups`.

> ⚠️ **Lesson learned (sudo su):** Operators who log in with a personal admin
> account and become root via `sudo su` need getScripts.py ≥ 9.7.3 — older
> versions installed into the wrong home directory in that case (root's
> shell had no aliases).

<a id="en-5-step-3-server-hardening"></a>
## 5. Step 3: Server Hardening

1. Maintain the secrets file (template: `scripts/.env.example`):

```bash
mcedit /root/.config/myodoo-docker/.env   # SSH_PORT, ALLOWED_IP_1..n, alert mail
```

2. **Audit first** (changes nothing), then apply:

```bash
sudo python3 /root/server_hardening.py            # audit / dry run
sudo python3 /root/server_hardening.py --apply    # UFW, fail2ban, SSH, sysctl, auditd, AIDE, ...
```

UFW is only enabled here — after the SSH port and allowed IPs are configured,
so you cannot lock yourself out. Target individual modules with
`--apply --module ufw` or `-m fail2ban ssh sysctl`. Configuration:
`scripts/hardening_config.yaml`.

<a id="en-6-step-4-nginx-base--vhosts"></a>
## 6. Step 4: nginx Base + Vhosts

### 6.1 Deploy the base files

Every generated vhost references shared include files
(`nginxconfig.io/security.conf`, `general.conf`) and the maintenance page.
Without them `nginx -t` fails — so run this **before** the first vhost:

```bash
~/myodoo-docker/scripts/deploy-nginx-base.sh            # incl. nginx.conf (backup + validation + rollback)
~/myodoo-docker/scripts/deploy-nginx-base.sh --dry-run  # report only
```

> ⚠️ **Lesson learned (pid file trap):** `nginx -t` can (re)create
> `/run/nginx.pid` empty. The stock nginx.org unit reloads via
> `kill -s HUP $(cat /run/nginx.pid)` — with an empty file the reload fails
> (kill usage text in the journal) and **the old config silently stays
> live**. `deploy-nginx-base.sh` ≥ 1.1.0 repairs the pid file automatically.
> Permanent safeguard via systemd drop-in:
>
> ```bash
> mkdir -p /etc/systemd/system/nginx.service.d
> printf '[Service]\nExecReload=\nExecReload=/bin/kill -s HUP $MAINPID\n' \
>   > /etc/systemd/system/nginx.service.d/10-reload-mainpid.conf
> systemctl daemon-reload
> ```

### 6.2 Generate the vhost configuration

The interactive wizard builds the YAML file consumed by `nginx-set-conf` —
entry by entry ("add another domain?" loop), with validation and an optional
deploy at the end:

```bash
~/myodoo-docker/scripts/ngx-conf-wizard.sh
```

For the two Odoo systems: template `eq_odoo_ssl`, domain, certificate name,
port `11000` (live) / `13000` (test), pollport `12000` / `14000`. The YAML
lands in `$HOME/docker-builds/ngx-conf/`; deploy any time with:

```bash
ngxset        # = nginx-set-conf --config_path=$HOME/docker-builds/ngx-conf/
ngx!          # nginx -t
ngxs          # status
```

> ⚠️ **Lessons learned:**
> - **The bind IP must be LOCAL.** Behind NAT the **internal** IP
>   (`192.168.1.50`) belongs in the config, not the public DNS IP —
>   otherwise `bind() failed (99: Cannot assign requested address)`. The
>   wizard lists local IPs and warns about foreign ones.
> - `nginx-set-conf` only **reloads** — a stopped nginx is not started.
>   After the first deploy check `ngxs`, then `ngx+` if needed.

<a id="en-7-step-5-postgresql-live-dbtest-db"></a>
## 7. Step 5: PostgreSQL (live-db/test-db)

One dedicated PostgreSQL container per system — interactively via:

```bash
~/myodoo-docker/scripts/pg-local-deploy.sh   # run 1: live-db
~/myodoo-docker/scripts/pg-local-deploy.sh   # run 2: test-db
```

Prompts include container name (`live-db`), base directory, DB user/password,
PostgreSQL version (current tags:
<https://hub.docker.com/_/postgres/tags?name=16.>), performance profile
(2cpu4gb … 8cpu32gb) and optional **self-signed SSL**. The script creates the
network (`live-db-net`), a compose file
(`<base>/live-db-deploy/docker-compose.yml`) and starts the container.
Details: [scripts/README_pg-local-deploy.md](../scripts/README_pg-local-deploy.md).

> ⚠️ **Lesson learned (db_sslmode):** The `odoo.conf` inside the Odoo image
> must contain `db_sslmode = prefer`. With `require`, Odoo refuses to talk to
> a PostgreSQL without SSL ("server does not support SSL, but SSL was
> required"). Check before the first start:
>
> ```fish
> docker run --rm --entrypoint grep odoo/live db_sslmode /opt/odoo/etc/odoo.conf
> # expected: db_sslmode = prefer
> ```

<a id="en-8-step-6-first-start-of-the-odoo-containers"></a>
## 8. Step 6: First Start of the Odoo Containers

### 8.1 Provide the image

Either pull from your registry or build on the server. For a build, each
system has a build directory (e.g. `$HOME/docker-builds/live-odoo/` with
Dockerfile, `build_odoo.py`, `release.file`, `odoo.conf`, `bin/boot` — see
`Dockerfiles/v19-odoo/ReadMe.md`):

```fish
cd $HOME/docker-builds/live-odoo
docker build -t odoo/live .
```

### 8.2 Start the containers

```fish
# LIVE
docker run -d -p 127.0.0.1:11000:8069 -p 127.0.0.1:12000:8072 \
  --restart=always --network live-db-net \
  -v /opt/odoo/live:/opt/odoo/data --name="live-odoo" odoo/live:latest start

# TEST
docker run -d -p 127.0.0.1:13000:8069 -p 127.0.0.1:14000:8072 \
  --restart=always --network test-db-net \
  -v /opt/odoo/test:/opt/odoo/data --name="test-odoo" odoo/test:latest start
```

The boot script inside the container accepts exactly three commands:
`start` (normal operation), `update` (module update, used by `doup`),
`neutralize` (neutralize the DB, e.g. after restoring onto test).

### 8.3 Verify

```fish
dps                                                # both containers "Up"?
curl -sI http://127.0.0.1:11000/web/health         # HTTP/1.1 200 OK
docker logs --tail 20 live-odoo                    # errors in the log?
```

Then open `https://erp-live.example.com` in a browser → create the database.
Each instance's `odoo.conf` points at its DB container via `db_host`
(`live-db` / `test-db`) — name resolution is handled by the Docker network.

> ⚠️ **Lessons learned:**
> - **Always map with the `127.0.0.1:` prefix.** Without it, 11000/12000
>   listen on all interfaces — anyone on the LAN bypasses nginx, SSL and the
>   security headers.
> - If the start fails with `exec /app/bin/boot: no such file or directory`
>   although the build directory is correct → almost always the Docker 29
>   store bug, see [Troubleshooting](#en-16-troubleshooting).

<a id="en-9-step-7-lets-encrypt--reachability"></a>
## 9. Step 7: Let's Encrypt & Reachability

Certificates are created by `nginx-set-conf`/certbot during the vhost deploy
(HTTP-01 via port 80). Automatic renewal is handled later by the maintenance
cron ([chapter 12](#en-12-step-10-automate-maintenance)) via `ssl-renew.sh` —
nginx is only stopped when a certificate is actually due. Safety net:
`nginx-cert-guard.py` quarantines a single broken vhost (certificate/DNS)
instead of blocking the whole server.

```bash
showcerts                 # certbot certificates — check validity
/root/ssl-renew.sh        # manual renewal run
```

> ⚠️ **Lessons learned (NAT):**
> - The **port 80 forwarding must stay permanently** — without HTTP-01 no
>   renewal, and the certificate expires after 90 days.
> - **Internal clients cannot reach the domain, external access works?**
>   Classic split-DNS problem: internally the public IP is resolved and the
>   gateway cannot do hairpin NAT. Solution: create a pinpoint zone
>   `erp-live.example.com` with an A record pointing to the internal server
>   IP (`192.168.1.50`) on the internal DNS server — do **not** touch the
>   firewall for this.

<a id="en-10-step-8-set-up-updates-edupdoup"></a>
## 10. Step 8: Set Up Updates (edup/doup)

`update_docker_odoo.py` updates the Odoo containers automatically (image
rebuild, container re-creation, module update) — driven by
`~/docker2update.yaml`:

```bash
edup    # edit the YAML (mcedit)
doup    # run the update
```

Example entry per container (template: `scripts/docker2update.yaml`):

```yaml
containers:
  - active: true
    type: "F"                        # [M]odules | [F]ull | [N]eutralize
    delay_time: 10
    container_name: "live-odoo"
    database_name: "live_odoo"
    port: "127.0.0.1:11000"
    longpolling_port: "127.0.0.1:12000"
    dockerfile_path: "$HOME/docker-builds/live-odoo/"
    docker_image_name: "odoo/live"
    db_user: "ownerp"
    db_password: "***"
    db_host: "live-db"
    volume: "--network live-db-net -v /opt/odoo/live:/opt/odoo/data"
    odoo_version: "19"
    translate: "Y"
```

Useful options: `doup --validate` (check config), `-s CONTAINER` (single
container), `-v` (verbose). **Proxy customers:** `defaults.proxy` and
`pre_build_files` in the YAML, daemon proxy via `getScripts.py --proxy-check`.

<a id="en-11-step-9-set-up-backups-edbkdobk"></a>
## 11. Step 9: Set Up Backups (edbk/dobk)

`container2backup.py` backs up the SQL dump + filestore per database plus
service directories (nginx, letsencrypt, docker-builds) — driven by
`~/container2backup.yaml`:

```bash
edbk    # edit the YAML
dobk    # run a full backup
dobk --sql-only
llbk    # list the backup directory (/opt/backups/docker)
```

Example (template: `scripts/container2backup.yaml`):

```yaml
defaults:
  retention_days: 14
  db_user: ownerp
  backup_path: /opt/backups
  compression: { format: "7z", level: 5 }
  stream: false          # true = streaming .tar.zst (large filestores!)

databases:
  - name: live_odoo
    sql_container: live-db
    data_container: live-odoo
  - name: test_odoo
    sql_container: test-db
    data_container: test-odoo
    only_sql_dump: true
```

> 💡 **Lesson learned:** For large filestores (≫ 50 GB) set `stream: true` —
> the backup is piped straight into a `.tar.zst` without an uncompressed
> staging copy. Compression level 3 is enough (filestore media is already
> compressed). Details, encryption (AES-256/GPG) and per-format restore:
> [scripts/README_BackUp.md](../scripts/README_BackUp.md).

<a id="en-12-step-10-automate-maintenance"></a>
## 12. Step 10: Automate Maintenance

Once `container2backup.yaml` is in place, a single call wires up all
maintenance jobs as `/etc/cron.d/myodoo-maintenance` (incl. logrotate):

```bash
~/myodoo-docker/scripts/setup-maintenance-cron.sh
```

| Time | Job |
|---|---|
| 02:00 / 14:00 | `container2backup.py` — backups |
| 23:50 | `nginx-cert-guard.py --check --apply` — DNS drift/certificate guard |
| 00:00 | `ssl-renew.sh` — Let's Encrypt renewal |
| 03:00 | `cleanup-weblogs.py` — GDPR weblog rotation (7 days) |
| 04:30 | `nightly-cleanup.sh` — memory-based container restart |

Remove with `--remove`. Nightly cleanup details:
[scripts/NIGHTLY_CLEANUP.md](../scripts/NIGHTLY_CLEANUP.md).

<a id="en-13-restore--emergency"></a>
## 13. Restore & Emergency

Restore a backup (archive produced by `container2backup.py`; detects
`.zip/.7z/.7z.gpg/.tar.gz/.tar.zst` automatically):

```bash
env PGPASSWORD='<pg_password>' ~/myodoo-docker/scripts/restore-zip.sh \
  <backup_kind 1|2> <run_sql> <orig_dbname> <new_dbname> <drop_db Y/n> \
  <archive> <odoo_volume> <pg_container>
```

Pass the password via the `PGPASSWORD` environment variable — as the 9th
positional argument it would be visible in `ps aux` and shell history (the
script warns in that case).

Typical use case: restore the live backup as the test DB, then run
`neutralize` in the container (disables mails/cron). For manual container
updates without `doup` (fallback):
[docs/MANUAL_DOCKER_UPDATE_GUIDE.md](MANUAL_DOCKER_UPDATE_GUIDE.md).

<a id="en-14-script-reference"></a>
## 14. Script Reference

All scripts in this repository (`scripts/`, as of 16.07.2026):

| Script | Purpose | Invocation |
|---|---|---|
| `bootstrap.sh` (1.7.0) | Baseline for fresh servers (Docker, nginx, certbot, UFW, fail2ban) | `curl … bootstrap.sh -o /opt/… && /opt/myodoo-bootstrap.sh` |
| `getScripts.py` (9.7.3) | fish shell, aliases, management scripts into `/root` | `./getScripts.py [--dns-check\|--proxy-check\|--reconfigure]` |
| `server_hardening.py` (1.8.0) | Audit + hardening (UFW, fail2ban, SSH, sysctl, auditd, AIDE) | `sudo python3 server_hardening.py [--apply] [-m MODULE …]` |
| `deploy-nginx-base.sh` (1.1.0) | nginx base: includes, maintenance page, nginx.conf (with rollback) | `./deploy-nginx-base.sh [--dry-run] [--no-main-conf]` |
| `ngx-conf-wizard.sh` (1.1.0) | Interactive YAML wizard for nginx-set-conf | `./ngx-conf-wizard.sh` |
| `pg-local-deploy.sh` (1.2.1) | Deploy a PostgreSQL container interactively (profiles, optional SSL) | `./pg-local-deploy.sh` |
| `fr-local-deploy.sh` | Deploy the FastReport API container (default `/opt/fast-report`) | `./fr-local-deploy.sh` |
| `update_docker_odoo.py` (5.3.1) | Odoo container updates via YAML | `doup` or `python3 update_docker_odoo.py [-s NAME] [--validate]` |
| `container2backup.py` (4.7.1) | SQL+filestore backups, compression/encryption/streaming | `dobk` or `~/container2backup.py [--sql-only]` |
| `restore-zip.sh` (2.1.0) | Backup restore (DB + filestore) into Docker | see [chapter 13](#en-13-restore--emergency) |
| `ssl-renew.sh` (1.3.0) | certbot renewal, nginx stopped only when needed | `./ssl-renew.sh` (cron) |
| `nginx-cert-guard.py` (1.1.0) | Quarantine broken vhosts instead of blocking nginx | `--reconcile [--start]`, `--check [--apply]`, `--list`, `--restore DOMAIN` |
| `setup-maintenance-cron.sh` (1.2.0) | Install maintenance cron + logrotate | `./setup-maintenance-cron.sh [--remove]` |
| `nightly-cleanup.sh` (1.1.0) | Container restart under memory pressure | cron; `MEMORY_THRESHOLD=90 DRY_RUN=1 ./nightly-cleanup.sh` |
| `cleanup-weblogs.py` (2.0.0) | nginx log rotation, GDPR purge after 7 days | cron; `python3 cleanup-weblogs.py` |
| `dist-upgrade-debian.sh` (1.0.0) | Guided Debian major upgrade (e.g. bookworm→trixie) | `./dist-upgrade-debian.sh [CODENAME] [--yes]` |
| `check_docker_volumes.sh` (1.0.0) | List volumes and referencing containers | `dkvol` |

<a id="en-15-shell-reference-fish"></a>
## 15. Shell Reference (fish)

Complete reference with definitions: [fish/README.md](../fish/README.md).
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
| `dkrm` / `dkrmi` / `dkrmv` | Delete all containers/images/volumes — confirmation-gated, `dkrmv` requires typing `DELETE` |

**Odoo** (`35-aliases-odoo.fish`): `odoo-shell`, `odoo-logs`, `odoo-restart`,
`pg-shell` — placeholder container names, adapt per server.

<a id="en-16-troubleshooting"></a>
## 16. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `docker build` fails at "exporting to image" with `ref moby/1/… locked … unavailable` | Docker ≥ 29 with the containerd image store ([moby#52431](https://github.com/moby/moby/issues/52431)) | `/etc/docker/daemon.json`: `{"storage-driver": "overlay2"}` → `systemctl restart docker` → **reboot the server** → re-pull images, recreate containers (volumes survive) |
| `exec /app/bin/boot: no such file or directory` on container start although the build "succeeded" | Hollow image from a poisoned BuildKit cache (aftermath of the store bug). Cross-check: is even `/bin/sh` missing in the image? | After switching the store: `docker builder prune -af`, then `docker build --no-cache --pull` |
| Builds produce **non-deterministically** hollow images; kernel log: `overlayfs: lowerdir is in-use as upperdir/workdir of another mount` | Orphaned overlay mounts of the old store after a store switch without reboot — two overlay worlds share directories | **Reboot the server**, then `docker builder prune -af` + `docker build --no-cache --pull` |
| nginx: `bind() to 203.0.113.10:443 failed (99: Cannot assign requested address)` | Behind NAT the public DNS IP is not local | Use the **internal** IP in the vhost config; `ngx-conf-wizard.sh` lists the local IPs |
| `systemctl reload nginx` fails, journal shows kill usage text; old config stays live | Empty `/run/nginx.pid` (created by `nginx -t`), stock unit trusts the file | Install the `$MAINPID` drop-in ([chapter 6.1](#en-6-step-4-nginx-base--vhosts)); also happens on nginx **package upgrades** (postinst) — then `systemctl daemon-reload && systemctl restart nginx` |
| Odoo: "server does not support SSL, but SSL was required" when creating a DB | `db_sslmode = require` in odoo.conf, PostgreSQL without SSL | Set `db_sslmode = prefer` (or enable PG SSL via `pg-local-deploy.sh`) |
| Domain reachable externally but not internally | Split DNS: internal clients resolve the public IP, gateway cannot hairpin-NAT | Pinpoint zone on the internal DNS: `erp-live.example.com` → internal server IP |
| Certificate expires, renewal fails | Port 80 forwarding was removed | Forward TCP 80 → server permanently (HTTP-01) |
| `fish: $? is not the exit status …` | Bash syntax in the fish shell | `$status` instead of `$?`; bash blocks via `bash -c '…'` |
| Odoo web UI directly reachable via `IP:11000` from the LAN | Port mapping without the `127.0.0.1:` prefix | Recreate the container with `-p 127.0.0.1:11000:8069 …` |

<a id="en-17-optional-components"></a>
## 17. Optional Components

**FastReport API** (PDF rendering for Odoo): interactively via
`~/myodoo-docker/scripts/fr-local-deploy.sh` — default base
`/opt/fast-report`, one container per system (e.g. `fr-live`, `fr-test`),
registry access required. Backup integration via the `fast_report:` block in
`container2backup.yaml` ([chapter 11](#en-11-step-9-set-up-backups-edbkdobk)).

**Debian major upgrade:** `dist-upgrade-debian.sh` guides through an in-place
upgrade (rewrite sources, phased upgrade, reboot prompt).
