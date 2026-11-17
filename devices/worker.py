"""Worker MQTT – jedyny stały klient brokera po stronie Django (`manage.py mqtt_worker`).

- Subskrybuje tematy backendu (`smart-home-mqtt`, `specs/topics.md`):
  `home/+/state`, `home/+/telemetry`, `home/+/availability`, `gateway/status`
  i zapisuje je w cache (`DeviceState`, `SystemStatus`). Po każdym połączeniu
  broker oddaje retained wiadomości, więc cache się odświeża.
- Po każdym połączeniu porównuje retained `home/+/config` z bazą i publikuje
  brakujące lub zmienione wpisy (`sync.py`) – bez usuwania.
- Heartbeat w `SystemStatus` – UI uznaje dane za aktualne tylko przy żywym
  i połączonym workerze.

Callbacki paho działają w wątku pętli sieciowej, `tick()` w wątku głównym.
Każda porcja pracy z bazą jest otoczona `close_old_connections()`, jak
żądanie HTTP – worker przeżywa restart PostgreSQL.
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone as dt_timezone

from django.db import close_old_connections
from django.utils import timezone

from . import mqtt, sync
from .models import Device, DeviceState, SystemStatus

log = logging.getLogger(__name__)

GATEWAY_STATUS_TOPIC = 'gateway/status'
SUBSCRIPTIONS = (f'{mqtt.PREFIX}/+/state', f'{mqtt.PREFIX}/+/telemetry',
                 f'{mqtt.PREFIX}/+/availability', GATEWAY_STATUS_TOPIC)
AVAILABILITY = ('online', 'offline')
HEARTBEAT_S = 30
# Synchronizacja `config`: koniec zbierania retained, gdy przez tyle sekund
# nie przyszła żadna wiadomość `config` (broker oddaje je zaraz po SUBACK).
SYNC_QUIET_S = 1.0


def parse_ts(value):
    """`ts` z payloadu (ISO 8601 UTC, np. `2026-11-16T21:57:38Z`) → datetime albo None."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt_timezone.utc)


class Worker:
    """Logika workera niezależna od pętli paho – `client` to klient paho albo atrapa w testach."""

    def __init__(self, client):
        self.client = client
        self.connected = False
        self.sync_pending = False
        self.config_retained: dict[str, bytes] = {}
        self.last_config_at = 0.0
        self.last_heartbeat = None

    # Zdarzenia połączenia (wątek paho)

    def on_connect(self, reason_code):
        if reason_code.is_failure:
            log.error('MQTT broker refused the connection: %s', reason_code)
            return
        log.info('connected to the MQTT broker')
        self.connected = True
        for topic_filter in SUBSCRIPTIONS + (mqtt.CONFIG_FILTER,):
            self.client.subscribe(topic_filter, qos=1)
        self.config_retained = {}
        self.last_config_at = time.monotonic()
        self.sync_pending = True
        self._save_status(worker_connected=True)

    def on_disconnect(self, reason_code):
        if reason_code.is_failure:
            log.warning('disconnected from the MQTT broker: %s – reconnecting', reason_code)
        else:
            log.info('disconnected from the MQTT broker')
        self.connected = False
        self.sync_pending = False
        self._save_status(worker_connected=False)

    # Wiadomości (wątek paho)

    def on_message(self, topic, payload, retain):
        if topic == GATEWAY_STATUS_TOPIC:
            self._gateway_status(payload)
            return
        parsed = mqtt.parse_topic(topic)
        if parsed is None:
            log.warning('%s: unexpected topic – ignored', topic)
            return
        slug, name = parsed
        if name == 'config':
            # tylko na czas synchronizacji po połączeniu
            if self.sync_pending and retain:
                self.config_retained[topic] = payload
                self.last_config_at = time.monotonic()
        elif name in ('state', 'telemetry'):
            self._measurement(slug, name, payload)
        elif name == 'availability':
            self._availability(slug, payload)

    def _gateway_status(self, payload):
        value = payload.decode(errors='replace')
        if value not in AVAILABILITY and value:
            log.warning('gateway/status: unexpected value %r – ignored', value)
            return
        self._save_status(gateway_status=value)

    def _measurement(self, slug, name, payload):
        if not payload:
            self._clear(slug, name)
            return
        try:
            data = json.loads(payload)
        except ValueError:
            log.warning('home/%s/%s: invalid JSON – ignored', slug, name)
            return
        if not isinstance(data, dict):
            log.warning('home/%s/%s: expected a JSON object – ignored', slug, name)
            return
        ts = parse_ts(data.pop('ts', None))
        self._update(slug, **{name: data, f'{name}_ts': ts})

    def _availability(self, slug, payload):
        value = payload.decode(errors='replace')
        if not value:
            self._clear(slug, 'availability')
        elif value in AVAILABILITY:
            self._update(slug, availability=value)
        else:
            log.warning('home/%s/availability: unexpected value %r – ignored', slug, value)

    def _update(self, slug, **fields):
        close_old_connections()
        DeviceState.objects.update_or_create(slug=slug, defaults=fields)

    def _clear(self, slug, name):
        """Pusty retained – urządzenie usunięte; wiersz znika, gdy nie ma już żadnych danych."""
        close_old_connections()
        fields = {'availability': ''} if name == 'availability' else {name: None, f'{name}_ts': None}
        state = DeviceState.objects.filter(slug=slug).first()
        if state is None:
            return
        for field, value in fields.items():
            setattr(state, field, value)
        if state.state is None and state.telemetry is None and not state.availability:
            state.delete()
        else:
            state.save()

    def _save_status(self, **fields):
        close_old_connections()
        SystemStatus.objects.update_or_create(pk=1, defaults=fields)

    # Wątek główny

    def tick(self, monotonic=None):
        """Krok pętli głównej: synchronizacja `config` po połączeniu i heartbeat."""
        now = time.monotonic() if monotonic is None else monotonic
        if self.sync_pending and now - self.last_config_at >= SYNC_QUIET_S:
            self.sync_pending = False
            self._sync_configs()
        if self.last_heartbeat is None or now - self.last_heartbeat >= HEARTBEAT_S:
            self.last_heartbeat = now
            self._save_status(worker_connected=self.connected, worker_seen_at=timezone.now())

    def _sync_configs(self):
        self.client.unsubscribe(mqtt.CONFIG_FILTER)
        close_old_connections()
        result = sync.plan(self.config_retained, Device.objects.all())
        for message in result.messages:
            self.client.publish(message.topic, message.payload, qos=1, retain=message.retain)
        log.info('config sync: added %s, changed %s, unchanged %d',
                 ', '.join(result.added) or '-', ', '.join(result.changed) or '-', len(result.unchanged))
        if result.extra:
            log.warning('config in the broker for devices not in the database (kept, '
                        'remove with "manage.py mqtt_sync --prune"): %s', ', '.join(result.extra))

    def stop(self):
        self._save_status(worker_connected=False)


