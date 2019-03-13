FROM ubuntu:16.04
MAINTAINER Equitania Software GmbH <info@myodoo.de>
# For Odoo 10 powered by MyOdoo.de
# Version 2.1.7
# Date 13.03.2019

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get -y dist-upgrade && apt-get install -y wget locales tzdata && \
    ln -sf /usr/share/zoneinfo/Europe/Berlin /etc/localtime

# Set LOCALE to UTF8..
RUN echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && \
    locale-gen en_US.UTF-8 && \
    dpkg-reconfigure locales && \
    /usr/sbin/update-locale LANG=en_US.UTF-8
ENV LC_ALL en_US.UTF-8

# Postgres 9.6 for Ubuntu
RUN wget -q https://www.postgresql.org/media/keys/ACCC4CF8.asc -O - | apt-key add - && \
    sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt/ xenial-pgdg main" >> /etc/apt/sources.list.d/pgdg.list' && \
    apt-get update && \
    apt-get install -y postgresql-client-9.6

# Update bash..
COPY ./.bashrc /root/

# Install basics..
RUN set -x; \
		apt-get install -y --no-install-recommends \
		ca-certificates \
		ghostscript \
		graphviz \
		antiword  \
		poppler-utils \
		htop \
		dnsutils \
		curl \
		build-essential \
		libfreetype6-dev \
		libjpeg-dev \
		libpq-dev \
		python-dev \
		libxml2-dev \
		libxslt1-dev \
		libldap2-dev \
		libsasl2-dev \
		libffi-dev \		
		unzip \
		sqlite3 \
		nano \
		mc \
		pkg-config \
		geoip-bin \
		geoip-database \
		sudo \
		node-less \
		node-clean-css \
		imagemagick \
		xfonts-75dpi \
		xfonts-base \
        ttf-mscorefonts-installer

# Install python libs ..
RUN set -x; \
		apt-get install -y --no-install-recommends \
		python-software-properties \
		python-pip  \
		python-magic \
		python-libxslt1 \
		python-imaging \
		python-renderpm \
		python-reportlab-accel \
	    python-tz \
        python-zsi \
        python-webdav

