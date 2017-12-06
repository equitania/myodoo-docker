## Build
docker build -t myodoo/myodoo-10-public:171201 .
docker push myodoo/myodoo-10-public:171201

docker run -d --restart=always -e POSTGRES_USER=myodoo -e POSTGRES_PASSWORD=myodoo --name "myodoo-db" postgres:9.6.5

## Run
docker run -d --restart=always -p 8069:8069 --name="myodoo-10-public" --link myodoo-db:db  myodoo/myodoo-10-public:171201 start

## Test
docker run -it --rm -p 8069:8069 --name="myodoo-10-public" --link myodoo-db:db  myodoo/myodoo-10-public:171201 start
 
 
## Filestore auf Host mounten
docker run -d --restart=always -p 8069:8069 --name="myodoo-10-public" -v ~/odoofilestore:/opt/odoo/data --link myodoo10-db:db  myodoo/myodoo-10-public:171201 start
 
## Update
docker run -it --rm -p 8069:8069 --name="myodoo-10-public" --link myodoo-db:db myodoo/myodoo-10-public:171201 update --database=test --db_user=myodoo --db_password=myodoo --db_host=db
 
 
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
https://release.myodoo.de/v10_basis_public_Build_171001_admin_myodoo2017.zip
 
# bash Zugriff
docker exec -ti "myodoo-10-public" env TERM=xterm bash -l
