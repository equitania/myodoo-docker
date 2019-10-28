#!/bin/bash
# Erneuert die von Let's encrypt erstellten Zertifikate und nginx logs älter als 14 Tage löschen
# Einstellung für crontab -e
# Renew certificates every wednesday at 0:00 h
# 0 0 * * 3 /root/ssl-renew.sh >/dev/null 2>&1

echo "Refresh python 2"
sudo python2 -m pip install pip --upgrade
sudo python2 -m pip install setuptools --upgrade
sudo python2 -m pip install wheel --upgrade
sudo python2 -m pip install odoorpc --upgrade

echo "Refresh python 3"
sudo python3 -m pip install pip --upgrade
sudo python3 -m pip install setuptools --upgrade
sudo python3 -m pip install wheel --upgrade
sudo python3 -m pip install odoorpc --upgrade

echo "Refresh pypy 3"
sudo pypy3 -m pip install pip --upgrade
sudo pypy3 -m pip install setuptools --upgrade
sudo pypy3 -m pip install wheel --upgrade
sudo pypy3 -m pip install odoorpc --upgrade

exit 0

