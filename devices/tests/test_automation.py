"""Reguły i nadpisania w workerze (`devices/automation.py`): kiedy worker wysyła `set`.

Tabela `SCHEDULE_CASES` (`test_schedule.py`) dla kroku workera – `set` wysłany
albo nie przy danym stanie w cache – i maszyna stanów: ponowienia,
potwierdzenie, zmiany ręczne, restart, nadpisanie.
"""

import logging
from datetime import time, timedelta
from unittest import mock

from django.test import TestCase

from .. import automation
from ..kinds import KINDS
from ..models import AutomationState, Device, Override, Rule, SystemStatus
from .base import DeviceHelper, LocationHelper
from .test_cards import cache, system
from .test_schedule import EVERY_DAY, OFF, ON, SCHEDULE_CASES, local

LIGHT_OFF = {'on': False, 'brightness': 30, 'mode': 'cct', 'ct': 2700, 'rgb': [255, 255, 255]}
CACHED_STATES = {
    'switch': (ON, OFF),
    'light_rgbcct': (LIGHT_OFF, {**LIGHT_OFF, 'on': True},
                     {'on': True, 'brightness': 10, 'mode': 'rgb', 'ct': 4000, 'rgb': [255, 0, 0]}),
}


def checked(at):
    """Koniec poprzedniego kroku workera (`SystemStatus.rules_checked_at`)."""
    SystemStatus.objects.filter(pk=1).update(rules_checked_at=at)


class AutomationTestCase(TestCase):
    def setUp(self):
        # INFO automatyzacji tylko tam, gdzie test go sprawdza (assertLogs)
        logger = logging.getLogger('devices.automation')
        self.addCleanup(logger.setLevel, logger.level)
        logger.setLevel(logging.WARNING)
        self.location = LocationHelper.create_location('room')
        self.plug = DeviceHelper.create_device(self.location, 'plug', slug='plug-1')
        self.sent = []

    def publish(self, slug, command):
        self.sent.append((slug, command))

    def step(self, now, state=None, availability='online'):
        """Krok workera w chwili `now`: świeży heartbeat, opcjonalnie nowy stan w cache."""
        system(seen=now)
        if state is not None or availability != 'online':
            cache('plug-1', availability=availability, state=state, ts=now)
        automation.step(self.publish, now)

    def start(self, at, state=OFF):
        """Worker działa do chwili `at`, urządzenie w stanie `state`."""
        system(seen=at)
        checked(at)
        cache('plug-1', state=state, ts=at)

    def take_sent(self):
        sent, self.sent = self.sent, []
        return sent

    def rule(self, at=time(8), state=ON, device=None, **fields):
        return Rule.objects.create(device=device or self.plug, days=list(EVERY_DAY), time=at,
                                   target_state=state, **fields)

    def override(self, state, created_at, until, previous=OFF):
        return Override.objects.create(device=self.plug, state=state, previous_state=previous,
                                       created_at=created_at, until=until)

    def auto(self, device=None):
        return AutomationState.objects.get(device=device or self.plug)


class ScheduleTableTests(AutomationTestCase):
    """`SCHEDULE_CASES` w kroku workera bez zapisanego stanu: `set`, chyba że cache już spełnia stan."""

    def test_cases(self):
        devices = {'switch': self.plug,
                   'light_rgbcct': DeviceHelper.create_device(self.location, 'bulb', kind='light_rgbcct')}
        for case in SCHEDULE_CASES:
            device = devices[case.kind]
            kind = KINDS[case.kind]
            for cached in CACHED_STATES[case.kind]:
                with self.subTest(case.name, cached=cached):
                    for model in (Rule, Override, AutomationState):
                        model.objects.all().delete()
                    for r in case.rules:
                        r.rule(device=device).save()
                    if case.override:
                        case.override.override(device=device).save()
                    system(seen=case.now)
                    checked(case.start)
                    cache(device.slug, state=cached, ts=case.now)
                    self.sent = []
                    automation.step(self.publish, case.now)
                    if case.expected is None or kind.satisfied(cached, case.expected):
                        self.assertEqual(self.sent, [])
                    else:
                        self.assertEqual(self.sent, [(device.slug, case.expected)])
                    self.assertEqual(SystemStatus.get().rules_checked_at, case.now)
                    # wygasłe nadpisanie usunięte po wyliczeniu stanu
                    if case.override and case.now >= case.override.until:
                        self.assertFalse(Override.objects.exists())


