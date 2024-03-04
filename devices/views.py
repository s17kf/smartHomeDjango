from django.http import HttpResponseRedirect
from django.shortcuts import render, get_object_or_404, get_list_or_404
from django.urls import reverse

from .models import Location, Device


# Create your views here.
def index(request):
    locations = Location.objects.all()
    context = {
        'locations': locations,
    }
    return render(request, 'devices/index.html', context)


def location(request, location_id):
    location_name = get_object_or_404(Location, pk=location_id).name

    devices = Device.objects.filter(location=location_id)
    context = {
        'location_id': location_id,
        'location_name': location_name,
        'devices': devices,
    }
    return render(request, 'devices/location.html', context)


def device_details(request, device_id):
    device = get_object_or_404(Device, pk=device_id)

    context = {
        'device': device,
    }
    return render(request, 'devices/device.html', context)


def location_update(request, location_id):
    selected_location = get_object_or_404(Location, pk=location_id)
    devices = get_list_or_404(Device, location=location_id)
    for device in devices:
        try:
            value = request.POST[f'device_{device.id}']
        except (KeyError):
            continue
        else:
            device.value = value
            device.save()
    return HttpResponseRedirect(reverse('devices:location', args=(location_id,)))
