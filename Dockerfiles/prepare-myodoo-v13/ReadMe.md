# For build of the docker image
# For Odoo 13 powered by MyOdoo.de
# Version 2.0.0
# Date 26.10.2020
docker build -t myodoo/prepare-v13:2.0.0 .
docker push myodoo/prepare-v13:2.0.0

#This is only a prepare script for the release images of myodoo.
