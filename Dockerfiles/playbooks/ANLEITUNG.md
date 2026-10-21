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
mkdir -p /opt/backups/prerestore /opt/backups/restore-tmp
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

Dazu kommen zwei Hilfs-Playbooks:

- **`wiederherstellen.yaml`** holt den Stand vor dem letzten Lauf zurück.
- **`passwoerter.yaml`** setzt ein gemeinsames Passwort für alle Benutzer.

## Was bei jedem Zustand immer passiert

Jedes Playbook neutralisiert die Datenbank, damit das Testsystem nichts nach außen sendet:

- Alle geplanten Aktionen sind abgeschaltet.
- Alle Postausgangs- und Posteingangsserver sind abgeschaltet. Aktiv ist danach nur
  Odoos Platzhalter „neutralization - disable emails“, der jeden Versand ins Leere
  laufen lässt.
- Die Bankanbindung ist entfernt.
- **EBICS ist deinstalliert**, falls es installiert war. Konfiguration und Benutzer werden
  vor dem Start von Odoo deaktiviert und die EBICS-Passphrasen gelöscht; danach werden
  `account_ebics`, `account_ebics_batch` und `account_ebics_oe` so deinstalliert wie
  über das Apps-Menü.
- Odoo führt seine eigene Neutralisierung aus und blendet einen Hinweis ein, dass es
  sich um eine Testdatenbank handelt.

**Die Anmeldedaten stammen aus dem Live-System.** Nach jedem Lauf gelten die
Live-Passwörter. Behandeln Sie das Testsystem deshalb so vertraulich wie das
Live-System, oder setzen Sie danach ein gemeinsames Passwort (siehe unten).

## Der Ablauf

1. Der aktuelle Stand des Testsystems wird nach `/opt/backups/prerestore` gesichert.
2. `test-odoo` wird gestoppt. **Ab hier ist das Testsystem nicht erreichbar.**
3. Das neueste Live-Backup wird eingespielt und je nach Zustand bereinigt. Entpackt wird
   es dafür in `/opt/backups/restore-tmp`. Die bisherige Datenbank wird erst ersetzt,
   wenn die neue vollständig eingespielt ist.
4. EBICS wird abgeschaltet, bevor Odoo startet.
5. `doup` baut das Image neu, aktualisiert alle Module und startet Odoo.
6. EBICS wird deinstalliert, danach startet Odoo neu.
7. Odoo neutralisiert die Datenbank.
8. Das Playbook prüft, ob Odoo gesund läuft, kein Modul hängen geblieben ist und die
   Anmeldeseite lädt. Erst danach ist das Testsystem einsatzbereit.

Welches Backup verwendet wird, entscheidet der Zeitstempel im Dateinamen. Ein Lauf
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
Fehlermeldung an. Muss das Testsystem schnell wieder brauchbar sein, holen Sie den
vorherigen Stand zurück.

## Den Stand vor dem letzten Lauf zurückholen

`wiederherstellen.yaml` spielt die jüngste Sicherung aus `/opt/backups/prerestore`
zurück, also den Stand vor dem letzten Lauf:

```
odoodev run wiederherstellen.yaml --dry-run
odoodev run wiederherstellen.yaml
```

- **Der aktuelle Stand wird dabei nicht gesichert.** Eine neue Sicherung wäre sonst
  selbst die jüngste und würde statt der gewünschten eingespielt.
- **Es geht immer nur einen Schritt zurück.** Ein zweiter Aufruf spielt dieselbe
  Sicherung noch einmal ein.
- **Auch der zurückgeholte Stand wird neutralisiert** und EBICS deinstalliert.

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

Jeder Lauf legt in `/opt/backups/prerestore` eine Sicherung in der Größe des Backups ab.
Sie wird nicht automatisch gelöscht. Behalten Sie mindestens die jüngste, denn nur sie
kann `wiederherstellen.yaml` zurückholen.

## Dateien

- `generate.py`: erzeugt die Playbooks aus der Konfiguration des Servers.
- `passwort-setzen.py`: hinterlegt das gemeinsame Testpasswort.
- `v16/`, `v18/`, `v19/`: Beispiel-Playbooks mit den Werten der Vorlagen.
