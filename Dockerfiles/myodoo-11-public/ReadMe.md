## Build
docker build -t myodoo/myodoo-11-public:180510 .
docker push myodoo/myodoo-11-public:180510

# Start Postgres Container

# Start Postgres Container
docker run -d --restart=always -e POSTGRES_USER=myodoo -e POSTGRES_PASSWORD=myodoo --name "myodoo-11-db" postgres:9.6.8
# Start Postgres Container mit mount Host Filesystem
docker run -d --restart=always -v /opt/postgresql/pg-data/:/var/lib/postgresql/data/ -e POSTGRES_USER=myodoo -e POSTGRES_PASSWORD=myodoo --name "myodoo-11-db" postgres:9.6.8
### Links Optimierungswebsite für Postgres http://pgtune.leopard.in.ua/ oder https://www.pgconfig.org/#/tuning 

### pgAdmin 4 https://hub.docker.com/r/myodoo/pgadmin4/

## Run
docker run -d --restart=always -p 11069:8069 --name="myodoo-11-public" --link myodoo-11-db:db  myodoo/myodoo-11-public:180510 start

## Test
docker run -it --rm -p 11069:8069 --name="myodoo-11-public" --link myodoo-11-db:db  myodoo/myodoo-11-public:180510 start

## Filestore auf Host mounten
docker run -d --restart=always -p 11069:8069 --name="myodoo-11-public" -v /opt/odoo/data:/opt/odoo/data --link myodoo-11-db:db  myodoo/myodoo-11-public:180510 start
 
## Update
docker run -it --rm -p 11069:8069 --name="myodoo-10-public" --link myodoo-11-db:db myodoo/myodoo-11-public:180510 update --database=test --db_user=myodoo --db_password=myodoo --db_host=db

## Update im Container
sudo -i -u odoo /usr/bin/python3 \
    /opt/odoo/odoo-server/odoo-bin \
    --update=all \
    --workers=0 \
    --no-xmlrpc \
    --database=test \
    --db_user=myodoo \
    --db_password=myodoo \
    --db_host=db \
    --stop-after-init

# Vorbereitete Datenbank ohne Kontenrahmen

 
# bash Zugriff
docker exec -ti "myodoo-11-public" env TERM=xterm bash -l

# Weitere Dokumentationen zum Thema Docker:
https://equitania.atlassian.net/wiki/x/BABRAw

# Anleitung für den Betrieb unter Synology finden Sie hier:
https://equitania.atlassian.net/wiki/x/Pb1XAw