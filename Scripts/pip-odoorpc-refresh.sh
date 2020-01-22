#!/bin/bash
# Refresh python libs and other important system things
# 20.01.2020
# 1.0.1

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

echo "CTOP docker shell tool"
sudo wget https://github.com/bcicen/ctop/releases/download/v0.7.3/ctop-0.7.3-linux-amd64 -O /usr/local/bin/ctop
sudo chmod +x /usr/local/bin/ctop

exit 0

