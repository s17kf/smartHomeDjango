from django.contrib import admin

from .models import Location, Device


class DeviceInline(admin.TabularInline):
    """Urządzenia lokalizacji tylko do podglądu – edycja w panelu urządzenia (slug, parametry)."""
    model = Device
    fields = ['name', 'slug', 'kind', 'driver']
    readonly_fields = fields
    extra = 0
    show_change_link = True
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    inlines = [DeviceInline]


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'location', 'kind', 'driver']
    list_filter = ['location', 'kind', 'driver']
    search_fields = ['name', 'slug']
    fieldsets = [
        (None, {'fields': ['name', 'location']}),
        ('MQTT', {'fields': ['slug', 'kind', 'driver', 'params']}),
    ]

    def get_readonly_fields(self, request, obj=None):
        # Slug wyznacza tematy MQTT – nadawany przy dodaniu, potem bez zmian.
        return ['slug'] if obj is not None else []
