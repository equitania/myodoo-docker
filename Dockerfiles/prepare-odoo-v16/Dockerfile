FROM python:3.8.16-slim-buster
LABEL maintainer=info@ownerp.com
# For Odoo 16 powered by ownerp.com
# Version 23.02.01
# Date 02.02.2023

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get -y dist-upgrade && apt-get install -y wget sudo gnupg2 locales tzdata less git && \
    ln -sf /usr/share/zoneinfo/Europe/Berlin /etc/localtime

# Set LOCALE to UTF8..
RUN echo "de_DE.UTF-8 UTF-8" > /etc/locale.gen && \
    locale-gen de_DE.UTF-8 && \
    dpkg-reconfigure locales && \
    /usr/sbin/update-locale LANG=de_DE.UTF-8
ENV LC_ALL de_DE.UTF-8

#Postgres for Debian
RUN wget -q https://www.postgresql.org/media/keys/ACCC4CF8.asc -O- | sudo apt-key add - && \
    sh -c 'echo "deb https://apt.postgresql.org/pub/repos/apt/ buster-pgdg main" | sudo tee /etc/apt/sources.list.d/postgresql.list' && \
    apt-get update && \
    apt-get install -y postgresql-client-14

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
    imagemagick \
    htop \
    dnsutils \
    curl \
    unzip \
    sqlite3 \
    nano \
    mc \
    pkg-config \
    geoip-bin \
    geoip-database \
    python3-dev \
    libxml2-dev \
    libxslt1-dev \
    libldap2-dev \
    libsasl2-dev \
    libtiff5-dev \
    libjpeg62-turbo-dev \
    libopenjp2-7-dev \
    zlib1g-dev \
    libfreetype6-dev \
    liblcms2-dev \
    libwebp-dev \
    libharfbuzz-dev \
    libfribidi-dev \
    libxcb1-dev \
    libpq-dev \
    build-essential \
    nodejs \
    npm \
    xfonts-75dpi \
    xfonts-base

RUN set -x; \
    npm install -g rtlcss && \
    npm install -g less && \
    npm install -g less-plugin-clean-css


RUN set -x; \
    python3 -m pip install --no-cache-dir pip --upgrade \
    && python3 -m pip install --no-cache-dir wheel --upgrade \
    && python3 -m pip install --no-cache-dir Babel==2.9.1 \
    && python3 -m pip install --no-cache-dir chardet==3.0.4 \
    && python3 -m pip install --no-cache-dir cryptography==3.4.8 \
    && python3 -m pip install --no-cache-dir decorator==4.4.2 \
    && python3 -m pip install --no-cache-dir docutils==0.16 \
    && python3 -m pip install --no-cache-dir ebaysdk==2.1.5 \
    && python3 -m pip install --no-cache-dir freezegun==0.3.15 \
    && python3 -m pip install --no-cache-dir gevent==20.9.0 \
    && python3 -m pip install --no-cache-dir greenlet==0.4.17 \
    && python3 -m pip install --no-cache-dir idna==2.8 \
    && python3 -m pip install --no-cache-dir Jinja2==2.11.3 \
    && python3 -m pip install --no-cache-dir libsass==0.18.0 \
    && python3 -m pip install --no-cache-dir lxml==4.6.5 \
    && python3 -m pip install --no-cache-dir MarkupSafe==1.1.0 \
    && python3 -m pip install --no-cache-dir num2words==0.5.6 \
    && python3 -m pip install --no-cache-dir ofxparse==0.19 \
    && python3 -m pip install --no-cache-dir passlib==1.7.3 \
    && python3 -m pip install --no-cache-dir Pillow==9.0.1 \
    && python3 -m pip install --no-cache-dir polib==1.1.0 \
    && python3 -m pip install --no-cache-dir psutil==5.6.7 \
    && python3 -m pip install --no-cache-dir psycopg2==2.8.6 \
    && python3 -m pip install --no-cache-dir pydot==1.4.1 \
    && python3 -m pip install --no-cache-dir pyopenssl==19.0.0 \
    && python3 -m pip install --no-cache-dir PyPDF2==1.26.0 \
    && python3 -m pip install --no-cache-dir pyserial==3.4 \
    && python3 -m pip install --no-cache-dir python-dateutil==2.7.3 \
    && python3 -m pip install --no-cache-dir python-ldap==3.1.0 \
    && python3 -m pip install --no-cache-dir python-stdnum==1.13 \
    && python3 -m pip install --no-cache-dir pytz==2019.3 \
    && python3 -m pip install --no-cache-dir pyusb==1.0.2 \
    && python3 -m pip install --no-cache-dir qrcode==6.1 \
    && python3 -m pip install --no-cache-dir reportlab==3.5.59 \
    && python3 -m pip install --no-cache-dir requests==2.25.1 \
    && python3 -m pip install --no-cache-dir vobject==0.9.6.1 \
    && python3 -m pip install --no-cache-dir Werkzeug==0.16.1 \
    && python3 -m pip install --no-cache-dir XlsxWriter==1.1.2 \
    && python3 -m pip install --no-cache-dir xlwt==1.3.* \
    && python3 -m pip install --no-cache-dir zeep==3.4.0 \
    && python3 -m pip install --no-cache-dir openpyxl \
    && python3 -m pip install --no-cache-dir pycryptodome==3.9.0 \
    && python3 -m pip install --no-cache-dir nextcloud-api-wrapper \
    && python3 -m pip install --no-cache-dir xmltodict==0.12.0 \
    && python3 -m pip install --no-cache-dir holidays==0.10.1 \
    && python3 -m pip install --no-cache-dir beautifulsoup4==4.11.1 \
    && python3 -m pip install --no-cache-dir bleach==3.1.5 \
    && python3 -m pip install --no-cache-dir phonenumbers \
    && python3 -m pip install --no-cache-dir odoorpc-toolbox \
    && python3 -m pip install --no-cache-dir python-slugify \
    && python3 -m pip install --no-cache-dir parse-accept-language \
    && python3 -m pip install --no-cache-dir wget \
    && python3 -m pip install --no-cache-dir python-docx \
    && python3 -m pip install --no-cache-dir paramiko \
    && python3 -m pip install --no-cache-dir python-barcode \
    && python3 -m pip install --no-cache-dir pyston_lite_autoload

# PDF export engine install..
RUN set -x; \
    curl -k -o wkhtmltox.deb -SL https://rm.myodoo.net/staff/wkhtmltox_0.12.5-1.buster_amd64.deb \
    && dpkg --force-depends -i wkhtmltox.deb \
    && ln -s /usr/local/bin/wkhtmltopdf /usr/bin \
    && ln -s /usr/local/bin/wkhtmltoimage /usr/bin \
    && apt-get -y install -f --no-install-recommends \
    && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false -o APT::AutoRemove::SuggestsImportant=false  \
    && rm -rf /var/lib/apt/lists/* wkhtmltox.deb

# Finished with build.
