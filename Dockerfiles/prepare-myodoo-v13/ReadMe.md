# For build of the docker image
# For Odoo 13 powered by MyOdoo.de
# Version 2.0.9
# Date 11.03.2021
docker pull python:3.8.8-slim-buster
docker build -t myodoo/prepare-v13:2.0.9 .

#This is only a prepare script for the release images of myodoo.
