# For build of the docker image
# For Odoo 12 powered by MyOdoo.de
# Version 2.0.0
# Date 09.11.2020
docker build -t myodoo/prepare-v12:2.0.0 .
docker push myodoo/prepare-v12:2.0.0

#This is only a prepare script for the release images of myodoo.
