# Wartung und optionale Komponenten / Maintenance and Optional Components

Teil der [Server-Installationsanleitung](../INSTALLATION_GUIDE.md) · Part of the [server installation guide](../INSTALLATION_GUIDE.md)

[🇩🇪 Deutsch](#deutsch) | [🇬🇧 English](#english)

---

<a id="deutsch"></a>
# Wartung und optionale Komponenten

<a id="de-12-schritt-10-wartung-automatisieren"></a>
## Schritt 10: Wartung automatisieren

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
| Mo 06:00 | `server-readiness.py --quiet` — Konfigurations-Drift-Report |

Entfernen mit `--remove`. Details zum Nightly-Cleanup:
[scripts/NIGHTLY_CLEANUP.md](../../scripts/NIGHTLY_CLEANUP.md).

Der wöchentliche Readiness-Report schreibt bewusst **kein** Logfile: `--quiet`
gibt nichts aus, solange alles in Ordnung ist, sodass Cron per `MAILTO=root`
ausschließlich bei tatsächlicher Abweichung eine Mail schickt. Den vollen
Bericht jederzeit auf Zuruf: `chk`.

> **Prüfen statt raten:** Nach diesem Schritt beantwortet `chk` die Frage, ob
> der Server vollständig eingerichtet ist. Genau dafür existiert das Werkzeug —
> auf Servern, auf denen `setup-maintenance-cron.sh` nie lief, fehlt die
> logrotate-Konfiguration, und `/var/log/container2backup.log` wächst
> unbemerkt ins Unendliche.

### Server ohne Backups / ohne Odoo-Instanzen

Ein reiner Entwickler-Terminalserver läuft absichtlich ohne `dobk` und ohne
`doup` — `container2backup.yaml` und `docker2update.yaml` fehlen dort zu
Recht. Damit `chk`, `dostat`/`konsole` und der Montags-Cron das nicht als
Dauerfehler melden, wird der jeweilige Wartungsjob abgeschaltet, statt eine
weitere Konfigurationsdatei zu pflegen:

```bash
# Keine Backups auf diesem Host — beide Backup-Einträge mit einem Aufruf
# abschalten (der Job läuft zweimal täglich, --disable schaltet beide
# Cron-Zeilen zugleich):
docron --disable container2backup

# Keine von doup verwalteten Odoo-Instanzen auf diesem Host:
docron --disable odoo_build_cache
```

`server-readiness.py` liest das über `DERIVED_MUTES`: die zugehörigen Befunde
(`backup_recency`/`backup_config` bzw. `update_config`) laufen weiter, zeigen
im vollständigen Bericht aber `[MUTED] … cron job disabled on this host` statt
`FAIL`, und zählen nicht mehr für `--brief`, `--quiet` oder den Exit-Code.
`dostat`/`konsole` zeigen dieselbe Entscheidung als eigene Zeile: `off  backups
disabled on this host — …` bzw. `off  no doup-managed instances — …`, statt
der sonst üblichen „Datei nicht gefunden“-Meldung. Wieder einschalten mit
`docron --enable <Job>` — der Bericht normalisiert sich sofort, ohne dass
irgendwo etwas aufgeräumt werden muss.

<a id="de-17-optionale-komponenten"></a>
## Optionale Komponenten

**FastReport-API** (PDF-Rendering für Odoo): interaktiv per
`~/myodoo-docker/scripts/fr-local-deploy.sh` — Standard-Basis
`/opt/fast-report`, ein Container je System (z.B. `fr-live`, `fr-test`),
Registry-Zugang erforderlich. Die Backup-Einbindung erfolgt über den
`fast_report:`-Block in `container2backup.yaml` ([Kapitel 11](05-backup-restore.md#de-11-schritt-9-backups-einrichten-edbkdobk)).

**Debian-Major-Upgrade:** `dist-upgrade-debian.sh` führt geführt durch ein
In-Place-Upgrade (Quellen umschreiben, phasenweises Upgrade, Reboot-Abfrage).

---

<a id="english"></a>
# Maintenance and Optional Components

<a id="en-12-step-10-automate-maintenance"></a>
## Step 10: Automate Maintenance

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
| Mon 06:00 | `server-readiness.py --quiet` — configuration drift report |

Remove with `--remove`. Nightly cleanup details:
[scripts/NIGHTLY_CLEANUP.md](../../scripts/NIGHTLY_CLEANUP.md).

The weekly readiness report deliberately writes **no** logfile: `--quiet` prints
nothing while everything is fine, so cron mails via `MAILTO=root` only on actual
drift. For the full report at any time: `chk`.

> **Check instead of guessing:** After this step, `chk` answers whether the
> server is fully set up. That is exactly what the tool exists for — on servers
> where `setup-maintenance-cron.sh` never ran, the logrotate config is missing
> and `/var/log/container2backup.log` grows unbounded unnoticed.

### Server without backups / without Odoo instances

A pure developers' terminal server deliberately runs neither `dobk` nor
`doup` — `container2backup.yaml` and `docker2update.yaml` are rightly absent
there. So that `chk`, `dostat`/`konsole` and the Monday cron do not report
that as a permanent fault, switch off the matching maintenance job instead of
maintaining yet another configuration file:

```bash
# No backups on this host — switch off both backup entries in one call
# (the job runs twice a day, and --disable switches both cron lines at once):
docron --disable container2backup

# No doup-managed Odoo instances on this host:
docron --disable odoo_build_cache
```

`server-readiness.py` reads that through `DERIVED_MUTES`: the corresponding
findings (`backup_recency`/`backup_config`, or `update_config`) keep running,
but the full report shows `[MUTED] … cron job disabled on this host` instead
of `FAIL`, and they no longer count towards `--brief`, `--quiet` or the exit
code. `dostat`/`konsole` show the same decision as their own line: `off
backups disabled on this host — …` or `off  no doup-managed instances — …`,
instead of the usual "file not found" message. Switch it back on with `docron
--enable <job>` — the report normalises immediately, with nothing left to
clean up anywhere.

<a id="en-17-optional-components"></a>
## Optional Components

**FastReport API** (PDF rendering for Odoo): interactively via
`~/myodoo-docker/scripts/fr-local-deploy.sh` — default base
`/opt/fast-report`, one container per system (e.g. `fr-live`, `fr-test`),
registry access required. Backup integration via the `fast_report:` block in
`container2backup.yaml` ([chapter 11](05-backup-restore.md#en-11-step-9-set-up-backups-edbkdobk)).

**Debian major upgrade:** `dist-upgrade-debian.sh` guides through an in-place
upgrade (rewrite sources, phased upgrade, reboot prompt).
