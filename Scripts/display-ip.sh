#!/bin/bash
# Mit diesem Skript wird das System so erweitert, 
# dass die IP-Adresse beim Login angezeigt wird
# Verwenden Sie den Benutzer root
# With this script you can display the server ip address at start screen
##############################################################################
#
#    Shell Script for Debian / Ubuntu
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

echo "Do you want to modify your system? | Wollen Sie Ihr System anpassen (Y/n):"
read myip

if [ "$myip" == "Y" ]; then
  cp get-ip-address /usr/local/bin/
  cp show-ip-address /etc/network/if-up.d/
  echo "Your system will now display ip at start ..."
else
  echo "No changes!"
fi

echo "Finished!"
