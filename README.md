# „Die absolute Abfahrt" – Werkzeuge für die Orga

Drei Webanwendungen für die Veranstaltung, die als **ein Dienst** laufen:

| Bereich | öffentlich | im Backoffice | mehr |
| --- | --- | --- | --- |
| Kennzeichen | Antragsformular für Durchfahrtsberechtigungen | Sichten, Genehmigen, Karten drucken, Liste für die Straßensperre | [kennzeichen/README.md](kennzeichen/README.md) |
| Presse | Akkreditierung für Fotografen und Videografen | Abholliste, Gebühren, ausstehende Bilder | [presse/README.md](presse/README.md) |
| Helfer | Monitor und Unterschriften-Tablet, per Token | Schichten, Aufgaben, T-Shirts, Funkgeräte, Schlüssel | [helfer/README.md](helfer/README.md) |

Was nur einen Bereich betrifft, steht in dessen README. Hier steht, was alle
drei verbindet: wie sie zusammengesetzt sind, wie man sie startet und wie die
Konfiguration aufgebaut ist.

## Wie es zusammenhängt

Ein Prozess, verteilt nach **Hostname**:

| Adresse | was dort liegt |
| --- | --- |
| `kennzeichen.example.de` | Antragsformular, öffentlich |
| `presse.example.de` | Akkreditierung, öffentlich |
| `helfer.example.de` | Monitor und Unterschriften-Tablet, per Token |
| `admin.example.de` | **alle drei Backoffices**, eine Anmeldung |

Nach Hostname und nicht nach Pfad, weil die öffentlichen Adressen auf
Plakaten, in Mails und in QR-Codes stehen – sie müssen bleiben, wie sie sind.
Das Backoffice liegt umgekehrt unter **einer** Adresse, weil dieselben paar
Leute alle drei betreuen: `admin.example.de/kennzeichen`, `/presse`,
`/helfer`, oben eine Zeile zum Wechseln. Eine Anmeldung öffnet alle drei.

Die Daten liegen in **einer PostgreSQL-Datenbank**, jeder Bereich in seinem
eigenen Schema: `kennzeichen`, `presse`, `helfer`. Die Bereiche haben
gleichnamige Tabellen (`einstellung`, `mail_out`), die Schemas halten sie
auseinander. Jeder Bereich bringt seine Tabellen beim Start selbst auf Stand –
nummerierte Dateien in `<bereich>/app/migrationen/`, eingespielt von
[kern/db.py](kern/db.py).

Der Dienst spricht **nur HTTP**. TLS, Weiterleitung und Zertifikate macht der
Reverse Proxy davor, siehe [deploy/](deploy/).

## Aufbau

```text
dienst/        setzt die drei zusammen und verteilt nach Hostname
kern/          was alle drei teilen: Konten und Anmeldung, Veranstaltungen,
               Backoffice-Rahmen, Stilblatt, Suche, Datenbank, Mailversand
kennzeichen/   Kennzeichen-Anträge     ┐
presse/        Presse-Akkreditierung   ├ je app/, .env.example, README.md
helfer/        Helfer-Dashboard        ┘
deploy/        Unit, nginx, Sicherung, Löschwerkzeug, Vorlagen für den Betrieb
docs/          die Projektpläne
tests/         Tests für Kennzeichen, kern und den Dienst
compose.yaml   PostgreSQL für die Entwicklung
```

Jeder Bereich ist ein eigenes Paket – `kennzeichen.app`, `presse.app`,
`helfer.app` – mit eigenem Schema und eigener Konfiguration. In `kern/`
liegt nur, was wirklich Wort für Wort gleich war. `worker.py`, `mail.py` und
`db.py` in Kennzeichen und Presse tragen bloß denselben Namen und gehen um
Hunderte Zeilen auseinander; sie bleiben, wo sie sind.

Vorlagen sucht jede Anwendung erst bei sich, dann in `kern/templates`. Eine
gemeinsame Vorlage lässt sich also überschreiben, indem man eine gleichnamige
danebenlegt, ohne `kern` anzufassen.

## Lokal starten

Erst die Datenbank. [compose.yaml](compose.yaml) startet einen PostgreSQL in
Docker, erreichbar unter `127.0.0.1:55432` (Benutzer, Passwort und Datenbank
heißen `abfahrt`). Ohne `DATABASE_URL` nehmen alle drei Bereiche genau diesen.

```bash
docker compose up -d
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Linux: .venv/bin/python
cp kennzeichen/.env.example kennzeichen/.env
cp presse/.env.example      presse/.env
cp helfer/.env.example      helfer/.env
.venv/Scripts/python.exe -m kern.konto admin                  # das eigene Admin-Konto
```

Schlüssel und Hostnamen gelten für alle drei und gehören deshalb in die
Umgebung, nicht in die drei `.env`:

```bash
export APP_SECRET_KEY=lokal-irgendwas
export HOST_KENNZEICHEN=kennzeichen.localhost HOST_PRESSE=presse.localhost \
       HOST_HELFER=helfer.localhost HOST_ADMIN=admin.localhost
.venv/Scripts/python.exe -m uvicorn dienst.main:app --reload --port 8080
```

