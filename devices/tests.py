from django.test import TestCase
from django.urls import reverse

from .models import Device, Location


# Create your tests here.

class DeviceModelTests(TestCase):
    pass


class LocationHelper:
    @staticmethod
    def create_location(name):
        return Location.objects.create(name=name)

    @staticmethod
    def get_context_locations(response):
        return response.context['locations']


class DeviceHelper:
    @staticmethod
    def create_device(location, name):
        params = {
            'location': location,
            'name': name,
            'config_file': 'config_file'
        }
        return Device.objects.create(**params)

    @staticmethod
    def get_context_device_details(response):
        return response.context['device']


class LocationListViewTests(TestCase):

    def get_location_list_response(self):
        return self.client.get(reverse('devices:location_list'))

    def test_no_locations(self):
        response = self.get_location_list_response()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No locations available.')
        self.assertQuerySetEqual(LocationHelper.get_context_locations(response), [])

    def test_one_location(self):
        location = LocationHelper.create_location('some location')
        response = self.get_location_list_response()
        self.assertNotContains(response, 'No locations available.')
        self.assertQuerySetEqual(LocationHelper.get_context_locations(response), [location])

    def test_two_locations(self):
        location1 = LocationHelper.create_location("location 1")
        location2 = LocationHelper.create_location("second location")
        response = self.get_location_list_response()
        self.assertQuerySetEqual(LocationHelper.get_context_locations(response),
                                 [location1, location2],
                                 ordered=False)


class LocationViewTests(TestCase):
    def get_location_response(self, location_id):
        return self.client.get(reverse('devices:location', args=(location_id,)))

    def test_location_not_exist(self):
        location = LocationHelper.create_location('location')
        invalid_id = location.id + 1
        response = self.get_location_response(invalid_id)
        self.assertEqual(response.status_code, 404)


class DeviceViewTests(TestCase):
    def get_device_response(self, device_id):
        return self.client.get(reverse('devices:device', args=(device_id,)))

    def setUp(self):
        self.location = LocationHelper.create_location('room')
        self.device = DeviceHelper.create_device(self.location, 'device')

    def test_device_not_exist(self):
        invalid_id = self.device.id + 1
        response = self.get_device_response(invalid_id)
        self.assertEqual(response.status_code, 404)

    def test_device_page_loads_status_scripts(self):
        response = self.get_device_response(self.device.id)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'jquery-3.7.1.min.js')
        self.assertContains(response, 'const RELAY_UPDATE_URL')
        self.assertContains(response, 'devices/js/device_status_update.js')


class RelayUpdateTests(TestCase):
    def get_relay_update_url(self, device_id):
        return reverse('devices:relay_update', args=(device_id,))

    def test_device_not_exist(self):
        response = self.client.post(self.get_relay_update_url(1), {'state': 'on'})
        self.assertEqual(response.json(), {'status': 'error', 'message': 'Device not found'})

    def test_get_not_allowed(self):
        response = self.client.get(self.get_relay_update_url(1))
        self.assertEqual(response.json(), {'status': 'error', 'message': 'Invalid request method'})
