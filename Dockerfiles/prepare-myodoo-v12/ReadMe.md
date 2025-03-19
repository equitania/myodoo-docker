# For build of the docker image
# For Odoo 12 powered by ownerp.com
# Version 24.06.01
# Date 01.06.2024
`docker pull python:3.8.17-slim-buster`  
  
`docker build -t myodoo/prepare-v12:tags .`  
  
`docker push myodoo/prepare-v12:tags`  
   
#This is only a prepare script for the release images of myodoo.
