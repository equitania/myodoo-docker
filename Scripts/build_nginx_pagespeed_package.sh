#!/bin/bash
# Install latest nginx with pagedspeed
# Script must run with mit root-rights
# Version 1.0.1 - Stand 07.05.2018
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
apt-get update && apt-get -y dist-upgrade && apt-get install -y sudo build-essential zlib1g-dev unzip uuid-dev curl libpcre3-dev wget libssl-dev

# Install latest nginx with pagespeed
bash <(curl -f -L -sS https://ngxpagespeed.com/install) \
    --nginx-version latest --assume-yes \
    --additional-nginx-configure-arguments '--prefix=/etc/nginx --sbin-path=/usr/sbin/nginx --modules-path=/usr/lib/nginx/modules --conf-path=/etc/nginx/nginx.conf --error-log-path=/var/log/nginx/error.log --http-log-path=/var/log/nginx/access.log --pid-path=/var/run/nginx.pid --lock-path=/var/run/nginx.lock --http-client-body-temp-path=/var/cache/nginx/client_temp --http-proxy-temp-path=/var/cache/nginx/proxy_temp --http-fastcgi-temp-path=/var/cache/nginx/fastcgi_temp --http-uwsgi-temp-path=/var/cache/nginx/uwsgi_temp --http-scgi-temp-path=/var/cache/nginx/scgi_temp --user=nginx --group=nginx --with-http_ssl_module --with-http_v2_module'

# prepare nginx
useradd --no-create-home nginx
mkdir -p /var/cache/nginx/client_temp
mkdir /etc/nginx/conf.d/
mv /etc/nginx/nginx.conf /etc/nginx/nginx.conf.backup
cp $HOME/myodoo-docker/nginx-conf/nginx.conf /etc/nginx/

# prepare pagespeed
mkdir /var/cache/ngx_pagespeed/
chown nginx:nginx /var/cache/ngx_pagespeed/

# Install & start service nginx
cp $HOME/myodoo-docker/nginx.service /lib/systemd/system/
systemctl enable nginx
systemctl start nginx

echo "nginx installed"
nginx -V
nginx -t