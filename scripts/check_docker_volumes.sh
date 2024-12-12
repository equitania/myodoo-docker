#!/bin/bash
# Version 1.0.0 - Stand 12.12.2024

for vol in $(docker volume ls -q); do
  echo "Volume: $vol"
  docker ps -a --filter volume="$vol" --format "  -> {{.Names}}"
done
