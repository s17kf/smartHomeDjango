from django.shortcuts import get_object_or_404
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import generic

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


class DeviceView(generic.DetailView):
    template_name = 'devices/device.html'
    model = Device


class LocationView(generic.ListView):
    template_name = 'devices/location.html'
    context_object_name = 'devices'

    def get_queryset(self):
        self.location = get_object_or_404(Location, pk=self.kwargs['location_id'])
        return Device.objects.filter(location=self.location).order_by('name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['location'] = self.location
        return context


def get_next_url(request):
    """Adres powrotu z formularza (`next`) – tylko w obrębie tej strony, inaczej `/`."""
    next_url = request.POST.get('next', '/')
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()},
                                       require_https=request.is_secure()):
        return next_url
    return '/'
