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
  UI działa bez internetu.
- Wszystkie widoki UI wymagają zalogowania (sesje Django). Bez otwartej
  rejestracji – konta zakłada admin.
- Panel admina Django służy do zarządzania urządzeniami i lokalizacjami.
- Sterowanie urządzeniami: komendy na `home/<id>/set`, stan z `…/state`,
  `…/telemetry` i `…/availability`. Nie dopisujemy kodu, który komunikuje się
  z urządzeniami bezpośrednio (GPIO, HTTP do urządzeń).
- Reguły automatyzacji to osobny model, niezależny od typu urządzenia:
  przypięty do urządzenia, z `target_state` walidowanym per rodzaj
  urządzenia.
- JSON API tylko tam, gdzie jest potrzebne (np. komendy głosowe), jako
  zwykłe widoki w tym projekcie. DRF dopiero, gdy API urośnie.
- Konfiguracja ze zmiennych środowiskowych (`SECRET_KEY`, `DEBUG`,
  `ALLOWED_HOSTS`, baza). Sekretów ani adresów hostów nie wpisujemy do kodu.
- Docelowy sprzęt: Raspberry Pi 4 (arm64). Obraz ma wariant amd64 i arm64,
  pilnujemy zużycia RAM (liczba procesów i workerów, ciężkie zależności).

## Stan przejściowy

Część kodu powstała przed przejściem na MQTT i zostanie zastąpiona. Nie
rozwijamy jej – poprawiamy tylko wtedy, gdy blokuje bieżącą pracę:

- sterowanie przekaźnikiem przez GPIO (`gpiocontrol` w
  `devices/device_helpers.py`) i pliki konfiguracyjne urządzeń
  (`Device.config_file`),
- typ `relay-periodic` i modele `RelayPeriodic*` – harmonogram przechodzi do
  reguł automatyzacji,
- obraz deweloperski: `Dockerfile` (ubuntu, cron), `build.sh`, `run.sh`,
  `assets/` – do zastąpienia obrazem `python:*-slim` z gunicornem,
- ustawienia na sztywno w `smartHomeSite/settings.py`, SQLite (docelowo
  PostgreSQL), `USE_TZ = False`,
- jQuery, Bootstrap i ikony ładowane z CDN.

## Struktura katalogów

```
.
├── smartHomeSite/   # projekt Django: ustawienia, główne urls, wsgi/asgi
├── devices/         # aplikacja: modele, widoki, szablony, statyki, komendy
├── templates/       # nadpisania szablonów spoza aplikacji (panel admina)
├── locale/          # tłumaczenia en/pl
├── assets/          # obraz deweloperski: instalacja, fikstury, konfiguracje urządzeń
├── Dockerfile, build.sh, run.sh   # obraz deweloperski (do zastąpienia)
├── requirements.txt
├── manage.py
├── CONTRIBUTING.md
└── README.md
```

### `smartHomeSite/`

- Ustawienia projektu i główny `urls.py` – adresy z prefiksem języka
  (`i18n_patterns`).
- Bez logiki aplikacji – ta trafia do aplikacji (`devices/` lub kolejnej).

### `devices/`

- Modele, widoki, `urls.py`, admin i menu.
- Szablony w `templates/devices/`. Status i szczegóły urządzenia mają osobne
  szablony per typ w `templates/devices/details/`
  (`<typ>_status.html`, `<typ>_details.html`).
- Statyki w `static/devices/`, komendy zarządzania w
  `management/commands/`, testy w `tests.py`.

### `templates/`

- Tylko szablony nadpisujące szablony spoza projektu (np.
  `admin/base_site.html`). Szablony aplikacji trzymamy w aplikacji.

### `locale/`

- Pliki `.po` dla `en` i `pl`. Skompilowane `.mo` są poza gitem.

### `assets/`

- Pliki obrazu deweloperskiego (zob. [Stan przejściowy](#stan-przejściowy)).
- Fikstury z danymi (`db_fixtures/*.json`) i konfiguracje urządzeń
  (`devices/*.json`, poza `example_device.json`) są poza gitem.

## Konwencje

- Kod, identyfikatory i teksty źródłowe UI – po angielsku. Komentarze
  i dokumentacja – po polsku; wyjątkiem jest `README.md` (opis repozytorium
  po angielsku).
- Każdy tekst widoczny w UI przechodzi przez tłumaczenia: `gettext` /
  `gettext_lazy` w Pythonie, `{% trans %}` / `{% blocktrans %}` w
  szablonach. Po zmianie tekstów:
  `python manage.py makemessages -l en -l pl` i uzupełnienie
  `locale/pl/LC_MESSAGES/django.po` w tym samym commicie.
- Zmiana modeli razem z migracją (`makemigrations`) w tym samym commicie.
- Testy: `python manage.py test`. Nowe widoki i logika reguł / harmonogramów
  – z testami.
- Zależności przypięte do wersji (`==`) w `requirements.txt`. Przed dodaniem
  nowej sprawdzamy, czy działa na arm64 i ile kosztuje w RAM.

## Git

Katalog główny jest lokalnym repozytorium git, służącym do zapisu historii prac.

- Commity wykonujemy **w miarę często** – po każdej sensownej zmianie.
- Wiadomość commita: **preferowany sam subject**.
- Krótkie body dodajemy tylko wtedy, gdy coś naprawdę wymaga doprecyzowania.
- Agent (AI) **nie wykonuje commitów** – przedstawia jedynie propozycję
  wiadomości commita, a commit wykonuje użytkownik samodzielnie.
