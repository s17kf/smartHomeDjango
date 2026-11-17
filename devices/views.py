import logging
from datetime import timedelta

from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views import generic
from django.views.decorators.http import require_POST

from . import control, events, forms, mqtt
from . import status as device_status
from .kinds import InvalidCommand
from .models import Device, Location, Override, Rule

log = logging.getLogger(__name__)


class LocationListView(generic.ListView):
    template_name = 'devices/location_list.html'
    context_object_name = 'locations'

    def get_queryset(self):
        return Location.objects.all()

    def get_context_data(self, **kwargs):
        """Karty lokalizacji: liczba urządzeń i dostępnych (jedno zapytanie do cache dla wszystkich)."""
        context = super().get_context_data(**kwargs)
        statuses = device_status.statuses(Device.objects.filter(location__in=context['locations']))
        summaries = {location.pk: {'location': location, 'devices': 0, 'available': 0}
                     for location in context['locations']}
        for status in statuses:
            summary = summaries[status.device.location_id]
            summary['devices'] += 1
            summary['available'] += status.available
        context['location_summaries'] = list(summaries.values())
        return context


class FavouritesView(generic.ListView):
    template_name = 'devices/favourites.html'
    context_object_name = 'favourites_devices'

    def get_queryset(self):
        return Device.objects.none()


def _location_context(location_id):
    location = get_object_or_404(Location, pk=location_id)
    devices = Device.objects.filter(location=location).order_by('name')
    return {'location': location, 'statuses': device_status.statuses(devices)}


def location(request, location_id):
    return render(request, 'devices/location.html', _location_context(location_id))


def device(request, slug):
    device_ = get_object_or_404(Device.objects.select_related('location'), slug=slug)
    return render(request, 'devices/device.html', {
        'device': device_, 'status': device_status.status(device_),
        'rules': _rules().filter(device=device_) if device_.kind_spec.accepts_rules else None,
    })


def _card(request, status_, **context):
    return render(request, status_.template, {'status': status_, **context})


def device_events(request):
    """Strumień SSE ze zmienionymi kartami urządzeń: `?location=<id>` albo `?device=<slug>` (`events.py`)."""
    devices = Device.objects.select_related('location').order_by('name')
    if 'device' in request.GET:
        devices = devices.filter(slug=request.GET['device'])
    elif request.GET.get('location', '').isdigit():
        devices = devices.filter(location_id=int(request.GET['location']))
    else:
        raise Http404('location or device required')
    devices = list(devices)
    if not devices:
        raise Http404('no devices')
    response = StreamingHttpResponse(events.stream(events.CardStream(devices, request)),
                                     content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    # bez buforowania w proxy (nginx; Caddy przepuszcza text/event-stream od razu)
    response['X-Accel-Buffering'] = 'no'
    return response


def device_card(request, slug):
    """Karta jednego urządzenia – fragment odświeżany przez HTMX.

    Z `cmd` i `try` w adresie (po wysłaniu polecenia): sprawdza, czy stan już
    je potwierdził; jeśli nie – karta odpytuje dalej co 1 s, po
    `CONFIRM_TRIES` próbach pokazuje „brak potwierdzenia”.
    """
    device_ = get_object_or_404(Device.objects.select_related('location'), slug=slug)
    status_ = device_status.status(device_)
    command, attempt = control.pending_command(request.GET)
    if command is None or device_.kind_spec.satisfied(status_.state, command):
        return _card(request, status_)
    if attempt >= control.CONFIRM_TRIES:
        return _card(request, status_, error=_('No confirmation from the device – check that it is available.'))
    return _card(request, status_, pending=True, refresh_url=control.refresh_url(device_, command, attempt + 1))


@require_POST
def device_set(request, slug):
    """Polecenie z karty → `home/<slug>/set`; odpowiedź – karta czekająca na potwierdzenie stanu."""
    device_ = get_object_or_404(Device.objects.select_related('location'), slug=slug)
    status_ = device_status.status(device_)
    try:
        command = device_.kind_spec.validate_set(control.parse_command(request.POST))
    except InvalidCommand as exc:
        return _card(request, status_, error=str(exc))
    # Polecenie do niedostępnego urządzenia przepada (bez kolejkowania) – nie wysyłamy.
    if not status_.available:
        return _card(request, status_, error=_('The device is unavailable (%(reason)s) – the command was not sent.')
                     % {'reason': status_.reason_label})
    try:
        control.send(device_, command)
    except mqtt.MqttError as exc:
        log.warning('%s: set not sent: %s', device_.slug, exc)
        return _card(request, status_, error=_('The command was not sent: %(error)s') % {'error': exc})
    return _card(request, status_, pending=True, refresh_url=control.refresh_url(device_, command, 1))


@require_POST
def device_override(request, slug):
    """Nadpisanie z karty: „włącz / wyłącz na N minut” (`on`, `minutes`) albo anulowanie (`cancel`).

    Nadpisanie od razu wysyła `set` (jak zwykłe sterowanie) i zapamiętuje
    stan sprzed niego; worker MQTT wstrzymuje reguły do `until`, a potem
    ustawia stan z reguły z tego czasu albo stan sprzed nadpisania
    (`automation.py`). Przedłużenie zostawia stan sprzed pierwszego
    nadpisania. Anulowanie przesuwa `until` na teraz – koniec obsługuje
    worker tak samo jak wygaśnięcie.
    """
    device_ = get_object_or_404(Device.objects.select_related('location'), slug=slug)
    now = timezone.now()
    if 'cancel' in request.POST:
        Override.objects.filter(device=device_, until__gt=now).update(until=now)
        return _card(request, device_status.status(device_))
    status_ = device_status.status(device_)
    try:
        state, minutes = control.parse_override(request.POST)
        state = device_.kind_spec.validate_target(state)
    except InvalidCommand as exc:
        return _card(request, status_, error=str(exc))
    if not status_.available:
        return _card(request, status_, error=_('The device is unavailable (%(reason)s) – the command was not sent.')
                     % {'reason': status_.reason_label})
    Override.objects.update_or_create(
        device=device_, defaults={'state': state, 'until': now + timedelta(minutes=minutes)},
        create_defaults={'state': state, 'until': now + timedelta(minutes=minutes), 'created_at': now,
                         'previous_state': control.previous_state(status_)},
    )
    status_ = device_status.status(device_)
    try:
        control.send(device_, state)
    except mqtt.MqttError as exc:
        log.warning('%s: override set not sent: %s', device_.slug, exc)
        return _card(request, status_, error=_('The override was saved, but the command was not sent: %(error)s. '
                                               'The MQTT worker will send it.') % {'error': exc})
    return _card(request, status_, pending=True, refresh_url=control.refresh_url(device_, state, 1))


def _safe_url(request, url, default):
    """`url` tylko w obrębie tej strony (bez `javascript:` i obcych hostów), inaczej `default`."""
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()},
                                               require_https=request.is_secure()):
        return url
    return default


