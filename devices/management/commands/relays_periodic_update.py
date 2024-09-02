from django.core.management.base import BaseCommand, CommandError
from devices.models import Device, RelayPeriodicPeriod, RelayPeriodicDay
from datetime import datetime
import json, subprocess

PIN_CONTROL_COMMAND = "/usr/bin/pinctrl"


def add_timestamp(msg):
    return f"{datetime.now().strftime('%Y.%m.%d-%H:%M:%S.%f')} {msg}"


class Command(BaseCommand):
    help = ('Updates the state of all periodic relay devices. '
            'It is intended to be run by a cron job or other periodic scheduler')

    def handle(self, *args, **options):
        now = datetime.now()
        for device in Device.objects.filter(type=Device.DeviceType.RELAY_PERIODIC):
            try:
                config_file = open(device.config_file)
            except IOError:
                self.stdout.write(add_timestamp(f"device: {device.name} - failed to open config file"))
                continue
            data = json.load(config_file)
            pin_number = data["pinNumber"]

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
            if active_time:
                self.stdout.write(add_timestamp(activation_log))
                command_result = subprocess.run([PIN_CONTROL_COMMAND, '-e', 'set', f'{pin_number}', 'op', 'dl'],
                                                capture_output=True)
            else:
                self.stdout.write(add_timestamp(f"device: {device.name} - no active period"))
                command_result = subprocess.run([PIN_CONTROL_COMMAND, '-e', 'set', f'{pin_number}', 'op', 'dh'],
                                                capture_output=True)

            if command_result.returncode != 0:
                self.stdout.write(add_timestamp(f"ERROR: pin change: {command_result.stdout}"))
        # self.stdout.write(self.style.SUCCESS('Successfully updated all devices'))
