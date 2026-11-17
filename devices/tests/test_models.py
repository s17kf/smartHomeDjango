from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from .. import kinds
from ..models import Device, Location
from .base import DeviceHelper, LocationHelper


class DeviceFieldsTests(TestCase):
    """Pola urządzenia z kontraktu MQTT: slug, rodzaj, sterownik, parametry."""

    @classmethod
    def setUpTestData(cls):
        cls.location = LocationHelper.create_location('room')

    def device(self, **fields):
        values = {'location': self.location, 'name': 'plug', 'slug': 'plug-1', 'kind': 'switch',
                  'driver': 'shelly', 'params': {'prefix': 'shelly/plug1', 'component': 'switch:0'}}
        values.update(fields)
        return Device(**values)

    def assert_invalid(self, field, **fields):
        with self.assertRaises(ValidationError) as caught:
            self.device(**fields).full_clean()
        self.assertIn(field, caught.exception.message_dict)

    def test_valid(self):
        for slug in ('plug-1', 'a', 'temp-salon', 'x' * 50):
            with self.subTest(slug=slug):
                self.device(slug=slug).full_clean()

    def test_invalid_slug(self):
        # wzorzec [a-z0-9]+(-[a-z0-9]+)*, najwyżej 50 znaków (ADR 0004)
        for slug in ('Plug-1', 'plug_1', 'plug--1', '-plug', 'plug-', 'plug 1', 'gniazdko-ąę', 'x' * 51, ''):
            with self.subTest(slug=slug):
                self.assert_invalid('slug', slug=slug)

    def test_slug_unique(self):
        self.device().save()
        with self.assertRaises(IntegrityError):
            self.device(name='other').save()

    def test_invalid_kind(self):
        for kind in ('relay', 'relay-periodic', ''):
            with self.subTest(kind=kind):
                self.assert_invalid('kind', kind=kind)

    def test_kinds_match_contract(self):
        self.assertEqual([value for value, _label in Device._meta.get_field('kind').choices],
                         ['switch', 'light_rgbcct', 'sensor'])
        self.assertIs(self.device(kind='sensor').kind_spec, kinds.SENSOR)

    def test_invalid_driver(self):
        for driver in ('Shelly', 'shelly-gen2', 'shelly/1', ''):
            with self.subTest(driver=driver):
                self.assert_invalid('driver', driver=driver)

    def test_params(self):
        for params in ({}, {'topic': 'nous1'}, {'sensor': '28-00000a99077c', 'interval_s': 60}):
            with self.subTest(params=params):
                self.device(params=params).full_clean()

    def test_params_not_object(self):
        for params in ([], 'shelly/plug1', 1):
            with self.subTest(params=params):
                self.assert_invalid('params', params=params)

    def test_params_without_secrets(self):
        # params trafiają do retained `config` w brokerze – bez haseł
        for params in ({'password': 'x'}, {'mqtt': {'Token': 'x'}}, {'list': [{'pass': 1}]},
                       {'client_secret': 'x'}):
            with self.subTest(params=params):
                self.assert_invalid('params', params=params)


class DeviceSlugImmutableTests(TestCase):
    """Slug wyznacza tematy MQTT – po utworzeniu się nie zmienia."""

    def setUp(self):
        self.device = DeviceHelper.create_device(LocationHelper.create_location('room'), 'plug')

    def test_save_other_fields(self):
        self.device.name = 'renamed'
        self.device.params = {'prefix': 'shelly/plug2', 'component': 'switch:0'}
        self.device.save()
        self.device.full_clean()

    def test_save_rejects_slug_change(self):
        self.device.slug = 'plug-2'
        with self.assertRaises(ValueError):
            self.device.save()
        self.assertEqual(Device.objects.get(pk=self.device.pk).slug, 'plug')

    def test_clean_rejects_slug_change(self):
        self.device.slug = 'plug-2'
        with self.assertRaises(ValidationError) as caught:
            self.device.full_clean()
        self.assertIn('slug', caught.exception.message_dict)


class LocationTests(TestCase):
    def test_name_unique(self):
        LocationHelper.create_location('room')
        with self.assertRaises(IntegrityError):
            LocationHelper.create_location('room')

    def test_delete_removes_devices(self):
        location = LocationHelper.create_location('room')
        DeviceHelper.create_device(location, 'plug')
        location.delete()
        self.assertFalse(Device.objects.exists())
        self.assertFalse(Location.objects.exists())
