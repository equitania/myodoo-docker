#!/bin/bash
## Install PageSpeed on Debian 8/9 and Ubuntu 16.04 64Bits
## https://www.howtoforge.com/tutorial/how-to-install-nginx-and-google-pagespeed-on-ubuntu-16-04/
## http://nginx.org/en/linux_packages.html
## https://www.modpagespeed.com/doc/build_ngx_pagespeed_from_source
## https://developers.google.com/speed/pagespeed/module/
## Debian ISO: https://cdimage.debian.org/cdimage/archive/8.9.0/amd64/iso-cd/
## https://github.com/jniltinho/ispconfig/tree/master/packages/debian/jessie
## Run as root (sudo su)


echo "deb http://nginx.org/packages/debian/ jessie nginx" >> /etc/apt/sources.list.d/nginx.list
echo "deb-src http://nginx.org/packages/debian/ jessie nginx" >> /etc/apt/sources.list.d/nginx.list

curl http://nginx.org/keys/nginx_signing.key | apt-key add -


NPS_VERSION=1.12.34.3-stable
NPS_RELEASE_NUMBER=${NPS_VERSION/stable/}

sed -i "s|# deb-src|deb-src|" /etc/apt/sources.list
apt-get update
apt-get install -y lsb-release dpkg-dev build-essential zlib1g-dev libpcre3 libpcre3-dev unzip curl

cd ~
mkdir -p ~/nginx_source/
cd ~/nginx_source/
apt-get source nginx

rm -rf /var/lib/apt/lists/
apt-get update
apt-get build-dep -y nginx

sed -i "s|deb-src|# deb-src|" /etc/apt/sources.list

cd ~
wget https://github.com/pagespeed/ngx_pagespeed/archive/v${NPS_VERSION}.tar.gz
tar xvfz v${NPS_VERSION}.tar.gz

cd ngx_pagespeed-${NPS_VERSION}/
psol_url=https://dl.google.com/dl/page-speed/psol/${NPS_RELEASE_NUMBER}.tar.gz
psol_url=$(scripts/format_binary_url.sh PSOL_BINARY_URL)
wget ${psol_url}
tar -xzvf $(basename ${psol_url})

sed -i "s|--with-http_auth_request_module|--with-http_auth_request_module --add-module=$HOME/ngx_pagespeed-${NPS_VERSION}|" $HOME/nginx_source/nginx-1.*.*/debian/rules
cd ~/nginx_source/nginx-1.*.*/
dpkg-buildpackage -b

cd ../
## Von der nginx.conf wird ein Backup gemacht
if [ -f /etc/nginx/nginx.conf ]; then service nginx stop; cp -aR /etc/nginx /etc/nginx_$$; fi
dpkg --force-all -i nginx_1.*_all.deb nginx-common_1.*_all.deb nginx-full_1.*_amd64.deb
## Von der nginx.conf wird wiederhergestellt
if [ -f "/etc/nginx_$$/nginx.conf" ]; then rm -rf /etc/nginx/*; cp -aR /etc/nginx_$$/* /etc/nginx/; fi


## Para Finalizar
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