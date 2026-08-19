# Kennzeichen-Antrag – „Die absolute Abfahrt"

Webanwendung für Durchfahrtsberechtigungen: öffentliches Antragsformular plus
Backoffice zur Sichtung und (später) redaktionellen Freigabe.
Grundlage ist [docs/plan-kennzeichen-webapp_1.md](docs/plan-kennzeichen-webapp_1.md).

Die App spricht **nur HTTP** und lauscht auf `127.0.0.1`. TLS, Redirect und
Zertifikate macht der Reverse Proxy davor.

## Stand

| # | Schritt aus dem Plan | Status |
| --- | --- | --- |
| 1 | Projektgerüst, Config über Env, SQLite-Schema | fertig |
| 2 | Öffentliches Formular + Validierung + Bestätigungsseite | fertig |
| 3 | Login (Passwort) + Session-Cookie | fertig |
| 4 | Backoffice: Liste, Filter, Detailansicht, Löschen | fertig |
| 5 | Redaktionelle Freigabe: genehmigen/ablehnen, Werte korrigieren | fertig |
| 6 | Mail-Queue + Versand-Worker + Vorlagen | fertig |
| 7 | SPF/DKIM/DMARC für example.de | SPF und DMARC stehen, DKIM offen – siehe unten |
| 8 | CSV-Export | fertig |
| 9 | Honeypot, Rate Limit, Datenschutzhinweis | fertig (Formular-Limit liegt im nginx, siehe `deploy/`) |
| 10 | Deployment: systemd, Proxy-Config, Backup-Cron | fertig, siehe [deploy/](deploy/) |
| 11 | Druckansicht der Karten | fertig |

