"""Ustawienia gunicorna – wczytywane automatycznie z katalogu roboczego.

Zmiana bez przebudowy obrazu: WEB_CONCURRENCY (liczba procesów) albo
GUNICORN_CMD_ARGS z dowolnymi opcjami (np. "--log-level debug") – mają
pierwszeństwo przed tym plikiem.
https://docs.gunicorn.org/en/stable/settings.html
"""

import os

wsgi_app = 'smartHomeSite.wsgi'
bind = '0.0.0.0:8000'

# Każdy proces to osobna kopia Django w RAM (RPi4). Ruch domowy obsłużą dwa.
workers = int(os.environ.get('WEB_CONCURRENCY', '2'))
# Django ładowane raz w procesie głównym; procesy robocze współdzielą tę
# pamięć (copy-on-write). Połączenia z bazą Django otwiera dopiero w żądaniu.
# Pomiar kontenera na RPi4 (2026-11-13): 2 workery – 77 MiB, bez preload
# 107 MiB; 1 worker – 63 MiB, każdy kolejny ok. +14 MiB.
preload_app = True

# Plik heartbeat procesów roboczych w pamięci zamiast na overlayfs kontenera
# https://docs.gunicorn.org/en/stable/faq.html#blocking-os-fchmod
worker_tmp_dir = '/dev/shm'

# Gniazdo sterujące `gunicornc` (od 25.1) niepotrzebne – zmiany przez restart
# kontenera; bez katalogu domowego i XDG_RUNTIME_DIR kończyłoby się ostrzeżeniem.
control_socket_disable = True

# Log żądań na stdout (błędy gunicorna domyślnie na stderr)
accesslog = '-'
