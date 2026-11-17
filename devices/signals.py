"""Konfiguracja urządzeń w brokerze: Django jest jej źródłem.

Po zapisie urządzenia – retained `home/<slug>/config`, po usunięciu – pusty
retained na `config`, `state`, `telemetry` i `availability` (`specs/topics.md`).
Sygnały modelu, a nie admin, żeby to samo działo się przy kaskadzie z
lokalizacji, imporcie i w shellu (`QuerySet.update()` sygnałów nie wysyła –
nie używamy go dla urządzeń). Publikacja po zatwierdzeniu transakcji, więc
wycofany zapis nie trafia do brokera.

Błąd brokera nie przerywa zapisu: WARNING w logu i `device.mqtt_error`
(admin pokazuje komunikat). Zgodność przywraca `manage.py mqtt_sync`.
"""

import logging

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from . import mqtt
from .models import Device

log = logging.getLogger(__name__)


@receiver(post_save, sender=Device)
def publish_config(sender, instance, raw=False, **kwargs):
    # `loaddata` (raw) – bez publikacji; potem `mqtt_sync`.
    if raw:
        return
    messages = mqtt.config_messages(instance)
    transaction.on_commit(lambda: _publish(instance, messages, 'config'))


@receiver(post_delete, sender=Device)
def publish_removal(sender, instance, **kwargs):
    messages = mqtt.removal_messages(instance.slug)
    transaction.on_commit(lambda: _publish(instance, messages, 'removal'))


def _publish(device, messages, what):
    try:
        mqtt.broker().publish(messages)
    except mqtt.MqttError as exc:
        device.mqtt_error = str(exc)
        log.warning('%s: %s not published to the MQTT broker: %s', device.slug, what, exc)
    else:
        device.mqtt_error = None
