# For build of the docker image
# For Odoo 10 powered by MyOdoo.de
# Version 2.2.2
# Date 29.04.2019
docker build -t myodoo/prepare-v10:2.2.2 .
docker push myodoo/prepare-v10:2.2.2

#This is only a prepare script for the release images of myodoo.
