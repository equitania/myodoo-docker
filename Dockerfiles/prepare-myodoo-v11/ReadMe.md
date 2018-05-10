# For build of the docker image
# For Odoo 11 powered by MyOdoo.de
# Version 1.0.4
# Date 10.05.2018
docker build -t myodoo/prepare-v11:1.0.4 .
docker push myodoo/prepare-v11:1.0.4

#This is only a prepare script for the release images of myodoo.
