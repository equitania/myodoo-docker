#!/bin/bash
# Install all Python 3.8 Libs for Odoo 13
# Version 1.0.0 - Stand 09.11.2020
##############################################################################

# To prepare your Ubuntu 18.04
# sudo apt-get install python3-pip
# sudo pip3 install 


mypython="v13-p38"
mypath="/venv/"
myenv=$mypath$mypython

# delete old
if [ -d "$myenv" ]; then
   rm -rf $myenv
fi
# create new
if [ ! -d $myenv ]; then
  mkdir -p $myenv
fi
cd $mypath

virtualenv -p /usr/bin/python3.8 $mypython
#echo '[list]\nformat=columns' > pip.conf
source $mypython/bin/activate

python3.8 -m pip install --no-cache-dir pip --upgrade \
    && python3.8 -m pip install --no-cache-dir wheel \
    && python3.8 -m pip install --no-cache-dir Babel==2.6.0 \
    && python3.8 -m pip install --no-cache-dir chardet==3.0.4 \
    && python3.8 -m pip install --no-cache-dir decorator==4.3.0 \
    && python3.8 -m pip install --no-cache-dir docutils==0.14 \
    && python3.8 -m pip install --no-cache-dir ebaysdk==2.1.5 \
    && python3.8 -m pip install --no-cache-dir feedparser==5.2.1 \
    && python3.8 -m pip install --no-cache-dir gevent==1.5.0 \
    && python3.8 -m pip install --no-cache-dir greenlet==0.4.15 \
    && python3.8 -m pip install --no-cache-dir html2text==2018.1.9 \
    && python3.8 -m pip install --no-cache-dir Jinja2==2.10.1 \
    && python3.8 -m pip install --no-cache-dir libsass==0.17.0 \
    && python3.8 -m pip install --no-cache-dir lxml==4.3.2 \
    && python3.8 -m pip install --no-cache-dir Mako==1.0.7 \
    && python3.8 -m pip install --no-cache-dir MarkupSafe==1.1.0 \
    && python3.8 -m pip install --no-cache-dir mock==2.0.0 \
    && python3.8 -m pip install --no-cache-dir num2words==0.5.6 \
    && python3.8 -m pip install --no-cache-dir ofxparse==0.19 \
    && python3.8 -m pip install --no-cache-dir passlib==1.7.1 \
    && python3.8 -m pip install --no-cache-dir Pillow==6.1.0 \
    && python3.8 -m pip install --no-cache-dir polib==1.1.0 \
    && python3.8 -m pip install --no-cache-dir psutil==5.6.6 \
    && python3.8 -m pip install --no-cache-dir psycopg2==2.8.3 \
    && python3.8 -m pip install --no-cache-dir pydot==1.4.1 \
    && python3.8 -m pip install --no-cache-dir python-ldap==3.1.0 \
    && python3.8 -m pip install --no-cache-dir pyparsing==2.2.0 \
    && python3.8 -m pip install --no-cache-dir PyPDF2==1.26.0 \
    && python3.8 -m pip install --no-cache-dir pyserial==3.4 \
    && python3.8 -m pip install --no-cache-dir python-dateutil==2.7.3 \
    && python3.8 -m pip install --no-cache-dir pytz==2019.1 \
    && python3.8 -m pip install --no-cache-dir pyusb==1.0.2 \
    && python3.8 -m pip install --no-cache-dir qrcode==6.1 \
    && python3.8 -m pip install --no-cache-dir reportlab==3.5.13 \
    && python3.8 -m pip install --no-cache-dir requests \
    && python3.8 -m pip install --no-cache-dir zeep==3.2.0 \
    && python3.8 -m pip install --no-cache-dir vatnumber==1.2 \
    && python3.8 -m pip install --no-cache-dir vobject==0.9.6.1 \
    && python3.8 -m pip install --no-cache-dir Werkzeug==0.14.1 \
    && python3.8 -m pip install --no-cache-dir XlsxWriter==1.1.2 \
    && python3.8 -m pip install --no-cache-dir xlwt==1.3.* \
    && python3.8 -m pip install --no-cache-dir xlrd==1.1.0 \
    && python3.8 -m pip install --no-cache-dir openpyxl \
    && python3.8 -m pip install --no-cache-dir elasticsearch \
    && python3.8 -m pip install --no-cache-dir pycryptodome==3.9.0 \
    && python3.8 -m pip install --no-cache-dir pyocclient \
    && python3.8 -m pip install --no-cache-dir xmltodict==0.12.0 \
    && python3.8 -m pip install --no-cache-dir phonenumbers \
    && python3.8 -m pip install --no-cache-dir odoorpc \
    && python3.8 -m pip install --no-cache-dir python-slugify \
    && python3.8 -m pip install --no-cache-dir parse-accept-language \
    && python3.8 -m pip install --no-cache-dir MT-940 \
    && python3.8 -m pip install --no-cache-dir Faker \
    && python3.8 -m pip install --no-cache-dir bleach==3.1.5 \
    && python3.8 -m pip install --no-cache-dir randomuser \
    && python3.8 -m pip install --no-cache-dir pandas==0.25.2 \
    && python3.8 -m pip install --no-cache-dir holidays==0.10.1 \
    && python3.8 -m pip install --no-cache-dir python-gitlab \
    && python3.8 -m pip install --no-cache-dir python-redmine==2.3.0 \
    && python3.8 -m pip install --no-cache-dir pyotp \
    && python3.8 -m pip install --no-cache-dir paramiko
