from django.contrib import admin

# Register your models here.

from .models import Location, Device

admin.site.register(Location)
admin.site.register(Device)
