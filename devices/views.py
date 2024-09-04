from django.http import HttpResponseRedirect
from django.shortcuts import render, get_object_or_404, get_list_or_404
from django.urls import reverse
from django.views import generic

from .models import Location, Device
from .device_helpers import DeviceConfig, RelayDeviceConfig
import gpiocontrol as gpio


class IndexView(generic.ListView):
    template_name = 'devices/index.html'
    context_object_name = 'locations'

    def get_queryset(self):
        return Location.objects.all()


class DeviceView(generic.DetailView):
    template_name = 'devices/device.html'
    model = Device

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['device_config'] = DeviceConfig.parse_device(context['device'])
        return context


class LocationView(generic.ListView):
    template_name = 'devices/location.html'

    def get_queryset(self):
        return

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        location_id = self.kwargs['location_id']
        devices = []
        for device in Device.objects.filter(location=self.kwargs['location_id']):
            devices.append(DeviceConfig.parse_device(device))
        context.update({
            'location_id': location_id,
            'location_name': get_object_or_404(Location, pk=location_id),
            'device_config_list': devices,
        })
        return context


def location_update(request, location_id):
    selected_location = get_object_or_404(Location, pk=location_id)
    devices = get_list_or_404(Device, location=location_id)
    for device in devices:
        try:
            value = request.POST[f'device_{device.id}']
        except KeyError:
            continue
        else:
            device.value = value
            device.save()
    return HttpResponseRedirect(reverse('devices:location', args=(location_id,)))


def relay_update(request, device_id):
    next = request.POST.get('next', '/')
    try:
        device = Device.objects.get(pk=device_id)
    except Device.DoesNotExist:
        # todo: log error
        return HttpResponseRedirect(next)
    device_config = RelayDeviceConfig(device)
    new_state = device_config.active_state if request.POST.get('state', 'off') == 'on' else device_config.inactive_state
    device_config.setstate(new_state)
    return HttpResponseRedirect(next)
