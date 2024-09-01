from django.contrib import admin

from .models import Location, Device, RelayPeriodicPeriod, RelayPeriodicDay


# Register your models here.
class DeviceInline(admin.TabularInline):
    model = Device
    extra = 0


class DeviceAdmin(admin.ModelAdmin):
    fieldsets = [
        (None, {'fields': ['location']}),
        ('General', {'fields': ['name']}),
        ('Specific', {'fields': ['config_file']})
    ]


class RelayPeriodicDayAdmin(admin.ModelAdmin):
    pass


class RelayPeriodicPeriodAdmin(admin.ModelAdmin):
    pass


class LocationAdmin(admin.ModelAdmin):
    inlines = [DeviceInline]


admin.site.register(Location, LocationAdmin)
admin.site.register(Device, DeviceAdmin)
admin.site.register(RelayPeriodicPeriod, RelayPeriodicPeriodAdmin)
admin.site.register(RelayPeriodicDay, RelayPeriodicDayAdmin)
