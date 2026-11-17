from django.test import SimpleTestCase

from ..kinds import KINDS, LIGHT_RGBCCT, SENSOR, SWITCH, InvalidCommand


class ValidateSetTests(SimpleTestCase):
    """Polecenia `set` według rodzaju – te same pola i zakresy co w gatewayu (`payloads.md`)."""

    def assert_valid(self, kind, command):
        result = kind.validate_set(command)
        self.assertEqual(result, command)
        self.assertIsNot(result, command)

    def assert_invalid(self, kind, command, message=None):
        with self.assertRaises(InvalidCommand) as caught:
            kind.validate_set(command)
        if message:
            self.assertIn(message, str(caught.exception))

    def test_switch(self):
        self.assert_valid(SWITCH, {'on': True})
        self.assert_valid(SWITCH, {'on': False})
        for command in ({'on': 1}, {'on': 'true'}, {'on': None}):
            with self.subTest(command=command):
                self.assert_invalid(SWITCH, command)
        self.assert_invalid(SWITCH, {'on': True, 'brightness': 5}, 'brightness')
        self.assert_invalid(SWITCH, {}, 'nothing to change')

    def test_not_object(self):
        for command in ([], 'on', None, True):
            with self.subTest(command=command):
                self.assert_invalid(SWITCH, command)

    def test_light_valid(self):
        for command in ({'on': True}, {'brightness': 1}, {'brightness': 100},
                        {'mode': 'rgb', 'rgb': [255, 0, 0]}, {'mode': 'cct', 'ct': 2700},
                        {'ct': 6500, 'transition': 1.5}, {'on': False, 'transition': 0}):
            with self.subTest(command=command):
                self.assert_valid(LIGHT_RGBCCT, command)

    def test_light_invalid(self):
        for command in ({'brightness': 0}, {'brightness': 101}, {'brightness': 50.5},
                        {'mode': 'white'}, {'rgb': [0, 0, 256]}, {'rgb': [1, 2]},
                        {'rgb': [True, 0, 0]}, {'ct': 2699}, {'ct': 6501},
                        {'on': True, 'transition': -1}, {'on': True, 'transition': float('nan')},
                        {'on': True, 'power': 5}):
            with self.subTest(command=command):
                self.assert_invalid(LIGHT_RGBCCT, command)

    def test_transition_alone(self):
        # sam czas przejścia niczego nie zmienia
        self.assert_invalid(LIGHT_RGBCCT, {'transition': 2}, 'nothing to change')

    def test_sensor_rejects_commands(self):
        self.assert_invalid(SENSOR, {'on': True}, 'does not accept commands')
        self.assert_invalid(SENSOR, {})


class ValidateTargetTests(SimpleTestCase):
    """Stan docelowy reguły i nadpisania: polecenie `set`, kolor i biel z właściwym trybem."""

    def test_valid(self):
        for kind, state in ((SWITCH, {'on': False}),
                            (LIGHT_RGBCCT, {'on': True, 'brightness': 30, 'mode': 'cct', 'ct': 2700}),
                            (LIGHT_RGBCCT, {'brightness': 10}),
                            (LIGHT_RGBCCT, {'on': True, 'mode': 'rgb', 'rgb': [255, 0, 0], 'transition': 2})):
            with self.subTest(state=state):
                self.assertEqual(kind.validate_target(state), state)

    def test_invalid(self):
        cases = (
            (SWITCH, {'on': 'yes'}, 'on='),
            (LIGHT_RGBCCT, {'on': True, 'rgb': [255, 0, 0]}, '"mode": "rgb"'),
            (LIGHT_RGBCCT, {'on': True, 'mode': 'rgb', 'ct': 3000}, '"mode": "cct"'),
            (SENSOR, {'on': True}, 'does not accept rules'),
        )
        for kind, state, message in cases:
            with self.subTest(state=state), self.assertRaisesMessage(InvalidCommand, message):
                kind.validate_target(state)


class KindTests(SimpleTestCase):
    def test_kinds(self):
        self.assertEqual(list(KINDS), ['switch', 'light_rgbcct', 'sensor'])

    def test_rules_and_rest_state(self):
        # stan spoczynkowy – po nadpisaniu, gdy stan sprzed niego jest nieznany; czujnik nie ma reguł
        self.assertTrue(SWITCH.accepts_rules)
        self.assertTrue(LIGHT_RGBCCT.accepts_rules)
        self.assertFalse(SENSOR.accepts_rules)
        for kind in (SWITCH, LIGHT_RGBCCT):
            with self.subTest(kind=kind.name):
                self.assertEqual(kind.validate_set(kind.rest_state), {'on': False})
