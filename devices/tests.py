from django.test import TestCase
from django.urls import reverse

from .models import Device, Location


# Create your tests here.

class DeviceModelTests(TestCase):

    def test_switch_value0_device_control_input_params(self):
        dev = Device(type=Device.DeviceType.SWITCH, value=0)
        expected_params = [
            Device.ControlInputParams('radio', '0', {'value': 0, 'checked': ''}),
            Device.ControlInputParams('radio', '1', {'value': 1}),
        ]
        self.assertListEqual(dev.get_control_input_params_list(), expected_params)

    def test_switch_value1_device_control_input_params(self):
        dev = Device(type=Device.DeviceType.SWITCH, value=1)
        expected_params = [
            Device.ControlInputParams('radio', '0', {'value': 0}),
            Device.ControlInputParams('radio', '1', {'value': 1, 'checked': ''}),
        ]
        self.assertListEqual(dev.get_control_input_params_list(), expected_params)

    def test_pwm_device_control_input_params(self):
        value = 10
        min = 0
        max = 99
        dev = Device(type=Device.DeviceType.PWM, value=value, params=f'{{ "min": {min}, "max": {max} }}')
        expected_params = [
            Device.ControlInputParams(input_type='range', params={
                'value': value,
                'min': min,
                'max': max,
            })
        ]
        self.assertListEqual(dev.get_control_input_params_list(), expected_params)


class LocationHelper:
    @staticmethod
    def create_location(name):
        return Location.objects.create(name=name)

    @staticmethod
    def get_context_locations(response):
        return response.context['locations']


class DeviceHelper:
    @staticmethod
    def create_device(location, name, value=0, dev_type=None):
        params = {
            'location': location,
            'name': name,
            'value': value
        }
        if dev_type is not None:
            params['type'] = dev_type
        return Device.objects.create(**params)

    @staticmethod
    def get_context_device_list(response):
        return response.context['device_list']

    @staticmethod
    def get_context_device_details(response):
        return response.context['device']


class IndexViewTests(TestCase):

    def get_index_response(self):
        return self.client.get(reverse('devices:index'))

    def test_no_locations(self):
        response = self.get_index_response()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No locations available.')
        self.assertQuerySetEqual(LocationHelper.get_context_locations(response), [])

    def test_one_location(self):
        location = LocationHelper.create_location('some location')
        response = self.get_index_response()
        self.assertNotContains(response, 'No locations available.')
        self.assertQuerySetEqual(LocationHelper.get_context_locations(response), [location])

    def test_two_locations(self):
        location1 = LocationHelper.create_location("location 1")
        location2 = LocationHelper.create_location("second location")
        response = self.get_index_response()
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

    def test_no_devices_in_location(self):
        location_with_dev = LocationHelper.create_location('location1')
        location_empty = LocationHelper.create_location('location2')
        dev1 = DeviceHelper.create_device(location_with_dev, 'device')
        response = self.get_location_response(location_empty.id)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'No devices available in {location_empty.name}.')
        self.assertQuerySetEqual(DeviceHelper.get_context_device_list(response), [])

    def test_device_in_location(self):
        location_with_dev = LocationHelper.create_location('location1')
        location_empty = LocationHelper.create_location('location2')
        dev1 = DeviceHelper.create_device(location_with_dev, 'device')
        response = self.get_location_response(location_with_dev.id)
        self.assertEqual(response.status_code, 200)
        self.assertQuerySetEqual(DeviceHelper.get_context_device_list(response), [dev1])

    def test_devices_in_all_location(self):
        location1 = LocationHelper.create_location('location1')
        location2 = LocationHelper.create_location('location2')
        dev1_1 = DeviceHelper.create_device(location1, 'device')
        dev1_2 = DeviceHelper.create_device(location1, 'dev')
        dev2_1 = DeviceHelper.create_device(location2, 'dev in 2')
        response1 = self.get_location_response(location1.id)
        response2 = self.get_location_response(location2.id)
        self.assertEqual(response1.status_code, 200)
        self.assertQuerySetEqual(DeviceHelper.get_context_device_list(response1), [dev1_1, dev1_2], ordered=False)
        self.assertEqual(response2.status_code, 200)
        self.assertQuerySetEqual(DeviceHelper.get_context_device_list(response2), [dev2_1])


class DeviceView(TestCase):
    def get_device_response(self, device_id):
        return self.client.get(reverse('devices:device', args=(device_id,)))

    def setUp(self, dev_type=Device.DeviceType.SWITCH):
        self.location = LocationHelper.create_location('room')
        self.device = DeviceHelper.create_device(self.location, 'device', dev_type=dev_type)

    def test_device_not_exist(self):
        invalid_id = self.device.id + 1
        response = self.get_device_response(invalid_id)
        self.assertEqual(response.status_code, 404)

    def test_device_data(self):
        response = self.get_device_response(self.device.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(DeviceHelper.get_context_device_details(response), self.device)
        expected_device_type_label = Device.DeviceType(self.device.type).label
        self.assertEqual(response.context['device_type_label'], expected_device_type_label)
