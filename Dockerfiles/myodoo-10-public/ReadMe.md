## Build
docker build -t myodoo/myodoo-10-public:171002 .
docker push myodoo/myodoo-10-public:171002

docker run -d --restart=always -e POSTGRES_USER=myodoo10 -e POSTGRES_PASSWORD=myodoo10 --name "myodoo10-db" postgres:9.6.5

## Run
docker run -d --restart=always -p 9069:8069 --name="myodoo-10-public" --link myodoo10-db:db  myodoo/myodoo-10-public:171001 start

## Test
docker run -it --rm -p 9069:8069 --name="myodoo-10-public" --link myodoo10-db:db  myodoo/myodoo-10-public:171001 start
 
 
## Filestore auf Host mounten
docker run -d --restart=always -p 9069:8069 --name="myodoo-10-public" -v ~/odoofilestore:/opt/odoo/data --link myodoo10-db:db  myodoo/myodoo-10-public:171001 start
 
## Update
docker run -it --rm -p 9069:8069 --name="myodoo-10-public" --link myodoo10-db:db myodoo/myodoo-10-public:171001 update --database=test --db_user=myodoo10 --db_password=myodoo10 --db_host=db
 
 
## Update im Container
sudo -i -u odoo /usr/bin/python \
    /opt/odoo/odoo-server/odoo-bin \
    --update=all \
    --workers=0 \
    --no-xmlrpc \
    --database=test \
    --db_user=myodoo10 \
    --db_password=myodoo10 \
    --db_host=db \
    --stop-after-init

# Vorbereitete Datenbank ohne Kontenrahmen
https://release.myodoo.de/v10_basis_public_Build_170901_admin_myodoo2017.zip
 
# bash Zugriff
docker exec -ti "myodoo-10-public" env TERM=xterm bash -l
