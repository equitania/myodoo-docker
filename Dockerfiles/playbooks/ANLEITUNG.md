# Testsystem aus dem Live-Backup neu aufsetzen

Diese Playbooks überschreiben das Testsystem eines ownERP-Servers (`test-odoo` mit der
Datenbank in `test-db`) mit dem Stand des neuesten Live-Backups. Sie werden mit einem
einzigen Befehl gestartet. Sie wählen nur, **in welchem Zustand** die Daten danach sein
sollen.

Das Live-System wird dabei nicht berührt. Gelesen wird nur das Backup, das
`container2backup.py` (`dobk`) für `live-odoo` geschrieben hat.

## Voraussetzungen

- odoodev ab Version 0.75.7 (`odoodev --version`)
- `test-odoo` steht in `~/docker2update.yaml`, `update_docker_odoo.py` (`doup`) liegt in `~`
- Die Live-Backups enthalten den Filestore (kein `only_sql_dump`) und sind nicht
  verschlüsselt. Verschlüsselte Backups (`.gpg`) kann der Restore nicht lesen.
- Auf der lokalen Platte ist Platz für die alte und die neue Datenbank nebeneinander,
  dazu für das entpackte Backup.

## Einrichtung (einmal pro Server)

Die Playbooks in `v16/`, `v18/` und `v19/` sind Beispiele mit den Werten der Vorlagen
(`test_db`, `live_db`, `/opt/odoo/test`, Backups als `.7z`). Für einen echten Server
werden sie mit dem Generator aus dessen eigener Konfiguration erzeugt:

```
cd ~/myodoo-docker/Dockerfiles/playbooks
python3 generate.py --version 18 --out ~/playbooks
mkdir -p /opt/backups/restore-tmp
cp passwort-setzen.py ~/playbooks/
```

Für Odoo 16 oder 19 steht `--version 16` bzw. `--version 19`. Der Generator liest:

- aus `~/docker2update.yaml` den Datenbanknamen und das Datenverzeichnis von `test-odoo`,
- aus `~/container2backup.yaml` das Backup-Verzeichnis, den Datenbanknamen in den
  Live-Backups und das Archivformat.

Er zeigt am Ende, welche Werte er verwendet. Jeder Wert lässt sich überschreiben,
`python3 generate.py --help` listet die Optionen. Läuft `doup` oder `dobk` später mit
geänderter Konfiguration, erzeugen Sie die Playbooks neu.

## Die Zustände

| Datei | Was danach in der Datenbank steht | Geeignet für |
|---|---|---|
| `neutral.yaml` | Alle Daten wie im Live-System, aber neutralisiert (siehe unten) | Fehler nachstellen, Abnahme mit echten Daten |
| `anonym.yaml` | Wie `neutral`, zusätzlich sind personenbezogene Daten durch Fantasiewerte ersetzt | Tests mit externen Beteiligten, Schulung ohne Echtdaten |
| `anonym-leer.yaml` | Wie `anonym`, zusätzlich sind Nachrichten (Chatter) und Anhänge gelöscht | Wenn auch Dokumentinhalte nicht sichtbar sein dürfen |
| `stammdaten.yaml` | Alle Bewegungsdaten gelöscht, Stammdaten bleiben | Schulung, Probe eines Neustarts |
| `vorlage.yaml` | Zusätzlich Kunden, Lieferanten und Kontakte gelöscht | Leere Vorlage mit Konfiguration und Artikelstamm |

Im Einzelnen:

- **`anonym`** ersetzt Namen, Adressen, E-Mail-Adressen und Telefonnummern von Kontakten,
  Leads, Bankverbindungen und Mitarbeiterdaten. Benutzer und Firma behalten ihre echten
  Namen, damit die Anmeldung weiter funktioniert.
- **`anonym-leer`** löscht zusätzlich alle Nachrichten und Notizen im Chatter sowie die
  Anhänge, darunter Rechnungs-PDFs. Artikelbilder und Firmenlogo bleiben erhalten.
