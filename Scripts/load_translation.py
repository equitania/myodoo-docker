#!/usr/bin/python
# -*- coding: utf-8 -*-
# Mit diesem Skript werden alle Übersetzungen auf Deutsch neu geladen
# With this script you can backup odoo db on postgresql incl. filestore under Docker
# Version 1.0.0
# Date 29.02.2016
##############################################################################
#
#    Python Script for Odoo, Open Source Management Solution
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
import xmlrpclib

username = "admin"
pwd = "pw"
dbname = "db"
baseurl = "http://localhost:8069"

sock_common = xmlrpclib.ServerProxy(baseurl + "/xmlrpc/common")

uid = sock_common.login(dbname, username, pwd)

sock = xmlrpclib.ServerProxy(baseurl + "/xmlrpc/object")

website_ids = sock.execute(dbname, uid, pwd, 'website', 'search', [])

lang_vals = {
            'lang': 'de_DE',
            'overwrite': True,
             'website_ids': [(6, 0, website_ids)]
             }

lang_id = sock.execute(dbname, uid, pwd, 'base.language.install', 'create', lang_vals)

sock.execute(dbname, uid, pwd, 'base.language.install', 'lang_install', [lang_id])