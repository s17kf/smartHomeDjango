from django.contrib import admin

from .models import Location, Device


# Register your models here.
class DeviceInline(admin.TabularInline):
    model = Device
    extra = 0


class DeviceAdmin(admin.ModelAdmin):
    fieldsets = [
        (None, {'fields': ['location']}),
        ('General', {'fields': ['name', 'type']}),
        ('Specific', {'fields': ['value', 'params', 'address']})
    ]


class LocationAdmin(admin.ModelAdmin):
    inlines = [DeviceInline]


admin.site.register(Location, LocationAdmin)
admin.site.register(Device, DeviceAdmin)
