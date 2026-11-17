import re

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from . import kinds

# Slug – identyfikator urządzenia w tematach `home/<slug>/…` (ADR 0004 w repo
# nadrzędnym, `smart-home-mqtt` `specs/topics.md`). SlugField dopuszcza też
# wielkie litery i `_`, więc wzorzec jest węższy. Najwyżej 50 znaków.
SLUG_PATTERN = r'[a-z0-9]+(-[a-z0-9]+)*'
validate_device_slug = RegexValidator(
    rf'\A{SLUG_PATTERN}\Z',
    _('Lowercase letters and digits, words separated by single hyphens, e.g. plug-living-room.'),
)

# Rodzina urządzeń (`shelly`, `tasmota`, `w1`, …). Listy sterowników Django nie
# zna – sprawdza je gateway, przy nieznanym urządzenie jest `offline`.
validate_driver = RegexValidator(
    r'\A[a-z0-9_]+\Z',
    _('Lowercase letters, digits and underscores, e.g. shelly.'),
)

# Parametry trafiają do retained `config` w brokerze – bez haseł (urządzenia
# łączą się z brokerem same).
SECRET_KEY_RE = re.compile(r'pass|secret|token', re.IGNORECASE)


def secret_keys(value, prefix=''):
    """Klucze (także zagnieżdżone), których nazwa wygląda na sekret."""
    if isinstance(value, dict):
        for key, item in value.items():
            if SECRET_KEY_RE.search(key):
                yield prefix + key
            yield from secret_keys(item, f'{prefix}{key}.')
    elif isinstance(value, list):
        for item in value:
            yield from secret_keys(item, prefix)


def validate_params(value):
    if not isinstance(value, dict):
        raise ValidationError(_('Parameters must be a JSON object.'))
    found = sorted(secret_keys(value))
    if found:
        raise ValidationError(
            _('Parameters look like a secret: %(keys)s. Passwords do not belong in the device config.'),
            params={'keys': ', '.join(found)},
        )


class Location(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Device(models.Model):
    location = models.ForeignKey(Location, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    slug = models.SlugField(
        max_length=50, unique=True, validators=[validate_device_slug],
        help_text=_('Device identifier in MQTT topics (home/&lt;slug&gt;/…). Cannot be changed later.'),
    )
    kind = models.CharField(max_length=20, choices=kinds.CHOICES)
    driver = models.CharField(
        max_length=50, validators=[validate_driver],
        help_text=_('Device family handled by the gateway: shelly, tasmota, w1.'),
    )
    params = models.JSONField(
        default=dict, blank=True, validators=[validate_params],
        help_text=_('Driver parameters, e.g. shelly: {"prefix": "shelly/plug1", "component": "switch:0"}; '
                    'tasmota: {"topic": "nous1"}; w1: {"sensor": "28-00000a99077c", "interval_s": 60}.'),
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def kind_spec(self) -> kinds.Kind:
        return kinds.KINDS[self.kind]

    def _stored_slug(self):
        if self.pk is None:
            return None
        return type(self).objects.filter(pk=self.pk).values_list('slug', flat=True).first()

    def clean(self):
        super().clean()
        # Walidatory pól pomijają wartości „puste” – także `[]`.
        if not isinstance(self.params, dict):
            raise ValidationError({'params': _('Parameters must be a JSON object.')})
        stored = self._stored_slug()
        if stored is not None and stored != self.slug:
            raise ValidationError({'slug': _('The slug cannot be changed – create a new device instead.')})

    def save(self, *args, **kwargs):
        # Zmiana sluga to inne tematy MQTT (stare zostałyby w brokerze) – także
        # poza formularzem (shell, import).
        stored = self._stored_slug()
        if stored is not None and stored != self.slug:
            raise ValueError(f'slug of device {self.pk} cannot change ({stored!r} → {self.slug!r})')
        super().save(*args, **kwargs)
