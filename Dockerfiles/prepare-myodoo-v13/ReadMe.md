# For build of the docker image
# For Odoo 13 powered by MyOdoo.de
# Version 22.08.01
# Date 22.08.2022  

   
`docker pull python:3.8.13-slim-buster`     
`docker build -t myodoo/prepare-v13:22.08.01 .`      
`docker push myodoo/prepare-v13:22.08.01`  
  
#This is only a prepare script for the release images of myodoo.
