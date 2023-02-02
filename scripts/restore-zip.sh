#!/bin/bash
# Version 1.1.0 - Stand 02.02.2023
# Mit diesem Skript wird ein Restore einer Odoo Datenbank auf Basis von Docker durchgeführt
# Das FileStore wird in den Odoo Container und die Datenbank in den PostgreSQL Container eingespielt
# With this script you can restore a Odoo db in postgresql on base of Docker
# The filestore will restore in the Odoo container and the db in the posgres container 
###############################################################################################################################
# ./restore-zip.sh
#  -backup_kind(../web/database/manager (1) or automatic backups scripts (2))
#  -runsql (v10,v12,v13,14,v15,16)
#  -orginal-dbname
#  -dbname
#  -drop database(Y/n)
#  -Zip-File
#  -OdooVolumeName
#  -PostgreSQLContainer
#  -Postgresql-Password
# 
# f.e. live-db
# ./restore-zip.sh 2 v10/v12/v13 orgdbname newdbname live-myodoo_dockerbackup.zip live-myodoo vol-odoo-live live-db password
# f.e. test-db
# ./restore-zip.sh 2 v10/v12/v13 orgdbname newdbname test-myodoo_dockerbackup.zip test-myodoo vol-odoo-test test-db password
###############################################################################################################################

mybackuppath=$mybasepath"/opt/backups/docker/"

mykind=$1
myrunsql=$2
myorgdb=$3
mydb=$4
mybackupzip=$5
myodoocontainer=$6
myodoovol=$7
mydbcontainer=$8
mypgpassword=$9

#mypgpassword="ownerp2021" # password for postgresql
mydbuser="ownerp"         # user for postgresql
mydbserver=$mydbcontainer # mostly the same like live-db or test-db

echo "Your backup path is: "$mybackuppath
echo "So your zip file should store there!"
echo "DB kind ../web/database/manager (1) or automatic backups scripts (2): "$mykind
echo "DB original name: "$myorgdb
echo "DB name: "$mydb
echo "DB Zipfile: "$mybackupzip
echo "Name of Odoo Container: "$myodoocontainer
echo "Name of Odoo Volume: "$myodoovol
echo "Name of Postgres Container: "$mydbcontainer
echo "Name of Database Server: "$mydbserver
echo "Name of Database User: "$mydbuser
echo "Database password: "$mypgpassword
echo "Run SQL for Odoo version: "$myrunsql

if [ "$mykind" == "" ]
then
    echo "Backup made with ../web/database/manager (1) or automatic backups scripts (2):"
    read mykind
fi

if [ "$mykind" == "2" ] && [ "$myorgdb" == "" ]
then
    echo "Originalname of the database:"
    read myorgdb
fi

if [ "$mydb" == "" ]
then
    echo "Name of the new database:"
    read mydb
fi

if [ "$mybackupzip" == "" ]
then
    echo "Name of the backupfile (path: $mybackuppath):"
    read mybackupzip
fi

if [ "$myodoovol" == "" ]
then
    echo "Name of the Odoo volume name on Docker:"
    read myodoovol
fi

if [ "$mydbcontainer" == "" ]
then
    echo "Name of the Postgres Container:"
    read mydbcontainer
fi

if [ "$myodoocontainer" == "" ]
then
    echo "Name of the Odoo Container:"
    read myodoocontainer
fi

if [ "$mydbserver" == "" ]
then
    echo "Name of the Postgres database server:"
    read mydbserver
fi

if [ "$mydbuser" == "" ]
then
    echo "Name of the Postgres database user:"
    read mydbuser
fi

if [ "$mystart" == "" ]
then
    echo "Start with import (Y/n):"
    read mystart
fi

if [ "$mystart" != "Y" ] && [ "$mystart" != "y" ]
then
    exit 0
else
    echo "**************************************************"
    echo "**             Starting restore now             **"
    echo "**************************************************"
    echo "docker stop $myodoocontainer"
    docker stop $myodoocontainer
fi


