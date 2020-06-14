# For build of the docker image
# For Odoo 13 powered by MyOdoo.de
# Version 1.0.6
# Date 10.06.2020
docker build -t myodoo/prepare-v13:1.0.6 .
docker push myodoo/prepare-v13:1.0.6

#This is only a prepare script for the release images of myodoo.
