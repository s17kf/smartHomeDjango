from django.contrib import admin, messages
from django.db import transaction
from django.utils.translation import gettext as _

from .models import Location, Device, DeviceState, SystemStatus


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

    # Publikację w brokerze robią sygnały po zatwierdzeniu transakcji
    # (`signals.py`); ten callback rejestrujemy później, więc widzi jej wynik.
    # Widok admina zatwierdza transakcję przed zwróceniem odpowiedzi, więc
    # komunikat trafia do tej samej strony.

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        transaction.on_commit(lambda: self._report_mqtt_error(request, obj, _(
            'The device was saved, but its config did not reach the MQTT broker: %(error)s. '
            'Run "manage.py mqtt_sync" when the broker is available.')))

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        transaction.on_commit(lambda: self._report_mqtt_error(request, obj, _(
            'The device was deleted, but the MQTT broker still has its topics: %(error)s. '
            'Run "manage.py mqtt_sync --prune" when the broker is available.')))

    def _report_mqtt_error(self, request, obj, message):
        error = getattr(obj, 'mqtt_error', None)
        if error:
            self.message_user(request, message % {'error': error}, messages.WARNING)


class ReadOnlyAdmin(admin.ModelAdmin):
    """Cache z brokera – zapisuje go worker MQTT; w adminie tylko podgląd."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DeviceState)
class DeviceStateAdmin(ReadOnlyAdmin):
    list_display = ['slug', 'availability', 'state', 'state_ts', 'telemetry_ts', 'updated_at']
    search_fields = ['slug']


@admin.register(SystemStatus)
class SystemStatusAdmin(ReadOnlyAdmin):
    list_display = ['gateway_status', 'worker_connected', 'worker_seen_at', 'updated_at']