| Adresse | was dort liegt |
| --- | --- |
| <http://kennzeichen.localhost:8080/> | Antragsformular |
| <http://presse.localhost:8080/> | Presse-Anmeldung |
| <http://admin.localhost:8080/> | Backoffice, alle drei Bereiche |

Browser lösen `*.localhost` ohne Eintrag in der `hosts`-Datei auf den eigenen
Rechner auf. So läuft lokal dieselbe Verteilung wie im Betrieb.

Ohne `HOST_…` geht alles über Pfade: das Backoffice unter
<http://127.0.0.1:8080/kennzeichen> usw., die öffentlichen Seiten unter
`/oeffentlich/<bereich>/`. Das taugt nur für einen Blick – Stilblatt und
Absenden der öffentlichen Formulare zeigen auf die Wurzel und kommen dort
nicht an.

Lokal über `http` bleibt `COOKIE_SECURE=auto` richtig: das Secure-Flag wird nur
gesetzt, wenn der Browser über HTTPS kam.

Jeder Bereich lässt sich auch **einzeln** starten (`python -m app` in seinem
Verzeichnis, Ports 8080, 8081, 8082). So starten die Tests ihre Server; wie
es geht, steht in der README des Bereichs.

## Betrieb

```bash
python -m dienst
```

Bind-Adresse und vertraute Proxys kommen aus `BIND` und `FORWARDED_ALLOW_IPS`,
`--proxy-headers` ist fest eingeschaltet. Das ist Absicht: Ohne dieses Flag
steht in jedem Antrag und jedem Protokoll die IP des Proxys statt die des
Besuchers, das Login-Rate-Limit greift für alle gemeinsam, und das Secure-Flag
am Cookie fehlt. An einer Kommandozeile vergisst man es irgendwann – in einer
Env-Datei nicht.

Ein zusammengesetzter ASGI-Dienst ruft die Lebensläufe seiner Teile nicht von
selbst auf; [dienst/main.py](dienst/main.py) startet sie ausdrücklich. Im
Protokoll steht deshalb beim Start **dreimal `starte Bereich …`** – fehlt
einer, hat seine Konfiguration nicht gepasst.

Installation, nginx, Sicherung, Prüfliste vor dem Livegang und das Löschen
der Personendaten nach der Veranstaltung: [deploy/README.md](deploy/README.md).

## Konfiguration

Ausschließlich über Env-Variablen, auf zwei Ebenen.

**Für alle drei** – die Umgebung des Prozesses, im Betrieb
`/etc/abfahrt/dienst.env` (Vorlage [deploy/dienst.env.example](deploy/dienst.env.example)):

| Variable | wofür |
| --- | --- |
| `BIND` | Adresse und Port. Liegt der Proxy auf einem anderen Host, die eigene IP – und der Port per Firewall auf den Proxy beschränkt. |
| `FORWARDED_ALLOW_IPS` | die IP des Reverse Proxys. Nur von dort werden `X-Forwarded-For` und `X-Forwarded-Proto` geglaubt. |
| `DATABASE_URL` | die PostgreSQL-Datenbank, für alle drei dieselbe. Leer heißt: der Entwicklungs-Container aus `compose.yaml`. |
| `HOST_KENNZEICHEN`, `HOST_PRESSE`, `HOST_HELFER`, `HOST_ADMIN` | welcher Hostname zu welchem Bereich gehört |
| `APP_SECRET_KEY` | signiert die CSRF-Token. Ohne ihn erzeugt **jeder Bereich** beim Start seinen eigenen – dann passen Formulare nicht zum Bereich, an den sie gehen, und nach jedem Neustart nicht mehr. |
| `ADMIN_PASSWORD_HASH` | nur für den Übergang, siehe *Konten* unten. Erzeugen mit `python -m kern.passwort`. |
| `KENNZEICHEN_ENV`, `PRESSE_ENV`, `HELFER_ENV` | wo die drei ihre eigenen Werte finden |

**Je Bereich** eine Datei – lokal `<bereich>/.env`, im Betrieb
`/etc/abfahrt/<bereich>.env`, worauf die drei Zeiger oben zeigen. Darin
Veranstaltung, Kontakt, Mailversand und alles Fachliche.
Was jeweils drinsteht, erklärt die README des Bereichs.

Die Regel dazwischen: **die Umgebung schlägt die Datei.** Eine dort gesetzte
Variable gilt also für alle drei. Genau deshalb steht der Schlüssel in der
Umgebung, und dasselbe gilt für `DATABASE_URL`: eine Datenbank, die Schemas
trennen die Bereiche.

## Konten

Ins Backoffice meldet sich jeder mit seinem **eigenen Konto** an:
Mailadresse und Passwort, eine Anmeldung für alle Bereiche, die das Konto
sehen darf. Ein Konto hat

- eine **Rolle**: *Admin* (alles, dazu die Konten), *Orga* (darf in seinen
  Bereichen alles bearbeiten) oder *Lesend* (sieht, ändert nichts);
