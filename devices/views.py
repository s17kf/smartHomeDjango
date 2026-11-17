import logging

from django.shortcuts import get_object_or_404, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views import generic
from django.views.decorators.http import require_POST

from . import control, mqtt
from . import status as device_status
from .kinds import InvalidCommand
from .models import Location, Device

log = logging.getLogger(__name__)


class LocationListView(generic.ListView):
    template_name = 'devices/location_list.html'
    context_object_name = 'locations'

    def get_queryset(self):
        return Location.objects.all()


class FavouritesView(generic.ListView):
    template_name = 'devices/favourites.html'
    context_object_name = 'favourites_devices'

    def get_queryset(self):
        return Device.objects.none()


def _location_context(location_id):
    location = get_object_or_404(Location, pk=location_id)
    devices = Device.objects.filter(location=location).order_by('name')
    return {'location': location, 'statuses': device_status.statuses(devices)}


def location(request, location_id):
    return render(request, 'devices/location.html', _location_context(location_id))


def location_cards(request, location_id):
    """Karty urządzeń lokalizacji – fragment odświeżany przez HTMX."""
    return render(request, 'devices/cards/list.html', _location_context(location_id))


def device(request, slug):
    device_ = get_object_or_404(Device.objects.select_related('location'), slug=slug)
    return render(request, 'devices/device.html', {'device': device_, 'status': device_status.status(device_)})


def _card(request, status_, **context):
    return render(request, status_.template, {'status': status_, **context})


def device_card(request, slug):
    """Karta jednego urządzenia – fragment odświeżany przez HTMX.

    Z `cmd` i `try` w adresie (po wysłaniu polecenia): sprawdza, czy stan już
    je potwierdził; jeśli nie – karta odpytuje dalej co 1 s, po
    `CONFIRM_TRIES` próbach pokazuje „brak potwierdzenia”.
    """
    device_ = get_object_or_404(Device.objects.select_related('location'), slug=slug)
    status_ = device_status.status(device_)
    command, attempt = control.pending_command(request.GET)
    if command is None or device_.kind_spec.satisfied(status_.state, command):
        return _card(request, status_)
    if attempt >= control.CONFIRM_TRIES:
        return _card(request, status_, error=_('No confirmation from the device – check that it is available.'))
    return _card(request, status_, pending=True, refresh_url=control.refresh_url(device_, command, attempt + 1))


@require_POST
def device_set(request, slug):
    """Polecenie z karty → `home/<slug>/set`; odpowiedź – karta czekająca na potwierdzenie stanu."""
    device_ = get_object_or_404(Device.objects.select_related('location'), slug=slug)
    status_ = device_status.status(device_)
    try:
        command = device_.kind_spec.validate_set(control.parse_command(request.POST))
    except InvalidCommand as exc:
        return _card(request, status_, error=str(exc))
    # Polecenie do niedostępnego urządzenia przepada (bez kolejkowania) – nie wysyłamy.
    if not status_.available:
        return _card(request, status_, error=_('The device is unavailable (%(reason)s) – the command was not sent.')
                     % {'reason': status_.reason_label})
    try:
        control.send(device_, command)
    except mqtt.MqttError as exc:
        log.warning('%s: set not sent: %s', device_.slug, exc)
        return _card(request, status_, error=_('The command was not sent: %(error)s') % {'error': exc})
    return _card(request, status_, pending=True, refresh_url=control.refresh_url(device_, command, 1))


def get_next_url(request):
    """Adres powrotu z formularza (`next`) – tylko w obrębie tej strony, inaczej `/`."""
    next_url = request.POST.get('next', '/')
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()},
                                       require_https=request.is_secure()):
        return next_url
    return '/'
