#!/bin/bash
# Install all Python 2.7 Libs for Odoo 8
# Script must run with mit root-rights
# Version 1.0.14 - Stand 04.03.2018
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

cd /home/ownerp/Public/gitbase/
git clone -b develop git@gitlab.ownerp.io:v8-myodoo-public/v8-server.git
virtualenv -p /usr/bin/python2.7 v8-server
echo '[list]\nformat=columns' > pip.conf
source v8-server/bin/activate


python2.7 -m pip install --upgrade pip \
    && python2.7 -m pip install psycopg2==2.7.1 \
    && python2.7 -m pip install argparse==1.2.1 \
    && python2.7 -m pip install Babel==2.3.4 \
    && python2.7 -m pip install decorator==4.0.10 \
    && python2.7 -m pip install docutils==0.12 \
    && python2.7 -m pip install feedparser==5.2.1 \
    && python2.7 -m pip install gevent==1.1.2 \
    && python2.7 -m pip install greenlet==0.4.10 \
    && python2.7 -m pip install jcconv==0.2.3 \
    && python2.7 -m pip install Jinja2==2.8 \
    && python2.7 -m pip install lxml==3.6.4 \
    && python2.7 -m pip install Mako==1.0.4 \
    && python2.7 -m pip install MarkupSafe==0.23 \
    && python2.7 -m pip install mock==2.0.0 \
    && python2.7 -m pip install ofxparse==0.15 \
    && python2.7 -m pip install passlib==1.6.5 \
    && python2.7 -m pip install Pillow==3.4.1 \
    && python2.7 -m pip install psutil==4.3.1 \
    && python2.7 -m pip install psycogreen==1.0 \
    && python2.7 -m pip install pydot==1.2.3 \
    && python2.7 -m pip install pyparsing==2.1.10 \
    && python2.7 -m pip install pyPdf==1.13 \
    && python2.7 -m pip install pyserial==3.1.1 \
    && python2.7 -m pip install Python-Chart==1.39 \
    && python2.7 -m pip install python-dateutil==2.5.3 \
    && python2.7 -m pip install python-openid==2.2.5 \
    && python2.7 -m pip install pytz==2016.7 \
    && python2.7 -m pip install pyusb==1.0.0 \
    && python2.7 -m pip install PyYAML==3.12 \
    && python2.7 -m pip install qrcode==5.3 \
    && python2.7 -m pip install reportlab==3.3.0 \
    && python2.7 -m pip install requests==2.11.1 \
    && python2.7 -m pip install six==1.10.0 \
    && python2.7 -m pip install suds-jurko==0.6 \
    && python2.7 -m pip install vatnumber==1.2 \
    && python2.7 -m pip install vobject==0.9 \
    && python2.7 -m pip install Werkzeug==0.11.11 \
    && python2.7 -m pip install wsgiref==0.1.2 \
    && python2.7 -m pip install XlsxWriter==0.9.3 \
    && python2.7 -m pip install xlwt==1.1.2

python2.7 -m pip install gdata \
    && python2.7 -m pip install simplejson \
    && python2.7 -m pip install unittest2 \
    && python2.7 -m pip install pdftools \
    && python2.7 -m pip install matplotlib \
    && python2.7 -m pip install beautifulsoup4 \
    && python2.7 -m pip install evdev \
    && python2.7 -m pip install polib \
    && python2.7 -m pip install unidecode \
    && python2.7 -m pip install validate_email \
    && python2.7 -m pip install pyDNS \
    && python2.7 -m pip install python-slugify \
    && python2.7 -m pip install paramiko==1.9.0 \
    && python2.7 -m pip install pycrypto==2.6 \
    && python2.7 -m pip install pyinotify \
    && python2.7 -m pip install ecdsa==0.11 \
    && python2.7 -m pip install sphinx \
    && python2.7 -m pip install Pygments==2.0 \
    && python2.7 -m pip install egenix-mx-base \
    && python2.7 -m pip install pypdf2 \
    && python2.7 -m pip install odoorpc \
    && python2.7 -m pip install pyelasticsearch \
    && python2.7 -m pip install openpyxl \
    && python2.7 -m pip install phonenumbers \
    && python2.7 -m pip install pysftp \
    && python2.7 -m pip install soappy

cd /home/ownerp/Public/gitbase/ && source v8-server/bin/activate && cd /home/ownerp/Public/gitbase/v8-server/