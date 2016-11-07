#!/bin/bash
# Mit diesem Skript wird ein Restore einer Odoo Datenbank durchgeführt
# Verwenden Sie den Benutzer odoo > sudo su odoo
# With this script you can restore a odoo db on postgresql
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
mydbuser=$2
mydbpw=$3
mydatacontainer=$4
mydel=$5
mybackupzip=$6
mycron=$7

if [ "$mydb" = "" ]; then
  echo "Name of the new db:"
  read mydb
fi

if [ "$mydbuser" = "" ]; then
  echo "Name of the db user:"
  read mydbuser
fi

if [ "$mydbpw" = "" ]; then
  echo "Password of the db user:"
  read mydbpw
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
  dropdb -U $mydbuser -W $mydbpw $mydb
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
  mybackup="dump.sql"
  if [ -f "$mybackup" ]; then
	 echo "$mybackup found."
	 isDocker=""
  else
	 echo "$mybackup not found."
	 isDocker="Y"
	 cd $mydb
	 mybackuppath="$PWD"
  fi
  echo "Create DB $mydb with $mybackup file.."
  createdb -U $mydbuser -W $mydbpw -T template1 $mydb
  echo "Restore DB $mydb"
  psql -U $mydbuser -W $mydbpw -f $mybackuppath/$mybackup -d $mydb -h localhost -p 5432
  # Filestore restore
  #filestorepath="$mybasepath/.local/share/Odoo/filestore/"
  #rm -rf "$mybasepath/.local/share/Odoo/sessions/"
  #if [ -d "$filestorepath$mydb" ]; then
  #  rm -rf "$filestorepath$mydb"
  #fi
  # Restore Filesystem
  #mv "$mybackuppath/filestore" "$mybackuppath/$mydb"
  #cp -r "$mybackuppath/$mydb" $filestorepath
  # Delete dump.sql
  #rm $mybackuppath/$mybackup
  #rm -rf "$mybackuppath/$mydb"
  # Delete Manifest if exists
  #if [ -f "$mybackuppath/manifest.json" ]; then
  #  rm "$mybackuppath/manifest.json"
  #fi
  # If Docker Backup
  #if [ "$isDocker" = "Y" ]; then
  #  cd ..
  #  rm -rf $mydb
  #fi
  echo "Do you want to deactivate cronjob functions in $mydb [Y/n]:"
  read mycron
  if [ "$mycron" == "Y" ] || [ "$mycron" == "y" ]; then
    psql -d $mydb -U $mydbuser -W $mydbpw -c $'UPDATE ir_cron SET active = FALSE;'
  fi
  echo "Restore is done."
else
  echo "No restore."
fi

cd $mybasepath
echo "Finished!"
