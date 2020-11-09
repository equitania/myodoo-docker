# For build of the docker image
# For Odoo 13 powered by MyOdoo.de
# Version 2.0.1
# Date 28.10.2020
docker build -t myodoo/prepare-v13:2.0.1 .
docker push myodoo/prepare-v13:2.0.1

#This is only a prepare script for the release images of myodoo.
