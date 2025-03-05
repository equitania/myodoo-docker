# How to start

## Docker Build

### Public
``` shell
./check_dockerimage_myodoo.py
docker build -t myodoo/myodoo-18-public:latest .
# optional
docker push myodoo/myodoo-18-public:latest
```

### Get actual release file
``` shell
./check_dockerimage_myodoo.py
..
dockerimage: myodoo/prepare-v18:latest
sed -i '1s|.*|FROM myodoo/prepare-v18:latest |' Dockerfile
Dockerfile image changed
Cleanup and finished!

..

╭─root@rm ~/docker-builds/v18-myodoo
╰─# ll release.file
-rw-r--r--. 1 root root 16843 Dec 24 10:15 release.file
```

### Docker Build
``` shell
docker build -t myodoo/v18-live .
```


For more infomations [ownERP.com](https://www.ownerp.com)
[Technical source](https://github.com/equitania/myodoo-docker)