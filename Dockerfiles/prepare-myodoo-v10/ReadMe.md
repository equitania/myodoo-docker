# For build of the docker image
# For Odoo 10 powered by MyOdoo.de
# Version 2.3.0
# Date 14.07.2020
docker build -t myodoo/prepare-v10:2.3.0 .
docker push myodoo/prepare-v10:2.3.0

#This is only a prepare script for the release images of myodoo.