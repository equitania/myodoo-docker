FROM debian:jessie
MAINTAINER Equitania Software GmbH <info@myodoo.de>
# For Odoo 8 powered by MyOdoo.de
# Version 1.0.17
# Date 10.05.2018

# "echo" "MyOdoo build will start now.."

ENV DEBIAN_FRONTEND noninteractive

RUN apt-get update && apt-get -y dist-upgrade && apt-get install -y locales

# "echo" "Update bash.."
COPY ./.bashrc /root/

RUN \
  apt-get -y install tzdata && \
  ln -sf /usr/share/zoneinfo/Europe/Berlin /etc/localtime

# "echo" "Set LOCALE to UTF8.."
RUN echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && \
    locale-gen en_US.UTF-8 && \
    dpkg-reconfigure locales && \
    /usr/sbin/update-locale LANG=en_US.UTF-8
ENV LC_ALL en_US.UTF-8


# "echo" "Set fs.inotify.max_user_watches = 524288.."
RUN echo "fs.inotify.max_user_watches = 524288" >> /etc/sysctl.conf

# "echo" "Install basics.."
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

# "echo" "Install python libs .."
RUN set -x; \
		apt-get install -y --no-install-recommends \
		python-software-properties \
		python-pip  \
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


# "echo" "Python packages pip install.."
RUN set -x; \
    python2.7 -m pip install pip==10.0.1 \
    && python2.7 -m pip install --no-cache-dir wheel \
    && python2.7 -m pip install --no-cache-dir setuptools \
    && python2.7 -m pip install --no-cache-dir psycopg2==2.7.1 \
    && python2.7 -m pip install --no-cache-dir argparse==1.2.1 \
    && python2.7 -m pip install --no-cache-dir Babel==2.3.4 \
    && python2.7 -m pip install --no-cache-dir decorator==4.0.10 \
    && python2.7 -m pip install --no-cache-dir docutils==0.12 \
    && python2.7 -m pip install --no-cache-dir feedparser==5.2.1 \
    && python2.7 -m pip install --no-cache-dir gevent==1.1.2 \
    && python2.7 -m pip install --no-cache-dir greenlet==0.4.10 \
    && python2.7 -m pip install --no-cache-dir jcconv==0.2.3 \
    && python2.7 -m pip install --no-cache-dir Jinja2==2.8 \
    && python2.7 -m pip install --no-cache-dir lxml==3.6.4 \
    && python2.7 -m pip install --no-cache-dir Mako==1.0.4 \
    && python2.7 -m pip install --no-cache-dir MarkupSafe==0.23 \
    && python2.7 -m pip install --no-cache-dir mock==2.0.0 \
    && python2.7 -m pip install --no-cache-dir ofxparse==0.15 \
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
    && python2.7 -m pip install --no-cache-dir python-openid==2.2.5 \
    && python2.7 -m pip install --no-cache-dir pytz==2016.7 \
    && python2.7 -m pip install --no-cache-dir pyusb==1.0.0 \
    && python2.7 -m pip install --no-cache-dir PyYAML==3.12 \
    && python2.7 -m pip install --no-cache-dir qrcode==5.3 \
    && python2.7 -m pip install --no-cache-dir reportlab==3.3.0 \
    && python2.7 -m pip install --no-cache-dir requests==2.11.1 \
    && python2.7 -m pip install --no-cache-dir six==1.10.0 \
    && python2.7 -m pip install --no-cache-dir suds-jurko==0.6 \
    && python2.7 -m pip install --no-cache-dir vatnumber==1.2 \
    && python2.7 -m pip install --no-cache-dir vobject==0.9 \
    && python2.7 -m pip install --no-cache-dir Werkzeug==0.11.11 \
    && python2.7 -m pip install --no-cache-dir wsgiref==0.1.2 \
    && python2.7 -m pip install --no-cache-dir XlsxWriter==0.9.3 \
    && python2.7 -m pip install --no-cache-dir xlwt==1.1.2 \
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
    && python2.7 -m pip install --no-cache-dir paramiko==1.9.0 \
    && python2.7 -m pip install --no-cache-dir pycrypto==2.6 \
    && python2.7 -m pip install --no-cache-dir pyinotify \
    && python2.7 -m pip install --no-cache-dir ecdsa==0.11 \
    && python2.7 -m pip install --no-cache-dir sphinx \
    && python2.7 -m pip install --no-cache-dir Pygments==2.0 \
    && python2.7 -m pip install --no-cache-dir egenix-mx-base \
    && python2.7 -m pip install --no-cache-dir pypdf2 \
    && python2.7 -m pip install --no-cache-dir odoorpc \
    && python2.7 -m pip install --no-cache-dir pyelasticsearch \
    && python2.7 -m pip install --no-cache-dir openpyxl \
    && python2.7 -m pip install --no-cache-dir phonenumbers \
    && python2.7 -m pip install --no-cache-dir pysftp

# "echo" "OpenSans font install.."
RUN set -x; \
		wget https://release.myodoo.de/fonts/opensans.zip \
		&& unzip opensans.zip \
		&& mv opensans /usr/share/fonts/truetype/ \
		&& rm opensans.zip

# "echo" "Barcodes font install.."
RUN set -x; \
		wget http://www.reportlab.com/ftp/pfbfer.zip \
		&& unzip pfbfer.zip -d fonts \
		&& mv fonts /usr/lib/python2.7/dist-packages/reportlab/ \
		&& rm pfbfer.zip \
		&& fc-cache -f -v

# "echo" "PDF export engine install.."
# http://download.gna.org/wkhtmltopdf/0.12/
# http://nightly.odoo.com/extra/
RUN set -x; \
		curl -k -o wkhtmltox.deb -SL https://release.myodoo.de/wkhtmltox-0.12.1.2_linux-jessie-amd64.deb \
		&& echo '40e8b906de658a2221b15e4e8cd82565a47d7ee8 wkhtmltox.deb' | sha1sum -c - \
		&& dpkg --force-depends -i wkhtmltox.deb \
        && ln -s /usr/local/bin/wkhtmltopdf /usr/bin \
        && ln -s /usr/local/bin/wkhtmltoimage /usr/bin \
		&& apt-get -y install -f --no-install-recommends \
		&& apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false -o APT::AutoRemove::SuggestsImportant=false npm \
		&& rm -rf /var/lib/apt/lists/* wkhtmltox.deb

# "echo" "Finished with build."