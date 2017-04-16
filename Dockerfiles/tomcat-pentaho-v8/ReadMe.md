## For build of the docker image
docker build -t myodoo/tomcat-pentaho-v8:8.0.43 .

docker push myodoo/tomcat-pentaho-v8:8.0.43

## To run the container
docker run -d -p 8080:8080 --restart=always --name "tomcat-pentaho" -e TOMCAT_PASS="mypassword" myodoo/tomcat-pentaho-v8:8.0.43

## Parameter in your Odoo System:
pentaho.server.url = http://IP_FROM_DOCKER_HOST_FOR_TOMCAT_PENTAHO:8080/pentaho-odoo/

pentaho.openerp.xml.interface = IP_FROM_DOCKER_HOST_FOR_ODOO

pentaho.openerp.xml.port = PORT_ODOO_DOCKER_CONTAINER f.e. 8069

## bash access
docker exec -ti "tomcat-pentaho"  env TERM=xterm bash -l

## Tags
Tag number = Tomcat version number