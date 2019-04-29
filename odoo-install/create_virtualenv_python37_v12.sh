#!/bin/bash
# Install all Python 3.7 Libs for Odoo 12
# Version 2.0.3 - Stand 28.04.2019
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

# To prepare your Ubuntu 18.04
# sudo apt-get install python3-pip
# sudo pip3 install virtualenv
# Python 3.7 erzeugen
#cd /usr/src
#wget https://www.python.org/ftp/python/3.7.3/Python-3.7.3.tgz \
#    && tar xzf Python-3.7.3.tgz \
#    && cd Python-3.7.3 \
#    && ./configure --enable-optimizations \
#    && make altinstall \
#    && cd /usr/src \
#    && rm -rf Python-3.7.3* \
#    && cd /root/
# sudo make altinstall
# sudo pip3.7 install --upgrade pip

mypython="v12-p37"
mypath="$HOME/venv/"
myenv=$mypath$mypython

if [ ! -d $myenv ]; then
  mkdir -p $myenv
fi
cd $mypath

virtualenv -p /usr/local/bin/python3.7 $mypython
#echo '[list]\nformat=columns' > pip.conf
source $mypython/bin/activate

python3.7 -m pip install --no-cache-dir wheel --upgrade \
    && python3.7 -m pip install --no-cache-dir Babel==2.3.4 \
    && python3.7 -m pip install --no-cache-dir chardet==3.0.4 \
    && python3.7 -m pip install --no-cache-dir decorator==4.0.10 \
    && python3.7 -m pip install --no-cache-dir docutils==0.12 \
    && python3.7 -m pip install --no-cache-dir feedparser==5.2.1 \
    && python3.7 -m pip install --no-cache-dir gevent==1.3.4 \
    && python3.7 -m pip install --no-cache-dir greenlet==0.4.13 \
    && python3.7 -m pip install --no-cache-dir html2text==2016.9.19 \
    && python3.7 -m pip install --no-cache-dir Jinja2==2.10.1 \
    && python3.7 -m pip install --no-cache-dir libsass==0.12.3 \
    && python3.7 -m pip install --no-cache-dir lxml==4.2.3 \
    && python3.7 -m pip install --no-cache-dir Mako==1.0.4 \
    && python3.7 -m pip install --no-cache-dir MarkupSafe==0.23 \
    && python3.7 -m pip install --no-cache-dir mock==2.0.0 \
    && python3.7 -m pip install --no-cache-dir num2words==0.5.4 \
    && python3.7 -m pip install --no-cache-dir ofxparse==0.16 \
    && python3.7 -m pip install --no-cache-dir passlib==1.6.5 \
    && python3.7 -m pip install --no-cache-dir Pillow==4.0.0 \
    && python3.7 -m pip install --no-cache-dir psutil==4.3.1 \
    && python3.7 -m pip install --no-cache-dir psycopg2==2.7.3.1 \
    && python3.7 -m pip install --no-cache-dir pydot==1.2.3 \
    && python3.7 -m pip install --no-cache-dir pyldap==2.4.28 \
    && python3.7 -m pip install --no-cache-dir pyparsing==2.1.10 \
    && python3.7 -m pip install --no-cache-dir PyPDF2==1.26.0 \
    && python3.7 -m pip install --no-cache-dir pyserial==3.1.1 \
    && python3.7 -m pip install --no-cache-dir python-dateutil==2.5.3 \
    && python3.7 -m pip install --no-cache-dir pydot==1.2.3 \
    && python3.7 -m pip install --no-cache-dir pyldap==2.4.28 \
    && python3.7 -m pip install --no-cache-dir pyparsing==2.1.10 \
    && python3.7 -m pip install --no-cache-dir PyPDF2==1.26.0 \
    && python3.7 -m pip install --no-cache-dir pyserial==3.1.1 \
    && python3.7 -m pip install --no-cache-dir python-dateutil==2.5.3 \
    && python3.7 -m pip install --no-cache-dir pytz==2016.7 \
    && python3.7 -m pip install --no-cache-dir pyusb==1.0.0 \
    && python3.7 -m pip install --no-cache-dir PyYAML==3.13 \
    && python3.7 -m pip install --no-cache-dir qrcode==5.3 \
    && python3.7 -m pip install --no-cache-dir reportlab==3.3.0 \
    && python3.7 -m pip install --no-cache-dir requests==2.11.1 \
    && python3.7 -m pip install --no-cache-dir suds-jurko==0.6 \
    && python3.7 -m pip install --no-cache-dir vatnumber==1.2 \
    && python3.7 -m pip install --no-cache-dir vobject==0.9.3 \
    && python3.7 -m pip install --no-cache-dir Werkzeug==0.11.15 \
    && python3.7 -m pip install --no-cache-dir XlsxWriter==0.9.3 \
    && python3.7 -m pip install --no-cache-dir xlwt==1.3.* \
    && python3.7 -m pip install --no-cache-dir xlrd==1.0.0 \
    && python3.7 -m pip install --no-cache-dir openpyxl \
    && python3.7 -m pip install --no-cache-dir phonenumbers \
    && python3.7 -m pip install --no-cache-dir odoorpc \
    && python3.7 -m pip install --no-cache-dir python-slugify \
    && python3.7 -m pip install --no-cache-dir parse-accept-language \
    && python3.7 -m pip install --no-cache-dir elasticsearch==6.1.1 \
    && python3.7 -m pip install --no-cache-dir MT-940


cd $mypath && source $mypython/bin/activate && cd cd $HOME/gitbase/v12/v12-server/
