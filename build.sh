#!/usr/bin/bash

RED_B='\033[1;31m'
YELLOW_B='\033[1;33m'
BOLD='\033[1m'
ITALIC='\033[3m'
NC='\033[0m'

ERROR="${RED_B}ERROR${NC}:"
WARNING="${YELLOW_B}WARNING${NC}:"
INFO="${BOLD}INFO${NC}:"

function usage() {
  cat <<EOF
${BOLD}Usage${NC}: $0 [OPTIONS]

Prepare and build docker image for SmartHomeDjango app.

${YELLOW_B}WARNING${NC}: Any files staged for commit will be included in patch and UNSTAGED!

${BOLD}Options${NC}:
  -a, --add-file FILE[,FILE]
                      Add file(s)/dir(s) to be included in patch applied to docker image's repo
                      To add multiple entries use comma as separator.
  -c, --cache         Do not use --no-cache flag when building docker image
  -h, --help          Display this help and exit
EOF
}

# run git commands as root will cause problems with permissions afterwards
if [ "$EUID" -eq 0 ]; then
  echo -e "${ERROR} $0 Can't be run as root!"
  exit 1
fi

# Check if sudo is available and ask password if needed
sudo ls > /dev/null

VALID_ARGS=$(getopt -o a:ch --long add-file:,cache,help -- "$@")
if [[ $? -ne 0 ]]; then
  echo -e "$(usage)"
  exit 1;
fi

set -e

eval set -- "$VALID_ARGS"
cache="--no-cache"
# shellcheck disable=SC2078
while [ : ]; do
  case "$1" in
    -a | --add-file)
      if [[ ${files_to_git_add} ]]; then
        echo -e "${ERROR} $1 option can be used only once!"
        exit 1
      fi
      IFS=',' read -r -a files_to_git_add <<< "$2"
      for file in "${files_to_git_add[@]}"; do
        if [[ ! -f "$file" && ! -d "$file" ]]; then
          echo -e "${ERROR} File ${file} does not exist!"
          exit 1
        fi
      done
      shift 2
      ;;
    -c | --cache)
      echo -e "${INFO} --no-cache flag will NOT be used"
      cache=""
      shift
      ;;
    -h | --help)
      echo -e "$(usage)"
      exit 0
      ;;
    --) shift;
      break
      ;;
  esac
done

if [[ $# -ne 0 ]]; then
  echo -e "${ERROR} Unexpected arguments provided:" "$@"
  echo -e "$(usage)"
  exit 1
fi

# shellcheck disable=SC2164
cd "$(dirname "$0")"

mkdir -p _tmp
for file in "${files_to_git_add[@]}"; do
  echo -e "${INFO} git add ${file}"
  git add "$file"
done
echo -e "${INFO} Files included in patch:"
git diff --staged HEAD --name-only | xargs -i echo -e "\t{}"
git diff --staged HEAD > _tmp/patch.diff
echo -e "${INFO} Run: ${ITALIC}git reset HEAD${NC}"
git reset HEAD > /dev/null


HOST_IP=$(ifconfig wlp0s20f3 | grep -Po "inet (?:[0-9]{1,3}\.){3}[0-9]{1,3}" | sed 's/inet //')
echo -e "${INFO} host's IP: ${HOST_IP}"

echo -e "${INFO} Run: ${ITALIC}sudo docker build -t smarthome . $cache --build-arg HOST_IP=\"${HOST_IP}\"${NC}"
sudo docker build -t smarthome . $cache --build-arg HOST_IP="${HOST_IP}"

echo -e "${INFO} Cleaning up"
rm -rf _tmp
