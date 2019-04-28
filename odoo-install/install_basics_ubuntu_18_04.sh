#!/bin/bash
# Install all basic and Python 2.7 Libs for Odoo 10
# Script must run with mit root-rights
# Version 1.0.0 - Stand 26.04.2019
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

# Basis Ubuntu
apt-get update && apt-get -y dist-upgrade && apt-get install -y wget locales tzdata gnupg2 && \
        ln -sf /usr/share/zoneinfo/Europe/Berlin /etc/localtime

# Nötige Grundpakete 
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
    python-minimal \
    python-dev \
    python3-pip \
    libxml2-dev \
    libxslt1-dev \
    libldap2-dev \
    libsasl2-dev \
    libffi-dev \
    unzip \
    sqlite3 \
    nano \
    mc \
    git \
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

# PostgreSQL Server 9.6
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add - && \
    sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt/ bionic-pgdg main" >> /etc/apt/sources.list.d/pgdg.list' && \
    apt-get update && \
    apt-get install -y postgresql-9.6 postgresql-client-9.6

# Python Module
apt-get install -y --no-install-recommends \
    software-properties-common \
    python-pip  \
    python-magic \
    python-libxslt1 \
    python-pil \
    python-renderpm \
    python-reportlab-accel \
    python-tz \
    python-zsi \
    python-webdav

# Module für Python 3.7 Build
apt-get -y install build-essential checkinstall \
    libreadline-gplv2-dev libncursesw5-dev libssl-dev \
    libsqlite3-dev tk-dev libgdbm-dev libc6-dev libbz2-dev libffi-dev

# Python 3.7 erzeugen
cd /usr/src
wget https://www.python.org/ftp/python/3.7.3/Python-3.7.3.tgz \
    && tar xzf Python-3.7.3.tgz \
    && cd Python-3.7.3 \
    && ./configure --enable-optimizations \
    && make altinstall \
    && cd /usr/src \
    && rm -rf Python-3.7.3* \
    && cd /root/

# Opensans Schrift
wget https://rm.myodoo.net/staff/opensans.zip \
    && unzip opensans.zip \
    && mv opensans /usr/share/fonts/truetype/ \
    && rm opensans.zip

# Barcode
wget https://rm.myodoo.net/staff/pfbfer.zip \
    && unzip pfbfer.zip -d fonts \
    && cp -r fonts /usr/local/lib/python2.7/dist-packages/reportlab/ \
    && mv fonts /usr/local/lib/python3.6/dist-packages/reportlab/ \
    && rm pfbfer.zip \
    && fc-cache -f -v

# WKHTML2PDF
curl -k -o wkhtmltox.deb -SL https://rm.myodoo.net/staff/wkhtmltox_0.12.5-1.bionic_amd64.deb \
    && dpkg --force-depends -i wkhtmltox.deb \
    && ln -s /usr/local/bin/wkhtmltopdf /usr/bin \
    && ln -s /usr/local/bin/wkhtmltoimage /usr/bin

# Cleanup
apt-get -y autoremove && apt-get -y autoclean
