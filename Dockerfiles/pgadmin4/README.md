#pgAdmin4 in docker container - Version 3.2

## Build
`docker build -t myodoo/pgadmin4:3.2 .`   
`docker push myodoo/pgadmin4:3.2`  
  
  
**Quick start**
  
##### Prepare if storage setting external
mkdir -p /home/user/.config/pgadmin

##### Test  
`$ docker run -it -rm --name="pgadmin4" -p 5050:5050 -v /home/user/.config/pgadmin:/var/lib/pgadmin myodoo/pgadmin4:3.2`
  
##### Run
`$ docker run -d --restart=always --name="pgadmin4" -p 5050:5050 -v /home/user/.config/pgadmin:/var/lib/pgadmin myodoo/pgadmin4:3.2`
  
##### Run & Link in a PostgreSQL Docker Container
`$ docker run -d --restart=always -v /opt/postgresql/myodoo/:/var/lib/postgresql/data/ -e POSTGRES_USER=myodoo -e POSTGRES_PASSWORD=myodoo --name "myodoo-db" postgres:9.6.10`
`$ docker run -d --restart=always --name="pgadmin4" -p 5050:5050 --link myodoo-db:myodoo-db -v /home/user/.config/pgadmin:/var/lib/pgadmin myodoo/pgadmin4:3.2`


##Environment Variables

**DEFAULT_USER**  
`default 'pg@ownerp.io'`  
  
**DEFAULT_PASSWORD**  
`default 'ownerp2018'`    
   
**MAIL_SERVER**  
`default 'localhost'`  
  
**MAIL_PORT**  
`default 25`  
  
**MAIL_USE_SSL**  
`default False`  
  
**MAIL_USE_TLS**  
`default False`  

**MAIL_USERNAME**  
`default None`  
  
**MAIL_PASSWORD**  
`default None`  
