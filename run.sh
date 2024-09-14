#!/usr/bin/bash

set -e

if [ "$EUID" -eq 0 ]
  then echo "$0 Can't be run as root!"
  exit 1
fi

sudo docker run -it -p 8000:8000 smarthome
