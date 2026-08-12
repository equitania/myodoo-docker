# Betrieb hinter HTTP-Proxy / Operation Behind an HTTP Proxy

Teil der [Server-Installationsanleitung](../INSTALLATION_GUIDE.md) · Part of the [server installation guide](../INSTALLATION_GUIDE.md)

[🇩🇪 Deutsch](#deutsch) | [🇬🇧 English](#english)

---

<a id="deutsch"></a>
# Betrieb hinter HTTP-Proxy

<a id="de-18-betrieb-hinter-http-proxy"></a>
## Betrieb hinter HTTP-Proxy

Für Server, die nur über einen Firmen-Proxy ins Internet dürfen
(getScripts.py ≥ 9.8.2, update_docker_odoo.py ≥ 5.3.0). Typisches
Erkennungsmerkmal: Firewalls solcher Umgebungen **droppen** direkte
Outbound-Verbindungen oft still — Prozesse ohne Proxy-Konfiguration
**hängen** dann, statt sofort zu scheitern.

### 18.1 Erstinstallation hinter Proxy

Bootstrap und Repo-Clone brauchen Internet, bevor der Proxy dauerhaft
konfiguriert ist — daher die Variablen zuerst manuell in der Session setzen
(frischer Server = noch bash), dann den normalen Bootstrap aus
[Kapitel 3](01-provisioning.md#de-3-schritt-1-bootstrap) ausführen:

```bash
# As root, bash — set proxy for this session first:
export http_proxy="http://proxy.example.com:8080"
export https_proxy="http://proxy.example.com:8080"
export no_proxy="localhost,127.0.0.1,::1,.local"
```

`apt`, `curl` und `git` übernehmen die Variablen — der Bootstrap läuft damit
vollständig durch den Proxy. Direkt danach die Konfiguration dauerhaft
machen (18.2).

### 18.2 Proxy dauerhaft konfigurieren

```fish
python3 ~/getScripts.py --proxy-check
```

Fragt Proxy-URL und Ausnahmen interaktiv ab und schreibt vier Stellen:

| Datei | Wirkung | Greift ab |
|---|---|---|
| `~/.config/fish/conf.d/99-proxy.fish` | Alle fish-Sessions (interaktiv + Skripte) | Nächste fish-Session (`exec fish`) |
| `/etc/environment` | Systemweit über PAM: Logins, cron, su | Nächster Login |
| `~/.getscripts_proxy` | Marker/Fallback für `update_docker_odoo.py` und das fastfetch-Deploy | Sofort |
| `/etc/systemd/system/docker.service.d/http-proxy.conf` | Docker-Daemon (Image-Pulls) | **Erst nach `systemctl restart docker`** |

> ⚠️ **Wartungsfenster:** `systemctl restart docker` startet **alle
> Container** neu. Bis zum Restart schlagen `docker pull`s fehl.

Proxy ändern oder entfernen: immer erneut über `--proxy-check` — nie die
Dateien einzeln editieren.

### 18.3 Container-Updates (doup)

`update_docker_odoo.py` löst den Proxy in dieser Reihenfolge auf:
`container.proxy` > `defaults.proxy` > Umgebungsvariablen >
`~/.getscripts_proxy`. Empfehlung: explizit in der `docker2update.yaml`
eintragen, dann sind auch cron-Läufe unabhängig von der Shell-Umgebung:

```yaml
defaults:
  proxy:                                    # wget downloads + docker build
    http_proxy: "http://proxy.example.com:8080"
    https_proxy: "http://proxy.example.com:8080"
    no_proxy: "localhost,127.0.0.1,.local"
```

Der YAML-Proxy wirkt auf `wget` und `docker build` (Env + `--build-arg`).
Das **Base-Image-Pull macht der Docker-Daemon** — dafür ist ausschließlich
das systemd-Drop-in aus 18.2 zuständig. Dateien, die der Build nicht selbst
laden kann, lassen sich pro Container über `pre_build_files`
(Liste aus `{source, target}`) vorab in den Build-Ordner kopieren.

### 18.4 Besonderheiten

- **fastfetch:** Das `publicip`-Modul nutzt Raw-Sockets, ignoriert
  `http_proxy` und würde beim Login endlos hängen. getScripts entfernt es
  auf Proxy-Hosts automatisch aus der deployten Config. Die verbleibende
  ~1 s Laufzeit ist normal (NetIO/DiskIO messen über ein 1-s-Fenster).
- **uv:** Bei per Paketmanager installiertem uv ist `uv self update` nicht
  möglich — getScripts erkennt das und loggt einen INFO-Skip, kein Fehler.
- **Interne Dienste:** Sprechen Skripte oder Container interne Hosts per
  HTTP an (z.B. `*.internal.example.com`), die Ausnahmen bei
  `--proxy-check` um `.internal.example.com` erweitern — sonst läuft der
  Traffic durch den Proxy.

### 18.5 Verifikation

```fish
env | grep -i proxy                                # fish-Umgebung
grep -i proxy /etc/environment                     # systemweit
systemctl show docker --property=Environment       # Docker-Daemon
git -C ~/myodoo-docker fetch --dry-run; echo $status   # Internet via Proxy (0 = ok)
time fastfetch > /dev/null                         # ~1 s, kein Haenger
```

| Symptom | Ursache | Fix |
|---|---|---|
| Login/fastfetch hängt endlos | Alte fastfetch-Config mit `publicip` | `ups`, danach `--proxy-check` |
| `docker pull` hängt/scheitert | Drop-in fehlt oder Docker nicht neu gestartet | 18.2 |
| `git pull` / `curl` hängt | Session ohne Proxy-Umgebung | `exec fish` bzw. neu einloggen |
| cron-Jobs ohne Internet | `/etc/environment` fehlt/veraltet | `--proxy-check` erneut ausführen |

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
| `proxy.example.com:8080` | Customer HTTP proxy (only [chapter 18](#en-18-operation-behind-an-http-proxy)) |

## Contents

1. [Overview & Architecture](01-provisioning.md#en-1-overview--architecture)
2. [Prerequisites](01-provisioning.md#en-2-prerequisites)
3. [Step 1: Bootstrap](01-provisioning.md#en-3-step-1-bootstrap)
4. [Step 2: getScripts.py](01-provisioning.md#en-4-step-2-getscriptspy)
5. [Step 3: Server Hardening](01-provisioning.md#en-5-step-3-server-hardening)
6. [Step 4: nginx Base + Vhosts](02-nginx-certs.md#en-6-step-4-nginx-base--vhosts)
7. [Step 5: PostgreSQL](03-postgres-odoo.md#en-7-step-5-postgresql-live-dbtest-db)
8. [Step 6: First Start of the Odoo Containers](03-postgres-odoo.md#en-8-step-6-first-start-of-the-odoo-containers)
9. [Step 7: Let's Encrypt & Reachability](02-nginx-certs.md#en-9-step-7-lets-encrypt--reachability)
10. [Step 8: Set Up Updates (edup/doup)](04-updates.md#en-10-step-8-set-up-updates-edupdoup)
11. [Step 9: Set Up Backups (edbk/dobk)](05-backup-restore.md#en-11-step-9-set-up-backups-edbkdobk)
12. [Step 10: Automate Maintenance](06-maintenance.md#en-12-step-10-automate-maintenance)
13. [Restore & Emergency](05-backup-restore.md#en-13-restore--emergency)
14. [Script Reference](09-reference.md#en-14-script-reference)
15. [Shell Reference (fish)](09-reference.md#en-15-shell-reference-fish)
16. [Troubleshooting](08-troubleshooting.md#en-16-troubleshooting)
17. [Optional Components](06-maintenance.md#en-17-optional-components)
18. [Operation Behind an HTTP Proxy](#en-18-operation-behind-an-http-proxy)

---

<a id="english"></a>
# Operation Behind an HTTP Proxy

<a id="en-18-operation-behind-an-http-proxy"></a>
## Operation Behind an HTTP Proxy

For servers that may only reach the internet through a corporate proxy
(getScripts.py ≥ 9.8.2, update_docker_odoo.py ≥ 5.3.0). Typical tell:
firewalls in such environments often **drop** direct outbound connections
silently — processes without proxy configuration then **hang** instead of
failing immediately.

### 18.1 Initial Installation Behind a Proxy

Bootstrap and repo clone need internet access before the proxy is
permanently configured — so set the variables manually in the session first
(fresh server = still bash), then run the normal bootstrap from
[chapter 3](01-provisioning.md#en-3-step-1-bootstrap):

```bash
# As root, bash — set proxy for this session first:
export http_proxy="http://proxy.example.com:8080"
export https_proxy="http://proxy.example.com:8080"
export no_proxy="localhost,127.0.0.1,::1,.local"
```

`apt`, `curl` and `git` pick up the variables — the bootstrap then runs
entirely through the proxy. Immediately afterwards, make the configuration
permanent (18.2).

### 18.2 Configure the Proxy Permanently

```fish
python3 ~/getScripts.py --proxy-check
```

Prompts for proxy URL and exceptions interactively and writes four places:

| File | Effect | Takes effect |
|---|---|---|
| `~/.config/fish/conf.d/99-proxy.fish` | All fish sessions (interactive + scripts) | Next fish session (`exec fish`) |
| `/etc/environment` | System-wide via PAM: logins, cron, su | Next login |
| `~/.getscripts_proxy` | Marker/fallback for `update_docker_odoo.py` and the fastfetch deploy | Immediately |
| `/etc/systemd/system/docker.service.d/http-proxy.conf` | Docker daemon (image pulls) | **Only after `systemctl restart docker`** |

> ⚠️ **Maintenance window:** `systemctl restart docker` restarts **all
> containers**. Until the restart, `docker pull` will fail.

To change or remove the proxy: always rerun `--proxy-check` — never edit
the files individually.

### 18.3 Container Updates (doup)

`update_docker_odoo.py` resolves the proxy in this order:
`container.proxy` > `defaults.proxy` > environment variables >
`~/.getscripts_proxy`. Recommendation: set it explicitly in
`docker2update.yaml` so cron runs are independent of the shell environment:

```yaml
defaults:
  proxy:                                    # wget downloads + docker build
    http_proxy: "http://proxy.example.com:8080"
    https_proxy: "http://proxy.example.com:8080"
    no_proxy: "localhost,127.0.0.1,.local"
```

The YAML proxy applies to `wget` and `docker build` (env + `--build-arg`).
The **base image pull is done by the Docker daemon** — only the systemd
drop-in from 18.2 covers that. Files the build cannot fetch itself can be
copied into the build folder beforehand via per-container `pre_build_files`
(list of `{source, target}`).

### 18.4 Peculiarities

- **fastfetch:** The `publicip` module uses raw sockets, ignores
  `http_proxy` and would hang the login indefinitely. getScripts strips it
  automatically from the deployed config on proxy hosts. The remaining
  ~1 s runtime is normal (NetIO/DiskIO sample over a 1 s window).
- **uv:** With uv installed via a package manager, `uv self update` is not
  possible — getScripts detects this and logs an INFO skip, not an error.
- **Internal services:** If scripts or containers talk to internal hosts
  over HTTP (e.g. `*.internal.example.com`), extend the exceptions in
  `--proxy-check` with `.internal.example.com` — otherwise that traffic
  goes through the proxy.

### 18.5 Verification

```fish
env | grep -i proxy                                # fish environment
grep -i proxy /etc/environment                     # system-wide
systemctl show docker --property=Environment       # Docker daemon
git -C ~/myodoo-docker fetch --dry-run; echo $status   # internet via proxy (0 = ok)
time fastfetch > /dev/null                         # ~1 s, no hang
```

| Symptom | Cause | Fix |
|---|---|---|
| Login/fastfetch hangs indefinitely | Old fastfetch config with `publicip` | `ups`, then `--proxy-check` |
| `docker pull` hangs/fails | Drop-in missing or Docker not restarted | 18.2 |
| `git pull` / `curl` hangs | Session without proxy environment | `exec fish` or re-login |
| cron jobs without internet | `/etc/environment` missing/outdated | Rerun `--proxy-check` |
