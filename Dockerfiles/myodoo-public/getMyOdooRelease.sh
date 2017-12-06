#!/bin/bash
# Hole Ihre aktuelle Release vom Server
myrelease=$(curl -k https://v8.myodoo.de/get_release_info/myodoopublic)
echo $myrelease
curl -k -o $myrelease https://release.myodoo.de/conf/$myrelease
now=$(date +"%Y-%m-%d_%H-%M-%S")
filename="myodoo.$now.release"
mv myodoo.release $filename
mv $myrelease myodoo.release
