# How to start

## Docker Build

### Public
``` shell
./check_dockerimage_myodoo.py
docker build -t myodoo/myodoo-14-public:latest .
# optional
docker push myodoo/myodoo-14-public:latest
```

### Get actual release file
``` shell
./check_dockerimage_myodoo.py
..
dockerimage: myodoo/prepare-v14:1.0.8
sed -i '1s|.*|FROM myodoo/prepare-v14:1.0.8|' Dockerfile
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

For more infomations [MyOdoo.de](https://www.myodoo.de) or [ownERP.com](https://www.ownerp.com)
[Technical source](https://github.com/equitania/myodoo-docker)