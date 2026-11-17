"""UI reguł: lista z filtrem, formularz (pola stanu per rodzaj), włączanie, usuwanie, reguły na stronie urządzenia."""

from datetime import time
from unittest import mock

from django.urls import reverse

from ..models import Rule
from ..templatetags.devices_extras import days_label, next_run
from .base import DeviceHelper, LocationHelper, LoggedInTestCase
from .test_cards import system
from .test_schedule import local

RULES = reverse('devices:rule_list')
NEW = reverse('devices:rule_new')


class RuleTestCase(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.salon = LocationHelper.create_location('Salon')
        self.plug = DeviceHelper.create_device(self.salon, 'Plug', slug='plug-1')
        self.bulb = DeviceHelper.create_device(self.salon, 'Bulb', slug='bulb-1', kind='light_rgbcct')
        self.temp = DeviceHelper.create_device(self.salon, 'Temp', slug='temp-1', kind='sensor', driver='w1')

    def rule(self, device=None, at=time(18), state=None, days=(0, 1, 2, 3, 4, 5, 6), **fields):
        return Rule.objects.create(device=device or self.plug, days=list(days), time=at,
                                   target_state=state or {'on': True}, **fields)

    def post_form(self, url=NEW, **fields):
        data = {'device': self.plug.pk, 'time': '18:00', 'days': ['0', '1', '2', '3', '4'], 'power': 'true',
                'enabled': 'on', 'ct': '2700', 'color': '#ffffff'}
        data.update(fields)
        return self.client.post(url, data)


class RuleListTests(RuleTestCase):
    def test_cards(self):
        self.rule(name='Evening', days=(0, 1, 2, 3, 4))
        self.rule(self.bulb, time(22, 30), {'on': True, 'brightness': 10}, days=(5, 6))
        response = self.client.get(RULES)
        content = response.content.decode()
        self.assertContains(response, 'Evening')
        self.assertContains(response, '18:00')
        self.assertContains(response, 'Mon–Fri')
        self.assertContains(response, '22:30')
        self.assertContains(response, 'Weekend')
        self.assertContains(response, '10%')
        self.assertContains(response, 'Next: ')
        self.assertEqual(content.count('class="card h-100 rule-card'), 2)

    def test_filter_by_device(self):
        self.rule(name='Plug rule')
        self.rule(self.bulb, name='Bulb rule')
        response = self.client.get(RULES, {'device': 'bulb-1'})
        self.assertContains(response, 'Bulb rule')
        self.assertNotContains(response, 'Plug rule')
        self.assertContains(response, '<option value="bulb-1" selected>', html=False)
        # filtr bez czujników; nieznany slug – wszystkie reguły
        self.assertNotContains(response, 'value="temp-1"')
        self.assertContains(self.client.get(RULES, {'device': 'nope'}), 'Plug rule')
        # HTMX podmienia samą listę
        self.assertContains(response, 'hx-select="#rule-list"')

    def test_empty(self):
        self.assertContains(self.client.get(RULES), 'No rules yet.')

    def test_disabled_rule(self):
        self.rule(enabled=False)
        response = self.client.get(RULES)
        self.assertContains(response, 'Disabled')
        self.assertNotContains(response, 'Next: ')

    def test_menu(self):
        self.assertContains(self.client.get(RULES), f'href="{RULES}"')


class RuleFormTests(RuleTestCase):
    def test_new_with_device(self):
        response = self.client.get(NEW, {'device': 'bulb-1', 'next': '/en/devices/device/bulb-1/'})
        self.assertContains(response, f'<option value="{self.bulb.pk}" selected>', html=False)
        self.assertNotContains(response, 'Temp (Salon)')
        # wszystkie dni, „włącz” i „włączona” zaznaczone; pola światła
        self.assertEqual(response.content.decode().count('checked>'), 7 + 1 + 1)
        self.assertContains(response, 'name="brightness"')
        self.assertContains(response, 'value="/en/devices/device/bulb-1/"')

    def test_create_switch(self):
        response = self.post_form(power='false', name='Night', next='/en/devices/device/plug-1/')
        self.assertRedirects(response, '/en/devices/device/plug-1/', fetch_redirect_response=False)
        rule = Rule.objects.get()
        self.assertEqual((rule.name, rule.days, rule.time, rule.target_state, rule.enabled),
                         ('Night', [0, 1, 2, 3, 4], time(18), {'on': False}, True))

    def test_create_light(self):
        cases = (
            ({'power': 'true', 'brightness': '30', 'light_mode': 'cct', 'ct': '3000'},
             {'on': True, 'brightness': 30, 'mode': 'cct', 'ct': 3000}),
            ({'power': 'true', 'light_mode': 'rgb', 'color': '#ff0010'}, {'on': True, 'mode': 'rgb', 'rgb': [255, 0, 16]}),
            ({'power': '', 'brightness': '10'}, {'brightness': 10}),
            # wyłączenie ignoruje jasność i kolor
            ({'power': 'false', 'brightness': '30', 'light_mode': 'cct'}, {'on': False}),
        )
        for fields, expected in cases:
            with self.subTest(fields=fields):
                Rule.objects.all().delete()
                response = self.post_form(device=self.bulb.pk, **fields)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(Rule.objects.get().target_state, expected)

    def test_redirect_default_and_external_next(self):
        response = self.post_form(next='https://example.com/')
        self.assertRedirects(response, RULES, fetch_redirect_response=False)

    def test_invalid(self):
        cases = (
            ('days', {'days': []}, 'This field is required'),
            ('time', {'time': ''}, 'This field is required'),
            ('device', {'device': self.temp.pk}, 'Select a valid choice'),
            ('target_state', {'power': ''}, 'nothing to change'),
            ('ct', {'device': self.bulb.pk, 'light_mode': 'cct', 'ct': ''}, 'Enter the white temperature'),
            ('ct', {'device': self.bulb.pk, 'light_mode': 'cct', 'ct': '9000'}, 'less than or equal to 6500'),
        )
        for field, fields, message in cases:
            with self.subTest(field, fields=fields):
                response = self.post_form(**fields)
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context['form'].errors)
                self.assertContains(response, message)
        self.assertFalse(Rule.objects.exists())

    def test_conflict(self):
        self.rule(name='Evening on')
        response = self.post_form(power='false')
        self.assertContains(response, 'Rule &quot;Evening on&quot; sets a different state at the same time.')
        self.assertEqual(Rule.objects.count(), 1)

    def test_edit(self):
        rule = self.rule(self.bulb, time(6, 45), {'on': True, 'mode': 'rgb', 'rgb': [255, 0, 16]}, days=(5, 6))
        url = reverse('devices:rule_edit', args=(rule.pk,))
        response = self.client.get(url)
        form = response.context['form']
        self.assertEqual(form.days_selected, {5, 6})
        self.assertContains(response, 'value="06:45"')
        self.assertContains(response, 'value="#ff0010"')
        self.assertEqual((form['power'].value(), form['light_mode'].value()), ('true', 'rgb'))
        self.post_form(url, device=self.bulb.pk, power='false', days=['6'])
        rule.refresh_from_db()
        self.assertEqual((rule.target_state, rule.days), ({'on': False}, [6]))

    def test_cancel_url(self):
        response = self.client.get(NEW, {'next': 'javascript:alert(1)'})
        self.assertEqual(response.context['cancel_url'], RULES)
        response = self.client.get(NEW, {'next': '/en/devices/device/plug-1/'})
        self.assertEqual(response.context['cancel_url'], '/en/devices/device/plug-1/')

    def test_state_fields(self):
        url = reverse('devices:rule_state_fields')
        light = self.client.get(url, {'device': self.bulb.pk})
        self.assertContains(light, 'name="brightness"')
        self.assertContains(light, 'Keep on / off')
        switch = self.client.get(url, {'device': self.plug.pk})
        self.assertNotContains(switch, 'name="brightness"')
        self.assertNotContains(switch, 'Keep on / off')
        self.assertContains(switch, 'Turn off')
        for value in ('', 'x', self.temp.pk):
            with self.subTest(device=value):
                self.assertContains(self.client.get(url, {'device': value}), 'Choose a device first.')


