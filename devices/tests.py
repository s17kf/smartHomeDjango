import json
import os
import re
import runpy
import tempfile
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone as dt_timezone
from io import StringIO
from unittest import mock

import gpiocontrol as gpio
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.templatetags.static import static
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from smartHomeSite import settings as project_settings

from . import urls as devices_urls
from .device_helpers import RelayPeriodicDeviceConfig
from .models import Device, Location, RelayPeriodicDay, RelayPeriodicManualActivation, RelayPeriodicPeriod

User = get_user_model()

# Plik konfiguracyjny, którego nie ma – urządzenie bez dostępnego stanu.
MISSING_CONFIG_FILE = '/nonexistent/device.json'


def utc(*args):
    """Chwila w UTC – testy ustawiają `timezone.now()` niezależnie od strefy hosta."""
    return datetime(*args, tzinfo=dt_timezone.utc)


def local(*args):
    """Chwila w czasie lokalnym (`TIME_ZONE`), w którym liczony jest harmonogram."""
    return timezone.make_aware(datetime(*args))


def frozen_now(now):
    return mock.patch('django.utils.timezone.now', return_value=now)


def login_url(next_url):
    """Adres, na który LoginRequiredMiddleware przekierowuje niezalogowanego użytkownika."""
    return f"{reverse('login')}?next={next_url}"


