## Release aktualisieren
./getMyOdooRelease.sh
 
 
## Build
docker build -t myodoo/public-myodoo:170102 .

docker push myodoo/public-myodoo:170102


## Run
docker run -d --restart=always -p 8069:8069 --name="public-myodoo" --link myodoo-db:db  myodoo/public-myodoo:latest start
 
## Filestore auf Host mounten
docker run -d --restart=always -p 8069:8069 --name="public-myodoo" -v ~/odoofilestore:/opt/odoo/data --link myodoo-db:db  myodoo/public-myodoo:latest start
 
## Update
docker run -it --rm -p 8069:8069 --name="public-myodoo" --link myodoo-db:db  myodoo/public-myodoo:latest update --database=test --db_user=myodoo --db_password=myodoo --db_host=db
 
 
## Update im Container
sudo -i -u odoo /usr/bin/python \
    /opt/odoo/odoo-server/odoo.py \
    --update=all \
    --workers=0 \
    --no-xmlrpc \
    --database=test \
    --db_user=myodoo \
    --db_password=myodoo \
    --db_host=db \
    --stop-after-init
 
 
# bash Zugriff
docker exec -ti "public-myodoo" env TERM=xterm bash -l