#!/bin/bash
# Install pypy / pypy3 
# Script must run with mit root-rights
# Version 1.0.0 - Stand 30.04.2019
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
apt-get update && apt-get -y dist-upgrade 

# PyPy 3.6
wget https://bitbucket.org/pypy/pypy/downloads/pypy3.6-v7.1.1-linux64.tar.bz2 \
    && tar xfj pypy3.6-v7.1.1-linux64.tar.bz2 \
    && mv pypy3.6-v7.1.1-linux64/ pypy3.6/ \
    && mv pypy3.6/ /opt/ \
    && wget https://bootstrap.pypa.io/get-pip.py \
    && /opt/pypy3.6/bin/pypy3 get-pip.py \
    && /opt/pypy3.6/bin/pypy3 -m pip install odoorpc \
    && /opt/pypy3.6/bin/pypy3 -m pip install xlrd \
    && rm pypy3.6-v7.1.1-linux64.tar.bz2 \
    && rm get-pip.py \
    && /opt/pypy3.6/bin/pypy3 -m pip list



