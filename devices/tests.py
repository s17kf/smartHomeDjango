import os
import re
import runpy
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.exceptions import ImproperlyConfigured
from django.templatetags.static import static
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from smartHomeSite import settings as project_settings

from . import urls as devices_urls
from .models import Device, Location
from .views import get_next_url

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
    def create_device(location, name, device_type=Device.DeviceType.RELAY):
        return Device.objects.create(location=location, name=name, type=device_type, config_file='')


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


class LocationViewTests(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.location = LocationHelper.create_location('room')

    def get_location_response(self, location_id):
        return self.client.get(reverse('devices:location', args=(location_id,)))

    def test_location_not_exist(self):
        response = self.get_location_response(self.location.id + 1)
        self.assertEqual(response.status_code, 404)

    def test_no_devices(self):
        response = self.get_location_response(self.location.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['location'], self.location)
        self.assertQuerySetEqual(response.context['devices'], [])
        self.assertContains(response, 'No devices available in room.')

    def test_only_devices_of_location(self):
        device = DeviceHelper.create_device(self.location, 'lamp')
        DeviceHelper.create_device(LocationHelper.create_location('other room'), 'elsewhere')
        response = self.get_location_response(self.location.id)
        self.assertQuerySetEqual(response.context['devices'], [device])
        self.assertContains(response, self.location.name)
        self.assertContains(response, reverse('devices:device', args=(device.id,)))
        self.assertNotContains(response, 'elsewhere')


class DeviceViewTests(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.location = LocationHelper.create_location('room')
        self.device = DeviceHelper.create_device(self.location, 'device')

    def get_device_response(self, device_id):
        return self.client.get(reverse('devices:device', args=(device_id,)))

    def test_device_not_exist(self):
        response = self.get_device_response(self.device.id + 1)
        self.assertEqual(response.status_code, 404)

    def test_device_with_location(self):
        response = self.get_device_response(self.device.id)
        self.assertEqual(response.context['device'], self.device)
        self.assertContains(response, f'{self.device.name} ({self.location.name})')
        self.assertContains(response, reverse('devices:location', args=(self.location.id,)))


class GetNextUrlTests(SimpleTestCase):
    """Adres powrotu z formularza (`next`) – tylko w obrębie tej strony."""

    def next_url(self, data):
        return get_next_url(RequestFactory().post('/', data))

    def test_local_next(self):
        self.assertEqual(self.next_url({'next': '/en/devices/locations/'}), '/en/devices/locations/')

    def test_missing_next(self):
        self.assertEqual(self.next_url({}), '/')

    def test_external_next_ignored(self):
        for next_url in ('https://example.com/', '//example.com/', 'javascript:alert(1)'):
            with self.subTest(next=next_url):
                self.assertEqual(self.next_url({'next': next_url}), '/')


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

    def test_post_redirects_to_login(self):
        url = reverse('devices:location_list')
        response = self.client.post(url, {'next': '/'})
        self.assertRedirects(response, login_url(url), fetch_redirect_response=False)


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
