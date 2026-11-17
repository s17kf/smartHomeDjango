"""Nadpisanie z karty: „włącz / wyłącz na N minut”, anulowanie, wyświetlanie na karcie."""

import json
from datetime import timedelta
from unittest import mock

from django.urls import reverse
from django.utils import timezone

from ..models import Override
from .base import BrokerTestMixin, DeviceHelper, LocationHelper, LoggedInTestCase
from .test_cards import cache, system


class OverrideViewTests(BrokerTestMixin, LoggedInTestCase):
    def setUp(self):
        super().setUp()
        location = LocationHelper.create_location('room')
        self.plug = DeviceHelper.create_device(location, 'Plug', slug='plug-1')
        self.bulb = DeviceHelper.create_device(location, 'Bulb', slug='bulb-1', kind='light_rgbcct')
        self.temp = DeviceHelper.create_device(location, 'Temp', slug='temp-1', kind='sensor', driver='w1')
        self.now = timezone.now()
        system(seen=self.now)
        cache('plug-1', state={'on': False})
        cache('bulb-1', state={'on': False, 'brightness': 40, 'mode': 'cct', 'ct': 2700, 'rgb': [255, 0, 0]})
        cache('temp-1', telemetry={'temperature_c': 21.5})

    def post(self, slug, **fields):
        return self.client.post(reverse('devices:device_override', args=(slug,)), fields)

    def sent(self):
        return [(m.topic, json.loads(m.payload), m.retain) for m in self.broker.published]

    def test_on_for_minutes(self):
        with mock.patch('django.utils.timezone.now', return_value=self.now):
            response = self.post('plug-1', on='true', minutes='30')
        override = Override.objects.get(device=self.plug)
        self.assertEqual((override.state, override.until), ({'on': True}, self.now + timedelta(minutes=30)))
        # `set` od razu, jak przy zwykłym sterowaniu; karta czeka na potwierdzenie
        self.assertEqual(self.sent(), [('home/plug-1/set', {'on': True}, False)])
        self.assertContains(response, 'Sent – waiting for the device')
        self.assertContains(response, 'On until')

    def test_previous_state(self):
        self.post('plug-1', on='true', minutes='30')
        self.assertEqual(Override.objects.get().previous_state, {'on': False})
        # bez stanu w cache – stan spoczynkowy
        cache('plug-1', state=None)
        Override.objects.all().delete()
        self.post('plug-1', on='true', minutes='30')
        self.assertEqual(Override.objects.get().previous_state, {'on': False})

    def test_renewal_keeps_previous_state_and_start(self):
        with mock.patch('django.utils.timezone.now', return_value=self.now):
            self.post('plug-1', on='true', minutes='30')
        # w trakcie nadpisania urządzenie jest włączone – przedłużenie nie zmienia stanu do przywrócenia
        cache('plug-1', state={'on': True})
        system(seen=self.now + timedelta(minutes=10))
        with mock.patch('django.utils.timezone.now', return_value=self.now + timedelta(minutes=10)):
            self.post('plug-1', on='false', minutes='60')
        override = Override.objects.get()
        self.assertEqual((override.state, override.previous_state), ({'on': False}, {'on': False}))
        self.assertEqual((override.created_at, override.until),
                         (self.now, self.now + timedelta(minutes=70)))

    def test_light_off(self):
        self.post('bulb-1', on='false', minutes='15')
        self.assertEqual(Override.objects.get(device=self.bulb).state, {'on': False})
        self.assertEqual(self.sent(), [('home/bulb-1/set', {'on': False}, False)])

    def test_invalid(self):
        for slug, fields in (('plug-1', {'on': 'true', 'minutes': '0'}),
                             ('plug-1', {'on': 'true', 'minutes': '1441'}),
                             ('plug-1', {'on': 'true', 'minutes': 'x'}),
                             ('plug-1', {'on': 'maybe', 'minutes': '30'}),
                             ('plug-1', {'minutes': '30'}),
                             ('temp-1', {'on': 'true', 'minutes': '30'})):
            with self.subTest(slug=slug, fields=fields):
                response = self.post(slug, **fields)
                self.assertContains(response, 'alert-danger')
        self.assertFalse(Override.objects.exists())
        self.assertEqual(self.broker.published, [])

    def test_unavailable(self):
        system(gateway='offline', seen=self.now)
        response = self.post('plug-1', on='true', minutes='30')
        self.assertContains(response, 'The device is unavailable')
        self.assertFalse(Override.objects.exists())
        self.assertEqual(self.broker.published, [])

    def test_broker_error_keeps_override(self):
        # worker wyśle `set` sam – zmiana stanu pożądanego
        self.broker.error = 'connection refused'
        with self.assertLogs('devices.views', 'WARNING'):
            response = self.post('plug-1', on='true', minutes='30')
        self.assertContains(response, 'The MQTT worker will send it')
        self.assertTrue(Override.objects.exists())

    def test_cancel(self):
        Override.objects.create(device=self.plug, state={'on': True}, previous_state={'on': False},
                                until=self.now + timedelta(minutes=30))
        response = self.post('plug-1', cancel='1')
        # koniec nadpisania obsługuje worker – `until` przesunięte na teraz, bez `set` z widoku
        self.assertLessEqual(Override.objects.get().until, timezone.now())
        self.assertEqual(self.broker.published, [])
        self.assertNotContains(response, 'On until')
        self.assertContains(response, 'Timer')

    def test_post_only(self):
        response = self.client.get(reverse('devices:device_override', args=('plug-1',)))
        self.assertEqual(response.status_code, 405)


class OverrideCardTests(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        location = LocationHelper.create_location('room')
        self.plug = DeviceHelper.create_device(location, 'Plug', slug='plug-1')
        DeviceHelper.create_device(location, 'Temp', slug='temp-1', kind='sensor', driver='w1')
        system(seen=timezone.now())
        cache('plug-1', state={'on': True})
        cache('temp-1', telemetry={'temperature_c': 21.5})

    def card(self, slug):
        return self.client.get(reverse('devices:device_card', args=(slug,)))

    def test_timer_menu(self):
        response = self.card('plug-1')
        self.assertContains(response, 'data-bs-toggle="dropdown"')
        self.assertContains(response, '"minutes": "30"')
        self.assertContains(response, '2 h')
        self.assertNotContains(self.card('temp-1'), 'Timer')

    def test_active_override_in_local_time(self):
        # 11:00 UTC = 12:00 CET
        until = timezone.now().replace(year=2099, month=1, day=1, hour=11, minute=0, second=0, microsecond=0)
        Override.objects.create(device=self.plug, state={'on': False}, previous_state={'on': True}, until=until)
        response = self.card('plug-1')
        self.assertContains(response, 'Off until 12:00')
        self.assertContains(response, '"cancel": "1"')

    def test_expired_override_not_shown(self):
        Override.objects.create(device=self.plug, state={'on': False}, previous_state={'on': True},
                                until=timezone.now() - timedelta(seconds=1))
        self.assertNotContains(self.card('plug-1'), 'until')

    def test_disabled_when_unavailable(self):
        system(gateway='offline', seen=timezone.now())
        response = self.card('plug-1')
        self.assertRegex(response.content.decode(), r'data-bs-toggle="dropdown"\s+aria-expanded="false"\s+disabled')
