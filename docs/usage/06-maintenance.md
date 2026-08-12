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

<a id="en-17-optional-components"></a>
## Optional Components

**FastReport API** (PDF rendering for Odoo): interactively via
`~/myodoo-docker/scripts/fr-local-deploy.sh` — default base
`/opt/fast-report`, one container per system (e.g. `fr-live`, `fr-test`),
registry access required. Backup integration via the `fast_report:` block in
`container2backup.yaml` ([chapter 11](05-backup-restore.md#en-11-step-9-set-up-backups-edbkdobk)).

**Debian major upgrade:** `dist-upgrade-debian.sh` guides through an in-place
upgrade (rewrite sources, phased upgrade, reboot prompt).
