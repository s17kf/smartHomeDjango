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
- [Usage](#usage)
- [License](#license)

## Features

- Manage smart home devices (relay, more types soon).
- Responsive web interface for manage device's state.
- Admin panel to manage devices.

## Technologies Used

- **Backend:** Python
- **Frontend:** HTML, CSS, JavaScript
- **Web Framework:** Django
- **Database:** PostgreSQL (address in `DATABASE_URL`, see [Configuration](#configuration))

## Installation

The app is designed to run on a Raspberry Pi device.
To run on other devices, it is recommended to use Docker. See the [Docker](#docker) section for more details.

### Prerequisites

- Python 3.12+
- Pip (Python package installer)
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
  works and is used only by the development Docker image. Database
  connections are kept open for 60 s between requests.
- **Tests** create and drop a separate `test_<name>` database, so the
  PostgreSQL user needs the `CREATEDB` privilege.
- Check a production configuration with `python manage.py check --deploy`.

## Docker

The app can be run in a Docker container.
The Docker image is based on ubuntu and includes all dependencies required to run the app.

### Prerequisites

- Docker
- Repository cloned (see [Installation](#installation))
- Create a build.env file in the project root directory (use `build.env.example` as a template)

The image is meant for development: it uses SQLite
(`DATABASE_URL=sqlite:////home/ubuntu/smartHomeDjango/db.sqlite3`), sets
`DJANGO_DEBUG=true` and
`DJANGO_ALLOWED_HOSTS` to the host's IP address (detected on the `INTERFACE`
from `build.env`) and `localhost`, so the app is reachable from other devices
in the LAN.

### Build the Docker image

1. Navigate into the project directory:
   ```bash
   cd smartHomeDjango
   ```
2. Build the Docker image:
   ```bash
   ./build.sh [OPTIONS]
   ```
   Use -h option for help.

### Run the Docker container

1. Start the Docker container:
   ```bash
   ./run.sh
   ```
2. Start server:

   Run from the container shell (from home directory):
   ```bash
   ./run_server.sh
   ```
3. Access the app at http://localhost:8000

### Database Setup

Run ./build.sh script or docker build command will apply DB fixtures stored in
.json files in assets/db_fixtures directory.
To generate fixtures you can use command:

   ```
   ./manage.py dumpdata [app_name[.model_name]]

   ## Example:
   ./manage.py dumpdata auth.user
   ./manage.py dumpdata devices
   ```

### Moving data from SQLite to PostgreSQL

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
2. Access the app at http://localhost:8000
3. Log into the admin panel at http://localhost:8000/admin/ to manage devices.

## License

This project is licensed under the MIT License.