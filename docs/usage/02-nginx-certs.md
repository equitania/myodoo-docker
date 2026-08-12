# nginx und Zertifikate / nginx and Certificates

Teil der [Server-Installationsanleitung](../INSTALLATION_GUIDE.md) · Part of the [server installation guide](../INSTALLATION_GUIDE.md)

[🇩🇪 Deutsch](#deutsch) | [🇬🇧 English](#english)

---

<a id="deutsch"></a>
# nginx und Zertifikate

<a id="de-6-schritt-4-nginx-basis--vhosts"></a>
## Schritt 4: nginx-Basis + Vhosts

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

<a id="de-9-schritt-7-lets-encrypt--erreichbarkeit"></a>
## Schritt 7: Let's Encrypt & Erreichbarkeit

Die Zertifikate erzeugt `nginx-set-conf`/certbot beim Vhost-Deploy
(HTTP-01 über Port 80). Die automatische Erneuerung übernimmt später der
Wartungs-Cron ([Kapitel 12](06-maintenance.md#de-12-schritt-10-wartung-automatisieren)) über
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

---

<a id="english"></a>
# nginx and Certificates

<a id="en-6-step-4-nginx-base--vhosts"></a>
## Step 4: nginx Base + Vhosts

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

<a id="en-9-step-7-lets-encrypt--reachability"></a>
## Step 7: Let's Encrypt & Reachability

Certificates are created by `nginx-set-conf`/certbot during the vhost deploy
(HTTP-01 via port 80). Automatic renewal is handled later by the maintenance
cron ([chapter 12](06-maintenance.md#en-12-step-10-automate-maintenance)) via `ssl-renew.sh` —
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
