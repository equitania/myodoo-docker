# For build of the docker image
# For Odoo 10 powered by MyOdoo.de
# Version 2.2.7
# Date 02.04.2020
docker build -t myodoo/prepare-v10:2.2.7 .
docker push myodoo/prepare-v10:2.2.7

#This is only a prepare script for the release images of myodoo.