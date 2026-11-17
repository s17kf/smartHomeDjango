import re

from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.urls import reverse

from .base import LoggedInTestCase


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
