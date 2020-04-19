#!/bin/bash
# Mit diesem Skript wird ein Restore einer Odoo Datenbank in 2 Docker-Container durchgeführt
# With this script you can restore an odoo db on 2 Docker containers
# Version 1.1.0
# Date 14.12.2015
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
mybackuppath="/root/"
mybasepath="$HOME"

echo "Your home path is: "$mybasepath
echo "Your backup path is: "$mybackuppath
echo "So your zip file should store there!"

mydb=$1
mysqlcontainer=$2
mydatacontainer=$3
mydel=$4
mybackupzip=$5
mycron=$6

if [ "$mydb" = "" ]; then
  echo "Name of the new db:"
  read mydb
fi

if [ "$mysqlcontainer" = "" ]; then
  echo "ID of the Postgres container:"
  read mysqlcontainer
fi

if [ "$mydatacontainer" = "" ]; then
  echo "ID of the Data container:"
  read mydatacontainer
fi

if [ "$mydel" = "" ]; then
  echo "Delete the old version of $mydb [Y/n]:"
  read mydel
fi

if [ "$mydel" == "Y" ] || [ "$mydel" == "y" ]; then
  docker exec -i $mysqlcontainer dropdb -U postgres $mydb
  echo "Drop is done."
fi

if [ "$mybackupzip" = "" ]; then
  echo "Name of the backupfile (path: $mybackuppath):"
  read mybackupzip
fi

if [ "$mydb" != "" ]; then
  echo "Unzip $mybackuppath/$mybackupzip.."
  cd $mybackuppath
  unzip $mybackuppath/$mybackupzip
  mybackup=dump.sql
  if [ -f "$mybackup" ]; then
	 echo "$mybackup found."
  else
	echo "$mybackup not found."
	mv "$mydb/$mybackup" /root/
	mv "$mydb/filestore" /root/
	rm -rf $mydb
  fi
  echo "Create DB $mydb with $mybackup file.."
  if [ "$mysqlcontainer" != "" ]; then
    docker exec -i $mysqlcontainer createdb -U odoo -T template0 $mydb
    echo "Restore DB $mydb"
    cat $mybackup | docker exec -i $mysqlcontainer psql -U odoo -d $mydb
    if [ "$mycron" = "" ]; then
      echo "Do you want to deactivate cronjob functions in $mydb [Y/n]:"
      read mycron
    fi
    if [ "$mycron" == "Y" ] || [ "$mycron" == "y" ]; then
      docker exec -i $mysqlcontainer psql -d $mydb -U odoo -c $'UPDATE ir_cron SET active = FALSE;'
    fi
  fi
  if [ "$mydatacontainer" != "" ]; then
    filestorepath="/opt/odoo/data/filestore/"
    docker exec -i $mydatacontainer mkdir -p /opt/odoo/data/filestore/
    mv $mybackuppath/filestore $mybackuppath/$mydb
    docker cp /root/$mydb $mydatacontainer:/opt/odoo/data/filestore/
    docker exec -i $mydatacontainer chown -R odoo:odoo /opt/odoo/data/
  fi
  rm $mybackuppath/$mybackup
  rm -rf $mybackuppath/$mydb
  # Delete Manifest if exists
  if [ -f "$mybackuppath/manifest.json" ]; then
    rm "$mybackuppath/manifest.json"
  fi
  echo "Restore is done."
else
  echo "No restore."
fi

cd $mybasepath
echo "Finished!"
