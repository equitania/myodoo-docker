# Myodoo-Docker
(c) 2016 till now by Equitania Software GmbH

## Vorbereitung

### Beim ersten Start

`git clone https://github.com/equitania/myodoo-docker.git`

### danach

`cp myodoo-docker/updateMyscripts.py /root/`

`./updateMyscripts.py`

## Skripte

### auto_backup_docker.py

Erstellt Backups aller MyOdoo Container, die in `containers2backup.csv` mit `,` als Separator definiert sind.

Dabei ist in der csv-Datei zuerst der Datenbankname, der Postgres-Containername sowie der MyOdoo-Containername anzugeben.  


### auto_update_docker.py

Führt Update aller MyOdoo Container, die in `containers2update.csv` mit `,` als Separator definiert sind und in der Spalte 1 das Wort `update` stehen haben.

Dabei ist in der csv-Datei zuerst der MyOdoo-Containername, der Datenbankname, der Port, der Pfad zum Dockerfile sowie der Postgres-Containername anzugeben.  

### auto_update_docker_with_same_image.py


### restore2docker.sh

Zum Restoren von Backups.
