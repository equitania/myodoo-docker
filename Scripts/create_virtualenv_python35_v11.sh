#!/bin/bash
# Install all Python 3.5 Libs for Odoo 11
# Version 2.0.3 - Stand 04.03.2018
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
git clone -b develop git@gitlab.ownerp.io:v11-myodoo-public/v11-server.git
virtualenv -p /usr/bin/python3.5 v11-server
echo '[list]\nformat=columns' > pip3.conf
source v11-server/bin/activate

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
    && pip3 install lxml==3.7.1 \
    && pip3 install Mako==1.0.4 \
    && pip3 install MarkupSafe==0.23 \
    && pip3 install mock==2.0.0 \
    && pip3 install num2words==0.5.4 \
    && pip3 install ofxparse==0.16 \
    && pip3 install passlib==1.6.5 \
    && pip3 install Pillow==4.0.0 \
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


cd /home/ownerp/Public/gitbase/ && source v11-server/bin/activate && cd /home/ownerp/Public/gitbase/v11-server/
