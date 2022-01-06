# Myodoo-Docker
(c) 2016 till now by Equitania Software GmbH

## Vorbereitung

### Beim ersten Start
  
`git clone https://github.com/equitania/myodoo-docker.git`
  
### danach
  
`cp myodoo-docker/getScripts.py /root/`
  
`./getScripts.py`
  
## Skripte
  
Dieses Repository bietet Hilfsskripte und Dockerfiles für den MyOdoo Fork https://www.myodoo.de.  
Wir benutzen es bei unseren täglichen Administrationstätigkeiten mit den Kunden Systemen.  
  
### Bereiche:  
  
1. Dockerfiles
2. Hilfsskripte für Installation, Updates & Backups
  
Weiterführende Informationen finden Sie in unserem WIKI https://equitania.atlassian.net/wiki/spaces/MW/overview 
  
#### Exchange branch
```
cd $HOME && rm -rf myodoo-docker && rm -rf nginx-conf && \
  git clone -b 2022 https://github.com/equitania/myodoo-docker.git && \
  cp myodoo-docker/getScripts.py $HOME && \
  $HOME/getScripts.py && source ~/.zshrc
```
  
  
For more infomations [MyOdoo.de](https://www.myodoo.de) or [ownERP.com](https://www.ownerp.com)  
[Technical source](https://github.com/equitania/myodoo-docker)
