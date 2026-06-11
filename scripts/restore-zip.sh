#!/bin/bash
# Version 2.0.0 - Stand 11.06.2026
# Mit diesem Skript wird ein Restore einer Odoo Datenbank auf Basis von Docker durchgeführt
# Das FileStore wird in den Odoo Container und die Datenbank in den PostgreSQL Container eingespielt
# With this script you can restore a Odoo db in postgresql on base of Docker
# The filestore will restore in the Odoo container and the db in the posgres container
#
# v2.0.0: Supports all container2backup.py formats with automatic detection:
#   .zip | .7z | .7z.gpg (GPG-encrypted, prompts for passphrase) | .tar.gz | .tar.zst
###############################################################################################################################
# ./restore-zip.sh
#  -backup_kind(../web/database/manager (1) or automatic backups scripts (2))
#  -runsql (v10,v12,v13,14,v15,v16)
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

set -euo pipefail

mybackuppath="${mybasepath:-}/opt/backups/docker/"
mybackuproot="$mybackuppath"   # immutable reference for the cleanup guard

mykind="${1:-}"
myrunsql="${2:-}"
myorgdb="${3:-}"
mydb="${4:-}"
mybackupzip="${5:-}"
myodoocontainer="${6:-}"
myodoovol="${7:-}"
mydbcontainer="${8:-}"
mypgpassword="${9:-}"

mydbuser="ownerp"         # user for postgresql
mydbserver="$mydbcontainer" # mostly the same like live-db or test-db

# Input validation: only allow safe characters in names
validate_name() {
    local value="$1"
    local label="$2"
    if [[ -n "$value" ]] && ! [[ "$value" =~ ^[a-zA-Z0-9._-]+$ ]]; then
        echo "ERROR: Invalid characters in $label: $value"
        echo "Only alphanumeric characters, dots, underscores and hyphens are allowed."
        exit 1
    fi
}

# Required values: an empty name would later expand rm -rf targets to the
# backup root - refuse to continue instead.
require_value() {
    local value="$1"
    local label="$2"
    if [ -z "$value" ]; then
        echo "ERROR: $label must not be empty."
        exit 1
    fi
}

echo "Your backup path is: $mybackuppath"
echo "So your zip file should store there!"
echo "DB kind ../web/database/manager (1) or automatic backups scripts (2): $mykind"
echo "DB original name: $myorgdb"
echo "DB name: $mydb"
echo "DB Zipfile: $mybackupzip"
echo "Name of Odoo Container: $myodoocontainer"
echo "Name of Odoo Volume: $myodoovol"
echo "Name of Postgres Container: $mydbcontainer"
echo "Name of Database Server: $mydbserver"
echo "Name of Database User: $mydbuser"
echo "Run SQL for Odoo version: $myrunsql"

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

# Validate all inputs after collection
validate_name "$mydb" "database name"
validate_name "$myorgdb" "original database name"
validate_name "$myodoocontainer" "Odoo container"
validate_name "$myodoovol" "Odoo volume"
validate_name "$mydbcontainer" "Postgres container"
validate_name "$mydbuser" "database user"
validate_name "$mydbserver" "database server"

require_value "$mydb" "database name"
require_value "$mybackupzip" "backup file"
require_value "$myodoocontainer" "Odoo container"
require_value "$myodoovol" "Odoo volume"
require_value "$mydbcontainer" "Postgres container"
if [ "$mykind" == "2" ]; then
    require_value "$myorgdb" "original database name"
fi

mystart=""
if [ "${mystart:-}" == "" ]
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
    docker stop "$myodoocontainer"
fi