- **`stammdaten`** löscht Aufträge, Rechnungen, Buchungen, Zahlungen, Lagerbewegungen,
  Fertigungsaufträge und Kassenvorgänge. **Alle Lagerbestände stehen danach auf null.**
  Kontakte, Artikel, Preislisten, Benutzer und Konfiguration bleiben, die Kontakte
  **nicht** anonymisiert.
- **`vorlage`** löscht alles, was `stammdaten` löscht, und zusätzlich Kunden, Lieferanten
  und Kontakte, CRM- und Personaldaten samt Anhängen.

Dazu kommt das Hilfs-Playbook **`passwoerter.yaml`**. Es setzt ein gemeinsames Passwort
für alle Benutzer.

Nur mit `--safety-backup` (siehe *Den Stand vor dem letzten Lauf zurückholen*) entsteht
zusätzlich **`wiederherstellen.yaml`**.

## Was bei jedem Zustand immer passiert

Jedes Playbook neutralisiert die Datenbank, damit das Testsystem nichts nach außen sendet:

- Alle geplanten Aktionen sind abgeschaltet — auch nach dem Modul-Update, das sie wieder
  einschalten würde: dafür gibt es nach dem Update (und nach dem Installieren zusätzlicher
  Module) einen eigenen Schritt.
- Alle Postausgangs- und Posteingangsserver sind abgeschaltet. Aktiv ist danach nur
  Odoos Platzhalter „neutralization - disable emails“, der jeden Versand ins Leere
  laufen lässt.
- Die Bankanbindung ist entfernt.
- **EBICS ist deinstalliert**, falls es installiert war — aber nur, wenn die EBICS-Schritte
  eingeschaltet sind (siehe unten). Konfiguration und Benutzer werden vor dem Start von
  Odoo deaktiviert und die EBICS-Passphrasen gelöscht; danach werden `account_ebics`,
  `account_ebics_batch` und `account_ebics_oe` so deinstalliert wie über das Apps-Menü.
- Odoo führt seine eigene Neutralisierung aus und blendet einen Hinweis ein, dass es
  sich um eine Testdatenbank handelt.

**Die Anmeldedaten stammen aus dem Live-System.** Nach jedem Lauf gelten die
Live-Passwörter. Behandeln Sie das Testsystem deshalb so vertraulich wie das
Live-System, oder setzen Sie danach ein gemeinsames Passwort (siehe unten).

## Zusätzliche Module installieren (optional)

Sollen nach jedem Neuaufsetzen bestimmte Module im Testsystem installiert sein, tragen Sie
sie beim Container `test-odoo` in `~/docker2update.yaml` ein, immer in einer Zeile:

```yaml
    install_modules: [eq_module_a, eq_module_b]
```

Angegeben werden die technischen Namen der Module (Buchstaben, Ziffern, Unterstrich).
Mit `wizup` (Menü 4) oder in `konsole` lässt sich die Liste ebenfalls setzen. Danach
`generate.py` neu ausführen: Jedes Playbook, das ein Backup einspielt (alle außer
`passwoerter.yaml`), enthält dann nach dem Neutralisieren den Schritt „Install additional
modules“. Dafür braucht es odoodev ab Version 0.78.0; die Kopfzeile des Playbooks nennt
die nötige Version. Ohne Eintrag ändert sich nichts. `update_docker_odoo.py` (`doup`)
ignoriert den Schlüssel.

Statt der Datei geht auch eine Angabe auf der Kommandozeile, sie hat Vorrang:
`python3 generate.py --version 18 --install-modules eq_module_a,eq_module_b --out ~/playbooks`.
`--install-modules ""` schaltet den Schritt für diesen Aufruf ab.

## EBICS-Schritte (nur bei Bedarf)

Die beiden EBICS-Schritte („Switch off EBICS“ und „Uninstall EBICS“) stehen nur in den
Playbooks, wenn Sie sie verlangen: `ebics: true` beim Test-Container in
`~/docker2update.yaml`, oder `python3 generate.py --version 18 --ebics --out ~/playbooks`.
`--no-ebics` hat Vorrang vor der Datei. Ohne Angabe fehlen beide Schritte; ein Wert, der
weder `true` noch `false` ist, wird mit einer Warnung als `false` gewertet. `generate.py`
zeigt am Ende, ob die Schritte enthalten sind.

