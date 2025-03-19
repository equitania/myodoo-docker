# For build of the docker image
# For Odoo 18 powered by ownERP.com
Version: 25.02.25-3.12.9
Python Version: 3.12.9
Last Update: 2025-02-25

```shell
docker pull python:3.12.2-bookworm
docker build -t myodoo/prepare-v18:Tag .
docker push myodoo/prepare-v18:Tag
```

#This is only a prepare script for the release images of myodoo.
