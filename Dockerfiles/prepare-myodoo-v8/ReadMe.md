# For build of the docker image
# For Odoo 8 powered by MyOdoo.de
# Version 1.0.18
# Date 28.04.2019
docker build -t myodoo/prepare-v8:1.0.18 .
docker push myodoo/prepare-v8:1.0.18

#This is only a prepare script for the release images of myodoo.
