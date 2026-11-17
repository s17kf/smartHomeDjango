from datetime import datetime, timedelta, timezone as dt_timezone

from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone, translation

from .. import status as device_status
from ..models import DeviceState, SystemStatus
from ..templatetags.devices_extras import ago, reading, rgb_css
from .base import DeviceHelper, LocationHelper, LoggedInTestCase, User

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=dt_timezone.utc)


def system(gateway='online', connected=True, seen=NOW):
    SystemStatus.objects.update_or_create(pk=1, defaults={
        'gateway_status': gateway, 'worker_connected': connected, 'worker_seen_at': seen})


def cache(slug, availability='online', state=None, telemetry=None, ts=NOW):
    DeviceState.objects.update_or_create(slug=slug, defaults={
        'availability': availability, 'state': state, 'state_ts': ts if state is not None else None,
        'telemetry': telemetry, 'telemetry_ts': ts if telemetry is not None else None})


class AvailabilityTests(TestCase):
    """Dostępne tylko przy żywym workerze, gatewayu online i `availability` = online (ADR 0009)."""

    def setUp(self):
        self.device = DeviceHelper.create_device(LocationHelper.create_location('room'), 'plug')

    def reason(self):
        return device_status.status(self.device, now=NOW).reason

    def test_available(self):
        system()
        cache('plug')
        self.assertEqual(self.reason(), 'ok')
        self.assertTrue(device_status.status(self.device, now=NOW).available)

    def test_worker(self):
        cache('plug')
        self.assertEqual(self.reason(), 'worker')          # worker jeszcze nie działał
        system(seen=NOW - timedelta(seconds=91))
        self.assertEqual(self.reason(), 'worker')          # heartbeat nieaktualny
        system(seen=NOW - timedelta(seconds=90))
        self.assertEqual(self.reason(), 'ok')
        system(connected=False)
        self.assertEqual(self.reason(), 'worker')          # rozłączony z brokerem

    def test_gateway(self):
        cache('plug')
        for gateway in ('offline', ''):
            with self.subTest(gateway=gateway):
                system(gateway=gateway)
                self.assertEqual(self.reason(), 'gateway')

    def test_device(self):
        system()
        self.assertEqual(self.reason(), 'unknown')         # brak wiersza w cache
        cache('plug', availability='')
        self.assertEqual(self.reason(), 'unknown')
        cache('plug', availability='offline')
        self.assertEqual(self.reason(), 'device')

    def test_page_view_does_not_write(self):
        device_status.status(self.device)
        self.assertFalse(SystemStatus.objects.exists())


