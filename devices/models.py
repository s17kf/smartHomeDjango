from django.db import models
from django.utils.translation import gettext_lazy as _


# Create your models here.

class Location(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class Device(models.Model):
    class DeviceTypes(models.TextChoices):
        SWITCH = 'SW', _('Switch')
        PWM = 'PWM', _('PWM regulator')

    location = models.ForeignKey(Location, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    type = models.CharField(
        max_length=10,
        choices=DeviceTypes,
    )
    address = models.CharField(
        "HW address",
        max_length=100,
    )

    def __str__(self):
        return f"{self.name}({self.type})"
