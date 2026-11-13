# Obraz aplikacji: gunicorn + whitenoise. python:*-slim ma warianty amd64
# i arm64 (Raspberry Pi 4).

# Etap tłumaczeń: skompilowane .mo są poza gitem, a msgfmt (gettext) jest
# potrzebny tylko tutaj – nie trafia do obrazu.
FROM python:3.14-slim AS messages
RUN apt-get update \
    && apt-get install -y --no-install-recommends gettext \
    && rm -rf /var/lib/apt/lists/*
COPY locale /locale
# To samo co `manage.py compilemessages`; `{} +`, żeby błąd msgfmt przerwał budowę
RUN find /locale -name '*.po' -exec sh -c \
    'for po; do msgfmt --check-format -o "${po%.po}.mo" "$po" || exit 1; done' _ {} +

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .
COPY --from=messages /locale ./locale

# Statyki z hashem w nazwach i manifest powstają tylko przy wyłączonym DEBUG.
# Ustawienia wymagają wtedy klucza i adresu bazy – tu wartości tylko na czas
# tej komendy (collectstatic nie łączy się z bazą), nie zostają w obrazie.
RUN DJANGO_DEBUG=false \
    DJANGO_SECRET_KEY=collectstatic-only \
    DATABASE_URL=sqlite://:memory: \
    python manage.py collectstatic --noinput

# Kod i statyki należą do roota – aplikacja tylko je czyta.
RUN useradd --system --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin django
USER django

EXPOSE 8000
# Ustawienia gunicorna w gunicorn.conf.py (wczytywany z katalogu roboczego).
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn"]