class CardsTests(LoggedInTestCase):
    """Karty urządzeń per rodzaj na stronie lokalizacji."""

    def setUp(self):
        super().setUp()
        self.location = LocationHelper.create_location('room')
        self.plug = DeviceHelper.create_device(self.location, 'Plug', slug='plug-1')
        self.bulb = DeviceHelper.create_device(self.location, 'Bulb', slug='bulb-1', kind='light_rgbcct',
                                               params={'prefix': 'shelly/bulb1', 'component': 'rgbcct:0'})
        self.temp = DeviceHelper.create_device(self.location, 'Thermometer', slug='temp-1', kind='sensor',
                                               driver='w1', params={'sensor': '28-00000a99077c'})
        system(seen=timezone.now())
        self.page_url = reverse('devices:location', args=(self.location.id,))

    def card(self, slug):
        response = self.client.get(reverse('devices:device_card', args=(slug,)))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_switch(self):
        cache('plug-1', state={'on': True}, telemetry={'power_w': 4.5, 'energy_wh': 9, 'voltage_v': 234.8})
        card = self.card('plug-1')
        self.assertIn('ON', card)
        self.assertIn('4.5 W', card)
        self.assertIn('9 Wh', card)
        self.assertNotIn('234.8', card)       # napięcie tylko na stronie urządzenia
        self.assertIn('data-available="true"', card)

    def test_switch_off_and_unknown(self):
        cache('plug-1', state={'on': False})
        self.assertIn('OFF', self.card('plug-1'))
        DeviceState.objects.all().delete()
        self.assertIn('State unknown', self.card('plug-1'))

    def test_light(self):
        cache('bulb-1', state={'on': True, 'brightness': 40, 'mode': 'cct', 'ct': 2700, 'rgb': [255, 0, 0]})
        card = self.card('bulb-1')
        self.assertIn('40%', card)
        self.assertIn('White 2700 K', card)
        cache('bulb-1', state={'on': True, 'brightness': 80, 'mode': 'rgb', 'ct': 2700, 'rgb': [255, 0, 0]})
        self.assertIn('background-color: rgb(255, 0, 0)', self.card('bulb-1'))

    def test_sensor(self):
        cache('temp-1', telemetry={'temperature_c': 23.75}, ts=timezone.now() - timedelta(minutes=3))
        card = self.card('temp-1')
        self.assertIn('23.75 °C', card)
        self.assertIn('3\xa0minutes ago', card)

    def test_unavailable(self):
        cache('plug-1', availability='offline', state={'on': True})
        card = self.card('plug-1')
        self.assertIn('unavailable', card)
        self.assertIn('device offline', card)
        self.assertIn('opacity-50', card)        # ostatni znany stan, przygaszony
        self.assertIn('data-available="false"', card)

    def test_location_page(self):
        response = self.client.get(self.page_url)
        for slug in ('plug-1', 'bulb-1', 'temp-1'):
            self.assertContains(response, f'id="device-{slug}"')
        # odświeżanie fragmentu co 10 s, tylko przy widocznej karcie przeglądarki
        self.assertContains(response, f'hx-get="{reverse("devices:location_cards", args=(self.location.id,))}"')
        self.assertContains(response, "every 10s [document.visibilityState === 'visible']")

    def test_cards_fragment(self):
        response = self.client.get(reverse('devices:location_cards', args=(self.location.id,)))
        self.assertContains(response, 'id="device-plug-1"')
        self.assertNotContains(response, '<html')

    def test_htmx_instead_of_jquery(self):
        response = self.client.get(self.page_url)
        self.assertContains(response, 'devices/vendor/htmx/htmx.min.js')
        self.assertNotContains(response, 'jquery')
        self.assertContains(response, 'hx-headers=\'{"X-CSRFToken": "')


class HtmxLoginRedirectTests(TestCase):
    """Wygasła sesja przy żądaniu HTMX – przejście całej strony na logowanie (HX-Redirect)."""

    def setUp(self):
        self.location = LocationHelper.create_location('room')
        self.page = reverse('devices:location', args=(self.location.id,))
        self.fragment = reverse('devices:location_cards', args=(self.location.id,))

    def test_htmx_request(self):
        response = self.client.get(self.fragment, headers={
            'HX-Request': 'true', 'HX-Current-URL': f'https://example.lan{self.page}'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['HX-Redirect'], f"{reverse('login')}?next={self.page}")
        self.assertEqual(response.content, b'')

    def test_plain_request_unchanged(self):
        response = self.client.get(self.fragment)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('HX-Redirect', response)

    def test_logged_in_htmx_request_unchanged(self):
        client = Client()
        client.force_login(User.objects.create_user('user'))
        response = client.get(self.fragment, headers={'HX-Request': 'true'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('HX-Redirect', response)


class RgbCssTests(SimpleTestCase):
    def test_valid(self):
        self.assertEqual(rgb_css([255, 0, 10]), 'rgb(255, 0, 10)')

    def test_invalid(self):
        # stan z brokera trafia do atrybutu style – tylko liczby 0–255
        for value in ([256, 0, 0], [1, 2], [True, 0, 0], ['red', 0, 0], '255, 0, 0); x: url(a)', None,
                      [1.5, 0, 0]):
            with self.subTest(value=value):
                self.assertEqual(rgb_css(value), '')


class ReadingFilterTests(SimpleTestCase):
    def test_reading(self):
        for value, shown in ((4.5, '4.5'), (9, '9'), (23.75, '23.75'), (0.1 + 0.2, '0.3'), (14.124, '14.12'),
                             (35.0, '35'), (True, True), ('x', 'x')):
            with self.subTest(value=value):
                self.assertEqual(reading(value), shown)

    def test_reading_polish(self):
        with translation.override('pl'):
            self.assertEqual(reading(23.75), '23,75')

    def test_ago(self):
        with translation.override('en'):
            self.assertEqual(ago(timezone.now() - timedelta(hours=6, minutes=35)), '6\xa0hours ago')
        self.assertEqual(ago(None), '')