def run(stop_event: threading.Event, loop_s: float = 1.0):
    """Proces workera: klient paho z ponownym łączeniem, pętla główna do `stop_event`."""
    import paho.mqtt.client as paho
    from django.conf import settings
    from paho.mqtt.enums import CallbackAPIVersion, MQTTProtocolVersion

    client = paho.Client(CallbackAPIVersion.VERSION2, client_id='backend-worker',
                         protocol=MQTTProtocolVersion.MQTTv5)
    client.username_pw_set(settings.MQTT_USER, settings.MQTT_PASSWORD)
    client.reconnect_delay_set(1, 30)
    worker = Worker(client)

    def on_connect(client_, userdata, flags, reason_code, properties):
        worker.on_connect(reason_code)

    def on_disconnect(client_, userdata, flags, reason_code, properties):
        worker.on_disconnect(reason_code)

    def on_connect_fail(client_, userdata):
        # broker niedostępny (także przy starcie) – paho ponawia z opóźnieniem 1 → 30 s
        log.warning('cannot connect to the MQTT broker %s:%s – retrying', settings.MQTT_HOST, settings.MQTT_PORT)

    def on_message(client_, userdata, message):
        try:
            worker.on_message(message.topic, message.payload, message.retain)
        except Exception:
            # błąd jednej wiadomości (np. chwilowo niedostępna baza) nie zatrzymuje pętli paho
            log.exception('%s: message handling failed', message.topic)

    def on_publish(client_, userdata, mid, reason_code, properties):
        if reason_code.is_failure:
            log.warning('MQTT broker refused publish mid=%s: %s', mid, reason_code)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_connect_fail = on_connect_fail
    client.on_message = on_message
    client.on_publish = on_publish

    log.info('connecting to the MQTT broker %s:%s as %s', settings.MQTT_HOST, settings.MQTT_PORT,
             settings.MQTT_USER)
    client.connect_async(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=30, clean_start=True)
    client.loop_start()
    try:
        while not stop_event.wait(loop_s):
            try:
                worker.tick()
            except Exception:
                log.exception('worker step failed')
    finally:
        client.disconnect()
        client.loop_stop()
        try:
            worker.stop()
        except Exception:
            log.exception('cannot save worker status')
        log.info('stopped')
