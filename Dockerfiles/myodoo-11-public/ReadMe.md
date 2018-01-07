## Build
docker build -t myodoo/myodoo-11-public:180101 .
docker push myodoo/myodoo-11-public:180101

# Start Postgres Container
docker run -d --restart=always -e POSTGRES_USER=myodoo -e POSTGRES_PASSWORD=myodoo --name "myodoo-11-db" postgres:9.6.6

## Run
docker run -d --restart=always -p 11069:8069 --name="myodoo-11-public" --link myodoo-11-db:db  myodoo/myodoo-11-public:180101 start

## Test
docker run -it --rm -p 11069:8069 --name="myodoo-11-public" --link myodoo-11-db:db  myodoo/myodoo-11-public:180101 start

## Filestore auf Host mounten
docker run -d --restart=always -p 11069:8069 --name="myodoo-11-public" -v ~/odoofilestore:/opt/odoo/data --link myodoo-11-db:db  myodoo/myodoo-11-public:180101 start
 
## Update
docker run -it --rm -p 11069:8069 --name="myodoo-10-public" --link myodoo-11-db:db myodoo/myodoo-11-public:180101 update --database=test --db_user=myodoo --db_password=myodoo --db_host=db

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