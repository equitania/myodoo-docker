## Version 6.1.3
## Date 09.02.2018

## docker
docker build -t myodoo/elasticsearch-kibana:6.1.3 .

## Push to Docker
docker push myodoo/elasticsearch-kibana:6.1.3

## Run
docker run -d --restart=always -p 9200:9200 -p 5601:5601 --name="es-myodoo" myodoo/elasticsearch-kibana:6.1.3
 
## Test
docker run -it --rm -p 9200:9200 -p 5601:5601 --name="es-myodoo" myodoo/elasticsearch-kibana:6.1.3
 
## bash Zugriff
docker exec -ti "es-myodoo" env TERM=xterm bash -l
