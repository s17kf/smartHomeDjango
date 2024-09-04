from django.core.management.base import BaseCommand, CommandError
from devices.models import Device, RelayPeriodicPeriod, RelayPeriodicDay
from devices.device_helpers import RelayPeriodicDeviceConfig
from datetime import datetime
import json, subprocess
import gpiocontrol as gpio

PIN_CONTROL_COMMAND = "/usr/bin/pinctrl"


def add_timestamp(msg):
    return f"{datetime.now().strftime('%Y.%m.%d-%H:%M:%S.%f')} {msg}"


class Command(BaseCommand):
    help = ('Updates the state of all periodic relay devices. '
            'It is intended to be run by a cron job or other periodic scheduler')

    def handle(self, *args, **options):
        now = datetime.now()
        for device in Device.objects.filter(type=Device.DeviceType.RELAY_PERIODIC):
            device_config = RelayPeriodicDeviceConfig(device)
            if not device_config.state_available:
                self.stdout.write(add_timestamp(f"device: {device.name} - config error"))
                continue

            periods = RelayPeriodicPeriod.objects.filter(device=device)
            days = RelayPeriodicDay.objects.filter(device=device)
            active_time = False
            if now.weekday() in [day.day for day in days]:
                active_time = True
                activation_log = f"device: {device.name} active day: {now.strftime('%A')}"
            else:
                for period in periods:
                    if period.begin < period.end:
                        if period.begin <= now.time() <= period.end:
                            active_time = True
                            activation_log = f"device: {device.name} active period: {period.begin} - {period.end}"
                            break
                    elif period.begin < now.time() or now.time() < period.end:
                        active_time = True
                        activation_log = f"device: {device.name} active period: {period.begin} - {period.end}"
                        break

            try:
                if active_time:
                    self.stdout.write(add_timestamp(activation_log))
                    device_config.setstate(device_config.active_state)
                else:
                    self.stdout.write(add_timestamp(f"device: {device.name} - no active period"))
                    device_config.setstate(device_config.inactive_state)
            except Exception as e:
                self.stdout.write(add_timestamp(f"Pin change error: {str(e)}"))
                continue
