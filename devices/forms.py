"""Formularz reguły automatyzacji: pola stanu docelowego zależne od rodzaju urządzenia.

Stan docelowy (`target_state`) składa się z pól formularza: `power` (włącz /
wyłącz / bez zmiany), dla światła także `brightness`, `light_mode` (biel albo
kolor), `ct` i `color`. Sprawdza go model (`Rule.clean` → `Kind.validate_target`),
błąd trafia do ukrytego pola `target_state` i szablon pokazuje go przy polach
stanu. Po zmianie urządzenia HTMX pobiera pola stanu od nowa
(`views.rule_state_fields`).
"""

import re

from django import forms
from django.utils.translation import gettext_lazy as _

from .kinds import KINDS, LIGHT_RGBCCT
from .models import Device, Rule

DAY_CHOICES = [(0, _('Mon')), (1, _('Tue')), (2, _('Wed')), (3, _('Thu')), (4, _('Fri')), (5, _('Sat')),
               (6, _('Sun'))]
# Skróty dni w formularzu: (napis, dni)
DAY_PRESETS = ((_('Every day'), (0, 1, 2, 3, 4, 5, 6)), (_('Mon–Fri'), (0, 1, 2, 3, 4)), (_('Weekend'), (5, 6)))
POWER_CHOICES = [('true', _('Turn on')), ('false', _('Turn off')), ('', _('Keep on / off'))]
LIGHT_MODE_CHOICES = [('', _('Keep')), ('cct', _('White')), ('rgb', _('Colour'))]
_HEX_COLOR = re.compile(r'\A#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})\Z')


def rule_devices():
    """Urządzenia, które przyjmują reguły (bez czujników)."""
    names = [name for name, kind in KINDS.items() if kind.accepts_rules]
    return Device.objects.filter(kind__in=names).select_related('location').order_by('location__name', 'name')


class DeviceChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f'{obj.name} ({obj.location})'


class RuleForm(forms.ModelForm):
    device = DeviceChoiceField(queryset=Device.objects.none(), label=_('Device'))
    days = forms.TypedMultipleChoiceField(choices=DAY_CHOICES, coerce=int, label=_('Days'),
                                          widget=forms.CheckboxSelectMultiple)
    time = forms.TimeField(label=_('Time'), widget=forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'))
    power = forms.ChoiceField(choices=POWER_CHOICES, required=False, label=_('On / off'))
    brightness = forms.IntegerField(required=False, min_value=1, max_value=100, label=_('Brightness (%)'))
    light_mode = forms.ChoiceField(choices=LIGHT_MODE_CHOICES, required=False, label=_('Colour mode'))
    ct = forms.IntegerField(required=False, min_value=2700, max_value=6500, initial=2700, label=_('White (K)'))
    color = forms.RegexField(_HEX_COLOR, required=False, initial='#ffffff', label=_('Colour'))
    # Liczone w clean() z pól powyżej; nie renderowane – tu trafia błąd stanu z modelu.
    target_state = forms.JSONField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Rule
        fields = ['device', 'name', 'days', 'time', 'target_state', 'enabled']
        labels = {'name': _('Name'), 'enabled': _('Enabled')}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['device'].queryset = rule_devices()
        self.fields['name'].help_text = _('Optional, e.g. "Evening".')
        if self.instance.pk and not self.is_bound:
            self.initial.update(self._initial_state(self.instance.target_state or {}))

    @staticmethod
    def _initial_state(state):
        initial = {'power': {True: 'true', False: 'false'}.get(state.get('on'), '')}
        if 'brightness' in state:
            initial['brightness'] = state['brightness']
        if state.get('mode') in ('cct', 'rgb'):
            initial['light_mode'] = state['mode']
        if 'ct' in state:
            initial['ct'] = state['ct']
        rgb = state.get('rgb')
        if isinstance(rgb, list) and len(rgb) == 3:
            initial['color'] = '#{:02x}{:02x}{:02x}'.format(*rgb)
        return initial

    @property
    def selected_device(self):
        """Urządzenie wybrane w formularzu (dane POST, wartość początkowa albo reguła) – dla pól stanu."""
        if self.is_bound:
            value = self.data.get(self.add_prefix('device'))
        else:
            value = self.initial.get('device') or self.instance.device_id
        if not value:
            return None
        try:
            return self.fields['device'].queryset.get(pk=value)
        except (Device.DoesNotExist, ValueError, TypeError):
            return None

    @property
    def days_selected(self) -> set[int]:
        """Zaznaczone dni (dane POST albo wartość początkowa) – dla pól wyboru w szablonie."""
        selected = set()
        for value in self['days'].value() or []:
            try:
                selected.add(int(value))
            except (TypeError, ValueError):
                pass
        return selected

    @property
    def time_value(self) -> str:
        """Godzina do `<input type="time">`: HH:MM z reguły albo tekst wpisany przez użytkownika."""
        value = self['time'].value()
        if hasattr(value, 'strftime'):
            return value.strftime('%H:%M')
        return value or ''

    @property
    def selected_kind(self):
        device = self.selected_device
        return device.kind_spec if device else None

    def clean(self):
        cleaned = super().clean()
        device = cleaned.get('device')
        if device is None:
            return cleaned
        power = cleaned.get('power') or ''
        state = {}
        if power:
            state['on'] = power == 'true'
        # Wyłączenie światła ignoruje jasność i kolor.
        if device.kind_spec is LIGHT_RGBCCT and power != 'false':
            if cleaned.get('brightness'):
                state['brightness'] = cleaned['brightness']
            mode = cleaned.get('light_mode')
            if mode == 'cct' and cleaned.get('ct') is not None:
                state.update(mode='cct', ct=cleaned['ct'])
            elif mode == 'cct':
                self.add_error('ct', _('Enter the white temperature.'))
            elif mode == 'rgb' and cleaned.get('color'):
                match = _HEX_COLOR.match(cleaned['color'])
                state.update(mode='rgb', rgb=[int(part, 16) for part in match.groups()])
            elif mode == 'rgb':
                self.add_error('color', _('Choose a colour.'))
        cleaned['target_state'] = state
        return cleaned
