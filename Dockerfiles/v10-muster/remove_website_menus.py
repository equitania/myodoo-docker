#!/usr/bin/python
# -*- coding: utf-8 -*-
# Mit diesem Skript kann man Website Menüs nach dem Update wieder entfernen
# With this script you can remove menus after system update
# Version 1.0.0
# Date 01.11.2018
#
# Prepare
# sudo curl https://bootstrap.pypa.io/get-pip.py | sudo python
# sudo pip install odoorpc
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

import odoorpc

def odoo_connect():
    """
         Prepare the connection to the server
         :return:
    """

    # Use this for http
    odoo_address = 'localhost'
    odoo_port = 8069
    user = 'admin'
    pw = 'password'
    db = 'dbname'
    protocol = 'jsonrpc'

    # Use this for https
    # odoo_address = 'test.myodoo.de' # without praefix http/https etc.
    # odoo_address = 'pwd'
    # odoo_port = 443
    # user = 'admin'
    # pw = 'dbpassword'
    # db = 'dbname'
    # protocol = 'jsonrpc+ssl'


    if odoo_address.startswith('https'):
        ssl = True
        odoo_address = odoo_address.replace('https:', '')
        protocol = 'jsonrpc+ssl'
        if odoo_port <= 0:
            odoo_port = 443
    elif odoo_address.startswith('http:'):
        odoo_address = odoo_address.replace('http:', '')

    while odoo_address and odoo_address.startswith('/'):
        odoo_address = odoo_address[1:]

    while odoo_address and odoo_address.endswith('/'):
        odoo_address = odoo_address[:-1]

    while odoo_address and odoo_address.endswith('\\'):
        odoo_address = odoo_address[:-1]

    odoo_con = odoorpc.ODOO(odoo_address, port=odoo_port, protocol=protocol)
    odoo_con.login(db, user, pw)

    odoo_con.config['auto_commit'] = True  # No need for manual commits
    odoo_con.env.context['active_test'] = False  # Show inactive articles
    odoo_con.env.context['tracking_disable'] = True
    return odoo_con

_odoo = odoo_connect()

_menus_to_remove = ["Shop", "Blog"]
WEBSITE_MENU = _odoo.env['website.menu']
_menus_ids = WEBSITE_MENU.search([("name", "in", _menus_to_remove)])
WEBSITE_MENU.unlink(_menus_ids)