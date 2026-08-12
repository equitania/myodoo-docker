# Myodoo-Docker

(c) 2016 till now by Equitania Software GmbH

[🇩🇪 Deutsch](#deutsch) | [🇬🇧 English](#english)

<a name="deutsch"></a>
## Deutsch

### Über dieses Repository

Dieses Repository enthält eine Sammlung von Docker-Konfigurationen und Verwaltungsskripten für Odoo-Installationen. Es wird täglich in der professionellen Administration von Kundensystemen eingesetzt — vom Provisionieren eines frischen Servers über die Härtung bis zu Backup, SSL und Wartung.

### Schnellstart

➡️ **Kompletter Leitfaden vom frischen Server bis zum laufenden Odoo-live/test-System:** [docs/INSTALLATION_GUIDE.md](docs/INSTALLATION_GUIDE.md)

Für einen **frisch installierten Debian-/Ubuntu-Server** ist `bootstrap.sh` der Einstiegspunkt. Es richtet die Grundausstattung (Docker, nginx, certbot, UFW, fail2ban, automatische Sicherheitsupdates) ein und ruft anschließend `getScripts.py` auf.

```bash
# Out-of-the-box-Initialisierung (als root):
curl -fsSL https://raw.githubusercontent.com/equitania/myodoo-docker/2026/scripts/bootstrap.sh \
  -o /opt/myodoo-bootstrap.sh && chmod +x /opt/myodoo-bootstrap.sh && /opt/myodoo-bootstrap.sh

# Klassische Installation der Skripte (falls bootstrap nicht genutzt wird):
git clone https://github.com/equitania/myodoo-docker.git
cp myodoo-docker/getScripts.py /root/
./getScripts.py

# DNS-Optimierung (eigenständig)
./getScripts.py --dns-check
```

### Server-Lifecycle / Provisioning-Workflow

Die Tools sind auf einen klaren Ablauf abgestimmt:

1. **`bootstrap.sh`** — Grundausstattung auf frischem Server (idempotent, abschaltbar).
2. **`getScripts.py`** — Fish-Shell, Aliase/Funktionen und alle Verwaltungsskripte nach `/root`.
3. **`.env` pflegen** — `/root/.config/myodoo-docker/.env` (SSH-Port, erlaubte IPs) für die Härtung.
4. **`server_hardening.py`** — erst Audit (ohne `--apply`), dann `--apply` (UFW, fail2ban, SSH, sysctl, auditd, AIDE …).
5. **`setup-maintenance-cron.sh`** — Wartungs-Cron (Backup, Cert-Erneuerung, DSGVO-Weblog-Bereinigung), nachdem `container2backup.yaml` konfiguriert ist.

### Hauptkomponenten

#### 1. Provisionierung & Härtung

- **bootstrap.sh** (v1.6.x)
  - Out-of-the-box-Initialisierung für frische **Debian 12/13** und **Ubuntu 20.04/22.04/24.04/26.04**
  - Installiert Docker CE (offizielles Repo), nginx (nginx.org), certbot, UFW (installiert, aber bewusst DEAKTIVIERT), fail2ban-Baseline, unattended-upgrades
  - Generiert `en_US.UTF-8`-Locale auf Minimal-Images (z. B. IONOS), bei denen SSH mit `LANG=en_US.UTF-8` verbindet, die Locale aber nicht installiert ist (perl/apt-Warnungen)
  - Self-Install nach `/opt`, idempotent, jede Stufe per Umgebungsvariable abschaltbar (`INSTALL_DOCKER`, `INSTALL_NGINX`, `INSTALL_CERTBOT`, `INSTALL_UFW`, `INSTALL_FAIL2BAN`, `INSTALL_UNATTENDED`)

- **server_hardening.py** (v1.5.x)
  - Config-getriebenes Audit-/Apply-Tool (`hardening_config.yaml`)
  - Module: `ufw`, `fail2ban`, `ssh`, `sysctl`, `sysctl_persist`, `kernel_modules`, `docker`, `auto_updates`, `auditd`, `aide`, `nginx`, `ports`
  - Ohne `--apply` reiner Dry-Run; mit `--apply` werden Dateien geändert (jeweils mit Timestamp-Backup)
  - Lockout-sicher: SSH-Config wird erst nach `sshd -t` atomar getauscht; Docker wird nie automatisch neugestartet
  - `.env` füllt die Platzhalter (SSH-Port, erlaubte Quell-IPs); `--help` erklärt jedes Modul ausführlich

- **dist-upgrade-debian.sh** (v1.0.x)
  - Geführtes Debian-Major-Upgrade (z. B. bookworm → trixie), phasenweise nach den Release Notes
  - Sichert alle apt-Quellen vor dem Umschreiben; fragt vor Reboot nach; verweigert die Ausführung auf Ubuntu

#### 2. Verwaltungsskripte

- **getScripts.py** (Version 9.x)
  - Hauptinstallationsskript: Fish Shell mit Starship Prompt, alle Werkzeuge/Abhängigkeiten
  - Aktualisiert bestehende Installationen, verteilt die Verwaltungsskripte nach `/root`
  - DNS-Konfigurationsprüfung und -optimierung (erkennt u. a. Hetzner-DNS-Probleme mit DigitalOcean)
  - Schlanke Ausgabe: ohne `-v` erscheinen nur Status zu Serveroptimierungen, Warnungen und Fehler auf dem Schirm. Alles Übrige — jede INFO-Zeile und die gesamte Ausgabe der aufgerufenen Programme (apt, git, curl) — steht in `~/getscripts.log`; scheitert ein Befehl, kommt das Ende seiner Ausgabe zurück auf den Schirm. `ups -v` reicht das Flag durch

- **container2backup.py** (v4.6.x)
  - Automatisches Backup-System für Odoo-Datenbanken (SQL + Filestore + zusätzliche Pfade)
  - Konfiguration über YAML; Kompression 7z/zip/gzip/zstd; optional GPG-Verschlüsselung (`.7z.gpg`, Primär) mit Fallback auf 7z-internes AES (nur wenn `gnupg` fehlt)
  - Automatische Bereinigung alter Backups; cron-sicher (bricht bei Pfadproblemen non-interaktiv sauber ab)
  ```yaml
  # Beispiel container2backup.yaml
  defaults:
    retention_days: 14
    db_user: ownerp
    compression:
      format: "7z"  # 7z, zip, gzip, zstd
      level: 5      # Kompressionsgrad (0-9)
  ```
  → Ausführliche Doku: [scripts/README_BackUp.md](scripts/README_BackUp.md)

- **restore-zip.sh** (v2.x) — Wiederherstellung aus den von container2backup.py erzeugten Backups; erkennt das Format automatisch (`.zip`, `.7z`, `.7z.gpg`, `.tar.gz`, `.tar.zst`)
- **update_docker_odoo.py** (v5.11.x) — automatisierte Aktualisierung von Docker-Containern inkl. Neustart-Management; Option `db_password_via_env: true` pro Container in `docker2update.yaml` übergibt das DB-Passwort via `PGPASSWORD`-Umgebungsvariable statt als `--db_password=...` in argv (verhindert Sichtbarkeit in `ps aux`); Standard: `false` (Legacy-Modus für ältere Images). Ohne `-v` bleibt die Ausgabe knapp; Warnungen und Fehler des gesamten Laufs stehen gesammelt im Abschlussblock. Unabhängig davon schreibt jeder Lauf ein vollständiges Protokoll in den Build-Ordner der Instanz (`update_JJJJMMTT_HHMMSS.log`) — mit allen INFO-Zeilen, die die Konsole verschweigt; die Pfade werden zum Schluss genannt, auch nach Abbruch oder Fehler
  - Auswahl für einen einzelnen Lauf, ohne die YAML anzufassen: `-s` nimmt mehrere Namen (wiederholt oder kommagetrennt), `--type M|F|N` überschreibt den Modus dieses Laufs, `--comment "…"` hält fest, warum er stattfand. **`-s` sticht `active: false`** — ein ausdrücklich benannter Container läuft, auch wenn er in der Konfiguration geparkt ist; ein unbekannter Name bricht ab, statt stillschweigend nichts zu tun
  - Jeder Container-Lauf hinterlässt eine Zeile in `~/update-history.jsonl`: wann, welches System, welcher Modus, Ergebnis, Dauer, Protokollpfad und Kommentar. Geschrieben vom Skript selbst, also auch bei klassischen und Cron-Läufen. Aufbewahrung über `defaults.history_retention_days` (Standard 365 Tage, `0` = unbegrenzt)

- **ownerp_tui.py** (v1.1.0) — Auswahlmaske für Ad-hoc-Updates, gestartet mit `tui`. Listet alle Systeme aus `docker2update.yaml` mit Modus und letztem Lauf; Space wählt aus, `m` schaltet den Modus (M/F/N), `c` hinterlegt einen Kommentar, `w` ruft den Assistenten `ownerp_wizard.py` auf und lädt die Liste danach neu, Enter startet. **Die YAML wird nie verändert** — `active:` und `type:` sind die Vorauswahl, der Lauf selbst geht als Argumente an `update_docker_odoo.py`; es gibt danach nichts zurückzustellen. Ein Neutralize (`N`) in der Auswahl verlangt eine zweite Bestätigung mit Nennung der betroffenen Datenbanken. Ohne Terminal, bei `TERM=dumb` oder unter 80×20 Zeichen verweigert die Maske den Start mit einem klaren Satz — ein Cronjob bleibt nie in ihr hängen
- **odoo_build_cache.py** (v1.5.x) — Host-Cache der Release-Archive unter `/opt/odoo-build-cache`, den sich alle Instanzen desselben Release teilen: ein Build lädt nur noch, was sich geändert hat. Blockiert nie einen Build — was der Cache nicht liefert, holt `build_odoo.py` wie zuvor selbst. Pflegt zusätzlich Dockerfile und `odoo.conf` des Build-Ordners, die sonst nichts aktualisiert: fehlende Image-Direktiven (`HEALTHCHECK`, `VOLUME`, `EXPOSE`) werden ergänzt, ein `ADD` an das `COPY` der Vorlage angeglichen, wo beides dasselbe tut, und ungesetzte verwaltete Konfigurationsschlüssel (`http_interface`) aus der Vorlage gefüllt — Passwörter bleiben unberührt, alles nur Abweichende wird gemeldet. `stats` zeigt die Belegung, `gc` räumt nach 30 Tagen auf (Wartungs-Cron)
- **ownerp_validate.py** (v1.0.0) — rein lesende Prüfung von `docker2update.yaml` und `container2backup.yaml` gegen ihr jeweiliges Schema, gestartet mit `doval`. Prüft Pflichtfelder, Typen, Portform (`11000`, `"11000"`, `"127.0.0.1:11000"`, `"[::1]:11000"`), doppelte Container-/Datenbanknamen und doppelte Host-Ports (**nur unter aktiven Einträgen**), ob konfigurierte Pfade existieren (Warnung), und unbekannte Schlüssel mit Vorschlag für den nächstliegenden bekannten Namen (ebenfalls Warnung). Ein Block mit `active: false` wird vollständig geprüft, seine Befunde werden aber zu Warnungen mit dem Präfix `(inactive)` herabgestuft — ein geparkter Block färbt den Exitcode nie rot. Schreibt nie, zeigt nie den Wert eines auf `password` endenden Schlüssels. **Exitcode**: `0` keine Fehler (Warnungen können vorhanden sein und wirken sich nie auf den Exitcode aus), `1` mindestens ein Fehler, `2` Datei fehlt/unlesbar/nicht parsebar oder PyYAML fehlt. `update_docker_odoo.py --validate` und `container2backup.py --validate` rufen es intern auf
- **ownerp_wizard.py** (v1.0.0) — geführtes Bearbeiten von `docker2update.yaml`, gestartet mit `wiz`: eine Instanz hinzufügen oder ein einzelnes Feld eines bestehenden Eintrags ändern. Liest die Konfiguration, bevor er etwas fragt, und schlägt aus ihr vor — den nächsten freien Host-Port (über **beide** Port-Felder **aller** Einträge, auch inaktiver), einen `db_user`/`db_host`, auf den sich alle Einträge einigen, das gemeinsame Muster des Build-Ordners mit eingesetztem neuem Namen, den gemeinsamen Präfix der Image-Namen. Der Vorschlag steht in Klammern und wird mit Enter übernommen; sind sich die Einträge uneinig, schlägt er nichts vor, statt zu raten. **Das einzige Werkzeug dieser Sammlung, das in eine Kundenkonfiguration schreibt** — deshalb ist der Schreibweg die Substanz: Sicherung nach `<Pfad>.bak-<JJJJmmtt_HHMMSS>` → Aufbau im Speicher → temporäre Datei **im selben Verzeichnis** → `ownerp_validate.py` prüft genau diese Datei → **Fehler: temporäre Datei *und* Sicherung werden entfernt, das Original bleibt Byte für Byte unverändert** → **sauber: `os.replace()`**, die Sicherung bleibt. Warnungen blockieren nie, denn ein noch nicht existierender Build-Ordner ist bei einer neuen Instanz der Normalfall. **Verweigert statt zu raten**: ohne Terminal (nennt `edup`), ohne `ownerp_validate.py` daneben (nennt `ups`), bei nicht parsebarer Konfiguration (verweist auf `doval`). Ein doppelter Container- oder Datenbankname wird schon am Prompt abgelehnt, nicht erst bei der Prüfung. Bearbeitet **nur Skalare** (`pre_build_files` und `proxy` werden gezeigt, nie geändert) und **entfernt nie einen Eintrag**. `db_password` wird nie vorgeschlagen, nie angezeigt (`getpass`) und erscheint in jeder Zusammenfassung als `********`. Sein einziger Schreibzugriff außerhalb der YAML ist der leere Build-Ordner, den er anzulegen anbietet — hineinkopiert wird nichts, das Befüllen gehört zu `odoo_build_cache.py`
- **cleanup-weblogs.py** (v2.x) — DSGVO-konforme nginx-Log-Rotation: rotiert `/var/log/nginx/*.log` und löscht `.bak` älter als 7 Tage (Access-Logs enthalten personenbezogene IP-Adressen)
- **nightly-cleanup.sh** — speicherbasierter Container-Neustart bei Überschreiten einer Schwelle → [scripts/NIGHTLY_CLEANUP.md](scripts/NIGHTLY_CLEANUP.md)
- **setup-maintenance-cron.sh** — installiert die Wartungs-Cron-Jobs deklarativ als `/etc/cron.d/myodoo-maintenance` plus passende logrotate-Konfiguration (idempotent, `--remove` zum Entfernen)
- **server-readiness.py** (v1.0.0) — beantwortet „ist dieser Server auf Stand, und was fehlt noch?“ mit einer Ampel-Liste aus 13 Prüfungen (Wartungs-Cron, logrotate, doppelte Cron-Einträge, Log-Größen, Backup-Alter/-Konfiguration/-Plattenplatz, Docker-Storage-Driver, nginx-systemd-Drop-in, certbot-Fenster, Skript-Stände). Zu jedem Befund gehört genau ein kopierfertiger Fix-Befehl. **Rein lesend** — verändert nichts. Läuft automatisch am Ende jedes `ups`-Laufs (`--brief`), auf Zuruf per `chk`, und wöchentlich montags 06:00 per Cron (`--quiet`, meldet sich nur bei Abweichung)
- **nginx-cert-guard.py** — verhindert den nginx-Totalausfall, wenn eine Kunden-(Sub-)Domain nicht mehr auf den Server zeigt. `--reconcile` bringt nginx beim Renewal **immer** hoch und isoliert dabei nur die kaputte vhost (statt dass ein einzelnes fehlendes Zertifikat den ganzen Server lahmlegt); `--check` erkennt weg-zeigende Domains proaktiv per DNS und deaktiviert sie nach mehreren bestätigten Fehlläufen + Alarm-Mail. Mit Massenfehler-Schutz (kein Blind-Abschalten). Reaktivierung via `--restore <domain>`
- **deploy-nginx-base.sh** — rollt die von jeder vhost benötigten nginx-Basisdateien aus (`nginxconfig.io/security.conf`, `general.conf`, `html/custom_50x.html`) nach `/etc/nginx` und tauscht die `nginx.conf` abgesichert aus (Backup + `nginx -t` + automatischer Rollback bei Fehler). **Vor** dem Erstellen von vhosts ausführen, damit `include nginxconfig.io/...` nie fehlschlägt. Idempotent; `--no-main-conf`, `--dry-run`

#### 3. Shell-Konfiguration (ab Version 7.0)

**Fish Shell** ist die primäre Shell mit Starship Prompt.

```
fish/
├── config.fish              # Einstiegspunkt
├── conf.d/
│   ├── 00-env.fish         # Umgebungsvariablen
│   ├── 10-path.fish        # PATH-Konfiguration
│   ├── 20-tools.fish       # Zoxide, Starship Init
│   ├── 30-aliases-*.fish   # Domain-spezifische Aliase
│   └── 50-prompt.fish      # Startup-Verhalten
└── functions/linux/        # Linux-spezifische Funktionen
```

**Starship Prompt** zeigt: Benutzer/Hostname, Git-Branch und -Status, Docker-Kontext, Python/Node.js/Rust-Versionen, Befehlsdauer (>2s).

#### 4. Systemkonfigurationen

- Nginx-Konfigurationen für Reverse Proxy
- Let's Encrypt SSL-Integration via certbot (Erneuerung standalone über `ssl-renew.sh`)
- Docker-Build-Konfigurationen

#### 5. Sicherheitsfeatures

- Mehrschichtige Serverhärtung über `server_hardening.py`: UFW-Firewall, fail2ban, SSH-Härtung (`sshd_config`), Kernel-Parameter (`sysctl`), Kernel-Modul-Blacklist, Docker-daemon-Härtung, auditd und AIDE (File-Integrity)
- Automatische Sicherheitsupdates (unattended-upgrades)
- Verschlüsselte Backups (AES-256, 7z)
- Automatische SSL-Zertifikatserneuerung (mit nginx-Ausfallschutz via `nginx-cert-guard.py`)
- DSGVO-konforme Weblog-Bereinigung (7 Tage Aufbewahrung)
- DNS-Optimierung für bessere Performance

#### 6. Shell-Aliase & Funktionen

Die Fish-Konfiguration enthält ~80 Aliase und Funktionen. Unten die wichtigsten — die **vollständige Referenz** steht in [fish/README.md](fish/README.md).

> **Hinweis:** `syspatch`, `ups`, `chk`, `dkrm`, `dkrmi`, `dkrmv` sind **Funktionen** (mit Logik/Bestätigung), keine einfachen Aliase.

##### System (Funktionen & Aliase)
- `syspatch` *(Funktion)* — umfassende Systemaktualisierung + Bereinigung (inkl. AIDE-Baseline)
- `ups` *(Funktion)* — ownERP-Skripte aus dem Repository aktualisieren
- `chk` *(Funktion)* — Readiness-Report: ist der Server auf Stand, was fehlt noch? (rein lesend)
- `prepatch` — Systemupdate in einer Screen-Session vorbereiten
- `cleandlog` — Docker-Container-Logs leeren
- `dusort` — Verzeichnisgrößen sortiert anzeigen
- `f2b` — `fail2ban-client status`
- `fishcfg` — Fish-Konfiguration bearbeiten

##### ownERP / Backup
- `dobk` — Backup-Skript ausführen (`container2backup.py`)
- `edbk` — Backup-Konfiguration bearbeiten (`container2backup.yaml`)
- `tui` — Auswahlmaske für Updates (`ownerp_tui.py`): System, Modus und Kommentar wählen, dann starten
- `doup` *(Funktion)* — Docker-Container aktualisieren (`update_docker_odoo.py`). Startet die Maske statt des Skripts, sobald `~/.ownerp_tui_default` existiert (in der Maske mit `d` umschaltbar) — aber nur ohne Argumente und nur in einer interaktiven Shell. Mit Argumenten oder ohne Terminal läuft immer das Skript
- `edup` — Update-Konfiguration bearbeiten (`docker2update.yaml`)
- `doval` — beide YAML-Konfigurationen prüfen (`ownerp_validate.py`): rein lesend, Exitcode `0`/`1`/`2`, Warnungen zählen nicht
- `wiz` — Instanz hinzufügen oder ein Feld ändern (`ownerp_wizard.py`): geführt, mit Vorschlägen aus der bestehenden Konfiguration. Prüft, bevor er ersetzt; verweigert ohne Terminal; entfernt nie einen Eintrag. In der Maske `tui` liegt derselbe Assistent auf der Taste `w`
- `llbk` / `cdbk` / `cpbk` — Backup-Verzeichnis `/opt/backups/docker` auflisten / hineinwechseln / kopieren

##### Nginx
- `cdngx` — ins Konfigurationsverzeichnis wechseln
- `ngx+` / `ngx-` / `ngx#` / `ngxr` / `ngxs` — Nginx start / stop / restart / reload / status
- `ngx!` / `ngxl` — Konfigurationstest
- `ngxset` — Konfiguration mit `nginx-set-conf` setzen
- `showcerts` — `certbot certificates`

##### Docker
- `dk` — Shortcut für `docker`
- `dps` / `dpsall` — Container übersichtlich auflisten
- `dpi` — Images anzeigen
- `dkvol` — Docker-Volumes prüfen (`check_docker_volumes.sh`)
- `dkstop` — alle Container stoppen
- `dkrm` / `dkrmi` / `dkrmv` *(Funktionen)* — alle Container / Images / Volumes entfernen (mit Bestätigung)
- `dkprs` / `dkprv` / `dkprf` / `dkprfa` — Docker-System/-Volumes bereinigen
- `dco` / `dcup` / `dcdown` / `dclogs` / `dcps` — `docker compose`-Kürzel
- `ct` — Shortcut für `ctop`

##### Weitere Kategorien
- **Git** (`g`, `gst`, `gco`, `gcm`, `gp`, `gl`, `glog` …) — siehe fish/README.md
- **Odoo** (`odoo-shell`, `odoo-logs`, `odoo-restart`, `pg-shell`) — siehe fish/README.md

#### 7. DNS-Optimierung

```bash
./getScripts.py            # DNS-Optimierung als Teil der Installation
./getScripts.py --dns-check # Nur DNS-Prüfung
```

**Erkannte Probleme:** Hetzner-DNS-Server können Probleme mit DigitalOcean-Servern verursachen; langsame Auflösung (>50ms); suboptimale Konfiguration.

**Empfohlene DNS-Server:** 1.1.1.1 (Cloudflare), 8.8.8.8 (Google), 9.9.9.9 (Quad9).

### Branch-Verwaltung

```bash
# Wechsel zu einer spezifischen Version (z.B. 2026)
cd $HOME && rm -rf myodoo-docker && rm -rf nginx-conf && \
  git clone -b 2026 https://github.com/equitania/myodoo-docker.git && \
  cp myodoo-docker/getScripts.py $HOME && \
  $HOME/getScripts.py && source ~/.config/fish/config.fish
```

### Weiterführende Dokumentation

- **[docs/INSTALLATION_GUIDE.md](docs/INSTALLATION_GUIDE.md) — der rote Faden: frischer Server → Odoo live/test in zehn Schritten (DE/EN), jeder Schritt mit Link in die zuständige Anleitung**

Die Anleitungen selbst liegen je Aufgabe in [docs/usage/](docs/usage/) — jede
zweisprachig, jede für sich lesbar:

| Anleitung | Worum es geht |
|---|---|
| [01 Provisionierung und Härtung](docs/usage/01-provisioning.md) | Überblick, Voraussetzungen, `bootstrap.sh`, `getScripts.py`, `server_hardening.py` |
| [02 nginx und Zertifikate](docs/usage/02-nginx-certs.md) | Basisdateien, Vhosts per Wizard, Let's Encrypt, Erreichbarkeit |
| [03 PostgreSQL und Odoo-Container](docs/usage/03-postgres-odoo.md) | `pg-local-deploy.sh`, Build-Ordner, Erststart von live und test |
| [04 Updates einrichten und fahren](docs/usage/04-updates.md) | `edup`, `doup`, Auswahlmaske `tui`, Assistent `wiz`, Laufhistorie |
| [05 Backup und Restore](docs/usage/05-backup-restore.md) | `edbk`, `dobk`, Aufbewahrung, Verschlüsselung, Wiederherstellung, Notfall |
| [06 Wartung und optionale Komponenten](docs/usage/06-maintenance.md) | Wartungs-Cron, Bereitschaftsprüfung, FastReport, Debian-Major-Upgrade |
| [07 Betrieb hinter HTTP-Proxy](docs/usage/07-proxy.md) | Server, die nur über einen Firmen-Proxy ins Internet dürfen |
| [08 Troubleshooting](docs/usage/08-troubleshooting.md) | Symptom → Ursache → Lösung, inklusive der Docker-≥-29-Fallen |
| [09 Skript- und Shell-Referenz](docs/usage/09-reference.md) | Alle Skripte mit Aufruf, alle fish-Aliase nach Kategorie |

- [scripts/README_BackUp.md](scripts/README_BackUp.md) — Backup-System (Konfiguration, Kompression, Automatisierung)
- [scripts/README_pg-local-deploy.md](scripts/README_pg-local-deploy.md) — PostgreSQL-Container-Deployment (Profile, Self-Signed-SSL)
- [scripts/NIGHTLY_CLEANUP.md](scripts/NIGHTLY_CLEANUP.md) — speicherbasierter Container-Neustart
- [fish/README.md](fish/README.md) — vollständige Alias-/Funktionsreferenz
- [docs/MANUAL_DOCKER_UPDATE_GUIDE.md](docs/MANUAL_DOCKER_UPDATE_GUIDE.md) — manuelles Container-Update (Fallback)

#### Skripte auf einen Blick

| Aufgabe | Befehl / Skript | Details |
|---|---|---|
| Server initialisieren | `bootstrap.sh` (One-Liner) | [Provisionierung](docs/usage/01-provisioning.md#de-3-schritt-1-bootstrap) |
| Shell & Skripte installieren | `./getScripts.py` | [Provisionierung](docs/usage/01-provisioning.md#de-4-schritt-2-getscriptspy) |
| Server härten | `sudo python3 server_hardening.py --apply` | [Provisionierung](docs/usage/01-provisioning.md#de-5-schritt-3-server-härtung) |
| nginx-Basis + Vhosts | `deploy-nginx-base.sh`, `ngx-conf-wizard.sh`, `ngxset` | [nginx & Zertifikate](docs/usage/02-nginx-certs.md#de-6-schritt-4-nginx-basis--vhosts) |
| PostgreSQL deployen | `pg-local-deploy.sh` | [PostgreSQL & Odoo](docs/usage/03-postgres-odoo.md#de-7-schritt-5-postgresql-live-dbtest-db) |
| Odoo-Container starten | `docker run … start` | [PostgreSQL & Odoo](docs/usage/03-postgres-odoo.md#de-8-schritt-6-odoo-container-erststarten) |
| Updates | `edup` (Config) / `doup` (Lauf) / `tui` (Auswahlmaske) | [Updates](docs/usage/04-updates.md#de-10-schritt-8-updates-einrichten-edupdoup) |
| Instanz hinzufügen | `wiz` (geführt, prüft vor dem Schreiben) | [Updates](docs/usage/04-updates.md#de-10-schritt-8-updates-einrichten-edupdoup) |
| Backups | `edbk` (Config) / `dobk` (Lauf) / `llbk` | [Backup & Restore](docs/usage/05-backup-restore.md#de-11-schritt-9-backups-einrichten-edbkdobk) |
| Konfiguration prüfen | `doval` (beide YAMLs, rein lesend) | [Backup & Restore](docs/usage/05-backup-restore.md#de-11-schritt-9-backups-einrichten-edbkdobk) |
| Wartungs-Cron | `setup-maintenance-cron.sh` | [Wartung](docs/usage/06-maintenance.md#de-12-schritt-10-wartung-automatisieren) |
| Restore | `restore-zip.sh` | [Backup & Restore](docs/usage/05-backup-restore.md#de-13-restore--notfall) |
| Proxy-Umgebung einrichten | `./getScripts.py --proxy-check` | [Proxy](docs/usage/07-proxy.md#de-18-betrieb-hinter-http-proxy) |
| Alle 17 Skripte + Usages | — | [Referenz](docs/usage/09-reference.md#de-14-skript-referenz) |

---

<a name="english"></a>
## English

### About this Repository

This repository contains a collection of Docker configurations and management scripts for Odoo installations. It is used daily in professional customer system administration — from provisioning a fresh server through hardening to backup, SSL, and maintenance.

### Quick Start

➡️ **Complete guide from a fresh server to a running Odoo live/test system:** [docs/INSTALLATION_GUIDE.md](docs/INSTALLATION_GUIDE.md)

For a **freshly installed Debian/Ubuntu server**, `bootstrap.sh` is the entry point. It sets up the baseline (Docker, nginx, certbot, UFW, fail2ban, automatic security updates) and then runs `getScripts.py`.

```bash
# Out-of-the-box initialization (as root):
curl -fsSL https://raw.githubusercontent.com/equitania/myodoo-docker/2026/scripts/bootstrap.sh \
  -o /opt/myodoo-bootstrap.sh && chmod +x /opt/myodoo-bootstrap.sh && /opt/myodoo-bootstrap.sh

# Classic script installation (if bootstrap is not used):
git clone https://github.com/equitania/myodoo-docker.git
cp myodoo-docker/getScripts.py /root/
./getScripts.py

# DNS optimization (standalone)
./getScripts.py --dns-check
```

### Server Lifecycle / Provisioning Workflow

The tools follow a clear sequence:

1. **`bootstrap.sh`** — baseline on a fresh server (idempotent, toggleable).
2. **`getScripts.py`** — Fish shell, aliases/functions, and all management scripts into `/root`.
3. **Fill `.env`** — `/root/.config/myodoo-docker/.env` (SSH port, allowed IPs) for hardening.
4. **`server_hardening.py`** — audit first (no `--apply`), then `--apply` (UFW, fail2ban, SSH, sysctl, auditd, AIDE …).
5. **`setup-maintenance-cron.sh`** — maintenance cron (backup, cert renewal, DSGVO weblog purge) once `container2backup.yaml` is configured.

### Main Components

#### 1. Provisioning & Hardening

- **bootstrap.sh** (v1.6.x)
  - Out-of-the-box initializer for fresh **Debian 12/13** and **Ubuntu 20.04/22.04/24.04/26.04**
  - Installs Docker CE (official repo), nginx (nginx.org), certbot, UFW (installed but deliberately DISABLED), fail2ban baseline, unattended-upgrades
  - Generates the `en_US.UTF-8` locale on minimal cloud images (e.g. IONOS) where SSH connects with `LANG=en_US.UTF-8` but the locale is not installed (eliminates perl/apt warnings)
  - Self-installs to `/opt`, idempotent, every stage toggleable via env var (`INSTALL_DOCKER`, `INSTALL_NGINX`, `INSTALL_CERTBOT`, `INSTALL_UFW`, `INSTALL_FAIL2BAN`, `INSTALL_UNATTENDED`)

- **server_hardening.py** (v1.5.x)
  - Config-driven audit/apply tool (`hardening_config.yaml`)
  - Modules: `ufw`, `fail2ban`, `ssh`, `sysctl`, `sysctl_persist`, `kernel_modules`, `docker`, `auto_updates`, `auditd`, `aide`, `nginx`, `ports`
  - Without `--apply` it is a pure dry-run; with `--apply` files are changed (each with a timestamped backup)
  - Lockout-safe: the SSH config is swapped atomically only after `sshd -t`; Docker is never restarted automatically
  - `.env` fills the placeholders (SSH port, allowed source IPs); `--help` documents each module in detail

- **dist-upgrade-debian.sh** (v1.0.x)
  - Guided Debian major upgrade (e.g. bookworm → trixie), phased per the release notes
  - Backs up all apt sources before rewriting; prompts before reboot; refuses to run on Ubuntu

#### 2. Management Scripts

- **getScripts.py** (Version 9.x)
  - Main installation script: Fish shell with Starship prompt, all tools/dependencies
  - Updates existing installations, deploys the management scripts to `/root`
  - DNS configuration check and optimization (detects e.g. Hetzner DNS issues with DigitalOcean)
  - Lean output: without `-v` only server-optimization status, warnings and errors reach the screen. Everything else — every INFO line and all output of the programs it calls (apt, git, curl) — goes to `~/getscripts.log`; when a command fails, the tail of its output comes back on screen. `ups -v` forwards the flag

- **container2backup.py** (v4.6.x)
  - Automatic backup system for Odoo databases (SQL + filestore + additional paths)
  - YAML configuration; 7z/zip/gzip/zstd compression; optional GPG encryption (`.7z.gpg`, primary) with fallback to 7z-internal AES (only if `gnupg` is absent)
  - Automatic cleanup of old backups; cron-safe (aborts cleanly and non-interactively on path issues)
  ```yaml
  # Example container2backup.yaml
  defaults:
    retention_days: 14
    db_user: ownerp
    compression:
      format: "7z"  # 7z, zip, gzip, zstd
      level: 5      # Compression level (0-9)
  ```
  → Detailed docs: [scripts/README_BackUp.md](scripts/README_BackUp.md)

- **restore-zip.sh** (v2.x) — restore from the backups produced by container2backup.py; auto-detects the format (`.zip`, `.7z`, `.7z.gpg`, `.tar.gz`, `.tar.zst`)
- **update_docker_odoo.py** (v5.11.x) — automated Docker container updates incl. restart management; per-container option `db_password_via_env: true` in `docker2update.yaml` passes the DB password via `PGPASSWORD` environment variable instead of `--db_password=...` in argv (prevents exposure in `ps aux`); default: `false` (legacy mode for older images). Without `-v` the output stays terse; every warning and error of the whole run is collected in a closing block. Independently of that, every run writes a full log into the instance's build folder (`update_YYYYMMDD_HHMMSS.log`) — including the INFO lines the console withholds; the paths are named at the end, after an abort or a failure too
  - Picking systems for a single run without touching the YAML: `-s` takes several names (repeated or comma-separated), `--type M|F|N` overrides the mode for that run, `--comment "…"` records why it happened. **`-s` overrides `active: false`** — a container named explicitly runs even when the configuration has it parked; an unknown name aborts instead of silently doing nothing
  - Every container run appends a line to `~/update-history.jsonl`: when, which system, which mode, result, duration, log path and comment. Written by the script itself, so classic and cron runs are recorded too. Retention via `defaults.history_retention_days` (365 days by default, `0` = keep forever)

- **ownerp_tui.py** (v1.1.0) — selection screen for ad-hoc updates, started with `tui`. Lists every system from `docker2update.yaml` with its mode and its last run; Space selects, `m` cycles the mode (M/F/N), `c` records a comment, `w` calls the assistant `ownerp_wizard.py` and reloads the list afterwards, Enter starts. **The YAML is never modified** — `active:` and `type:` are the pre-selection, the run itself is passed as arguments to `update_docker_odoo.py`; there is nothing to turn back afterwards. A Neutralize (`N`) in the selection requires a second confirmation naming the affected databases. Without a terminal, on `TERM=dumb`, or below 80×20 characters the screen refuses to start with a plain sentence — no cron job can end up waiting in it
- **odoo_build_cache.py** (v1.5.x) — host-side cache of the release archives under `/opt/odoo-build-cache`, shared by every instance on the same release: a build downloads only what actually changed. Never blocks a build — whatever the cache does not supply, `build_odoo.py` fetches itself as before. Also maintains the build folder's Dockerfile and `odoo.conf`, which nothing else updates: absent image directives (`HEALTHCHECK`, `VOLUME`, `EXPOSE`) are filled in, an `ADD` is aligned with the reference's `COPY` where the two do the same thing, and unset managed config keys (`http_interface`) are taken from the template — passwords are never touched, anything that merely differs is reported. `stats` shows the size, `gc` cleans up after 30 days (maintenance cron)
- **ownerp_validate.py** (v1.0.0) — read-only validation of `docker2update.yaml` and `container2backup.yaml` against their declared schema, started with `doval`. Checks required fields, types, port form (`11000`, `"11000"`, `"127.0.0.1:11000"`, `"[::1]:11000"`), duplicate container/database names and duplicate host ports (**among active entries only**), whether configured paths exist (warning), and unknown keys with a suggestion for the closest known name (also a warning). A block with `active: false` is checked in full, but its findings are downgraded to warnings prefixed `(inactive)` — a parked block never turns the exit code red. Never writes, never prints the value of a key whose name ends in `password`. **Exit code**: `0` no errors (warnings may be present and never affect the exit code), `1` at least one error, `2` a file is missing, unreadable, unparseable, or PyYAML is absent. `update_docker_odoo.py --validate` and `container2backup.py --validate` both call it internally
- **ownerp_wizard.py** (v1.0.0) — guided editing of `docker2update.yaml`, started with `wiz`: add an instance, or change a single field of an existing entry. It reads the configuration before it asks anything and proposes values from it — the next free host port (across **both** port fields of **every** entry, active or not), a `db_user`/`db_host` the existing entries agree on, the shared build-folder pattern with the new name substituted, the shared image-name prefix. A suggestion sits in brackets and is taken with Enter; where the entries disagree it suggests nothing rather than guessing. **The only tool in this set that writes to a customer configuration** — which is why the write path is the substance: a backup to `<path>.bak-<YYYYmmdd_HHMMSS>` → the new text built in memory → a temporary file **in the same directory** → `ownerp_validate.py` run against that file → **any error: the temporary file *and* the backup are removed and the original is left byte-identical** → **clean: `os.replace()`**, and the backup stays. Warnings never block, because a build folder that does not exist yet is the normal state for a new instance. It **refuses rather than guesses**: without a terminal (naming `edup`), without `ownerp_validate.py` beside it (naming `ups`), on a configuration that does not parse (pointing at `doval`). A duplicate container or database name is rejected at the prompt, not at validation. It edits **scalars only** (`pre_build_files` and `proxy` are shown, never changed) and **never removes an entry**. `db_password` is never suggested, never echoed (`getpass`), and appears as `********` in every summary. Its one write outside the YAML is the empty build folder it offers to create — nothing is copied into it; populating a build folder belongs to `odoo_build_cache.py`
- **cleanup-weblogs.py** (v2.x) — DSGVO-compliant nginx log rotation: rotates `/var/log/nginx/*.log` and deletes `.bak` older than 7 days (access logs contain personal IP data)
- **nightly-cleanup.sh** — memory-based container restart above a threshold → [scripts/NIGHTLY_CLEANUP.md](scripts/NIGHTLY_CLEANUP.md)
- **setup-maintenance-cron.sh** — installs the maintenance cron jobs declaratively as `/etc/cron.d/myodoo-maintenance` plus a matching logrotate config (idempotent, `--remove` to uninstall)
- **server-readiness.py** (v1.0.0) — answers "is this server up to date, and what is still missing?" with a traffic-light list of 13 checks (maintenance cron, logrotate, duplicate cron entries, log sizes, backup age/config/disk space, Docker storage driver, nginx systemd drop-in, certbot window, script staleness). Every finding carries exactly one copy-paste fix command. **Read-only** — changes nothing. Runs automatically at the end of every `ups` run (`--brief`), on demand via `chk`, and weekly on Mondays at 06:00 via cron (`--quiet`, speaks up only on drift)
- **nginx-cert-guard.py** — prevents a full nginx outage when a customer's (sub)domain stops pointing at the server. `--reconcile` always brings nginx up at renewal, isolating only the broken vhost (instead of one missing certificate taking the whole server down); `--check` proactively detects drifted domains via DNS and disables them after several confirmed failing runs plus an alert email. Includes a mass-failure guard (no blind shutdown). Re-enable with `--restore <domain>`
- **deploy-nginx-base.sh** — rolls out the base nginx files every vhost needs (`nginxconfig.io/security.conf`, `general.conf`, `html/custom_50x.html`) to `/etc/nginx`, and replaces `nginx.conf` safely (backup + `nginx -t` + automatic rollback on failure). Run it **before** creating vhosts so `include nginxconfig.io/...` never fails. Idempotent; `--no-main-conf`, `--dry-run`

#### 3. Shell Configuration (since Version 7.0)

**Fish Shell** is the primary shell with Starship Prompt.

```
fish/
├── config.fish              # Entry point
├── conf.d/
│   ├── 00-env.fish         # Environment variables
│   ├── 10-path.fish        # PATH configuration
│   ├── 20-tools.fish       # Zoxide, Starship init
│   ├── 30-aliases-*.fish   # Domain-specific aliases
│   └── 50-prompt.fish      # Startup behavior
└── functions/linux/        # Linux-specific functions
```

**Starship Prompt** shows: username/hostname, Git branch and status, Docker context, Python/Node.js/Rust versions, command duration (>2s).

#### 4. System Configurations

- Nginx configurations for reverse proxy
- Let's Encrypt SSL integration via certbot (renewal standalone through `ssl-renew.sh`)
- Docker build configurations

#### 5. Security Features

- Layered server hardening via `server_hardening.py`: UFW firewall, fail2ban, SSH hardening (`sshd_config`), kernel parameters (`sysctl`), kernel module blacklist, Docker daemon hardening, auditd and AIDE (file integrity)
- Automatic security updates (unattended-upgrades)
- Encrypted backups (AES-256, 7z)
- Automatic SSL certificate renewal (with nginx outage protection via `nginx-cert-guard.py`)
- DSGVO/GDPR-compliant weblog cleanup (7-day retention)
- DNS optimization for better performance

#### 6. Shell Aliases & Functions

The Fish configuration ships ~80 aliases and functions. The most important are below — the **full reference** lives in [fish/README.md](fish/README.md).

> **Note:** `syspatch`, `ups`, `chk`, `dkrm`, `dkrmi`, `dkrmv` are **functions** (with logic/confirmation), not plain aliases.

##### System (functions & aliases)
- `syspatch` *(function)* — comprehensive system update + cleanup (incl. AIDE baseline)
- `ups` *(function)* — update ownERP scripts from the repository
- `chk` *(function)* — readiness report: is the server up to date, what is missing? (read-only)
- `prepatch` — prepare a system update in a screen session
- `cleandlog` — clear Docker container logs
- `dusort` — show directory sizes sorted
- `f2b` — `fail2ban-client status`
- `fishcfg` — edit the Fish configuration

##### ownERP / Backup
- `dobk` — run the backup script (`container2backup.py`)
- `edbk` — edit the backup configuration (`container2backup.yaml`)
- `tui` — selection screen for updates (`ownerp_tui.py`): pick system, mode and comment, then start
- `doup` *(function)* — update Docker containers (`update_docker_odoo.py`). Starts the screen instead of the script once `~/.ownerp_tui_default` exists (toggled with `d` inside the screen) — but only without arguments and only in an interactive shell. With arguments, or without a terminal, the script always runs
- `edup` — edit the update configuration (`docker2update.yaml`)
- `doval` — validate both YAML configurations (`ownerp_validate.py`): read-only, exit code `0`/`1`/`2`, warnings do not count
- `wiz` — add an instance or change a field (`ownerp_wizard.py`): guided, with suggestions drawn from the existing configuration. Validates before it replaces anything; refuses without a terminal; never removes an entry. Inside the `tui` screen the same assistant is the `w` key
- `llbk` / `cdbk` / `cpbk` — list / cd into / copy from the backup directory `/opt/backups/docker`

##### Nginx
- `cdngx` — change to the configuration directory
- `ngx+` / `ngx-` / `ngx#` / `ngxr` / `ngxs` — nginx start / stop / restart / reload / status
- `ngx!` / `ngxl` — configuration test
- `ngxset` — set the configuration via `nginx-set-conf`
- `showcerts` — `certbot certificates`

##### Docker
- `dk` — shortcut for `docker`
- `dps` / `dpsall` — list containers in a clear format
- `dpi` — show images
- `dkvol` — check Docker volumes (`check_docker_volumes.sh`)
- `dkstop` — stop all containers
- `dkrm` / `dkrmi` / `dkrmv` *(functions)* — remove all containers / images / volumes (with confirmation)
- `dkprs` / `dkprv` / `dkprf` / `dkprfa` — clean Docker system/volumes
- `dco` / `dcup` / `dcdown` / `dclogs` / `dcps` — `docker compose` shortcuts
- `ct` — shortcut for `ctop`

##### Further categories
- **Git** (`g`, `gst`, `gco`, `gcm`, `gp`, `gl`, `glog` …) — see fish/README.md
- **Odoo** (`odoo-shell`, `odoo-logs`, `odoo-restart`, `pg-shell`) — see fish/README.md

#### 7. DNS Optimization

```bash
./getScripts.py            # DNS optimization as part of installation
./getScripts.py --dns-check # Run DNS check only
```

**Detected Issues:** Hetzner DNS servers may cause issues with DigitalOcean servers; slow resolution (>50ms); suboptimal configuration.

**Recommended DNS Servers:** 1.1.1.1 (Cloudflare), 8.8.8.8 (Google), 9.9.9.9 (Quad9).

### Branch Management

```bash
# Switch to a specific version (e.g., 2026)
cd $HOME && rm -rf myodoo-docker && rm -rf nginx-conf && \
  git clone -b 2026 https://github.com/equitania/myodoo-docker.git && \
  cp myodoo-docker/getScripts.py $HOME && \
  $HOME/getScripts.py && source ~/.config/fish/config.fish
```

### Further Documentation

- **[docs/INSTALLATION_GUIDE.md](docs/INSTALLATION_GUIDE.md) — the thread: fresh server → Odoo live/test in ten steps (DE/EN), each step linking into the guide that covers it**

The guides themselves sit one per task in [docs/usage/](docs/usage/) — each
bilingual, each readable on its own:

| Guide | What it covers |
|---|---|
| [01 Provisioning and Hardening](docs/usage/01-provisioning.md) | Overview, prerequisites, `bootstrap.sh`, `getScripts.py`, `server_hardening.py` |
| [02 nginx and Certificates](docs/usage/02-nginx-certs.md) | Base files, vhosts via the wizard, Let's Encrypt, reachability |
| [03 PostgreSQL and the Odoo Containers](docs/usage/03-postgres-odoo.md) | `pg-local-deploy.sh`, build folders, first start of live and test |
| [04 Setting Up and Running Updates](docs/usage/04-updates.md) | `edup`, `doup`, the `tui` selection screen, the `wiz` assistant, run history |
| [05 Backup and Restore](docs/usage/05-backup-restore.md) | `edbk`, `dobk`, retention, encryption, restoring, emergencies |
| [06 Maintenance and Optional Components](docs/usage/06-maintenance.md) | Maintenance cron, readiness check, FastReport, Debian major upgrade |
| [07 Operation Behind an HTTP Proxy](docs/usage/07-proxy.md) | Servers that may only reach the internet through a corporate proxy |
| [08 Troubleshooting](docs/usage/08-troubleshooting.md) | Symptom → cause → fix, including the Docker ≥ 29 traps |
| [09 Script and Shell Reference](docs/usage/09-reference.md) | Every script with its invocation, every fish alias by category |

- [scripts/README_BackUp.md](scripts/README_BackUp.md) — backup system (configuration, compression, automation)
- [scripts/README_pg-local-deploy.md](scripts/README_pg-local-deploy.md) — PostgreSQL container deployment (profiles, self-signed SSL)
- [scripts/NIGHTLY_CLEANUP.md](scripts/NIGHTLY_CLEANUP.md) — memory-based container restart
- [fish/README.md](fish/README.md) — complete alias/function reference
- [docs/MANUAL_DOCKER_UPDATE_GUIDE.md](docs/MANUAL_DOCKER_UPDATE_GUIDE.md) — manual container update (fallback)

#### Scripts at a Glance

| Task | Command / script | Details |
|---|---|---|
| Initialize a server | `bootstrap.sh` (one-liner) | [Provisioning](docs/usage/01-provisioning.md#en-3-step-1-bootstrap) |
| Install shell & scripts | `./getScripts.py` | [Provisioning](docs/usage/01-provisioning.md#en-4-step-2-getscriptspy) |
| Harden the server | `sudo python3 server_hardening.py --apply` | [Provisioning](docs/usage/01-provisioning.md#en-5-step-3-server-hardening) |
| nginx base + vhosts | `deploy-nginx-base.sh`, `ngx-conf-wizard.sh`, `ngxset` | [nginx & certificates](docs/usage/02-nginx-certs.md#en-6-step-4-nginx-base--vhosts) |
| Deploy PostgreSQL | `pg-local-deploy.sh` | [PostgreSQL & Odoo](docs/usage/03-postgres-odoo.md#en-7-step-5-postgresql-live-dbtest-db) |
| Start Odoo containers | `docker run … start` | [PostgreSQL & Odoo](docs/usage/03-postgres-odoo.md#en-8-step-6-first-start-of-the-odoo-containers) |
| Updates | `edup` (config) / `doup` (run) / `tui` (selection screen) | [Updates](docs/usage/04-updates.md#en-10-step-8-set-up-updates-edupdoup) |
| Add an instance | `wiz` (guided, validates before writing) | [Updates](docs/usage/04-updates.md#en-10-step-8-set-up-updates-edupdoup) |
| Backups | `edbk` (config) / `dobk` (run) / `llbk` | [Backup & restore](docs/usage/05-backup-restore.md#en-11-step-9-set-up-backups-edbkdobk) |
| Validate configuration | `doval` (both YAMLs, read-only) | [Backup & restore](docs/usage/05-backup-restore.md#en-11-step-9-set-up-backups-edbkdobk) |
| Maintenance cron | `setup-maintenance-cron.sh` | [Maintenance](docs/usage/06-maintenance.md#en-12-step-10-automate-maintenance) |
| Restore | `restore-zip.sh` | [Backup & restore](docs/usage/05-backup-restore.md#en-13-restore--emergency) |
| Set up a proxy environment | `./getScripts.py --proxy-check` | [Proxy](docs/usage/07-proxy.md#en-18-operation-behind-an-http-proxy) |
| All 17 scripts + usages | — | [Reference](docs/usage/09-reference.md#en-14-script-reference) |

---

For more information:
- [ownERP.com](https://www.ownerp.com)
