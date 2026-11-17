import json
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.http import QueryDict
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from ..control import parse_command
from ..kinds import LIGHT_RGBCCT, SWITCH, InvalidCommand
from ..templatetags.devices_extras import rgb_hex
from .base import BrokerTestMixin, DeviceHelper, LocationHelper, LoggedInTestCase, User
from .test_cards import cache, system


class ParseCommandTests(SimpleTestCase):
    """Pola z kontrolek karty → polecenie `set`."""

    def parse(self, **fields):
        data = QueryDict(mutable=True)
        data.update(fields)
        return parse_command(data)

    def test_fields(self):
        self.assertEqual(self.parse(on='true'), {'on': True})
        self.assertEqual(self.parse(on='false'), {'on': False})
        self.assertEqual(self.parse(brightness='40'), {'brightness': 40})
        # biel i kolor dokładają tryb – samo `rgb` nie przełącza żarówki (payloads.md)
        self.assertEqual(self.parse(ct='3000'), {'ct': 3000, 'mode': 'cct'})
        self.assertEqual(self.parse(color='#FF0010'), {'rgb': [255, 0, 16], 'mode': 'rgb'})
        self.assertEqual(self.parse(), {})

    def test_invalid(self):
        for fields in ({'on': 'yes'}, {'brightness': 'x'}, {'ct': ''}, {'color': 'red'}, {'color': '#ff00'}):
            with self.subTest(fields=fields), self.assertRaises(InvalidCommand):
                self.parse(**fields)


class SatisfiedTests(SimpleTestCase):
    def test_satisfied(self):
        state = {'on': True, 'brightness': 40, 'mode': 'rgb', 'rgb': [255, 0, 0], 'ct': 2700}
        self.assertTrue(LIGHT_RGBCCT.satisfied(state, {'rgb': [255, 0, 0], 'mode': 'rgb', 'transition': 2}))
        self.assertFalse(LIGHT_RGBCCT.satisfied(state, {'brightness': 41}))
        self.assertFalse(SWITCH.satisfied(None, {'on': True}))
        self.assertTrue(SWITCH.satisfied({'on': False}, {'on': False}))

    def test_rgb_hex(self):
        self.assertEqual(rgb_hex([255, 0, 16]), '#ff0010')
        self.assertEqual(rgb_hex(None), '#ffffff')
        self.assertEqual(rgb_hex([256, 0, 0]), '#ffffff')


class DeviceSetTests(BrokerTestMixin, LoggedInTestCase):
    """`POST device/<slug>/set/` → `home/<slug>/set`, odpowiedź – karta czekająca na potwierdzenie."""

    def setUp(self):
        super().setUp()
        location = LocationHelper.create_location('room')
        self.plug = DeviceHelper.create_device(location, 'Plug', slug='plug-1')
        self.bulb = DeviceHelper.create_device(location, 'Bulb', slug='bulb-1', kind='light_rgbcct')
        self.temp = DeviceHelper.create_device(location, 'Temp', slug='temp-1', kind='sensor', driver='w1')
        system(seen=timezone.now())
        cache('plug-1', state={'on': False})
        cache('bulb-1', state={'on': True, 'brightness': 40, 'mode': 'cct', 'ct': 2700, 'rgb': [255, 0, 0]})
        cache('temp-1', telemetry={'temperature_c': 21.5})

    def post(self, slug, **fields):
        return self.client.post(reverse('devices:device_set', args=(slug,)), fields)

    def sent(self):
        return [(m.topic, json.loads(m.payload), m.retain) for m in self.broker.published]

    def test_switch(self):
        response = self.post('plug-1', on='true')
        self.assertEqual(self.sent(), [('home/plug-1/set', {'on': True}, False)])
        self.assertContains(response, 'Sent – waiting for the device')
        self.assertContains(response, 'hx-trigger="load delay:1s"')

    def test_light(self):
        self.post('bulb-1', color='#00ff00')
        self.post('bulb-1', ct='4000')
        self.post('bulb-1', brightness='80')
        self.assertEqual([payload for _t, payload, _r in self.sent()],
                         [{'rgb': [0, 255, 0], 'mode': 'rgb'}, {'ct': 4000, 'mode': 'cct'}, {'brightness': 80}])

    def test_invalid_command_not_sent(self):
        cases = (('plug-1', {'brightness': '50'}, 'fields outside kind switch'),
                 ('bulb-1', {'brightness': '0'}, 'brightness=0'),
                 ('bulb-1', {'ct': '9000'}, 'ct=9000'),
                 ('temp-1', {'on': 'true'}, 'does not accept commands'),
                 ('plug-1', {}, 'nothing to change'),
                 ('plug-1', {'on': 'maybe'}, 'expected true or false'))
        for slug, fields, message in cases:
            with self.subTest(slug=slug, fields=fields):
                response = self.post(slug, **fields)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, message)
                self.assertContains(response, 'alert-danger')
        self.assertEqual(self.broker.published, [])

    def test_unavailable_device_not_sent(self):
        system(gateway='offline', seen=timezone.now())
        response = self.post('plug-1', on='true')
        self.assertContains(response, 'The device is unavailable (gateway offline)')
        self.assertEqual(self.broker.published, [])

    def test_broker_error(self):
        self.broker.error = 'connection refused'
        with self.assertLogs('devices.views', 'WARNING'):
            response = self.post('plug-1', on='true')
        self.assertContains(response, 'The command was not sent: connection refused')

    def test_post_only(self):
        response = self.client.get(reverse('devices:device_set', args=('plug-1',)))
        self.assertEqual(response.status_code, 405)

    def test_unknown_device(self):
        self.assertEqual(self.post('no-such', on='true').status_code, 404)

    def test_card_controls(self):
        card = self.client.get(reverse('devices:device_card', args=('plug-1',))).content.decode()
        self.assertIn(f'hx-post="{reverse("devices:device_set", args=("plug-1",))}"', card)
        self.assertIn('hx-vals=\'{"on": "true"}\'', card)        # wyłączone → przełącznik wysyła włącz
        self.assertNotIn('disabled', card)
        system(gateway='offline', seen=timezone.now())
        card = self.client.get(reverse('devices:device_card', args=('plug-1',))).content.decode()
        self.assertIn('disabled', card)                          # niedostępne – przełącznik wyłączony


