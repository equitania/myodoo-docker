# Server Installation Guide — Odoo live/test under Docker

Version 2.0.0 — 12.08.2026

[🇩🇪 Deutsche Version](#deutsche-version) | [🇬🇧 English Version](#english-version)

---

<a id="deutsche-version"></a>
# Deutsche Version

Der rote Faden von einem frisch installierten Debian-/Ubuntu-Server bis zu
zwei produktiv laufenden Odoo-Systemen (live/test) hinter nginx mit
Let's-Encrypt-SSL, automatischen Updates (`doup`) und Backups (`dobk`).

**Diese Seite ist die Reihenfolge, nicht das Handbuch.** Jeder Schritt steht
hier in zwei, drei Sätzen; die vollständige Anleitung mit allen Befehlen,
Konfigurationsbeispielen und Fallstricken liegt daneben in
[usage/](usage/) — eine Datei je Aufgabe. Wer nur ein Backup einrichten oder
eine Instanz nachtragen will, springt direkt dorthin und liest den Rest nicht.

Alle Beispiele sind neutral gehalten — ersetze Domains, IPs und Passwörter
durch eure Werte.

**Verwendete Platzhalter:**

| Platzhalter | Bedeutung |
|---|---|
| `erp-live.example.com` / `erp-test.example.com` | Öffentliche Domains der beiden Systeme |
| `203.0.113.10` | Öffentliche IP (DNS-A-Record) |
| `192.168.1.50` | Interne Server-IP (nur bei NAT relevant) |
| `live-odoo` / `test-odoo`, `live-db` / `test-db` | Container-Namen |
| `odoo/live`, `odoo/test` | Docker-Image-Namen |
| `proxy.example.com:8080` | HTTP-Proxy des Kunden (nur [Betrieb hinter HTTP-Proxy](usage/07-proxy.md)) |

## Die Anleitungen

| Datei | Worum es geht |
|---|---|
| [01 Provisionierung und Härtung](usage/01-provisioning.md) | Überblick, Voraussetzungen, `bootstrap.sh`, `getScripts.py`, `server_hardening.py` |
| [02 nginx und Zertifikate](usage/02-nginx-certs.md) | nginx-Basisdateien, Vhosts per Wizard, Let's Encrypt, Erreichbarkeit |
| [03 PostgreSQL und Odoo-Container](usage/03-postgres-odoo.md) | `pg-local-deploy.sh`, Build-Ordner, Erststart von live und test |
| [04 Updates einrichten und fahren](usage/04-updates.md) | `edup`, `doup`, die Konsole `konsole`, der Assistent `wiz`, Laufhistorie |
| [05 Backup und Restore](usage/05-backup-restore.md) | `edbk`, `dobk`, Aufbewahrung, Verschlüsselung, Wiederherstellung, Notfall |
| [06 Wartung und optionale Komponenten](usage/06-maintenance.md) | Wartungs-Cron, Bereitschaftsprüfung, FastReport, Debian-Major-Upgrade |
| [07 Betrieb hinter HTTP-Proxy](usage/07-proxy.md) | Server, die nur über einen Firmen-Proxy ins Internet dürfen |
| [08 Troubleshooting](usage/08-troubleshooting.md) | Symptom → Ursache → Lösung, inklusive der Docker-≥-29-Fallen |
| [09 Skript- und Shell-Referenz](usage/09-reference.md) | Alle Skripte mit Aufruf, alle fish-Aliase nach Kategorie |

## Der Ablauf

Zehn Schritte, in dieser Reihenfolge. Die Links führen in die jeweilige
Anleitung, genau an die Stelle des Schrittes.

<a id="de-1-überblick--architektur"></a>
<a id="de-2-voraussetzungen"></a>
### Vorher: Überblick und Voraussetzungen

Was am Ende läuft (zwei Odoo-Container, zwei PostgreSQL-Container, nginx davor)
und was der Server dafür mitbringen muss — Debian 12/13 oder Ubuntu,
root-Zugang, DNS-Einträge, offene Ports.
→ [01 Provisionierung und Härtung](usage/01-provisioning.md#de-1-überblick--architektur)

<a id="de-3-schritt-1-bootstrap"></a>
### Schritt 1: Bootstrap

Ein Aufruf richtet die Grundausstattung ein: Docker CE (mit `overlay2` als
Storage-Driver), nginx, certbot, UFW, fail2ban und automatische
Sicherheitsupdates. Idempotent, jede Stufe abschaltbar.
→ [01 Provisionierung und Härtung](usage/01-provisioning.md#de-3-schritt-1-bootstrap)

<a id="de-4-schritt-2-getscriptspy"></a>
### Schritt 2: getScripts.py

Verteilt die Fish-Shell samt Aliasen und alle Verwaltungsskripte nach `/root`.
Danach existieren `doup`, `dobk`, `doval`, `konsole`, `dostat` und `wiz` als Befehle.
→ [01 Provisionierung und Härtung](usage/01-provisioning.md#de-4-schritt-2-getscriptspy)

<a id="de-5-schritt-3-server-härtung"></a>
### Schritt 3: Server-Härtung

Erst das Audit ohne `--apply` lesen, dann anwenden: UFW, fail2ban, SSH, sysctl,
auditd, AIDE. Lockout-sicher — die SSH-Konfiguration wird erst getauscht,
nachdem `sshd -t` sie akzeptiert hat.
→ [01 Provisionierung und Härtung](usage/01-provisioning.md#de-5-schritt-3-server-härtung)

<a id="de-6-schritt-4-nginx-basis--vhosts"></a>
### Schritt 4: nginx-Basis und Vhosts

Zuerst die Basisdateien ausrollen, sonst schlägt jedes `include` einer vhost
fehl. Danach die Vhosts über den Wizard erzeugen und ausliefern.
→ [02 nginx und Zertifikate](usage/02-nginx-certs.md#de-6-schritt-4-nginx-basis--vhosts)

<a id="de-7-schritt-5-postgresql-live-dbtest-db"></a>
### Schritt 5: PostgreSQL

Je ein Datenbank-Container für live und test, interaktiv deployt, mit
Ressourcen-Profil und optionalem SSL.
→ [03 PostgreSQL und Odoo-Container](usage/03-postgres-odoo.md#de-7-schritt-5-postgresql-live-dbtest-db)

<a id="de-8-schritt-6-odoo-container-erststarten"></a>
### Schritt 6: Odoo-Container erststarten

Build-Ordner anlegen, Image bauen, Container starten — einmal für live, einmal
für test.
→ [03 PostgreSQL und Odoo-Container](usage/03-postgres-odoo.md#de-8-schritt-6-odoo-container-erststarten)

<a id="de-9-schritt-7-lets-encrypt--erreichbarkeit"></a>
### Schritt 7: Let's Encrypt und Erreichbarkeit

Zertifikate holen, Erreichbarkeit prüfen, den Renewal-Pfad testen.
→ [02 nginx und Zertifikate](usage/02-nginx-certs.md#de-9-schritt-7-lets-encrypt--erreichbarkeit)

<a id="de-10-schritt-8-updates-einrichten-edupdoup"></a>
### Schritt 8: Updates einrichten

`docker2update.yaml` beschreibt jede Instanz, `doup` fährt die Updates. Eine
weitere Instanz trägt man am besten mit `wiz` nach — der Assistent prüft, bevor
er schreibt. `doval` prüft die Konfiguration jederzeit rein lesend.
→ [04 Updates einrichten und fahren](usage/04-updates.md#de-10-schritt-8-updates-einrichten-edupdoup)

<a id="de-11-schritt-9-backups-einrichten-edbkdobk"></a>
### Schritt 9: Backups einrichten

`container2backup.yaml` beschreibt, was gesichert wird, `dobk` führt es aus.
Aufbewahrung, Kompression und Verschlüsselung gehören zur Erstkonfiguration.
→ [05 Backup und Restore](usage/05-backup-restore.md#de-11-schritt-9-backups-einrichten-edbkdobk)

<a id="de-12-schritt-10-wartung-automatisieren"></a>
### Schritt 10: Wartung automatisieren

Ein Aufruf verdrahtet Backup, Zertifikatserneuerung, DSGVO-Log-Bereinigung und
Speicher-Aufräumen in einem Cron-Drop-in. Erst sinnvoll, wenn Schritt 9 steht.
→ [06 Wartung und optionale Komponenten](usage/06-maintenance.md#de-12-schritt-10-wartung-automatisieren)

## Zum Nachschlagen

<a id="de-13-restore--notfall"></a>
### Restore und Notfall

Wiederherstellung aus einem Backup, inklusive Formaterkennung und der
Reihenfolge, in der die Container gestoppt werden.
→ [05 Backup und Restore](usage/05-backup-restore.md#de-13-restore--notfall)

<a id="de-14-skript-referenz"></a>
<a id="de-15-shell-referenz-fish"></a>
### Skript- und Shell-Referenz

Alle Skripte des Repos mit Zweck und Aufruf, alle fish-Aliase nach Kategorie.
→ [09 Skript- und Shell-Referenz](usage/09-reference.md#de-14-skript-referenz)

<a id="de-16-troubleshooting"></a>
### Troubleshooting

Symptom, Ursache, Lösung — darunter die Docker-≥-29-Fallen, bei denen Builds
still hohle Images erzeugen.
→ [08 Troubleshooting](usage/08-troubleshooting.md#de-16-troubleshooting)

<a id="de-17-optionale-komponenten"></a>
### Optionale Komponenten

FastReport-API für die PDF-Erzeugung, geführtes Debian-Major-Upgrade.
→ [06 Wartung und optionale Komponenten](usage/06-maintenance.md#de-17-optionale-komponenten)

<a id="de-18-betrieb-hinter-http-proxy"></a>
### Betrieb hinter HTTP-Proxy

Für Server, die nur über einen Firmen-Proxy ins Internet dürfen — inklusive des
Daemon-Proxys, ohne den jeder Base-Image-Pull scheitert.
→ [07 Betrieb hinter HTTP-Proxy](usage/07-proxy.md#de-18-betrieb-hinter-http-proxy)

---

<a id="english-version"></a>
# English Version

The thread from a freshly installed Debian/Ubuntu server to two production Odoo
systems (live/test) behind nginx with Let's Encrypt SSL, automated updates
(`doup`) and backups (`dobk`).

**This page is the order of things, not the manual.** Each step gets two or
three sentences here; the full instructions — every command, configuration
example and pitfall — sit beside it in [usage/](usage/), one file per task.
Anyone who only wants to set up a backup or add an instance jumps straight
there and reads none of the rest.

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
| `proxy.example.com:8080` | Customer HTTP proxy (only [Operation Behind an HTTP Proxy](usage/07-proxy.md)) |

## The guides

| File | What it covers |
|---|---|
| [01 Provisioning and Hardening](usage/01-provisioning.md) | Overview, prerequisites, `bootstrap.sh`, `getScripts.py`, `server_hardening.py` |
| [02 nginx and Certificates](usage/02-nginx-certs.md) | nginx base files, vhosts via the wizard, Let's Encrypt, reachability |
| [03 PostgreSQL and the Odoo Containers](usage/03-postgres-odoo.md) | `pg-local-deploy.sh`, build folders, first start of live and test |
| [04 Setting Up and Running Updates](usage/04-updates.md) | `edup`, `doup`, the `konsole` console, the `wiz` assistant, run history |
| [05 Backup and Restore](usage/05-backup-restore.md) | `edbk`, `dobk`, retention, encryption, restoring, emergencies |
| [06 Maintenance and Optional Components](usage/06-maintenance.md) | Maintenance cron, readiness check, FastReport, Debian major upgrade |
| [07 Operation Behind an HTTP Proxy](usage/07-proxy.md) | Servers that may only reach the internet through a corporate proxy |
| [08 Troubleshooting](usage/08-troubleshooting.md) | Symptom → cause → fix, including the Docker ≥ 29 traps |
| [09 Script and Shell Reference](usage/09-reference.md) | Every script with its invocation, every fish alias by category |

## The sequence

Ten steps, in this order. Each link lands on that step inside its guide.

<a id="en-1-overview--architecture"></a>
<a id="en-2-prerequisites"></a>
### First: overview and prerequisites

What ends up running (two Odoo containers, two PostgreSQL containers, nginx in
front) and what the server needs for it — Debian 12/13 or Ubuntu, root access,
DNS records, open ports.
→ [01 Provisioning and Hardening](usage/01-provisioning.md#en-1-overview--architecture)

<a id="en-3-step-1-bootstrap"></a>
### Step 1: Bootstrap

One call installs the baseline: Docker CE (with `overlay2` as the storage
driver), nginx, certbot, UFW, fail2ban and unattended security updates.
Idempotent, every stage can be switched off.
→ [01 Provisioning and Hardening](usage/01-provisioning.md#en-3-step-1-bootstrap)

<a id="en-4-step-2-getscriptspy"></a>
### Step 2: getScripts.py

Deploys the fish shell with its aliases and every management script to `/root`.
Afterwards `doup`, `dobk`, `doval`, `konsole`, `dostat` and `wiz` exist as commands.
→ [01 Provisioning and Hardening](usage/01-provisioning.md#en-4-step-2-getscriptspy)

<a id="en-5-step-3-server-hardening"></a>
### Step 3: Server hardening

Read the audit without `--apply` first, then apply: UFW, fail2ban, SSH, sysctl,
auditd, AIDE. Lockout-safe — the SSH configuration is swapped only after
`sshd -t` accepts it.
→ [01 Provisioning and Hardening](usage/01-provisioning.md#en-5-step-3-server-hardening)

<a id="en-6-step-4-nginx-base--vhosts"></a>
### Step 4: nginx base and vhosts

Roll out the base files first, or every `include` in a vhost fails. Then
generate and deploy the vhosts through the wizard.
→ [02 nginx and Certificates](usage/02-nginx-certs.md#en-6-step-4-nginx-base--vhosts)

<a id="en-7-step-5-postgresql-live-dbtest-db"></a>
### Step 5: PostgreSQL

One database container each for live and test, deployed interactively, with a
resource profile and optional SSL.
→ [03 PostgreSQL and the Odoo Containers](usage/03-postgres-odoo.md#en-7-step-5-postgresql-live-dbtest-db)

<a id="en-8-step-6-first-start-of-the-odoo-containers"></a>
### Step 6: First start of the Odoo containers

Create the build folder, build the image, start the container — once for live,
once for test.
→ [03 PostgreSQL and the Odoo Containers](usage/03-postgres-odoo.md#en-8-step-6-first-start-of-the-odoo-containers)

<a id="en-9-step-7-lets-encrypt--reachability"></a>
### Step 7: Let's Encrypt and reachability

Obtain the certificates, check reachability, test the renewal path.
→ [02 nginx and Certificates](usage/02-nginx-certs.md#en-9-step-7-lets-encrypt--reachability)

<a id="en-10-step-8-set-up-updates-edupdoup"></a>
### Step 8: Set up updates

`docker2update.yaml` describes every instance, `doup` runs the updates. The
best way to add another instance is `wiz` — the assistant validates before it
writes. `doval` checks the configuration at any time, read-only.
→ [04 Setting Up and Running Updates](usage/04-updates.md#en-10-step-8-set-up-updates-edupdoup)

<a id="en-11-step-9-set-up-backups-edbkdobk"></a>
### Step 9: Set up backups

`container2backup.yaml` describes what is backed up, `dobk` carries it out.
Retention, compression and encryption belong to the initial configuration.
→ [05 Backup and Restore](usage/05-backup-restore.md#en-11-step-9-set-up-backups-edbkdobk)

<a id="en-12-step-10-automate-maintenance"></a>
### Step 10: Automate maintenance

One call wires backup, certificate renewal, GDPR log purging and memory cleanup
into a single cron drop-in. Only useful once step 9 is in place.
→ [06 Maintenance and Optional Components](usage/06-maintenance.md#en-12-step-10-automate-maintenance)

## For reference

<a id="en-13-restore--emergency"></a>
### Restore and emergency

Restoring from a backup, including format detection and the order in which the
containers are stopped.
→ [05 Backup and Restore](usage/05-backup-restore.md#en-13-restore--emergency)

<a id="en-14-script-reference"></a>
<a id="en-15-shell-reference-fish"></a>
### Script and shell reference

Every script in the repository with its purpose and invocation, every fish
alias by category.
→ [09 Script and Shell Reference](usage/09-reference.md#en-14-script-reference)

<a id="en-16-troubleshooting"></a>
### Troubleshooting

Symptom, cause, fix — including the Docker ≥ 29 traps where builds silently
produce hollow images.
→ [08 Troubleshooting](usage/08-troubleshooting.md#en-16-troubleshooting)

<a id="en-17-optional-components"></a>
### Optional components

The FastReport API for PDF rendering, and the guided Debian major upgrade.
→ [06 Maintenance and Optional Components](usage/06-maintenance.md#en-17-optional-components)

<a id="en-18-operation-behind-an-http-proxy"></a>
### Operation behind an HTTP proxy

For servers that may only reach the internet through a corporate proxy —
including the daemon proxy, without which every base image pull fails.
→ [07 Operation Behind an HTTP Proxy](usage/07-proxy.md#en-18-operation-behind-an-http-proxy)
