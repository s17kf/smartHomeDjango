"""Zmiany kart przez SSE (`devices/events.py`, widok `device_events`)."""

from datetime import timedelta

from unittest import mock

from django.urls import reverse
from django.utils import timezone

from .. import events
from ..models import Override, SystemStatus
from .base import BrokerTestMixin, DeviceHelper, LocationHelper, LoggedInTestCase
from .test_cards import cache, system

EVENTS = reverse('devices:events')


def names(chunks):
    """Nazwy zdarzeń SSE (`ping` dla komentarza)."""
    result = []
    for chunk in chunks:
        if chunk.startswith(':'):
            result.append('ping')
        else:
            result.append(chunk.split('\n', 1)[0].removeprefix('event: '))
    return result


class SseEventTests(LoggedInTestCase):
    def test_format(self):
        self.assertEqual(events.sse_event('device-a', '<div>\n  x\n</div>'),
                         'event: device-a\ndata: <div>\ndata:   x\ndata: </div>\n\n')
        self.assertEqual(events.sse_event('x', ''), 'event: x\ndata: \n\n')


class CardStreamTests(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        location = LocationHelper.create_location('room')
        self.plug = DeviceHelper.create_device(location, 'Plug', slug='plug-1')
        self.bulb = DeviceHelper.create_device(location, 'Bulb', slug='bulb-1', kind='light_rgbcct')
        self.now = timezone.now()
        system(seen=self.now)
        cache('plug-1', state={'on': False})
        cache('bulb-1', state={'on': True, 'brightness': 40, 'mode': 'cct', 'ct': 2700, 'rgb': [255, 0, 0]})
        self.stream = events.CardStream([self.bulb, self.plug])

    def step(self, now_s, now=None):
        return names(self.stream.step(now_s, now or self.now))

    def test_all_cards_first(self):
        chunks = self.stream.step(0, self.now)
        self.assertEqual(names(chunks), ['device-bulb-1', 'device-plug-1'])
        self.assertIn('id="device-plug-1"', chunks[1])
        # linie danych z prefiksem, pusta linia kończy zdarzenie
        lines = chunks[1].split('\n')
        self.assertTrue(all(line.startswith('data: ') for line in lines[1:-2]))
        self.assertEqual(lines[-2:], ['', ''])

    def test_changes_and_ping(self):
        self.step(0)
        self.assertEqual(self.step(1), [])
        # zmiana stanu jednego urządzenia
        cache('plug-1', state={'on': True})
        self.assertEqual(self.step(2), ['device-plug-1'])
        self.assertEqual(self.step(3), [])
        # komentarz po PING_S bez zdarzeń
        self.assertEqual(self.step(2 + events.PING_S), ['ping'])
        self.assertEqual(self.step(3 + events.PING_S), [])

    def test_system_change_updates_all(self):
        self.step(0)
        SystemStatus.objects.filter(pk=1).update(gateway_status='offline')
        self.assertEqual(self.step(1), ['device-bulb-1', 'device-plug-1'])
        # heartbeat workera się zestarzał – bez zmiany w bazie
        self.assertEqual(self.step(2, self.now + timedelta(seconds=120)), ['device-bulb-1', 'device-plug-1'])

    def test_override_change(self):
        self.step(0)
        Override.objects.create(device=self.plug, state={'on': True}, previous_state={'on': False},
                                until=self.now + timedelta(seconds=30))
        self.assertEqual(self.step(1), ['device-plug-1'])
        # koniec nadpisania (bez zmiany w bazie)
        self.assertEqual(self.step(2, self.now + timedelta(seconds=30)), ['device-plug-1'])

    def test_full_refresh(self):
        self.step(0)
        self.assertEqual(self.step(events.FULL_REFRESH_S), ['device-bulb-1', 'device-plug-1'])


class StreamTests(LoggedInTestCase):
    def test_retry_steps_and_end(self):
        class Cards:
            calls = []

            def step(self, now_s):
                self.calls.append(now_s)
                return [f'step {now_s}\n\n']

        clock = [0.0]
        chunks = list(events.stream(Cards(), clock=lambda: clock[0],
                                    sleep=lambda s: clock.__setitem__(0, clock[0] + s)))
        self.assertEqual(chunks[0], f'retry: {events.RETRY_MS}\n\n')
        self.assertEqual(len(chunks), 1 + int(events.STREAM_S / events.POLL_S) + 1)
        self.assertEqual(chunks[-1], f'step {events.STREAM_S}\n\n')


class EventsViewTests(BrokerTestMixin, LoggedInTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(events, 'STREAM_S', 0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.location = LocationHelper.create_location('room')
        DeviceHelper.create_device(self.location, 'Plug', slug='plug-1')
        system(seen=timezone.now())
        cache('plug-1', state={'on': False})

    def chunks(self, response):
        """Cały strumień – skrócony do jednego kroku (`STREAM_S` = 0).

        Klient testowy po przeczytaniu całości zamyka odpowiedź bez
        close_old_connections(); przerwanie strumienia w połowie zamknęłoby na
        PostgreSQL połączenie transakcji testu.
        """
        return [chunk.decode() for chunk in response.streaming_content]

    def test_location_stream(self):
        response = self.client.get(EVENTS, {'location': self.location.id})
        self.assertEqual(response['Content-Type'], 'text/event-stream')
        self.assertEqual(response['Cache-Control'], 'no-cache')
        retry, card = self.chunks(response)
        self.assertEqual(retry, f'retry: {events.RETRY_MS}\n\n')
        self.assertTrue(card.startswith('event: device-plug-1\n'))
        self.assertIn('sse-swap="device-plug-1"', card)

    def test_device_stream(self):
        response = self.client.get(EVENTS, {'device': 'plug-1'})
        self.assertTrue(self.chunks(response)[1].startswith('event: device-plug-1\n'))

    def test_not_found(self):
        for params in ({}, {'location': 'x'}, {'location': self.location.id + 1}, {'device': 'nope'}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get(EVENTS, params).status_code, 404)

    def test_device_page(self):
        response = self.client.get(reverse('devices:device', args=('plug-1',)))
        self.assertContains(response, f'sse-connect="{EVENTS}?device=plug-1"')

    def test_pending_card_without_sse_swap(self):
        # „wysłano” – karta odpytuje sama, SSE nie zdejmuje oczekiwania
        response = self.client.post(reverse('devices:device_set', args=('plug-1',)), {'on': 'true'})
        self.assertContains(response, 'Sent – waiting for the device')
        self.assertNotContains(response, 'sse-swap=')
