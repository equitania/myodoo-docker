# For build of the docker image
# For Odoo 12 powered by MyOdoo.de
# Version 1.0.1
# Date 28.04.2019
docker build -t myodoo/prepare-v12:1.0.1 .
docker push myodoo/prepare-v12:1.0.1

#This is only a prepare script for the release images of myodoo.
