from django import template
from django.utils.formats import number_format
from django.utils.timesince import timesince
from django.utils.translation import gettext as _

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
    """Ile czasu minęło – jedna jednostka („3 minuty temu”)."""
    if not moment:
        return ''
    return _('%(time)s ago') % {'time': timesince(moment, depth=1)}


@register.filter
def rgb_hex(value):
    """`[r, g, b]` → `#rrggbb` dla `<input type="color">`; inna wartość → biały."""
    if rgb_css(value):
        return '#{:02x}{:02x}{:02x}'.format(*value)
    return '#ffffff'