def get_next_url(request, default='/'):
    """Adres powrotu z formularza (`next`) – tylko w obrębie tej strony, inaczej `default`."""
    return _safe_url(request, request.POST.get('next'), default)


# Reguły automatyzacji

def _rules():
    return Rule.objects.select_related('device', 'device__location').order_by('device__name', 'time', 'pk')


def rule_list(request):
    """Lista reguł, filtr `?device=<slug>` (HTMX podmienia samą listę)."""
    rules = _rules()
    selected = None
    slug = request.GET.get('device')
    if slug:
        selected = Device.objects.filter(slug=slug).first()
        if selected is not None:
            rules = rules.filter(device=selected)
    return render(request, 'devices/rules/list.html',
                  {'rules': rules, 'devices': forms.rule_devices(), 'selected': selected})


def rule_form(request, pk=None):
    """Dodanie (`?device=<slug>` wybiera urządzenie) albo edycja reguły; po zapisie powrót do `next`."""
    rule = get_object_or_404(Rule, pk=pk) if pk is not None else None
    if request.method == 'POST':
        form = forms.RuleForm(request.POST, instance=rule)
        if form.is_valid():
            form.save()
            return redirect(get_next_url(request, default=reverse('devices:rule_list')))
    else:
        initial = {}
        if rule is None:
            initial = {'days': list(range(7)), 'power': 'true'}
            device_ = forms.rule_devices().filter(slug=request.GET.get('device', '')).first()
            if device_ is not None:
                initial['device'] = device_.pk
        form = forms.RuleForm(instance=rule, initial=initial)
    next_url = request.POST.get('next') or request.GET.get('next') or ''
    return render(request, 'devices/rules/form.html', {
        'form': form, 'rule': rule, 'next': next_url, 'day_presets': forms.DAY_PRESETS,
        'cancel_url': _safe_url(request, next_url, reverse('devices:rule_list')),
    })


def rule_state_fields(request):
    """Pola stanu formularza dla urządzenia `?device=<pk>` – fragment po zmianie urządzenia (HTMX)."""
    form = forms.RuleForm(initial={'device': request.GET.get('device'), 'power': 'true'})
    return render(request, 'devices/rules/state_fields.html', {'form': form})


@require_POST
def rule_toggle(request, pk):
    """Włączenie / wyłączenie reguły – odpowiedź to karta reguły.

    Bez walidacji formularza: reguły o tej samej porze z różnym stanem są
    odrzucane także wtedy, gdy któraś jest wyłączona (`Rule._check_conflict`).
    """
    rule = get_object_or_404(_rules(), pk=pk)
    rule.enabled = not rule.enabled
    rule.save(update_fields=['enabled'])
    return render(request, 'devices/rules/card.html', {'rule': rule})


@require_POST
def rule_delete(request, pk):
    """Usunięcie reguły; przy HTMX pusta odpowiedź (karta znika), inaczej powrót do `next`."""
    get_object_or_404(Rule, pk=pk).delete()
    if request.headers.get('HX-Request'):
        return HttpResponse('')
    return redirect(get_next_url(request, default=reverse('devices:rule_list')))
