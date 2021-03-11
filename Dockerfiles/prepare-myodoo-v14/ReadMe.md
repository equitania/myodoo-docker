# For build of the docker image
# For Odoo 14 powered by MyOdoo.de
# Version 1.0.4
# Date 11.03.2021
docker pull python:3.8.8-slim-buster
docker build -t myodoo/prepare-v14:1.0.4 .

#This is only a prepare script for the release images of myodoo.
