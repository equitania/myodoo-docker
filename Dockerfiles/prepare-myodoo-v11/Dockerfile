FROM ubuntu:16.04
MAINTAINER Equitania Software GmbH <info@myodoo.de>
# For Odoo 11 powered by MyOdoo.de
# Version 1.0.5
# Date 27.05.2018


ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get -y dist-upgrade && apt-get install -y wget locales tzdata && \
    ln -sf /usr/share/zoneinfo/Europe/Berlin /etc/localtime

# Set LOCALE to UTF8..
RUN echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && \
    locale-gen en_US.UTF-8 && \
    dpkg-reconfigure locales && \
    /usr/sbin/update-locale LANG=en_US.UTF-8
ENV LC_ALL en_US.UTF-8

#Postgres 10 for Ubuntu
RUN wget -q https://www.postgresql.org/media/keys/ACCC4CF8.asc -O - | apt-key add - && \
    sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt/ xenial-pgdg main" >> /etc/apt/sources.list.d/pgdg.list' && \
    apt-get update && \
    apt-get install -y postgresql-client-10


# Update bash..
COPY ./.bashrc /root/


# Install basics..
RUN set -x; \
		apt-get install -y --no-install-recommends \
		ca-certificates \
		locales \
		ghostscript \
		graphviz \
		antiword  \
		poppler-utils \
		htop \
		dnsutils \
		curl \
		build-essential \
		python3-pip \
		python3-stdnum \
		libfreetype6-dev \
		libjpeg-dev \
		libpq-dev \
		python3-dev \
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
		xfonts-base


# Python packages pip install..
RUN set -x; \
    python3 -m pip install --no-cache-dir pip==10.0.1 \
    && python3 -m pip install --no-cache-dir wheel --upgrade \
    && python3 -m pip install --no-cache-dir setuptools --upgrade \
    && python3 -m pip install --no-cache-dir Babel==2.3.4 \
    && python3 -m pip install --no-cache-dir decorator==4.0.10 \
    && python3 -m pip install --no-cache-dir docutils==0.12 \
    && python3 -m pip install --no-cache-dir feedparser==5.2.1 \
    && python3 -m pip install --no-cache-dir gevent==1.1.2 \
    && python3 -m pip install --no-cache-dir greenlet==0.4.10 \
    && python3 -m pip install --no-cache-dir html2text==2016.9.19 \
    && python3 -m pip install --no-cache-dir Jinja2==2.8 \
    && python3 -m pip install --no-cache-dir lxml==3.7.1 \
    && python3 -m pip install --no-cache-dir Mako==1.0.4 \
    && python3 -m pip install --no-cache-dir MarkupSafe==0.23 \
    && python3 -m pip install --no-cache-dir mock==2.0.0 \
    && python3 -m pip install --no-cache-dir num2words==0.5.4 \
    && python3 -m pip install --no-cache-dir ofxparse==0.16 \
    && python3 -m pip install --no-cache-dir passlib==1.6.5 \
    && python3 -m pip install --no-cache-dir Pillow==4.0.0 \
    && python3 -m pip install --no-cache-dir psutil==4.3.1 \
    && python3 -m pip install --no-cache-dir psycopg2==2.7.3.1 \
    && python3 -m pip install --no-cache-dir pydot==1.2.3 \
    && python3 -m pip install --no-cache-dir pyldap==2.4.28 \
    && python3 -m pip install --no-cache-dir pyparsing==2.1.10 \
    && python3 -m pip install --no-cache-dir PyPDF2==1.26.0 \
    && python3 -m pip install --no-cache-dir pyserial==3.1.1 \
    && python3 -m pip install --no-cache-dir python-dateutil==2.5.3 \
    && python3 -m pip install --no-cache-dir pytz==2016.7 \
    && python3 -m pip install --no-cache-dir pyusb==1.0.0 \
    && python3 -m pip install --no-cache-dir PyYAML==3.12 \
    && python3 -m pip install --no-cache-dir qrcode==5.3 \
    && python3 -m pip install --no-cache-dir reportlab==3.3.0 \
    && python3 -m pip install --no-cache-dir requests==2.11.1 \
    && python3 -m pip install --no-cache-dir six==1.10.0 \
    && python3 -m pip install --no-cache-dir suds-jurko==0.6 \
    && python3 -m pip install --no-cache-dir vatnumber==1.2 \
    && python3 -m pip install --no-cache-dir vobject==0.9.3 \
    && python3 -m pip install --no-cache-dir Werkzeug==0.11.11 \
    && python3 -m pip install --no-cache-dir XlsxWriter==0.9.3 \
    && python3 -m pip install --no-cache-dir xlwt==1.3.* \
    && python3 -m pip install --no-cache-dir xlrd==1.0.0 \
    && python3 -m pip install --no-cache-dir openpyxl \
    && python3 -m pip install --no-cache-dir phonenumbers \
    && python3 -m pip install --no-cache-dir odoorpc \
    && python3 -m pip install --no-cache-dir elasticsearch==6.1.1 \
    && python3 -m pip install --no-cache-dir dropbox==8.7.1 \
    && python3 -m pip install --no-cache-dir MT-940

# OpenSans font install..
RUN set -x; \
		wget https://release.myodoo.de/fonts/opensans.zip \
		&& unzip opensans.zip \
		&& mv opensans /usr/share/fonts/truetype/ \
		&& rm opensans.zip

# Barcodes font install..
RUN set -x; \
		wget http://www.reportlab.com/ftp/pfbfer.zip \
		&& unzip pfbfer.zip -d fonts \
		&& mv fonts /usr/lib/python2.7/dist-packages/reportlab/ \
		&& rm pfbfer.zip \
		&& fc-cache -f -v

# PDF export engine install..
# http://download.gna.org/wkhtmltopdf/0.12/0.12.2.1/
RUN set -x; \
		curl -k -o wkhtmltox.deb -SL https://release.myodoo.de/wkhtmltox-0.12.2.1_linux-trusty-amd64.deb \
		&& dpkg --force-depends -i wkhtmltox.deb \
        && ln -s /usr/local/bin/wkhtmltopdf /usr/bin \
        && ln -s /usr/local/bin/wkhtmltoimage /usr/bin \
		&& apt-get -y install -f --no-install-recommends \
		&& apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false -o APT::AutoRemove::SuggestsImportant=false npm \
		&& rm -rf /var/lib/apt/lists/* wkhtmltox.deb

# Finished with build.
