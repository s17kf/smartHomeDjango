"""Reguły i nadpisania w workerze MQTT – krok pętli co kilka sekund (ADR 0010 w repo nadrzędnym).

Krok sprawdza przedział `(since, now]`, gdzie `since` to koniec poprzedniego
przedziału (`SystemStatus.rules_checked_at`, w bazie – po restarcie workera
przedział obejmuje przerwę). Dla każdego urządzenia z regułami, nadpisaniem
albo niepotwierdzonym zdarzeniem:

1. zdarzenie z `schedule.event`: najnowsza reguła w przedziale, początek
   nadpisania (reguły w trakcie czekają) albo jego koniec (stan z reguły od
   początku nadpisania, a bez niej – stan sprzed nadpisania);
2. zdarzenie → nowy stan do wysłania w `AutomationState`; `set`, chyba że
   `state` w cache już go spełnia;
3. bez potwierdzenia – `set` ponawiany co `RETRY_AFTER`, najwyżej
   `MAX_ATTEMPTS` wysłań i tylko przy dostępnym urządzeniu (polecenie do
   niedostępnego przepada – czeka na dostępność); potem WARNING i koniec prób;
4. po potwierdzeniu żadnych `set` do następnego zdarzenia – ręczna zmiana
   (UI, przycisk, włącznik ścienny) zostaje;
5. wygasłe nadpisanie – usunięte po wyliczeniu stanu.

Restart workera bez przegapionej reguły nie wysyła `set`; z kilku
przegapionych wykonuje się tylko najnowsza. Reguła dodana po swojej
godzinie wykona się dopiero w następnym dniu.

Potwierdzenie: pola stanu (bez `transition`) równe polom `state` w cache
(`Kind.satisfied`), sprawdzane tylko przy dostępnym urządzeniu – stan
niedostępnego jest nieaktualny.
"""

import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from django.core.exceptions import ObjectDoesNotExist

from . import schedule
from . import status as device_status
from .kinds import InvalidCommand
from .models import AutomationState, Device, Override, Rule, SystemStatus

log = logging.getLogger(__name__)

RETRY_AFTER = timedelta(minutes=1)
MAX_ATTEMPTS = 5

Publish = Callable[[str, dict], None]
"""Wysłanie `set`: (slug, polecenie)."""

_REASONS = {
    schedule.RULE: 'rule',
    schedule.OVERRIDE: 'override',
    schedule.OVERRIDE_END: 'override ended',
}


def _json(value):
    return json.dumps(value, separators=(',', ':'))


def _related(device, name):
    try:
        return getattr(device, name)
    except ObjectDoesNotExist:
        return None


def _reason(event: schedule.Event) -> str:
    label = _REASONS[event.reason]
    if event.rule is not None:
        label += f' "{event.rule.label}"' if event.reason == schedule.RULE else f', rule "{event.rule.label}"'
    return label


def step(publish: Publish, now: datetime) -> None:
    """Jeden krok automatyzacji dla wszystkich urządzeń: przedział od poprzedniego kroku do `now` (aware)."""
    checked = SystemStatus.objects.filter(pk=1).values_list('rules_checked_at', flat=True).first()
    since = checked or now
    ids = (set(Rule.objects.filter(enabled=True).values_list('device_id', flat=True))
           | set(Override.objects.values_list('device_id', flat=True))
           | set(AutomationState.objects.filter(outcome=AutomationState.PENDING)
                 .values_list('device_id', flat=True)))
    devices = (Device.objects.filter(pk__in=ids).order_by('slug')
               .select_related('override', 'automation').prefetch_related('rules'))
    for status in device_status.statuses(devices, now):
        try:
            _device_step(status, publish, since, now)
        except Exception:
            # błąd jednego urządzenia nie zatrzymuje pozostałych
            log.exception('%s: automation step failed', status.device.slug)
    # update() – bez `auto_now` w `updated_at`, które oznacza zmianę stanu dla UI
    SystemStatus.objects.filter(pk=1).update(rules_checked_at=now)


def _device_step(status: device_status.DeviceStatus, publish: Publish, since: datetime, now: datetime) -> None:
    device = status.device
    if not device.kind_spec.accepts_rules:
        return
    override = _related(device, 'override')
    auto = _related(device, 'automation')
    event = schedule.event(device.rules.all(), override, since, now)

    # trwające nadpisanie zwracane jest co krok – nowe tylko przy zmianie stanu (np. przedłużenie z innym)
    if (event is not None and event.reason == schedule.OVERRIDE and auto is not None
            and auto.reason == schedule.OVERRIDE and auto.desired == event.state):
        event = None
    if event is not None:
        auto = auto or AutomationState(device=device)
        auto.desired, auto.reason, auto.changed_at = event.state, event.reason, event.at
        auto.outcome, auto.outcome_at, auto.sent_at, auto.attempts = AutomationState.PENDING, None, None, 0
        log.info('%s: %s → %s', device.slug, _reason(event), _json(event.state))
        auto.save()

    if auto is not None:
        _deliver(status, auto, publish, now)

    if override is not None and not schedule.override_active(override, now):
        # Bez usuwania nadpisania przedłużonego w międzyczasie z UI.
        Override.objects.filter(pk=override.pk, until__lte=now).delete()


def _deliver(status, auto: AutomationState, publish: Publish, now: datetime) -> None:
    """Wysłanie, ponowienie albo potwierdzenie stanu z ostatniego zdarzenia."""
    if auto.outcome != AutomationState.PENDING or not status.available:
        return
    slug, kind = status.device.slug, status.kind
    if kind.satisfied(status.state, auto.desired):
        auto.outcome, auto.outcome_at = AutomationState.CONFIRMED, now
        if auto.attempts:
            log.info('%s: state confirmed after %d attempt(s)', slug, auto.attempts)
        else:
            log.info('%s: already in that state – no set', slug)
    elif auto.attempts < MAX_ATTEMPTS:
        if auto.sent_at is not None and now - auto.sent_at < RETRY_AFTER:
            return
        try:
            command = kind.validate_target(auto.desired)
        except InvalidCommand as exc:
            # np. rodzaj urządzenia zmieniony poza adminem – reguła nie pasuje
            log.warning('%s: state %s does not fit kind %s (%s) – not sent',
                        slug, _json(auto.desired), kind.name, exc)
            auto.outcome, auto.outcome_at = AutomationState.FAILED, now
        else:
            publish(slug, command)
            auto.attempts += 1
            auto.sent_at = now
            log.info('%s: set %s (%s)', slug, _json(command),
                     'sent' if auto.attempts == 1 else f'retry {auto.attempts}/{MAX_ATTEMPTS}')
    elif now - auto.sent_at >= RETRY_AFTER:
        auto.outcome, auto.outcome_at = AutomationState.FAILED, now
        log.warning('%s: no confirmation of %s after %d attempts – no more set until the next event',
                    slug, _json(auto.desired), auto.attempts)
    else:
        return
    auto.save()
