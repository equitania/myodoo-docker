# Myodoo-Docker

(c) 2016 till now by Equitania Software GmbH

[🇩🇪 Deutsch](#deutsch) | [🇬🇧 English](#english)

<a name="deutsch"></a>
## Deutsch

### Vorbereitung

#### Beim ersten Start

`git clone https://github.com/equitania/myodoo-docker.git`

#### Danach

`cp myodoo-docker/getScripts.py /root/`

`./getScripts.py`

### Über dieses Repository

Dieses Repository bietet Hilfsskripte und Dockerfiles für den MyOdoo Fork https://www.myodoo.de.
Wir benutzen es bei unseren täglichen Administrationstätigkeiten mit den Kunden Systemen.

### Bereiche:

1. Dockerfiles
2. Hilfsskripte für Installation, Updates & Backups

Weiterführende Informationen finden Sie in unserem WIKI https://equitania.atlassian.net/wiki/spaces/MW/overview

#### Branch wechseln

```shell
cd $HOME && rm -rf myodoo-docker && rm -rf nginx-conf && \
  git clone -b 2024 https://github.com/equitania/myodoo-docker.git && \
  cp myodoo-docker/getScripts.py $HOME && \
  $HOME/getScripts.py && source ~/.zshrc
```

<a name="english"></a>
## English

### Preparation

#### First Time Setup

`git clone https://github.com/equitania/myodoo-docker.git`

#### Next Steps

`cp myodoo-docker/getScripts.py /root/`

`./getScripts.py`

### About this Repository

This repository provides helper scripts and Dockerfiles for the MyOdoo Fork https://www.myodoo.de.
We use it in our daily administration activities with customer systems.

### Areas:

1. Dockerfiles
2. Helper scripts for installation, updates & backups

For more detailed information, please visit our WIKI https://equitania.atlassian.net/wiki/spaces/MW/overview

#### Exchange Branch

```shell
cd $HOME && rm -rf myodoo-docker && rm -rf nginx-conf && \
  git clone -b 2024 https://github.com/equitania/myodoo-docker.git && \
  cp myodoo-docker/getScripts.py $HOME && \
  $HOME/getScripts.py && source ~/.zshrc
```

---

For more information:
- [ownERP.com](https://www.ownerp.com)
- [Technical source](https://github.com/equitania/myodoo-docker)
