"""Rodzaje urządzeń z kontraktu MQTT (`smart-home-mqtt`, `specs/payloads.md`).

Rodzaj określa pola polecenia `set`, stanu `state` i pomiarów `telemetry`
niezależnie od sterownika – gniazdko Shelly i Tasmota to ten sam rodzaj
`switch`. Te same pola i zakresy sprawdza gateway (`smart-home-gateway`,
`kinds.py`): zmiana kontraktu to zmiana w obu miejscach.

„Gniazdko z pomiarem” nie jest osobnym rodzajem – to `switch`, którego
urządzenie wysyła też `telemetry`.
"""

import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from django.utils.translation import gettext_lazy as _

Check = Callable[[Any], str | None]
"""Sprawdzenie wartości pola: opis błędu albo None, gdy wartość poprawna."""


class InvalidCommand(ValueError):
    """Polecenie `set` niezgodne z rodzajem urządzenia – odrzucane w całości."""


def _bool(value: Any) -> str | None:
    return None if isinstance(value, bool) else _('expected true or false')


def _int(value: Any) -> bool:
    # bool to w Pythonie podklasa int, a w JSON osobny typ.
    return isinstance(value, int) and not isinstance(value, bool)


def _int_range(low: int, high: int) -> Check:
    def check(value: Any) -> str | None:
        if not _int(value):
            return _('expected an integer')
        if not low <= value <= high:
            return _('allowed range %(low)s–%(high)s') % {'low': low, 'high': high}
        return None

    return check


def _choice(*allowed: str) -> Check:
    def check(value: Any) -> str | None:
        if value in allowed:
            return None
        return _('allowed values: %(values)s') % {'values': ', '.join(allowed)}

    return check


def _rgb(value: Any) -> str | None:
    if isinstance(value, list) and len(value) == 3 and all(_int(c) and 0 <= c <= 255 for c in value):
        return None
    return _('expected [r, g, b], each component 0–255')


def _seconds(value: Any) -> str | None:
    if (_int(value) or isinstance(value, float)) and math.isfinite(value) and value >= 0:
        return None
    return _('expected a number of seconds ≥ 0')


@dataclass(frozen=True)
class Measurement:
    """Pole `telemetry` – nazwa z jednostką w nazwie, opis i jednostka do wyświetlenia."""

    name: str
    label: str
    unit: str


# Wspólne nazwy pól `telemetry` (`payloads.md`); urządzenie wysyła tylko te, które mierzy.
MEASUREMENTS: dict[str, Measurement] = {m.name: m for m in (
    Measurement('power_w', _('Power'), 'W'),
    Measurement('energy_wh', _('Energy'), 'Wh'),
    Measurement('voltage_v', _('Voltage'), 'V'),
    Measurement('current_a', _('Current'), 'A'),
    Measurement('device_temperature_c', _('Device temperature'), '°C'),
    Measurement('temperature_c', _('Temperature'), '°C'),
    Measurement('humidity_pct', _('Humidity'), '%'),
)}


@dataclass(frozen=True, eq=False)
class Kind:
    """Rodzaj urządzenia. Instancje są stałymi modułu – porównujemy je przez tożsamość."""

    name: str
    label: str
    set_fields: Mapping[str, Check]
    state_fields: tuple[str, ...]
    """Pola pełnego stanu w `state` (gateway publikuje zawsze wszystkie)."""
    modifiers: frozenset[str] = frozenset()
    """Pola `set`, które same niczego nie zmieniają (np. czas przejścia)."""
    rest_state: Mapping[str, Any] | None = field(default=None)
    """Stan spoczynkowy – `set` poza oknami reguł; None: rodzaj bez reguł."""

    @property
    def accepts_commands(self) -> bool:
        return bool(self.set_fields)

    @property
    def accepts_rules(self) -> bool:
        return self.accepts_commands and self.rest_state is not None

    def validate_set(self, command: Any) -> dict[str, Any]:
        """Sprawdza polecenie i zwraca jego kopię; błąd → `InvalidCommand`."""
        if not self.accepts_commands:
            raise InvalidCommand(_('kind %(kind)s does not accept commands') % {'kind': self.name})
        if not isinstance(command, Mapping):
            raise InvalidCommand(_('expected a JSON object'))
        unknown = sorted(command.keys() - self.set_fields.keys())
        if unknown:
            raise InvalidCommand(_('fields outside kind %(kind)s: %(fields)s')
                                 % {'kind': self.name, 'fields': ', '.join(unknown)})
        if not command.keys() - self.modifiers:
            allowed = [name for name in self.set_fields if name not in self.modifiers]
            raise InvalidCommand(_('nothing to change – allowed fields: %(fields)s')
                                 % {'fields': ', '.join(allowed)})
        for name, value in command.items():
            error = self.set_fields[name](value)
            if error:
                raise InvalidCommand(f'{name}={json.dumps(value)}: {error}')
        return dict(command)


# Wyjście włącz/wyłącz: gniazdko, przekaźnik. `on` – wyjście włączone.
SWITCH = Kind(
    'switch', _('Switch'),
    set_fields={'on': _bool},
    state_fields=('on',),
    rest_state={'on': False},
)

# Światło z kolorem (RGB) i bielą o regulowanej temperaturze (CCT). Zmiana
# koloru wymaga `mode: "rgb"`, bieli – `mode: "cct"` (`payloads.md`).
LIGHT_RGBCCT = Kind(
    'light_rgbcct', _('RGBCCT light'),
    set_fields={
        'on': _bool,
        'brightness': _int_range(1, 100),
        'mode': _choice('rgb', 'cct'),
        'rgb': _rgb,
        'ct': _int_range(2700, 6500),
        'transition': _seconds,
    },
    state_fields=('on', 'brightness', 'mode', 'rgb', 'ct'),
    modifiers=frozenset({'transition'}),
    rest_state={'on': False},
)

# Czujnik: tylko pomiary (`telemetry`), bez `set` i `state`, więc bez reguł.
SENSOR = Kind('sensor', _('Sensor'), set_fields={}, state_fields=())

KINDS: dict[str, Kind] = {kind.name: kind for kind in (SWITCH, LIGHT_RGBCCT, SENSOR)}

CHOICES = [(kind.name, kind.label) for kind in KINDS.values()]
