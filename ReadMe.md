# Myodoo-Docker

(c) 2016 till now by Equitania Software GmbH

[🇩🇪 Deutsch](#deutsch) | [🇬🇧 English](#english)

<a name="deutsch"></a>
## Deutsch

### Über dieses Repository

Dieses Repository enthält eine Sammlung von Docker-Konfigurationen und Verwaltungsskripten für Odoo-Installationen. Es wird täglich in der professionellen Administration von Kundensystemen eingesetzt.

### Schnellstart

```bash
# Erstmalige Installation
git clone https://github.com/equitania/myodoo-docker.git
cp myodoo-docker/getScripts.py /root/
./getScripts.py

# DNS-Optimierung (eigenständig)
./getScripts.py --dns-check
```

### Hauptkomponenten

#### 1. Verwaltungsskripte

- **getScripts.py**
  - Hauptinstallationsskript (Version 7.x)
  - Installiert Fish Shell mit Starship Prompt
  - Installiert alle benötigten Werkzeuge und Abhängigkeiten
  - Aktualisiert bestehende Installationen
  - DNS-Konfigurationsprüfung und -optimierung
  - Erkennt Hetzner-DNS-Probleme mit DigitalOcean
  - Unterstützt systemd-resolved, resolvconf und direkte DNS-Konfiguration

- **container2backup.py**
  - Automatisches Backup-System für Odoo-Datenbanken
  - Sichert Datenbank, Filestore und zusätzliche Pfade
  - Konfiguration über YAML-Datei
  - Unterstützt 7z, zip, gzip und zstd Kompression
  - Optionale AES-256 Verschlüsselung (nur 7z)
  - Automatische Bereinigung alter Backups
  ```yaml
  # Beispiel container2backup.yaml
  defaults:
    retention_days: 14
    db_user: ownerp
    compression:
      format: "7z"  # 7z, zip, gzip, zstd
      level: 5      # Kompressionsgrad (0-9)
  ```

- **update_docker_odoo.py**
  - Automatisierte Aktualisierung von Docker-Containern
  - Sicherheitsrelevante Updates
  - Neustart von Diensten

#### 2. Shell-Konfiguration (NEU ab Version 7.0)

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

**Starship Prompt** zeigt:
- Benutzername und Hostname
- Git-Branch und Status
- Docker-Kontext
- Python/Node.js/Rust Versionen
- Befehlsdauer (>2s)

#### 3. Systemkonfigurationen

- Nginx-Konfigurationen für Reverse Proxy
- Let's Encrypt SSL-Integration
- Docker-Build-Konfigurationen

#### 4. Sicherheitsfeatures

- Verschlüsselte Backups (AES-256)
- Automatische SSL-Zertifikatserneuerung
- Sichere Standardkonfigurationen
- DNS-Optimierung für bessere Performance

#### 5. Shell-Aliasse

Die Fish-Konfiguration enthält nützliche Aliasse für die tägliche Arbeit:

##### Grundlegende Aliasse
- `ls` - verbesserte Verzeichnisanzeige
- `ll` - ausführliche Verzeichnisanzeige
- `lg` - Lazygit-Shortcut
- `grep` - Ausgabe mit Farbhervorhebung
- `hg` - History-Suche
- `ff` - Fastfetch ausführen
- `bat` - Alias für batcat

##### Nginx-Aliasse
- `cdngx` - Wechsel ins Nginx-Konfigurationsverzeichnis
- `ngx+` - Nginx starten
- `ngx-` - Nginx stoppen
- `ngx#` - Nginx neu starten
- `ngxr` - Nginx-Konfiguration neu laden
- `ngxs` - Nginx-Status anzeigen
- `ngx!` - Nginx-Konfigurationstest
- `ngxset` - Nginx-Konfiguration setzen
- `showcerts` - Zertifikate anzeigen

##### System-Aliasse
- `syspatch` - Umfassende Systemaktualisierung und Bereinigung
- `prepatch` - Systemupdate in einer Screen-Session vorbereiten
- `cleandlog` - Docker-Logs bereinigen
- `dusort` - Verzeichnisgrößen sortiert anzeigen
- `f2b` - Fail2ban-Client-Status anzeigen
- `ups` - Update der ownERP-Skripte

##### ownERP-Aliasse
- `dobk` - Ausführen des Backup-Skripts
- `doup` - Aktualisieren der Docker-Container
- `edbk` - Backup-Konfiguration bearbeiten (YAML)
- `edup` - Update-Konfiguration bearbeiten (YAML)
- `llbk` - Backup-Verzeichnis auflisten
- `cpbk` - Kopieren aus dem Backup-Verzeichnis

##### Docker-Aliasse
- `dk` - Shortcut für docker
- `dps` - Docker-Container übersichtlich auflisten
- `dpi` - Docker-Images anzeigen
- `dkvol` - Docker-Volumes überprüfen
- `dkstop` - Alle Container stoppen
- `dkrm` - Alle Container entfernen (mit Bestätigung)
- `dkrmi` - Alle Images entfernen (mit Bestätigung)
- `dkrmv` - Alle Docker-Volumes entfernen (mit Bestätigung)
- `dkprs` - Docker-System bereinigen
- `ct` - Shortcut für ctop

#### 6. DNS-Optimierung

**Automatische DNS-Konfigurationsprüfung und -optimierung**

```bash
# DNS-Optimierung als Teil der Installation
./getScripts.py

# Nur DNS-Prüfung durchführen
./getScripts.py --dns-check
```

**Erkannte Probleme:**
- Hetzner-DNS-Server können Probleme mit DigitalOcean-Servern verursachen
- Langsame DNS-Auflösungszeiten (>50ms)
- Suboptimale DNS-Konfiguration

**Empfohlene DNS-Server:**
- Primär: 1.1.1.1 (Cloudflare)
- Sekundär: 8.8.8.8 (Google)
- Tertiär: 9.9.9.9 (Quad9)

### Branch-Verwaltung

```bash
# Wechsel zu einer spezifischen Version (z.B. 2026)
cd $HOME && rm -rf myodoo-docker && rm -rf nginx-conf && \
  git clone -b 2026 https://github.com/equitania/myodoo-docker.git && \
  cp myodoo-docker/getScripts.py $HOME && \
  $HOME/getScripts.py && source ~/.config/fish/config.fish
```

---

<a name="english"></a>
## English

### About this Repository

This repository contains a collection of Docker configurations and management scripts for Odoo installations. It is used daily in professional customer system administration.

### Quick Start

```bash
# Initial Installation
git clone https://github.com/equitania/myodoo-docker.git
cp myodoo-docker/getScripts.py /root/
./getScripts.py

# DNS optimization (standalone)
./getScripts.py --dns-check
```

### Main Components

#### 1. Management Scripts

- **getScripts.py**
  - Main installation script (Version 7.x)
  - Installs Fish Shell with Starship Prompt
  - Installs all required tools and dependencies
  - Updates existing installations
  - DNS configuration check and optimization
  - Detects Hetzner DNS issues with DigitalOcean
  - Supports systemd-resolved, resolvconf, and direct DNS configuration

- **container2backup.py**
  - Automatic backup system for Odoo databases
  - Backs up database, filestore, and additional paths
  - Configuration via YAML file
  - Supports 7z, zip, gzip and zstd compression
  - Optional AES-256 encryption (7z only)
  - Automatic cleanup of old backups
  ```yaml
  # Example container2backup.yaml
  defaults:
    retention_days: 14
    db_user: ownerp
    compression:
      format: "7z"  # 7z, zip, gzip, zstd
      level: 5      # Compression level (0-9)
  ```

- **update_docker_odoo.py**
  - Automated Docker container updates
  - Security-relevant updates
  - Service restart management

#### 2. Shell Configuration (NEW in Version 7.0)

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

**Starship Prompt** shows:
- Username and hostname
- Git branch and status
- Docker context
- Python/Node.js/Rust versions
- Command duration (>2s)

#### 3. System Configurations

- Nginx configurations for reverse proxy
- Let's Encrypt SSL integration
- Docker build configurations

#### 4. Security Features

- Encrypted backups (AES-256)
- Automatic SSL certificate renewal
- Secure default configurations
- DNS optimization for better performance

#### 5. Shell Aliases

The Fish configuration includes useful aliases for daily work:

##### Basic Aliases
- `ls` - enhanced directory listing
- `ll` - detailed directory listing
- `lg` - lazygit shortcut
- `grep` - output with color highlighting
- `hg` - history search
- `ff` - run fastfetch
- `bat` - alias for batcat

##### Nginx Aliases
- `cdngx` - change to nginx configuration directory
- `ngx+` - start nginx
- `ngx-` - stop nginx
- `ngx#` - restart nginx
- `ngxr` - reload nginx configuration
- `ngxs` - show nginx status
- `ngx!` - test nginx configuration
- `ngxset` - set nginx configuration
- `showcerts` - show certificates

##### System Aliases
- `syspatch` - comprehensive system update and cleanup
- `prepatch` - prepare system update in a screen session
- `cleandlog` - clean docker logs
- `dusort` - show directory sizes sorted
- `f2b` - show fail2ban client status
- `ups` - update ownERP scripts

##### ownERP Aliases
- `dobk` - run backup script
- `doup` - update docker containers
- `edbk` - edit backup configuration (YAML)
- `edup` - edit update configuration (YAML)
- `llbk` - list backup directory
- `cpbk` - copy from backup directory

##### Docker Aliases
- `dk` - shortcut for docker
- `dps` - list docker containers in a clear format
- `dpi` - show docker images
- `dkvol` - check docker volumes
- `dkstop` - stop all containers
- `dkrm` - remove all containers (with confirmation)
- `dkrmi` - remove all images (with confirmation)
- `dkrmv` - remove all docker volumes (with confirmation)
- `dkprs` - clean docker system
- `ct` - shortcut for ctop

#### 6. DNS Optimization

**Automatic DNS Configuration Check and Optimization**

```bash
# DNS optimization as part of installation
./getScripts.py

# Run DNS check only
./getScripts.py --dns-check
```

**Detected Issues:**
- Hetzner DNS servers may cause issues with DigitalOcean servers
- Slow DNS resolution times (>50ms)
- Suboptimal DNS configuration

**Recommended DNS Servers:**
- Primary: 1.1.1.1 (Cloudflare)
- Secondary: 8.8.8.8 (Google)
- Tertiary: 9.9.9.9 (Quad9)

### Branch Management

```bash
# Switch to a specific version (e.g., 2026)
cd $HOME && rm -rf myodoo-docker && rm -rf nginx-conf && \
  git clone -b 2026 https://github.com/equitania/myodoo-docker.git && \
  cp myodoo-docker/getScripts.py $HOME && \
  $HOME/getScripts.py && source ~/.config/fish/config.fish
```

---

For more information:
- [ownERP.com](https://www.ownerp.com)
