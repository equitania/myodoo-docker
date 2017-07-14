## docker
docker build -t myodoo/elasticsearch-kibana:5.5.0 .

## Push to Docker
docker push myodoo/elasticsearch-kibana:5.5.0

## Run
docker run -d --restart=always -p 9200:9200 -p 5601:5601 --name="elasticsearch-kibana-myodoo" myodoo/elasticsearch-kibana:5.5.0
 
## Test
docker run -it --rm -p 9200:9200 -p 5601:5601 --name="elasticsearch-kibana-myodoo" myodoo/elasticsearch-kibana
 
## bash Zugriff
docker exec -ti "elasticsearch-kibana-myodoo" env TERM=xterm bash -l
