#!/bin/bash
# Install basic libs for all Odoo versions
# Script must run with mit root-rights
# Version 1.0.1 - Stand 05.11.2018
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

wget https://release.myodoo.de/fonts/opensans.zip \
    && unzip opensans.zip \
	&& mv opensans /usr/share/fonts/truetype/ \
	&& rm opensans.zip

wget http://www.reportlab.com/ftp/pfbfer.zip \
	&& unzip pfbfer.zip -d fonts \
	&& mv fonts /usr/lib/python2.7/dist-packages/reportlab/ \
	&& rm pfbfer.zip \
	&& fc-cache -f -v

curl -k -o wkhtmltox.deb -SL https://rm.ownerp.io/staff/wkhtmltox-0.12.2.1_linux-trusty-amd64.deb \
	&& dpkg --force-depends -i wkhtmltox.deb \
    && ln -s /usr/local/bin/wkhtmltopdf /usr/bin \
    && ln -s /usr/local/bin/wkhtmltoimage /usr/bin \
    && apt-get -y install -f --no-install-recommends \
	&& apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false -o APT::AutoRemove::SuggestsImportant=false npm \
	&& rm -rf /var/lib/apt/lists/* wkhtmltox.deb