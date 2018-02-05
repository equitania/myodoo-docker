## Build
docker build -t myodoo/myodoo-10-public:180201 .
docker push myodoo/myodoo-10-public:180201

# Start Postgres Container
docker run -d --restart=always -e POSTGRES_USER=myodoo -e POSTGRES_PASSWORD=myodoo --name "myodoo-10-db" postgres:9.6.6

## Run
docker run -d --restart=always -p 10069:8069 --name="myodoo-10-public" --link myodoo-10-db:db  myodoo/myodoo-10-public:180201 start

## Test
docker run -it --rm -p 10069:8069 --name="myodoo-10-public" --link myodoo-10-db:db  myodoo/myodoo-10-public:180201 start

## Filestore auf Host mounten
docker run -d --restart=always -p 10069:8069 --name="myodoo-10-public" -v ~/odoofilestore:/opt/odoo/data --link myodoo-10-db:db  myodoo/myodoo-10-public:180201 start
 
## Update
docker run -it --rm -p 10069:8069 --name="myodoo-10-public" --link myodoo-10-db:db myodoo/myodoo-10-public:180201 update --database=test --db_user=myodoo --db_password=myodoo --db_host=db

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