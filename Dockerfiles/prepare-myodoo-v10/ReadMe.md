# For build of the docker image
# For Odoo 10 powered by MyOdoo.de
# Version 2.1.4
# Date 18.10.2018
docker build -t myodoo/prepare-v10:2.1.4 .
docker push myodoo/prepare-v10:2.1.4

#This is only a prepare script for the release images of myodoo.
