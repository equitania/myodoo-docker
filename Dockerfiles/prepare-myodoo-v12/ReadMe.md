# For build of the docker image
# For Odoo 12 powered by MyOdoo.de
# Version 1.4.5
# Date 10.06.2020
docker build -t myodoo/prepare-v12:1.4.5 .
docker push myodoo/prepare-v12:1.4.5

#This is only a prepare script for the release images of myodoo.
