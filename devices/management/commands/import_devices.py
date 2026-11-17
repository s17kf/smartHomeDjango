import json
import sys
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from devices.models import Device, Location

FIELDS = ('name', 'location', 'kind', 'driver', 'params')


def _reject_duplicates(pairs):
    keys = [key for key, _value in pairs]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise ValueError(f'duplicate keys: {", ".join(duplicates)}')
    return dict(pairs)


class Command(BaseCommand):
    help = ('Imports devices from a JSON object: slug → {"name", "location", "kind", "driver", '
            '"params"}. The whole file is checked first – on any error nothing is saved. Devices '
            'whose slug is already in the database are skipped. Saved devices publish their '
            'config to the MQTT broker.')

    def add_arguments(self, parser):
        parser.add_argument('file', help='JSON file, "-" reads standard input')
        parser.add_argument('--location', help='location for entries without "location"')

    def handle(self, *args, file, location, **options):
        entries = self._load(file)
        added, skipped, problems = [], [], []
        with transaction.atomic():
            for slug, entry in entries.items():
                if Device.objects.filter(slug=slug).exists():
                    skipped.append(slug)
                    continue
                errors = self._import(slug, entry, location)
                if errors:
                    problems += [f'{slug}: {error}' for error in errors]
                else:
                    added.append(f'{slug} ({entry.get("location") or location})')
            if problems:
                # wyjątek w bloku atomic – wycofanie całego importu
                raise CommandError('nothing imported:\n  ' + '\n  '.join(problems))
        self.stdout.write(f'added: {", ".join(added) or "-"}')
        self.stdout.write(f'skipped (slug already in the database): {", ".join(skipped) or "-"}')

    @staticmethod
    def _load(file):
        try:
            text = sys.stdin.read() if file == '-' else Path(file).read_text(encoding='utf-8')
        except OSError as exc:
            raise CommandError(f'cannot read {file}: {exc}')
        try:
            entries = json.loads(text, object_pairs_hook=_reject_duplicates)
        except ValueError as exc:
            raise CommandError(f'{file}: invalid JSON: {exc}')
        if not isinstance(entries, dict):
            raise CommandError(f'{file}: expected a JSON object slug → device')
        return entries

    @staticmethod
    def _import(slug, entry, default_location):
        if not isinstance(entry, dict):
            return ['expected an object with name, location, kind, driver, params']
        errors = []
        unknown = sorted(entry.keys() - set(FIELDS))
        if unknown:
            errors.append(f'unknown fields: {", ".join(unknown)} (allowed: {", ".join(FIELDS)})')
        location_name = entry.get('location', default_location)
        for field, value in (('name', entry.get('name')), ('location', location_name),
                             ('kind', entry.get('kind')), ('driver', entry.get('driver'))):
            if not isinstance(value, str) or not value.strip():
                errors.append(f'{field}: expected a non-empty string'
                              + (' (or --location)' if field == 'location' else ''))
        if errors:
            return errors
        location = Location.objects.filter(name=location_name.strip()).first()
        if location is None:
            location = Location(name=location_name.strip())
            try:
                location.full_clean()
            except ValidationError as exc:
                return [f'location: {" ".join(m for ms in exc.message_dict.values() for m in ms)}']
            location.save()
        device = Device(location=location, slug=slug, name=entry['name'], kind=entry['kind'],
                        driver=entry['driver'], params=entry.get('params', {}))
        try:
            device.full_clean()
        except ValidationError as exc:
            return [f'{field}: {" ".join(messages)}' for field, messages in exc.message_dict.items()]
        device.save()
        return []
