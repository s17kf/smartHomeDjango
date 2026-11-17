# Zasady pracy w repozytorium

Zasady dla osób i agentów (AI) pracujących w `smartHomeDjango`. Opis
aplikacji i uruchamiania: [`README.md`](README.md).

## Rola w systemie

Aplikacja Django projektu **smart home**: UI, użytkownicy, lokalizacje,
urządzenia i reguły automatyzacji. Zastępuje wcześniejszy podział na
`smartHomeServer` (Django REST Framework) i `smartHomeFrontend` (React).

Z urządzeniami rozmawia wyłącznie przez broker MQTT, w schemacie kanonicznym
(`home/<device_id>/…`). Protokoły konkretnych urządzeń zna tylko gateway
(`smart-home-gateway`), schemat tematów i payloadów opisuje `smart-home-mqtt`.

Uruchomienie całego stosu (compose, broker, baza, reverse proxy) i decyzje
architektoniczne żyją w repo nadrzędnym
[`smart-home-project`](https://github.com/s17kf/smart-home-project). To repo
nie odwołuje się do ścieżek repo nadrzędnego ani innych repozytoriów
projektu – trzymamy tu kod aplikacji i ustalenia o niej samej.

## Zasady architektury

- UI to szablony Django renderowane po stronie serwera. Interaktywność przez
  HTMX, Alpine.js tylko tam, gdzie HTMX nie wystarczy (drobne skrypty
  w przeglądarce – `hx-on`, np. skróty dni w formularzu reguły). Bez
  budowania frontendu (Node).
- Wygląd: Bootstrap z motywem ciemnym (`data-bs-theme="dark"` w
  `base.html`) – klasy motywu (`text-body-secondary`, `link-body-emphasis`,
  …), bez własnych kolorów; `style.css` tylko dla tego, czego Bootstrap nie
  ma. Treść jako karty w siatce (`row-cols-1` na telefonie), nagłówek strony
  w bloku `page_title` albo `heading` (ścieżka `breadcrumb.html`).
- Zasoby statyczne (CSS, JS, ikony) w repo i serwowane lokalnie, nie z CDN –
  UI działa bez internetu. Serwuje je sama aplikacja (whitenoise),
  w produkcji po `collectstatic` (opis w README, sekcja Static files).
- Wszystkie widoki UI wymagają zalogowania (sesje Django). Bez otwartej
  rejestracji – konta zakłada admin.
  Wymusza to `LoginRequiredMiddleware`, więc nowe widoki są chronione bez
  dodatkowego kodu. Wyjątek tylko przez `@login_not_required` z komentarzem,
  dlaczego (np. endpoint z własnym uwierzytelnianiem). Panel admina ma własne
  logowanie i wymaga `is_staff`.
- Fragmenty dla HTMX to zwykłe widoki zwracające kawałek strony (np. karta
  urządzenia po poleceniu, pola stanu w formularzu reguły). Żądania HTMX bez ważnej sesji dostają `HX-Redirect` na logowanie
  (`devices/middleware.py`), żeby formularz logowania nie trafił do
  fragmentu. Token CSRF wysyła HTMX w nagłówku (`hx-headers` na `<body>`).
- Zmiany kart przez SSE (`devices/events.py`, widok `device_events`,
  rozszerzenie `htmx-ext-sse`): strumień `text/event-stream` co 1 s sprawdza
  w bazie cache stanu, status systemu i nadpisania i wysyła zmienione karty
  (`sse-swap="device-<slug>"`); po 5 min serwer kończy strumień,
  przeglądarka łączy się ponownie. Bez `LISTEN/NOTIFY` (kod niezależny od
  silnika bazy). gunicorn `gthread` – połączenie trzyma wątek, nie proces;
  przed zmianą liczby wątków pomiar RAM na RPi.
- Sterowanie z karty (`devices/control.py`, widok `device_set`): pola
  kontrolek → polecenie `set`, sprawdzenie według rodzaju (`kinds.py`),
  publikacja krótkim połączeniem tylko do dostępnego urządzenia. Karta
  pokazuje „wysłano” i odpytuje co 1 s (najwyżej 5 razy), aż `state` w cache
  potwierdzi polecenie – kanału błędów `set` w kontrakcie nie ma.
- Widoki, które zmieniają stan, przyjmują tylko POST (`@require_POST`, żeby
  działała ochrona CSRF). Adres powrotu z formularza (`next`) bierzemy przez
  `get_next_url`, która nie przepuszcza adresów spoza strony.
- Panel admina Django służy do zarządzania urządzeniami i lokalizacjami.
- Sterowanie urządzeniami: komendy na `home/<slug>/set`, stan z `…/state`,
  `…/telemetry` i `…/availability`. Nie dopisujemy kodu, który komunikuje się
  z urządzeniami bezpośrednio (GPIO, HTTP do urządzeń).
- Urządzenie: `slug` – identyfikator w tematach MQTT (`[a-z0-9]+(-[a-z0-9]+)*`,
  najwyżej 50 znaków), niezmienny po utworzeniu (`pk` zostaje kluczem
  w bazie); `kind` – rodzaj z kontraktu (`devices/kinds.py`, `smart-home-mqtt`
  `specs/payloads.md`); `driver` i `params` – trafiają do `config`
  w brokerze, sprawdza je gateway. W `params` bez haseł.
- Baza jest źródłem konfiguracji urządzeń w brokerze: sygnały modelu
  (`devices/signals.py`) publikują `config` po zapisie i czyszczą tematy
  po usunięciu, po zatwierdzeniu transakcji. Urządzeń nie zmieniamy przez
  `QuerySet.update()` (bez sygnałów). Publikacja przez krótkie połączenie
  (`devices/mqtt.py`) – bez stałego klienta MQTT w procesach gunicorna.
- Jedyny stały klient MQTT to worker (`manage.py mqtt_worker`,
  `devices/worker.py`): subskrybuje stany, zapisuje cache (`DeviceState`
  po slugu, bez klucza obcego; `SystemStatus` z heartbeatem) i po każdym
  połączeniu synchronizuje `config` z bazą. Widoki czytają stan z cache,
  nie z brokera. Logika workera (`Worker`) nie zależy od pętli paho –
  testy podają jej wiadomości wprost.
- Reguły automatyzacji to osobny model (`Rule`), niezależny od typu
  urządzenia: przypięty do urządzenia, „w te dni o tej godzinie (czas
  lokalny) ustaw `target_state`”, stan walidowany per rodzaj
  (`Kind.validate_target`). Semantyka – ADR 0010 w repo nadrzędnym:
  - które reguły się wykonują, liczą czyste funkcje `schedule.py` (reguły,
    nadpisanie, przedział `(since, now]`) – te same dla workera i UI, bez
    bazy i zegara;
  - worker (`automation.py`, co 5 s) wysyła `set` przy wykonaniu reguły
    i ponawia go do potwierdzenia przez `state` (co minutę, najwyżej 5 razy,
    tylko do dostępnego urządzenia). Między regułami nic nie wysyła – nie
    dopisujemy wyrównywania stanu, cofałoby ręczne zmiany. Koniec
    sprawdzonego przedziału jest w bazie (`SystemStatus.rules_checked_at`),
    po restarcie wykonuje się tylko najnowsza przegapiona reguła;
  - nadpisanie z wygaśnięciem (`Override`, „włącz na N minut” z karty) –
    widok od razu wysyła `set` i zapamiętuje stan sprzed nadpisania; reguły
    w trakcie czekają, koniec (także anulowanie: `until` = teraz) obsługuje
    worker.
- JSON API tylko tam, gdzie jest potrzebne (np. komendy głosowe), jako
  zwykłe widoki w tym projekcie. DRF dopiero, gdy API urośnie.
- Baza: PostgreSQL. Bez kodu zależnego od silnika bazy (surowy SQL, funkcje
  tylko jednego silnika), dopóki nie będzie naprawdę potrzebny.
- Konfiguracja ze zmiennych środowiskowych (`DJANGO_SECRET_KEY`,
  `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DATABASE_URL`, `DJANGO_HTTPS`,
  `MQTT_HOST`, `MQTT_PORT`, `MQTT_BACKEND_USER`, `MQTT_BACKEND_PASSWORD`) –
  lista i wartości domyślne w README (sekcja Configuration), nowe zmienne
  dopisujemy tam.
- HTTPS kończy reverse proxy (Caddy), aplikacja mówi zwykłym HTTP.
  `DJANGO_HTTPS` włącza zaufanie do `X-Forwarded-Proto` i ciasteczka
  `Secure`. Przekierowanie na HTTPS i HSTS należą do proxy, nie do Django.
  Sekretów ani adresów hostów nie wpisujemy do kodu.
- Docelowy sprzęt: Raspberry Pi 4 (arm64). Obraz ma wariant amd64 i arm64,
  pilnujemy zużycia RAM (liczba procesów i workerów, ciężkie zależności).

## Struktura katalogów

```
.
├── smartHomeSite/   # projekt Django: ustawienia, główne urls, wsgi/asgi
├── devices/         # aplikacja: modele, widoki, szablony, statyki, komendy
├── templates/       # szablony widoków spoza aplikacji (panel admina, logowanie)
├── locale/          # tłumaczenia en/pl
├── Dockerfile, .dockerignore, docker-entrypoint.sh   # obraz aplikacji
├── gunicorn.conf.py # ustawienia gunicorna (obraz)
├── requirements.txt
├── manage.py
├── CONTRIBUTING.md
└── README.md
```

### `smartHomeSite/`

- Ustawienia projektu i główny `urls.py` – adresy z prefiksem języka
  (`i18n_patterns`), w tym logowanie i wylogowanie (widoki
  `django.contrib.auth`).
- Bez logiki aplikacji – ta trafia do aplikacji (`devices/` lub kolejnej).

### `devices/`

- Modele, widoki, `urls.py`, admin i menu; rodzaje urządzeń (pola `set`,
  `state`, `telemetry`) w `kinds.py`.
- Worker MQTT: `worker.py` (połączenie, cache, synchronizacja `config`),
  `automation.py` (reguły i nadpisania); chwile wykonania reguł – `schedule.py`.
- Szablony w `templates/devices/`. Karta urządzenia per rodzaj:
  `templates/devices/cards/<kind>.html` (rama i pomiary w `cards/base.html`);
  stan do wyświetlenia (urządzenie + cache, dostępność z powodem) –
  `status.py`, filtry szablonów – `templatetags/devices_extras.py`.
- UI reguł: formularz w `forms.py` (pola stanu docelowego per rodzaj,
  podmieniane przez HTMX po zmianie urządzenia), szablony
  w `templates/devices/rules/` (karta reguły, lista, formularz).
- Statyki w `static/devices/`, biblioteki zewnętrzne w
  `static/devices/vendor/` ([Biblioteki frontendowe](#biblioteki-frontendowe)),
  komendy zarządzania w `management/commands/`.
- Testy w pakiecie `tests/`: moduł na obszar (`test_models.py`,
  `test_views.py`, …), wspólne pomoce w `tests/base.py`.

### `templates/`

- Tylko szablony widoków spoza projektu: nadpisania (np.
  `admin/base_site.html`) i szablony, których szukają widoki
  `django.contrib.auth` (`registration/login.html`). Szablony aplikacji
  trzymamy w aplikacji.

### `locale/`

- Pliki `.po` dla `en` i `pl`. Skompilowane `.mo` są poza gitem.

### Obraz Dockera

- Jeden obraz – produkcyjny (`python:3.14-slim`, amd64 i arm64). Praca
  lokalna: `runserver` na hoście (README, Installation).
- Przy budowie: tłumaczenia (`msgfmt` w osobnym etapie, gettext nie trafia
  do obrazu) i `collectstatic` z wyłączonym DEBUG.
- Start: `migrate` tylko przed serwerem WWW (domyślna komenda `gunicorn`),
  inne komendy z obrazu (worker, testy) bez migracji – bazę migruje jedna
  usługa.
- Użytkownik nie-root (`django`, uid 10001), kod i statyki należą do roota –
  aplikacja nie zapisuje plików lokalnie, stan trzyma w bazie.
- Pakiety systemowe w obrazie tylko gdy niezbędne (rozmiar, RAM na RPi).

## Konwencje

- Kod, identyfikatory i teksty źródłowe UI – po angielsku. Komentarze
  i dokumentacja – po polsku; wyjątkiem jest `README.md` (opis repozytorium
  po angielsku).
- Każdy tekst widoczny w UI przechodzi przez tłumaczenia: `gettext` /
  `gettext_lazy` w Pythonie, `{% trans %}` / `{% blocktrans %}` w
  szablonach. Po zmianie tekstów:
  `python manage.py makemessages -l en -l pl` i uzupełnienie
  `locale/pl/LC_MESSAGES/django.po` w tym samym commicie.
- Czas: `USE_TZ = True`, `TIME_ZONE = 'Europe/Warsaw'`. Znaczniki czasu
  i czas trwania przez `timezone.now()` (UTC), godziny i dni harmonogramów
  przez `timezone.localtime()`. Nie używamy `datetime.now()` ani naiwnych
  dat zapisywanych do bazy.
- Zmiana modeli razem z migracją (`makemigrations`) w tym samym commicie.
- Testy: `DJANGO_DEBUG=true DATABASE_URL=postgres://… python manage.py test`
  (bez `DJANGO_SECRET_KEY` ustawienia wymagają trybu debug; Django zakłada
  i usuwa osobną bazę `test_<nazwa>`). Nowe widoki i logika reguł / harmonogramów
  – z testami.
- Zachowanie reguł opisuje tabela `SCHEDULE_CASES`
  w `devices/tests/test_schedule.py`: reguły, nadpisanie, przedział kroku
  workera i oczekiwany stan do ustawienia (dni tygodnia, przegapione
  reguły, nadpisanie, zmiana czasu). Tabelę sprawdzamy dla
  `schedule.event` i kroku workera (`test_automation.py` – `set` wysłany
  albo nie przy danym stanie w cache). Zmianę zachowania zaczynamy od
  zmiany tabeli. Testy widoków dziedziczą po `LoggedInTestCase` z
  `devices/tests/base.py` (klient zalogowany jako zwykły użytkownik); test
  `LoginRequiredTests` sprawdza przekierowanie na logowanie dla wszystkich
  adresów `devices`.
- Testy nie łączą się z brokerem MQTT: runner (`devices/tests/runner.py`)
  podmienia go na `MemoryBroker` (retained jak w Mosquitto, lista publikacji).
  Testy publikacji dziedziczą po `BrokerTestMixin` (czysty broker
  w `self.broker`), a publikację po zatwierdzeniu transakcji uruchamia
  `captureOnCommitCallbacks(execute=True)`.
- Zależności przypięte do wersji (`==`) w `requirements.txt`. Przed dodaniem
  nowej sprawdzamy, czy działa na arm64 i ile kosztuje w RAM.

## Biblioteki frontendowe

Biblioteki CSS/JS leżą w `devices/static/devices/vendor/<pakiet>/`: gotowe
pliki z pakietu npm danej wersji, bez zmian, razem z jego `LICENSE`.
Szablony ładują je przez `{% static %}` – test `LocalStaticFilesTests`
sprawdza, że strony nie ładują CSS ani JS z zewnątrz.

| Pakiet npm | Wersja | Pliki z pakietu |
|---|---|---|
| `bootstrap` | 5.3.3 | `dist/css/bootstrap.min.css`, `dist/js/bootstrap.bundle.min.js` (z `.map`) |
| `bootstrap-icons` | 1.11.3 | `font/bootstrap-icons.min.css`, `font/fonts/bootstrap-icons.woff2`, `.woff` |
| `htmx.org` | 2.0.11 | `dist/htmx.min.js` (katalog `vendor/htmx/`) |
| `htmx-ext-sse` | 2.2.4 | `dist/sse.min.js` (katalog `vendor/htmx-ext-sse/`) |

Dodanie lub aktualizacja biblioteki:

- Tarball z `https://registry.npmjs.org/<pakiet>/-/<pakiet>-<wersja>.tgz`,
  suma sprawdzona z polem `dist.integrity` w
  `https://registry.npmjs.org/<pakiet>/<wersja>`.
- Kopiujemy pliki używane w szablonach i to, do czego same się odwołują
  (fonty w `url()`, mapy źródeł z `sourceMappingURL`), z zachowaniem
  względnych ścieżek (np. `fonts/` obok CSS ikon). `collectstatic`
  w produkcji przerywa, gdy odwołanie prowadzi do brakującego pliku.
- Tabela, ścieżki w szablonach i pliki – w jednym commicie.

## Git

Katalog główny jest lokalnym repozytorium git, służącym do zapisu historii prac.

- Commity wykonujemy **w miarę często** – po każdej sensownej zmianie.
- Wiadomość commita: **preferowany sam subject**.
- Krótkie body dodajemy tylko wtedy, gdy coś naprawdę wymaga doprecyzowania.
- Agent (AI) **nie wykonuje commitów** – przedstawia jedynie propozycję
  wiadomości commita, a commit wykonuje użytkownik samodzielnie.
