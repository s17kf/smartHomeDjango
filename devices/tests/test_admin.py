from django.test import TestCase
from django.urls import reverse

from ..models import Device
from .base import DeviceHelper, LocationHelper, User


class DeviceAdminTests(TestCase):
    """Urządzenia zakłada admin; slug podaje się tylko przy dodaniu."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser('admin')
        cls.location = LocationHelper.create_location('room')

    def setUp(self):
        self.client.force_login(self.admin)

    def test_add_device(self):
        response = self.client.post(reverse('admin:devices_device_add'), {
            'name': 'Plug', 'location': self.location.pk, 'slug': 'plug-1', 'kind': 'switch',
            'driver': 'shelly', 'params': '{"prefix": "shelly/plug1", "component": "switch:0"}',
        })
        self.assertRedirects(response, reverse('admin:devices_device_changelist'))
        device = Device.objects.get(slug='plug-1')
        self.assertEqual(device.params, {'prefix': 'shelly/plug1', 'component': 'switch:0'})

    def test_add_rejects_secret_params(self):
        response = self.client.post(reverse('admin:devices_device_add'), {
            'name': 'Plug', 'location': self.location.pk, 'slug': 'plug-1', 'kind': 'switch',
            'driver': 'shelly', 'params': '{"password": "x"}',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'look like a secret')
        self.assertFalse(Device.objects.exists())

    def test_slug_read_only_after_creation(self):
        device = DeviceHelper.create_device(self.location, 'plug')
        add = self.client.get(reverse('admin:devices_device_add'))
        change = self.client.get(reverse('admin:devices_device_change', args=(device.pk,)))
        self.assertContains(add, 'name="slug"')
        self.assertNotContains(change, 'name="slug"')
        self.assertContains(change, device.slug)

    def test_location_shows_devices(self):
        device = DeviceHelper.create_device(self.location, 'plug')
        response = self.client.get(reverse('admin:devices_location_change', args=(self.location.pk,)))
        self.assertContains(response, device.slug)
