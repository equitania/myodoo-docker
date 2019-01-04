# For build of the docker image
# For Odoo 10 powered by MyOdoo.de
# Version 2.1.5
# Date 17.12.2018
docker build -t myodoo/prepare-v10:2.1.5 .
docker push myodoo/prepare-v10:2.1.5

#This is only a prepare script for the release images of myodoo.
