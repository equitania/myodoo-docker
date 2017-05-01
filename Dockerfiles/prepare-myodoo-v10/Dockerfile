FROM debian:jessie
MAINTAINER Equitania Software GmbH <info@myodoo.de>
# For Odoo 10 powered by MyOdoo.de
# Version 1.0.12
# Date 01.05.2017

CMD "echo" "MyOdoo build will start now.."

ENV DEBIAN_FRONTEND noninteractive

RUN apt-get update && apt-get -y dist-upgrade && apt-get install -y apt-utils locales

CMD "echo" "Update bash.."
COPY ./.bashrc /root/

CMD "echo" "Set LOCALE to UTF8.."
RUN echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && \
    locale-gen en_US.UTF-8 && \
    dpkg-reconfigure locales && \
    /usr/sbin/update-locale LANG=en_US.UTF-8
ENV LC_ALL en_US.UTF-8

CMD "echo" "Set fs.inotify.max_user_watches = 524288.."
RUN echo "fs.inotify.max_user_watches = 524288" >> /etc/sysctl.conf

CMD "echo" "Install basics.."
RUN set -x; \
		apt-get install -y --no-install-recommends \
		ca-certificates \
		ghostscript \
		graphviz \
		antiword  \
		poppler-utils \
		mtr \
		dnsutils \
		curl \
		postgresql-client-9.4 \
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
		wget \
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
		tesseract-ocr \
		imagemagick \
		xfonts-75dpi \
		xfonts-base

CMD "echo" "Install python libs .."
RUN set -x; \
		apt-get install -y --no-install-recommends \
		python-software-properties \
		python-pip  \
		python-psycopg2 \
		python-ldap \
		python-magic \
		python-libxslt1 \
		python-imaging \
		python-openssl \
		python-renderpm \
		python-reportlab-accel \
		python-support \
	    python-tz \
        python-zsi \
        python-webdav


CMD "echo" "Python packages pip install.."
RUN set -x; \
    pip install --upgrade pip \
    && pip install Babel==2.3.4 \
    && pip install decorator==4.0.10 \
    && pip install docutils==0.12 \
    && pip install ebaysdk==2.1.4 \
    && pip install feedparser==5.2.1 \
    && pip install gevent==1.1.2 \
    && pip install greenlet==0.4.10 \
    && pip install jcconv==0.2.3 \
    && pip install Jinja2==2.8 \
    && pip install lxml==3.6.4 \
    && pip install Mako==1.0.4 \
    && pip install MarkupSafe==0.23 \
    && pip install mock==2.0.0 \
    && pip install ofxparse==0.15 \
    && pip install passlib==1.6.5 \
    && pip install Pillow==3.4.1 \
    && pip install psutil==4.3.1 \
    && pip install psycogreen==1.0 \
    && pip install psycopg2==2.6.2 \
    && pip install pydot==1.2.3 \
    && pip install pyparsing==2.1.10 \
    && pip install pyPdf==1.13 \
    && pip install pyserial==3.1.1 \
    && pip install Python-Chart==1.39 \
    && pip install python-dateutil==2.5.3 \
    && pip install python-ldap==2.4.27 \
    && pip install python-openid==2.2.5 \
    && pip install pytz==2016.7 \
    && pip install pyusb==1.0.0 \
    && pip install PyYAML==3.12 \
    && pip install qrcode==5.3 \
    && pip install reportlab==3.3.0 \
    && pip install requests==2.11.1 \
    && pip install six==1.10.0 \
    && pip install suds-jurko==0.6 \
    && pip install vatnumber==1.2 \
    && pip install vobject==0.9 \
    && pip install Werkzeug==0.11.11 \
    && pip install wsgiref==0.1.2 \
    && pip install XlsxWriter==0.9.3 \
    && pip install xlwt==1.1.2 \
    && pip install xlrd==1.0.0

RUN set -x; \
    pip install gdata \
    && pip install simplejson \
    && pip install unittest2 \
    && pip install pdftools \
    && pip install matplotlib \
    && pip install beautifulsoup4 \
    && pip install evdev \
    && pip install polib \
    && pip install unidecode \
    && pip install validate_email \
    && pip install pyDNS \
    && pip install python-slugify \
    && pip install paramiko==1.9.0 \
    && pip install pycrypto==2.6 \
    && pip install pyinotify \
    && pip install ecdsa==0.11 \
    && pip install sphinx \
    && pip install Pygments==2.0 \
    && pip install egenix-mx-base \
    && pip install pypdf2 \
    && pip install odoorpc \
    && pip install pyelasticsearch \
    && pip install openpyxl \
    && pip install phonenumbers \
    && pip install pysftp \
    && pip install email \
    && pip install suds

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
		curl -k -o wkhtmltox.deb -SL https://release.myodoo.de/wkhtmltox-0.12.2.1_linux-jessie-amd64.deb \
		&& echo 'c81fffae4c0914f95fb12e047a72edda5042b1c6 wkhtmltox.deb' | sha1sum -c - \
		&& dpkg --force-depends -i wkhtmltox.deb \
        && ln -s /usr/local/bin/wkhtmltopdf /usr/bin \
        && ln -s /usr/local/bin/wkhtmltoimage /usr/bin \
		&& apt-get -y install -f --no-install-recommends \
		&& apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false -o APT::AutoRemove::SuggestsImportant=false npm \
		&& rm -rf /var/lib/apt/lists/* wkhtmltox.deb

CMD "echo" "Cleanup.."
RUN apt-get autoremove
CMD "echo" "Finished with build."
