# How to start

## Docker Build

### Get actual release file
``` shell
./check_dockerimage_myodoo.py
..
dockerimage: myodoo/prepare-v13:2.0.5
sed -i '1s|.*|FROM myodoo/prepare-v13:2.0.5|' Dockerfile
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
