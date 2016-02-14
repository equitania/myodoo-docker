#!/bin/bash

docker ps

echo "\$# = $#"
echo "\$0 = $0"
echo "\$1 = $1"

if [ "$1" == "start" ] || [ "$1" == "stop" ] || [ "$1" == "restart" ]; then
  # Datenbank Container
  docker $1 db-containername
  ## MyOdoo Container
  docker $1 myodoo-containername
fi

docker ps

exit 0
