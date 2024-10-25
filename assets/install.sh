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

if $USE_LOCAL; then
  echo "Using local smartHomeDjango repository no need to clone"
  sudo chown -R "$USER":"$USER" smartHomeDjango
  cd smartHomeDjango || exit 1
    if [ -f db.sqlite3 ]; then
      echo "Removing old database"
      rm db.sqlite3
    fi
  cd ..
else
  echo "Cloning smartHomeDjango repository"
  git clone --depth=1 https://github.com/s17kf/smartHomeDjango.git

  cd smartHomeDjango || exit 1
  git apply --allow-empty ../tmp/patch.diff

  cd ..
fi

ln -s smartHomeDjango/manage.py .

cd smartHomeDjango || exit 1

echo "Installing dependencies from requirements.txt"
# Use flag --break-system-packages to be possible to install packages without virtualenv,
# there is no need to use virtualenv inside docker container
pip3 install --break-system-packages -r requirements.txt

echo "Applying patches"
if [ -d ../patches ]; then
  find ../patches -name '*.patch' -exec echo "Applying patch: {}" \; -exec git apply --allow-empty {} \;
fi

echo "Migrating database and loading fixtures"
./manage.py migrate
./manage.py compilemessages
if [ -d ../db_fixtures ]; then
  find ../db_fixtures -name '*.json' | sort | xargs -I{} sh -c 'echo "Loading fixture: {}" && ./manage.py loaddata {}'
fi

echo "Adding host's IP to ALLOWED_HOSTS in settings.py"
# Host's IP is needed here to allow access to the server from other devices in LAN
sed -i -E "s/(ALLOWED_HOSTS = \[)/\1'${HOST_IP}', 'localhost'/g" smartHomeSite/settings.py
