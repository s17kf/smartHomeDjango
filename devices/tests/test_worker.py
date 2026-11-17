import json
import logging
from datetime import datetime, timezone as dt_timezone
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from .. import worker
from ..models import DeviceState, SystemStatus
from ..worker import Worker
from .base import DeviceHelper, LocationHelper

OK = SimpleNamespace(is_failure=False)
REFUSED = SimpleNamespace(is_failure=True)


class FakeClient:
    """Atrapa klienta paho – zapisuje subskrypcje i publikacje."""

    def __init__(self):
        self.subscribed = []
        self.unsubscribed = []
        self.published = []

    def subscribe(self, topic_filter, qos=0):
        self.subscribed.append(topic_filter)

    def unsubscribe(self, topic_filter):
        self.unsubscribed.append(topic_filter)

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, retain))


class WorkerTestCase(TestCase):
    def setUp(self):
        # INFO workera (połączenie, synchronizacja) tylko tam, gdzie test go sprawdza (assertLogs)
        logger = logging.getLogger('devices.worker')
        self.addCleanup(logger.setLevel, logger.level)
        logger.setLevel(logging.WARNING)
        # TestCase trzyma transakcję (bez autocommit), a close_old_connections()
        # zamyka wtedy połączenie – na PostgreSQL test traci bazę. Klient
        # testowy Django wyłącza ją z tego samego powodu.
        patcher = mock.patch('devices.worker.close_old_connections')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = FakeClient()
        self.worker = Worker(self.client)

    def message(self, topic, payload, retain=False):
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        if isinstance(payload, str):
            payload = payload.encode()
        self.worker.on_message(topic, payload, retain)

    def state(self, slug):
        return DeviceState.objects.get(slug=slug)


class CacheTests(WorkerTestCase):
    """Cache stanu z tematów `home/<slug>/…` i `gateway/status`."""

    def test_state(self):
        self.message('home/plug-1/state', {'on': True, 'ts': '2026-11-16T21:57:38Z'})
        state = self.state('plug-1')
        self.assertEqual(state.state, {'on': True})
        self.assertEqual(state.state_ts, datetime(2026, 11, 16, 21, 57, 38, tzinfo=dt_timezone.utc))

    def test_telemetry_and_availability(self):
        self.message('home/temp-1/telemetry', {'temperature_c': 24.4375, 'ts': '2026-11-16T21:57:38Z'})
        self.message('home/temp-1/availability', 'online')
        state = self.state('temp-1')
        self.assertEqual(state.telemetry, {'temperature_c': 24.4375})
        self.assertEqual(state.availability, 'online')
        self.assertIsNone(state.state)

    def test_newer_replaces(self):
        self.message('home/plug-1/state', {'on': True, 'ts': '2026-11-16T21:57:38Z'})
        self.message('home/plug-1/state', {'on': False, 'ts': 'not a date'})
        state = self.state('plug-1')
        self.assertEqual(state.state, {'on': False})
        self.assertIsNone(state.state_ts)

    def test_slug_without_device(self):
        # urządzenie może powstać w Django później – cache po slugu, bez klucza obcego
        self.message('home/not-in-db/availability', 'offline')
        self.assertEqual(self.state('not-in-db').availability, 'offline')

    def test_invalid_messages_ignored(self):
        self.message('home/plug-1/state', {'on': True})
        with self.assertLogs('devices.worker', 'WARNING') as logs:
            self.message('home/plug-1/state', '{not json')
            self.message('home/plug-1/state', '[1, 2]')
            self.message('home/plug-1/availability', 'maybe')
            self.message('home/Plug_1/state', {'on': False})
            self.message('gateway/status', 'restarting')
        self.assertEqual(len(logs.output), 5)
        self.assertEqual(self.state('plug-1').state, {'on': True})
        self.assertEqual(DeviceState.objects.count(), 1)

    def test_empty_payload_clears(self):
        # usunięcie urządzenia: pusty retained na każdym temacie
        self.message('home/plug-1/state', {'on': True})
        self.message('home/plug-1/telemetry', {'power_w': 5})
        self.message('home/plug-1/availability', 'online')
        self.message('home/plug-1/state', '')
        self.assertIsNone(self.state('plug-1').state)
        self.message('home/plug-1/telemetry', '')
        self.message('home/plug-1/availability', '')
        self.assertFalse(DeviceState.objects.exists())
        self.message('home/other/state', '')
        self.assertFalse(DeviceState.objects.exists())

    def test_gateway_status(self):
        self.message('gateway/status', 'online')
        self.assertEqual(SystemStatus.get().gateway_status, 'online')
        self.message('gateway/status', 'offline')
        self.assertEqual(SystemStatus.get().gateway_status, 'offline')


