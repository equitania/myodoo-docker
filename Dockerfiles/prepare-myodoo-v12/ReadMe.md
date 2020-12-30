# For build of the docker image
# For Odoo 12 powered by MyOdoo.de
# Version 2.0.3
# Date 29.12.2020
docker pull python:3.8.7-slim-buster
docker build -t myodoo/prepare-v12:2.0.3 .
docker push myodoo/prepare-v12:2.0.3

#This is only a prepare script for the release images of myodoo.
