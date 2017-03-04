
## Build
docker build -t myodoo/myodoo-10:170301 .

docker run -d --restart=always -e POSTGRES_USER=myodoo10 -e POSTGRES_PASSWORD=myodoo10 --name "myodoo10-db" postgres:9.4

## Run
docker run -d --restart=always -p 9069:8069 --name="myodoo-10" --link myodoo10-db:db  myodoo/myodoo-10:170301 start

## test
docker run -it --rm -p 9069:8069 --name="myodoo-10" --link myodoo10-db:db  myodoo/myodoo-10:170301 start
 
 
## Filestore auf Host mounten
docker run -d --restart=always -p 9069:8069 --name="myodoo-10" -v ~/odoofilestore:/opt/odoo/data --link myodoo10-db:db  myodoo/myodoo-10:170301 start
 
## Update
docker run -it --rm -p 8069:8069 --name="myodoo-10" --link myodoo10-db:db myodoo/myodoo-10:170301 update --database=test --db_user=myodoo10 --db_password=myodoo10 --db_host=db
 
 
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
 
 
# bash Zugriff
docker exec -ti "myodoo-10" env TERM=xterm bash -l