class ConfirmationTests(LoggedInTestCase):
    """Karta po wysłaniu polecenia odpytuje co 1 s, aż `state` je potwierdzi (najwyżej 5 razy)."""

    def setUp(self):
        super().setUp()
        DeviceHelper.create_device(LocationHelper.create_location('room'), 'Plug', slug='plug-1')
        system(seen=timezone.now())
        cache('plug-1', state={'on': False})

    def card(self, cmd, attempt):
        url = reverse('devices:device_card', args=('plug-1',))
        return self.client.get(url, {'cmd': cmd, 'try': attempt}).content.decode()

    def refresh_query(self, card):
        start = card.index('hx-get="') + len('hx-get="')
        return parse_qs(urlsplit(card[start:card.index('"', start)].replace('&amp;', '&')).query)

    def test_waits_for_state(self):
        card = self.card('{"on":true}', 1)
        self.assertIn('Sent – waiting for the device', card)
        self.assertEqual(self.refresh_query(card)['try'], ['2'])

    def test_confirmed(self):
        cache('plug-1', state={'on': True})
        card = self.card('{"on":true}', 2)
        self.assertNotIn('hx-get=', card)
        self.assertNotIn('waiting for the device', card)

    def test_no_confirmation(self):
        card = self.card('{"on":true}', 5)
        self.assertIn('No confirmation from the device', card)
        self.assertNotIn('hx-get=', card)

    def test_invalid_parameters(self):
        for cmd, attempt in (('{not json', 1), ('[1]', 1), ('{"on":true}', 0), ('{"on":true}', 9)):
            with self.subTest(cmd=cmd, attempt=attempt):
                card = self.card(cmd, attempt)
                self.assertNotIn('hx-get=', card)


class CsrfTests(BrokerTestMixin, TestCase):
    """HTMX wysyła token CSRF w nagłówku X-CSRFToken (hx-headers na <body>)."""

    def setUp(self):
        super().setUp()
        DeviceHelper.create_device(LocationHelper.create_location('room'), 'Plug', slug='plug-1')
        system(seen=timezone.now())
        cache('plug-1', state={'on': False})
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(User.objects.create_user('user'))
        self.url = reverse('devices:device_set', args=('plug-1',))

    def test_header_token(self):
        page = self.client.get(reverse('devices:device', args=('plug-1',)))
        self.assertContains(page, 'X-CSRFToken')
        token = self.client.cookies[settings.CSRF_COOKIE_NAME].value
        response = self.client.post(self.url, {'on': 'true'}, headers={'X-CSRFToken': token, 'HX-Request': 'true'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.broker.published), 1)

    def test_without_token(self):
        with self.assertLogs('django.security.csrf', 'WARNING'):
            response = self.client.post(self.url, {'on': 'true'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.broker.published, [])
