#!/usr/bin/bash

set -eEuo pipefail

__error_trapper() {
  local parent_lineno="$1"
  local code="$2"
  local commands="$3"
  echo "Error: exit status: $code, at file $0 on or near line $parent_lineno: $commands"
}
trap '__error_trapper "${LINENO}/${BASH_LINENO}" "$?" "$BASH_COMMAND"' ERR

BLUE='\033[0;34m'
GREEN='\033[0;32m'
IT_BLUE='\033[3;34m'
NC='\033[0m'

function welcome_print() {
  local border=$GREEN
  cat <<EOF
${border}
*********************************************
*                                           *
*   ${BLUE}Welcome to SmartHomeDjango container!${border}   *
*                                           *
*********************************************

${BLUE}Starting Django server...
${NC}
EOF
}

function server_stopped_print() {
  cat <<EOF

${BLUE}Django server has been stopped.
You still are in the container!
To exit type: ${IT_BLUE}exit$
${NC}
EOF
}

# Not sure if there is need cron tab job to be run
# without this cron jobs won't work (crontab file is set by install.sh)
# sudo cron

python3 /home/ubuntu/smartHomeDjango/manage.py relays_periodic_update >> /home/ubuntu/logs/relays_periodic_update_crontab.log 2>&1

echo -e "$(welcome_print)"

./run_server.sh

# Uncomment below lines if you want to keep container running after server stops
#echo -e "$(server_stopped_print)"
#bash
