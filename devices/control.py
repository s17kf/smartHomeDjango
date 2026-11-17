"""Polecenia `set` z kart urządzeń: pola formularza → polecenie, wysłanie, potwierdzenie.

Pola z formularza (każda kontrolka wysyła tylko swoje): `on` (`true`/`false`),
`brightness`, `ct`, `color` (`#rrggbb`), `mode`. Zmiana koloru wymaga
`mode: "rgb"`, bieli – `mode: "cct"` (`smart-home-mqtt`, `specs/payloads.md`),
więc `color` i `ct` dokładają tryb same. Pola spoza rodzaju i zakresy
sprawdza `Kind.validate_set` – błędne polecenie nie jest wysyłane.
"""

import json
import logging
import re
from urllib.parse import urlencode

from django.urls import reverse
from django.utils.translation import gettext as _

from . import mqtt
from .kinds import InvalidCommand

log = logging.getLogger(__name__)

# Ile razy karta po wysłaniu odpytuje o stan (co 1 s), zanim pokaże „brak potwierdzenia”.
CONFIRM_TRIES = 5
_HEX_COLOR = re.compile(r'\A#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})\Z')


def _bool(value):
    if value in ('true', 'false'):
        return value == 'true'
    raise InvalidCommand(_('on: expected true or false'))


def _int(name, value):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise InvalidCommand(_('%(field)s: expected an integer') % {'field': name}) from None


def parse_command(data) -> dict:
    """Pola formularza (QueryDict) → polecenie `set` (jeszcze bez sprawdzenia według rodzaju)."""
    command = {}
    if 'on' in data:
        command['on'] = _bool(data['on'])
    if 'brightness' in data:
        command['brightness'] = _int('brightness', data['brightness'])
    if 'mode' in data:
        command['mode'] = data['mode']
    if 'ct' in data:
        command['ct'] = _int('ct', data['ct'])
        command.setdefault('mode', 'cct')
    if 'color' in data:
        match = _HEX_COLOR.match(data['color'])
        if not match:
            raise InvalidCommand(_('color: expected #rrggbb'))
        command['rgb'] = [int(part, 16) for part in match.groups()]
        command.setdefault('mode', 'rgb')
    return command


def send(device, command) -> None:
    """Publikacja `home/<slug>/set`; błąd brokera → `mqtt.MqttError`."""
    mqtt.broker().publish([mqtt.set_message(device.slug, command)])
    log.info('%s: set %s', device.slug, json.dumps(command))


def refresh_url(device, command, attempt) -> str:
    """Adres karty, która sprawdzi, czy stan potwierdził polecenie (kolejna próba)."""
    query = urlencode({'cmd': json.dumps(command, separators=(',', ':')), 'try': attempt})
    return f"{reverse('devices:device_card', args=(device.slug,))}?{query}"


def pending_command(params):
    """Polecenie i numer próby z adresu karty; (None, 0) przy braku lub błędnej wartości."""
    try:
        command = json.loads(params.get('cmd', ''))
        attempt = int(params.get('try', ''))
    except (TypeError, ValueError):
        return None, 0
    if not isinstance(command, dict) or not 1 <= attempt <= CONFIRM_TRIES:
        return None, 0
    return command, attempt