if [ "$mydb" != "" ]
then
    echo "Drop old database..."
    sleep 3
    docker exec -i "$mydbcontainer" psql -U "$mydbuser" -d postgres -c "DROP DATABASE IF EXISTS \"$mydb\";"
    echo "Drop is done."
    echo "Extracting $mybackuppath/$mybackupzip ..."
    cd "$mybackuppath"
    myarchive="$mybackuppath/$mybackupzip"
    if [ ! -f "$myarchive" ]; then
        echo "ERROR: backup file not found: $myarchive"
        exit 1
    fi
    # Format detection: handles every format container2backup.py produces
    case "$mybackupzip" in
        *.7z.gpg)
            command -v gpg >/dev/null 2>&1 || { echo "ERROR: gpg not installed (apt-get install gnupg)"; exit 1; }
            command -v 7zz >/dev/null 2>&1 || { echo "ERROR: 7zz not installed"; exit 1; }
            mydecrypted="${myarchive%.gpg}"
            echo "GPG-encrypted backup - decrypting (passphrase prompt follows)..."
            gpg --output "$mydecrypted" --decrypt "$myarchive"
            7zz x -y "$mydecrypted"
            rm -f "$mydecrypted"
            ;;
        *.7z)
            command -v 7zz >/dev/null 2>&1 || { echo "ERROR: 7zz not installed"; exit 1; }
            # 7zz prompts for the password itself if the archive is encrypted
            7zz x -y "$myarchive"
            ;;
        *.tar.gz|*.tgz)
            tar -xzf "$myarchive"
            ;;
        *.tar.zst)
            command -v zstd >/dev/null 2>&1 || { echo "ERROR: zstd not installed (apt-get install zstd)"; exit 1; }
            tar --use-compress-program=unzstd -xf "$myarchive"
            ;;
        *.zip)
            unzip -o "$myarchive"
            ;;
        *)
            echo "ERROR: Unsupported backup format: $mybackupzip"
            echo "Supported: .zip, .7z, .7z.gpg, .tar.gz, .tar.zst"
            exit 1
            ;;
    esac
    mybackup="dump.sql"
    if [ -f "$mybackup" ]
    then
	   echo "$mybackup found."
	   isDocker=""
    else
	   echo "$mybackup based on Docker. "
	   isDocker="Y"
	   cd "$myorgdb/$myorgdb"
	   mybackuppath="$mybackuppath/$myorgdb"
	   echo "$mybackuppath"
    fi
    echo "Create DB $mydb with $mybackup file.."
    docker exec -i "$mydbcontainer" psql -U "$mydbuser" -d postgres -c "CREATE DATABASE \"$mydb\" OWNER \"$mydbuser\" TEMPLATE template0;"
    echo "Restore DB $mydb"
    sleep 3
    cat "$mybackuppath/$mybackup" | docker exec -i "$mydbcontainer" psql -U "$mydbuser" -d "$mydb"
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
    # Supports both Odoo-native format (filestore/) and legacy script format (db_name/)
    if [ -d "$mybackuppath/filestore" ]
    then
        # Odoo-native format or new container2backup format: directory is named "filestore"
        mv "$mybackuppath/filestore" "$mybackuppath/$mydb"
        cp -r "$mybackuppath/$mydb" "$filestorepath"
    elif [ "$mykind" == "1" ]
    then
        mv "$mybackuppath/filestore" "$mybackuppath/$mydb"
        cp -r "$mybackuppath/$mydb" "$filestorepath"
    else
        # Legacy container2backup format: directory is named after original database
        mv "$mybackuppath/$myorgdb" "$mybackuppath/$mydb"
        cp -r "$mybackuppath/$mydb" "$filestorepath"
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
        # Guard: only remove the extracted subdirectory, never the backup
        # root itself (mybackuppath is only reassigned in the isDocker branch)
        if [ "$mybackuppath" != "$mybackuproot" ]; then
            rm -rf "$mybackuppath"
        else
            echo "Skipping cleanup: extraction left files directly in $mybackuproot - remove them manually if needed."
            rm -rf "${mybackuproot:?}/${mydb:?}"
        fi
    fi
    if [ "$myrunsql" == "" ]
    then
        echo "Do you want to sql statements in $mydb [v10/v12/v13/v14/v15/v16]:"
        read myrunsql
    fi
    echo "Starting Docker Container $myodoocontainer"
    docker start "$myodoocontainer"
    sleep 3
    cd "$HOME"

    # Helper function to execute SQL via docker exec
    # Password is forwarded from the client environment (-e PGPASSWORD without
    # value) so it never appears in the docker/psql argv (visible via ps).
    run_sql() {
        local sql="$1"
        echo "$sql"
        PGPASSWORD="$mypgpassword" docker exec -i -e PGPASSWORD "$mydbcontainer" psql -d "$mydb" -U "$mydbuser" -h "$mydbserver" -c "$sql"
    }

    if [[ "$myrunsql" == "v10" ]] || [[ "$myrunsql" == "v12" ]] || [[ "$myrunsql" == "v13" ]] || [[ "$myrunsql" == "v14" ]] || [[ "$myrunsql" == "v15" ]] || [[ "$myrunsql" == "v16" ]]
    then
        run_sql 'UPDATE ir_cron SET active = FALSE;'
        run_sql 'DELETE FROM ir_mail_server;'
        run_sql 'DELETE FROM fetchmail_server;'
        if [ "$myrunsql" == "v10" ]
        then
            run_sql "DELETE FROM ir_values where model='eq.cloud.settings';"
            run_sql 'DELETE FROM eq_cloud_settings;'
            run_sql 'UPDATE res_users SET eq_office_username = NULL;'
            run_sql 'UPDATE res_users SET eq_office_password = NULL;'
        elif [ "$myrunsql" == "v12" ]
        then
            run_sql 'UPDATE res_config_settings SET eq_ignore_ssl = false, eq_cloud_url = NULL, eq_cloud_username = NULL, eq_cloud_password = NULL, eq_is_log_attachment_enabled = false, eq_is_log_enabled = false, eq_is_cloud_connector_enabled = false, eq_is_delete_allowed = false;'
            run_sql "DELETE FROM ir_config_parameter WHERE key LIKE 'eq_cloud_base%' OR key LIKE 'eq_cloud_nextcloud%';"
            run_sql 'UPDATE res_users SET eq_client_id = NULL;'
            run_sql 'UPDATE res_users SET eq_client_secret = NULL;'
        elif [[ "$myrunsql" == "v13" ]] || [[ "$myrunsql" == "v14" ]] || [[ "$myrunsql" == "v15" ]] || [[ "$myrunsql" == "v16" ]]
        then
            run_sql 'UPDATE res_config_settings SET eq_ignore_ssl = false, eq_cloud_url = NULL, eq_cloud_username = NULL, eq_cloud_password = NULL, eq_is_log_attachment_enabled = false, eq_is_log_enabled = false, eq_is_cloud_connector_enabled = false, eq_is_delete_allowed = false;'
            run_sql "DELETE FROM ir_config_parameter WHERE key LIKE 'eq_cloud_base%' OR key LIKE 'eq_cloud_nextcloud%';"
            run_sql 'UPDATE res_users SET eq_client_id = NULL;'
            run_sql 'UPDATE res_users SET eq_client_secret = NULL;'
            run_sql 'UPDATE res_users SET eq_tenant_id = NULL;'
        fi
        run_sql 'UPDATE eq_es_config SET eq_web_search_es_url = NULL;'
        run_sql 'DELETE FROM res_company_ldap;'
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

cd "$HOME"
echo "Finished!"
