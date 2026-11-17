"""Reguły i nadpisania: walidacja modeli `Rule` i `Override`, zmiana rodzaju urządzenia z regułami."""

from datetime import time

from django.core.exceptions import ValidationError
from django.test import TestCase

from ..models import Override, Rule
from .base import DeviceHelper, LocationHelper
from .test_schedule import MONDAY, TUESDAY, WARM_30, local


class RuleValidationTests(TestCase):
    def setUp(self):
        location = LocationHelper.create_location('room')
        self.plug = DeviceHelper.create_device(location, 'plug')
        self.bulb = DeviceHelper.create_device(location, 'bulb', kind='light_rgbcct')
        self.temp = DeviceHelper.create_device(location, 'temp', kind='sensor', driver='w1')

    def rule(self, device=None, days=(MONDAY,), at=time(8), state=None, **fields):
        return Rule(device=device or self.plug, days=list(days), time=at,
                    target_state={'on': True} if state is None else state, **fields)

    def assert_error(self, rule, field, message=''):
        with self.assertRaises(ValidationError) as caught:
            rule.full_clean()
        self.assertIn(field, caught.exception.message_dict)
        self.assertIn(message, ' '.join(caught.exception.message_dict[field]))

    def test_valid(self):
        rule = self.rule(days=(4, 0, 2))
        rule.full_clean()
        self.assertEqual(rule.days, [0, 2, 4])
        self.rule(self.bulb, state=WARM_30).full_clean()
        self.rule(self.bulb, state={'brightness': 10}).full_clean()

    def test_days(self):
        for days in ((), (7,), (-1,), (1, 1), ('1',), (True,)):
            with self.subTest(days=days):
                self.assert_error(self.rule(days=days), 'days', '0–6')
        self.assert_error(Rule(device=self.plug, days={'mon': 1}, time=time(8), target_state={'on': True}), 'days')

    def test_target_state_per_kind(self):
        self.assert_error(self.rule(state={'on': True, 'brightness': 30}), 'target_state', 'brightness')
        self.assert_error(self.rule(self.bulb, state={'rgb': [255, 0, 0]}), 'target_state', '"mode": "rgb"')
        self.assert_error(self.rule(state=[True]), 'target_state', 'JSON object')

    def test_sensor_has_no_rules(self):
        self.assert_error(self.rule(self.temp), 'device', 'do not accept rules')

    def test_conflict_at_the_same_time(self):
        self.rule(name='Morning').save()
        self.assert_error(self.rule(state={'on': False}), '__all__', 'Morning')
        # ten sam stan, inna pora, inny dzień, inne urządzenie – wolno
        self.rule().full_clean()
        self.rule(at=time(8, 1), state={'on': False}).full_clean()
        self.rule(days=(TUESDAY,), state={'on': False}).full_clean()
        self.rule(self.bulb, state={'on': False}).full_clean()

    def test_conflict_with_disabled_rule(self):
        # włączenie reguły nie przechodzi przez formularz, więc wyłączone też się liczą
        self.rule(enabled=False).save()
        self.assert_error(self.rule(state={'on': False}), '__all__', 'same time')

    def test_edit_does_not_conflict_with_itself(self):
        rule = self.rule()
        rule.save()
        rule.target_state = {'on': False}
        rule.full_clean()


class OverrideValidationTests(TestCase):
    def test_state_per_kind(self):
        location = LocationHelper.create_location('room')
        plug = DeviceHelper.create_device(location, 'plug')
        until = local(2026, 11, 16, 12)
        Override(device=plug, state={'on': True}, previous_state={'on': False}, until=until).full_clean()
        for field, values in (('state', {'state': {'brightness': 5}, 'previous_state': {'on': False}}),
                              ('previous_state', {'state': {'on': True}, 'previous_state': {}})):
            with self.subTest(field), self.assertRaises(ValidationError) as caught:
                Override(device=plug, until=until, **values).full_clean()
            self.assertIn(field, caught.exception.message_dict)


class DeviceKindChangeTests(TestCase):
    def test_kind_change_with_rules(self):
        location = LocationHelper.create_location('room')
        plug = DeviceHelper.create_device(location, 'plug')
        plug.kind = 'light_rgbcct'
        plug.full_clean()
        plug.kind = 'switch'
        Rule.objects.create(device=plug, days=[MONDAY], time=time(8), target_state={'on': True})
        plug.kind = 'light_rgbcct'
        with self.assertRaises(ValidationError) as caught:
            plug.full_clean()
        self.assertIn('kind', caught.exception.message_dict)
