FROM debian:jessie
MAINTAINER Equitania Software GmbH <info@myodoo.de>
# Version 1.0.7
# Date 12.01.2017

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
		curl \
		postgresql-client-9.4 \
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
		python-dev \
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
RUN pip install --upgrade pip
RUN pip install Babel==2.3.4
RUN pip install decorator==4.0.10
RUN pip install docutils==0.12
RUN pip install feedparser==5.2.1
RUN pip install gevent==1.1.2
RUN pip install greenlet==0.4.10
RUN pip install jcconv==0.2.3
RUN pip install Jinja2==2.8
RUN pip install lxml==3.6.4
RUN pip install Mako==1.0.4
RUN pip install MarkupSafe==0.23
RUN pip install mock==2.0.0
RUN pip install ofxparse==0.15
RUN pip install passlib==1.6.5
RUN pip install Pillow==3.4.1
RUN pip install psutil==4.3.1
RUN pip install psycogreen==1.0
RUN pip install pydot==1.2.3
RUN pip install pyparsing==2.1.10
RUN pip install pyPdf==1.13
RUN pip install pyserial==3.1.1
RUN pip install Python-Chart==1.39
RUN pip install python-dateutil==2.5.3
RUN pip install python-openid==2.2.5
RUN pip install pytz==2016.7
RUN pip install pyusb==1.0.0
RUN pip install PyYAML==3.12
RUN pip install qrcode==5.3
RUN pip install reportlab==3.3.0
RUN pip install requests==2.11.1
RUN pip install six==1.10.0
RUN pip install suds-jurko==0.6
RUN pip install vatnumber==1.2
RUN pip install vobject==0.9
RUN pip install Werkzeug==0.11.11
RUN pip install wsgiref==0.1.2
RUN pip install XlsxWriter==0.9.3
RUN pip install xlwt==1.1.2
RUN pip install gdata
RUN pip install simplejson
RUN pip install unittest2
RUN pip install pdftools
RUN pip install matplotlib
RUN pip install beautifulsoup4
RUN pip install evdev
RUN pip install polib
RUN pip install unidecode
RUN pip install validate_email
RUN pip install pyDNS
RUN pip install python-slugify
RUN pip install paramiko==1.9.0
RUN pip install pycrypto==2.6
RUN pip install pyinotify
RUN pip install ecdsa==0.11
RUN pip install sphinx
RUN pip install Pygments==2.0
RUN pip install egenix-mx-base
RUN pip install pypdf2
RUN pip install odoorpc
RUN pip install pyelasticsearch
RUN pip install openpyxl
RUN pip install phonenumbers

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
RUN set -x; \
		curl -k -o wkhtmltox.deb -SL https://release.myodoo.de/wkhtmltox-0.12.1.2_linux-jessie-amd64.deb \
		&& echo '40e8b906de658a2221b15e4e8cd82565a47d7ee8 wkhtmltox.deb' | sha1sum -c - \
		&& dpkg --force-depends -i wkhtmltox.deb \
		&& apt-get -y install -f --no-install-recommends \
		&& apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false -o APT::AutoRemove::SuggestsImportant=false npm \
		&& rm -rf /var/lib/apt/lists/* wkhtmltox.deb

CMD "echo" "Cleanup.."
RUN apt-get autoremove
CMD "echo" "Finished with build."