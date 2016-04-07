#!/bin/bash
# Mit diesem Skript installiert Odoo unter /opt/odoo und bindet es in den Autostart ein
# Skript muss mit root-Rechten ausgeführt werden
# Version 1.2.1 - Stand 29.03.2016
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

echo "Geben Sie den Namen für den User für Ihre Odoo Datenbank innerhalb der PostgreSQL an: "
read mypguser

echo "Geben Sie das Passwort für den User $mypguser innerhalb der PostgreSQL an (Leerlassen für kein Passwort): "
read myodoopwd

if [ "$mypguser" != "" ]; then
  adduser $mypguser --no-create-home --gecos "" --disabled-login
  echo "PostgreSQL Passwort $mypguser wird gesetzt ..."
  su postgres -c "psql --command \"CREATE USER $mypguser WITH PASSWORD '$myodoopwd'\""
  su postgres -c "psql --command \"ALTER USER $mypguser CREATEDB\""
fi

echo "Geben Sie das Passwort für den User postgres innerhalb der PostgreSQL an (Leerlassen für kein Passwort): "
read mypsqlpwd

if [ "$mypsqlpwd" != "" ]; then
  echo "PostgreSQL Passwort postgres wird gesetzt ..."
  su postgres -c "psql --command \"ALTER USER postgres WITH PASSWORD '$mypsqlpwd'\""
fi

