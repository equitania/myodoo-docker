#!/bin/bash
# Refresh python libs and other important system things
# 20.01.2020
# 1.0.5

echo "pypy3"
FILE="/usr/bin/pypy3"
mkdir -p /root/.local/bin
[ -d "/opt/pypy3.6" ] && sudo rm -rf /opt/pypy3.6
if [ -f "$FILE" ]; then
    sudo rm /usr/bin/pypy3
fi
sudo pypy3 -m ensurepip --user
sudo snap install pypy3 --classic

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
sudo pypy3 -m pip install pip --upgrade --user
sudo pypy3 -m pip install setuptools --upgrade --user
sudo pypy3 -m pip install wheel --upgrade --user
sudo pypy3 -m pip install odoorpc --upgrade --user

echo "CTOP docker shell tool"
sudo wget https://github.com/bcicen/ctop/releases/download/v0.7.3/ctop-0.7.3-linux-amd64 -O /usr/local/bin/ctop
sudo chmod +x /usr/local/bin/ctop

echo "code-server"
wget https://github.com/cdr/code-server/releases/download/2.1698/code-server2.1698-vsc1.41.1-linux-x86_64.tar.gz  
tar xvfz code-server2.1698-vsc1.41.1-linux-x86_64.tar.gz && sudo mv code-server2.1698-vsc1.41.1-linux-x86_64/code-server /bin && rm -rf code-server2.1698-vsc1.41.1-linux-x86_64*

exit 0

