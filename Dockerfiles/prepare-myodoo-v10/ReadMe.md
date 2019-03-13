# For build of the docker image
# For Odoo 10 powered by MyOdoo.de
# Version 2.2.0
# Date 13.03.2019
docker build -t myodoo/prepare-v10:2.2.0 .
docker push myodoo/prepare-v10:2.2.0

#This is only a prepare script for the release images of myodoo.