class RuleTests(AutomationTestCase):
    def test_rule_fires_once(self):
        self.rule()
        self.start(local(2026, 11, 16, 7, 59, 55))
        with self.assertLogs('devices.automation', 'INFO') as logs:
            self.step(local(2026, 11, 16, 8, 0))
        self.assertEqual(self.take_sent(), [('plug-1', ON)])
        self.assertIn('plug-1: rule "08:00" → {"on":true}', ''.join(logs.output))
        self.step(local(2026, 11, 16, 8, 0, 5), state=ON)
        self.assertEqual(self.auto().outcome, AutomationState.CONFIRMED)
        self.step(local(2026, 11, 16, 8, 0, 10))
        self.assertEqual(self.take_sent(), [])

    def test_already_in_state(self):
        self.rule(time(23), OFF)
        self.start(local(2026, 11, 16, 22, 59, 55), state=OFF)
        self.step(local(2026, 11, 16, 23, 0))
        self.assertEqual(self.take_sent(), [])
        self.assertEqual(self.auto().outcome, AutomationState.CONFIRMED)

    def test_manual_change_stays_until_next_rule(self):
        self.rule(time(18), name='Evening')
        self.start(local(2026, 11, 16, 17, 59, 55))
        self.step(local(2026, 11, 16, 18, 0))
        self.step(local(2026, 11, 16, 18, 0, 5), state=ON)
        # ręczne wyłączenie (UI, przycisk) – worker nie cofa
        for minutes in (60, 120, 300):
            self.step(local(2026, 11, 16, 18, 0) + timedelta(minutes=minutes), state=OFF)
        self.assertEqual(self.take_sent(), [('plug-1', ON)])
        # ta sama reguła następnego dnia – znów `set`, choć stan docelowy ten sam
        self.step(local(2026, 11, 17, 17, 59, 55))
        self.step(local(2026, 11, 17, 18, 0))
        self.assertEqual(self.take_sent(), [('plug-1', ON)])

    def test_rule_added_after_its_time(self):
        self.start(local(2026, 11, 16, 8, 30))
        self.rule()
        self.step(local(2026, 11, 16, 8, 30, 5))
        self.assertEqual(self.take_sent(), [])
        self.assertFalse(AutomationState.objects.exists())

    def test_disabled_rule(self):
        self.rule(enabled=False)
        self.start(local(2026, 11, 16, 7, 59, 55))
        self.step(local(2026, 11, 16, 8, 0))
        self.assertEqual(self.take_sent(), [])

    def test_first_start_without_checked_time(self):
        # pierwszy start workera – bez nadrabiania reguł sprzed niego
        self.rule()
        system(seen=local(2026, 11, 16, 12, 0))
        cache('plug-1', state=OFF)
        self.step(local(2026, 11, 16, 12, 0))
        self.assertEqual(self.take_sent(), [])
        self.assertEqual(SystemStatus.get().rules_checked_at, local(2026, 11, 16, 12, 0))

    def test_checked_time_without_touching_updated_at(self):
        # `updated_at` stanu systemu oznacza zmianę dla UI – krok co 5 s jej nie udaje
        self.start(local(2026, 11, 16, 12, 0))
        before = SystemStatus.get().updated_at
        automation.step(self.publish, local(2026, 11, 16, 12, 0, 5))
        status = SystemStatus.get()
        self.assertEqual((status.rules_checked_at, status.updated_at), (local(2026, 11, 16, 12, 0, 5), before))


class DeliveryTests(AutomationTestCase):
    """Ponowienia co minutę (najwyżej 5), tylko przy dostępnym urządzeniu, do potwierdzenia."""

    def setUp(self):
        super().setUp()
        self.rule()
        self.start(local(2026, 11, 16, 7, 59, 55))
        self.at = local(2026, 11, 16, 8, 0)

    def test_retries_until_given_up(self):
        for minute in range(5):
            self.step(self.at + timedelta(minutes=minute))
            self.assertEqual(self.take_sent(), [('plug-1', ON)], minute)
            self.step(self.at + timedelta(minutes=minute, seconds=30))
            self.assertEqual(self.take_sent(), [])
        self.assertEqual(self.auto().attempts, 5)
        with self.assertLogs('devices.automation', 'WARNING') as logs:
            self.step(self.at + timedelta(minutes=5))
        self.assertIn('no confirmation', logs.output[0])
        self.assertEqual(self.auto().outcome, AutomationState.FAILED)
        self.step(self.at + timedelta(minutes=10))
        self.assertEqual(self.take_sent(), [])
        # następne zdarzenie – od nowa
        Rule.objects.create(device=self.plug, days=list(EVERY_DAY), time=time(9), target_state=OFF)
        self.step(local(2026, 11, 16, 9, 0), state=ON)
        self.assertEqual(self.take_sent(), [('plug-1', OFF)])
        self.assertEqual(self.auto().attempts, 1)

    def test_confirmed_after_retry(self):
        self.step(self.at)
        self.step(self.at + timedelta(minutes=1))
        self.assertEqual(len(self.take_sent()), 2)
        self.step(self.at + timedelta(minutes=1, seconds=5), state=ON)
        auto = self.auto()
        self.assertEqual((auto.outcome, auto.attempts), (AutomationState.CONFIRMED, 2))
        self.step(self.at + timedelta(minutes=2))
        self.assertEqual(self.take_sent(), [])

    def test_only_when_available(self):
        # gateway nie działał w chwili reguły – `set` po powrocie, bez straconych prób
        self.step(self.at, availability='offline')
        self.step(self.at + timedelta(minutes=10), availability='offline')
        self.assertEqual(self.take_sent(), [])
        self.assertEqual(self.auto().attempts, 0)
        self.step(self.at + timedelta(minutes=20), state=OFF)
        self.assertEqual(self.take_sent(), [('plug-1', ON)])

    def test_stale_state_of_unavailable_device_does_not_confirm(self):
        self.step(self.at, state=ON, availability='offline')
        self.assertEqual(self.auto().outcome, AutomationState.PENDING)


