# For build of the docker image
# For Odoo 10 powered by MyOdoo.de
# Version 2.2.3
# Date 30.06.2019
docker build -t myodoo/prepare-v10:2.2.3 .
docker push myodoo/prepare-v10:2.2.3

#This is only a prepare script for the release images of myodoo.
