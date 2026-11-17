import re

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from . import kinds, schedule

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

    def _stored(self, field):
        if self.pk is None:
            return None
        return type(self).objects.filter(pk=self.pk).values_list(field, flat=True).first()

    def _stored_slug(self):
        return self._stored('slug')

    def clean(self):
        super().clean()
        # Walidatory pól pomijają wartości „puste” – także `[]`.
        if not isinstance(self.params, dict):
            raise ValidationError({'params': _('Parameters must be a JSON object.')})
        stored = self._stored_slug()
        if stored is not None and stored != self.slug:
            raise ValidationError({'slug': _('The slug cannot be changed – create a new device instead.')})
        # `target_state` reguł jest sprawdzany według rodzaju urządzenia.
        stored_kind = self._stored('kind')
        if stored_kind is not None and stored_kind != self.kind and self.rules.exists():
            raise ValidationError({'kind': _('The kind cannot be changed while the device has rules – '
                                             'delete its rules first.')})

    def save(self, *args, **kwargs):
        # Zmiana sluga to inne tematy MQTT (stare zostałyby w brokerze) – także
        # poza formularzem (shell, import).
        stored = self._stored_slug()
        if stored is not None and stored != self.slug:
            raise ValueError(f'slug of device {self.pk} cannot change ({stored!r} → {self.slug!r})')
        super().save(*args, **kwargs)


class DeviceState(models.Model):
    """Ostatni stan, pomiary i dostępność urządzenia z brokera (cache, zapisuje worker MQTT).

    Kluczem jest slug, nie urządzenie: retained stan urządzenia, które powstanie
    w Django później (np. przy imporcie), jest w cache od razu. `state`
    i `telemetry` bez pola `ts` – czas wiadomości w `*_ts` (UTC).
    """
    slug = models.SlugField(max_length=50, unique=True)
    state = models.JSONField(null=True, blank=True)
    state_ts = models.DateTimeField(null=True, blank=True)
    telemetry = models.JSONField(null=True, blank=True)
    telemetry_ts = models.DateTimeField(null=True, blank=True)
    availability = models.CharField(max_length=10, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['slug']

    def __str__(self):
        return self.slug


class SystemStatus(models.Model):
    """Jeden wiersz (pk=1): status gatewaya z `gateway/status` i stan workera MQTT."""
    gateway_status = models.CharField(max_length=10, blank=True)
    worker_connected = models.BooleanField(default=False)
    worker_seen_at = models.DateTimeField(null=True, blank=True)
    rules_checked_at = models.DateTimeField(null=True, blank=True)
    """Koniec przedziału, do którego worker sprawdził reguły – po restarcie wykonuje najnowszą przegapioną."""
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'system status'

    def __str__(self):
        return 'system status'

    @classmethod
    def get(cls):
        return cls.objects.get_or_create(pk=1)[0]


def validate_days(value):
    """Dni tygodnia reguły: niepusta lista liczb 0–6 (0 = poniedziałek) bez powtórzeń."""
    if (not isinstance(value, list) or not value
            or not all(isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 6 for d in value)
            or len(set(value)) != len(value)):
        raise ValidationError(_('Days must be a non-empty list of distinct numbers 0–6 (0 = Monday).'))


class Rule(models.Model):
    """Reguła automatyzacji: w wybrane dni o godzinie `time` (czas lokalny) ustaw `target_state`.

    Semantyka (przegapione reguły, nadpisanie, zmiana czasu) – `schedule.py`
    i ADR 0010 w repo nadrzędnym. Dni tygodnia jako lista w `JSONField` – bez
    `ArrayField`, żeby kod nie zależał od silnika bazy.
    """
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='rules')
    name = models.CharField(max_length=100, blank=True)
    days = models.JSONField(
        default=list, validators=[validate_days],
        help_text=_('Days of the week, 0 = Monday … 6 = Sunday, e.g. [0, 1, 2, 3, 4].'),
    )
    time = models.TimeField(help_text=_('Local time.'))
    target_state = models.JSONField(
        help_text=_('Fields of a set command for the device kind, e.g. switch {"on": true}; '
                    'light {"on": true, "brightness": 30, "mode": "cct", "ct": 2700}.'),
    )
    enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ['device', 'time', 'pk']

    def __str__(self):
        return f'{self.device}: {self.name} ({self.time:%H:%M})' if self.name else f'{self.device}: {self.time:%H:%M}'

    @property
    def label(self):
        return self.name or f'{self.time:%H:%M}'

    def clean(self):
        super().clean()
        errors = {}
        try:
            validate_days(self.days)
        except ValidationError as exc:
            errors['days'] = exc.messages
        else:
            self.days = sorted(self.days)
        if self.device_id is None:
            raise ValidationError(errors or {'device': _('Choose a device.')})
        kind = self.device.kind_spec
        if not kind.accepts_rules:
            errors['device'] = _('%(kind)s devices do not accept rules.') % {'kind': kind.label}
        else:
            try:
                self.target_state = kind.validate_target(self.target_state)
            except kinds.InvalidCommand as exc:
                errors['target_state'] = str(exc)
        if errors:
            raise ValidationError(errors)
        self._check_conflict()

    def _check_conflict(self):
        # Dwie reguły o tej samej porze z różnym stanem – nie wiadomo, która wygrywa.
        # Także z wyłączonymi regułami: włączenie reguły nie przechodzi przez walidację formularza.
        if self.time is None:
            return
        for other in Rule.objects.filter(device_id=self.device_id).exclude(pk=self.pk):
            if schedule.conflict(self, other):
                raise ValidationError(
                    _('Rule "%(rule)s" sets a different state at the same time.'),
                    params={'rule': other.label},
                )


