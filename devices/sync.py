"""Zgodność retained `home/+/config` w brokerze z bazą – źródłem prawdy jest baza.

Wspólne dla `manage.py mqtt_sync` i workera MQTT (synchronizacja po każdym
połączeniu, bez usuwania). Porównujemy sparsowany JSON, jak gateway – inna
kolejność kluczy czy odstępy nie są zmianą.
"""

import json
from dataclasses import dataclass, field

from . import mqtt


@dataclass
class SyncPlan:
    added: list[str] = field(default_factory=list)
    """W bazie, brak `config` w brokerze."""
    changed: list[str] = field(default_factory=list)
    """Inna (albo niepoprawna) treść `config` w brokerze."""
    unchanged: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    """`config` w brokerze dla sluga, którego nie ma w bazie."""
    messages: list[mqtt.Message] = field(default_factory=list)
    """Publikacja nowych i zmienionych wpisów."""

    def prune_messages(self) -> list[mqtt.Message]:
        """Usunięcie z brokera urządzeń spoza bazy – tylko na wyraźne żądanie."""
        return [message for slug in self.extra for message in mqtt.removal_messages(slug)]


def plan(retained: dict[str, bytes], devices) -> SyncPlan:
    """Plan synchronizacji z retained wiadomości `home/+/config` i urządzeń z bazy."""
    in_broker = {}
    for topic, payload in retained.items():
        parsed = mqtt.parse_topic(topic)
        if parsed is None or parsed[1] != 'config' or not payload:
            continue
        try:
            in_broker[parsed[0]] = json.loads(payload)
        except ValueError:
            in_broker[parsed[0]] = None

    result = SyncPlan()
    in_db = set()
    for device in sorted(devices, key=lambda d: d.slug):
        in_db.add(device.slug)
        if device.slug not in in_broker:
            result.added.append(device.slug)
        elif in_broker[device.slug] != mqtt.config_payload(device):
            result.changed.append(device.slug)
        else:
            result.unchanged.append(device.slug)
            continue
        result.messages += mqtt.config_messages(device)
    result.extra = sorted(in_broker.keys() - in_db)
    return result
