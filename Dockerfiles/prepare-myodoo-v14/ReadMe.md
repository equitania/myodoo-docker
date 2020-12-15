# For build of the docker image
# For Odoo 14 powered by MyOdoo.de
# Version 1.0.1
# Date 02.12.2020
docker pull python:3.8.6-slim-buster
docker build -t myodoo/prepare-v14:1.0.1 .
docker push myodoo/prepare-v14:1.0.1

#This is only a prepare script for the release images of myodoo.
