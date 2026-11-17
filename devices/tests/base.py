"""Wspólne pomoce testów: zalogowany klient, tworzenie lokalizacji i urządzeń."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.text import slugify

from ..models import Device, Location

User = get_user_model()


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


class LocationHelper:
    @staticmethod
    def create_location(name):
        return Location.objects.create(name=name)

    @staticmethod
    def get_context_locations(response):
        return response.context['locations']


class DeviceHelper:
    @staticmethod
    def create_device(location, name, slug=None, kind='switch', driver='shelly', params=None):
        """Urządzenie ze slugiem z nazwy; domyślnie gniazdko Shelly."""
        return Device.objects.create(
            location=location, name=name, slug=slug or slugify(name), kind=kind, driver=driver,
            params={'prefix': f'shelly/{slugify(name)}', 'component': 'switch:0'} if params is None else params,
        )
