# How to start

## Docker Build

### Public
``` shell
./check_dockerimage_myodoo.py
docker build -t myodoo/myodoo-12-public:210113 .
# optional
docker push myodoo/myodoo-12-public:210113
```

### Get actual release file
``` shell
./check_dockerimage_myodoo.py
..
dockerimage: myodoo/prepare-v12:2.0.3
sed -i '1s|.*|FROM myodoo/prepare-v12:2.0.3|' Dockerfile
Dockerfile image changed
Cleanup and finished!

..

╭─root@rm ~/docker-builds/v13-myodoo 
╰─# ll release.file
-rw-r--r--. 1 root root 24993 Dec 30 10:41 release.file
``` 

### Docker Build
``` shell
docker build -t myodoo/live .
```

### Docker compose up
``` shell
docker-compose up
```
