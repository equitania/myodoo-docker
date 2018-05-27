## Build
docker build -t myodoo/myodoo-10-public:180527 .
docker push myodoo/myodoo-10-public:180527

# Start Postgres Container
docker run -d --restart=always -e POSTGRES_USER=myodoo -e POSTGRES_PASSWORD=myodoo --name "myodoo-10-db" postgres:9.6.9

# Start Postgres Container mit mount Host Filesystem
docker run -d --restart=always -v /opt/postgresql/pg-data/:/var/lib/postgresql/data/ -e POSTGRES_USER=myodoo -e POSTGRES_PASSWORD=myodoo --name "myodoo-10-db" postgres:9.6.9

### Links Optimierungswebsite für Postgres http://pgtune.leopard.in.ua/ oder https://www.pgconfig.org/#/tuning 

### pgAdmin 4 https://hub.docker.com/r/myodoo/pgadmin4/

## Run
docker run -d --restart=always -p 10069:8069 --name="myodoo-10-public" --link myodoo-10-db:db  myodoo/myodoo-10-public:180527 start

## Test
docker run -it --rm -p 10069:8069 --name="myodoo-10-public" --link myodoo-10-db:db  myodoo/myodoo-10-public:180527 start

## Filestore auf Host mounten
docker run -d --restart=always -p 10069:8069 --name="myodoo-10-public" -v /opt/odoo/data:/opt/odoo/data --link myodoo-10-db:db  myodoo/myodoo-10-public:180527 start
 
## Update
docker run -it --rm -p 10069:8069 --name="myodoo-10-public" --link myodoo-10-db:db myodoo/myodoo-10-public:180527 update --database=test --db_user=myodoo --db_password=myodoo --db_host=db

## Update im Container
sudo -i -u odoo /usr/bin/python \
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
https://release.myodoo.de/public/v10_basis_public_build_180101_admin_myodoo2018.zip
admin_passwd = myodoo2018

# bash Zugriff
docker exec -ti "myodoo-10-public" env TERM=xterm bash -l

# Weitere Dokumentationen zum Thema Docker:
https://equitania.atlassian.net/wiki/x/BABRAw

# Anleitung für den Betrieb unter Synology finden Sie hier:
https://equitania.atlassian.net/wiki/x/Pb1XAw