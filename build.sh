#!/usr/bin/bash

# shellcheck disable=SC2164
cd "$(dirname "$0")"

HOST_IP=$(ifconfig wlp0s20f3 | grep -Po "inet (?:[0-9]{1,3}\.){3}[0-9]{1,3}" | \
          sed 's/inet //')
echo "host's IP: ${HOST_IP}"

sudo docker build -t smarthome . --no-cache --build-arg HOST_IP="${HOST_IP}"