class RestartTests(AutomationTestCase):
    """Koniec sprawdzonego przedziału w bazie: po restarcie tylko najnowsza przegapiona reguła."""

    def setUp(self):
        super().setUp()
        self.rule(time(18))
        self.rule(time(23), OFF)

    def test_restart_without_missed_rule(self):
        AutomationState.objects.create(device=self.plug, desired=ON, reason='rule',
                                       changed_at=local(2026, 11, 16, 18, 0), outcome=AutomationState.CONFIRMED,
                                       sent_at=local(2026, 11, 16, 18, 0), attempts=1)
        # ręczne wyłączenie przed restartem zostaje
        self.start(local(2026, 11, 16, 19, 0), state=OFF)
        self.step(local(2026, 11, 16, 19, 0, 30))
        self.assertEqual(self.take_sent(), [])

    def test_missed_rule(self):
        self.start(local(2026, 11, 16, 17, 0))
        self.step(local(2026, 11, 16, 18, 20))
        self.assertEqual(self.take_sent(), [('plug-1', ON)])

    def test_only_latest_missed_rule(self):
        self.start(local(2026, 11, 16, 17, 0), state=ON)
        self.step(local(2026, 11, 16, 23, 30))
        self.assertEqual(self.take_sent(), [('plug-1', OFF)])

    def test_pending_retries_continue(self):
        AutomationState.objects.create(device=self.plug, desired=ON, reason='rule',
                                       changed_at=local(2026, 11, 16, 18, 0), sent_at=local(2026, 11, 16, 18, 0),
                                       attempts=1)
        self.start(local(2026, 11, 16, 18, 0, 30))
        self.step(local(2026, 11, 16, 18, 0, 35))
        self.assertEqual(self.take_sent(), [])
        self.step(local(2026, 11, 16, 18, 1))
        self.assertEqual(self.take_sent(), [('plug-1', ON)])
        self.assertEqual(self.auto().attempts, 2)


