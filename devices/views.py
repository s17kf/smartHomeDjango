from datetime import datetime, timedelta

from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, get_list_or_404
from django.urls import reverse
from django.views import generic

from .device_helpers import DeviceConfig, RelayDeviceConfig, RelayPeriodicDeviceConfig
from .models import Location, Device, RelayPeriodicManualActivation


class LocationListView(generic.ListView):
    template_name = 'devices/location_list.html'
    context_object_name = 'locations'

    def get_queryset(self):
        return Location.objects.all()


class FavouritesView(generic.ListView):
    template_name = 'devices/favourites.html'
    context_object_name = 'favourites_devices'

    def get_queryset(self):
        return


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


def periodic_relay_manual_activate(request, device_id):
    next = request.POST.get('next', '/')
    try:
        device = Device.objects.get(pk=device_id)
    except Device.DoesNotExist:
        # todo: log error
        return HttpResponseRedirect(next)
    manual_activation = RelayPeriodicManualActivation.objects.filter(device=device).first()
    if manual_activation:
        manual_activation.delete()
    manual_activation = RelayPeriodicManualActivation(device=device)
    try:
        minutes = int(request.POST.get('minutes', '0'))
    except ValueError:
        minutes = 0
    if minutes <= 0:
        return HttpResponseRedirect(next)
    end_time = datetime.now().replace(second=0) + timedelta(minutes=minutes)
    manual_activation.end_time = end_time
    manual_activation.save()
    device_config = RelayPeriodicDeviceConfig(device)
    device_config.setstate(device_config.active_state)
    return HttpResponseRedirect(next)


def periodic_relay_manual_deactivate(request, device_id):
    next = request.POST.get('next', '/')
    try:
        device = Device.objects.get(pk=device_id)
    except Device.DoesNotExist:
        # todo: log error
        return HttpResponseRedirect(next)
    manual_activation = RelayPeriodicManualActivation.objects.filter(device=device).first()
    if manual_activation is None:
        print(f"no manual activation to deactivate (dev: {device.name})")
        return HttpResponseRedirect(next)
    manual_activation.delete()
    device_config = RelayPeriodicDeviceConfig(device)
    if not device_config.is_active_day() and device_config.current_period is None:
        device_config.setstate(device_config.inactive_state)
    return HttpResponseRedirect(next)


def periodic_relay_add_active_day(request, device_id):
    next = request.POST.get('next', '/')
    try:
        device = Device.objects.get(pk=device_id)
    except Device.DoesNotExist:
        # todo: log error
        return HttpResponseRedirect(next)
    try:
        day = int(request.POST.get('day', '-1'))
    except ValueError:
        return HttpResponseRedirect(next)
    if day < 0 or day > 6:
        return HttpResponseRedirect(next)
    if device.relayperiodicday_set.filter(day=day).exists():
        return HttpResponseRedirect(next)
    device.relayperiodicday_set.create(day=day)
    device_config = RelayPeriodicDeviceConfig(device)
    if not device_config.is_active() and day == datetime.now().weekday():
        device_config.setstate(device_config.active_state)
    return HttpResponseRedirect(next)


def periodic_relay_remove_active_day(request, device_id):
    next = request.POST.get('next', '/')
    try:
        device = Device.objects.get(pk=device_id)
    except Device.DoesNotExist:
        # todo: log error
        return HttpResponseRedirect(next)
    try:
        day = int(request.POST.get('day', '-1'))
    except ValueError:
        return HttpResponseRedirect(next)
    if day < 0 or day > 6:
        return HttpResponseRedirect(next)
    device.relayperiodicday_set.filter(day=day).delete()
    if day == datetime.now().weekday():
        device_config = RelayPeriodicDeviceConfig(device)
        if not device_config.is_manual_activated() and device_config.current_period is None:
            device_config.setstate(device_config.inactive_state)
    return HttpResponseRedirect(next)


def periodic_relay_add_active_period(request, device_id):
    next = request.POST.get('next', '/')
    try:
        device = Device.objects.get(pk=device_id)
    except Device.DoesNotExist:
        # todo: log error
        return HttpResponseRedirect(next)
    try:
        begin = request.POST.get('begin', '00:00')
        end = request.POST.get('end', '00:00')
        begin_time = datetime.strptime(begin, '%H:%M').time()
        end_time = datetime.strptime(end, '%H:%M').time()
    except ValueError:
        return HttpResponseRedirect(next)
    if begin_time == end_time:
        return HttpResponseRedirect(next)
    if device.relayperiodicperiod_set.filter(begin=begin_time, end=end_time).exists():
        return HttpResponseRedirect(next)
    device.relayperiodicperiod_set.create(begin=begin_time, end=end_time)
    device_config = RelayPeriodicDeviceConfig(device)
    if not device_config.is_active() and device_config.current_period is not None:
        device_config.setstate(device_config.active_state)
    return HttpResponseRedirect(next)


def periodic_relay_remove_active_period(request, device_id):
    next = request.POST.get('next', '/')
    try:
        device = Device.objects.get(pk=device_id)
    except Device.DoesNotExist:
        # todo: log error
        return HttpResponseRedirect(next)
    try:
        period_id = int(request.POST.get('period_id', '-1'))
    except ValueError:
        return HttpResponseRedirect(next)
    device.relayperiodicperiod_set.filter(pk=period_id).delete()
    device_config = RelayPeriodicDeviceConfig(device)
    if (device_config.is_active() and device_config.current_period is None
            and not device_config.is_manual_activated()
            and not device_config.is_active_day()):
        device_config.setstate(device_config.inactive_state)
    return HttpResponseRedirect(next)
