from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from .. import urls as devices_urls
from ..views import get_next_url
from .base import DeviceHelper, LocationHelper, LoggedInTestCase, User, login_url


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
        self.assertEqual(self.get_location_response(self.location.id + 1).status_code, 404)
        url = reverse('devices:location_cards', args=(self.location.id + 1,))
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_no_devices(self):
        response = self.get_location_response(self.location.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['location'], self.location)
        self.assertEqual(response.context['statuses'], [])
        self.assertContains(response, 'No devices available in room.')

    def test_only_devices_of_location(self):
        device = DeviceHelper.create_device(self.location, 'lamp')
        DeviceHelper.create_device(LocationHelper.create_location('other room'), 'elsewhere')
        response = self.get_location_response(self.location.id)
        self.assertEqual([s.device for s in response.context['statuses']], [device])
        self.assertContains(response, self.location.name)
        self.assertContains(response, reverse('devices:device', args=(device.slug,)))
        self.assertNotContains(response, 'elsewhere')


class DeviceViewTests(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.location = LocationHelper.create_location('room')
        self.device = DeviceHelper.create_device(self.location, 'device')

    def test_device_not_exist(self):
        for name in ('device', 'device_card'):
            with self.subTest(name):
                response = self.client.get(reverse(f'devices:{name}', args=('no-such-device',)))
                self.assertEqual(response.status_code, 404)

    def test_device_with_location(self):
        # adres urządzenia po slugu
        response = self.client.get(reverse('devices:device', args=(self.device.slug,)))
        self.assertEqual(response.context['device'], self.device)
        self.assertContains(response, f'{self.device.name} ({self.location.name})')
        self.assertContains(response, reverse('devices:location', args=(self.location.id,)))
        self.assertContains(response, 'home/device/…')


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
