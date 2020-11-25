# For build of the docker image
# For Odoo 13 powered by MyOdoo.de
# Version 2.0.5
# Date 25.11.2020
docker pull python:3.8.6-slim-buster
docker build -t myodoo/prepare-v13:2.0.5 .
docker push myodoo/prepare-v13:2.0.5

#This is only a prepare script for the release images of myodoo.
