# How to start

## Docker Build

### Public
``` shell
./check_dockerimage_myodoo.py
docker build -t myodoo/myodoo-13-public:210206 .
# optional
docker push myodoo/myodoo-13-public:210206
```

### Get actual release file
``` shell
./check_dockerimage_myodoo.py
..
dockerimage: myodoo/prepare-v13:2.0.8
sed -i '1s|.*|FROM myodoo/prepare-v13:2.0.8|' Dockerfile
Dockerfile image changed
Cleanup and finished!

..

╭─root@rm ~/docker-builds/v13-myodoo 
╰─# ll release.file
-rw-r--r--. 1 root root 16843 Dec 24 10:15 release.file
``` 

### Docker Build
``` shell
docker build -t myodoo/live .
```

### Docker compose up
``` shell
docker-compose up
```
