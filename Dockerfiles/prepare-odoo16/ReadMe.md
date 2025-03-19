# For build of the docker image
# For Odoo 16 powered by ownERP.com
Version: 25.02.24-3.12.2
Python Version: 3.12.2
Last Update: 2025-02-24

```shell
docker pull python:3.12.2-bookworm
docker build -t myodoo/prepare-v16:Tag .
docker push myodoo/prepare-v16:Tag
```

#This is only a prepare script for the release images of myodoo.
