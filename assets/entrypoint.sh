#!/usr/bin/bash

set -eEuo pipefail

__error_trapper() {
  local parent_lineno="$1"
  local code="$2"
  local commands="$3"
  echo "Error: exit status: $code, at file $0 on or near line $parent_lineno: $commands"
}
trap '__error_trapper "${LINENO}/${BASH_LINENO}" "$?" "$BASH_COMMAND"' ERR


# Not sure if there is need cron tab job to be run
# without this cron jobs won't work (crontab file is set by install.sh)
# sudo cron

python3 /home/ubuntu/smartHomeDjango/manage.py relays_periodic_update >> /home/ubuntu/logs/relays_periodic_update_crontab.log 2>&1

echo "*********************************************"
echo "*                                           *"
echo "*   Welcome to SmartHomeDjango container!   *"
echo "*                                           *"
echo "*********************************************"

bash
