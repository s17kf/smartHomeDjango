from django.shortcuts import get_object_or_404, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import generic

from . import status as device_status
from .models import Location, Device


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


def device_card(request, slug):
    """Karta jednego urządzenia – fragment odświeżany przez HTMX."""
    device_ = get_object_or_404(Device.objects.select_related('location'), slug=slug)
    status_ = device_status.status(device_)
    return render(request, status_.template, {'status': status_})


def get_next_url(request):
    """Adres powrotu z formularza (`next`) – tylko w obrębie tej strony, inaczej `/`."""
    next_url = request.POST.get('next', '/')
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()},
                                       require_https=request.is_secure()):
        return next_url
    return '/'
