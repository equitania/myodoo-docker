# For build of the docker image
# For Odoo 13 powered by MyOdoo.de
# Version 23.09.01
# Date 21.09.2023  

   
https://hub.docker.com/_/python  
`docker pull python:3.8.17-slim-buster`  
`docker build -t myodoo/prepare-v13:tag .`  
`docker push myodoo/prepare-v13:teag`  
  
#This is only a prepare script for the release images of myodoo.
