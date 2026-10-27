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

> ℹ️ **Storage-Treiber: `overlay2`, wegen der Geschwindigkeit** (seit
> `bootstrap.sh` 1.14.0). Die Versionen 1.7.0 bis 1.12.0 pinnten ihn schon
> einmal, damals als Notbehelf gegen einen kaputten Image-Export auf dem
> containerd-Store ([moby/moby#52431](https://github.com/moby/moby/issues/52431)).
> Diese Begründung wurde am **14.08.2026 weggemessen** — fünf Builds mit 2,2 GB
> auf dem containerd-Store kamen fehlerfrei heraus.
>
> **Am 15.08.2026 wurde dann der echte Odoo-Build gemessen**, dieselbe
> Wegwerf-Instanz, Docker 29.7.2, 394 Modul-Archive vorab lokal — genau so, wie
> `odoo_build_cache.py` es im Betrieb macht:
>
> | | overlay2 | containerd |
> |---|---|---|
> | kalter Build | **14 s** | 37 s (2,6×) |
> | davon Export | 3,5 s | 19,7 s (5,6×) |
> | warmer Build | **0–1 s** | 35–36 s |
>
> Die letzte Zeile ist die entscheidende: Auf dem containerd-Store überlebt der
> Build-Cache das `docker system prune -f` nicht, das `update_docker_odoo.py`
> nach **jedem** Update ausführt — dort wäre also jeder `doup` ein Vollbau. Und
> die Vorteile des neuen Stores bekommen wir ohnehin nicht: Diese Images werden
> lokal gebaut, nie gepusht, eine Plattform, keine Attestations.
>
> `DOCKER_STORAGE_DRIVER="" ./bootstrap.sh` lässt Dockers Voreinstellung stehen.
> Eine vorhandene `daemon.json` wird **ergänzt** statt übersprungen (nur der
> Schlüssel `storage-driver`; ein absichtlich anderer Treiber bleibt stehen und
> wird gemeldet). Auf einem **laufenden** Server wird nichts umgestellt — das
> würde vorhandene Images bis zu Neustart und Reboot unsichtbar machen;
> `bootstrap.sh` sagt nur, was es kostet.
>
> **Auf einem laufenden Server** fragt `ups` (`getScripts.py` ≥ 9.24.0)
> einmal je interaktivem Lauf nach, wenn `docker info` einen anderen Treiber
> als `overlay2` meldet: Wartungsschritte anzeigen, dauerhaft stummschalten
> (`ownerp_mute.py docker_storage_driver --reason "..."`) oder später
> entscheiden. Ein Server ohne Terminal (Cron, CI) bekommt keine Frage — der
> `server-readiness.py`-Bericht (`chk`) trägt die Warnung ohnehin. Rückgängig:
> `ownerp_mute.py --unmute docker_storage_driver`.
>
> **Unabhängig davon** baut das Skript nach der Installation ein zweizeiliges
> Image und startet es: Ein Daemon, der Images ohne Dateisystem exportiert,
> besteht jede andere Prüfung. `DOCKER_SMOKE_TEST=0` schaltet das ab (Host ohne
> Registry-Zugang). Grenze dieser Prüfung: Sie ist grob — am 16.07.2026 baute
> auf demselben Server ein 1-Schicht-Image sauber, während das 22-Schicht-Odoo-Image
> hohl herauskam. Sie erkennt einen durchgehend kaputten Daemon, keinen
> selektiv kaputten.
>
> Symptome und Heilung bei einem hohlen Image: [Troubleshooting](08-troubleshooting.md#de-16-troubleshooting).

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

Danach neue Shell öffnen (aus bash: `exec fish`) — die
Aliase aus [Kapitel 15](09-reference.md#de-15-shell-referenz-fish) stehen bereit. Später
aktualisieren mit `ups`. Ab `getScripts.py` 9.25.0 genügt dafür ein einziges
`ups`: Bringt der Repository-Pull eine neuere Version mit, ersetzt sich das
Skript mittendrin selbst und startet sofort neu — eine neue Funktion oder ein
Fix ist damit noch im selben Lauf aktiv, nicht erst beim nächsten `ups`.

### Frischer Server ohne bootstrap

Ab `getScripts.py` 9.34.0 (27.10.2026) kommt auch der Weg über den
README-Einzeiler zum Ziel. Fehlt `docker` auf dem Host, bietet das Skript
direkt nach dem Klonen an, `scripts/bootstrap.sh` aus dem Repository zu
starten (Docker CE, nginx, certbot, UFW aus, fail2ban, automatische Updates,
python3-yaml/-dotenv, curl/git, UTF-8-Locale) — mit `RUN_GETSCRIPTS=0`, damit
bootstrap nicht wiederum getScripts aufruft. Ohne Terminal steht nur die eine
Zeile mit dem Befehl. Ein „n“ wird in
`~/.config/myodoo-docker/bootstrap-declined` gemerkt — ein bewusst Docker-loser
Host wird einmal gefragt, nicht bei jedem `ups`; Datei löschen, um erneut
gefragt zu werden. Der Erstlauf-Dialog fragt als dritten Block **SSH-Zugang
für die Härtung**: den festen SSH-Port (Vorschlag: der Port aus `sshd -T`) und
die Admin-Adressen kommagetrennt (Vorschlag: die verbundenen Sitzungen) und
schreibt `/root/.config/myodoo-docker/.env` sofort — vor dem Klonen als
Minimaldatei mit nur diesen Schlüsseln, sonst aus `scripts/.env.example`.
Netze (`/24`) werden abgelehnt, `ALLOWED_IP` kennt nur einzelne Adressen. Ein
anderer Port als der live lauschende wird eingetragen, nicht umgestellt: die
Härtung wartet mit UFW und SSH, bis sshd dort lauscht. Versionsabfragen laufen
unter `LC_ALL=C` (Fish 4.9 schreibt unter deutscher Locale „Version“), und als
root kommt das Skript ohne das Paket `sudo` aus.

### Ohne root: eingeschränkter Modus

Für Kunden, die getScripts.py weder als root noch mit sudo ausführen wollen
(ab 9.27.0). Das Skript installiert dann nichts systemweit, sondern richtet
nur die eigene Umgebung des Benutzers ein: Fish-Konfiguration,
Starship-Prompt, fastfetch-Konfiguration und — mit dem eigenen Passwort — die
Login-Shell. Server-Werkzeuge, Härtung, Proxy und DNS bleiben root
vorbehalten.

Als normaler Benutzer (funktioniert in bash und fish, braucht nur python3):

```bash
python3 -c "import urllib.request; urllib.request.urlretrieve('https://raw.githubusercontent.com/equitania/myodoo-docker/2026/getScripts.py', 'getScripts.py')"
python3 getScripts.py
```

Ohne root-Rechte und ohne sudo ohne Passwort fragt das Skript, ob es im
eingeschränkten Modus weiterlaufen soll (ohne Terminal: `--restricted`
angeben). Fehlen Pakete, nennt es die Befehle, die der Administrator als root
ausführt — ausschließlich Pakete aus dem Debian-Archiv:

```bash
apt-get update
apt-get upgrade
apt-get install fish git                      # nötig (ca-certificates, falls es fehlt)
apt-get install starship zoxide fastfetch     # empfohlen
```

Danach `python3 getScripts.py` erneut starten. Die Wahl wird in
`~/.getscripts_restricted` gemerkt; spätere Läufe und `ups` gehen ohne
Rückfrage und ohne sudo in diesen Modus. Voraussetzung ist Debian 13: es
bringt Fish 4.0 mit (die volle Einrichtung installiert 4.5+ aus dem
Fish-Projekt-Repository, was hier ausgeschlossen ist). Debian 12 hat nur
Fish 3.6, und die Backports enthalten kein Fish 4 — dort bricht der Modus mit
dieser Begründung ab. Das Befehlsfeld beim Start der Shell zeigt statt der
Server-Befehle, die hier nicht installiert sind, eine eigene Übersicht mit
dem, was ohne root funktioniert (`ups`, `help`, `ll`, `z`, Git-Kürzel, `ff`).

**Zweite Stufe: Benutzer in der Gruppe `docker`** (ab 9.28.0). Ist der
Benutzer in der Gruppe `docker`, liefert der eingeschränkte Modus zusätzlich
die Odoo-Werkzeuge, die nur Docker und das eigene Home brauchen: `doup`,
`dobk`, `edup`, `edbk`, `dostat`, `doval`, `wiz`/`wizup`/`wizbk` und die
Docker-Übersichten `dps`/`dpsall`/`dpi`. Das Befehlsfeld zeigt sie dann mit an.
Bei root bleiben `docron` (`/etc/cron.d`), nginx, Härtung, der
Build-Cache in `/opt/odoo-build-cache` und die Wartungs-Crons.

> ⚠️ **Die Gruppe `docker` ist gleichbedeutend mit root.** Wer Docker
> steuert, kann einen Container starten, der das ganze Dateisystem des Hosts
> einbindet. Das Skript fragt deshalb nie danach, sondern nennt den Befehl
> einmal mit diesem Hinweis. Die Entscheidung liegt beim Kunden.

Der Administrator erledigt dafür als root:

```bash
usermod -aG docker <benutzer>                                # danach neu anmelden
apt-get install mc python3-yaml python3-dotenv 7zip zstd gnupg
install -d -o <benutzer> /opt/backups                        # Ziel von dobk
```

Die Konfiguration entsteht aus den laufenden Containern mit
`python3 ~/ownerp_migrate.py --from-docker`. Welche Pakete fehlen und ob
`/opt/backups` beschreibbar ist, meldet `ups` selbst.

> ⚠️ **Erfahrungswert (sudo su):** Wer sich mit einem persönlichen
> Admin-Account anmeldet und per `sudo su` zu root wird, braucht
> getScripts.py ≥ 9.7.3 — ältere Versionen installierten in diesem Fall ins
> falsche Home-Verzeichnis (Aliase fehlten für root).

<a id="de-5-schritt-3-server-härtung"></a>
## Schritt 3: Server-Härtung

**`ups` fragt nach.** Auf einem Terminal prüft jeder `ups`-Lauf die Härtung
(`server_hardening.py --json`) und bietet an, offene Bereiche zu schließen —
Schritt 2 hat das bereits mitlaufen lassen, hier nur zur Erklärung, was dabei
passiert:

1. **Fehlt `/root/.config/myodoo-docker/.env`**, bietet `ups` an, sie
   anzulegen. Ab getScripts 9.32.0 leitet es die Werte aus dem Server ab:
   `SSH_PORT` aus `sshd -T`, die Admin-IPs samt Kommentar aus den UFW-Regeln,
   die SSH auf diesem Port für eine einzelne Adresse freigeben, dazu jede
   gerade verbundene SSH-Sitzung. Eine Rückfrage genügt; `h` führt in die
   Eingabe von Hand. Netze (`198.51.100.0/24`) kann `ALLOWED_IP` nicht
   aufnehmen — sie werden genannt, ihre UFW-Regeln bleiben bestehen, weil die
   Härtung Regeln nur hinzufügt. Eine bestehende `/root/.env` (Alt-Pfad) wird unverändert
   übernommen, nie überschrieben.
2. **Weicht danach noch ein Bereich ab**, nennt `ups` ihn und sagt in einem
   Absatz, was Anwenden heißt: neuer SSH-Port statt des alten (wenn
   `SSH_PORT` vom Live-Port abweicht), Zugriff nur von den Admin-Adressen,
   Firewall an, fail2ban, automatische Sicherheitsupdates ohne nächtlichen
   Neustart. Dann **eine** Frage: „Härtung jetzt anwenden? (j/N)“. Alles
   außer `j` lässt den Server, wie er ist; die Zeile „Später“ nennt `chk`,
   `server_hardening.py --help`, `ownerp_mute.py <check_id>` (einen Bereich
   dauerhaft stummschalten) und den Befehl für den nächtlichen Neustart
   (`server_hardening.py --apply -m auto_updates`).
3. **„j“ mit Portwechsel startet den Übergang** (`server_hardening.py
   --ssh-transition begin`, seit 9.35.0/1.12.0): sshd lauscht zusätzlich auf
   dem neuen Port (Kandidat mit `sshd -t` geprüft, Reload, Verbindung auf
   den neuen Port; schlägt das fehl, wird die Sicherung zurückgespielt und
   nichts weiter angefasst), die Firewall lässt alten und neuen Port für die
   Admin-Adressen zu, fail2ban überwacht beide, dann folgen die übrigen
   Module. Der alte Port bleibt offen, bis einmal eine Anmeldung über den
   neuen Port von einer Admin-Adresse zu sehen ist — der nächste `ups`
   schließt ihn dann (`ssh port: updated` im Install-Report); bis dahin
   meldet `chk` „Portwechsel läuft: anmelden über <Port>, dann ups“. Eine
   vorgeschaltete Anbieter-Firewall (Hetzner Cloud Firewall, Security Group)
   muss den neuen Port offen haben — die Frage sagt das. Ohne Portwechsel
   laufen die Module wie bisher: unkritische zuerst, dann ufw/fail2ban/ssh,
   Docker, AIDE.
4. **Was `ups` nicht tut**: ohne Aussperr-Prüfung an Firewall, fail2ban
   oder SSH gehen — jede bestehende SSH-Verbindung muss von einer
   Admin-Adresse kommen, die `.env` braucht mindestens eine, `sshd -T` und
   `ss` müssen lesbar sein; sonst warten diese drei Bereiche mit einer
   Statuszeile, die übrigen werden trotzdem angeboten. Und den Docker-Daemon
   neustarten, solange irgendein Container existiert — auch ein gestoppter
   trägt `--restart=always` und würde beim Neustart ungefragt wieder anlaufen
   — oder die `docker`-Härtung selbst fehlschlug. `daemon.json` wird
   geschrieben, der Neustart nur ausgeführt, wenn das Apply erfolgreich war
   *und* kein Container existiert, sonst als Wartungsfenster-Hinweis
   ausgegeben.

Ohne Terminal (Cron, CI) meldet nur `chk` die offenen Bereiche — `ups` fragt
dort nichts.

Der manuelle Weg bleibt die Alternative, z. B. für gezielte Module oder
außerhalb eines Terminals:

```bash
mcedit /root/.config/myodoo-docker/.env   # SSH_PORT, ALLOWED_IP_1..n, Alert-Mail
sudo python3 /root/server_hardening.py            # Audit / Dry-Run
sudo python3 /root/server_hardening.py --apply    # UFW, fail2ban, SSH, sysctl, auditd, AIDE, ...
```

UFW wird erst hier aktiviert — nach konfiguriertem SSH-Port und erlaubten
IPs, damit man sich nicht aussperrt. Einzelne Module gezielt:
`--apply --module ufw` bzw. `-m fail2ban ssh sysctl`. Konfiguration:
`scripts/hardening_config.yaml`.

<a id="de-5a-ssh-port-wechseln"></a>
### SSH-Port wechseln

Der Portwechsel ist ein **Übergang** (seit getScripts 9.35.0 /
server_hardening 1.12.0): sshd lauscht eine Zeit lang auf dem alten und dem
neuen Port, die Firewall lässt beide für die Admin-Adressen zu, und der alte
Port schließt sich erst, wenn eine Anmeldung über den neuen Port von einer
Admin-Adresse gesehen wurde. Was kein Skript sieht, bleibt beim Anbieter: eine
vorgeschaltete Firewall/Security Group muss den neuen Port offen haben.

1. Neuen Port in der Firewall/Security Group des Anbieters für die
   Admin-IPs öffnen (alten Port offen lassen)
2. `SSH_PORT` in `/root/.config/myodoo-docker/.env` auf den neuen Port
   setzen — auf einem frischen Server hat der Erstlauf das schon erledigt
3. `ups` und die Frage „Härtung jetzt anwenden?“ mit `j` beantworten, oder
   von Hand: `sudo python3 /root/server_hardening.py --ssh-transition begin`
4. Auf dem neuen Port anmelden und `ups` ausführen (oder
   `sudo python3 /root/server_hardening.py --ssh-transition finish`) — das
   schließt den alten Port in sshd und UFW und entfernt die Übergangsmarke
   `/root/.config/myodoo-docker/ssh-transition`
5. Alten Port beim Anbieter schließen

`sudo python3 /root/server_hardening.py --ssh-transition status` zeigt
`none` oder `pending <alt> -> <neu>`. Ein Drop-in unter
`/etc/ssh/sshd_config.d/` mit eigener `Port`-Zeile lehnt `begin` ab und nennt
die Datei; auf Ubuntu schaltet `begin` von `ssh.socket` auf `ssh.service` um,
weil der Socket die `Port`-Zeile sonst überstimmt.

<a id="de-5b-cloud-images-root-gesperrt"></a>
### Cloud-Images: root gesperrt

Cloud-Images (OpenStack, die meisten Provider-Images) sperren das
root-Passwort und setzen `disable_root: true` in `/etc/cloud/cloud.cfg` —
das kollidiert mit einer `hardening_config.yaml`, die `PermitRootLogin yes`
erwartet: `passwd -S root` meldet `L`, root kann sich also gar nicht
anmelden, obwohl die Härtung es erlaubt. `chk` meldet das als `root_login_locked`
(WARN) und behebt es nicht automatisch — das braucht ein Passwort:

```bash
passwd root
printf '%s\n' 'disable_root: false' > /etc/cloud/cloud.cfg.d/99-ownerp-root.cfg
```

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

> ℹ️ **Storage driver: `overlay2`, for speed** (since `bootstrap.sh` 1.14.0).
> Versions 1.7.0 to 1.12.0 already pinned it, back then as a workaround for a
> broken image export on the containerd store
> ([moby/moby#52431](https://github.com/moby/moby/issues/52431)). That
> justification was **measured away on 14.08.2026** — five 2.2 GB builds on the
> containerd store came out correct.
>
> **On 15.08.2026 the real Odoo build was measured**, same throwaway box, Docker
> 29.7.2, 394 module archives pre-fetched exactly as `odoo_build_cache.py` does
> in production:
>
> | | overlay2 | containerd |
> |---|---|---|
> | cold build | **14 s** | 37 s (2.6×) |
> | of which export | 3.5 s | 19.7 s (5.6×) |
> | warm build | **0–1 s** | 35–36 s |
>
> The last row is the decisive one: on the containerd store the build cache does
> not survive the `docker system prune -f` that `update_docker_odoo.py` runs
> after **every** update, so every `doup` there would be a full rebuild. And we
> get none of that store's benefits anyway: these images are built locally,
> never pushed, single-platform, no attestations.
>
> `DOCKER_STORAGE_DRIVER="" ./bootstrap.sh` leaves Docker's default in place. An
> existing `daemon.json` is **merged into** rather than skipped (only the
> `storage-driver` key; a deliberately different driver is left alone and
> reported). Nothing is switched on a **running** server — that would hide
> existing images until a restart and a reboot; `bootstrap.sh` only says what it
> costs.
>
> **On a running server**, `ups` (`getScripts.py` >= 9.24.0) asks once per
> interactive run when `docker info` reports a driver other than `overlay2`:
> show the maintenance steps, mute it permanently
> (`ownerp_mute.py docker_storage_driver --reason "..."`), or decide later. A
> server with no terminal (cron, CI) gets no question — the
> `server-readiness.py` report (`chk`) already carries the warning. Undo with
> `ownerp_mute.py --unmute docker_storage_driver`.
>
> **Independently of all that**, the script builds and runs a two-line image
> after the install: a daemon that exports images with no filesystem passes
> every other check. `DOCKER_SMOKE_TEST=0` disables it (host without registry
> access). Its limit: it is coarse — on 16.07.2026, on that same server, a
> 1-layer image built cleanly while the 22-layer Odoo image came out hollow. It
> catches a comprehensively broken daemon, not a selectively broken one.
>
> Symptoms and cure for a hollow image: [Troubleshooting](08-troubleshooting.md#en-16-troubleshooting).

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

Then open a new shell (from bash: `exec fish`) — the aliases
from [chapter 15](09-reference.md#en-15-shell-reference-fish) are available. Update later
with `ups`. As of `getScripts.py` 9.25.0, one `ups` is enough: if the
repository pull brings in a newer version, the script replaces itself
mid-run and restarts immediately, so a new feature or fix is already active
in that same run instead of only the next `ups`.

### Fresh server without bootstrap

As of `getScripts.py` 9.34.0 (27.10.2026) the README one-liner reaches the
goal too. When `docker` is missing on the host, the script offers right after
the clone to run `scripts/bootstrap.sh` from the repository (Docker CE, nginx,
certbot, UFW off, fail2ban, unattended upgrades, python3-yaml/-dotenv,
curl/git, UTF-8 locale) — with `RUN_GETSCRIPTS=0` so bootstrap does not call
getScripts in turn. Without a terminal only the one line with the command is
printed. An "n" is remembered in `~/.config/myodoo-docker/bootstrap-declined` —
a deliberately Docker-less host is asked once, not on every `ups`; delete the
file to be asked again. The first-run dialogue asks, as its third block **SSH access for the
hardening**, for the fixed SSH port (suggested: the port from `sshd -T`) and
the admin addresses, comma-separated (suggested: the connected sessions), and
writes `/root/.config/myodoo-docker/.env` right away — before the clone as a
minimal file with only these keys, otherwise rendered from
`scripts/.env.example`. Networks (`/24`) are rejected; `ALLOWED_IP` takes
single addresses only. A port other than the live one is recorded, not
switched: the hardening waits with UFW and SSH until sshd listens there.
Version probes run under `LC_ALL=C` (Fish 4.9 prints „Version“ under a German
locale), and as root the script no longer needs the `sudo` package.

### Without root: restricted mode

For customers who will run getScripts.py neither as root nor through sudo
(since 9.27.0). The script then installs nothing system-wide and sets up only
the user's own environment: the Fish configuration, the Starship prompt,
fastfetch's configuration and — with the user's own password — the login
shell. Server tools, hardening, proxy and DNS stay with root.

As an ordinary user (works in bash and fish, needs only python3):

```bash
python3 -c "import urllib.request; urllib.request.urlretrieve('https://raw.githubusercontent.com/equitania/myodoo-docker/2026/getScripts.py', 'getScripts.py')"
python3 getScripts.py
```

Without root and without passwordless sudo the script asks whether to
continue in restricted mode (with no terminal, pass `--restricted`). When
packages are missing it prints the commands the administrator runs as root —
packages from the Debian archive only:

```bash
apt-get update
apt-get upgrade
apt-get install fish git                      # required (ca-certificates if missing)
apt-get install starship zoxide fastfetch     # recommended
```

Then run `python3 getScripts.py` again. The choice is remembered in
`~/.getscripts_restricted`; later runs and `ups` enter this mode without
asking and without sudo. It requires Debian 13, which ships Fish 4.0 (the
full setup installs 4.5+ from the Fish project's repository, which is ruled
out here). Debian 12 has only Fish 3.6 and its backports carry no Fish 4 —
the mode stops there and says so. The command panel at shell start shows,
instead of the server commands that are not installed here, its own overview
of what works without root (`ups`, `help`, `ll`, `z`, git shortcuts, `ff`).

**Second tier: a user in the `docker` group** (since 9.28.0). When the user is
in the `docker` group, the restricted mode also delivers the Odoo tools that
need nothing beyond Docker and the user's own home: `doup`, `dobk`, `edup`,
`edbk`, `dostat`, `doval`, `wiz`/`wizup`/`wizbk` and the Docker views
`dps`/`dpsall`/`dpi`. The command panel then lists them too. `docron`
(`/etc/cron.d`), nginx, hardening, the build cache in `/opt/odoo-build-cache`
and the maintenance crons stay with root.

> ⚠️ **The `docker` group is root in all but name.** Whoever controls Docker
> can start a container that mounts the host's whole filesystem. The script
> therefore never asks for it; it names the command once, with this warning.
> The decision is the customer's.

The administrator runs as root:

```bash
usermod -aG docker <user>                                    # then log in again
apt-get install mc python3-yaml python3-dotenv 7zip zstd gnupg
install -d -o <user> /opt/backups                            # dobk's target
```

The configuration is built from the running containers with
`python3 ~/ownerp_migrate.py --from-docker`. `ups` itself reports which
packages are missing and whether `/opt/backups` is writable.

> ⚠️ **Lesson learned (sudo su):** Operators who log in with a personal admin
> account and become root via `sudo su` need getScripts.py ≥ 9.7.3 — older
> versions installed into the wrong home directory in that case (root's
> shell had no aliases).

<a id="en-5-step-3-server-hardening"></a>
## Step 3: Server Hardening

**`ups` asks.** On a terminal, every `ups` run checks the hardening
(`server_hardening.py --json`) and offers to close whatever is open — step 2
already ran this along the way; this is what happens under the hood:

1. **If `/root/.config/myodoo-docker/.env` is missing**, `ups` offers to
   create it. From getScripts 9.32.0 on it derives the values from the
   server: `SSH_PORT` from `sshd -T`, the admin IPs with their comments from
   the ufw rules that admit a single address to SSH on that port, plus every
   SSH session connected right now. One confirmation is enough; `h` goes to
   typing the values by hand. Networks (`198.51.100.0/24`) cannot go into
   `ALLOWED_IP` — they are named, and their ufw rules stay, because the
   hardening only adds rules. An existing `/root/.env` (legacy path) is used as is and never
   overwritten.
2. **If any area still deviates afterwards**, `ups` names it and says in
   one paragraph what applying means: the new SSH port instead of the old
   one (when `SSH_PORT` differs from the live port), access only from the
   admin addresses, firewall on, fail2ban, automatic security updates
   without the nightly reboot. Then **one** question: "Härtung jetzt
   anwenden? (j/N)". Anything but `j` leaves the server as it is; the
   "Später" line names `chk`, `server_hardening.py --help`,
   `ownerp_mute.py <check_id>` (mute one area permanently) and the command
   for the nightly reboot (`server_hardening.py --apply -m auto_updates`).
3. **"j" with a port change starts the transition** (`server_hardening.py
   --ssh-transition begin`, since 9.35.0/1.12.0): sshd listens on the new
   port in addition to the old one (candidate checked with `sshd -t`,
   reload, a connection to the new port; on failure the backup is restored
   and nothing else is touched), the firewall admits old and new port for
   the admin addresses, fail2ban watches both, then the remaining modules
   follow. The old port stays open until a login over the new port from an
   admin address has been seen — the next `ups` then closes it (`ssh port:
   updated` in the install report); until then `chk` reports "Portwechsel
   läuft: anmelden über <port>, dann ups". A provider firewall in front
   (Hetzner Cloud Firewall, security group) must have the new port open —
   the question says so. Without a port change the modules run as before:
   harmless ones first, then ufw/fail2ban/ssh, Docker, AIDE.
4. **What `ups` does not do**: touch firewall, fail2ban or SSH without a
   lockout check — every established SSH connection must come from an admin
   address, the `.env` needs at least one, `sshd -T` and `ss` must be
   readable; otherwise those three areas wait with one status line and the
   rest is still offered. And restart the Docker daemon while any container
   exists — a stopped one still carries `--restart=always` and would come
   back unasked on the restart — or after the `docker` hardening itself
   failed to apply. `daemon.json` is still written; the restart only runs
   when the apply succeeded *and* no container exists, otherwise it is
   printed as a maintenance-window hint.

Without a terminal (cron, CI) only `chk` reports the open areas — `ups` asks
nothing there.

The manual path remains the alternative, e.g. for targeting individual
modules or outside a terminal:

```bash
mcedit /root/.config/myodoo-docker/.env   # SSH_PORT, ALLOWED_IP_1..n, alert mail
sudo python3 /root/server_hardening.py            # audit / dry run
sudo python3 /root/server_hardening.py --apply    # UFW, fail2ban, SSH, sysctl, auditd, AIDE, ...
```

UFW is only enabled here — after the SSH port and allowed IPs are configured,
so you cannot lock yourself out. Target individual modules with
`--apply --module ufw` or `-m fail2ban ssh sysctl`. Configuration:
`scripts/hardening_config.yaml`.

<a id="en-5a-changing-the-ssh-port"></a>
### Changing the SSH port

The port change is a **transition** (since getScripts 9.35.0 /
server_hardening 1.12.0): for a while sshd listens on the old and the new
port, the firewall admits both for the admin addresses, and the old port
closes only once a login over the new port from an admin address has been
seen. What no script can see stays with the provider: a firewall/security
group in front must have the new port open.

1. Open the new port in the provider's firewall/security group for the
   admin IPs (leave the old port open)
2. Set `SSH_PORT` in `/root/.config/myodoo-docker/.env` to the new port —
   on a fresh server the first-run dialogue has done that already
3. Run `ups` and answer "Härtung jetzt anwenden?" with `j`, or by hand:
   `sudo python3 /root/server_hardening.py --ssh-transition begin`
4. Log in on the new port and run `ups` (or
   `sudo python3 /root/server_hardening.py --ssh-transition finish`) — that
   closes the old port in sshd and UFW and removes the transition marker
   `/root/.config/myodoo-docker/ssh-transition`
5. Close the old port at the provider

`sudo python3 /root/server_hardening.py --ssh-transition status` prints
`none` or `pending <old> -> <new>`. A drop-in under
`/etc/ssh/sshd_config.d/` with its own `Port` line makes `begin` refuse and
name the file; on Ubuntu `begin` switches from `ssh.socket` to `ssh.service`,
because the socket would otherwise override the `Port` line.

<a id="en-5b-cloud-images-root-locked"></a>
### Cloud images: root locked

Cloud images (OpenStack, most provider images) lock root's password and set
`disable_root: true` in `/etc/cloud/cloud.cfg` — that conflicts with a
`hardening_config.yaml` that expects `PermitRootLogin yes`: `passwd -S root`
reports `L`, so root cannot log in at all even though the hardening allows
it. `chk` reports this as `root_login_locked` (WARN) and does not fix it
automatically — that needs a password:

```bash
passwd root
printf '%s\n' 'disable_root: false' > /etc/cloud/cloud.cfg.d/99-ownerp-root.cfg
```
