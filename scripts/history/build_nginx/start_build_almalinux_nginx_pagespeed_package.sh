#!/bin/bash
# Install latest nginx with pagedspeed
# Script must run with mit root-rights
# Version 1.3.1 - Stand 17.04.2022
##############################################################################
#
#    Shell Script for Odoo, Open Source Management Solution
#    Copyright (C) 2014-now Equitania Software GmbH(<http://www.equitania.de>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

# Update OS and get dependencies
sudo yum -y update && sudo yum -y group install 'Development Tools' && sudo yum -y install perl-core zlib-devel openssl-devel memcached
id -u nginx &>/dev/null || sudo adduser -r nginx

# Install latest nginx with pagespeed
# Quelle: https://github.com/apache/incubator-pagespeed-ngx/blob/master/scripts/build_ngx_pagespeed.sh
sudo bash $HOME/myodoo-docker/scripts/build_nginx/build_ngx_pagespeed.sh \
    --nginx-version latest --assume-yes \
    --additional-nginx-configure-arguments '--prefix=/etc/nginx --sbin-path=/usr/sbin/nginx --modules-path=/usr/lib/nginx/modules --conf-path=/etc/nginx/nginx.conf --error-log-path=/var/log/nginx/error.log --http-log-path=/var/log/nginx/access.log --pid-path=/var/run/nginx.pid --lock-path=/var/run/nginx.lock --http-client-body-temp-path=/var/cache/nginx/client_temp --http-proxy-temp-path=/var/cache/nginx/proxy_temp --http-fastcgi-temp-path=/var/cache/nginx/fastcgi_temp --http-uwsgi-temp-path=/var/cache/nginx/uwsgi_temp --http-scgi-temp-path=/var/cache/nginx/scgi_temp --user=nginx --group=nginx --with-http_ssl_module --with-http_v2_module'

# --prefix=/etc/nginx
# --sbin-path=/usr/sbin/nginx
# --modules-path=/usr/lib/nginx/modules
# --conf-path=/etc/nginx/nginx.conf
# --error-log-path=/var/log/nginx/error.log
# --http-log-path=/var/log/nginx/access.log
# --pid-path=/var/run/nginx.pid
# --lock-path=/var/run/nginx.lock
# --http-client-body-temp-path=/var/cache/nginx/client_temp
# --http-proxy-temp-path=/var/cache/nginx/proxy_temp
# --http-fastcgi-temp-path=/var/cache/nginx/fastcgi_temp
# --http-uwsgi-temp-path=/var/cache/nginx/uwsgi_temp
# --http-scgi-temp-path=/var/cache/nginx/scgi_temp
# --user=nginx
# --group=nginx
# --with-http_ssl_module
# --with-http_v2_module

# prepare nginx
FILE_PATH=/etc/nginx/

[ ! -d /var/cache/nginx/client_temp ] && sudo mkdir -p /var/cache/nginx/client_temp
[ ! -d $FILE_PATH ] && sudo mkdir -p
[ ! -d $FILE_PATH"html/" ] && sudo mkdir -p $FILE_PATH"html/"
[ ! -d $FILE_PATH"conf.d/" ] && sudo mkdir -p $FILE_PATH"conf.d/"

FILE=nginx.conf
if [ ! -f "$FILE_PATH$FILE" ]; then
    sudo cp $HOME/myodoo-docker/scripts/build_nginx/$FILE /etc/nginx/
else
    sudo mv /etc/nginx/$FILE /etc/nginx/$FILE.backup
    sudo cp $HOME/myodoo-docker/scripts/build_nginx/$FILE /etc/nginx/
    sed -i '1s|.*|user nginx;|' /etc/nginx/$FILE
fi

FILE=pagespeed_main.conf
if [ ! -f "$FILE_PATH$FILE" ]; then
    sudo cp $HOME/myodoo-docker/scripts/build_nginx/$FILE /etc/nginx/
else
    sudo mv /etc/nginx/$FILE /etc/nginx/$FILE.backup
    sudo cp $HOME/myodoo-docker/scripts/build_nginx/$FILE /etc/nginx/
fi

FILE=pagespeed_rules.conf
if [ ! -f "$FILE_PATH$FILE" ]; then
    sudo cp $HOME/myodoo-docker/scripts/build_nginx/$FILE /etc/nginx/
else
    sudo mv /etc/nginx/$FILE /etc/nginx/$FILE.backup
    sudo cp $HOME/myodoo-docker/scripts/build_nginx/$FILE /etc/nginx/
fi

# Maintenance Message
[ ! -f /etc/nginx/html/custom_50x.html ] && sudo cp $HOME/myodoo-docker/nginx-conf/custom_50x.html /etc/nginx/html/

# prepare pagespeed
FOLDER=/var/cache/ngx_pagespeed/
if [ ! -d "$FOLDER" ]; then
    sudo -p mkdir /var/cache/ngx_pagespeed/
    sudo chown -R www-data:www-data /var/cache/ngx_pagespeed/
fi

# Install & start service nginx
FILE=/lib/systemd/system/nginx.service
if [ ! -f "$FILE" ]; then
    sudo cp $HOME/myodoo-docker/scripts/build_nginx/nginx.service /lib/systemd/system/
    sudo systemctl enable nginx
    sudo systemctl start nginx
else
   sudo cp $HOME/myodoo-docker/scripts/build_nginx/nginx.service /lib/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl restart nginx
fi

echo "**********************************************"
echo "nginx installed"
echo "**********************************************"
echo "nginx version"
sudo nginx -V
echo "**********************************************"
echo ""

FOLDER=/etc/systemd/system/nginx.service.d
if [ ! -d "$FOLDER" ]; then
   sudo mkdir /etc/systemd/system/nginx.service.d
   sudo printf "[Service]\nExecStartPost=/bin/sleep 0.1\n" > /etc/systemd/system/nginx.service.d/override.conf
   sudo systemctl daemon-reload
   sudo systemctl restart nginx
fi

echo "**********************************************"
echo "nginx check"
sudo nginx -t
echo "**********************************************"

echo "**********************************************"
echo "memcached check"
sudo systemctl enable memcached
sudo systemctl start memcached
sudo systemctl status memcached
echo "**********************************************"


echo "Cleanup"
sudo rm -rf $HOME/incubator-pagespeed-ngx-latest-stable/
sudo rm -rf $HOME/nginx-1.*