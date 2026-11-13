# Smart Home Django App

A Python-based smart home management system with device tracking and site management functionality.
Intended to run on a Raspberry Pi.

Repository rules (architecture, directory layout, conventions, git workflow) are
described in [CONTRIBUTING.md](CONTRIBUTING.md) (in Polish).

## Table of Contents

- [Features](#features)
- [Technologies Used](#technologies-used)
- [Installation](#installation)
- [Configuration](#configuration)
- [Docker](#docker)
- [Moving data from SQLite to PostgreSQL](#moving-data-from-sqlite-to-postgresql)
- [Usage](#usage)
- [License](#license)

## Features

- Manage smart home devices (relay, more types soon).
- Responsive web interface for manage device's state.
- Login required for every page (Django sessions). No sign-up – accounts are
  created by an administrator.
- Admin panel to manage devices and user accounts.

## Technologies Used

- **Backend:** Python
- **Frontend:** HTML, CSS, JavaScript; Bootstrap, Bootstrap Icons and jQuery
  are bundled in the repository (no CDN, the UI works without internet access)
- **Static files:** [WhiteNoise](https://whitenoise.readthedocs.io/), see
  [Static files](#static-files)
- **Web Framework:** Django
- **Database:** PostgreSQL (address in `DATABASE_URL`, see [Configuration](#configuration))

## Installation

The app is designed to run on a Raspberry Pi (arm64) in Docker, see the
[Docker](#docker) section. The steps below set up local development.

### Prerequisites

- Python 3.12+
- Pip (Python package installer)
- GNU gettext (`msgfmt`) to compile translations
- PostgreSQL server (e.g. `docker run -d -p 127.0.0.1:5432:5432 -e POSTGRES_PASSWORD=… postgres:17-alpine`)

1. Clone the repository:
    ```bash
    git clone https://github.com/s17kf/smartHomeDjango.git
    ```
2. Navigate into the project directory:
    ```bash
    cd smartHomeDjango
    ```
3. Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
4. Set environment variables (see [Configuration](#configuration)). For local
   development debug mode and the database address are enough:
    ```bash
    export DJANGO_DEBUG=true
    export DATABASE_URL=postgres://user:password@localhost:5432/name
    ```

### Database Setup

Run the following commands to set up the database:

```bash
python manage.py migrate
python manage.py createsuperuser
```

Compile the translations (`.mo` files are not in the repository):

```bash
python manage.py compilemessages
```

### Start the development server

```bash
python manage.py runserver
```

Access the app at http://127.0.0.1:8000/.

## Configuration

Environment-specific settings are read from environment variables. Nothing
secret or host-specific is stored in the code.

| Variable | Required | Default | Description |
|---|---|---|---|
| `DJANGO_SECRET_KEY` | yes, unless debug is on | fixed insecure key (debug only) | Long random value, keep it secret. Changing it logs out all users. |
| `DJANGO_DEBUG` | no | `false` | Debug mode: `true`/`false` (also `1`/`0`, `yes`/`no`, `on`/`off`). Never enable it in production. |
| `DJANGO_ALLOWED_HOSTS` | yes, in production | empty | Comma-separated host names / IP addresses the app is served under, e.g. `smarthome.lan,192.168.1.10`. |
| `DATABASE_URL` | yes | – | Database URL in the [dj-database-url](https://github.com/jazzband/dj-database-url) format, e.g. `postgres://user:password@host:5432/name`. |
| `DJANGO_HTTPS` | no | `false` | `true` when the app is served over HTTPS by a reverse proxy (e.g. Caddy) that terminates TLS – see [HTTPS behind a reverse proxy](#https-behind-a-reverse-proxy). |

Notes:

- **Production** (debug off) needs at least `DJANGO_SECRET_KEY`,
  `DJANGO_ALLOWED_HOSTS` and `DATABASE_URL`; without the secret key or the
  database URL the app refuses to start.
  Generate the key with:
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(50))"
  ```
  The result contains only URL-safe characters (no `$`), so it can be put into
  `.env` files without quoting.
- **Debug mode** without `DJANGO_SECRET_KEY` uses a fixed development key, and
  with an empty `DJANGO_ALLOWED_HOSTS` Django accepts `localhost`, `127.0.0.1`
  and `[::1]`.
- **`DATABASE_URL`**: special characters in the user name or password must be
  URL-encoded (e.g. `@` → `%40`). The supported database is PostgreSQL
  (driver `psycopg` in `requirements.txt`). `sqlite:///<absolute path>` still
  works, but is not supported (the Docker build uses an in-memory SQLite URL
  only for `collectstatic`). Database connections are kept open for 60 s
  between requests.
- **Tests** create and drop a separate `test_<name>` database, so the
  PostgreSQL user needs the `CREATEDB` privilege.
- **Logs** go to stderr, also with debug off: Django warnings and errors,
  including server errors (500) with a traceback. Client errors (4xx) are
  only in the web server's request log.
- Check a production configuration with `python manage.py check --deploy`.
  See [HTTPS behind a reverse proxy](#https-behind-a-reverse-proxy) for the
  warnings that are expected.

### HTTPS behind a reverse proxy

The app itself speaks plain HTTP. HTTPS is terminated by a reverse proxy in
front of it, which forwards requests with the original `Host` header and
sets `X-Forwarded-Proto` (Caddy does both by default).

`DJANGO_HTTPS=true` makes the app trust `X-Forwarded-Proto: https` and marks
the session and CSRF cookies `Secure`. Without it a request coming through
the HTTPS proxy looks like plain HTTP to Django, so the CSRF check rejects
every form sent by a browser (`Origin checking failed`), including the login
form.

- Enable it only when the app is reachable **exclusively through the proxy**
  and the proxy overwrites `X-Forwarded-Proto` sent by clients (Caddy
  ignores it from untrusted clients). Otherwise a client could claim HTTPS by
  sending the header itself.
- Keep it off when the site is served over plain HTTP (e.g. in a local
  network): browsers do not send `Secure` cookies over HTTP, so logging in
  would fail.
- The app does not redirect HTTP to HTTPS and does not send HSTS – that is
  the proxy's job. Requests made directly to the app over HTTP (e.g. a health
  check inside the container) get a normal response.

Expected `check --deploy` warnings: with `DJANGO_HTTPS=true` –
`security.W004` (HSTS) and `security.W008` (HTTPS redirect); with it off
also `security.W012` and `security.W016` (cookies without `Secure`).

### Static files

CSS, JavaScript, fonts and front-end libraries live in the `static/`
directories of the apps (libraries in `devices/static/devices/vendor/`) and
are served by the app itself through WhiteNoise.

- **Production** (debug off): run
  ```bash
  python manage.py collectstatic --noinput
  ```
  after every code update, before starting the app (the Docker image does it
  at build time). It copies the files to
  `static_root/` with a content hash in their names and adds gzip versions.
  Browsers cache hashed files without revalidation (10 years); a changed file
  gets a new name. Without `collectstatic` pages fail with
  `Missing staticfiles manifest entry`. The command needs the same
  environment variables as the app, but does not connect to the database.
- **Debug mode and tests** serve the files directly from the app
  directories, `collectstatic` is not needed.

## Docker

The `Dockerfile` builds the production image (amd64 and arm64):
`python:3.14-slim`, [gunicorn](https://gunicorn.org/) on port 8000, a
non-root user. Translations are compiled and static files collected at build
time.

```bash
docker build -t smart-home-django .
docker run --rm -p 8000:8000 \
    -e DJANGO_SECRET_KEY=… -e DJANGO_ALLOWED_HOSTS=localhost \
    -e DATABASE_URL=postgres://user:password@host:5432/name \
    smart-home-django
```

- The default command (`gunicorn`) applies database migrations first. Any
  other command runs without migrations, so only one container migrates the
  database, e.g. a worker:
  `docker run … smart-home-django python manage.py relays_periodic_update`.
- gunicorn settings are in `gunicorn.conf.py`: 2 worker processes, request
  log on stdout. Change them without rebuilding with `WEB_CONCURRENCY`
  (number of processes) or `GUNICORN_CMD_ARGS` (any gunicorn option, e.g.
  `--log-level debug`).
- Run the tests in the image:
  `docker run --rm -e DJANGO_DEBUG=true -e DATABASE_URL=… smart-home-django python manage.py test`.
- Relays controlled through GPIO (`pinctrl`) do not work in the image –
  device control moves to MQTT.

## Moving data from SQLite to PostgreSQL

Dump the data with the old SQLite database, then load it into an empty,
migrated PostgreSQL database:

```bash
DATABASE_URL=sqlite:////path/to/db.sqlite3 ./manage.py dumpdata \
    --natural-foreign --natural-primary \
    -e contenttypes -e auth.permission -e admin.logentry -e sessions \
    --indent 2 -o data.json
DATABASE_URL=postgres://user:password@host:5432/name ./manage.py migrate
DATABASE_URL=postgres://user:password@host:5432/name ./manage.py loaddata data.json
```

Content types and permissions are recreated by `migrate`, so they are left
out of the dump (natural keys keep references to them valid). `loaddata`
resets the PostgreSQL ID sequences, so new objects get free IDs. `data.json`
contains password hashes – delete it afterwards.

## Usage

1. Build and run the app (locally or using docker) using the instructions above.
2. Access the app at http://localhost:8000 and log in. Every page requires
   login; the first account is created with `python manage.py createsuperuser`.
3. Log into the admin panel at http://localhost:8000/admin/ to manage devices
   and user accounts (Authentication and Authorization → Users). Regular
   users need no special permissions to use the app; the admin panel requires
   the *staff status* flag.

Sessions are stored in the database and last two weeks (Django default
`SESSION_COOKIE_AGE`). The *Log out* button is in the navigation bar.
Expired sessions stay in the database until `python manage.py clearsessions`
removes them.

## License

This project is licensed under the MIT License.