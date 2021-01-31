# For build of the docker image
# For Odoo 10 powered by MyOdoo.de
# Version 2.3.2
# Date 29.01.2021
docker build -t myodoo/prepare-v10:2.3.2 .
docker push myodoo/prepare-v10:2.3.2

#This is only a prepare script for the release images of myodoo.