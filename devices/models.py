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

    class ControlInputParams:
        def __init__(self, input_type: str, label: str = None, params: dict = ()):
            self.type = input_type
            self.label = label
            self.params = params

        def __eq__(self, other):
            return self.type == other.type and self.label == other.label and self.params == other.params

    location = models.ForeignKey(Location, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    config_file = models.CharField(max_length=100)

    def __str__(self):
        return (f"{self.name}: "
                f"config_file={self.config_file}")
