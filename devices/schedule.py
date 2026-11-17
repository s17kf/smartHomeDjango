"""Reguły automatyzacji: chwile wykonania i zdarzenie do wykonania (ADR 0010 w repo nadrzędnym).

Czyste funkcje – bez bazy i zegara systemowego; reguły i nadpisanie to
dowolne obiekty z polami modeli `Rule` i `Override`. Tego samego używa worker
(`automation.py`) i UI.

- Reguła: w wybrane dni tygodnia (0 = poniedziałek) o godzinie `time` na
  zegarze lokalnym (`TIME_ZONE`) ustaw `target_state`. „Włącz o 18:00,
  wyłącz o 23:00” to dwie reguły.
- Worker sprawdza reguły w kolejnych przedziałach `(since, now]`. Z kilku
  chwil w przedziale (przerwa w działaniu workera) wykonuje tylko najnowszą.
  Przerwa dłuższa niż `LOOKBACK` liczy się jak `LOOKBACK` – reguła
  wykonuje się co najmniej raz w tygodniu.
- Nadpisanie („włącz na N minut”): stan do `until` (bez tej chwili);
  reguły w trakcie czekają. Po końcu – stan z najnowszej reguły od początku
  nadpisania, a bez niej – stan sprzed nadpisania.

Zmiana czasu: wiosną reguła z brakującej godziny (02:00–03:00) wykonuje się
o 03:00, jesienią reguła z powtórzonej godziny – raz, w pierwszym przejściu.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone as dt_timezone

from django.utils import timezone

# Powód zdarzenia (zapisywany w `AutomationState.reason`).
RULE = 'rule'
OVERRIDE = 'override'
OVERRIDE_END = 'override_end'

LOOKBACK = timedelta(days=8)


@dataclass(frozen=True)
class Event:
    """Stan do ustawienia: z reguły, nadpisania albo po końcu nadpisania."""
    state: dict
    reason: str
    at: datetime
    """Chwila zdarzenia (UTC): wykonanie reguły, początek albo koniec nadpisania."""
    rule: object | None = None


def rule_instant(day: date, moment: time) -> datetime:
    """Chwila (UTC), w której reguła z godziną `moment` wykonuje się w dniu `day` (data lokalna).

    Godzina z luki wiosną – pierwsza istniejąca chwila po niej (03:00);
    godzina powtórzona jesienią – pierwsze przejście (`fold` = 0).
    """
    tz = timezone.get_default_timezone()
    wall = datetime.combine(day, moment)
    for minutes in range(0, 181):
        candidate = (wall + timedelta(minutes=minutes)).replace(tzinfo=tz)
        instant = candidate.astimezone(dt_timezone.utc)
        # godzina z luki nie przechodzi tam i z powrotem bez zmiany
        if instant.astimezone(tz).replace(tzinfo=None) == candidate.replace(tzinfo=None):
            return instant
    return wall.replace(tzinfo=tz).astimezone(dt_timezone.utc)


def occurrences(rule, since: datetime, now: datetime) -> list[datetime]:
    """Chwile wykonania reguły (UTC, rosnąco) w przedziale `(since, now]`, najwyżej `LOOKBACK` wstecz."""
    tz = timezone.get_default_timezone()
    since = max(since, now - LOOKBACK)
    day, last = since.astimezone(tz).date(), now.astimezone(tz).date()
    result = []
    while day <= last:
        if day.weekday() in rule.days:
            instant = rule_instant(day, rule.time)
            if since < instant <= now:
                result.append(instant)
        day += timedelta(days=1)
    return result


def latest(rules, since: datetime, now: datetime):
    """Najnowsze wykonanie włączonej reguły w `(since, now]`: (chwila, reguła) albo None.

    Przy tej samej chwili wygrywa pierwsza reguła wg kolejności `rules`
    (walidacja nie dopuszcza dwóch reguł urządzenia o tej samej porze
    z różnym stanem).
    """
    found = None
    for rule in rules:
        if not rule.enabled:
            continue
        for instant in occurrences(rule, since, now):
            if found is None or instant > found[0]:
                found = (instant, rule)
    return found


def override_active(override, now: datetime) -> bool:
    return override is not None and now < override.until


def event(rules, override, since: datetime, now: datetime) -> Event | None:
    """Zdarzenie urządzenia w przedziale `(since, now]`; None – nic do zrobienia.

    Trwające nadpisanie zwracane jest przy każdym wywołaniu – worker sam
    sprawdza, czy już je wykonał.
    """
    if override is not None:
        if override_active(override, now):
            return Event(dict(override.state), OVERRIDE, override.created_at)
        found = latest(rules, override.created_at, now)
        if found:
            return Event(dict(found[1].target_state), OVERRIDE_END, override.until, found[1])
        return Event(dict(override.previous_state), OVERRIDE_END, override.until)
    found = latest(rules, since, now)
    if found:
        return Event(dict(found[1].target_state), RULE, found[0], found[1])
    return None


def conflict(a, b) -> bool:
    """Czy dwie reguły wykonują się o tej samej porze w któryś dzień z różnym stanem."""
    return a.time == b.time and bool(set(a.days) & set(b.days)) and a.target_state != b.target_state
