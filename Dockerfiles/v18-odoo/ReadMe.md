# How to start

On servers, the normal way to build or update this image is `doup`
(`scripts/update_docker_odoo.py`, driven by `~/docker2update.yaml`) — see
[Updates](../../docs/usage/04-updates.md) and
[COMPONENTS.md](../../docs/COMPONENTS.md). It also syncs the release archives
into this folder via `odoo_build_cache.py` before building. The manual steps
below are the fallback for a first build or local testing.

## Docker Build

### Public
``` shell
./check_dockerimage_odoo.py
docker build -t myodoo/myodoo-18-public:latest .
# optional
docker push myodoo/myodoo-18-public:latest
```

### Get actual release file
``` shell
./check_dockerimage_odoo.py
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