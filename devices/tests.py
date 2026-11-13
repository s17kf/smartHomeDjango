import json
import os
import tempfile
from datetime import datetime, time, timezone as dt_timezone
from io import StringIO
from unittest import mock

import gpiocontrol as gpio
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .device_helpers import RelayPeriodicDeviceConfig
from .models import Device, Location, RelayPeriodicDay, RelayPeriodicManualActivation, RelayPeriodicPeriod


def utc(*args):
    """Chwila w UTC – testy ustawiają `timezone.now()` niezależnie od strefy hosta."""
    return datetime(*args, tzinfo=dt_timezone.utc)


def frozen_now(now):
    return mock.patch('django.utils.timezone.now', return_value=now)


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


class PeriodicDeviceTestCase(TestCase):
    """Urządzenie `relay-periodic` z plikiem konfiguracyjnym i zamockowanym GPIO (stan: wyłączone)."""

    PIN = 17

    def setUp(self):
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as config_file:
            json.dump({'pinNumber': self.PIN, 'activeState': gpio.State.HIGH.value}, config_file)
        self.addCleanup(os.unlink, config_file.name)
        for name, kwargs in (('get', {'return_value': gpio.State.LOW}), ('set', {})):
            patcher = mock.patch(f'gpiocontrol.{name}', **kwargs)
            setattr(self, f'gpio_{name}', patcher.start())
            self.addCleanup(patcher.stop)
        location = LocationHelper.create_location('room')
        self.device = Device.objects.create(location=location, name='periodic', config_file=config_file.name,
                                            type=Device.DeviceType.RELAY_PERIODIC)

    def config_at(self, now):
        with frozen_now(now):
            return RelayPeriodicDeviceConfig(self.device)


class RelayPeriodicLocalTimeTests(PeriodicDeviceTestCase):
    """Dni i okresy harmonogramu liczone w czasie lokalnym (Europe/Warsaw), nie w UTC."""

    def setUp(self):
        super().setUp()
        self.period = RelayPeriodicPeriod.objects.create(device=self.device, begin=time(0, 0), end=time(1, 0))

    def test_period_in_local_time_winter(self):
        # niedziela 23:30 UTC = poniedziałek 00:30 CET
        self.assertEqual(self.config_at(utc(2026, 11, 15, 23, 30)).current_period, self.period)

    def test_period_in_local_time_summer(self):
        # 22:30 UTC = 00:30 CEST
        self.assertEqual(self.config_at(utc(2026, 7, 1, 22, 30)).current_period, self.period)

    def test_period_not_in_utc(self):
        # 00:30 UTC = 01:30 CET – poza okresem 00:00–01:00, choć w UTC by się w nim mieścił
        self.assertIsNone(self.config_at(utc(2026, 11, 16, 0, 30)).current_period)

    def test_active_day_in_local_date(self):
        RelayPeriodicDay.objects.create(device=self.device, day=RelayPeriodicDay.DaysChoices.MONDAY)
        # w UTC jeszcze niedziela, lokalnie już poniedziałek
        config = self.config_at(utc(2026, 11, 15, 23, 30))
        self.assertTrue(config.is_active_day())
        self.assertEqual(config.current_day_display(), 'Monday')


class ManualActivationTimeTests(PeriodicDeviceTestCase):
    """Ręczne włączenie: koniec zapisany w UTC, wyświetlany w czasie lokalnym."""

    def activate(self, now, minutes):
        with frozen_now(now):
            self.client.post(reverse('devices:periodic_relay_manual_activate', args=(self.device.id,)),
                             {'minutes': minutes, 'next': '/'})
        return RelayPeriodicManualActivation.objects.get(device=self.device)

    def test_end_time_stored_in_utc(self):
        activation = self.activate(utc(2026, 11, 15, 23, 30, 45), 30)
        self.assertEqual(activation.end_time, utc(2026, 11, 16, 0, 0))
        config = self.config_at(utc(2026, 11, 15, 23, 45))
        self.assertTrue(config.is_manual_activated())
        self.assertEqual(config.get_manual_activation_end_display(), '2026-11-16 01:00')
        self.gpio_set.assert_called_once_with(self.PIN, gpio.State.HIGH)

    def test_expired(self):
        self.activate(utc(2026, 11, 15, 23, 30), 30)
        self.assertFalse(self.config_at(utc(2026, 11, 16, 0, 0, 1)).is_manual_activated())

    def test_duration_across_dst_change(self):
        # 25.10.2026 o 01:00 UTC zegary cofają się z 03:00 CEST na 02:00 CET:
        # włączenie o 02:30 CEST na 60 minut kończy się o 02:30 CET
        activation = self.activate(utc(2026, 10, 25, 0, 30), 60)
        self.assertEqual(activation.end_time, utc(2026, 10, 25, 1, 30))
        config = self.config_at(utc(2026, 10, 25, 1, 0))
        self.assertTrue(config.is_manual_activated())
        self.assertEqual(config.get_manual_activation_end_display(), '2026-10-25 02:30')


class RelaysPeriodicUpdateCommandTests(PeriodicDeviceTestCase):
    """Komenda workera `relays_periodic_update` w czasie lokalnym."""

    def run_at(self, now):
        with frozen_now(now):
            call_command('relays_periodic_update', stdout=StringIO())

    def test_activates_in_local_period(self):
        RelayPeriodicPeriod.objects.create(device=self.device, begin=time(0, 0), end=time(1, 0))
        self.run_at(utc(2026, 11, 15, 23, 30))
        self.gpio_set.assert_called_once_with(self.PIN, gpio.State.HIGH)

    def test_no_activation_outside_local_period(self):
        RelayPeriodicPeriod.objects.create(device=self.device, begin=time(0, 0), end=time(1, 0))
        self.run_at(utc(2026, 11, 16, 0, 30))
        self.gpio_set.assert_not_called()

    def test_keeps_active_manual_activation(self):
        RelayPeriodicManualActivation.objects.create(device=self.device, end_time=utc(2026, 11, 15, 23, 45))
        self.run_at(utc(2026, 11, 15, 23, 30))
        self.gpio_set.assert_called_once_with(self.PIN, gpio.State.HIGH)
        self.assertTrue(RelayPeriodicManualActivation.objects.filter(device=self.device).exists())

    def test_removes_expired_manual_activation(self):
        RelayPeriodicManualActivation.objects.create(device=self.device, end_time=utc(2026, 11, 15, 23, 0))
        self.run_at(utc(2026, 11, 15, 23, 30))
        self.gpio_set.assert_not_called()
        self.assertFalse(RelayPeriodicManualActivation.objects.filter(device=self.device).exists())
