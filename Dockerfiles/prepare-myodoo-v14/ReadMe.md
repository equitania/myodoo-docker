# For build of the docker image
# For Odoo 14 powered by MyOdoo.de
# Version 1.0.1
# Date 29.01.2021
docker pull python:3.8.6-slim-buster
docker build -t myodoo/prepare-v14:1.0.2 .
docker push myodoo/prepare-v14:1.0.2

#This is only a prepare script for the release images of myodoo.
