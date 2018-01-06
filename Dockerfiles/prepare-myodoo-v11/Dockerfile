FROM ubuntu:16.04
MAINTAINER Equitania Software GmbH <info@myodoo.de>
# For Odoo 11 powered by MyOdoo.de
# Version 1.0.0
# Date 03.01.2018

CMD "echo" "MyOdoo build will start now.."

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get -y dist-upgrade && apt-get install -y apt-utils wget locales

CMD "echo" "Set LOCALE to UTF8.."
RUN echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && \
    locale-gen en_US.UTF-8 && \
    dpkg-reconfigure locales && \
    /usr/sbin/update-locale LANG=en_US.UTF-8
ENV LC_ALL en_US.UTF-8

CMD "echo" "Postgres 9.6 for Ubuntu"
RUN wget -q https://www.postgresql.org/media/keys/ACCC4CF8.asc -O - | apt-key add - && \
    sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt/ jessie-pgdg main" >> /etc/apt/sources.list.d/pgdg.list' && \
    apt-get update && \
    apt-get install -y postgresql-client-9.6


CMD "echo" "Update bash.."
COPY ./.bashrc /root/


CMD "echo" "Install basics.."
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


CMD "echo" "Python packages pip install.."
RUN set -x; \
    pip3 install --upgrade pip \
    && pip3 install wheel  --upgrade \
    && pip3 install setuptools  --upgrade \
    && pip3 install Babel==2.3.4 \
    && pip3 install decorator==4.0.10 \
    && pip3 install docutils==0.12 \
    && pip3 install feedparser==5.2.1 \
    && pip3 install gevent==1.1.2 \
    && pip3 install greenlet==0.4.10 \
    && pip3 install html2text==2016.9.19 \
    && pip3 install Jinja2==2.8 \
    && pip3 install lxml==3.5.0 \
    && pip3 install Mako==1.0.4 \
    && pip3 install MarkupSafe==0.23 \
    && pip3 install mock==2.0.0 \
    && pip3 install num2words==0.5.4 \
    && pip3 install ofxparse==0.16 \
    && pip3 install passlib==1.6.5 \
    && pip3 install Pillow==3.4.1 \
    && pip3 install psutil==4.3.1 \
    && pip3 install psycopg2==2.7.3.1 \
    && pip3 install pydot==1.2.3 \
    && pip3 install pyldap==2.4.28 \
    && pip3 install pyparsing==2.1.10 \
    && pip3 install PyPDF2==1.26.0 \
    && pip3 install pyserial==3.1.1 \
    && pip3 install python-dateutil==2.5.3 \
    && pip3 install pytz==2016.7 \
    && pip3 install pyusb==1.0.0 \
    && pip3 install PyYAML==3.12 \
    && pip3 install qrcode==5.3 \
    && pip3 install reportlab==3.3.0 \
    && pip3 install requests==2.11.1 \
    && pip3 install six==1.10.0 \
    && pip3 install suds-jurko==0.6 \
    && pip3 install vatnumber==1.2 \
    && pip3 install vobject==0.9.3 \
    && pip3 install Werkzeug==0.11.11 \
    && pip3 install XlsxWriter==0.9.3 \
    && pip3 install xlwt==1.3.* \
    && pip3 install xlrd==1.0.0 \
    && pip3 install openpyxl \
    && pip3 install phonenumbers \
    && pip3 install odoorpc \
    && pip3 install elasticsearch==6.0.0


CMD "echo" "OpenSans font install.."
RUN set -x; \
		wget https://release.myodoo.de/fonts/opensans.zip \
		&& unzip opensans.zip \
		&& mv opensans /usr/share/fonts/truetype/ \
		&& rm opensans.zip

CMD "echo" "Barcodes font install.."
RUN set -x; \
		wget http://www.reportlab.com/ftp/pfbfer.zip \
		&& unzip pfbfer.zip -d fonts \
		&& mv fonts /usr/lib/python2.7/dist-packages/reportlab/ \
		&& rm pfbfer.zip \
		&& fc-cache -f -v

CMD "echo" "PDF export engine install.."
# http://download.gna.org/wkhtmltopdf/0.12/0.12.2.1/
RUN set -x; \
		curl -k -o wkhtmltox.deb -SL https://release.myodoo.de/wkhtmltox-0.12.2.1_linux-trusty-amd64.deb \
		&& dpkg --force-depends -i wkhtmltox.deb \
        && ln -s /usr/local/bin/wkhtmltopdf /usr/bin \
        && ln -s /usr/local/bin/wkhtmltoimage /usr/bin \
		&& apt-get -y install -f --no-install-recommends \
		&& apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false -o APT::AutoRemove::SuggestsImportant=false npm \
		&& rm -rf /var/lib/apt/lists/* wkhtmltox.deb

CMD "echo" "Cleanup.."
RUN apt-get autoremove
CMD "echo" "Finished with build."