## Starten (lokal)

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Linux: .venv/bin/python
cp .env.example .env
.venv/Scripts/python.exe -m app.passwort                      # Hash in die .env übernehmen
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8080
```

- Formular: <http://127.0.0.1:8080/>
- Backoffice: <http://127.0.0.1:8080/admin>

Lokal über `http` bleibt `COOKIE_SECURE=auto` richtig: das Secure-Flag wird nur
gesetzt, wenn der Browser über HTTPS kam.

## Starten (Betrieb)

```bash
python -m app
```

Bind-Adresse und vertraute Proxys kommen aus `BIND` und `FORWARDED_ALLOW_IPS`,
`--proxy-headers` ist fest eingeschaltet. Das ist Absicht: Ohne dieses Flag
steht in `antrag.remote_ip` die IP des Proxys statt die des Antragstellers, das
Login-Rate-Limit greift für alle gemeinsam, und das Secure-Flag am Cookie fehlt.
An einer Kommandozeile vergisst man es irgendwann – in einer Env-Datei nicht.

Der Proxy muss `X-Forwarded-For` und `X-Forwarded-Proto` setzen. Fertige
Konfigurationen für nginx, systemd und den Backup-Cron liegen in
[deploy/](deploy/), samt Prüfliste vor dem Livegang.

Der Plan empfiehlt zusätzlich, `/admin` im Proxy per IP-Allowlist oder Basic
Auth abzusichern – zweite Schicht, zwei Zeilen nginx, in der mitgelieferten
Config schon vorbereitet.

## Konfiguration

Ausschließlich über Env-Variablen – siehe [.env.example](.env.example) und
[app/config.py](app/config.py). Ein `.env` im Projektverzeichnis wird beim Start
gelesen; bereits gesetzte Umgebungsvariablen haben Vorrang.

Vier Werte gehören im Betrieb gesetzt, sonst warnt die App beim Start:

- `BIND` – Adresse und Port. Liegt der Proxy auf einem anderen Host, muss hier
  die eigene IP stehen und der Port per Firewall auf den Proxy beschränkt sein.
- `FORWARDED_ALLOW_IPS` – die IP des Reverse Proxys. Nur von dort werden
  `X-Forwarded-For` und `X-Forwarded-Proto` geglaubt.
- `ADMIN_PASSWORD_HASH` – ohne ihn bleibt `/admin` geschlossen (503 mit Anleitung),
  das öffentliche Formular läuft weiter. Erzeugen mit `python -m app.passwort`.
- `APP_SECRET_KEY` – ohne ihn wird beim Start einer erzeugt, und alle Anmeldungen
  enden mit dem nächsten Neustart.

Weiter erwähnenswert:

- `KATEGORIEN` – `schluessel:Beschriftung,schluessel2:Beschriftung 2`. Vorgabe
  sind die fünf Kategorien der Veranstaltung:

  | Schlüssel | Beschriftung |
  | --- | --- |
  | `camping` | Camping |
  | `expo` | Expo |
  | `local` | Local/Durchfahrt |
  | `parken` | Parken |
  | `vip` | VIP |

  Der Schlüssel steht in der Datenbank, im CSV-Export und in den Filter-URLs,
  die Beschriftung auf Formular, Karte und in der Mail. Schlüssel nachträglich
  zu ändern heisst, vorhandene Datensätze mitzuziehen – die Beschriftung lässt
  sich jederzeit anpassen.
- `KENNZEICHEN_ERFASSEN=0` – blendet das Kfz-Kennzeichen-Feld aus. Für diese
  Veranstaltung bleibt es an: an der Straßensperre werden die Aufkleber anhand
  der Liste ausgegeben, deshalb ist das Feld **Pflicht** (offene Frage 3 ist
  damit beantwortet).
- `KONTINGENTE` – **wird nicht genutzt.** Kontingente werden nicht verwaltet
  (offene Frage 1 ist damit beantwortet), deshalb bleibt der Wert leer und es
  warnt nichts. Falls es doch einmal eng wird: `camping:120,vip:40` genügt.
- `KUERZEL_ABFRAGEN=0` – lässt das Bearbeiter-Kürzel bei der Anmeldung weg (offene Frage 5)
- `FORM_PATH=/antrag/abfahrt30` – legt das Formular auf einen nicht geratenen Pfad;
  die Bestätigungsseite wandert mit, `/admin` bleibt wo es ist
- `IP_SPEICHERN=0` – erhebt die Client-IP gar nicht erst (das Login-Rate-Limit
  braucht sie trotzdem und bekommt sie unabhängig davon)
- `SESSION_STUNDEN`, `LOGIN_VERSUCHE`, `LOGIN_FENSTER_SEKUNDEN`, `COOKIE_SECURE`
- `CSV_TRENNER` – Vorgabe `;` (Excel unter deutschem Windows), `,` für Werkzeuge
- `KARTEN_URL_BASIS`, `LOGO_DATEI` – Ziel des QR-Codes und Logo auf den Karten

## Aufbau

```text
app/
  main.py         Routen: Formular, Anmeldung, Backoffice
  config.py       Env-Konfiguration, .env-Loader
  auth.py         Passwortprüfung, signiertes Session-Token, CSRF, Rate Limit
  passwort.py     CLI: python -m app.passwort
  mail.py         Vorlagen (reiner Text) und SMTP-Versand
  worker.py       Hintergrund-Task, arbeitet die Queue mit Backoff ab
  db.py           SQLite-Verbindung, Schema, Migration, Abfragen
  validation.py   Feldprüfung inkl. Kontaktregel und Honeypot
  schema.sql      Tabellen antrag + mail_out
  __main__.py     Einstiegspunkt: python -m app
  templates/      Jinja2, serverseitig gerendert
  static/         CSS und ein einziges Skript, keine externen Fonts
