"""Reguły i nadpisanie – tabela `SCHEDULE_CASES` (`devices/schedule.py`).

Tabela opisuje zachowanie automatyzacji; zmiany semantyki zaczynamy od niej.
Sprawdzamy ją dla czystej funkcji (tu) i dla kroku workera
(`test_automation.py`: `set` wysłany albo nie przy danym stanie w cache).
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from .. import schedule
from ..models import Override, Rule

WARSAW = ZoneInfo('Europe/Warsaw')
MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY = range(7)
EVERY_DAY = tuple(range(7))
WEEKDAYS = (MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY)
# krok workera – przedział (since, now] o tej długości, gdy przypadek nie podaje `since`
TICK = timedelta(seconds=5)

ON = {'on': True}
OFF = {'on': False}
WARM_30 = {'on': True, 'brightness': 30, 'mode': 'cct', 'ct': 2700}


def local(*args):
    return datetime(*args, tzinfo=WARSAW)


def utc(*args):
    return datetime(*args, tzinfo=dt_timezone.utc)


@dataclass(frozen=True)
class R:
    """Reguła w tabeli: o godzinie `at` ustaw `state`."""
    at: time
    state: dict | None = None
    days: tuple = EVERY_DAY
    enabled: bool = True

    def rule(self, **fields):
        return Rule(days=list(self.days), time=self.at, target_state=self.state or ON, enabled=self.enabled,
                    **fields)


@dataclass(frozen=True)
class O:
    """Nadpisanie w tabeli: `state` od `created_at` do `until`, potem `previous` (bez reguł w tym czasie)."""
    state: dict
    created_at: datetime
    until: datetime
    previous: dict | None = None

    def override(self, **fields):
        return Override(state=self.state, previous_state=self.previous or OFF, created_at=self.created_at,
                        until=self.until, **fields)


@dataclass(frozen=True)
class ScheduleCase:
    name: str
    now: datetime
    expected: dict | None
    """Stan do ustawienia; None – nic do zrobienia."""
    rules: tuple = ()
    override: O | None = None
    since: datetime | None = None
    """Koniec poprzedniego kroku workera; domyślnie `now` − `TICK`."""
    kind: str = 'switch'

    @property
    def start(self):
        return self.since or self.now - TICK


MORNING = (R(time(8)), R(time(9), OFF))
EVENING = (R(time(18)), R(time(23), OFF))
OVERNIGHT = (R(time(22)), R(time(6), OFF))
WHOLE_MONDAY = (R(time(0), days=(MONDAY,)), R(time(0), OFF, days=(TUESDAY,)))

SCHEDULE_CASES = (
    # Z `relay-periodic` (c549dda): okres → reguła na początku i na końcu, aktywny dzień →
    # reguły o 00:00 w ten dzień i w następny, ręczne włączenie → nadpisanie {"on": true}.
    # Różnica: urządzeniem bez reguł worker nie steruje (dawniej przekaźnik bez harmonogramu
    # był wyłączany co minutę), a między regułami nic nie wysyła.
    ScheduleCase('no rules', local(2026, 11, 16, 12, 0), None),
    ScheduleCase('rule time', local(2026, 11, 16, 8, 0), ON, MORNING),
    ScheduleCase('rule a few seconds ago', local(2026, 11, 16, 8, 0, 3), ON, MORNING),
    # przedział (since, now]: reguła z chwili `since` wykonała się w poprzednim kroku
    ScheduleCase('rule done in the previous step', local(2026, 11, 16, 8, 0, 5), None, MORNING,
                 since=local(2026, 11, 16, 8, 0)),
    ScheduleCase('between rules', local(2026, 11, 16, 8, 30), None, MORNING),
    ScheduleCase('second rule', local(2026, 11, 16, 9, 0), OFF, MORNING),
    ScheduleCase('overnight, evening rule', local(2026, 11, 16, 22, 0), ON, OVERNIGHT),
    ScheduleCase('overnight, morning rule', local(2026, 11, 17, 6, 0), OFF, OVERNIGHT),
    ScheduleCase('whole day start', local(2026, 11, 16, 0, 0), ON, WHOLE_MONDAY),
    ScheduleCase('whole day end', local(2026, 11, 17, 0, 0), OFF, WHOLE_MONDAY),
    ScheduleCase('whole day, Sunday', local(2026, 11, 15, 0, 0), None, WHOLE_MONDAY),
    ScheduleCase('override', local(2026, 11, 16, 12, 10), ON,
                 override=O(ON, local(2026, 11, 16, 12, 0), local(2026, 11, 16, 12, 30))),
    # koniec nadpisania (bez tej chwili) – stan sprzed nadpisania
    ScheduleCase('override end', local(2026, 11, 16, 12, 30), OFF,
                 override=O(ON, local(2026, 11, 16, 12, 0), local(2026, 11, 16, 12, 30))),
    ScheduleCase('expired override', local(2026, 11, 16, 12, 40), OFF,
                 override=O(ON, local(2026, 11, 16, 12, 0), local(2026, 11, 16, 12, 30))),
    ScheduleCase('override end, device was on', local(2026, 11, 16, 8, 15), ON, MORNING,
                 override=O(ON, local(2026, 11, 16, 8, 5), local(2026, 11, 16, 8, 15), previous=ON)),

    # Dni tygodnia
    ScheduleCase('weekdays rule on Friday', local(2026, 11, 20, 8, 0), ON, (R(time(8), days=WEEKDAYS),)),
    ScheduleCase('weekdays rule on Saturday', local(2026, 11, 21, 8, 0), None, (R(time(8), days=WEEKDAYS),)),
    ScheduleCase('disabled rule', local(2026, 11, 16, 8, 0), None, (R(time(8), enabled=False),)),
    ScheduleCase('two rules at the same time, same state', local(2026, 11, 16, 8, 0), ON,
                 (R(time(8), days=(MONDAY,)), R(time(8)))),

    # Przerwa w działaniu workera: tylko najnowsza przegapiona reguła
    ScheduleCase('missed rule', local(2026, 11, 16, 18, 20), ON, EVENING, since=local(2026, 11, 16, 17, 0)),
    ScheduleCase('missed rules, latest wins', local(2026, 11, 16, 23, 30), OFF, EVENING,
                 since=local(2026, 11, 16, 17, 0)),
    ScheduleCase('missed rules, no new one', local(2026, 11, 16, 17, 0), None, EVENING,
                 since=local(2026, 11, 16, 12, 0)),
    ScheduleCase('long downtime, weekly rule', local(2026, 11, 16, 12, 0), ON, (R(time(8), days=(WEDNESDAY,)),),
                 since=local(2026, 10, 1, 0, 0)),
    ScheduleCase('long downtime, latest of daily rules', local(2026, 11, 16, 12, 0), OFF, EVENING,
                 since=local(2026, 10, 1, 0, 0)),

    # Nadpisanie: reguły w trakcie czekają, po końcu – najnowsza z nich
    ScheduleCase('rule during override waits', local(2026, 11, 16, 18, 0), OFF, EVENING,
                 override=O(OFF, local(2026, 11, 16, 17, 50), local(2026, 11, 16, 18, 30))),
    ScheduleCase('override end, rule from its time', local(2026, 11, 16, 18, 30), ON, EVENING,
                 override=O(OFF, local(2026, 11, 16, 17, 50), local(2026, 11, 16, 18, 30))),
    ScheduleCase('override end, rule before it not repeated', local(2026, 11, 16, 18, 30), OFF, EVENING,
                 override=O(ON, local(2026, 11, 16, 18, 10), local(2026, 11, 16, 18, 30), previous=OFF)),
    ScheduleCase('override off, end', local(2026, 11, 16, 12, 30), ON,
                 override=O(OFF, local(2026, 11, 16, 12, 0), local(2026, 11, 16, 12, 30), previous=ON)),

    # Światło: target_state z jasnością i bielą albo samą jasnością
    ScheduleCase('light rule', local(2026, 11, 16, 18, 0), WARM_30, (R(time(18), WARM_30),), kind='light_rgbcct'),
    ScheduleCase('light rule, brightness only', local(2026, 11, 16, 22, 0), {'brightness': 10},
                 (R(time(22), {'brightness': 10}),), kind='light_rgbcct'),

    # Czas lokalny (Europe/Warsaw), nie UTC
    ScheduleCase('local time, winter', utc(2026, 11, 15, 23, 30), ON, (R(time(0, 30), days=(MONDAY,)),)),
    ScheduleCase('local time, summer', utc(2026, 7, 1, 22, 30), ON, (R(time(0, 30)),)),
    ScheduleCase('not in UTC', utc(2026, 11, 16, 0, 30), None, (R(time(0, 30)),)),

    # Zmiana czasu wiosną: 29.03.2026 zegar przeskakuje z 02:00 CET na 03:00 CEST (01:00 UTC).
    # Reguła z brakującej godziny wykonuje się o 03:00, tylko raz.
    ScheduleCase('spring, rule 02:30 at 03:00 CEST', utc(2026, 3, 29, 1, 0), ON, (R(time(2, 30)),)),
    ScheduleCase('spring, rule 02:30 not again at 03:30', utc(2026, 3, 29, 1, 30), None, (R(time(2, 30)),)),
    ScheduleCase('spring, day after', utc(2026, 3, 30, 0, 30), ON, (R(time(2, 30)),)),
    # Zmiana czasu jesienią: 25.10.2026 zegar cofa się z 03:00 CEST na 02:00 CET (01:00 UTC).
    # Reguła z powtórzonej godziny wykonuje się raz, w pierwszym przejściu.
    ScheduleCase('autumn, rule 02:30 at 02:30 CEST', utc(2026, 10, 25, 0, 30), ON, (R(time(2, 30)),)),
    ScheduleCase('autumn, rule 02:30 not at 02:30 CET', utc(2026, 10, 25, 1, 30), None, (R(time(2, 30)),)),
)


class ScheduleTests(SimpleTestCase):
    def event(self, case):
        override = case.override.override() if case.override else None
        return schedule.event([r.rule() for r in case.rules], override, case.start, case.now)

    def test_cases(self):
        for case in SCHEDULE_CASES:
            with self.subTest(case.name):
                result = self.event(case)
                self.assertEqual(result.state if result else None, case.expected)

    def test_reason(self):
        rules = [r.rule() for r in MORNING]
        rule_event = schedule.event(rules, None, local(2026, 11, 16, 7, 59), local(2026, 11, 16, 8, 0, 3))
        self.assertEqual((rule_event.reason, rule_event.at, rule_event.rule),
                         (schedule.RULE, local(2026, 11, 16, 8, 0), rules[0]))
        override = O(OFF, local(2026, 11, 16, 8, 50), local(2026, 11, 16, 9, 30)).override()
        active = schedule.event(rules, override, local(2026, 11, 16, 9, 0), local(2026, 11, 16, 9, 0, 5))
        self.assertEqual((active.reason, active.at), (schedule.OVERRIDE, local(2026, 11, 16, 8, 50)))
        ended = schedule.event(rules, override, local(2026, 11, 16, 9, 30), local(2026, 11, 16, 9, 30, 5))
        self.assertEqual((ended.reason, ended.at, ended.rule),
                         (schedule.OVERRIDE_END, local(2026, 11, 16, 9, 30), rules[1]))


class RuleInstantTests(SimpleTestCase):
    def test_instants(self):
        cases = (
            ('winter', date(2026, 11, 16), time(18), utc(2026, 11, 16, 17, 0)),
            ('summer', date(2026, 7, 1), time(18), utc(2026, 7, 1, 16, 0)),
            ('spring, missing hour', date(2026, 3, 29), time(2, 30), utc(2026, 3, 29, 1, 0)),
            ('autumn, repeated hour', date(2026, 10, 25), time(2, 30), utc(2026, 10, 25, 0, 30)),
        )
        for name, day, moment, expected in cases:
            with self.subTest(name):
                self.assertEqual(schedule.rule_instant(day, moment), expected)

    def test_occurrences(self):
        rule = R(time(8), days=(MONDAY, WEDNESDAY)).rule()
        self.assertEqual(schedule.occurrences(rule, local(2026, 11, 16, 0, 0), local(2026, 11, 19, 0, 0)),
                         [utc(2026, 11, 16, 7, 0), utc(2026, 11, 18, 7, 0)])

    def test_next_occurrence(self):
        rule = R(time(8), days=(MONDAY, WEDNESDAY)).rule()
        self.assertEqual(schedule.next_occurrence(rule, local(2026, 11, 16, 7, 0)), utc(2026, 11, 16, 7, 0))
        # w chwili wykonania – następne
        self.assertEqual(schedule.next_occurrence(rule, local(2026, 11, 16, 8, 0)), utc(2026, 11, 18, 7, 0))
        self.assertEqual(schedule.next_occurrence(rule, local(2026, 11, 18, 9, 0)), utc(2026, 11, 23, 7, 0))
        self.assertIsNone(schedule.next_occurrence(R(time(8), days=()).rule(), local(2026, 11, 16, 7, 0)))

    def test_lookback(self):
        rule = R(time(8)).rule()
        found = schedule.occurrences(rule, local(2025, 1, 1), local(2026, 11, 16, 12, 0))
        self.assertEqual(len(found), 8)
        self.assertEqual(found[-1], utc(2026, 11, 16, 7, 0))


class ConflictTests(SimpleTestCase):
    def test_conflict(self):
        cases = (
            ('same time, different state', R(time(8)), R(time(8), OFF), True),
            ('same time, same state', R(time(8)), R(time(8)), False),
            ('different days', R(time(8), days=(MONDAY,)), R(time(8), OFF, days=(TUESDAY,)), False),
            ('different time', R(time(8)), R(time(8, 1), OFF), False),
        )
        for name, a, b, expected in cases:
            with self.subTest(name):
                self.assertEqual(schedule.conflict(a.rule(), b.rule()), expected)
