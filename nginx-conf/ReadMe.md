# Create configurations for nginx   
  
The python script set_ngx_site_conf.py helps you to create configurations for different most docker based applications with nginx as reverse proxy.  
  
- Odoo  
- FastReport  
- NextCloud   
- Visual Code for browser 
- ...  
  
To run you can use it with or without parameters. Than the script will ask you.  
  
For the full power you should build your own nginx with pagespeed and memcache  
[Build your own nginx](https://github.com/equitania/myodoo-docker/blob/2020/scripts/build_nginx/build_nginx_pagespeed_package.sh)  
  

```shell    
./set_ngx_site_conf.py --help
Starting create nginx conf 
Basepath: /root/nginx-conf
Serverpath: /etc/nginx/conf.d/
Usage: set_ngx_site_conf.py [OPTIONS]

Options:
  --conf TEXT      Insert the conf-template.
                   
                   We support:
                   
                   - ngx_odoo_ssl_pagespeed (Odoo with ssl and PageSpeed)
                   - ngx_fast_report (FastReport with ssl)
                   - ngx_code_server (code-server with ssl)
                   - ngx_nextcloud (NextCloud with ssl)
                   - ngx_odoo_http (Odoo only http)
                   - ngx_odoo_ssl (Odoo with ssl)
                   - ngx_pgadmin (pgAdmin4 with ssl)
                   - ngx_pwa (Progressive Web App with ssl)
                   - ngx_redirect_ssl (Redirect Domain with ssl)
                   - ngx_redirect (Redirect Domain without ssl) 
                   
                   Files with the same name + .conf has to be stored in the
                   same folder.  [required]

  --ip TEXT        IP address of the server  [required]
  --domain TEXT    Name of the domain  [required]
  --port TEXT      Primary port for the Docker container  [required]
  --cert TEXT      Name of certificate
  --pollport TEXT  Secondary Docker container port for odoo pollings
  --help           Show this message and exit.
```
