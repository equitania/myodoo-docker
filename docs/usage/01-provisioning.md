# Provisionierung und Härtung / Provisioning and Hardening

Teil der [Server-Installationsanleitung](../INSTALLATION_GUIDE.md) · Part of the [server installation guide](../INSTALLATION_GUIDE.md)

[🇩🇪 Deutsch](#deutsch) | [🇬🇧 English](#english)

---

<a id="deutsch"></a>
# Provisionierung und Härtung

<a id="de-1-überblick--architektur"></a>
## Überblick & Architektur

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
## Voraussetzungen

- **OS:** Debian 12/13 oder Ubuntu 20.04–26.04, frisch installiert, Root-Zugang
- **DNS:** A-Records für `erp-live.example.com` / `erp-test.example.com` auf die öffentliche IP
- **Bei NAT** (Server steht hinter einer Firewall mit privater IP):
  - Firewall-Forwarding **TCP 443 und TCP 80** auf die interne Server-IP.
    Port 80 muss **dauerhaft** offen bleiben (Let's-Encrypt-Renewal!)
  - Interne Clients: siehe [Troubleshooting → Split-DNS](08-troubleshooting.md#de-16-troubleshooting)
- **Odoo-Image:** eigenes Registry-Image oder Build-Verzeichnis nach
  `Dockerfiles/v19-odoo/ReadMe.md` (Dockerfile, `build_odoo.py`, `release.file`,
  `odoo.conf`, `bin/boot`)

> ℹ️ **Die Server-Shell ist fish.** `getScripts.py` installiert fish als
> Standard-Shell. Für Copy-Paste-Blöcke gilt: `$status` statt `$?`,
> `set VAR wert` statt `VAR=wert`, keine Heredocs. Bash-Skripte laufen
> natürlich weiterhin per `./script.sh` oder `bash -c '…'`.

<a id="de-3-schritt-1-bootstrap"></a>
## Schritt 1: Bootstrap

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
> aufgesetzt wurden: Symptome und Heilung siehe [Troubleshooting](08-troubleshooting.md#de-16-troubleshooting).

<a id="de-4-schritt-2-getscriptspy"></a>
## Schritt 2: getScripts.py

Installiert die fish-Shell-Konfiguration, alle Aliase/Funktionen und die
Verwaltungsskripte (inkl. `container2backup.py`, `update_docker_odoo.py`)
nach `/root`. Wird vom Bootstrap automatisch ausgeführt; manuell:

```bash
/root/getScripts.py                 # Installation / Update (schlanke Ausgabe)
/root/getScripts.py -v              # dasselbe, mit jedem Schritt und jeder Befehlsausgabe
/root/getScripts.py --dns-check     # DNS-Konfiguration pruefen/optimieren
/root/getScripts.py --proxy-check   # Docker-Daemon-Proxy einrichten (Proxy-Kunden)
/root/getScripts.py --reconfigure   # First-Run-Einstellungen erneut abfragen
```

Danach neue Shell öffnen (oder `source ~/.config/fish/config.fish`) — die
Aliase aus [Kapitel 15](09-reference.md#de-15-shell-referenz-fish) stehen bereit. Später
aktualisieren mit `ups`.

> ⚠️ **Erfahrungswert (sudo su):** Wer sich mit einem persönlichen
> Admin-Account anmeldet und per `sudo su` zu root wird, braucht
> getScripts.py ≥ 9.7.3 — ältere Versionen installierten in diesem Fall ins
> falsche Home-Verzeichnis (Aliase fehlten für root).

<a id="de-5-schritt-3-server-härtung"></a>
## Schritt 3: Server-Härtung

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

---

<a id="english"></a>
# Provisioning and Hardening

<a id="en-1-overview--architecture"></a>
## Overview & Architecture

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
## Prerequisites

- **OS:** Debian 12/13 or Ubuntu 20.04–26.04, freshly installed, root access
- **DNS:** A records for `erp-live.example.com` / `erp-test.example.com` pointing to the public IP
- **Behind NAT** (server has a private IP behind a firewall):
  - Firewall forwarding of **TCP 443 and TCP 80** to the internal server IP.
    Port 80 must stay open **permanently** (Let's Encrypt renewal!)
  - Internal clients: see [Troubleshooting → split DNS](08-troubleshooting.md#en-16-troubleshooting)
- **Odoo image:** your own registry image or a build directory following
  `Dockerfiles/v19-odoo/ReadMe.md` (Dockerfile, `build_odoo.py`, `release.file`,
  `odoo.conf`, `bin/boot`)

> ℹ️ **The server shell is fish.** `getScripts.py` installs fish as the
> default shell. For copy-paste blocks: `$status` instead of `$?`,
> `set VAR value` instead of `VAR=value`, no heredocs. Bash scripts still run
> fine via `./script.sh` or `bash -c '…'`.

<a id="en-3-step-1-bootstrap"></a>
## Step 1: Bootstrap

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
> bootstrap: symptoms and cure in [Troubleshooting](08-troubleshooting.md#en-16-troubleshooting).

<a id="en-4-step-2-getscriptspy"></a>
## Step 2: getScripts.py

Installs the fish shell configuration, all aliases/functions and the
management scripts (including `container2backup.py`, `update_docker_odoo.py`)
into `/root`. Executed automatically by bootstrap; manually:

```bash
/root/getScripts.py                 # install / update (lean output)
/root/getScripts.py -v              # the same, with every step and all command output
/root/getScripts.py --dns-check     # check/optimize DNS configuration
/root/getScripts.py --proxy-check   # set up Docker daemon proxy (proxy customers)
/root/getScripts.py --reconfigure   # re-run first-run configuration
```

Then open a new shell (or `source ~/.config/fish/config.fish`) — the aliases
from [chapter 15](09-reference.md#en-15-shell-reference-fish) are available. Update later
with `ups`.

> ⚠️ **Lesson learned (sudo su):** Operators who log in with a personal admin
> account and become root via `sudo su` need getScripts.py ≥ 9.7.3 — older
> versions installed into the wrong home directory in that case (root's
> shell had no aliases).

<a id="en-5-step-3-server-hardening"></a>
## Step 3: Server Hardening

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
