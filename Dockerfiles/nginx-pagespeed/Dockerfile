FROM ubuntu:18.04
MAINTAINER Equitania Software GmbH <info@myodoo.de>

# Version
# http://nginx.org/en/download.html
#ENV NGINX_VERSION 1.14.0
# https://github.com/apache/incubator-pagespeed-ngx/releases
#ENV NPS_VERSION 1.13.35.2

# Setup Environment
#ENV MODULE_DIR /usr/src/nginx-modules
#ENV NGINX_TEMPLATE_DIR /usr/src/nginx
#ENV NGINX_RUNTIME_DIR /usr/src/runtime
# Set some required defaults
#ENV NPSC_FILE_CACHE_PATH=/var/cache/ngx_pagespeed

# Install Build Tools & Dependence
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get -y dist-upgrade && apt-get install -y sudo build-essential zlib1g-dev unzip uuid-dev curl libpcre3-dev wget libssl-dev tzdata && \
    ln -sf /usr/share/zoneinfo/Europe/Berlin /etc/localtime

RUN /bin/bash -c "bash <(curl -f -L -sS https://ngxpagespeed.com/install) --nginx-version latest"
#--additional-nginx-configure-arguments --prefix=/etc/nginx --sbin-path=/usr/sbin/nginx --modules-path=/usr/lib/nginx/modules --conf-path=/etc/nginx/nginx.conf --error-log-path=/var/log/nginx/error.log --http-log-path=/var/log/nginx/access.log --pid-path=/var/run/nginx.pid --lock-path=/var/run/nginx.lock --http-client-body-temp-path=/var/cache/nginx/client_temp --http-proxy-temp-path=/var/cache/nginx/proxy_temp --http-fastcgi-temp-path=/var/cache/nginx/fastcgi_temp --http-uwsgi-temp-path=/var/cache/nginx/uwsgi_temp --http-scgi-temp-path=/var/cache/nginx/scgi_temp --user=nginx --group=nginx --with-http_ssl_module --with-http_v2_module"

RUN useradd --no-create-home nginx

RUN /bin/bash -c "mkdir -p /etc/nginx/conf.d/"
COPY nginx.conf /etc/nginx/nginx.conf
RUN chown -R nginx:nginx /etc/nginx/
RUN /bin/bash -c "mkdir -p /var/cache/ngx_pagespeed/"
RUN /bin/bash -c "chown nginx:nginx /var/cache/ngx_pagespeed/"
COPY entrypoint.sh /sbin/entrypoint.sh
RUN chmod 755 /sbin/entrypoint.sh

EXPOSE 8080 8443

ENV NGINX_USER=www-data \
    NGINX_SITECONF_DIR=/etc/nginx/conf.d/ \
    NGINX_LOG_DIR=/var/log/nginx \
    NGINX_TEMP_DIR=/var/lib/nginx

VOLUME ["${NGINX_SITECONF_DIR}"]

ENTRYPOINT ["/sbin/entrypoint.sh"]
CMD ["/usr/local/nginx/sbin/nginx"]

