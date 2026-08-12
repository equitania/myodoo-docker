# Troubleshooting / Troubleshooting

Teil der [Server-Installationsanleitung](../INSTALLATION_GUIDE.md) · Part of the [server installation guide](../INSTALLATION_GUIDE.md)

[🇩🇪 Deutsch](#deutsch) | [🇬🇧 English](#english)

---

<a id="deutsch"></a>
# Troubleshooting

<a id="de-16-troubleshooting"></a>
## Troubleshooting

| Symptom | Ursache | Lösung |
|---|---|---|
| `docker build` scheitert bei „exporting to image" mit `ref moby/1/… locked … unavailable` | Docker ≥ 29 mit containerd Image Store ([moby#52431](https://github.com/moby/moby/issues/52431)) | `/etc/docker/daemon.json`: `{"storage-driver": "overlay2"}` → `systemctl restart docker` → **Server rebooten** → Images neu ziehen, Container neu erzeugen (Volumes bleiben) |
| `exec /app/bin/boot: no such file or directory` beim Container-Start, Build lief „durch" | Hohles Image aus vergiftetem BuildKit-Cache (Folge des Store-Bugs). Gegenprobe: fehlt sogar `/bin/sh` im Image? | Nach dem Store-Wechsel: `docker builder prune -af`, dann `docker build --no-cache --pull` |
| Builds liefern **nichtdeterministisch** hohle Images; Kernel-Log: `overlayfs: lowerdir is in-use as upperdir/workdir of another mount` | Verwaiste Overlay-Mounts des alten Stores nach einem Store-Wechsel ohne Reboot — zwei Overlay-Welten teilen sich Verzeichnisse | **Server rebooten**, danach `docker builder prune -af` + `docker build --no-cache --pull` |
| `docker build` bricht ab mit `Release server '…' could not be reached` bzw. `Connection refused` beim ZIP-Download | Webdienst auf dem Release-Server ist unten. Downloads werden 5× mit exponentiellem Backoff wiederholt (~45 s, build_odoo ≥ 2.5.0), danach bricht der Build ab | Auf dem Release-Server `systemctl status nginx` prüfen und starten, dann Build erneut anstoßen. Toleranz erhöhen via `BUILD_ODOO_RETRIES` / `BUILD_ODOO_RETRY_BACKOFF` |
| Build bricht ab mit `N module archive(s) could NOT be installed` samt Liste | Ein oder mehrere Modul-ZIPs fehlen auf dem Release-Server, oder ein Dateiname im `release.file` ist ungültig. Ab build_odoo ≥ 2.6.0 wird daraus ein harter Fehler statt eines stillschweigend unvollständigen Images | Gelistete Archive auf dem Release-Server prüfen bzw. `release.file` korrigieren, dann neu bauen. Drei aufeinanderfolgende Fehlschläge brechen den Lauf vorzeitig ab (`BUILD_ODOO_FAILURE_LIMIT`). Nur wenn ein unvollständiges Image bewusst in Kauf genommen wird: `BUILD_ODOO_ALLOW_PARTIAL=1` |
| nginx: `bind() to 203.0.113.10:443 failed (99: Cannot assign requested address)` | Öffentliche DNS-IP ist hinter NAT nicht lokal | In der Vhost-Config die **interne** IP verwenden; `ngx-conf-wizard.sh` zeigt die lokalen IPs an |
| `systemctl reload nginx` schlägt fehl, Journal zeigt kill-Usage-Text; alte Config bleibt aktiv | Leere `/run/nginx.pid` (durch `nginx -t` erzeugt), Standard-Unit vertraut der Datei | `$MAINPID`-Drop-in installieren ([Kapitel 6.1](02-nginx-certs.md#de-6-schritt-4-nginx-basis--vhosts)); tritt auch bei nginx-**Paket-Updates** auf (postinst) — danach `systemctl daemon-reload && systemctl restart nginx` |
| nginx tot (`Connection refused` auf 80 **und** 443), Host per SSH erreichbar; Journal zeigt `Failed to start nginx.service` wenige Sekunden nach einem apt-Upgrade | nginx wurde mitten im Austausch von glibc/openssl neu gestartet (durch `needrestart` oder den certbot-`pre_hook`); der Start scheiterte, und die nginx.org-Unit hat `Restart=no` — ein zweiter Versuch erfolgt nie | Drop-in `/etc/systemd/system/nginx.service.d/10-restart.conf` mit `Restart=on-failure` + `RestartSec=10` (plus `StartLimitBurst=5`/`StartLimitIntervalSec=300`). Zusätzlich `certbot.timer` per Drop-in auf einen festen Slot legen (z.B. `OnCalendar=*-*-* 03:00:00`, mit führender leerer `OnCalendar=`-Zeile), damit seine Zufallsverzögerung nicht ins apt-Fenster 06:00–07:00 fällt. **`bootstrap.sh` ≥ 1.9.0 setzt beide Drop-ins automatisch** — auch beim erneuten Lauf auf einem Bestandsserver |
| Odoo: „server does not support SSL, but SSL was required" beim DB-Anlegen | `db_sslmode = require` in der odoo.conf, PostgreSQL ohne SSL | `db_sslmode = prefer` setzen (oder PG-SSL aktivieren via `pg-local-deploy.sh`) |
| Domain extern erreichbar, intern nicht | Split-DNS: interne Clients bekommen die öffentliche IP, Gateway kann kein Hairpin-NAT | Pinpoint-Zone auf dem internen DNS: `erp-live.example.com` → interne Server-IP |
| Zertifikat läuft ab, Renewal schlägt fehl | Port-80-Forwarding wurde entfernt | TCP 80 → Server dauerhaft forwarden (HTTP-01) |
| `fish: $? is not the exit status …` | Bash-Syntax in der fish-Shell | `$status` statt `$?`; Bash-Blöcke via `bash -c '…'` |
| Odoo-Weboberfläche direkt über `IP:11000` aus dem LAN erreichbar | Port-Mapping ohne `127.0.0.1:`-Prefix | Container mit `-p 127.0.0.1:11000:8069 …` neu erzeugen |

---

<a id="english"></a>
# Troubleshooting

<a id="en-16-troubleshooting"></a>
## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `docker build` fails at "exporting to image" with `ref moby/1/… locked … unavailable` | Docker ≥ 29 with the containerd image store ([moby#52431](https://github.com/moby/moby/issues/52431)) | `/etc/docker/daemon.json`: `{"storage-driver": "overlay2"}` → `systemctl restart docker` → **reboot the server** → re-pull images, recreate containers (volumes survive) |
| `exec /app/bin/boot: no such file or directory` on container start although the build "succeeded" | Hollow image from a poisoned BuildKit cache (aftermath of the store bug). Cross-check: is even `/bin/sh` missing in the image? | After switching the store: `docker builder prune -af`, then `docker build --no-cache --pull` |
| Builds produce **non-deterministically** hollow images; kernel log: `overlayfs: lowerdir is in-use as upperdir/workdir of another mount` | Orphaned overlay mounts of the old store after a store switch without reboot — two overlay worlds share directories | **Reboot the server**, then `docker builder prune -af` + `docker build --no-cache --pull` |
| `docker build` aborts with `Release server '…' could not be reached` or `Connection refused` while downloading a ZIP | The web service on the release server is down. Downloads are retried 5× with exponential backoff (~45 s, build_odoo ≥ 2.5.0), then the build fails | On the release server check and start `systemctl status nginx`, then rerun the build. Raise the tolerance via `BUILD_ODOO_RETRIES` / `BUILD_ODOO_RETRY_BACKOFF` |
| Build aborts with `N module archive(s) could NOT be installed` plus a list | One or more module ZIPs are missing on the release server, or a filename in `release.file` is invalid. As of build_odoo ≥ 2.6.0 this is a hard failure instead of a silently incomplete image | Check the listed archives on the release server or fix `release.file`, then rebuild. Three consecutive failures abort the run early (`BUILD_ODOO_FAILURE_LIMIT`). Only if an incomplete image is knowingly acceptable: `BUILD_ODOO_ALLOW_PARTIAL=1` |
| nginx: `bind() to 203.0.113.10:443 failed (99: Cannot assign requested address)` | Behind NAT the public DNS IP is not local | Use the **internal** IP in the vhost config; `ngx-conf-wizard.sh` lists the local IPs |
| `systemctl reload nginx` fails, journal shows kill usage text; old config stays live | Empty `/run/nginx.pid` (created by `nginx -t`), stock unit trusts the file | Install the `$MAINPID` drop-in ([chapter 6.1](02-nginx-certs.md#en-6-step-4-nginx-base--vhosts)); also happens on nginx **package upgrades** (postinst) — then `systemctl daemon-reload && systemctl restart nginx` |
| nginx dead (`Connection refused` on 80 **and** 443), host still reachable via SSH; journal shows `Failed to start nginx.service` seconds after an apt upgrade | nginx was restarted mid-swap of glibc/openssl (by `needrestart` or the certbot `pre_hook`); the start failed and the nginx.org unit ships `Restart=no` — no second attempt ever happens | Drop-in `/etc/systemd/system/nginx.service.d/10-restart.conf` with `Restart=on-failure` + `RestartSec=10` (plus `StartLimitBurst=5`/`StartLimitIntervalSec=300`). Also pin `certbot.timer` to a fixed slot via drop-in (e.g. `OnCalendar=*-*-* 03:00:00`, preceded by an empty `OnCalendar=` line) so its randomized delay cannot land in the 06:00–07:00 apt window. **`bootstrap.sh` ≥ 1.9.0 installs both drop-ins automatically** — including on a re-run against an existing server |
| Odoo: "server does not support SSL, but SSL was required" when creating a DB | `db_sslmode = require` in odoo.conf, PostgreSQL without SSL | Set `db_sslmode = prefer` (or enable PG SSL via `pg-local-deploy.sh`) |
| Domain reachable externally but not internally | Split DNS: internal clients resolve the public IP, gateway cannot hairpin-NAT | Pinpoint zone on the internal DNS: `erp-live.example.com` → internal server IP |
| Certificate expires, renewal fails | Port 80 forwarding was removed | Forward TCP 80 → server permanently (HTTP-01) |
| `fish: $? is not the exit status …` | Bash syntax in the fish shell | `$status` instead of `$?`; bash blocks via `bash -c '…'` |
| Odoo web UI directly reachable via `IP:11000` from the LAN | Port mapping without the `127.0.0.1:` prefix | Recreate the container with `-p 127.0.0.1:11000:8069 …` |
