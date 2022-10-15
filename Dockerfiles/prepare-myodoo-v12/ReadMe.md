# For build of the docker image
# For Odoo 12 powered by MyOdoo.de
# Version 22.08.02
# Date 22.08.2022
`docker pull python:3.8.13-slim-buster`  
  
`docker build -t myodoo/prepare-v12:22.08.02 .`  
  
`docker push myodoo/prepare-v12:22.08.02`  
   
#This is only a prepare script for the release images of myodoo.
