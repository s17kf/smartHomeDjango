from django.core.management.base import BaseCommand, CommandError

from devices import mqtt, sync
from devices.models import Device

# Kod wyjścia, gdy broker jest niedostępny (1 – pozostałe błędy).
BROKER_UNAVAILABLE = 2


class Command(BaseCommand):
    help = ('Publishes retained home/<slug>/config of all devices to the MQTT broker – only '
            'devices that are missing or different there. Devices known only to the broker are '
            'reported and removed with --prune.')

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='only compare, publish nothing')
        parser.add_argument('--prune', action='store_true',
                            help='remove devices that are not in the database from the broker '
                                 '(empty retained config, state, telemetry, availability)')

    def handle(self, *args, dry_run, prune, **options):
        broker = mqtt.broker()
        try:
            retained = broker.retained(mqtt.CONFIG_FILTER)
        except mqtt.MqttError as exc:
            raise CommandError(f'MQTT broker unavailable: {exc}', returncode=BROKER_UNAVAILABLE)

        result = sync.plan(retained, Device.objects.all())
        for label, slugs in (('added', result.added), ('changed', result.changed),
                             ('unchanged', result.unchanged)):
            self.stdout.write(f'{label}: {", ".join(slugs) or "-"}')
        if result.extra:
            action = 'removing' if prune else 'not in the database, kept (use --prune to remove)'
            self.stdout.write(self.style.WARNING(f'only in the broker – {action}: {", ".join(result.extra)}'))

        messages = result.messages + (result.prune_messages() if prune else [])
        if dry_run:
            self.stdout.write(f'dry run – {len(messages)} message(s) not published')
            return
        try:
            broker.publish(messages)
        except mqtt.MqttError as exc:
            raise CommandError(f'MQTT broker unavailable: {exc}', returncode=BROKER_UNAVAILABLE)
        self.stdout.write(f'published: {len(messages)} message(s)')
