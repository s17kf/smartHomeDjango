# Smart Home Web Application

A Python-based smart home management system with device tracking and site management functionality.
Intended to run on a Raspberry Pi.

## Table of Contents
- [Features](#features)
- [Technologies Used](#technologies-used)
- [Installation](#installation)
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

### Prerequisites
- Python 3.11+
- Pip (Python package installer)
  
1. Clone the repository:
    ```bash
    git clone https://github.com/s17kf/smartHomeWebApp.git
    ```
2. Navigate into the project directory:
    ```bash
    cd smartHomeWebApp
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

## Usage

1. Log into the admin panel at http://127.0.0.1:8000/admin/ to manage devices.
2. Add, edit, or delete smart home devices via the admin panel
(config file for each device has to be created manually).
3. View and manage devices state via the web interface.

## License

This project is licensed under the MIT License.