# Myodoo-Docker

(c) 2016 till now by Equitania Software GmbH

[🇩🇪 Deutsch](#deutsch) | [🇬🇧 English](#english)

<a name="deutsch"></a>
## Deutsch

### Über dieses Repository

Dieses Repository enthält eine Sammlung von Docker-Konfigurationen und Verwaltungsskripten für Odoo-Installationen. Es wird täglich in der professionellen Administration von Kundensystemen eingesetzt — vom Provisionieren eines frischen Servers über die Härtung bis zu Backup, SSL und Wartung.

### Schnellstart

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
- **update_docker_odoo.py** (v5.2.x) — automatisierte Aktualisierung von Docker-Containern inkl. Neustart-Management; neue Option `db_password_via_env: true` pro Container in `docker2update.yaml` übergibt das DB-Passwort via `PGPASSWORD`-Umgebungsvariable statt als `--db_password=...` in argv (verhindert Sichtbarkeit in `ps aux`); Standard: `false` (Legacy-Modus für ältere Images)
- **cleanup-weblogs.py** (v2.x) — DSGVO-konforme nginx-Log-Rotation: rotiert `/var/log/nginx/*.log` und löscht `.bak` älter als 7 Tage (Access-Logs enthalten personenbezogene IP-Adressen)
- **nightly-cleanup.sh** — speicherbasierter Container-Neustart bei Überschreiten einer Schwelle → [scripts/NIGHTLY_CLEANUP.md](scripts/NIGHTLY_CLEANUP.md)
- **setup-maintenance-cron.sh** — installiert die Wartungs-Cron-Jobs deklarativ als `/etc/cron.d/myodoo-maintenance` plus passende logrotate-Konfiguration (idempotent, `--remove` zum Entfernen)
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

> **Hinweis:** `syspatch`, `ups`, `dkrm`, `dkrmi`, `dkrmv` sind **Funktionen** (mit Logik/Bestätigung), keine einfachen Aliase.

##### System (Funktionen & Aliase)
- `syspatch` *(Funktion)* — umfassende Systemaktualisierung + Bereinigung (inkl. AIDE-Baseline)
- `ups` *(Funktion)* — ownERP-Skripte aus dem Repository aktualisieren
- `prepatch` — Systemupdate in einer Screen-Session vorbereiten
- `cleandlog` — Docker-Container-Logs leeren
- `dusort` — Verzeichnisgrößen sortiert anzeigen
- `f2b` — `fail2ban-client status`
- `fishcfg` — Fish-Konfiguration bearbeiten

##### ownERP / Backup
- `dobk` — Backup-Skript ausführen (`container2backup.py`)
- `edbk` — Backup-Konfiguration bearbeiten (`container2backup.yaml`)
- `doup` — Docker-Container aktualisieren (`update_docker_odoo.py`)
- `edup` — Update-Konfiguration bearbeiten (`docker2update.yaml`)
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

- [scripts/README_BackUp.md](scripts/README_BackUp.md) — Backup-System (Konfiguration, Kompression, Automatisierung)
- [scripts/NIGHTLY_CLEANUP.md](scripts/NIGHTLY_CLEANUP.md) — speicherbasierter Container-Neustart
- [fish/README.md](fish/README.md) — vollständige Alias-/Funktionsreferenz
- [docs/MANUAL_DOCKER_UPDATE_GUIDE.md](docs/MANUAL_DOCKER_UPDATE_GUIDE.md) — manuelles Container-Update (Fallback)

---

<a name="english"></a>
## English

### About this Repository

This repository contains a collection of Docker configurations and management scripts for Odoo installations. It is used daily in professional customer system administration — from provisioning a fresh server through hardening to backup, SSL, and maintenance.

### Quick Start

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
- **update_docker_odoo.py** (v5.2.x) — automated Docker container updates incl. restart management; new per-container option `db_password_via_env: true` in `docker2update.yaml` passes the DB password via `PGPASSWORD` environment variable instead of `--db_password=...` in argv (prevents exposure in `ps aux`); default: `false` (legacy mode for older images)
- **cleanup-weblogs.py** (v2.x) — DSGVO-compliant nginx log rotation: rotates `/var/log/nginx/*.log` and deletes `.bak` older than 7 days (access logs contain personal IP data)
- **nightly-cleanup.sh** — memory-based container restart above a threshold → [scripts/NIGHTLY_CLEANUP.md](scripts/NIGHTLY_CLEANUP.md)
- **setup-maintenance-cron.sh** — installs the maintenance cron jobs declaratively as `/etc/cron.d/myodoo-maintenance` plus a matching logrotate config (idempotent, `--remove` to uninstall)
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

> **Note:** `syspatch`, `ups`, `dkrm`, `dkrmi`, `dkrmv` are **functions** (with logic/confirmation), not plain aliases.

##### System (functions & aliases)
- `syspatch` *(function)* — comprehensive system update + cleanup (incl. AIDE baseline)
- `ups` *(function)* — update ownERP scripts from the repository
- `prepatch` — prepare a system update in a screen session
- `cleandlog` — clear Docker container logs
- `dusort` — show directory sizes sorted
- `f2b` — `fail2ban-client status`
- `fishcfg` — edit the Fish configuration

##### ownERP / Backup
- `dobk` — run the backup script (`container2backup.py`)
- `edbk` — edit the backup configuration (`container2backup.yaml`)
- `doup` — update Docker containers (`update_docker_odoo.py`)
- `edup` — edit the update configuration (`docker2update.yaml`)
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

- [scripts/README_BackUp.md](scripts/README_BackUp.md) — backup system (configuration, compression, automation)
- [scripts/NIGHTLY_CLEANUP.md](scripts/NIGHTLY_CLEANUP.md) — memory-based container restart
- [fish/README.md](fish/README.md) — complete alias/function reference
- [docs/MANUAL_DOCKER_UPDATE_GUIDE.md](docs/MANUAL_DOCKER_UPDATE_GUIDE.md) — manual container update (fallback)

---

For more information:
- [ownERP.com](https://www.ownerp.com)
