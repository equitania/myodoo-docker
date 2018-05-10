# For build of the docker image
# For Odoo 10 powered by MyOdoo.de
# Version 2.0.9
# Date 10.05.2018
docker build -t myodoo/prepare-v10:2.0.9 .
docker push myodoo/prepare-v10:2.0.9

#This is only a prepare script for the release images of myodoo.
