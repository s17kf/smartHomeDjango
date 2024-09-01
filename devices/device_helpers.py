import json
from .models import Device


class DeviceConfig:
    class DeviceType:
        SWITCH = 'switch'
        RELAY_PERIODIC = 'relay-periodic'

    def __init__(self, device: Device):
        self.device = device

    @staticmethod
    def parse_device(device: Device):
        try:
            config_file = open(device.config_file)
        except IOError:
            return MissingConfigFileDeviceConfig(device)
        data = json.load(config_file)
        type = data["type"]
        match type:
            case DeviceConfig.DeviceType.SWITCH:
                return SwitchDeviceConfig(device)
            case DeviceConfig.DeviceType.RELAY_PERIODIC:
                return RelayPeriodicDeviceConfig(device)
        return UnknownTypeDeviceConfig(device, type)

    def get_control_html(self):
        pass


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

    def get_control_html(self):
        # Todo: add proper html content
        return "periodic relay"


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