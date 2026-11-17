"""Zmiany kart urządzeń przez SSE (Server-Sent Events) – zamiast odświeżania co 10 s.

Endpoint `devices/events/?location=<id>` albo `?device=<slug>` trzyma
połączenie (gunicorn `gthread` – wątek na połączenie) i co `POLL_S` sprawdza
w bazie cache stanu (`DeviceState.updated_at`), status systemu (gateway,
żywy worker) i trwające nadpisania. Dla zmienionych urządzeń wysyła
zdarzenie `device-<slug>` z wyrenderowaną kartą – HTMX (`htmx-ext-sse`)
podmienia kartę z `sse-swap="device-<slug>"`.

- Po połączeniu – od razu wszystkie karty (strona mogła się zestarzeć
  w przerwie między połączeniami).
- Co `FULL_REFRESH_S` – znów wszystkie (napisy „3 minuty temu”).
- Komentarz co `PING_S`, gdy nic nie poszło – połączenie nie wygasa w proxy.
- Po `STREAM_S` serwer kończy strumień, przeglądarka łączy się ponownie
  (`retry`) – zwalnia wątek i połączenie z bazą, po wdrożeniu przychodzi
  nowy kod.

Logika kroku (`CardStream.step`) nie zależy od zegara ani `sleep` – testy
podają jej chwile wprost.
"""

import time

from django.template.loader import render_to_string
from django.utils import timezone

from . import status as device_status
from .models import DeviceState, Override, SystemStatus

POLL_S = 1.0
PING_S = 15.0
FULL_REFRESH_S = 60.0
STREAM_S = 300.0
RETRY_MS = 3000


def sse_event(name: str, data: str) -> str:
    """Zdarzenie SSE: każda linia danych z prefiksem `data:`."""
    lines = data.splitlines() or ['']
    return f'event: {name}\n' + ''.join(f'data: {line}\n' for line in lines) + '\n'


class CardStream:
    """Zmiany kart wybranych urządzeń od poprzedniego kroku."""

    def __init__(self, devices, request=None):
        self.devices = list(devices)
        self.request = request
        self.signatures = {}
        self.last_full = None
        self.last_sent = None

    def _signatures(self, now):
        system = SystemStatus.objects.filter(pk=1).first() or SystemStatus()
        system_sig = (system.gateway_status, device_status.worker_alive(system, now))
        updated = dict(DeviceState.objects.filter(slug__in=[d.slug for d in self.devices])
                       .values_list('slug', 'updated_at'))
        overrides = {o.device_id: (o.state, o.until)
                     for o in Override.objects.filter(device__in=self.devices, until__gt=now)}
        return {d.slug: (system_sig, updated.get(d.slug), overrides.get(d.pk)) for d in self.devices}

    def step(self, now_s: float, now=None) -> list[str]:
        """Zdarzenia SSE w chwili `now_s` (zegar monotoniczny); `now` – czas do wyliczeń (domyślnie teraz)."""
        now = now or timezone.now()
        signatures = self._signatures(now)
        full = self.last_full is None or now_s - self.last_full >= FULL_REFRESH_S
        changed = [d for d in self.devices if full or signatures[d.slug] != self.signatures.get(d.slug)]
        self.signatures = signatures
        if full:
            self.last_full = now_s
        chunks = [sse_event(f'device-{s.device.slug}',
                            render_to_string(s.template, {'status': s}, request=self.request))
                  for s in device_status.statuses(changed, now)] if changed else []
        if chunks:
            self.last_sent = now_s
        elif self.last_sent is None or now_s - self.last_sent >= PING_S:
            chunks = [': ping\n\n']
            self.last_sent = now_s
        return chunks


def stream(cards: CardStream, clock=time.monotonic, sleep=time.sleep):
    """Treść odpowiedzi: `retry`, potem kroki co `POLL_S` przez `STREAM_S`."""
    yield f'retry: {RETRY_MS}\n\n'
    start = clock()
    while True:
        now_s = clock()
        yield from cards.step(now_s)
        if now_s - start >= STREAM_S:
            return
        sleep(POLL_S)
