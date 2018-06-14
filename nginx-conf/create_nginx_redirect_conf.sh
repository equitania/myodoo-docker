#!/bin/bash
# Erzeugt man eine nginx Konfiguration inkl. SSL
# Skript muss mit root-Rechten ausgeführt werden
# Version 2.0.0
# Date 14.06.2018
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

myscriptpath="$PWD"
myserverpath="/etc/nginx/conf.d/"
myip=$1
mydomain=$2
mytarget=$3

echo "Dieses Skript erstellt einen Redirect auf die eingebene Domain mit www als Präfix!"
echo "Basepath: "$myscriptpath
echo "Serverpath: "$myserverpath


if [ "$myip" = "" ]; then
  echo "Insert the server ip address | Geben Sie die Server IP Adresse ein:"
  read myip
fi

if [ "$mydomain" = "" ]; then
  echo "Insert the domain name | Geben Sie den Domainnamen ein:"
  read mydomain
fi

if [ "$mytarget" = "" ]; then
  echo "Insert the target domain name | Geben Sie den Ziel-Domainnamen ein:"
  read mytarget
fi


myolddomain="server.domain.de"
myoldtarget="target.domain.de"
myoldip="ip.ip.ip.ip"

if [ "$myip" != "" ] || [ "$mydomain" != "" ] || [ "$myport" != "" ]; then
  cp  $myscriptpath"/nginx.server.domain_redirect.conf" $myserverpath"/$mydomain.conf"
  sed -i "s/$myolddomain/$mydomain/g" $myserverpath"/$mydomain.conf"
  sed -i "s/$myoldtarget/$mytarget/g" $myserverpath"/$mydomain.conf"
  sed -i "s/$myoldip/$myip/g" $myserverpath"/$mydomain.conf"
  echo "Finished!"
else
  echo "Parameter wasn't correct - Parameter waren fehlerhaft!"
fi
