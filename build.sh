#!/usr/bin/bash

function usage() {
    cat <<EOF
  Usage: $0 [OPTIONS]

  Prepare and build docker image for smartHomeWebApp.

  WARNING: This script will unstage all changes in git repository!

  Options:
    -a, --add-file FILE     Add file to be included in patch applied to docker image's repo
    -c, --cache             Do not use --no-cache flag when building docker image
    -h, --help              Display this help and exit
EOF
}

if [ "$EUID" -eq 0 ]
  then echo "$0 Can't be run as root!"
  exit 1
fi

# Check if sudo is available and ask password if needed
sudo ls > /dev/null

VALID_ARGS=$(getopt -o a:ch --long add-file:,cache,help -- "$@")
if [[ $? -ne 0 ]]; then
  usage
  exit 1;
fi

set -e

eval set -- "$VALID_ARGS"
files_to_copy=()
cache="--no-cache"
# shellcheck disable=SC2078
while [ : ]; do
  case "$1" in
    -a | --add-file)
      if [[ ! -f "$2" && ! -d "$2" ]]; then
        echo "File $2 does not exist!"
        exit 1
      fi
      files_to_copy+=("$2")
      shift 2
      ;;
    -c | --cache)
      echo "--no-cache flag will NOT be used"
      cache=""
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    --) shift;
      break
      ;;
  esac
done

if [[ $# -ne 0 ]]; then
  echo "Unexpected arguments provided:" "$@"
  usage
  exit 1
fi

# shellcheck disable=SC2164
cd "$(dirname "$0")"

mkdir -p _tmp
for file in "${files_to_copy[@]}"; do
  echo "git add ${file}"
  git add "$file"
done
git diff --staged HEAD > _tmp/patch.diff
git reset HEAD


HOST_IP=$(ifconfig wlp0s20f3 | grep -Po "inet (?:[0-9]{1,3}\.){3}[0-9]{1,3}" | \
          sed 's/inet //')
echo "host's IP: ${HOST_IP}"

sudo docker build -t smarthome . $cache --build-arg HOST_IP="${HOST_IP}"

echo "Cleaning up"
rm -rf _tmp
