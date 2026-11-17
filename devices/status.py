"""Stan urządzeń do wyświetlenia: urządzenie + cache z brokera (`DeviceState`, `SystemStatus`).

Dostępność według ADR 0009 w repo nadrzędnym: urządzenie jest dostępne tylko
przy żywym workerze (połączony, heartbeat ≤ 90 s), `gateway/status` = `online`
i `availability` = `online`. Przy niedostępnym urządzeniu stan i pomiary są
ostatnimi znanymi wartościami.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .kinds import MEASUREMENTS
from .models import Device, DeviceState, Override, SystemStatus

WORKER_STALE_AFTER = timedelta(seconds=90)
CARD_MEASUREMENTS = ('power_w', 'energy_wh', 'temperature_c', 'humidity_pct')

# Powód niedostępności – klucz i opis dla UI.
OK = 'ok'
REASONS = {
    'worker': _('no data from the MQTT worker'),
    'gateway': _('gateway offline'),
    'device': _('device offline'),
    'unknown': _('no data from the device yet'),
}


@dataclass(frozen=True)
class Reading:
    """Pomiar z `telemetry` z opisem i jednostką (`kinds.MEASUREMENTS`)."""
    name: str
    label: str
    unit: str
    value: object


@dataclass
class DeviceStatus:
    device: Device
    state: dict | None = None
    state_ts: datetime | None = None
    telemetry: dict | None = None
    telemetry_ts: datetime | None = None
    reason: str = 'unknown'
    readings: list[Reading] = field(default_factory=list)
    override: Override | None = None
    """Trwające nadpisanie („włącz na N minut”)."""

    @property
    def available(self) -> bool:
        return self.reason == OK

    @property
    def reason_label(self):
        return REASONS.get(self.reason, '')

    @property
    def kind(self):
        return self.device.kind_spec

    @property
    def accepts_override(self) -> bool:
        return self.kind.accepts_rules

    @property
    def template(self) -> str:
        return f'devices/cards/{self.device.kind}.html'

    @property
    def updated(self) -> datetime | None:
        """Czas najnowszej wiadomości urządzenia (stan albo pomiary)."""
        times = [t for t in (self.state_ts, self.telemetry_ts) if t is not None]
        return max(times) if times else None

    @property
    def card_readings(self) -> list[Reading]:
        """Pomiary na karcie – pozostałe (napięcie, prąd, temperatura urządzenia) na stronie urządzenia."""
        return [r for r in self.readings if r.name in CARD_MEASUREMENTS]


def worker_alive(system: SystemStatus, now=None) -> bool:
    now = now or timezone.now()
    return (system.worker_connected and system.worker_seen_at is not None
            and now - system.worker_seen_at <= WORKER_STALE_AFTER)


def _reason(system: SystemStatus, cached: DeviceState | None, now) -> str:
    if not worker_alive(system, now):
        return 'worker'
    if system.gateway_status != 'online':
        return 'gateway'
    if cached is None or not cached.availability:
        return 'unknown'
    if cached.availability != 'online':
        return 'device'
    return OK


def _readings(telemetry) -> list[Reading]:
    # kolejność jak w MEASUREMENTS; nieznane pola pomijamy (kontrakt: odbiorca ignoruje nowe pola)
    telemetry = telemetry or {}
    return [Reading(m.name, m.label, m.unit, telemetry[m.name])
            for m in MEASUREMENTS.values() if m.name in telemetry]


def statuses(devices, now=None) -> list[DeviceStatus]:
    """Stan urządzeń w kolejności `devices` – jedno zapytanie do cache."""
    devices = list(devices)
    now = now or timezone.now()
    # Tylko odczyt – wiersz zakłada worker; przed jego pierwszym startem „brak danych”.
    system = SystemStatus.objects.filter(pk=1).first() or SystemStatus()
    cache = {s.slug: s for s in DeviceState.objects.filter(slug__in=[d.slug for d in devices])}
    overrides = {o.device_id: o for o in Override.objects.filter(device__in=devices, until__gt=now)}
    result = []
    for device in devices:
        cached = cache.get(device.slug)
        result.append(DeviceStatus(
            device=device,
            state=cached.state if cached else None,
            state_ts=cached.state_ts if cached else None,
            telemetry=cached.telemetry if cached else None,
            telemetry_ts=cached.telemetry_ts if cached else None,
            reason=_reason(system, cached, now),
            readings=_readings(cached.telemetry if cached else None),
            override=overrides.get(device.pk),
        ))
    return result


def status(device, now=None) -> DeviceStatus:
    return statuses([device], now)[0]
