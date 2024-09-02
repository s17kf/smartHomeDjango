import json
from .models import Device, RelayPeriodicPeriod, RelayPeriodicDay
import gpiocontrol as gpio


class DeviceConfig:
    class DeviceType:
        SWITCH = 'switch'
        RELAY_PERIODIC = 'relay-periodic'

    def __init__(self, device: Device):
        self.device = device

    @staticmethod
    def parse_device(device: Device):
        match device.type:
            case Device.DeviceType.SWITCH:
                return SwitchDeviceConfig(device)
            case Device.DeviceType.RELAY_PERIODIC:
                return RelayPeriodicDeviceConfig(device)
        return UnknownTypeDeviceConfig(device, device.type)

    def get_control_html(self):
        pass

    def get_details_html(self):
        return f"Device type: {self.device.name}"

    def get_status_html(self):
        return f"Device status for <b>{self.device.type}</b> is not implemented yet"


class SwitchDeviceConfig(DeviceConfig):
    def __init__(self, device: Device):
        super().__init__(device)

    def get_control_html(self):
        html_content = (
            f"<label for=device_{self.device.id}>0</label>"
            f"<input type='radio' name='device_{self.device.id}', id='device_{self.device.id}', value='0'>"
            f"<label for=device_{self.device.id}>1</label>"
            f"<input type='radio' name='device_{self.device.id}', id='device_{self.device.id}', value='1'>")
        return html_content


class RelayPeriodicDeviceConfig(DeviceConfig):
    def __init__(self, device: Device):
        super().__init__(device)
        try:
            config_file = open(device.config_file)
            self.config = json.load(config_file)
        except IOError:
            self.config = None

    def get_control_html(self):
        # Todo: add proper html content
        return "periodic relay"

    def get_details_html(self):
        active_days = RelayPeriodicDay.objects.filter(device=self.device)
        active_periods = RelayPeriodicPeriod.objects.filter(device=self.device)
        html_content = (
            f"Active days:"
            f"<ul>"
        )
        for day in active_days:
            html_content += f"<li>{day.get_day_display()}</li>"
        html_content += (
            f"</ul>"
            f"Active periods:"
            f"<ul>"
        )
        for period in active_periods:
            html_content += f"<li>{period.begin.strftime('%H:%M')} - {period.end.strftime('%H:%M')}</li>"
        html_content += (
            f"</ul>"
        )
        return html_content

    def get_status_html(self):
        if self.config is None:
            return "Missing config file!"
        pin_number = self.config["pinNumber"]
        try:
            pin_state = gpio.get(pin_number)
        except Exception:
            return "<span style='color:red;'>Error reading pin state!</span>"
        html_content = ""
        if pin_state == gpio.State.LOW:
            html_content = "Relay is <span style='color:green;'>ON</span>"
        else:
            html_content = "Relay is <span style='color:red;'>OFF</span>"
        return html_content


class MissingConfigFileDeviceConfig(DeviceConfig):
    def __init__(self, device: Device):
        super().__init__(device)

    def get_control_html(self):
        return "Missing config file!"


class UnknownTypeDeviceConfig(DeviceConfig):
    def __init__(self, device: Device, type: str):
        super().__init__(device)
        self.type = type

    def get_control_html(self):
        return f"Unknown device type: '{self.type}'!"