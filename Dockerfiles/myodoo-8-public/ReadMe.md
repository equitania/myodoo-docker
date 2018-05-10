## Release aktualisieren
./getMyOdooRelease.sh
 
 
## Build
docker build -t myodoo/public-myodoo:180510 .
docker push myodoo/public-myodoo:180510


## Run
docker run -d --restart=always -p 8069:8069 --name="public-myodoo" --link myodoo-db:db  myodoo/public-myodoo:180510 start
 
## Filestore auf Host mounten
docker run -d --restart=always -p 8069:8069 --name="public-myodoo" -v /opt/odoo/data:/opt/odoo/data --link myodoo-db:db  myodoo/public-myodoo:180510 start
 
## Update
docker run -it --rm -p 8069:8069 --name="public-myodoo" --link myodoo-db:db  myodoo/public-myodoo:180201 update --database=test --db_user=myodoo --db_password=myodoo --db_host=db
 
 
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