- seine **Bereiche**: Kennzeichen, Presse, Helfer – einzeln freizugeben;
- ein **Kürzel**, das als „bearbeitet von“ in den Daten landet.

Admins laden unter `admin.example.de/konten` ein: die Person bekommt eine
Mail mit einem Link und legt damit ihr Passwort fest. Vergessene Passwörter
setzt jeder selbst über *Passwort vergessen* zurück. Konten, Sitzungen und
Links stehen im Schema `kern` ([kern/konten.py](kern/konten.py)); die Seiten
dazu in [kern/konten_app.py](kern/konten_app.py).

## Veranstaltungen

Der ILRC hat mehr als eine Veranstaltung, die Helfer braucht. Jede steht
unter `admin.example.de/veranstaltungen` mit Name, Kurzname, Tagen, Ort,
Anmeldezeitraum und Status (*in Planung*, *angekündigt*, *Anmeldung offen*,
*geschlossen*, *archiviert*). Schichten, Programm, Aufgaben und Ausgaben des
Helferbereichs gehören immer zu einer; Helfer und Fahrzeugstamm gehören
keiner, es sind Jahr für Jahr dieselben.

Mit welcher gearbeitet wird, wählt jeder oben im Helferbereich, gemerkt im
Browser. Ohne Wahl gilt die nächste, die noch nicht vorbei ist – und die
nehmen auch Monitor, Zeitplan-Abruf und Helferabgleich. Kennzeichen und
Presse hängen noch an keiner Veranstaltung.

Den ersten Admin legt `python -m kern.konto admin` an. Wer bisher mit dem
gemeinsamen Passwort (`ADMIN_PASSWORD_HASH`) gearbeitet hat, kann sich damit
auch weiter anmelden und unter **Konten** sein eigenes anlegen – bis ein
Admin seine Einladung eingelöst hat. Ab dann gilt es nicht mehr.

## Tests

Keine Testbibliothek, nur Standardbibliothek – `python datei.py`,
Rückgabewert 0 heißt bestanden. Alles aus dem Hauptordner:

```bash
.venv/Scripts/python.exe tests/test_dienst.py     # drei Bereiche in einem Prozess, Verteilung, eine Anmeldung
.venv/Scripts/python.exe tests/test_konten.py     # Konten: Einladung, Rechte, Sperren, Passwort vergessen
.venv/Scripts/python.exe tests/test_kern_konten.py # Konten, Sitzungen und Links in der Datenbank
.venv/Scripts/python.exe tests/test_kern_db.py    # Datenbankzugriff und Migrationen
.venv/Scripts/python.exe tests/test_kern_veranstaltungen.py # Veranstaltungen und die Vorgabe
.venv/Scripts/python.exe tests/test_auth.py       # Anmeldung, Token, CSRF, Rate Limit
.venv/Scripts/python.exe tests/test_suchen.py     # Suche mit Umlauten, Python gegen JavaScript
node tests/test_suchen_js.js
```

Dazu die Tests der Bereiche:

- Kennzeichen: übrige Dateien in [tests/](tests/), siehe [tests/README.md](tests/README.md)
- Presse: [presse/tests/](presse/tests/), siehe [presse/README.md](presse/README.md#tests)
- Helfer: [helfer/tests/](helfer/tests/), siehe [helfer/README.md](helfer/README.md#tests)

Die Tests brauchen den PostgreSQL aus `compose.yaml`. Jeder legt sich darin
eine eigene Wegwerf-Datenbank an und räumt sie am Ende wieder ab; was ein
abgebrochener Lauf liegen lässt, entfernt `python -m kern.testdb`. Wo ein
Server nötig ist, starten die Tests ihn selbst. Ausnahme sind die HTTP-Ablauftests der
Kennzeichen-App, die einen vorbereiteten Server brauchen – Aufruf und
Umgebung stehen in [tests/README.md](tests/README.md).

Unter Windows gibt `PYTHONIOENCODING=utf-8` lesbare Umlaute in der Konsole –
und ist nötig, sobald die Ausgabe umgeleitet wird: sonst scheitert ein Test
schon daran, ein „ř" auszugeben.

## Pläne

- [docs/plan-kennzeichen-webapp_1.md](docs/plan-kennzeichen-webapp_1.md) – Kennzeichen
- [docs/plan-presse-akkreditierung.md](docs/plan-presse-akkreditierung.md) – Presse, dazu die Zusammenführung (Abschnitt 7)
- [docs/plan-helfer-dashboard.md](docs/plan-helfer-dashboard.md) – Helfer

Die Pläne sind der Stand, mit dem gebaut wurde. Was sich seither geändert hat,
steht in den READMEs.

## Lizenz

[MIT](LICENSE) – benutzen, ändern und weitergeben ist erlaubt, auch
kommerziell; mitgeliefert werden muss nur der Copyright-Hinweis. Ohne
Gewährleistung.

Nicht mit umfasst sind die Inhalte der Veranstaltung selbst: Logo, Texte und
Daten gehören denen, die sie beigesteuert haben.
