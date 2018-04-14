#!/bin/bash
# Install a Python 3.6 env
# Version 1.0.0 - Stand 14.04.2018
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

# To prepare your Ubuntu 16.04
# sudo apt-get install python3-pip
# sudo pip3 install virtualenv

mypython="p36-min"
mypath="/home/ownerp/venv/"
myenv=$mypath$mypython

if [ ! -d $myenv ]; then
  mkdir -p $myenv
fi
cd $mypath

virtualenv -p /usr/local/bin/python3.6 $mypython
echo '[list]\nformat=columns' > pip.conf
source $mypython/bin/activate

python3.6 -m pip install --no-cache-dir pip==9.0.3 \
    && python3.6 -m pip install --no-cache-dir wheel --upgrade \
    && python3.6 -m pip install --no-cache-dir setuptools --upgrade \
    && python3.6 -m pip install --no-cache-dir openpyxl \
    && python3.6 -m pip install --no-cache-dir odoorpc \

cd $mypath && source $mypython/bin/activate && cd $myenv