class Override(models.Model):
    """Nadpisanie z wygaśnięciem („włącz na N minut”): stan do `until` (UTC, bez tej chwili).

    Reguły w trakcie czekają. Po końcu (albo anulowaniu – `until` = teraz)
    worker ustawia stan z najnowszej reguły od `created_at`, a bez niej –
    `previous_state` (stan sprzed nadpisania), i usuwa nadpisanie.
    Przedłużenie z karty zmienia `state` i `until`, a `created_at`
    i `previous_state` zostają.
    """
    device = models.OneToOneField(Device, on_delete=models.CASCADE, related_name='override')
    state = models.JSONField()
    previous_state = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now)
    until = models.DateTimeField()

    def __str__(self):
        return f'{self.device}: {self.state} until {self.until:%Y-%m-%d %H:%M} UTC'

    def clean(self):
        super().clean()
        if self.device_id is None:
            return
        kind = self.device.kind_spec
        errors = {}
        for field_name in ('state', 'previous_state'):
            try:
                setattr(self, field_name, kind.validate_target(getattr(self, field_name)))
            except kinds.InvalidCommand as exc:
                errors[field_name] = str(exc)
        if errors:
            raise ValidationError(errors)


class AutomationState(models.Model):
    """Ostatnie zdarzenie automatyzacji urządzenia (reguła, nadpisanie) i jego wysyłanie (zapisuje worker MQTT).

    Worker wysyła `set` przy zdarzeniu i ponawia go, aż `state` potwierdzi
    zmianę (`automation.py`).
    """
    PENDING = 'pending'
    CONFIRMED = 'confirmed'
    FAILED = 'failed'
    OUTCOMES = [(PENDING, _('waiting for confirmation')), (CONFIRMED, _('confirmed')),
                (FAILED, _('no confirmation'))]

    device = models.OneToOneField(Device, on_delete=models.CASCADE, related_name='automation')
    desired = models.JSONField()
    reason = models.CharField(max_length=20)
    changed_at = models.DateTimeField()
    outcome = models.CharField(max_length=10, choices=OUTCOMES, default=PENDING)
    outcome_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)

    def __str__(self):
        return f'{self.device}: {self.desired} ({self.outcome})'
