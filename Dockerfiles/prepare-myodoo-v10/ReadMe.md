# For build of the docker image
# For Odoo 10 powered by MyOdoo.de
# Version 2.1.1
# Date 03.07.2018
docker build -t myodoo/prepare-v10:2.1.1 .
docker push myodoo/prepare-v10:2.1.1

#This is only a prepare script for the release images of myodoo.
