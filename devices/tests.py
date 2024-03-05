from django.test import TestCase

from .models import Device


# Create your tests here.

class DeviceModelTest(TestCase):

    def test_switch_value0_device_control_input_params(self):
        dev = Device(type=Device.DeviceType.SWITCH, value=0)
        expected_params = [
            Device.ControlInputParams('radio', '0', {'value': 0, 'checked': ''}),
            Device.ControlInputParams('radio', '1', {'value': 1}),
        ]
        self.assertListEqual(dev.get_control_input_params_list(), expected_params)

    def test_switch_value1_device_control_input_params(self):
        dev = Device(type=Device.DeviceType.SWITCH, value=1)
        expected_params = [
            Device.ControlInputParams('radio', '0', {'value': 0}),
            Device.ControlInputParams('radio', '1', {'value': 1, 'checked': ''}),
        ]
        self.assertListEqual(dev.get_control_input_params_list(), expected_params)

    def test_pwm_device_control_input_params(self):
        value = 10
        min = 0
        max = 99
        dev = Device(type=Device.DeviceType.PWM, value=value, params=f'{{ "min": {min}, "max": {max} }}')
        expected_params = [
            Device.ControlInputParams(input_type='range', params={
                'value': value,
                'min': min,
                'max': max,
            })
        ]
        self.assertListEqual(dev.get_control_input_params_list(), expected_params)
