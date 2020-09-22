# For build of the docker image
# For Odoo 8 powered by MyOdoo.de
# Version 1.0.21
# Date 21.09.2020
docker build -t myodoo/prepare-v8:1.0.21 .
docker push myodoo/prepare-v8:1.0.21

#This is only a prepare script for the release images of myodoo.
