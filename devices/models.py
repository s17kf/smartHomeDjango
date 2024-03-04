from django.db import models
from django.utils.translation import gettext_lazy as _
from json import loads as json_loads


# Create your models here.

class Location(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class Device(models.Model):
    class DeviceType(models.TextChoices):
        SWITCH = 'SW', _('Switch')
        PWM = 'PWM', _('PWM regulator')

    class ControlInputType:
        def __init__(self, input_type: str, label: str = None, params: dict = ()):
            self.type = input_type
            self.label = label
            self.params = params

    location = models.ForeignKey(Location, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    type = models.CharField(
        max_length=10,
        choices=DeviceType,
    )
    value = models.IntegerField()
    params = models.CharField(
        max_length=200,
        blank=True,
        default='',
    )
    address = models.CharField(
        "HW address",
        max_length=100,
    )

    def get_control_input_type(self) -> list[ControlInputType]:
        match self.type:
            case Device.DeviceType.SWITCH:
                l_params = {'value': 0}
                p_params = {'value': 1}
                if self.value == 0:
                    l_params['checked'] = ''
                else:
                    p_params['checked'] = ''
                return [
                    Device.ControlInputType('radio', 'L', l_params),
                    Device.ControlInputType('radio', 'P', p_params),
                ]
            case Device.DeviceType.PWM:
                params = json_loads(self.params)
                return [Device.ControlInputType('range', params={
                    'value': self.value,
                    'min': params['min'],
                    'max': params['max'],
                })]

    def __str__(self):
        return f"{self.name}({self.type})"