class ConnectionTests(WorkerTestCase):
    def test_connect_subscribes(self):
        self.worker.on_connect(OK)
        self.assertEqual(self.client.subscribed, ['home/+/state', 'home/+/telemetry', 'home/+/availability',
                                                  'gateway/status', 'home/+/config'])
        self.assertTrue(SystemStatus.get().worker_connected)

    def test_refused_connection(self):
        with self.assertLogs('devices.worker', 'ERROR'):
            self.worker.on_connect(REFUSED)
        self.assertEqual(self.client.subscribed, [])

    def test_disconnect(self):
        self.worker.on_connect(OK)
        with self.assertLogs('devices.worker', 'WARNING'):
            self.worker.on_disconnect(REFUSED)
        self.assertFalse(SystemStatus.get().worker_connected)

    def test_heartbeat(self):
        self.worker.on_connect(OK)
        self.worker.tick(monotonic=1000)
        seen = SystemStatus.get().worker_seen_at
        self.assertIsNotNone(seen)
        self.worker.tick(monotonic=1010)
        self.assertEqual(SystemStatus.get().worker_seen_at, seen)
        self.worker.tick(monotonic=1030)
        self.assertGreater(SystemStatus.get().worker_seen_at, seen)


class ConfigSyncTests(WorkerTestCase):
    """Po połączeniu: retained `config` z brokera porównany z bazą, brakujące i zmienione publikowane."""

    def setUp(self):
        super().setUp()
        location = LocationHelper.create_location('room')
        self.same = DeviceHelper.create_device(location, 'same')
        self.missing = DeviceHelper.create_device(location, 'missing')

    def connect_with_retained(self):
        with mock.patch('devices.worker.time.monotonic', return_value=100.0):
            self.worker.on_connect(OK)
            payload = json.dumps({'kind': 'switch', 'driver': 'shelly', 'params': self.same.params}).encode()
            self.worker.on_message('home/same/config', payload, True)
            self.worker.on_message('home/extra/config', b'{"kind":"switch","driver":"x","params":{}}', True)

    def test_sync_after_quiet_period(self):
        self.connect_with_retained()
        self.worker.tick(monotonic=100.5)
        self.assertEqual(self.client.published, [])
        with self.assertLogs('devices.worker', 'INFO') as logs:
            self.worker.tick(monotonic=101.5)
        self.assertEqual([(t, r) for t, _p, r in self.client.published], [('home/missing/config', True)])
        self.assertEqual(self.client.unsubscribed, ['home/+/config'])
        self.assertIn('kept', ''.join(logs.output))
        # bez usuwania urządzeń spoza bazy
        self.assertFalse([t for t, _p, _r in self.client.published if 'extra' in t])

    def test_sync_once_per_connection(self):
        self.connect_with_retained()
        with self.assertLogs('devices.worker', 'INFO'):
            self.worker.tick(monotonic=101.5)
        self.worker.tick(monotonic=200)
        self.assertEqual(len(self.client.published), 1)
        # po ponownym połączeniu – od nowa
        self.connect_with_retained()
        with self.assertLogs('devices.worker', 'INFO'):
            self.worker.tick(monotonic=101.5)
        self.assertEqual(len(self.client.published), 2)

    def test_live_config_ignored(self):
        self.worker.on_connect(OK)
        self.worker.on_message('home/same/config', b'{}', False)
        self.assertEqual(self.worker.config_retained, {})


class AutomationTickTests(WorkerTestCase):
    """Reguły co `AUTOMATION_S`, tylko przy połączeniu i po synchronizacji `config`; `set` przez klienta workera."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch('devices.worker.automation.step')
        self.step = patcher.start()
        self.addCleanup(patcher.stop)

    def test_not_connected(self):
        self.worker.tick(monotonic=1000)
        self.step.assert_not_called()

    def test_after_sync(self):
        with mock.patch('devices.worker.time.monotonic', return_value=100.0):
            self.worker.on_connect(OK)
        self.worker.tick(monotonic=100.5)
        self.step.assert_not_called()
        with self.assertLogs('devices.worker', 'INFO'):
            self.worker.tick(monotonic=101.5)
        self.step.assert_called_once()
        self.worker.tick(monotonic=103)
        self.assertEqual(self.step.call_count, 1)
        self.worker.tick(monotonic=106.5)
        self.assertEqual(self.step.call_count, 2)

    def test_publish_set(self):
        with mock.patch('devices.worker.time.monotonic', return_value=100.0):
            self.worker.on_connect(OK)
        with self.assertLogs('devices.worker', 'INFO'):
            self.worker.tick(monotonic=101.5)
        publish = self.step.call_args.args[0]
        publish('plug-1', {'on': True})
        self.assertEqual(self.client.published, [('home/plug-1/set', b'{"on":true}', False)])


class CommandTests(TestCase):
    @override_settings(MQTT_PASSWORD='')
    def test_requires_password(self):
        with self.assertRaisesMessage(CommandError, 'MQTT_BACKEND_PASSWORD'):
            call_command('mqtt_worker', stdout=StringIO())

    @override_settings(MQTT_PASSWORD='x')
    def test_runs_until_stopped(self):
        with mock.patch.object(worker, 'run') as run:
            call_command('mqtt_worker', stdout=StringIO())
        run.assert_called_once()