deploy/           systemd-Unit, nginx-Config, Backup-Skript, Prüfliste
tests/            Skripte ohne Testbibliothek, siehe tests/README.md
```

## Tests

```bash
.venv/Scripts/python.exe tests/test_auth.py       # Anmeldung, Token, CSRF, Rate Limit
.venv/Scripts/python.exe tests/test_mail.py       # Vorlagen, Queue, Backoff, Migration
.venv/Scripts/python.exe tests/test_versand.py    # echter SMTP-Weg gegen eine Attrappe
.venv/Scripts/python.exe tests/test_proxy.py      # Verhalten hinter dem Reverse Proxy
.venv/Scripts/python.exe tests/test_kategorien.py # alle Kategorien vom Formular bis zum CSV
.venv/Scripts/python.exe tests/test_durchfahrt.py # Durchfahrtsliste, Serverseite
.venv/Scripts/python.exe tests/test_einstellungen.py # Benachrichtigung, Schema-Umbau
node tests/test_durchfahrt_js.js                  # Filterlogik der Durchfahrtsliste
```

Diese laufen ohne vorbereiteten Server und legen sich eigene
Wegwerf-Datenbanken an. Die HTTP-Ablauftests brauchen einen Server mit
Testkonfiguration – Aufruf und Umgebung stehen in
[tests/README.md](tests/README.md).

## Was das Formular prüft

- Vorname, Name, Funktion, Kennzeichen und Kategorie sind Pflicht
- Kategorie muss ein Schlüssel aus `KATEGORIEN` sein
- Das Kennzeichen wird großgeschrieben und muss mindestens vier Zeichen haben.
  Bewusst keine Mustererkennung: Saison-, Wechsel- und ausländische Kennzeichen
  weichen zu stark ab, ein strenges Muster würde echte Anträge abweisen.
- E-Mail und Telefon einzeln freiwillig, **mindestens eines muss ausgefüllt sein** –
  zusätzlich als CHECK-Constraint in der Datenbank abgesichert
- Längenbegrenzungen pro Feld, Whitespace wird normalisiert
- Honeypot-Feld `webseite`: befüllt → Antrag wird verworfen, der Absender sieht
  trotzdem die Bestätigungsseite

Bei Fehlern wird das Formular mit Status 422, den eingegebenen Werten und
Meldungen am jeweiligen Feld neu gerendert. Erfolg führt per 303-Redirect auf
die Bestätigungsseite (kein doppeltes Absenden beim Neuladen).

## Anmeldung

Gemeinsames Passwort (Variante A im Plan). Der Ablauf steckt vollständig in
[app/auth.py](app/auth.py), damit ein Magic Link später nachrüstbar bleibt, ohne
Cookie- und CSRF-Handling anzufassen.

- bcrypt-Hash aus `ADMIN_PASSWORD_HASH`, nie im Code
- Session-Token: HMAC-signiert, enthält Kürzel und Ablaufzeit, keine Serverdaten
- Cookie `HttpOnly`, `SameSite=Lax`, `Secure` je nach `COOKIE_SECURE`, Pfad `/admin` –
  auf der öffentlichen Seite wird es damit gar nicht erst mitgeschickt
- Rate Limit: `LOGIN_VERSUCHE` Fehlversuche pro `LOGIN_FENSTER_SEKUNDEN` und IP,
  danach 429. Der Zähler liegt im Prozessspeicher – bei mehreren uvicorn-Workern
  zählt jeder für sich, und ein Neustart setzt zurück.
- Alle ändernden Aktionen (Löschen, Abmelden) verlangen einen an die Sitzung
  gebundenen CSRF-Token
- `?weiter=` akzeptiert nur eigene `/admin`-Pfade, keine offene Weiterleitung

## Backoffice

`/admin` zeigt die Liste, standardmäßig gefiltert auf Status `neu`.

- Zähler pro Kategorie (gesamt, neu, genehmigt, ausgegeben)
- Filter nach Status und Kategorie, Freitextsuche über Name, Funktion, Mail,
  Telefon, Kennzeichen und Bemerkung – Groß/Klein auch bei Umlauten
- Sortierung nach Eingang, Name oder Kategorie (feste Whitelist, nichts aus der
  URL landet im SQL)
- Anträge ohne Mailadresse sind mit „nur Telefon" markiert
- Detailansicht mit allen Feldern und endgültigem Löschen (mit Rückfrage)
- Sammelaktion: markierte Anträge auf einen Schlag genehmigen

## Redaktionelle Freigabe

Statusmodell wie im Plan: `neu → genehmigt → ausgegeben`, daneben `abgelehnt`.
Erlaubte Wechsel stehen in `db.UEBERGAENGE` und werden als Bedingung im `UPDATE`
geprüft, nicht vorher gelesen – zwei gleichzeitige Klicks können sich damit
nicht überholen.

- **Genehmigen** – ein Formular, zwei Knöpfe: „Änderungen speichern" und
  „Speichern und genehmigen". Korrekturen an Namen, Funktion und Kategorie
  laufen durch dieselbe Validierung wie das öffentliche Formular, die
  Kontaktregel gilt also auch hier.
- **Ablehnen** – Begründung ist Pflicht und wird gespeichert; sie geht ab
  Schritt 6 als Mail an den Antragsteller.
- **Zurücksetzen auf `neu`** – räumt Zeitpunkt, Kürzel und Begründung mit ab,
  die Entscheidung war ja ein Versehen.
- **Ausgegeben** – reines Häkchen bei der Kartenübergabe; die Entscheidungsdaten
  der Genehmigung bleiben stehen. Der Knopf erscheint nur bei `genehmigt`.

Zeitpunkt und Kürzel werden bei jeder Entscheidung festgehalten, das Kürzel
kommt aus der Sitzung (siehe `KUERZEL_ABFRAGEN`).

### Kontingente – nicht in Gebrauch

Kontingente werden nicht verwaltet, `KONTINGENTE` bleibt leer und es warnt
nichts. Die Funktion ist trotzdem da und getestet, weil sie nichts kostet,
solange sie ausgeschaltet ist: `KONTINGENTE=camping:120,vip:40` zählt genehmigte
und ausgegebene Anträge je Kategorie, warnt beim Erreichen der Grenze in der
Detailansicht und markiert die Kachel in der Liste. **Kein harter Block** – so
will es der Plan.

## CSV-Export

`/admin/export.csv` liefert **dieselbe Auswahl wie die Liste** – der Verweis
unter der Trefferzahl trägt die aktuellen Filter mit. Ohne Parameter kommt alles.

- UTF-8 **mit BOM** und Semikolon als Trenner: so öffnet Excel unter Windows die
  Datei ohne Import-Dialog und ohne Buchstabensalat. `CSV_TRENNER=,` stellt auf
  Komma um, wenn die Datei maschinell weiterverarbeitet wird.
- Zeitstempel im lesbaren Format (`18.08.2026 09:17`), nicht ISO – die Zielgruppe
  ist ein Serienbrief, kein Skript.
- Kategorie doppelt: als Schlüssel (`vip`) zum Filtern und als
  Klartext (`VIP`) zum Drucken. Dazu eine Spalte „Kontaktweg"
  (E-Mail oder Telefon).
- **Die IP-Adresse wird nicht exportiert.** Sie steht nur für Missbrauchsfälle in
  der Datenbank und hat in einer Datei, die per Mail herumgereicht wird, nichts
  verloren.

Semikolon, Anführungszeichen und Zeilenumbrüche in Freitextfeldern werden korrekt
maskiert – das prüft [tests/test_export.py](tests/test_export.py) mit.

## Durchfahrtsliste

`/admin/durchfahrt` ist die Ansicht für die Straßensperre – eigener Reiter im
Backoffice. Nur vier Spalten: Vorname, Name, Kennzeichen, Kategorie. Keine
Kennzahlen, keine Filter, keine Aktionen. Wer dort steht, will einen Namen oder
ein Kennzeichen nachschlagen und sonst nichts.

Aufgeführt sind **genehmigte und ausgegebene** Berechtigungen. Offene und
abgelehnte Anträge stehen bewusst nicht drauf – eine Liste an der Sperre, auf
der auch Abgelehnte auftauchen, wäre gefährlich.

### Gesucht wird im Browser

An der Sperre ist der Empfang mies, deshalb geht die vollständige Liste in einem
Rutsch in die Seite und [app/static/durchfahrt.js](app/static/durchfahrt.js)
filtert beim Tippen. Nach dem einmaligen Laden geht keine Anfrage mehr raus; das
Suchfeld steht in keinem Formular, damit auch Enter nichts nachlädt.

Das ist das einzige JavaScript im ganzen Projekt. Es hat einen Grund: eine
Suche, die an der Sperre auf eine Antwort vom Server wartet, ist keine.

Die **Normalisierung passiert auf dem Server**: jede Zeile trägt `data-name`
kleingeschrieben und `data-kfz` ohne Trennzeichen (`db.kfz_normalisieren`). Das
Skript richtet nur die Eingabe genauso zu und vergleicht. So gibt es die Regel
einmal, nicht zweimal – und [tests/test_durchfahrt.py](tests/test_durchfahrt.py)
prüft, dass Python und JavaScript wirklich dasselbe liefern. Weichen sie ab,
findet die Suche nichts, und zwar lautlos.

`kaab101`, `ka ab 101`, `KA-AB-101` und `ab101` finden alle `KA-AB 101`. Dieselbe
Toleranz gilt inzwischen auch für die Suche in der Antragsliste.

### Sortieren

Ein Tipp auf eine Spaltenüberschrift sortiert danach, ein zweiter dreht die
Richtung um. Läuft ebenfalls im Browser, also ohne Netz. Die Überschriften sind
echte Knöpfe und melden ihren Zustand über `aria-sort`.

Verglichen wird mit `localeCompare` und Gebietsschema `de`: Umlaute landen bei
ihrem Grundbuchstaben (Öztürk zwischen O und P, nicht hinter Z), und Zahlen in
Kennzeichen werden als Zahlen verglichen – `KA-AB 2` steht vor `KA-AB 10`.
Leere Felder bleiben in beiden Richtungen unten; die Richtung steckt deshalb im
Vergleich und wird nicht außen negiert.

Ohne JavaScript gibt es kein Suchfeld, aber die vollständige Liste – ein
`<noscript>`-Hinweis verweist auf Strg+F. Für den Fall, dass gar nichts geht,
lässt sich vorher der CSV-Export aufs Telefon laden.

### Offener Link für die Sperre

Damit die Leute an der Sperre kein Backoffice-Passwort brauchen – und damit
keine Rechte zum Genehmigen oder Löschen –, lässt sich unter
`/admin/durchfahrt` ein Link erzeugen:

```text
https://kennzeichen.example.de/durchfahrt/<43 Zeichen Zufall>
```

Der Token liegt in der Tabelle `einstellung` und wird im Backoffice erzeugt,
erneuert oder zurückgezogen. **Solange keiner erzeugt ist, gibt es keinen
offenen Zugang** – ein Aufruf von `/durchfahrt/irgendwas` gibt 404, genau wie
ein falscher oder zurückgezogener Token. Der Vergleich läuft über
`hmac.compare_digest`.

Die offene Ansicht zeigt dieselbe Tabelle (dasselbe Template-Fragment), aber
keine Navigation, kein Abmelden, keine Kontaktdaten, keine Funktion, keine
abgelehnten Anträge. Sie trägt `noindex` und `referrer: no-referrer`, damit der
Token nicht per Klick nach draußen wandert.

**Das ist eine bewusste Lockerung.** Wer den Link hat, sieht Namen und
Kennzeichen aller Berechtigten, ohne sich anzumelden. Deshalb:

- Nur an die Leute an der Sperre geben, nirgends öffentlich posten.
- Gerät er in falsche Hände: neuen Link erzeugen, der alte ist sofort tot.
- Nach der Veranstaltung zurückziehen.
- Der Token steht im Pfad und landet damit in den nginx-Zugriffslogs. Wer die
  Logs lesen kann, kann die Liste öffnen.

Im nginx bremst ein eigenes Limit (30 Aufrufe pro Minute und IP) das
Durchprobieren; an der Sperre fällt das nicht auf, weil die Seite einmal geladen
und danach im Browser gefiltert wird.

## Karten drucken

`/admin/karten` liefert die Ausweise als Druckseite. Der Verweis steht in der
Liste neben dem CSV-Export, sobald es genehmigte Anträge gibt.

**Vier A6-Karten auf einem A4-Bogen**, mit gestrichelten Schnittlinien. Ein
echter A6-Druck wäre schöner, setzt aber einen Drucker mit A6-Einzug voraus –
auf A4 drucken und schneiden geht überall. Weitere Bögen brechen sauber um.

Auf der Karte: Veranstaltungsname (bzw. Logo), Vor- und Nachname, Funktion,
Antragsnummer, Kennzeichen falls erfasst, QR-Code und ein Farbbalken mit der
Kategorie – den erkennt man an der Einfahrt auch aus drei Metern.

Im Druckdialog **Ränder auf „keine"** und **Hintergrundgrafiken einschalten**,
sonst fehlen Schnittlinien und Kategorieleiste. Der Hinweis steht auch auf der
Seite selbst und verschwindet im Ausdruck.

### Der Verweis druckt nur Genehmigte

Der Link aus der Liste setzt fest `status=genehmigt` und übernimmt nur Kategorie
und Suche. Die Standardansicht der Liste ist auf `neu` gefiltert – Karten für
noch nicht entschiedene Anträge zu drucken wäre ein teurer Fehlgriff. Über die
URL geht trotzdem jeder Status: `/admin/karten?status=ausgegeben`.

### QR-Code und Logo

- `KARTEN_URL_BASIS=https://kennzeichen.example.de` – dann führt der QR-Code in
  die Detailansicht des Antrags. Die verlangt eine Anmeldung, taugt also für die
  Orga an der Einfahrt und gibt Fremden nichts preis. Ohne den Wert enthält der
  Code nur Antragsnummer und Veranstaltung als Text.