class OverrideTests(AutomationTestCase):
    def test_already_sent_by_view(self):
        # widok wysłał `set` sam, stan zdążył się zmienić – worker tylko potwierdza
        self.start(local(2026, 11, 16, 12, 0), state=ON)
        self.override(ON, local(2026, 11, 16, 12, 0), local(2026, 11, 16, 12, 30))
        self.step(local(2026, 11, 16, 12, 0, 5))
        self.assertEqual(self.take_sent(), [])
        self.assertEqual(self.auto().outcome, AutomationState.CONFIRMED)
        self.step(local(2026, 11, 16, 12, 10), state=OFF)
        self.assertEqual(self.take_sent(), [])

    def test_rule_waits_until_override_end(self):
        self.rule(time(18), name='Evening')
        self.start(local(2026, 11, 16, 17, 50), state=OFF)
        self.override(OFF, local(2026, 11, 16, 17, 50), local(2026, 11, 16, 18, 30))
        self.step(local(2026, 11, 16, 17, 50, 5))
        self.step(local(2026, 11, 16, 18, 0))
        self.assertEqual(self.take_sent(), [])
        with self.assertLogs('devices.automation', 'INFO') as logs:
            self.step(local(2026, 11, 16, 18, 30))
        self.assertEqual(self.take_sent(), [('plug-1', ON)])
        self.assertIn('override ended, rule "Evening"', ''.join(logs.output))
        self.assertFalse(Override.objects.exists())

    def test_end_restores_previous_state(self):
        self.start(local(2026, 11, 16, 12, 0), state=ON)
        self.override(ON, local(2026, 11, 16, 12, 0), local(2026, 11, 16, 12, 30), previous=OFF)
        self.step(local(2026, 11, 16, 12, 0, 5))
        self.step(local(2026, 11, 16, 12, 30))
        self.assertEqual(self.take_sent(), [('plug-1', OFF)])
        self.assertFalse(Override.objects.exists())
        self.step(local(2026, 11, 16, 12, 30, 5), state=OFF)
        self.assertEqual(self.auto().outcome, AutomationState.CONFIRMED)
        # potem urządzeniem bez reguł worker nie steruje
        self.step(local(2026, 11, 16, 13, 0), state=ON)
        self.assertEqual(self.take_sent(), [])

    def test_end_retried(self):
        self.start(local(2026, 11, 16, 12, 0), state=ON)
        self.override(ON, local(2026, 11, 16, 12, 0), local(2026, 11, 16, 12, 30), previous=OFF)
        self.step(local(2026, 11, 16, 12, 30))
        self.step(local(2026, 11, 16, 12, 31))
        self.assertEqual(self.take_sent(), [('plug-1', OFF), ('plug-1', OFF)])

    def test_cancelled_override(self):
        # anulowanie z UI przesuwa `until` na teraz
        self.start(local(2026, 11, 16, 12, 0), state=ON)
        self.override(ON, local(2026, 11, 16, 12, 0), local(2026, 11, 16, 12, 30), previous=OFF)
        self.step(local(2026, 11, 16, 12, 0, 5))
        Override.objects.update(until=local(2026, 11, 16, 12, 10))
        self.step(local(2026, 11, 16, 12, 10))
        self.assertEqual(self.take_sent(), [('plug-1', OFF)])

    def test_renewed_with_other_state(self):
        self.start(local(2026, 11, 16, 12, 0), state=ON)
        self.override(ON, local(2026, 11, 16, 12, 0), local(2026, 11, 16, 12, 30))
        self.step(local(2026, 11, 16, 12, 0, 5))
        Override.objects.update(state=OFF, until=local(2026, 11, 16, 13, 0))
        self.step(local(2026, 11, 16, 12, 10))
        self.assertEqual(self.take_sent(), [('plug-1', OFF)])

    def test_renewed_override_kept(self):
        self.start(local(2026, 11, 16, 12, 0), state=ON)
        self.override(ON, local(2026, 11, 16, 11, 30), local(2026, 11, 16, 12, 0))
        status = automation.device_status.status(Device.objects.select_related('override').get(pk=self.plug.pk))
        # przedłużone z UI między odczytem a usunięciem wygasłego
        Override.objects.update(until=local(2026, 11, 16, 13, 0))
        automation._device_step(status, self.publish, local(2026, 11, 16, 12, 0), local(2026, 11, 16, 12, 0))
        self.assertTrue(Override.objects.exists())


class FailureTests(AutomationTestCase):
    def test_kind_changed_outside_admin(self):
        # admin nie pozwala zmienić rodzaju urządzenia z regułami; tu zmiana z pominięciem walidacji
        bulb = DeviceHelper.create_device(self.location, 'bulb', kind='light_rgbcct')
        self.rule(device=bulb, state={'on': True, 'brightness': 30})
        Device.objects.filter(pk=bulb.pk).update(kind='switch')
        self.start(local(2026, 11, 16, 7, 59, 55))
        cache('bulb', state=OFF)
        with self.assertLogs('devices.automation', 'WARNING') as logs:
            self.step(local(2026, 11, 16, 8, 0))
        self.assertIn('does not fit kind switch', logs.output[0])
        self.assertEqual(self.take_sent(), [])
        self.assertEqual(self.auto(bulb).outcome, AutomationState.FAILED)

    def test_one_device_failing_does_not_stop_others(self):
        bulb = DeviceHelper.create_device(self.location, 'bulb', kind='light_rgbcct')
        self.rule(device=bulb, state={'on': True})
        self.rule()
        self.start(local(2026, 11, 16, 7, 59, 55))
        cache('bulb', state=LIGHT_OFF)
        deliver = automation._deliver

        def failing(status, *args):
            if status.device.slug == 'bulb':
                raise RuntimeError('database error')
            return deliver(status, *args)

        with mock.patch.object(automation, '_deliver', failing), self.assertLogs('devices.automation', 'ERROR'):
            self.step(local(2026, 11, 16, 8, 0))
        self.assertEqual(self.take_sent(), [('plug-1', ON)])
