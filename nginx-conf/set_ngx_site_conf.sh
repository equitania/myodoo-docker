#!/bin/bash
# Create nginx configuration at /etc/nginx/conf.d/
# Script needs root-rights 
# Version 1.0.1
# Date 18.12.2020
##############################################################################
#
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

#test cases
#myserverpath="/home/devops/temp/"

myconf=$1
myip=$2
mydomain=$3
myport=$4
mycert=$5
mypollport=$6


echo "Starting create nginx conf "
echo "Basepath: "$myscriptpath
echo "Serverpath: "$myserverpath

if [ "$myconf" = "" ]; then
  echo "Insert the conf-template | Geben Sie die conf-Vorlage an:"
  echo "We support:"
  echo "- ngx_code_server"
  echo "- ngx_fast_report"
  echo "- ngx_nextcloud"
  echo "- ngx_odoo_http"
  echo "- ngx_odoo_ssl_pagespeed"
  echo "- ngx_odoo_ssl"
  echo "- ngx_pgadmin"
  echo "- ngx_pwa"
  echo "- ngx_redirect_ssl"
  echo "- ngx_redirect"
  echo "->"
  read myconf
fi

if [ "$myip" = "" ]; then
  echo "Insert the server ip address | Geben Sie die Server IP Adresse ein:"
  read myip
fi

if [ "$mydomain" = "" ]; then
  echo "Insert the domain name incl. Subdomain | Geben Sie den Domainnamen inkl. Subdomain ein:"
  read mydomain
fi

if [ "$myport" = "" ]; then
  echo "Insert the expose port | Geben Sie den Port für Odoo ein:"
  read myport
fi

if [ "$mycert" = "" ]; then
  echo "Insert the Let's encrypted cert name | Geben Sie den Name des Let's encrypted Zertikates ein:"
  read mycert
fi

if [ "$mypollport" = "" ]  | [ "$myconf" = "ngx_odoo_http" ] || [ "$myconf" = "ngx_odoo_ssl_pagespeed" ] || [ "$myconf" = "ngx_odoo_ssl" ]; then
  echo "Insert the polling expose port | Geben Sie den Port für Odoo ein:"
  read mypollport
fi


myolddomain="server.domain.de"
myoldip="ip.ip.ip.ip"
myoldport="oldport"
myoldpollport="oldpollport"
myoldcrt="zertifikat.crt"
myoldkey="zertifikat.key"

if [ "$myconf" != "" ] || [ "$myip" != "" ] || [ "$mydomain" != "" ] || [ "$myport" != "" ] || [ "$mycert" != "" ]; then
  echo "Copy" $myscriptpath"/$myconf.conf" $myserverpath"/$mydomain.conf"
  cp  $myscriptpath"/$myconf.conf" $myserverpath"/$mydomain.conf"
  echo "Set domain name in conf to "$mydomain
  sed -i "s/$myolddomain/$mydomain/g" $myserverpath"/$mydomain.conf"
  echo "Set ip in conf to "$myip
  sed -i "s/$myoldip/$myip/g" $myserverpath"/$mydomain.conf"
  echo "Set cert name in conf to "$mycert
  sed -i "s/$myoldcrt/$mycert/g" $myserverpath"/$mydomain.conf"
  sed -i "s/$myoldkey/$mycert/g" $myserverpath"/$mydomain.conf"
  echo "Set port in conf to "$myport
  sed -i "s/$myoldport/$myport/g" $myserverpath"/$mydomain.conf"
  if [ "$mypollport" != "" ]; then
    echo "Set polling port in conf to "$mypollport
    sed -i "s/$myoldpollport/$mypollport/g" $myserverpath"/$mydomain.conf"
  fi
  echo "Finished!"
else
  echo "Parameter wasn't correct - Parameter waren fehlerhaft!"
fi