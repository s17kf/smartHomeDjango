#!/usr/bin/bash

set -e

sudo ln -sf /usr/share/zoneinfo/Europe/Warsaw /etc/localtime

cd /home/$USER || exit 1

mkdir logs
crontab tmp/crontab

# Create dummy files to simulate GPIO pins
mkdir gpio
for i in $(seq 1 27); do
  echo "lo" > gpio/"$i"
done
sudo ln -s /home/ubuntu/pinctrl_dummy.py /usr/bin/pinctrl

git clone --depth=1 https://github.com/s17kf/smartHomeWebApp.git

cd smartHomeWebApp || exit 1

cp ../tmp/db.sqlite3 .

# Use flag --break-system-packages to be possible to install packages without virtualenv,
# there is no need to use virtualenv inside docker container
pip3 install --break-system-packages -r requirements.txt

# Host's IP is needed here to allow access to the server from other devices in LAN
sed -i -E "s/(ALLOWED_HOSTS = \[)/\1'${HOST_IP}', 'localhost'/g" smartHomeSite/settings.py
