from datetime import timedelta

from django import template
from django.utils import timezone
from django.utils.formats import date_format, number_format
from django.utils.timesince import timesince
from django.utils.translation import gettext as _

from .. import schedule
from ..control import OVERRIDE_PRESETS
from ..forms import DAY_CHOICES

register = template.Library()


@register.filter
def rgb_css(value):
    """`[r, g, b]` ze stanu światła → `rgb(r, g, b)` do atrybutu style; inna wartość → ''.

    Stan pochodzi z brokera, więc do CSS trafiają tylko liczby całkowite 0–255.
    """
    if (isinstance(value, list) and len(value) == 3
            and all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in value)):
        return 'rgb({}, {}, {})'.format(*value)
    return ''


@register.filter
def reading(value):
    """Pomiar do wyświetlenia: najwyżej 2 miejsca po przecinku, bez zer na końcu, separator wg języka."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    if isinstance(value, float):
        value = round(value, 2)
        if value.is_integer():
            value = int(value)
    return number_format(value)


@register.filter
def ago(moment):
    """Ile czasu minęło – jedna jednostka („3 minuty temu”), poniżej minuty „przed chwilą”."""
    if not moment:
        return ''
    if timezone.now() - moment < timedelta(minutes=1):
        return _('just now')
    return _('%(time)s ago') % {'time': timesince(moment, depth=1)}


@register.filter
def rgb_hex(value):
    """`[r, g, b]` → `#rrggbb` dla `<input type="color">`; inna wartość → biały."""
    if rgb_css(value):
        return '#{:02x}{:02x}{:02x}'.format(*value)
    return '#ffffff'


@register.simple_tag
def override_presets():
    """Przyciski nadpisania na karcie: [(on, opis grupy, [(minuty, napis)])]."""
    minutes = [(m, _('%(n)s h') % {'n': m // 60} if m % 60 == 0 else _('%(n)s min') % {'n': m})
               for m in OVERRIDE_PRESETS]
    return [('true', _('On for'), minutes), ('false', _('Off for'), minutes)]


@register.filter
def days_label(days):
    """Dni tygodnia reguły: „codziennie”, „pn–pt”, „weekend” albo lista skrótów."""
    days = sorted(set(days or []))
    if days == list(range(7)):
        return _('Every day')
    if days == list(range(5)):
        return _('Mon–Fri')
    if days == [5, 6]:
        return _('Weekend')
    names = dict(DAY_CHOICES)
    return ', '.join(str(names[d]) for d in days if d in names)


@register.filter
def next_run(rule):
    """Najbliższe wykonanie reguły: „dziś 18:00”, „jutro 06:00”, „pon. 18:00” (czas lokalny)."""
    instant = schedule.next_occurrence(rule, timezone.now())
    if instant is None:
        return ''
    local = timezone.localtime(instant)
    days = (local.date() - timezone.localdate()).days
    clock = local.strftime('%H:%M')
    if days == 0:
        return _('today %(time)s') % {'time': clock}
    if days == 1:
        return _('tomorrow %(time)s') % {'time': clock}
    return f"{date_format(local, 'D')} {clock}"
