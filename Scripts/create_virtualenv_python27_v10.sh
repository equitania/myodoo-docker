#!/bin/bash
# Install all Python 2.7 Libs for Odoo 10
# Version 2.0.4 - Stand 05.04.2018
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
git clone -b develop git@gitlab.ownerp.io:v10-myodoo-public/v10-server.git
virtualenv -p /usr/bin/python2.7 v10-server
echo '[list]\nformat=columns' > pip.conf
source v10-server/bin/activate

python2.7 -m pip install --no-cache-dir pip==9.0.3 \
    && python2.7 -m pip install --no-cache-dir wheel --upgrade \
    && python2.7 -m pip install --no-cache-dir setuptools --upgrade \
    && python2.7 -m pip install --no-cache-dir psycopg2==2.7.3.1 \
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
    && python2.7 -m pip install --no-cache-dir ofxparse==0.16 \
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
    && python2.7 -m pip install --no-cache-dir python-ldap==2.4.27 \
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
    && python2.7 -m pip install --no-cache-dir xlrd==1.0.0 \
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
    && python2.7 -m pip install --no-cache-dir elasticsearch==6.1.1 \
    && python2.7 -m pip install --no-cache-dir openpyxl \
    && python2.7 -m pip install --no-cache-dir phonenumbers \
    && python2.7 -m pip install --no-cache-dir pysftp \
    && python2.7 -m pip install --no-cache-dir email \
    && python2.7 -m pip install --no-cache-dir suds \
    && python2.7 -m pip install --no-cache-dir pycrypto==2.6.1 \
    && python2.7 -m pip install --no-cache-dir pyocclient==0.4 \
    && python2.7 -m pip install --no-cache-dir dropbox==8.7.1

cd /home/ownerp/Public/gitbase/ && source v10-server/bin/activate && cd /home/ownerp/Public/gitbase/v10-server/
