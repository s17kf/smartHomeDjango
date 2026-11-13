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
  HTMX, Alpine.js tylko tam, gdzie HTMX nie wystarczy. Bez budowania
  frontendu (Node).
- Zasoby statyczne (CSS, JS, ikony) w repo i serwowane lokalnie, nie z CDN –
  UI działa bez internetu. Serwuje je sama aplikacja (whitenoise),
  w produkcji po `collectstatic` (opis w README, sekcja Static files).
- Wszystkie widoki UI wymagają zalogowania (sesje Django). Bez otwartej
  rejestracji – konta zakłada admin.
  Wymusza to `LoginRequiredMiddleware`, więc nowe widoki są chronione bez
  dodatkowego kodu. Wyjątek tylko przez `@login_not_required` z komentarzem,
  dlaczego (np. endpoint z własnym uwierzytelnianiem). Panel admina ma własne
  logowanie i wymaga `is_staff`.
- Panel admina Django służy do zarządzania urządzeniami i lokalizacjami.
- Sterowanie urządzeniami: komendy na `home/<id>/set`, stan z `…/state`,
  `…/telemetry` i `…/availability`. Nie dopisujemy kodu, który komunikuje się
  z urządzeniami bezpośrednio (GPIO, HTTP do urządzeń).
- Reguły automatyzacji to osobny model, niezależny od typu urządzenia:
  przypięty do urządzenia, z `target_state` walidowanym per rodzaj
  urządzenia.
- JSON API tylko tam, gdzie jest potrzebne (np. komendy głosowe), jako
  zwykłe widoki w tym projekcie. DRF dopiero, gdy API urośnie.
- Baza: PostgreSQL. Bez kodu zależnego od silnika bazy (surowy SQL, funkcje
  tylko jednego silnika), dopóki nie będzie naprawdę potrzebny.
- Konfiguracja ze zmiennych środowiskowych (`DJANGO_SECRET_KEY`,
  `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DATABASE_URL`) – lista i wartości
  domyślne w README (sekcja Configuration), nowe zmienne dopisujemy tam.
  Sekretów ani adresów hostów nie wpisujemy do kodu.
- Docelowy sprzęt: Raspberry Pi 4 (arm64). Obraz ma wariant amd64 i arm64,
  pilnujemy zużycia RAM (liczba procesów i workerów, ciężkie zależności).

## Stan przejściowy

Część kodu powstała przed przejściem na MQTT i zostanie zastąpiona. Nie
rozwijamy jej – poprawiamy tylko wtedy, gdy blokuje bieżącą pracę:

- sterowanie przekaźnikiem przez GPIO (`gpiocontrol` w
  `devices/device_helpers.py`) i pliki konfiguracyjne urządzeń
  (`Device.config_file`) – w obrazie nie działa (brak `pinctrl`),
- typ `relay-periodic` i modele `RelayPeriodic*` – harmonogram przechodzi do
  reguł automatyzacji,
- jQuery (`devices/static/devices/js/`) – interaktywność przechodzi na HTMX.

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

- Modele, widoki, `urls.py`, admin i menu.
- Szablony w `templates/devices/`. Status i szczegóły urządzenia mają osobne
  szablony per typ w `templates/devices/details/`
  (`<typ>_status.html`, `<typ>_details.html`).
- Statyki w `static/devices/`, biblioteki zewnętrzne w
  `static/devices/vendor/` ([Biblioteki frontendowe](#biblioteki-frontendowe)),
  komendy zarządzania w `management/commands/`, testy w `tests.py`.

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
  – z testami. Testy widoków dziedziczą po `LoggedInTestCase` (klient
  zalogowany jako zwykły użytkownik); test `LoginRequiredTests` sprawdza
  przekierowanie na logowanie dla wszystkich adresów `devices`.
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
| `jquery` | 3.7.1 | `dist/jquery.min.js` |

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
