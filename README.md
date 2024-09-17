# Smart Home Django App

A Python-based smart home management system with device tracking and site management functionality.
Intended to run on a Raspberry Pi.

## Table of Contents

- [Features](#features)
- [Technologies Used](#technologies-used)
- [Installation](#installation)
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
- **Database:** SQLite (can be replaced with other compatible databases)

## Installation

The app is designed to run on a Raspberry Pi device.
To run on other devices, it is recommended to use Docker. See the [Docker](#docker) section for more details.

### Prerequisites

- Python 3.11+
- Pip (Python package installer)

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

## Docker

The app can be run in a Docker container.
The Docker image is based on ubuntu and includes all dependencies required to run the app.

### Prerequisites

- Docker
- Repository cloned (see [Installation](#installation))

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
   python3 manage.py dumpdata [app_name[.model_name]]
   ```

## Usage

1. Build and run the app (locally or using docker) using the instructions above.
2. Access the app at http://localhost:8000
3. Log into the admin panel at http://localhost:8000/admin/ to manage devices.

## License

This project is licensed under the MIT License.