## Einstellungen, die nur für das Testsystem gelten

Nach dem Einspielen stehen in der Datenbank die Werte von Live. Neutralisieren leert
außerdem den FastReport-Token. Was das Testsystem anders braucht, steht deshalb in einer
SQL-Datei auf dem Server, die nur `root` lesen kann:

```
/root/.config/odoodev/test-after-restore.sql
```

Gibt es die Datei, wenn `generate.py` läuft, führt jedes Playbook sie nach dem
Neutralisieren und nach den Zusatzmodulen aus und startet `test-odoo` danach neu. odoodev
liest die Datei erst beim Lauf. Passwörter und Tokens stehen so nie im Playbook. Ein
anderer Pfad geht mit `--after-restore-sql PFAD`, `--after-restore-sql ""` schaltet den
Schritt ab.

Beispiel:

```
UPDATE ir_config_parameter SET value = 'https://test.example.com' WHERE key = 'web.base.url';
UPDATE ir_config_parameter SET value = 'https://fr-test.example.com/api/reports' WHERE key = 'eq.fast.reports.server.api.url';
UPDATE ir_config_parameter SET value = '<Token von fr-test>' WHERE key = 'eq.fast.reports.server.api.token';
UPDATE res_users SET totp_secret = NULL, login = 'admin@example.com', password = '<Passwort>' WHERE id = 2;
```

Danach `chmod 600` auf die Datei und `generate.py` neu laufen lassen. Ein Passwort im
Klartext nimmt Odoo an und speichert es bei der ersten Anmeldung verschlüsselt.

## Der Ablauf

1. `test-odoo` wird gestoppt. **Ab hier ist das Testsystem nicht erreichbar.**
2. Das neueste Live-Backup wird eingespielt und je nach Zustand bereinigt. Entpackt wird
   es dafür in `/opt/backups/restore-tmp`. Die bisherige Datenbank wird erst ersetzt,
   wenn die neue vollständig eingespielt ist.
3. Nur mit EBICS-Schritten: EBICS wird abgeschaltet, bevor Odoo startet.
4. `doup` baut das Image neu, aktualisiert alle Module und startet Odoo. Danach werden
   die geplanten Aktionen wieder abgeschaltet, weil das Update sie einschaltet.
5. Nur mit EBICS-Schritten: EBICS wird deinstalliert, danach startet Odoo neu.
6. Odoo neutralisiert die Datenbank.
   Sind `install_modules` eingetragen, werden danach diese Module installiert und die
   geplanten Aktionen erneut abgeschaltet.
   Gibt es die Datei mit den Test-Einstellungen, wird sie danach ausgeführt und
   `test-odoo` neu gestartet.
7. Das Playbook prüft, ob Odoo gesund läuft, kein Modul hängen geblieben ist und die
   Anmeldeseite lädt. Erst danach ist das Testsystem einsatzbereit.

Welches Backup verwendet wird, entscheidet der Zeitstempel im Dateinamen. Es zählen
nur vollständige Backups mit Filestore; das mittägliche Backup nur der Datenbank
(`…_sql_only`) wird übersprungen. Ein Lauf
dauert bei einer Datenbank mit rund 2 GB Backup etwa 10 Minuten; den größten Teil
brauchen das Einspielen und das Modul-Update.

## So starten Sie ein Playbook

Alle Befehle als `root`, im Ordner mit den erzeugten Playbooks.

**1. Klären, ob jemand auf dem Testsystem arbeitet.** Alles seit dem letzten Lauf
Eingegebene wird überschrieben.

**2. Eine Sitzung öffnen, die einen Verbindungsabbruch übersteht**, zum Beispiel mit
`tmux`. Bricht die SSH-Verbindung ab, bricht sonst auch das Playbook ab.

**3. Prüfen, welches Backup eingespielt wird.** Der Generator hat das Muster beim
Erzeugen angezeigt; es steht auch im Playbook unter `pattern`. Die neueste Datei zeigt:

```
ls /opt/backups/docker/<Muster aus dem Playbook> | sort | tail -1
```

