"""Tematy kanoniczne `home/<slug>/…` i publikacja w brokerze MQTT.

Kontrakt: `smart-home-mqtt`, `specs/topics.md` i `specs/payloads.md`. Widoki,
admin i komendy publikują przez krótkie połączenie (connect → publish QoS 1 →
PUBACK → disconnect) – bez stałego klienta w procesach gunicorna. Przy MQTT 5
broker odpowiada na publikację odrzuconą przez ACL kodem błędu w PUBACK.

Broker wybiera `settings.MQTT_BROKER`: w aplikacji `MqttBroker`, w testach
`MemoryBroker` (ustawia go runner testów) – testy nie łączą się z brokerem,
także gdy w środowisku są zmienne `MQTT_*`.
"""

import functools
import json
import re
import secrets
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass

import paho.mqtt.client as paho
from django.conf import settings
from django.utils.module_loading import import_string
from paho.mqtt.enums import CallbackAPIVersion, MQTTProtocolVersion

PREFIX = 'home'
# Kolejność przy usuwaniu urządzenia: najpierw `config`, żeby gateway zatrzymał
# adapter (`specs/topics.md`, „Usunięcie urządzenia”).
DEVICE_TOPICS = ('config', 'state', 'telemetry', 'availability')
CONFIG_FILTER = f'{PREFIX}/+/config'
_TOPIC_RE = re.compile(r'\Ahome/([a-z0-9]+(?:-[a-z0-9]+)*)/([a-z]+)\Z')

TIMEOUT_S = 5.0


class MqttError(Exception):
    """Broker niedostępny, odmowa połączenia albo publikacji (np. ACL)."""


@dataclass(frozen=True)
class Message:
    topic: str
    payload: bytes
    retain: bool


def device_topic(slug: str, name: str) -> str:
    return f'{PREFIX}/{slug}/{name}'


def parse_topic(topic: str) -> tuple[str, str] | None:
    """`home/<slug>/<temat>` → (slug, temat); None dla innych tematów i złego sluga."""
    match = _TOPIC_RE.match(topic)
    if not match or len(match.group(1)) > 50:
        return None
    return match.group(1), match.group(2)


def encode_json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


def config_payload(device) -> dict:
    """Treść `home/<slug>/config` (`specs/payloads.md`): rodzaj, sterownik, parametry."""
    return {'kind': device.kind, 'driver': device.driver, 'params': device.params}


def config_messages(device) -> list[Message]:
    return [Message(device_topic(device.slug, 'config'), encode_json(config_payload(device)), retain=True)]


def removal_messages(slug: str) -> list[Message]:
    """Pusty retained na wszystkich tematach urządzenia – usunięcie z brokera."""
    return [Message(device_topic(slug, name), b'', retain=True) for name in DEVICE_TOPICS]


class MqttBroker:
    """Broker z ustawień (`MQTT_HOST`, `MQTT_PORT`, konto backendu) – krótkie połączenie."""

    def publish(self, messages: Iterable[Message]) -> None:
        messages = list(messages)
        if not messages:
            return
        with _Connection() as conn:
            infos = [conn.client.publish(m.topic, m.payload, qos=1, retain=m.retain) for m in messages]
            deadline = time.monotonic() + TIMEOUT_S
            for info in infos:
                try:
                    info.wait_for_publish(max(deadline - time.monotonic(), 0))
                except (RuntimeError, ValueError) as exc:
                    raise MqttError(f'publish failed: {exc}') from None
                if not info.is_published():
                    raise MqttError('no PUBACK from the broker')
            refused = [f'{m.topic} ({conn.acks[i.mid]})' for m, i in zip(messages, infos)
                       if conn.acks.get(i.mid) is not None and conn.acks[i.mid].is_failure]
            if refused:
                raise MqttError('broker refused: ' + ', '.join(refused))

    def retained(self, topic_filter: str, quiet_s: float = 0.5) -> dict[str, bytes]:
        """Wiadomości retained pasujące do filtra – broker wysyła je zaraz po subskrypcji.

        Koniec, gdy przez `quiet_s` nie przyszła żadna (najdłużej `TIMEOUT_S`).
        """
        with _Connection() as conn:
            result, _mid = conn.client.subscribe(topic_filter, qos=1)
            if result != paho.MQTT_ERR_SUCCESS or not conn.subscribed.wait(TIMEOUT_S):
                raise MqttError(f'subscribe {topic_filter} failed')
            if conn.suback_failure:
                raise MqttError(f'broker refused subscription {topic_filter}: {conn.suback_failure}')
            deadline = time.monotonic() + TIMEOUT_S
            while time.monotonic() - conn.last_message < quiet_s and time.monotonic() < deadline:
                time.sleep(0.05)
            return dict(conn.retained)


