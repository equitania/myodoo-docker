#!/bin/bash
# Erzeugt man eine nginx Konfiguration inkl. SSL
# Skript muss mit root-Rechten ausgeführt werden
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
myport=$3
mykey=$4
mycrt=$5
mylets=$6

echo "Dieses Skript erstellt einen Portweiterleitung auf die eingebene Domain für https!"
echo "Basepath: "$myscriptpath
echo "Serverpath: "$myserverpath

if [ "$myip" = "" ]; then
  echo "Insert the server ip address | Geben Sie die Server IP Adresse ein:"
  read myip
fi

if [ "$mydomain" = "" ]; then
  echo "Insert the domain name incl. Subdomain | Geben Sie den Domainnamen inkl. Subdomain ein:"
  read mydomain
fi

if [ "$myport" = "" ]; then
  echo "Insert the odoo port | Geben Sie den Port für Odoo ein:"
  read myport
fi

if [ "$mykey" = "" ]; then
  echo "Insert the ssl key file name | Geben Sie den Name der SSL key Datei ein:"
  read mykey
fi

if [ "$mycrt" = "" ]; then
  echo "Insert the ssl crt file name | Geben Sie den Name der SSL crt Datei ein:"
  read mycrt
fi

if [ "$mylets" = "" ]; then
  echo "Use let's encrypt | Wollen Sie let's encrypt verwenden? (y/n):"
  read mylets
fi


myolddomain="server.domain.de"
myoldip="ip.ip.ip.ip"
myoldport="oldport"
myoldcrt="zertifikat.crt"
myoldkey="zertifikat.key"
myzert1="#zert1"
myzert2="#zert2"
myempty=""

if [ "$myip" != "" ] || [ "$mydomain" != "" ] || [ "$myport" != "" ] || [ "$mykey" != "" ]  || [ "$mycrt" != "" ]; then
  cp  $myscriptpath"/nginx.server.domain_ssl_ps.conf" $myserverpath"/$mydomain.conf"
  sed -i "s/$myolddomain/$mydomain/g" $myserverpath"/$mydomain.conf"
  sed -i "s/$myoldip/$myip/g" $myserverpath"/$mydomain.conf"
  sed -i "s/$myoldcrt/$mycrt/g" $myserverpath"/$mydomain.conf"
  sed -i "s/$myoldkey/$mykey/g" $myserverpath"/$mydomain.conf"
  sed -i "s/$myoldport/$myport/g" $myserverpath"/$mydomain.conf"
  if [ "$mylets" = "y" ]; then
    sed -i "s/$myzert2/$myempty/g" $myserverpath"/$mydomain.conf"
  else
    sed -i "s/$myzert1/$myempty/g" $myserverpath"/$mydomain.conf"
  fi
  echo "Finished!"
else
  echo "Parameter wasn't correct - Parameter waren fehlerhaft!"
fi
