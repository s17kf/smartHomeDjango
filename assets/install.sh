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

echo "Cloning smartHomeWebApp repository"
git clone --depth=1 https://github.com/s17kf/smartHomeWebApp.git

cd smartHomeWebApp || exit 1

git apply --allow-empty ../tmp/patch.diff

echo "Installing dependencies from requirements.txt"
# Use flag --break-system-packages to be possible to install packages without virtualenv,
# there is no need to use virtualenv inside docker container
pip3 install --break-system-packages -r requirements.txt

echo "Migrating database and loading fixtures"
python3 manage.py migrate
python3 manage.py compilemessages
for fixture in ../db_fixtures/*.json; do
  echo "Loading fixture: $fixture"
  python3 manage.py loaddata "$fixture"
done

echo "Adding host's IP to ALLOWED_HOSTS in settings.py"
# Host's IP is needed here to allow access to the server from other devices in LAN
sed -i -E "s/(ALLOWED_HOSTS = \[)/\1'${HOST_IP}', 'localhost'/g" smartHomeSite/settings.py
