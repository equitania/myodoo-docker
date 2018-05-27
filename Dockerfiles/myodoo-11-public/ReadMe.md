## Build
`docker build -t myodoo/myodoo-11-public:180527 .`
`docker push myodoo/myodoo-11-public:180527`

# Start Postgres Container

## Start Postgres Container
`docker run -d --restart=always -e POSTGRES_USER=myodoo -e POSTGRES_PASSWORD=myodoo --name "myodoo-11-db" postgres:9.6.9`

## Start Postgres Container mit mount Host Filesystem
`docker run -d --restart=always -v /opt/postgresql/pg-data/:/var/lib/postgresql/data/ -e POSTGRES_USER=myodoo -e POSTGRES_PASSWORD=myodoo --name "myodoo-11-db" postgres:9.6.9`

## Start Postgres Container mit Docker Volume mount
`docker run -d --restart=always -v pg-myodoo11:/var/lib/postgresql/data/ -e POSTGRES_USER=myodoo -e POSTGRES_PASSWORD=myodoo --name "myodoo-11-db" postgres:9.6.9`
### Pfad zum Volume anzeigen
`docker inspect -f '{{ .Mounts }}' myodoo-11-db`
**oder für alle Container** 
`docker ps -q | xargs docker container inspect -f '{{ .Name }} {{ .HostConfig.Binds }}'`

### bash Zugriff Postgres
`docker exec -ti "myodoo-11-db" env COLUMNS=$COLUMNS LINES=$LINES TERM=$TERM bash -l`
`cd /var/lib/postgresql/data`
### Links Optimierungswebsite für Postgres http://pgtune.leopard.in.ua/ oder https://www.pgconfig.org/#/tuning 
**Änderungen zur Optimierung**
`sudo nano /var/lib/docker/volumes/pg-myodoo11/_data/postgresql.conf`  
**danach Container neu starten mit** `docker restart myodoo-11-db`  
#### Überprüfung  
`docker exec -ti "myodoo-11-db" env COLUMNS=$COLUMNS LINES=$LINES TERM=$TERM bash -l`  
`su postgres`  
`psql`  
**z.B. Parameter shared_buffers **
`SHOW shared_buffers;`


### pgAdmin 4 https://hub.docker.com/r/myodoo/pgadmin4/

## Run
`docker run -d --restart=always -p 11069:8069 --name="myodoo-11-public" --link myodoo-11-db:db  myodoo/myodoo-11-public:180527 start`    

## Test
`docker run -it --rm -p 11069:8069 --name="myodoo-11-public" --link myodoo-11-db:db  myodoo/myodoo-11-public:180527 start`  

## Filestore auf Host mounten
`docker run -d --restart=always -p 11069:8069 --name="myodoo-11-public" -v /opt/odoo/data:/opt/odoo/data --link myodoo-11-db:db  myodoo/myodoo-11-public:180527 start`  
 
## Filestore auf Docker Volume mounten
`docker run -d --restart=always -p 11069:8069 --name="myodoo-11-public" -v myodoo11:/opt/odoo/data --link myodoo-11-db:db  myodoo/myodoo-11-public:180527 start`  


## Update
`docker run -it --rm -p 11069:8069 --name="myodoo-10-public" --link myodoo-11-db:db myodoo/myodoo-11-public:180527 update --database=test --db_user=myodoo --db_password=myodoo --db_host=db`    

## Update im Container
`sudo -i -u odoo /usr/bin/python3 \
    /opt/odoo/odoo-server/odoo-bin \
    --update=all \
    --workers=0 \
    --no-xmlrpc \
    --database=test \
    --db_user=myodoo \
    --db_password=myodoo \
    --db_host=db \
    --stop-after-init`  

# Vorbereitete Datenbank ohne Kontenrahmen

 
# bash Zugriff
`docker exec -ti "myodoo-11-public" env COLUMNS=$COLUMNS LINES=$LINES TERM=$TERM bash -l`

# Weitere Dokumentationen zum Thema Docker:
https://equitania.atlassian.net/wiki/x/BABRAw

# Anleitung für den Betrieb unter Synology finden Sie hier:
https://equitania.atlassian.net/wiki/x/Pb1XAw
