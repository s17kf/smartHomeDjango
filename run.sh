#!/usr/bin/bash

if [ "$EUID" -ne 0 ]
  then echo "$0 has to be run as root!"
  exit 1
fi

docker run -it -p 8000:8000 smarthome
