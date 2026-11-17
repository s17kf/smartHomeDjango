from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponse
from django.shortcuts import resolve_url


class HtmxLoginRedirectMiddleware:
    """Wygasła sesja przy żądaniu HTMX → przejście całej strony na logowanie.

    `LoginRequiredMiddleware` odpowiada przekierowaniem na stronę logowania.
    HTMX podąża za nim w tle i wstawiłby formularz logowania do fragmentu
    (np. odświeżanej karty urządzenia). Zamiast tego odpowiedź z `HX-Redirect`:
    przeglądarka przechodzi na logowanie, a po nim wraca na bieżącą stronę
    (`HX-Current-URL`), nie na adres fragmentu. Musi być przed
    `LoginRequiredMiddleware` (obejmuje jego odpowiedź).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (request.headers.get('HX-Request') == 'true' and response.status_code == 302
                and urlsplit(response.url).path == resolve_url(settings.LOGIN_URL)):
            page = urlsplit(request.headers.get('HX-Current-URL', '')).path or '/'
            redirect = HttpResponse()
            redirect['HX-Redirect'] = redirect_to_login(page).url
            return redirect
        return response