- `LOGO_DATEI=logo.svg` – Dateiname **direkt** in `app/static/`. Fehlt die Datei
  oder steht ein Pfad drin, bleibt es beim Veranstaltungsnamen als Text; die
  Druckseite weist darauf hin. **Das Jubiläums-Logo fehlt noch** – die Datei
  dort ablegen und die Variable setzen.

Der QR-Code wird als eingebettetes SVG erzeugt ([segno](https://pypi.org/project/segno/),
reines Python ohne weitere Abhängigkeiten), nicht als `data:`-URI: die
ausgelieferte CSP setzt `img-src 'self'` und würde `data:` blockieren.

## Mailversand

Drei Mails, alle reiner Text: Eingangsbestätigung, Genehmigung, Absage. Erzeugt
werden sie nur, wenn eine Mailadresse hinterlegt ist.

**Nie im Request.** Die Route schreibt die fertige Mail in `mail_out` und liefert
sofort die Antwortseite aus; [app/worker.py](app/worker.py) holt sie alle
`MAIL_INTERVALL` Sekunden ab. Wenn der SMTP hängt, hängt so nicht das Formular.

- Entscheidung und Mail werden in **einer Transaktion** geschrieben. Wird ein
  Statuswechsel abgewiesen, entsteht auch keine Mail.
- Fehlschlag: `versuche + 1`, Backoff 1 → 2 → 4 → … Minuten (bei 60 gedeckelt).
  Nach `MAIL_MAX_VERSUCHE` bleibt die Mail liegen und erscheint in der
  Detailansicht als „fehlgeschlagen"; die Liste zeigt oben eine Warnung.
- Liegengebliebene Mails lassen sich im Backoffice erneut anstoßen.
- Ohne `SMTP_HOST` oder `MAIL_FROM` läuft der Worker gar nicht erst. Die Mails
  sammeln sich in `mail_out` und gehen nicht verloren; der Start warnt.

Die Genehmigungsmail nennt Ort und Zeit der Kartenübergabe nur, wenn `ABHOLUNG`
gesetzt ist (offene Frage 4). Sonst steht dort, dass die Info nachkommt – lieber
vage als falsch.

### Meldung an die Orga bei neuen Anträgen

Unter `/admin/einstellungen` lässt sich eine Adresse hinterlegen, die bei jedem
eingegangenen Antrag eine kurze Nachricht bekommt – mit den Daten und einem
Verweis in die Detailansicht. Leer lassen schaltet es ab.

Die Adresse steht in der Tabelle `einstellung`, nicht in der Env: sie lässt sich
damit ohne Neustart ändern. Die Nachricht läuft über dieselbe Queue wie alles
andere, wird also nicht im Request verschickt.

Der Plan warnt an dieser Stelle vor Lärm und schlägt eine tägliche
Sammelmeldung vor. Bei ein paar Dutzend Anträgen über mehrere Wochen ist eine
Nachricht je Antrag brauchbar; wenn es zu viel wird, ist das Feld in zehn
Sekunden geleert.

### Anträge ohne Mailadresse

`/admin/telefon` listet **abgelehnte** Anträge ohne Mailadresse, die noch niemand
angerufen hat, mit Häkchen „angerufen" (`tel_informiert_am`). Die Kopfzeile zeigt
die Zahl der offenen Anrufe.

Angerufen wird nur im Negativfall. Wer genehmigt ist, steht an der Straßensperre
ohnehin auf der Liste und bekommt den Aufkleber dort – ein Anruf wäre Arbeit ohne
Ertrag. Eine Absage dagegen muss ankommen, sonst fährt jemand umsonst hin. Der
Statusfilter dafür steht in `db.TELEFONISCH_STATUS`.

### Zustellbarkeit (Schritt 7, example.de)

Stand heute im DNS:

| Eintrag | Wert | Bewertung |
| --- | --- | --- |
| MX | `mx00.ionos.de`, `mx01.ionos.de` | Postfach liegt bei IONOS |
| SPF | `v=spf1 a mx include:agenturserver.de include:_spf-eu.ionos.com ~all` | deckt IONOS-Versand ab |
| DMARC | `_dmarc` → CNAME `dmarc.ionos.de` → `v=DMARC1; p=none;` | vorhanden |
| DKIM | unter den üblichen Selektoren nichts gefunden | vermutlich nicht aktiviert |

Daraus folgt: **nicht selbst aus dem Container versenden, sondern über IONOS
relayen.** Dann greift der vorhandene SPF-Eintrag, IONOS signiert mit DKIM, und
Reverse-DNS und IP-Reputation sind nicht dein Problem. Genau dazu rät der Plan im
Abschnitt Zustellbarkeit.

1. Postfach `kennzeichen@example.de` bei IONOS anlegen
2. `SMTP_HOST=smtp.ionos.de`, `SMTP_PORT=587`, `SMTP_TLS=starttls`,
   `SMTP_USER`/`SMTP_PASS` des Postfachs setzen
3. `MAIL_FROM` muss **dieselbe Adresse** tragen, sonst weist IONOS ab
4. DKIM im IONOS-Kundenmenü für example.de aktivieren, falls noch nicht geschehen
5. Testmails an Gmail, GMX und Outlook schicken und die Kopfzeilen prüfen:
   `spf=pass`, `dkim=pass`, `dmarc=pass`

Erst wenn das steht, `p=none` in DMARC auf `p=quarantine` anzuheben erwägen –
und das betrifft die ganze Domain, nicht nur diese App.

## Deployment

Alles in [deploy/](deploy/): systemd-Unit, nginx-Konfiguration für
`kennzeichen.example.de`, Backup-Skript und eine Prüfliste vor dem Livegang.

Aufbau: App in einem LXC-Container, nginx auf einem anderen Host mit
öffentlicher IP terminiert HTTPS.

```text
Internet ──HTTPS──▶ nginx (10.0.0.10)  ──HTTP──▶ LXC (10.0.0.42:8080)
                    Zertifikat                   nur von 10.0.0.10 erreichbar
                    Rate Limit
```

Weil der Proxy nicht auf demselben Host liegt, kann die App **nicht** auf
`127.0.0.1` lauschen. Zwei Dinge müssen deshalb zusammenpassen:
`FORWARDED_ALLOW_IPS` zeigt auf den nginx, und der App-Port ist per Firewall auf
den nginx beschränkt. Die App warnt beim Start, wenn das eine gesetzt ist und das
andere danach aussieht, als hätte man es vergessen.

Das Rate Limit fürs Formular sitzt im nginx und greift nur bei `POST` – wer die
Seite neu lädt oder nach einem Validierungsfehler noch einmal absendet, läuft
nicht gegen die Wand.

## Backup

`deploy/backup.sh` per Cron, nutzt `sqlite3 ".backup"` (nicht `cp` – die
Datenbank läuft im WAL-Modus) und prüft die Kopie anschließend mit
`PRAGMA integrity_check`.

## Was noch fehlt

Alle elf Schritte des Plans sind gebaut. Offen sind noch Dinge, die nicht am
Code hängen:

- **Schritt 7 zu Ende bringen**: IONOS-Postfach anlegen, DKIM aktivieren,
  Testmails an Gmail, GMX und Outlook. Solange `SMTP_HOST` fehlt, sammeln sich
  die Mails in `mail_out`, ohne dass etwas verloren geht.
- **Jubiläums-Logo** in `app/static/` ablegen und `LOGO_DATEI` setzen.
- **Offene Frage 4** aus dem Plan: der Text für die Kartenübergabe in der
  Genehmigungsmail (`ABHOLUNG`). Eine Env-Zeile, sobald Ort und Zeit feststehen.
- **Löschung X Wochen nach der Veranstaltung** (Abschnitt 8 des Plans,
  Datenschutz). Bewusst zurückgestellt – bisher gibt es dafür nur den
  Hinweistext im Formular, keinen Knopf und keinen Cron-Job.

## Lizenz

[MIT](LICENSE) – benutzen, ändern und weitergeben ist erlaubt, auch
kommerziell; mitgeliefert werden muss nur der Copyright-Hinweis. Ohne
Gewährleistung.

Nicht mit umfasst sind die Inhalte der Veranstaltung selbst: Logo, Texte und
Daten gehören denen, die sie beigesteuert haben.
