# ownERP Prepare-V19 Docker Image
#### Basis-Image für Odoo 19 Container | Base Image for Odoo 19 Containers

---

## 🇩🇪 Deutsche Beschreibung

### Überblick
Dieses Docker-Image dient als Basis für Odoo 19-Installationen in Docker-Containern. Es enthält alle notwendigen Abhängigkeiten und Werkzeuge, die für den Betrieb von Odoo 19 erforderlich sind, ohne Odoo selbst zu installieren. 

### Basis des Images
- **Betriebssystem**: Debian Bookworm
- **Basis-Image**: python:3.12.x-bookworm (genaue Version siehe Tag)
- **Lokalisierung**: Deutsch (de_DE.UTF-8)
- **Zeitzone**: Europe/Berlin

### Inhalt des Images
- **System-Abhängigkeiten**:
  - build-essential, libldap2-dev, libsasl2-dev, libxml2-dev, libxslt-dev
  - git, wget, less, nano, mc, screen
  - Schriftarten und Font-Bibliotheken
  - PostgreSQL-Client (neueste Version)
  - Node.js (aktuelle Version) mit npm
  - wkhtmltopdf für PDF-Generierung (Version 0.12.6.1-3)

- **Wichtige Python-Bibliotheken**:
  - Web/HTTP: Werkzeug, Jinja2, requests, zeep, urllib3
  - Datenbank: psycopg2, python-ldap
  - Dateiformate: lxml, openpyxl, Pillow, reportlab, PyPDF2, xlrd, XlsxWriter
  - Datumsfunktionen: python-dateutil, pytz, Babel
  - Kryptographie: cryptography, pyopenssl, pycryptodome
  - Hilfsprogramme: num2words, python-stdnum, qrcode, vobject
  - Weitere Tools:
    - pandas, numpy
    - python-gitlab, GitPython
    - deepl, phonenumbers
    - paramiko, msal
    - openai

### Anwendungsbereich
Dieses Image wird als Grundlage für die Erstellung von produktionsreifen Odoo 19-Docker-Containern verwendet. Es enthält alle notwendigen Komponenten, damit Odoo reibungslos funktionieren kann, wobei die eigentliche Odoo-Installation in einem darauf aufbauenden Image erfolgt.

### Verwendung
```bash
# Pull des Images
docker pull myodoo/prepare-v19:TAG

# Verwendung als Basis in einem Dockerfile
FROM myodoo/prepare-v19:TAG
# Weitere Schritte zur Installation von Odoo...
```

### Version
Die Versionsnummer im Tag folgt dem Format `YY.MM.DD-PYTHON_VERSION` (z.B. `25.02.25-3.12.9`).

---

## 🇬🇧 English Description

### Overview
This Docker image serves as a base for Odoo 19 installations in Docker containers. It includes all necessary dependencies and tools required for running Odoo 19, without installing Odoo itself.

### Base of the Image
- **Operating System**: Debian Bookworm
- **Base Image**: python:3.12.x-bookworm (exact version in tag)
- **Localization**: German (de_DE.UTF-8)
- **Timezone**: Europe/Berlin

### Image Contents
- **System Dependencies**:
  - build-essential, libldap2-dev, libsasl2-dev, libxml2-dev, libxslt-dev
  - git, wget, less, nano, mc, screen
  - Fonts and font libraries
  - PostgreSQL client (latest version)
  - Node.js (current version) with npm
  - wkhtmltopdf for PDF generation (version 0.12.6.1-3)

- **Key Python Libraries**:
  - Web/HTTP: Werkzeug, Jinja2, requests, zeep, urllib3
  - Database: psycopg2, python-ldap
  - File formats: lxml, openpyxl, Pillow, reportlab, PyPDF2, xlrd, XlsxWriter
  - Date functions: python-dateutil, pytz, Babel
  - Cryptography: cryptography, pyopenssl, pycryptodome
  - Utilities: num2words, python-stdnum, qrcode, vobject
  - Additional tools:
    - pandas, numpy
    - python-gitlab, GitPython
    - deepl, phonenumbers
    - paramiko, msal
    - openai

### Scope
This image is used as a foundation for creating production-ready Odoo 19 Docker containers. It contains all necessary components for Odoo to function smoothly, with the actual Odoo installation happening in an image built on top of this one.

### Usage
```bash
# Pull the image
docker pull myodoo/prepare-v19:TAG

# Use as base in a Dockerfile
FROM myodoo/prepare-v19:TAG
# Further steps to install Odoo...
```

### Version
The version number in the tag follows the format `YY.MM.DD-PYTHON_VERSION` (e.g. `25.02.25-3.12.9`).

---

### Maintainer
ownERP.com
Website: [https://www.ownerp.com](https://www.ownerp.com) 