**4. Probelauf.** Er verändert nichts, prüft die Konfiguration und listet alle Schritte:

```
odoodev run neutral.yaml --dry-run
```

**5. Echter Lauf.** Derselbe Befehl ohne `--dry-run`. Ganz am Ende steht, ob alle
Schritte erfolgreich waren.

## Wenn etwas schiefgeht

Bei einem Fehler hält das Playbook sofort an.

- **Fehler vor oder beim Einspielen:** Die bisherige Datenbank ist in der Regel
  unverändert. `test-odoo` kann aber gestoppt sein (`docker start test-odoo`).
- **Fehler nach dem Einspielen:** Die neue Datenbank ist aktiv, aber noch nicht
  vollständig vorbereitet. Nutzen Sie das Testsystem so nicht.

Starten Sie das Playbook nicht einfach erneut, sondern sehen Sie sich die erste
Fehlermeldung an. Muss das Testsystem schnell wieder brauchbar sein, beheben Sie die
Ursache und starten Sie das Playbook danach neu. Es spielt das Live-Backup noch einmal
vollständig ein. Den vorherigen Stand gibt es nur, wenn die Playbooks mit
`--safety-backup` erzeugt wurden.

## Den Stand vor dem letzten Lauf zurückholen

Ein Testsystem wird bei jedem Lauf überschrieben. Deshalb sichern die Playbooks den alten
Stand standardmäßig **nicht**. Wer ihn behalten will, erzeugt die Playbooks mit
`--safety-backup`:

```
python3 generate.py --version 18 --safety-backup --out ~/playbooks
mkdir -p /opt/backups/prerestore
```

Dann sichert jedes Zustands-Playbook das Testsystem zuerst nach `/opt/backups/prerestore`,
und `wiederherstellen.yaml` spielt die jüngste Sicherung aus `/opt/backups/prerestore`
zurück, also den Stand vor dem letzten Lauf:

```
odoodev run wiederherstellen.yaml --dry-run
odoodev run wiederherstellen.yaml
```

- **Der aktuelle Stand wird dabei nicht gesichert.** Eine neue Sicherung wäre sonst
  selbst die jüngste und würde statt der gewünschten eingespielt.
- **Es geht immer nur einen Schritt zurück.** Ein zweiter Aufruf spielt dieselbe
  Sicherung noch einmal ein.
- **Auch der zurückgeholte Stand wird neutralisiert** (und, wenn die EBICS-Schritte eingeschaltet sind, EBICS deinstalliert).

## Ein gemeinsames Passwort setzen

`passwoerter.yaml` setzt für alle Benutzer einschließlich `admin` und Portalbenutzern
dasselbe Passwort und schaltet die Zwei-Faktor-Anmeldung ab. Die Anmeldenamen bleiben.

Einmalig und bei jedem Passwortwechsel das Passwort hinterlegen:

```
python3 passwort-setzen.py
```

Das Skript speichert nur eine verschlüsselte Form des Passworts in
`/root/.config/odoodev/test-passwords.env` (nur für `root` lesbar). Danach:

```
odoodev run passwoerter.yaml
```

Fehlt der erste Schritt, bricht das Playbook ab, ohne etwas zu ändern. **Nach jedem
Neuaufsetzen und Wiederherstellen gelten wieder die alten Passwörter**; starten Sie
`passwoerter.yaml` dann erneut.

## Speicherplatz

Ein Lauf braucht vorübergehend Platz für das entpackte Backup in `/opt/backups/restore-tmp`
und für den alten Filestore, bis der neue ihn ersetzt.

Mit `--safety-backup` legt zusätzlich jeder Lauf in `/opt/backups/prerestore` eine Sicherung
in der Größe des Backups ab. Sie wird nicht automatisch gelöscht. Behalten Sie mindestens die
jüngste, denn nur sie kann `wiederherstellen.yaml` zurückholen.

## Dateien

- `generate.py`: erzeugt die Playbooks aus der Konfiguration des Servers.
- `passwort-setzen.py`: hinterlegt das gemeinsame Testpasswort.
- `v16/`, `v18/`, `v19/`: Beispiel-Playbooks mit den Werten der Vorlagen.