class _Connection:
    """Połączenie na czas jednej operacji: czysta sesja, MQTT 5, losowe id klienta."""

    def __init__(self):
        if not settings.MQTT_PASSWORD:
            raise MqttError('MQTT_BACKEND_PASSWORD is not set')
        self.client = paho.Client(
            CallbackAPIVersion.VERSION2,
            client_id=f'backend-web-{secrets.token_hex(4)}',
            protocol=MQTTProtocolVersion.MQTTv5,
        )
        self.client.username_pw_set(settings.MQTT_USER, settings.MQTT_PASSWORD)
        self.client.on_connect = self._on_connect
        self.client.on_publish = self._on_publish
        self.client.on_subscribe = self._on_subscribe
        self.client.on_message = self._on_message
        self.connected = threading.Event()
        self.connect_result = None
        self.acks = {}
        self.subscribed = threading.Event()
        self.suback_failure = None
        self.retained: dict[str, bytes] = {}
        self.last_message = time.monotonic()

    def __enter__(self):
        try:
            self.client.connect(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=30, clean_start=True)
        except (OSError, ValueError) as exc:
            raise MqttError(f'cannot connect to {settings.MQTT_HOST}:{settings.MQTT_PORT}: {exc}') from None
        self.client.loop_start()
        if not self.connected.wait(TIMEOUT_S):
            self._close()
            raise MqttError('no CONNACK from the broker')
        if self.connect_result.is_failure:
            self._close()
            raise MqttError(f'broker refused the connection: {self.connect_result}')
        return self

    def __exit__(self, *exc_info):
        self._close()

    def _close(self):
        self.client.disconnect()
        self.client.loop_stop()

    # Callbacki paho (CallbackAPIVersion.VERSION2) – w wątku pętli sieciowej.

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self.connect_result = reason_code
        self.connected.set()

    def _on_publish(self, client, userdata, mid, reason_code, properties):
        self.acks[mid] = reason_code

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties):
        failed = [rc for rc in reason_codes if rc.is_failure]
        self.suback_failure = failed[0] if failed else None
        self.last_message = time.monotonic()
        self.subscribed.set()

    def _on_message(self, client, userdata, message):
        # Flaga retain = 1 tylko dla wiadomości z pamięci brokera (przy subskrypcji).
        if message.retain:
            self.retained[message.topic] = message.payload
            self.last_message = time.monotonic()


class MemoryBroker:
    """Broker w pamięci dla testów: retained jak w Mosquitto, lista wszystkich publikacji.

    `error` ustawione na napis – każda operacja kończy się `MqttError` (broker
    niedostępny).
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.published: list[Message] = []
        self.retained_messages: dict[str, bytes] = {}
        self.error: str | None = None

    def publish(self, messages: Iterable[Message]) -> None:
        if self.error:
            raise MqttError(self.error)
        for message in messages:
            self.published.append(message)
            if message.retain:
                if message.payload:
                    self.retained_messages[message.topic] = message.payload
                else:
                    self.retained_messages.pop(message.topic, None)

    def retained(self, topic_filter: str, quiet_s: float = 0.5) -> dict[str, bytes]:
        if self.error:
            raise MqttError(self.error)
        return {topic: payload for topic, payload in self.retained_messages.items()
                if paho.topic_matches_sub(topic_filter, topic)}


def broker():
    """Broker z `settings.MQTT_BROKER` – jedna instancja na klasę (MemoryBroker trzyma stan)."""
    return _broker(settings.MQTT_BROKER)


@functools.cache
def _broker(path):
    return import_string(path)()
