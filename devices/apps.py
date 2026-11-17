from django.apps import AppConfig


class DevicesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'devices'

    def ready(self):
        # Publikacja konfiguracji urządzeń w brokerze MQTT (sygnały modelu).
        from . import signals  # noqa: F401