# Python packages pip install..
RUN set -x; \
    python2.7 -m pip install --no-cache-dir pip==18.1 \
    && python2.7 -m pip install --no-cache-dir wheel \
    && python2.7 -m pip install --no-cache-dir setuptools \
    && python2.7 -m pip install --no-cache-dir pyopenssl \
    && python2.7 -m pip install --no-cache-dir psycopg2==2.7.3.1 \
    && python2.7 -m pip install --no-cache-dir Babel==2.3.4 \
    && python2.7 -m pip install --no-cache-dir decorator==4.0.10 \
    && python2.7 -m pip install --no-cache-dir docutils==0.12 \
    && python2.7 -m pip install --no-cache-dir feedparser==5.2.1 \
    && python2.7 -m pip install --no-cache-dir gevent==1.1.2 \
    && python2.7 -m pip install --no-cache-dir greenlet==0.4.10 \
    && python2.7 -m pip install --no-cache-dir jcconv==0.2.3 \
    && python2.7 -m pip install --no-cache-dir Jinja2==2.8.1 \
    && python2.7 -m pip install --no-cache-dir lxml==3.6.4 \
    && python2.7 -m pip install --no-cache-dir Mako==1.0.4 \
    && python2.7 -m pip install --no-cache-dir MarkupSafe==0.23 \
    && python2.7 -m pip install --no-cache-dir mock==2.0.0 \
    && python2.7 -m pip install --no-cache-dir ofxparse==0.16 \
    && python2.7 -m pip install --no-cache-dir passlib==1.6.5 \
    && python2.7 -m pip install --no-cache-dir Pillow==3.4.1 \
    && python2.7 -m pip install --no-cache-dir psutil==4.3.1 \
    && python2.7 -m pip install --no-cache-dir psycogreen==1.0 \
    && python2.7 -m pip install --no-cache-dir pydot==1.2.3 \
    && python2.7 -m pip install --no-cache-dir pyparsing==2.1.10 \
    && python2.7 -m pip install --no-cache-dir pyPdf==1.13 \
    && python2.7 -m pip install --no-cache-dir pyserial==3.1.1 \
    && python2.7 -m pip install --no-cache-dir Python-Chart==1.39 \
    && python2.7 -m pip install --no-cache-dir python-dateutil==2.5.3 \
    && python2.7 -m pip install --no-cache-dir python-ldap==2.4.27 \
    && python2.7 -m pip install --no-cache-dir python-openid==2.2.5 \
    && python2.7 -m pip install --no-cache-dir pytz==2016.7 \
    && python2.7 -m pip install --no-cache-dir pyusb==1.0.0 \
    && python2.7 -m pip install --no-cache-dir PyYAML==4.2b1 \
    && python2.7 -m pip install --no-cache-dir qrcode==5.3 \
    && python2.7 -m pip install --no-cache-dir reportlab==3.3.0 \
    && python2.7 -m pip install --no-cache-dir requests==2.20.0 \
    && python2.7 -m pip install --no-cache-dir six==1.10.0 \
    && python2.7 -m pip install --no-cache-dir suds-jurko==0.6 \
    && python2.7 -m pip install --no-cache-dir vatnumber==1.2 \
    && python2.7 -m pip install --no-cache-dir vobject==0.9 \
    && python2.7 -m pip install --no-cache-dir Werkzeug==0.11.11 \
    && python2.7 -m pip install --no-cache-dir wsgiref==0.1.2 \
    && python2.7 -m pip install --no-cache-dir XlsxWriter==0.9.3 \
    && python2.7 -m pip install --no-cache-dir xlwt==1.1.2 \
    && python2.7 -m pip install --no-cache-dir xlrd==1.0.0 \
    && python2.7 -m pip install --no-cache-dir gdata \
    && python2.7 -m pip install --no-cache-dir simplejson \
    && python2.7 -m pip install --no-cache-dir unittest2 \
    && python2.7 -m pip install --no-cache-dir pdftools \
    && python2.7 -m pip install --no-cache-dir matplotlib \
    && python2.7 -m pip install --no-cache-dir beautifulsoup4 \
    && python2.7 -m pip install --no-cache-dir evdev \
    && python2.7 -m pip install --no-cache-dir polib \
    && python2.7 -m pip install --no-cache-dir unidecode \
    && python2.7 -m pip install --no-cache-dir validate_email \
    && python2.7 -m pip install --no-cache-dir pyDNS \
    && python2.7 -m pip install --no-cache-dir python-slugify \
    && python2.7 -m pip install --no-cache-dir paramiko==1.16.0 \
    && python2.7 -m pip install --no-cache-dir pycrypto==2.6 \
    && python2.7 -m pip install --no-cache-dir pyinotify \
    && python2.7 -m pip install --no-cache-dir ecdsa==0.11 \
    && python2.7 -m pip install --no-cache-dir sphinx \
    && python2.7 -m pip install --no-cache-dir Pygments==2.0 \
    && python2.7 -m pip install --no-cache-dir egenix-mx-base \
    && python2.7 -m pip install --no-cache-dir pypdf2 \
    && python2.7 -m pip install --no-cache-dir odoorpc \
    && python2.7 -m pip install --no-cache-dir elasticsearch==6.1.1 \
    && python2.7 -m pip install --no-cache-dir openpyxl \
    && python2.7 -m pip install --no-cache-dir phonenumbers \
    && python2.7 -m pip install --no-cache-dir pysftp \
    && python2.7 -m pip install --no-cache-dir email \
    && python2.7 -m pip install --no-cache-dir suds \
    && python2.7 -m pip install --no-cache-dir pycrypto==2.6.1 \
    && python2.7 -m pip install --no-cache-dir pyocclient==0.4 \
    && python2.7 -m pip install --no-cache-dir Office365Api==0.0.9 \
    && python2.7 -m pip install --no-cache-dir oauthlib==2.1.0 \
    && python2.7 -m pip install --no-cache-dir sphinx==1.4.6 \
    && python2.7 -m pip install --no-cache-dir sphinx_tabs==1.1.6 \
    && python2.7 -m pip install --no-cache-dir sphinxcontrib-httpdomain==1.5.0 \
    && python2.7 -m pip install --no-cache-dir sphinx_rtd_theme==0.2.5b2 \
    && python2.7 -m pip install --no-cache-dir zammad-py==0.1.5 \
    && python2.7 -m pip install --no-cache-dir bs4==0.0.1 \
    && python2.7 -m pip install --no-cache-dir zenpy==2.0.4 \
    && python2.7 -m pip install --no-cache-dir xmltodict==0.11.0 \
    && python2.7 -m pip install --no-cache-dir email_validator

# OpenSans font install..
RUN set -x; \
		wget https://rm.ownerp.io/staff/opensans.zip \
		&& unzip opensans.zip \
		&& mv opensans /usr/share/fonts/truetype/ \
		&& rm opensans.zip

# Barcodes font install..
RUN set -x; \
		wget https://rm.ownerp.io/staff/pfbfer.zip \
		&& unzip pfbfer.zip -d fonts \
		&& mv fonts /usr/lib/python2.7/dist-packages/reportlab/ \
		&& rm pfbfer.zip \
		&& fc-cache -f -v

# PDF export engine install..
RUN set -x; \
        curl -k -o wkhtmltox.deb -SL https://rm.ownerp.io/staff/wkhtmltox_0.12.5-1.trusty_amd64.deb \
        && dpkg --force-depends -i wkhtmltox.deb \
        && ln -s /usr/local/bin/wkhtmltopdf /usr/bin \
        && ln -s /usr/local/bin/wkhtmltoimage /usr/bin \
        && apt-get -y install -f --no-install-recommends \
        && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false -o APT::AutoRemove::SuggestsImportant=false npm \
        && rm -rf /var/lib/apt/lists/* wkhtmltox.deb

# Finished with build."
