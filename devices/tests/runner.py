from django.conf import settings
from django.test.runner import DiscoverRunner


class TestRunner(DiscoverRunner):
    """Testy nigdy nie łączą się z brokerem MQTT.

    Publikacja trafia do brokera w pamięci (`devices.mqtt.MemoryBroker`, jak
    `mail.outbox` dla e-maili) – także wtedy, gdy obraz dostaje zmienne
    `MQTT_*` z pliku env stosu.
    """

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        settings.MQTT_BROKER = 'devices.mqtt.MemoryBroker'
