import os
import runpy
from unittest import mock

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from smartHomeSite import settings as project_settings

from .base import User


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
