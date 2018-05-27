#pgAdmin4 in docker container - Version 3.0

## Build
`docker build -t myodoo/pgadmin4:3.0 .`   
`docker push myodoo/pgadmin4:3.0`  
  
  
**Quick start**
  
##### Prepare if storage setting external
mkdir -p /home/user/.config/pgadmin

##### Test  
`$ docker run -it -rm --name="pgadmin4" -p 5050:5050 -v /home/user/.config/pgadmin:/var/lib/pgadmin myodoo/pgadmin4:3.0`
  
##### Run
`$ docker run -d --restart=always --name="pgadmin4" -p 5050:5050 -v /home/user/.config/pgadmin:/var/lib/pgadmin myodoo/pgadmin4:3.0`
  
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