class RuleActionTests(RuleTestCase):
    def test_toggle(self):
        rule = self.rule()
        url = reverse('devices:rule_toggle', args=(rule.pk,))
        response = self.client.post(url)
        rule.refresh_from_db()
        self.assertFalse(rule.enabled)
        self.assertContains(response, f'id="rule-{rule.pk}"')
        self.assertContains(response, 'Disabled')
        self.client.post(url)
        rule.refresh_from_db()
        self.assertTrue(rule.enabled)
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_delete_htmx(self):
        rule = self.rule()
        response = self.client.post(reverse('devices:rule_delete', args=(rule.pk,)), HTTP_HX_REQUEST='true')
        self.assertEqual((response.status_code, response.content), (200, b''))
        self.assertFalse(Rule.objects.exists())

    def test_delete_form(self):
        rule = self.rule()
        response = self.client.post(reverse('devices:rule_delete', args=(rule.pk,)),
                                    {'next': '/en/devices/device/plug-1/'})
        self.assertRedirects(response, '/en/devices/device/plug-1/', fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('devices:rule_delete', args=(rule.pk,))).status_code, 405)


class DevicePageRulesTests(RuleTestCase):
    def test_rules_section(self):
        self.rule(name='Evening')
        self.rule(self.bulb, name='Other device')
        response = self.client.get(reverse('devices:device', args=('plug-1',)))
        self.assertContains(response, 'Evening')
        self.assertNotContains(response, 'Other device')
        self.assertContains(response, f'{NEW}?device=plug-1&amp;next=')

    def test_sensor_without_rules(self):
        response = self.client.get(reverse('devices:device', args=('temp-1',)))
        self.assertNotContains(response, 'Add rule')


class LocationListSummaryTests(RuleTestCase):
    def test_counts(self):
        from .test_cards import cache
        from django.utils import timezone
        system(seen=timezone.now())
        cache('plug-1', state={'on': True})
        response = self.client.get(reverse('devices:location_list'))
        summary = response.context['location_summaries'][0]
        self.assertEqual((summary['devices'], summary['available']), (3, 1))
        self.assertContains(response, '3 devices')
        self.assertContains(response, '1 available')


class RuleFilterTests(RuleTestCase):
    def test_days_label(self):
        self.assertEqual(days_label([6, 0, 1, 2, 3, 4, 5]), 'Every day')
        self.assertEqual(days_label([0, 1, 2, 3, 4]), 'Mon–Fri')
        self.assertEqual(days_label([5, 6]), 'Weekend')
        self.assertEqual(days_label([2, 0]), 'Mon, Wed')

    def test_next_run(self):
        rule = Rule(days=[0, 3], time=time(18))
        cases = ((local(2026, 11, 16, 12, 0), 'today 18:00'),       # poniedziałek
                 (local(2026, 11, 16, 18, 0), 'Thu 18:00'),
                 (local(2026, 11, 18, 19, 0), 'tomorrow 18:00'))
        for now, expected in cases:
            with self.subTest(now=now), mock.patch('django.utils.timezone.now', return_value=now):
                self.assertEqual(next_run(rule), expected)
