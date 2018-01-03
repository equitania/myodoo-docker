## docker
docker build -t myodoo/elasticsearch-kibana:6.1.1 .

## Push to Docker
docker push myodoo/elasticsearch-kibana:6.1.1

## Run
docker run -d --restart=always -p 9200:9200 -p 5601:5601 --name="es-myodoo" myodoo/elasticsearch-kibana:6.1.1
 
## Test
docker run -it --rm -p 9200:9200 -p 5601:5601 --name="es-myodoo" myodoo/elasticsearch-kibana:6.1.1
 
## bash Zugriff
docker exec -ti "es-myodoo" env TERM=xterm bash -l