if [ "$mydb" != "" ]
then
    echo "Drop old database..."
    sleep 3
    docker exec -i $mydbcontainer psql -U $mydbuser -d postgres -c "drop database "$mydb";"
    echo "Drop is done."
    echo "Unzip $mybackuppath/$mybackupzip.."
    cd $mybackuppath
    unzip $mybackuppath/$mybackupzip
    mybackup="dump.sql"
    if [ -f "$mybackup" ]
    then
	   echo "$mybackup found."
	   isDocker=""
    else
	   echo "$mybackup based on Docker. "
	   isDocker="Y"
	   cd $myorgdb/$myorgdb
	   mybackuppath="$mybackuppath/$myorgdb"
	   echo "$mybackuppath"
    fi
    echo "Create DB $mydb with $mybackup file.."
    docker exec -i $mydbcontainer psql -U $mydbuser -d postgres -c "CREATE DATABASE "$mydb" OWNER $mydbuser TEMPLATE template0;"
    echo "Restore DB $mydb"
    sleep 3
    cat $mybackuppath/$mybackup | docker exec -i $mydbcontainer psql -U $mydbuser  -d $mydb
    # filestore
    filestorepath="/var/lib/docker/volumes/$myodoovol/_data/filestore/"
    echo "Restore to: $filestorepath"
    rm -rf "/var/lib/docker/volumes/$myodoovol/_data/sessions/"
    if [ -d "$filestorepath$mydb" ]
    then
        rm -rf "$filestorepath$mydb"
    else
        mkdir -p "$filestorepath"
    fi
    # Restore Filesystem
    if [ "$mykind" == "1" ]
    then
        mv "$mybackuppath/filestore" "$mybackuppath/$mydb"
        cp -r "$mybackuppath/$mydb" $filestorepath
    else
        mv "$mybackuppath/$myorgdb" "$mybackuppath/$mydb"
        cp -r "$mybackuppath/$mydb" $filestorepath
    fi
    # Delete dump.sql
    if [ -f "$mybackuppath/dump.sql" ]
    then
        echo "rm $mybackuppath/dump.sql"
        rm "$mybackuppath/dump.sql"
    fi
    # Delete Manifest if exists
    if [ -f "$mybackuppath/manifest.json" ]
    then
        rm "$mybackuppath/manifest.json"
    fi
    if [ "$mykind" == "1" ]
    then
        rm -rf "$mybackuppath/$mydb"
    else
        rm -rf "$mybackuppath"
    fi
    if [ "$myrunsql" == "" ]
    then
        echo "Do you want to sql statements in $mydb [v10/v12/v13/v14/v15/v16]:"
        read myrunsql
    fi
    echo "Starting Docker Container "$myodoocontainer 
    docker start $myodoocontainer
    sleep 3
    cd $HOME
    if [ "$myrunsql" == "v10" ] || [ "$myrunsql" == "v12" ] || [ "$myrunsql" == "v13" || [ "$myrunsql" == "v14" || [ "$myrunsql" == "v15" || [ "$myrunsql" == "v16" ]
    then
        echo "UPDATE ir_cron SET active = FALSE;"
        docker exec -i $mydbcontainer env PGPASSWORD=$mypgpassword psql -d $mydb -U $mydbuser -h $mydbserver -c $'UPDATE ir_cron SET active = FALSE;'
        echo "DELETE FROM ir_mail_server;"
        docker exec -i $mydbcontainer env PGPASSWORD=$mypgpassword psql -d $mydb -U $mydbuser -h $mydbserver -c $'DELETE FROM ir_mail_server;'
        echo "DELETE FROM fetchmail_server;"
        docker exec -i $mydbcontainer env PGPASSWORD=$mypgpassword psql -d $mydb -U $mydbuser -h $mydbserver -c $'DELETE FROM fetchmail_server;'
        if [ "$myrunsql" == "v10" ]
        then
            echo "DELETE FROM ir_values where model='eq.cloud.settings';"
            docker exec -i $mydbcontainer env PGPASSWORD=$mypgpassword psql -d $mydb -U $mydbuser -h $mydbserver -c "DELETE FROM ir_values where model='eq.cloud.settings';"
            echo "DELETE FROM eq_cloud_settings;"
            docker exec -i $mydbcontainer env PGPASSWORD=$mypgpassword psql -d $mydb -U $mydbuser -h $mydbserver -c $'DELETE FROM eq_cloud_settings;'
            echo "UPDATE res_users SET eq_office_username = NULL;"
            docker exec -i $mydbcontainer env PGPASSWORD=$mypgpassword psql -d $mydb -U $mydbuser -h $mydbserver -c $'UPDATE res_users SET eq_office_username = NULL;'
            echo "UPDATE res_users SET eq_office_password = NULL;"
            docker exec -i $mydbcontainer env PGPASSWORD=$mypgpassword psql -d $mydb -U $mydbuser -h $mydbserver -c $'UPDATE res_users SET eq_office_password = NULL;'
        elif [ "$myrunsql" == "v12" ]
        then
            echo "update res_config_settings set eq_ignore_ssl = false, eq_cloud_url = null, eq_cloud_username = null, eq_cloud_password = null, eq_is_log_attachment_enabled = false, eq_is_log_enabled = false, eq_is_cloud_connector_enabled = false, eq_is_delete_allowed = false;"
            docker exec -i $mydbcontainer env PGPASSWORD=$mypgpassword psql -d $mydb -U $mydbuser -h $mydbserver -c $'update res_config_settings set eq_ignore_ssl = false, eq_cloud_url = NULL, eq_cloud_username = NULL, eq_cloud_password = NULL, eq_is_log_attachment_enabled = false, eq_is_log_enabled = false, eq_is_cloud_connector_enabled = false, eq_is_delete_allowed = false;'
            echo "delete from ir_config_parameter where key like 'eq_cloud_base%' or key like 'eq_cloud_nextcloud%';"
            docker exec -i $mydbcontainer env PGPASSWORD=$mypgpassword psql -d $mydb -U $mydbuser -h $mydbserver -c $"delete from ir_config_parameter where key like 'eq_cloud_base%' or key like 'eq_cloud_nextcloud%';"
            echo "UPDATE res_users SET eq_client_id = NULL;"
            docker exec -i $mydbcontainer env PGPASSWORD=$mypgpassword psql -d $mydb -U $mydbuser -h $mydbserver -c $'UPDATE res_users set eq_client_id = NULL;'
            echo "UPDATE res_users SET  eq_client_secret = NULL;"
            docker exec -i $mydbcontainer env PGPASSWORD=$mypgpassword psql -d $mydb -U $mydbuser -h $mydbserver -c $'UPDATE res_users SET eq_client_secret = NULL;'
        elif [ "$myrunsql" == "v13" || [ "$myrunsql" == "v14" || [ "$myrunsql" == "v15" || [ "$myrunsql" == "v16" ]
        then
            echo "update res_config_settings set eq_ignore_ssl = false, eq_cloud_url = null, eq_cloud_username = null, eq_cloud_password = null, eq_is_log_attachment_enabled = false, eq_is_log_enabled = false, eq_is_cloud_connector_enabled = false, eq_is_delete_allowed = false;"
            docker exec -i $mydbcontainer env PGPASSWORD=$mypgpassword psql -d $mydb -U $mydbuser -h $mydbserver -c $'update res_config_settings set eq_ignore_ssl = false, eq_cloud_url = NULL, eq_cloud_username = NULL, eq_cloud_password = NULL, eq_is_log_attachment_enabled = false, eq_is_log_enabled = false, eq_is_cloud_connector_enabled = false, eq_is_delete_allowed = false;'
            echo "delete from ir_config_parameter where key like 'eq_cloud_base%' or key like 'eq_cloud_nextcloud%';"
            docker exec -i $mydbcontainer env PGPASSWORD=$mypgpassword psql -d $mydb -U $mydbuser -h $mydbserver -c $"delete from ir_config_parameter where key like 'eq_cloud_base%' or key like 'eq_cloud_nextcloud%';"
            echo "UPDATE res_users SET eq_client_id = NULL;"
            docker exec -i $mydbcontainer env PGPASSWORD=$mypgpassword psql -d $mydb -U $mydbuser -h $mydbserver -c $'UPDATE res_users set eq_client_id = NULL;'
            echo "UPDATE res_users SET  eq_client_secret = NULL;"
            docker exec -i $mydbcontainer env PGPASSWORD=$mypgpassword psql -d $mydb -U $mydbuser -h $mydbserver -c $'UPDATE res_users SET eq_client_secret = NULL;'
            echo "UPDATE res_users SET  eq_tenant_id = NULL;"
            docker exec -i $mydbcontainer env PGPASSWORD=$mypgpassword psql -d $mydb -U $mydbuser -h $mydbserver -c $'UPDATE res_users SET eq_tenant_id = NULL;'
        fi
        echo "UPDATE eq_es_config SET eq_web_search_es_url = NULL;"
        docker exec -i $mydbcontainer env PGPASSWORD=$mypgpassword psql -d $mydb -U $mydbuser -h $mydbserver -c $'UPDATE eq_es_config SET eq_web_search_es_url = NULL;'
        echo "DELETE FROM res_company_ldap;"
        docker exec -i $mydbcontainer env PGPASSWORD=$mypgpassword psql -d $mydb -U $mydbuser -h $mydbserver -c $'DELETE FROM res_company_ldap;'
        echo "SQL statement are done."
        echo "****************************************************************"
        echo "Don't worry about error like"
        echo "ERROR:  relation res_company_ldap does not exist"
        echo "LINE 1: DELETE FROM res_company_ldap;"
        echo "****************************************************************"
        echo "Only if datamodel are not exists! ;)"
    fi
    echo "Restore is done."
  else
      echo "No restore."
fi # end

cd $HOME
echo "Finished!"