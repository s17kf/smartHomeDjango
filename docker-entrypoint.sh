#!/bin/sh
# Start kontenera. Serwer WWW (domyślna komenda `gunicorn`) najpierw
# migruje bazę. Inne komendy z tego obrazu (np. worker:
# `python manage.py …`) startują bez migracji – migruje tylko jedna usługa,
# więc dwa kontenery nie wykonują jej naraz.
set -e

if [ "$1" = "gunicorn" ]; then
    python manage.py migrate --noinput
fi

exec "$@"
