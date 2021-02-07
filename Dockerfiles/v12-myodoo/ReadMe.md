# How to start

## Docker Build

### Public
``` shell
./check_dockerimage_myodoo.py
docker build -t myodoo/myodoo-12-public:210206 .
# optional
docker push myodoo/myodoo-12-public:210206
```

### Get actual release file
``` shell
./check_dockerimage_myodoo.py
..
dockerimage: myodoo/prepare-v12:2.0.5
sed -i '1s|.*|FROM myodoo/prepare-v12:2.0.5|' Dockerfile
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
