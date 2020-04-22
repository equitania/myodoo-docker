# For build of the docker image
# For Odoo 10 powered by MyOdoo.de
# Version 2.2.9
# Date 22.04.2020
docker build -t myodoo/prepare-v10:2.2.9 .
docker push myodoo/prepare-v10:2.2.9

#This is only a prepare script for the release images of myodoo.