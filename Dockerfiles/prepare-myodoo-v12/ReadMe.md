# For build of the docker image
# For Odoo 12 powered by MyOdoo.de
# Version 1.5.0
# Date 22.09.2020
docker build -t myodoo/prepare-v12:1.5.0 .
docker push myodoo/prepare-v12:1.5.0

#This is only a prepare script for the release images of myodoo.
