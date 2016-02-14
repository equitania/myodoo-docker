FROM debian:jessie
MAINTAINER Equitania Software GmbH <info@myodoo.de>
# Version 1.0.1
# Date 06.01.2016

CMD "echo" "MyOdoo build will start now.."

# Install basics
RUN set -x; \
		apt-get update \
		&& apt-get install -y --no-install-recommends \
		ca-certificates \
		ghostscript \
		graphviz \
		antiword  \
		poppler-utils \
		curl \
		postgresql-client \
		build-essential \
		libfreetype6-dev \
		libjpeg-dev \
		wget \
		unzip \
		sqlite3 \
		nano \
		mc \
		geoip-bin \
		geoip-database \
		sudo

# Python packages..
RUN set -x; \
		apt-get install -y --no-install-recommends \
		python-pip  \
		python-magic \
		python-dateutil \
		python-pypdf \
		python-requests \
		python-feedparser \
		python-gdata \
		python-ldap \
		python-libxslt1 \
		python-lxml \
		python-mako \
		python-openid \
		python-psycopg2 \
		python-pybabel \
		python-pychart \
		python-pydot \
		python-pyparsing \
		python-reportlab \
		python-simplejson \
		python-tz \
		python-vatnumber \
		python-vobject \
		python-webdav \
		python-werkzeug \
		python-xlwt \
		python-yaml \
		python-zsi \
		python-docutils \
		python-psutil \
		python-unittest2 \
		python-mock \
		python-jinja2 \
		python-dev \
		python-pdftools \
		python-decorator \
		python-openssl \
		python-babel \
		python-imaging \
		python-reportlab-accel \
		python-paramiko \
		python-software-properties \
		python-matplotlib \
		python-support \
		python-passlib \
		python-pyinotify \
		python-gevent \
		python-renderpm

# Pip install..
RUN set -x; \
		pip install passlib \
		&& pip install beautifulsoup4 \
		&& pip install evdev \
		&& pip install reportlab \
		&& pip install qrcode \
		&& pip install polib \
		&& pip install unidecode \
		&& pip install validate_email \
		&& pip install pyDNS \
		&& pip install pysftp \
		&& pip install python-slugify \
		&& pip install six==1.4 \
		&& pip install paramiko==1.9.0 \
		&& pip install pycrypto==2.4 \
		&& pip install pyinotify \
		&& pip install ecdsa==0.11 \
		&& pip install sphinx \
		&& pip install babel==1.3 \
		&& pip install Pygments==2.0 \
		&& pip install docutils==0.11 \
		&& pip install markupsafe \
		&& pip install pytz \
		&& pip install Jinja2==2.3 \
		&& pip install gevent \
		&& pip install psycogreen\
		&& pip install egenix-mx-base

# Python Image Library will be install..
RUN set -x; \
		wget http://effbot.org/downloads/Imaging-1.1.7.tar.gz \
		&& tar fzvx Imaging-1.1.7.tar.gz \
		&& cd Imaging-1.1.7 \
		&& python setup.py install \
		&& pip install -I pillow \
		&& cd ..\
		&& rm -r Imaging-1.1.7 \
		&& rm  Imaging-1.1.7.tar.gz

# npm packages will be install..
RUN set -x; \
		curl -sL https://deb.nodesource.com/setup_0.12 | bash - \
		&& apt-get install -y --no-install-recommends nodejs \
		&& npm install -g less less-plugin-clean-css

# Barcodes will be install...
RUN set -x; \
		wget http://www.reportlab.com/ftp/pfbfer.zip \
		&& unzip pfbfer.zip -d fonts \
		&& mv fonts /usr/lib/python2.7/dist-packages/reportlab/ \
		&& rm pfbfer.zip

# Print engine..
RUN set -x; \
		curl -o wkhtmltox.deb -SL http://nightly.odoo.com/extra/wkhtmltox-0.12.1.2_linux-jessie-amd64.deb \
		&& echo '40e8b906de658a2221b15e4e8cd82565a47d7ee8 wkhtmltox.deb' | sha1sum -c - \
		&& dpkg --force-depends -i wkhtmltox.deb \
		&& apt-get -y install -f --no-install-recommends \
		&& apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false -o APT::AutoRemove::SuggestsImportant=false npm \
		&& rm -rf /var/lib/apt/lists/* wkhtmltox.deb

