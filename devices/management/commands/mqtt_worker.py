import signal
import threading

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from devices import worker


class Command(BaseCommand):
    help = ('Runs the MQTT worker: keeps the device state cache up to date and syncs device '
            'configs to the broker after each connection. Stops on SIGTERM / SIGINT.')

    def handle(self, *args, **options):
        if not settings.MQTT_PASSWORD:
            raise CommandError('MQTT_BACKEND_PASSWORD is not set – the broker does not accept anonymous clients')
        stop = threading.Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_: stop.set())
        worker.run(stop)
