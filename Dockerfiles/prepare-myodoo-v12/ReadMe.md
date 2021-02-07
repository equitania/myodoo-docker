# For build of the docker image
# For Odoo 12 powered by MyOdoo.de
# Version 2.0.5
# Date 03.02.2021
docker pull python:3.8.7-slim-buster
docker build -t myodoo/prepare-v12:2.0.5 .
docker push myodoo/prepare-v12:2.0.5

#This is only a prepare script for the release images of myodoo.
