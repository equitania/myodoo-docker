# For build of the docker image
# For Odoo 12 powered by MyOdoo.de
# Version 1.4.1
# Date 17.03.2020
docker build -t myodoo/prepare-v12:1.4.1 .
docker push myodoo/prepare-v12:1.4.1

#This is only a prepare script for the release images of myodoo.
