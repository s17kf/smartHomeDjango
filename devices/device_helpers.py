import json

from .models import Device, RelayPeriodicPeriod, RelayPeriodicDay, RelayPeriodicManualActivation
import gpiocontrol as gpio
from datetime import datetime


class DeviceConfig:

    def __init__(self, device: Device):
        self.device = device

    @staticmethod
    def parse_device(device: Device):
        match device.type:
            case Device.DeviceType.RELAY:
                return RelayDeviceConfig(device)
            case Device.DeviceType.RELAY_PERIODIC:
                return RelayPeriodicDeviceConfig(device)
        return UnknownTypeDeviceConfig(device, device.type)

    def get_details_template(self):
        return "devices/details/not_implemented_details.html"

    def get_status_template(self):
        return "devices/details/not_implemented_status.html"


class RelayDeviceCommonConfig(DeviceConfig):
    def __init__(self, device: Device):
        super().__init__(device)
        self.state_available = False
        try:
            config_file = open(device.config_file)
            self.config = json.load(config_file)
        except IOError as e:
            self.config = None
            print(f"config file error: {str(e)}")
            return
        try:
            self.pin_number = self.config["pinNumber"]
            self.state = gpio.get(self.pin_number)
            self.active_state = gpio.State(self.config['activeState'])
        except Exception as e:
            print(f"gpio error: {str(e)}")
            # todo: log error
            return
        self.inactive_state = gpio.State.HIGH if self.active_state == gpio.State.LOW else gpio.State.LOW
        self.state_available = True

    def is_active(self):
        return self.state == self.active_state

    def setstate(self, state: gpio.State):
        try:
            gpio.set(self.pin_number, state)
        except Exception as e:
            # todo: log error
            print(f"{self.device.name} set state gpio error: {str(e)}")
            pass


class RelayDeviceConfig(RelayDeviceCommonConfig):
    def __init__(self, device: Device):
        assert device.type == Device.DeviceType.RELAY
        super().__init__(device)

    def get_status_template(self):
        return "devices/details/relay_status.html"


class RelayPeriodicDeviceConfig(RelayDeviceCommonConfig):
    def __init__(self, device: Device):
        assert device.type == Device.DeviceType.RELAY_PERIODIC
        super().__init__(device)
        self.now = datetime.now()
        self.current_period = self.__get_current_period()
        self.manual_activation_period = self.__get_manual_activation()

    def is_active_day(self):
        return RelayPeriodicDay.objects.filter(device=self.device, day=self.now.weekday()).exists()

    def current_day_display(self):
        return self.now.strftime('%A')

    def __get_current_period(self):
        for period in RelayPeriodicPeriod.objects.filter(device=self.device):
            if period.begin < period.end:
                if period.begin <= self.now.time() <= period.end:
                    return period
            elif period.begin < self.now.time() or self.now.time() < period.end:
                return period
        return None

    def get_current_period_display(self):
        if self.current_period is None:
            return "None"
        return f"{self.current_period.begin.strftime('%H:%M')} - {self.current_period.end.strftime('%H:%M')}"

    def __get_manual_activation(self):
        return RelayPeriodicManualActivation.objects.filter(device=self.device).first()

    def is_manual_activated(self):
        if self.manual_activation_period is None:
            return False
        return self.now < self.manual_activation_period.end_time

    def get_manual_activation_end_display(self):
        if self.manual_activation_period is None:
            return "None"
        return self.manual_activation_period.end_time.strftime('%Y-%m-%d %H:%M')

    def get_active_days(self):
        return RelayPeriodicDay.objects.filter(device=self.device)

    def get_active_periods(self):
        return RelayPeriodicPeriod.objects.filter(device=self.device)

    def get_details_template(self):
        return "devices/details/relay_periodic_details.html"

    def get_status_template(self):
        return "devices/details/relay_periodic_status.html"


class MissingConfigFileDeviceConfig(DeviceConfig):
    def __init__(self, device: Device):
        super().__init__(device)


class UnknownTypeDeviceConfig(DeviceConfig):
    def __init__(self, device: Device, type: str):
        super().__init__(device)
        self.type = type
