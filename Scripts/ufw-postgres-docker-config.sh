#!/bin/bash
################################################################################
# Rather than run postgres in its own container, we want to run it on
# the (Ubuntu) host and allow:
#
#
# THIS IS COPY/PASTED FROM COMMAND LINE INPUT AND IS UNTESTED AS A SINGLE SCRIPT
################################################################################

# update ufw firewall rules (postgres assumed to be runing on port 5432)
ufw allow in from "172.17.1.0/24" to "127.0.0.1" port 5432
ufw allow ssh
ufw allow http
ufw allow https

echo "Restart of postgres and ufw services is now required"