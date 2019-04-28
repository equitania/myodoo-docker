#!/bin/bash
# Install all basic and Python 3.5 Libs for Odoo 11
# Script must run with mit root-rights
# Version 1.0.0 - Stand 05.04.2018
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

apt-get update

apt-get install -y --no-install-recommends \
	ca-certificates \
	locales \
	ghostscript \
	graphviz \
	antiword  \
	poppler-utils \
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
	sqlite3 \
	geoip-bin \
	geoip-database \
	node-less \
	node-clean-css \
	imagemagick \
	xfonts-75dpi \
	xfonts-base

apt-get install -y --no-install-recommends \
    python-software-properties \
	python-pip  \
	python-ldap \
	python-magic \
	python-libxslt1 \
	python-imaging \
	python-renderpm \
	python-reportlab-accel \
	python-tz \
    python-zsi \
    python-webdav

apt-get -y install -f --no-install-recommends
apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false -o APT::AutoRemove::SuggestsImportant=false npm
