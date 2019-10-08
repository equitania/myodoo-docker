# For build of the docker image
# For Odoo 11 powered by MyOdoo.de
# Version 1.0.5
# Date 27.05.2018
docker build -t myodoo/prepare-v11:1.0.5 .
docker push myodoo/prepare-v11:1.0.5

#This is only a prepare script for the release images of myodoo.
