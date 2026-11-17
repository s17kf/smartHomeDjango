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

- Manage locations and smart home devices; devices are controlled only
  through MQTT (`home/<slug>/set`), via the gateway.
- Device cards per kind (switch, RGBCCT light, sensor) with state, measurements and
  availability, refreshed every 10 s; on/off switch, brightness, white
  temperature and colour controls. After a command the card waits up to 5 s
  for the device to confirm the new state.
- Automation rules: on chosen days of the week at a given time set a device
  state (e.g. on at 18:00, off at 23:00) – list, form and on/off switch per
  rule; "on / off for N minutes" from the device card. Rules run in the MQTT
  worker.
- Dark Bootstrap theme, cards on every page, one column on a phone.
- Login required for every page (Django sessions). No sign-up – accounts are
  created by an administrator.
- Admin panel to manage devices and user accounts.

## Technologies Used

- **Backend:** Python
- **Frontend:** HTML, CSS, [htmx](https://htmx.org/); Bootstrap, Bootstrap Icons and htmx
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
| `MQTT_HOST` | no | `localhost` | Address of the MQTT broker (its listener for services). |
| `MQTT_PORT` | no | `1883` | Broker port. |
| `MQTT_BACKEND_USER` | no | `backend` | Broker account of the app. |
| `MQTT_BACKEND_PASSWORD` | yes, to reach the broker | empty | Password of that account. Without it the pages work, but device changes are not published to the broker (warning in the admin panel and in the log). |

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
  PostgreSQL user needs the `CREATEDB` privilege. They never connect to the
  MQTT broker, even with the `MQTT_*` variables set – the test runner
  replaces it with an in-memory one.
- **`MQTT_*`**: an empty value means the default.
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
  database, e.g. the MQTT worker:
  `docker run … smart-home-django python manage.py mqtt_worker`.
- gunicorn settings are in `gunicorn.conf.py`: 2 worker processes, request
  log on stdout. Change them without rebuilding with `WEB_CONCURRENCY`
  (number of processes) or `GUNICORN_CMD_ARGS` (any gunicorn option, e.g.
  `--log-level debug`).
- Run the tests in the image:
  `docker run --rm -e DJANGO_DEBUG=true -e DATABASE_URL=… smart-home-django python manage.py test`.

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

### Devices

Devices are added in the admin panel (Devices → Devices). The app talks to
them only through the MQTT gateway, so a device is described in terms of the
canonical MQTT contract (`smart-home-mqtt`, `specs/payloads.md`):

| Field | Meaning |
|---|---|
| `slug` | Identifier in the MQTT topics `home/<slug>/…`: lowercase letters and digits, words separated by single hyphens, at most 50 characters, e.g. `plug-living-room`. It cannot be changed after the device is created – a new slug means new topics. |
| `kind` | `switch` – on/off output (a plug or a relay; power readings when the device measures them), `light_rgbcct` – light with colour and white, `sensor` – measurements only, no commands. |
| `driver` | Device family handled by the gateway, e.g. `shelly`, `tasmota`, `w1`. The app does not check the list – a device with an unknown driver stays offline. |
| `params` | Driver parameters as a JSON object, e.g. `{"prefix": "shelly/plug1", "component": "switch:0"}`. No passwords – devices log in to the broker themselves; keys that look like a secret (`pass`, `secret`, `token`) are rejected. |

The database is the source of the device configuration for the gateway.
Saving a device publishes its retained `home/<slug>/config` (`kind`,
`driver`, `params`); deleting it – also by deleting its location – clears
`config`, `state`, `telemetry` and `availability` with empty retained
messages. The broker gets the change after the database transaction
commits. When the broker is unavailable, the change is saved anyway and the
admin panel shows a warning. Bring the broker in line with the database:

```bash
python manage.py mqtt_sync --dry-run   # only compare
python manage.py mqtt_sync             # publish missing and changed configs
python manage.py mqtt_sync --prune     # also remove devices known only to the broker
```

The exit code is 2 when the broker is unavailable. `loaddata` does not
publish anything – run `mqtt_sync` afterwards.

The state of the devices comes from the MQTT worker – a separate,
long-running process (one per installation, MQTT client id
`backend-worker`):

```bash
python manage.py mqtt_worker   # stops on SIGTERM / Ctrl+C
```

It keeps a cache of the latest `state`, `telemetry` and `availability` of
every device and of `gateway/status` in the database (visible read-only in
the admin panel: Device states, System status), reconnects to the broker on
its own and after every connection publishes missing or changed device
configs, like `mqtt_sync` without `--prune`. A heartbeat every 30 s tells the
pages whether the cached data is current. Every 5 s it runs the automation
rules ([Automation rules](#automation-rules)). Without the worker the pages
and the admin panel still work, but show no device state and rules do not
run.

Devices can also be imported from a JSON object (slug → device). The whole
file is checked first and on any error nothing is saved; slugs already in
the database are skipped; locations are created by name:

```json
{
  "plug-1": {"name": "Plug", "location": "Living room", "kind": "switch",
             "driver": "shelly", "params": {"prefix": "shelly/plug1", "component": "switch:0"}}
}
```

```bash
python manage.py import_devices devices.json             # "-" reads standard input
python manage.py import_devices devices.json --location Home   # for entries without "location"
```

### Automation rules

Rules are managed on the *Rules* page (filter by device, add, edit, switch
on/off, delete) and on the device page (its rules, *Add rule* with the device
chosen). The admin panel shows them too (Devices → Rules). A rule belongs to
a device (not a sensor) and says: on these days of the week (Monday to
Friday, stored as `[0, 1, 2, 3, 4]`) at this local `time` set
`target_state` – the fields of a `set` command for the device kind:

```json
{"on": true}
{"on": true, "brightness": 30, "mode": "cct", "ct": 2700}
{"brightness": 10}
```

"On from 18:00 to 23:00" is two rules. Two rules of one device at the same
time on the same day must set the same state.

- The worker sends `set` when a rule's time comes and repeats it every
  minute, at most 5 times and only while the device is available, until
  `state` confirms it. Between rules it sends nothing: a manual change
  (card, button, wall switch) stays until the next rule.
- A worker restart without a missed rule sends nothing. Rules missed while
  the worker was down: only the latest one is sent after the start. A rule
  added after its time today first runs on its next day.
- *Timer* on the device card – on or off for 15 min … 2 h (an override). The
  command is sent at once and rules wait. When the time is up or the
  override is cancelled, the device gets the state of the latest rule from
  that time, or the state it had before the override.
- Times come from the local wall clock: on the spring clock change a rule in
  the missing hour runs at 03:00, in autumn a rule in the repeated hour runs
  once.

The worker logs every rule and override event and every `set` it sends
(INFO), and a warning when a state is not confirmed after 5 attempts. The
admin panel shows the last event of each device (Devices → Automation
states).

## License

This project is licensed under the MIT License.