class LoggedInTestCase(TestCase):
    """Klient zalogowany jako zwykły użytkownik (bez uprawnień admina) – widoki UI wymagają zalogowania."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('user')

    def setUp(self):
        self.client.force_login(self.user)


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


class RelayDeviceTestCase(LoggedInTestCase):
    """Przekaźniki z plikiem konfiguracyjnym i zamockowanym GPIO (stan: wyłączone) w lokalizacji `room`."""

    PIN = 17

    def setUp(self):
        super().setUp()
        for name, kwargs in (('get', {'return_value': gpio.State.LOW}), ('set', {})):
            patcher = mock.patch(f'gpiocontrol.{name}', **kwargs)
            setattr(self, f'gpio_{name}', patcher.start())
            self.addCleanup(patcher.stop)
        self.location = LocationHelper.create_location('room')

    def create_relay(self, name, device_type, pin=PIN):
        """Przekaźnik włączany stanem wysokim na pinie `pin`."""
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as config_file:
            json.dump({'pinNumber': pin, 'activeState': gpio.State.HIGH.value}, config_file)
        self.addCleanup(os.unlink, config_file.name)
        return Device.objects.create(location=self.location, name=name, config_file=config_file.name,
                                     type=device_type)

    def create_relay_without_config(self, name):
        return Device.objects.create(location=self.location, name=name, config_file=MISSING_CONFIG_FILE,
                                     type=Device.DeviceType.RELAY)

    def create_device_of_each_type(self):
        """Po jednym urządzeniu każdego rodzaju obsługiwanego przez strony, także bez dostępnego stanu."""
        return [
            self.create_relay('relay', Device.DeviceType.RELAY, pin=self.PIN),
            self.create_relay('periodic', Device.DeviceType.RELAY_PERIODIC, pin=self.PIN + 1),
            self.create_relay_without_config('no config'),
            DeviceHelper.create_device(self.location, 'unknown type'),
        ]


class LocationListViewTests(LoggedInTestCase):

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


class LocationViewTests(RelayDeviceTestCase):
    def get_location_response(self, location_id):
        # przekaźnik bez pliku konfiguracyjnego wypisuje błąd na stdout
        with redirect_stdout(StringIO()):
            return self.client.get(reverse('devices:location', args=(location_id,)))

    @staticmethod
    def get_context_devices(response):
        return [device_config.device for device_config in response.context['device_config_list']]

    def test_location_not_exist(self):
        invalid_id = self.location.id + 1
        response = self.get_location_response(invalid_id)
        self.assertEqual(response.status_code, 404)

    def test_no_devices(self):
        response = self.get_location_response(self.location.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['location_name'], self.location)
        self.assertEqual(self.get_context_devices(response), [])

    def test_only_devices_of_location(self):
        device = self.create_relay('lamp', Device.DeviceType.RELAY)
        DeviceHelper.create_device(LocationHelper.create_location('other room'), 'elsewhere')
        response = self.get_location_response(self.location.id)
        self.assertEqual(self.get_context_devices(response), [device])
        self.assertContains(response, self.location.name)
        self.assertNotContains(response, 'elsewhere')

    def test_device_of_each_type(self):
        devices = self.create_device_of_each_type()
        response = self.get_location_response(self.location.id)
        self.assertEqual(response.status_code, 200)
        self.assertQuerySetEqual(self.get_context_devices(response), devices, ordered=False)
        for device in devices:
            with self.subTest(device=device.name):
                self.assertContains(response, reverse('devices:device', args=(device.id,)))


class DeviceViewTests(RelayDeviceTestCase):
    def get_device_response(self, device_id):
        # przekaźnik bez pliku konfiguracyjnego wypisuje błąd na stdout
        with redirect_stdout(StringIO()):
            return self.client.get(reverse('devices:device', args=(device_id,)))

    def setUp(self):
        super().setUp()
        self.device = DeviceHelper.create_device(self.location, 'device')

    def test_device_not_exist(self):
        invalid_id = self.device.id + 1
        response = self.get_device_response(invalid_id)
        self.assertEqual(response.status_code, 404)

    def test_device_with_location(self):
        response = self.get_device_response(self.device.id)
        self.assertEqual(DeviceHelper.get_context_device_details(response), self.device)
        self.assertContains(response, f'{self.device.name} ({self.location.name})')
        self.assertContains(response, reverse('devices:location', args=(self.location.id,)))

    def test_device_of_each_type(self):
        for device in self.create_device_of_each_type():
            with self.subTest(device=device.name):
                response = self.get_device_response(device.id)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['device_config'].device, device)

    def test_device_page_loads_status_scripts(self):
        response = self.get_device_response(self.device.id)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'devices/vendor/jquery/jquery.min.js')
        self.assertContains(response, 'const RELAY_UPDATE_URL')
        self.assertContains(response, 'devices/js/device_status_update.js')


class RelayUpdateTests(LoggedInTestCase):
    def get_relay_update_url(self, device_id):
        return reverse('devices:relay_update', args=(device_id,))

    def test_device_not_exist(self):
        response = self.client.post(self.get_relay_update_url(1), {'state': 'on'})
        self.assertEqual(response.json(), {'status': 'error', 'message': 'Device not found'})

    def test_get_not_allowed(self):
        response = self.client.get(self.get_relay_update_url(1))
        self.assertEqual(response.json(), {'status': 'error', 'message': 'Invalid request method'})


class PeriodicDeviceTestCase(RelayDeviceTestCase):
    """Urządzenie `relay-periodic` (pin `PIN`, stan: wyłączone)."""

    def setUp(self):
        super().setUp()
        self.device = self.create_relay('periodic', Device.DeviceType.RELAY_PERIODIC)

    def config_at(self, now):
        with frozen_now(now):
            return RelayPeriodicDeviceConfig(self.device)

    def run_command_at(self, now):
        """Jedno wykonanie komendy workera `relays_periodic_update`; zwraca jej wyjście."""
        output = StringIO()
        with frozen_now(now):
            call_command('relays_periodic_update', stdout=output)
        return output.getvalue()


@dataclass(frozen=True)
class ScheduleCase:
    """Harmonogram w chwili `now` (czas lokalny) i oczekiwany stan przekaźnika."""
    name: str
    now: datetime
    active: bool
    days: tuple = ()
    periods: tuple = ()
    manual_end: datetime | None = None


# 16.11.2026 to poniedziałek.
MONDAY = RelayPeriodicDay.DaysChoices.MONDAY
MORNING = ((time(8, 0), time(9, 0)),)
OVERNIGHT = ((time(22, 0), time(6, 0)),)

SCHEDULE_CASES = (
    ScheduleCase('no schedule', local(2026, 11, 16, 12, 0), False),
    # okres [begin, end): początek należy do okresu, koniec już nie
    ScheduleCase('inside period', local(2026, 11, 16, 8, 30), True, periods=MORNING),
    ScheduleCase('period begin', local(2026, 11, 16, 8, 0), True, periods=MORNING),
    ScheduleCase('period end', local(2026, 11, 16, 9, 0), False, periods=MORNING),
    ScheduleCase('before period', local(2026, 11, 16, 7, 59), False, periods=MORNING),
    ScheduleCase('second of periods', local(2026, 11, 16, 18, 30), True,
                 periods=MORNING + ((time(18, 0), time(19, 0)),)),
    # okres z końcem przed początkiem trwa przez północ
    ScheduleCase('overnight period, evening', local(2026, 11, 16, 23, 0), True, periods=OVERNIGHT),
    ScheduleCase('overnight period, morning', local(2026, 11, 16, 3, 0), True, periods=OVERNIGHT),
    ScheduleCase('overnight period begin', local(2026, 11, 16, 22, 0), True, periods=OVERNIGHT),
    ScheduleCase('overnight period end', local(2026, 11, 16, 6, 0), False, periods=OVERNIGHT),
    ScheduleCase('outside overnight period', local(2026, 11, 16, 12, 0), False, periods=OVERNIGHT),
    # aktywny dzień tygodnia: włączone przez całą dobę
    ScheduleCase('active day', local(2026, 11, 16, 12, 0), True, days=(MONDAY,)),
    ScheduleCase('active day begin', local(2026, 11, 16, 0, 0), True, days=(MONDAY,)),
    ScheduleCase('day before active day', local(2026, 11, 15, 23, 59), False, days=(MONDAY,)),
    ScheduleCase('day after active day', local(2026, 11, 17, 0, 0), False, days=(MONDAY,)),
    # ręczne włączenie trwa do `manual_end` (bez tej chwili), potem decyduje harmonogram
    ScheduleCase('manual activation', local(2026, 11, 16, 12, 0), True, manual_end=local(2026, 11, 16, 12, 30)),
    ScheduleCase('manual activation end', local(2026, 11, 16, 12, 30), False,
                 manual_end=local(2026, 11, 16, 12, 30)),
    ScheduleCase('expired manual activation', local(2026, 11, 16, 12, 0), False,
                 manual_end=local(2026, 11, 16, 11, 30)),
    ScheduleCase('expired manual activation, inside period', local(2026, 11, 16, 8, 30), True,
                 periods=MORNING, manual_end=local(2026, 11, 16, 8, 15)),
)


class ScheduleTests(PeriodicDeviceTestCase):
    """Stan przekaźnika z harmonogramu – tabela `SCHEDULE_CASES`.

    Tę samą tabelę sprawdzamy dla strony urządzenia (`RelayPeriodicDeviceConfig`)
    i komendy workera, bo każde z nich liczy harmonogram osobno. Tabela opisuje
    zachowanie, które ma przejść na reguły automatyzacji – zmiany semantyki
    zaczynamy od niej.
    """

    def set_schedule(self, case):
        self.device.relayperiodicday_set.all().delete()
        self.device.relayperiodicperiod_set.all().delete()
        RelayPeriodicManualActivation.objects.filter(device=self.device).delete()
        for day in case.days:
            self.device.relayperiodicday_set.create(day=day)
        for begin, end in case.periods:
            self.device.relayperiodicperiod_set.create(begin=begin, end=end)
        if case.manual_end:
            RelayPeriodicManualActivation.objects.create(device=self.device, end_time=case.manual_end)

    def test_device_config(self):
        for case in SCHEDULE_CASES:
            with self.subTest(case.name):
                self.set_schedule(case)
                config = self.config_at(case.now)
                active = (config.is_manual_activated() or config.is_active_day()
                          or config.current_period is not None)
                self.assertEqual(active, case.active)

    def test_command(self):
        expected_state = {True: gpio.State.HIGH, False: gpio.State.LOW}
        for case in SCHEDULE_CASES:
            # komenda zmienia stan tylko wtedy, gdy przekaźnik jest w innym niż oczekiwany
            for current_state in (gpio.State.LOW, gpio.State.HIGH):
                with self.subTest(case.name, current_state=current_state.name):
                    self.set_schedule(case)
                    self.gpio_get.return_value = current_state
                    self.gpio_set.reset_mock()
                    self.run_command_at(case.now)
                    if current_state == expected_state[case.active]:
                        self.gpio_set.assert_not_called()
                    else:
                        self.gpio_set.assert_called_once_with(self.PIN, expected_state[case.active])


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

    def test_invalid_minutes_keep_activation(self):
        end_time = utc(2026, 11, 16, 12, 0)
        RelayPeriodicManualActivation.objects.create(device=self.device, end_time=end_time)
        for minutes in ('0', '-5', 'abc', ''):
            with self.subTest(minutes=minutes):
                self.client.post(reverse('devices:periodic_relay_manual_activate', args=(self.device.id,)),
                                 {'minutes': minutes, 'next': '/'})
                self.assertEqual(RelayPeriodicManualActivation.objects.get(device=self.device).end_time, end_time)
        self.gpio_set.assert_not_called()

    def test_replaces_activation(self):
        RelayPeriodicManualActivation.objects.create(device=self.device, end_time=utc(2026, 11, 16, 12, 0))
        activation = self.activate(utc(2026, 11, 16, 11, 50), 30)
        self.assertEqual(activation.end_time, utc(2026, 11, 16, 12, 20))


class PeriodicRelayFormViewsTests(PeriodicDeviceTestCase):
    """Formularze harmonogramu: tylko POST, powrót (`next`) tylko na adres tej strony."""

    VIEW_NAMES = [pattern.name for pattern in devices_urls.urlpatterns
                  if pattern.name.startswith('periodic_relay_')]

    def post(self, view_name, data):
        # widoki wypisują część błędów na stdout
        with redirect_stdout(StringIO()):
            return self.client.post(reverse(f'devices:{view_name}', args=(self.device.id,)), data)

    def test_get_not_allowed(self):
        activation = RelayPeriodicManualActivation.objects.create(device=self.device,
                                                                  end_time=timezone.now() + timedelta(hours=1))
        for view_name in self.VIEW_NAMES:
            with self.subTest(view_name):
                response = self.client.get(reverse(f'devices:{view_name}', args=(self.device.id,)))
                self.assertEqual(response.status_code, 405)
        self.assertTrue(RelayPeriodicManualActivation.objects.filter(pk=activation.pk).exists())
        self.gpio_set.assert_not_called()

    def test_redirects_to_next(self):
        next_url = reverse('devices:location', args=(self.location.id,))
        for view_name in self.VIEW_NAMES:
            with self.subTest(view_name):
                response = self.post(view_name, {'next': next_url})
                self.assertRedirects(response, next_url, fetch_redirect_response=False)

    def test_external_next_ignored(self):
        for view_name in self.VIEW_NAMES:
            for next_url in ('https://example.com/', '//example.com/', 'javascript:alert(1)'):
                with self.subTest(view_name, next=next_url):
                    response = self.post(view_name, {'next': next_url})
                    self.assertRedirects(response, '/', fetch_redirect_response=False)

    def test_device_not_exist(self):
        next_url = reverse('devices:location', args=(self.location.id,))
        for view_name in self.VIEW_NAMES:
            with self.subTest(view_name):
                url = reverse(f'devices:{view_name}', args=(self.device.id + 1,))
                response = self.client.post(url, {'next': next_url, 'minutes': 30, 'day': 0})
                self.assertRedirects(response, next_url, fetch_redirect_response=False)
        self.assertFalse(RelayPeriodicManualActivation.objects.exists())
        self.assertFalse(RelayPeriodicDay.objects.exists())


class RelaysPeriodicUpdateCommandTests(PeriodicDeviceTestCase):
    """Komenda workera `relays_periodic_update` w czasie lokalnym."""

    def run_at(self, now):
        return self.run_command_at(now)

    def test_config_error_skips_device(self):
        Device.objects.create(location=self.location, name='broken', config_file=MISSING_CONFIG_FILE,
                              type=Device.DeviceType.RELAY_PERIODIC)
        RelayPeriodicPeriod.objects.create(device=self.device, begin=time(0, 0), end=time(1, 0))
        with redirect_stdout(StringIO()):
            output = self.run_at(utc(2026, 11, 15, 23, 30))
        self.assertIn('device: broken - config error', output)
        self.gpio_set.assert_called_once_with(self.PIN, gpio.State.HIGH)

    def test_gpio_error_does_not_stop_other_devices(self):
        other = self.create_relay('other', Device.DeviceType.RELAY_PERIODIC, pin=self.PIN + 1)
        for device in (self.device, other):
            RelayPeriodicPeriod.objects.create(device=device, begin=time(0, 0), end=time(1, 0))

        def fail_on_first_pin(pin, state):
            if pin == self.PIN:
                raise OSError('gpio error')

        self.gpio_set.side_effect = fail_on_first_pin
        with redirect_stdout(StringIO()):
            self.run_at(utc(2026, 11, 15, 23, 30))
        self.gpio_set.assert_has_calls([mock.call(self.PIN, gpio.State.HIGH),
                                        mock.call(self.PIN + 1, gpio.State.HIGH)], any_order=True)

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


class LoginRequiredTests(TestCase):
    """Bez zalogowania widoki przekierowują na stronę logowania i niczego nie zmieniają."""

    def test_devices_views_redirect_to_login(self):
        # wszystkie adresy aplikacji devices, także dodane w przyszłości
        for pattern in devices_urls.urlpatterns:
            args = [1] * len(pattern.pattern.converters)
            url = reverse(f'devices:{pattern.name}', args=args)
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertRedirects(response, login_url(url), fetch_redirect_response=False)

    def test_root_redirects_to_login(self):
        response = self.client.get('/en/')
        self.assertRedirects(response, login_url('/en/'), fetch_redirect_response=False)

    def test_admin_redirects_to_admin_login(self):
        # panel admina ma własne logowanie (wymaga is_staff), poza LoginRequiredMiddleware
        url = reverse('admin:index')
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('admin:login')}?next={url}", fetch_redirect_response=False)

    def test_post_has_no_effect(self):
        location = LocationHelper.create_location('room')
        device = DeviceHelper.create_device(location, 'device')
        url = reverse('devices:periodic_relay_add_active_day', args=(device.id,))
        response = self.client.post(url, {'day': 0, 'next': '/'})
        self.assertRedirects(response, login_url(url), fetch_redirect_response=False)
        self.assertFalse(RelayPeriodicDay.objects.exists())


class LoginViewTests(TestCase):
    PASSWORD = 'correct-horse-battery-staple'

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('user', password=cls.PASSWORD)

    def log_in(self, password=PASSWORD, **extra):
        return self.client.post(reverse('login'), {'username': 'user', 'password': password, **extra})

    def test_login_page_without_menu(self):
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="password"')
        self.assertNotContains(response, reverse('devices:location_list'))
        self.assertNotContains(response, reverse('logout'))

    def test_login_redirects_to_devices(self):
        response = self.log_in()
        self.assertRedirects(response, reverse('devices:main'), fetch_redirect_response=False)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_login_redirects_to_next(self):
        next_url = reverse('devices:location_list')
        response = self.log_in(next=next_url)
        self.assertRedirects(response, next_url)

    def test_login_ignores_external_next(self):
        response = self.log_in(next='https://example.com/')
        self.assertRedirects(response, reverse('devices:main'), fetch_redirect_response=False)

    def test_wrong_password(self):
        response = self.log_in(password='wrong')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'alert-danger')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_inactive_user_cannot_log_in(self):
        self.user.is_active = False
        self.user.save()
        response = self.log_in()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_logged_in_user_redirected_from_login_page(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('login'))
        self.assertRedirects(response, reverse('devices:main'), fetch_redirect_response=False)


class LogoutTests(LoggedInTestCase):
    def test_navbar_shows_user_and_logout(self):
        response = self.client.get(reverse('devices:location_list'))
        self.assertContains(response, self.user.get_username())
        self.assertContains(response, f'action="{reverse("logout")}"')

    def test_logout(self):
        response = self.client.post(reverse('logout'))
        self.assertRedirects(response, reverse('login'))
        url = reverse('devices:location_list')
        self.assertRedirects(self.client.get(url), login_url(url), fetch_redirect_response=False)

    def test_logout_requires_post(self):
        response = self.client.get(reverse('logout'))
        self.assertEqual(response.status_code, 405)
        self.assertIn('_auth_user_id', self.client.session)


def settings_from_env(**env):
    """Ustawienia projektu wczytane od nowa przy podanych zmiennych środowiskowych.

    Wartość None – zmienna nieustawiona. Pozostałe zmienne jak w środowisku testów.
    """
    environ = {name: value for name, value in os.environ.items() if name not in env}
    environ.update({name: value for name, value in env.items() if value is not None})
    with mock.patch.dict(os.environ, environ, clear=True):
        return runpy.run_path(project_settings.__file__)


HTTPS_SETTINGS = ('SECURE_PROXY_SSL_HEADER', 'SESSION_COOKIE_SECURE', 'CSRF_COOKIE_SECURE')


def https_settings(value):
    """Ustawienia zależne od DJANGO_HTTPS przy podanej wartości zmiennej."""
    namespace = settings_from_env(DJANGO_HTTPS=value)
    return {name: namespace[name] for name in HTTPS_SETTINGS}


class HttpsSettingsTests(SimpleTestCase):
    """DJANGO_HTTPS włącza razem zaufanie do nagłówka proxy i ciasteczka `Secure`."""

    def test_off_by_default(self):
        for value in (None, '', 'false'):
            with self.subTest(value=value):
                self.assertEqual(https_settings(value), {
                    'SECURE_PROXY_SSL_HEADER': None,
                    'SESSION_COOKIE_SECURE': False,
                    'CSRF_COOKIE_SECURE': False,
                })

    def test_on(self):
        self.assertEqual(https_settings('true'), {
            'SECURE_PROXY_SSL_HEADER': ('HTTP_X_FORWARDED_PROTO', 'https'),
            'SESSION_COOKIE_SECURE': True,
            'CSRF_COOKIE_SECURE': True,
        })

    def test_invalid_value(self):
        with self.assertRaises(ImproperlyConfigured):
            settings_from_env(DJANGO_HTTPS='https')


class HttpsBehindProxyTests(TestCase):
    """Logowanie przez HTTPS kończone na reverse proxy (Caddy) przy DJANGO_HTTPS=true.

    Proxy przekazuje żądanie po HTTP z nagłówkiem `X-Forwarded-Proto: https`
    i `Host` z przeglądarki (bez niego Django składa adres z portu serwera:
    `testserver:80`). Klient jak przeglądarka: sprawdzanie CSRF włączone, POST
    z nagłówkiem `Origin`.
    """

    PASSWORD = 'correct-horse-battery-staple'
    FROM_PROXY = {'Host': 'testserver', 'X-Forwarded-Proto': 'https'}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.enterClassContext(override_settings(**https_settings('true')))

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('user', password=cls.PASSWORD)

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def log_in(self):
        self.client.get(reverse('login'), headers=self.FROM_PROXY)
        token = self.client.cookies[settings.CSRF_COOKIE_NAME].value
        return self.client.post(
            reverse('login'),
            {'username': 'user', 'password': self.PASSWORD, 'csrfmiddlewaretoken': token},
            headers={**self.FROM_PROXY, 'Origin': 'https://testserver'},
        )

    def test_login(self):
        response = self.log_in()
        self.assertRedirects(response, reverse('devices:main'), fetch_redirect_response=False)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_cookies_secure(self):
        response = self.client.get(reverse('login'), headers=self.FROM_PROXY)
        self.assertTrue(response.cookies[settings.CSRF_COOKIE_NAME]['secure'])
        response = self.log_in()
        for name in (settings.SESSION_COOKIE_NAME, settings.CSRF_COOKIE_NAME):
            with self.subTest(cookie=name):
                self.assertTrue(response.cookies[name]['secure'])

    def test_login_rejected_without_proxy_header(self):
        # Powód tego ustawienia: bez niego Django widzi HTTP, a przeglądarka
        # wysyła `Origin: https://…` – kontrola CSRF odrzuca formularz.
        with self.settings(SECURE_PROXY_SSL_HEADER=None), \
                self.assertLogs('django.security.csrf', 'WARNING') as logs:
            response = self.log_in()
        self.assertEqual(response.status_code, 403)
        self.assertIn('Origin checking failed', logs.output[0])
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_plain_http_not_redirected(self):
        # Przekierowanie na HTTPS robi proxy. Żądanie bezpośrednio po HTTP
        # (np. healthcheck z kontenera) dostaje stronę, nie przekierowanie.
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.is_secure())


class LocalStaticFilesTests(LoggedInTestCase):
    """CSS i JS stron z repo (`{% static %}`), nie z CDN – UI działa bez internetu."""

    ASSET_URL = re.compile(r'<(?:link|script)\b[^>]*\b(?:href|src)="([^"]+)"')

    def assert_assets_local(self, response):
        urls = self.ASSET_URL.findall(response.content.decode())
        self.assertIn(static('devices/vendor/bootstrap/css/bootstrap.min.css'), urls)
        for url in urls:
            with self.subTest(url=url):
                self.assertTrue(url.startswith(static('')))
                self.assertIsNotNone(finders.find(url.removeprefix(static(''))))

    def test_devices_page(self):
        self.assert_assets_local(self.client.get(reverse('devices:location_list')))

    def test_login_page(self):
        self.client.logout()
        self.assert_assets_local(self.client.get(reverse('login')))
