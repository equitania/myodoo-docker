# For build of the docker image
# For Odoo 8 powered by MyOdoo.de
# Version 1.0.17
# Date 10.05.2018
docker build -t myodoo/prepare-v8:1.0.17 .
docker push myodoo/prepare-v8:1.0.17

#This is only a prepare script for the release images of myodoo.
