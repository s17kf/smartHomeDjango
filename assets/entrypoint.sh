#!/usr/bin/bash

# Not sure if there is need cron tab job to be run
# without this cron jobs won't work (crontab file is set by install.sh)
# sudo cron

python3 /home/ubuntu/smartHomeWebApp/manage.py relays_periodic_update >> /home/ubuntu/logs/relays_periodic_update_crontab.log 2>&1

bash
