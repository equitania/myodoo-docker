# Current status 29.12.2020 - **Password ../web/database/manager: ownerp2020**  
  
### Create network
```
docker network create ownerp-net  
```
### Create volumes
```
docker volume create vol-pg-live
docker volume create vol-odoo-live
```
### Start Postgres Container
```
docker run -d --restart=always \
       -e POSTGRES_USER=ownerp \
       -e POSTGRES_PASSWORD=ownerp2020 \
       -e POSTGRES_DB=postgres \
       --name=live-db \
       --network=ownerp-net \
       postgres:12.5-alpine
```
### Start Postgres Container with Docker volume mount
```
docker run -d --restart=always \
       -e POSTGRES_USER=ownerp \
       -e POSTGRES_PASSWORD=ownerp2020 \
       -e POSTGRES_DB=postgres \
       --name=live-db \
       --network=ownerp-net \
       --volume=vol-pg-live:/var/lib/postgresql/data/ \
       postgres:12.5-alpine
```
### Path to volume
```
docker inspect -f '{{ .Mounts }}' live-db
or all containers
docker ps -q | xargs docker container inspect -f '{{ .Name }} {{ .HostConfig.Binds }}'
```
### bash acces Postgres
```
docker exec -ti "live-db" env COLUMNS=$COLUMNS LINES=$LINES TERM=$TERM bash -l
cd /var/lib/postgresql/data
```
### Links PostgreSQL optimize [pgtune](http://pgtune.leopard.in.ua/) or [pgconfig](https://www.pgconfig.org/#/tuning)   
  
**Path for PostgreSQL settings*  
```
sudo nano /var/lib/docker/volumes/vol-pg-live/_data/postgresql.conf
```
**after that restart container** `docker restart live-db`    
  
 
### Run
```
docker run -d --restart=always \
       -p 8069:8069 \
       -p 8072:8072 \
       --network ownerp-net \
       --name=myodoo-13-public \
       myodoo/myodoo-13-public:201229 start
```
### Test
```
docker run -it --rm --restart=always \
       --port=8069:8069 \
       --port=8072:8072 \
       --network ownerp-net \
       --name=myodoo-13-public \
       myodoo/myodoo-13-public:201229 start
```
### Filestore mount to docker volume
```
docker run -d --restart=always \
       -p 8069:8069 \
       -p 8072:8072 \
       --network ownerp-net \
       --name=myodoo-13-public \
       --volume=vol-odoo-live:/opt/odoo/data \
       myodoo/myodoo-13-public:201229 start
```
### nginx
[Templates for nginx for Odoo](https://github.com/equitania/myodoo-docker/tree/2020/nginx-conf)  
  
### Update
**Note: `--database=test` should your database name!**  
```
docker run -it --rm --restart=always \
       --network ownerp-net \
       --name=myodoo-13-public \
       myodoo/myodoo-13-public:201229 update \
       --database=test \
       --db_user=ownerp \
       --db_password=ownerp2020 \
       --db_host=live-db
```
or  
**Note: `--database=test` should your database name!**  
```
docker run -it --rm --restart=always \
       --network ownerp-net \
       --volume=vol-odoo-live:/opt/odoo/data \
       --name=myodoo-13-public \
       myodoo/myodoo-13-public:201229 update \
       --database=test \
       --db_user=ownerp \
       --db_password=ownerp2020 \
       --db_host=live-db
```

### Update in container
```
sudo -i -u odoo /usr/bin/python3 \  
    /opt/odoo/odoo-server/odoo-bin \  
    --update=all \  
    --workers=0 \  
    --no-xmlrpc \  
    --database=test \  
    --db_user=ownerp \  
    --db_password=ownerp2020 \  
    --db_host=live-db \  
    --stop-after-init`    
```

### bash access
`docker exec -ti "myodoo-13-public" env COLUMNS=$COLUMNS LINES=$LINES TERM=$TERM bash -l`  

For more infomations [MyOdoo.de](https://www.myodoo.de) or [ownERP.com](https://www.ownerp.com)  
[Technical source](https://github.com/equitania/myodoo-docker)