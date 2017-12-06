#!/bin/bash
## Install PageSpeed on Debian 8/9 and Ubuntu 16.04 64Bits
## https://www.howtoforge.com/tutorial/how-to-install-nginx-and-google-pagespeed-on-ubuntu-16-04/
## http://nginx.org/en/linux_packages.html
## https://www.modpagespeed.com/doc/build_ngx_pagespeed_from_source
## https://developers.google.com/speed/pagespeed/module/
## Debian ISO: https://cdimage.debian.org/cdimage/archive/8.9.0/amd64/iso-cd/
## https://github.com/jniltinho/ispconfig/tree/master/packages/debian/jessie
## https://github.com/pagespeed/ngx_pagespeed/releases
## Run as root (sudo su)
## Stand 25.10.2017

echo "deb http://nginx.org/packages/debian/ jessie nginx" >> /etc/apt/sources.list.d/nginx.list
echo "deb-src http://nginx.org/packages/debian/ jessie nginx" >> /etc/apt/sources.list.d/nginx.list

curl http://nginx.org/keys/nginx_signing.key | apt-key add -


apt-get update
apt-get install -y lsb-release dpkg-dev build-essential zlib1g-dev libpcre3 libpcre3-dev unzip curl

cd ~
mkdir -p ~/compile/nginx_source/
cd ~/compile/nginx_source/
apt-get source nginx
apt-get build-dep nginx

mkdir -p ~/compile/ngx_pagespeed/
cd ~/compile/ngx_pagespeed/
wget https://github.com/pagespeed/ngx_pagespeed/archive/v1.12.34.3-stable.zip
unzip v1.12.34.3-stable.zip


cd ngx_pagespeed-1.12.34.3-stable/
wget https://dl.google.com/dl/page-speed/psol/1.12.34.2-x64.tar.gz
tar -xzvf 1.12.34.2-x64.tar.gz

cd ~/compile/nginx_source/nginx-1.12.2/
sed -i "s|--with-http_auth_request_module|--with-http_auth_request_module --add-module=/root/compile/ngx_pagespeed/ngx_pagespeed-1.12.34.3-stable|" /root/compile/nginx_source/nginx-1.12.2/debian/rules
dpkg-buildpackage -b

cd ../
## Von der nginx.conf wird ein Backup gemacht
if [ -f /etc/nginx/nginx.conf ]; then service nginx stop; cp -aR /etc/nginx /etc/nginx_$$; fi
dpkg --force-all -i nginx_1.12.2-1~jessie_amd64.deb
## Von der nginx.conf wird wiederhergestellt
if [ -f "/etc/nginx_$$/nginx.conf" ]; then rm -rf /etc/nginx/*; cp -aR /etc/nginx_$$/* /etc/nginx/; fi


## Finalizierung
mkdir -p /var/ngx_pagespeed_cache && chmod 777 /var/ngx_pagespeed_cache


## Set on PageSpeed Config /etc/nginx/conf.d/default.conf
sed -i "s|# concurs with nginx's one|include /etc/nginx/mod_pagespeed.conf;|" /etc/nginx/sites-enabled/default

echo 'pagespeed on;
pagespeed FileCachePath /var/ngx_pagespeed_cache;
location ~ "\.pagespeed\.([a-z]\.)?[a-z]{2}\.[^.]{10}\.[^.]+" {
  add_header "" "";
}
location ~ "^/pagespeed_static/" { }
location ~ "^/ngx_pagespeed_beacon$" { }' >/etc/nginx/mod_pagespeed.conf


## Einstellungen der configs Nginx wird überprüft
nginx -t
nginx -V

## Neustart Nginx
service nginx restart