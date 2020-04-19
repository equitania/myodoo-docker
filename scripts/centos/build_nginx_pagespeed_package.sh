#!/bin/bash
# Install latest nginx with pagedspeed
# Script must run with mit root-rights
# Version 1.0.0 - Stand 18.04.2020
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
sudo yum update && sudo yum group install 'Development Tools' && sudo yum install perl-core zlib-devel openssl-devel
id -u nginx &>/dev/null || sudo adduser -r nginx

# Install latest nginx with pagespeed
# Quelle: https://github.com/apache/incubator-pagespeed-ngx/blob/master/scripts/build_ngx_pagespeed.sh
sudo bash $HOME/myodoo-docker/Scripts/build_ngx_pagespeed.sh \
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
sudo mkdir -p /var/cache/nginx/client_temp
sudo mkdir -p /etc/nginx/
sudo mkdir -p /etc/nginx/html/
sudo mkdir -p /etc/nginx/conf.d/
sudo mv /etc/nginx/nginx.conf /etc/nginx/nginx.conf.backup
sudo cp $HOME/myodoo-docker/nginx-conf/centos/nginx.conf /etc/nginx/
sudo cp $HOME/myodoo-docker/nginx-conf/custom_50x.html /etc/nginx/html/
#/usr/share/nginx/html

# prepare pagespeed
sudo mkdir -p /var/cache/ngx_pagespeed/
sudo chown -R nginx:nginx /var/cache/ngx_pagespeed/

# Install & start service nginx
sudo cp $HOME/myodoo-docker/Scripts/centos/nginx.service /lib/systemd/system/
sudo systemctl enable nginx
sudo systemctl start nginx

echo "nginx installed"
echo ""

echo "nginx version"
sudo nginx -V
echo ""

sudo mkdir -p /etc/systemd/system/nginx.service.d
sudo printf "[Service]\nExecStartPost=/bin/sleep 0.1\n" > /etc/systemd/system/nginx.service.d/override.conf
sudo systemctl daemon-reload
sudo systemctl restart nginx

echo "nginx check"
sudo nginx -t

echo "Cleanup"
sudo rm -rf $HOME/incubator-pagespeed-ngx-latest-stable/
sudo rm -rf $HOME/nginx-1.*
