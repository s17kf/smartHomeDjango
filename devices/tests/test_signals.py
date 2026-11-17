from django.db import transaction
from django.db.models.signals import post_save
from django.test import TestCase

from ..models import Device
from .base import BrokerTestMixin, DeviceHelper, LocationHelper


class ConfigPublishingTests(BrokerTestMixin, TestCase):
    """Django jest źródłem `home/<slug>/config` – publikacja po zatwierdzeniu transakcji."""

    def setUp(self):
        super().setUp()
        self.location = LocationHelper.create_location('room')

    def create(self, name='plug', **fields):
        with self.captureOnCommitCallbacks(execute=True):
            return DeviceHelper.create_device(self.location, name, **fields)

    def test_create_publishes_config(self):
        device = self.create()
        self.assertEqual(self.retained_json('home/plug/config'),
                         {'kind': 'switch', 'driver': 'shelly', 'params': device.params})
        self.assertIsNone(device.mqtt_error)

    def test_change_publishes_new_config(self):
        device = self.create()
        with self.captureOnCommitCallbacks(execute=True):
            device.params = {'prefix': 'shelly/plug2', 'component': 'switch:0'}
            device.save()
        self.assertEqual(self.retained_json('home/plug/config')['params']['prefix'], 'shelly/plug2')

    def test_delete_clears_topics(self):
        device = self.create()
        for name in ('state', 'telemetry', 'availability'):
            self.broker.retained_messages[f'home/plug/{name}'] = b'x'
        self.broker.published.clear()
        with self.captureOnCommitCallbacks(execute=True):
            device.delete()
        self.assertEqual([(m.topic, m.payload) for m in self.broker.published],
                         [(f'home/plug/{name}', b'') for name in ('config', 'state', 'telemetry', 'availability')])
        self.assertEqual(self.broker.retained_messages, {})

    def test_location_delete_clears_devices(self):
        self.create('plug')
        self.create('lamp')
        with self.captureOnCommitCallbacks(execute=True):
            self.location.delete()
        self.assertEqual(self.broker.retained_messages, {})

    def test_rollback_publishes_nothing(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            try:
                with transaction.atomic():
                    DeviceHelper.create_device(self.location, 'plug')
                    raise RuntimeError('rollback')
            except RuntimeError:
                pass
        self.assertEqual(callbacks, [])
        self.assertEqual(self.broker.published, [])

    def test_raw_save_publishes_nothing(self):
        # loaddata – bez publikacji, zgodność przywraca mqtt_sync
        device = Device(location=self.location, name='plug', slug='plug', kind='switch', driver='shelly')
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            post_save.send(sender=Device, instance=device, created=True, raw=True)
        self.assertEqual(callbacks, [])

    def test_broker_error_keeps_device(self):
        self.broker.error = 'connection refused'
        with self.assertLogs('devices.signals', 'WARNING') as logs:
            device = self.create()
        self.assertTrue(Device.objects.filter(slug='plug').exists())
        self.assertEqual(device.mqtt_error, 'connection refused')
        self.assertIn('plug: config not published', logs.output[0])
