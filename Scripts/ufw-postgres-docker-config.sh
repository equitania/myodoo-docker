#!/bin/bash
################################################################################
# Rather than run postgres in its own container, we want to run it on
# the (Ubuntu) host and allow:
#
#    + peer connections on the host
#    + local md5 connections from any docker container
#
# THIS IS COPY/PASTED FROM COMMAND LINE INPUT AND IS UNTESTED AS A SINGLE SCRIPT
################################################################################

# Determine the docker bridge IP address (assumed to be docker0)
bridge_ip=$(ifconfig docker0 | grep "inet addr:" | awk '{print $2}' | sed "s/.*://")

# subnet for container interfaces
docker_subnet="172.17.1.0/24"

# update postgresql.conf to listen only on the bridge interface
sed -i.orig "s/^[#]\?listen_addresses .*/listen_addresses = '${bridge_ip}'/g" /etc/postgresql/9.6/main/postgresql.conf

# update pg_hba.conf to allow connections from the subnet
echo "host    all             all             ${docker_subnet}            md5" >> /etc/postgresql/9.6/main/pg_hba.conf

# update ufw firewall rules (postgres assumed to be runing on port 5432)
ufw allow in from ${docker_subnet} to ${bridge_ip} port 5432
ufw allow ssh
ufw allow http
ufw allow https

echo "Restart of postgres and ufw services is now required"