import io
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from ..models import Device, Location
from .base import BrokerTestMixin, DeviceHelper, LocationHelper

DEVICES = {
    'plug-1': {'name': 'Gniazdko', 'location': 'Salon', 'kind': 'switch', 'driver': 'shelly',
               'params': {'prefix': 'shelly/plug1', 'component': 'switch:0'}},
    'temp-1': {'name': 'Termometr', 'location': 'Sypialnia', 'kind': 'sensor', 'driver': 'w1',
               'params': {'sensor': '28-00000a99077c', 'interval_s': 60}},
}


class ImportDevicesTests(BrokerTestMixin, TestCase):
    """`import_devices` – format jak `devices.json`: slug → name, location, kind, driver, params."""

    def run_import(self, data, *args):
        text = data if isinstance(data, str) else json.dumps(data)
        with tempfile.NamedTemporaryFile('w', suffix='.json', encoding='utf-8', delete=False) as file:
            file.write(text)
        self.addCleanup(Path(file.name).unlink)
        out = io.StringIO()
        with self.captureOnCommitCallbacks(execute=True):
            call_command('import_devices', file.name, *args, stdout=out)
        return out.getvalue()

    def assert_rejected(self, data, message, *args):
        with self.assertRaisesMessage(CommandError, message):
            self.run_import(data, *args)
        self.assertFalse(Device.objects.exists())
        self.assertFalse(Location.objects.exists())
        self.assertEqual(self.broker.published, [])

    def test_import(self):
        out = self.run_import(DEVICES)
        self.assertIn('added: plug-1 (Salon), temp-1 (Sypialnia)', out)
        device = Device.objects.get(slug='temp-1')
        self.assertEqual((device.name, device.location.name, device.kind, device.driver),
                         ('Termometr', 'Sypialnia', 'sensor', 'w1'))
        self.assertEqual(device.params, DEVICES['temp-1']['params'])
        # zapis publikuje `config` jak każdy inny
        self.assertEqual(json.loads(self.broker.retained_messages['home/plug-1/config'])['driver'], 'shelly')

    def test_stdin(self):
        out = io.StringIO()
        with mock.patch('sys.stdin', io.StringIO(json.dumps(DEVICES))):
            call_command('import_devices', '-', stdout=out)
        self.assertEqual(Device.objects.count(), 2)

    def test_default_location(self):
        data = {'plug-1': {key: value for key, value in DEVICES['plug-1'].items() if key != 'location'}}
        self.run_import(data, '--location', 'Dom')
        self.assertEqual(Device.objects.get().location.name, 'Dom')

    def test_existing_location_and_slug(self):
        location = LocationHelper.create_location('Salon')
        DeviceHelper.create_device(location, 'old', slug='plug-1')
        out = self.run_import(DEVICES)
        self.assertIn('added: temp-1 (Sypialnia)', out)
        self.assertIn('skipped (slug already in the database): plug-1', out)
        self.assertEqual(Device.objects.get(slug='plug-1').name, 'old')
        self.assertEqual(Location.objects.filter(name='Salon').count(), 1)

    def test_invalid_file(self):
        self.assert_rejected('{"plug-1": ', 'invalid JSON')
        self.assert_rejected('{"a": {}, "a": {}}', 'duplicate keys: a')
        self.assert_rejected([], 'expected a JSON object')

    def test_invalid_entries(self):
        # błąd w jednym wpisie – nic nie zostaje zapisane, także poprawne wpisy
        cases = {
            'slug': ({'Plug_1': DEVICES['plug-1']}, 'Plug_1: slug'),
            'unknown field': ({'plug-1': {**DEVICES['plug-1'], 'login': 'plug1'}}, 'unknown fields: login'),
            'no name': ({'plug-1': {**DEVICES['plug-1'], 'name': ''}}, 'name: expected a non-empty string'),
            'no location': ({'plug-1': {k: v for k, v in DEVICES['plug-1'].items() if k != 'location'}},
                            'location: expected a non-empty string (or --location)'),
            'kind': ({'plug-1': {**DEVICES['plug-1'], 'kind': 'relay'}}, 'plug-1: kind'),
            'secret': ({'plug-1': {**DEVICES['plug-1'], 'params': {'password': 'x'}}}, 'look like a secret'),
            'not object': ({'plug-1': 'shelly'}, 'expected an object'),
        }
        for name, (entries, message) in cases.items():
            with self.subTest(name):
                self.assert_rejected({**DEVICES, **entries}, message)


class MqttSyncTests(BrokerTestMixin, TestCase):
    """`mqtt_sync` – retained `config` w brokerze zgodny z bazą."""

    def setUp(self):
        super().setUp()
        location = LocationHelper.create_location('room')
        for name in ('same', 'changed', 'missing'):
            DeviceHelper.create_device(location, name)
        device = Device.objects.get(slug='same')
        self.broker.retained_messages.update({
            # inna kolejność kluczy i odstępy – ta sama treść
            'home/same/config': json.dumps({'params': device.params, 'driver': 'shelly', 'kind': 'switch'},
                                           indent=2).encode(),
            'home/changed/config': json.dumps({'kind': 'switch', 'driver': 'tasmota', 'params': {}}).encode(),
            'home/extra/config': b'{"kind": "switch", "driver": "shelly", "params": {}}',
            'home/extra/state': b'{"on": true}',
            'home/same/state': b'{"on": false}',
        })

    def run_sync(self, *args):
        out = io.StringIO()
        call_command('mqtt_sync', *args, stdout=out)
        return out.getvalue()

    def test_sync(self):
        out = self.run_sync()
        self.assertIn('added: missing', out)
        self.assertIn('changed: changed', out)
        self.assertIn('unchanged: same', out)
        self.assertIn('only in the broker – not in the database, kept (use --prune to remove): extra', out)
        self.assertEqual(sorted(m.topic for m in self.broker.published),
                         ['home/changed/config', 'home/missing/config'])
        self.assertEqual(json.loads(self.broker.retained_messages['home/changed/config'])['driver'], 'shelly')
        self.assertIn('home/extra/config', self.broker.retained_messages)

    def test_second_run_publishes_nothing(self):
        self.run_sync()
        self.broker.published.clear()
        out = self.run_sync()
        self.assertIn('added: -', out)
        self.assertIn('changed: -', out)
        self.assertEqual(self.broker.published, [])

    def test_invalid_config_in_broker(self):
        self.broker.retained_messages['home/same/config'] = b'{not json'
        self.assertIn('changed: changed, same', self.run_sync())

    def test_dry_run(self):
        out = self.run_sync('--dry-run')
        self.assertIn('dry run – 2 message(s) not published', out)
        self.assertEqual(self.broker.published, [])

    def test_prune(self):
        out = self.run_sync('--prune')
        self.assertIn('only in the broker – removing: extra', out)
        self.assertFalse([topic for topic in self.broker.retained_messages if topic.startswith('home/extra/')])
        self.assertIn('home/same/state', self.broker.retained_messages)

    def test_broker_unavailable(self):
        self.broker.error = 'connection refused'
        with self.assertRaises(CommandError) as caught:
            self.run_sync()
        self.assertEqual(caught.exception.returncode, 2)
        self.assertIn('MQTT broker unavailable', str(caught.exception))
