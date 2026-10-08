# Kennzeichen – Anträge auf Durchfahrt

Einer der drei Bereiche im gemeinsamen Dienst – wie das Ganze zusammenhängt,
steht in der [Übersicht](../README.md). Hier geht es um das, was nur diesen
Bereich betrifft: öffentliches Antragsformular für Durchfahrtsberechtigungen,
Backoffice zur Sichtung und Freigabe, Kartendruck und die Liste für die
Straßensperre. Grundlage ist
[docs/plan-kennzeichen-webapp_1.md](../docs/plan-kennzeichen-webapp_1.md).

| Adresse | was dort liegt |
| --- | --- |
| `kennzeichen.example.de/` | Antragsformular |
| `kennzeichen.example.de/durchfahrt/<token>` | offene Durchfahrtsliste, siehe unten |
| `admin.example.de/kennzeichen` | Backoffice |

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
| 10 | Deployment: systemd, Proxy-Config, Backup-Cron | fertig, siehe [deploy/](../deploy/) |
| 11 | Druckansicht der Karten | fertig |

Danach dazugekommen: Fahrzeuge im Backoffice erfassen, auch mehrere auf
einmal (siehe unten), und die Suche, die mit Umlauten zurechtkommt.

## Starten

Im Alltag als Teil des Dienstes, siehe [Übersicht](../README.md#lokal-starten).
Einzeln geht es weiterhin – so starten auch die Tests ihren Server:

```bash
cp kennzeichen/.env.example kennzeichen/.env
.venv/Scripts/python.exe -m kern.passwort        # Hash in kennzeichen/.env übernehmen
cd kennzeichen
../.venv/Scripts/python.exe -m app
```

Formular dann unter <http://127.0.0.1:8080/>, Backoffice unter
<http://127.0.0.1:8080/kennzeichen>. `kern.passwort` läuft aus dem
Hauptordner, weil `kern` dort liegt.

## Konfiguration

Ausschließlich über Env-Variablen – siehe [.env.example](.env.example) und
[app/config.py](app/config.py). Gelesen wird `kennzeichen/.env`, im Betrieb
die Datei, auf die `KENNZEICHEN_ENV` zeigt; bereits gesetzte
Umgebungsvariablen haben Vorrang.

Was für alle drei Bereiche gilt – `BIND`, `FORWARDED_ALLOW_IPS`,
`ADMIN_PASSWORD_HASH`, `APP_SECRET_KEY` –, steht in der
[Übersicht](../README.md#konfiguration). Eigen ist diesem Bereich:

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
  die Bestätigungsseite wandert mit, das Backoffice bleibt wo es ist
- `IP_SPEICHERN=0` – erhebt die Client-IP gar nicht erst (das Login-Rate-Limit
  braucht sie trotzdem und bekommt sie unabhängig davon)
- `SESSION_STUNDEN`, `LOGIN_VERSUCHE`, `LOGIN_FENSTER_SEKUNDEN`, `COOKIE_SECURE`
- `CSV_TRENNER` – Vorgabe `;` (Excel unter deutschem Windows), `,` für Werkzeuge
- `KARTEN_URL_BASIS`, `LOGO_DATEI` – Ziel des QR-Codes und Logo auf den Karten

## Aufbau

```text
kennzeichen/
  app/
    main.py         Routen: Formular, Anmeldung, Backoffice
    config.py       Env-Konfiguration, .env-Loader
    mail.py         Vorlagen (reiner Text) und SMTP-Versand
    worker.py       Hintergrund-Task, arbeitet die Queue mit Backoff ab
    db.py           Abfragen; Verbindung und Migrationen über kern/db.py
    validation.py   Feldprüfung inkl. Kontaktregel und Honeypot
    migrationen/    Tabellen antrag, mail_out, einstellung (Schema kennzeichen)
    __main__.py     Einzelstart: python -m app (aus kennzeichen/)
    templates/      Jinja2, serverseitig gerendert
    static/         CSS und durchfahrt.js, keine externen Fonts
  .env.example      Vorlage für kennzeichen/.env
```

Anmeldung, Backoffice-Rahmen, Stilblatt und Suche kommen aus
[kern/](../kern/), gemeinsam mit Presse und Helfer.

## Tests

Die Tests dieses Bereichs liegen im gemeinsamen [tests/](../tests/), Aufruf
aus dem Hauptordner:

```bash
.venv/Scripts/python.exe tests/test_auth.py       # Anmeldung, Token, CSRF, Rate Limit
.venv/Scripts/python.exe tests/test_mail.py       # Vorlagen, Queue, Backoff, Migration
.venv/Scripts/python.exe tests/test_versand.py    # echter SMTP-Weg gegen eine Attrappe
.venv/Scripts/python.exe tests/test_proxy.py      # Verhalten hinter dem Reverse Proxy
.venv/Scripts/python.exe tests/test_kategorien.py # alle Kategorien vom Formular bis zum CSV
.venv/Scripts/python.exe tests/test_erfassen.py   # Fahrzeuge im Backoffice erfassen
.venv/Scripts/python.exe tests/test_durchfahrt.py # Durchfahrtsliste, Serverseite
.venv/Scripts/python.exe tests/test_einstellungen.py # Benachrichtigung, Schema-Umbau
node tests/test_durchfahrt_js.js                  # Filterlogik der Durchfahrtsliste
```

Diese laufen ohne vorbereiteten Server und legen sich eigene
Wegwerf-Datenbanken an, im PostgreSQL aus `compose.yaml`. Die HTTP-Ablauftests brauchen einen Server mit
Testkonfiguration – Aufruf und Umgebung stehen in
[tests/README.md](../tests/README.md).

## Was das Formular prüft

- Vorname, Name, Funktion, Kennzeichen und Kategorie sind Pflicht
- Kategorie muss ein Schlüssel aus `KATEGORIEN` sein
- Das Kennzeichen wird großgeschrieben und muss mindestens vier Zeichen haben.
  Bewusst keine Mustererkennung: Saison-, Wechsel- und ausländische Kennzeichen
  weichen zu stark ab, ein strenges Muster würde echte Anträge abweisen.
- E-Mail und Telefon einzeln freiwillig, **mindestens eines muss ausgefüllt sein** –
  sonst kann niemand antworten. Das prüft die Validierung, nicht mehr die
  Datenbank: bei einer Erfassung im Backoffice gilt die Regel nur, solange
  noch entschieden werden muss (siehe [Fahrzeug erfassen](#fahrzeug-erfassen))
- Längenbegrenzungen pro Feld, Whitespace wird normalisiert
- Honeypot-Feld `webseite`: befüllt → Antrag wird verworfen, der Absender sieht
  trotzdem die Bestätigungsseite

Bei Fehlern wird das Formular mit Status 422, den eingegebenen Werten und
Meldungen am jeweiligen Feld neu gerendert. Erfolg führt per 303-Redirect auf
die Bestätigungsseite (kein doppeltes Absenden beim Neuladen).

## Anmeldung

Gemeinsames Passwort (Variante A im Plan), eine Anmeldung für alle drei
Bereiche. Der Ablauf steckt vollständig in [kern/auth.py](../kern/auth.py),
damit ein Magic Link später nachrüstbar bleibt, ohne Cookie- und
CSRF-Handling anzufassen.

- bcrypt-Hash aus `ADMIN_PASSWORD_HASH`, nie im Code
- Session-Token: HMAC-signiert, enthält Kürzel und Ablaufzeit, keine Serverdaten
- Cookie `HttpOnly`, `SameSite=Lax`, `Secure` je nach `COOKIE_SECURE`, Pfad `/` –
  damit gilt er in allen drei Bereichen. Auf den öffentlichen Adressen kommt er
  trotzdem nicht an: er gehört zu `admin.example.de`.
- Rate Limit: `LOGIN_VERSUCHE` Fehlversuche pro `LOGIN_FENSTER_SEKUNDEN` und IP,
  danach 429. Der Zähler liegt im Prozessspeicher, je Bereich eigen – ein
  Neustart setzt zurück. Davor bremst nginx alle drei Anmeldeseiten gemeinsam.
- Alle ändernden Aktionen (Löschen, Abmelden) verlangen einen an die Sitzung
  gebundenen CSRF-Token
- `?weiter=` akzeptiert nur Pfade unter `/kennzeichen`, keine offene Weiterleitung

## Backoffice

`/kennzeichen` zeigt die Liste, standardmäßig gefiltert auf Status `neu`.

- Zähler pro Kategorie (gesamt, neu, genehmigt, ausgegeben)
- Filter nach Status und Kategorie, Freitextsuche über Name, Funktion, Mail,
  Telefon, Kennzeichen und Bemerkung. Umlaute in beiden Schreibweisen:
  „Müller", „Mueller" und „Muller" finden einander
  ([kern/suchen.py](../kern/suchen.py))
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
- **Ablehnen** – Begründung ist Pflicht und wird gespeichert; sie geht als
  Mail an den Antragsteller.
- **Zurücksetzen auf `neu`** – räumt Zeitpunkt, Kürzel und Begründung mit ab,
  die Entscheidung war ja ein Versehen.
- **Ausgegeben** – reines Häkchen bei der Kartenübergabe; die Entscheidungsdaten
  der Genehmigung bleiben stehen. Der Knopf erscheint nur bei `genehmigt`.

Zeitpunkt und Kürzel werden bei jeder Entscheidung festgehalten, das Kürzel
kommt aus der Sitzung (siehe `KUERZEL_ABFRAGEN`).

### Fahrzeug erfassen

Für Fahrzeuge, die nicht über das öffentliche Formular kommen, gibt es in der
Liste „Fahrzeug erfassen" (`/kennzeichen/antrag/neu`). Zwei Schalter: **gleich
genehmigen** – in einem Schreibvorgang, mit Zeitpunkt und Kürzel wie von Hand –
oder nur anlegen. Die Zusage geht nur auf Wunsch hinaus.

Die Kontaktregel gilt hier nur, solange noch entschieden werden muss: wer am
Tisch steht und seine Karte in die Hand bekommt, braucht keinen Kontaktweg.

Ins Kennzeichenfeld dürfen **mehrere Fahrzeuge** – eines je Zeile oder getrennt
durch Komma, Semikolon oder Tabulator. Daraus wird je Fahrzeug ein Antrag,
denn an der Sperre wird je Fahrzeug eine Karte gesucht.

- Das Leerzeichen trennt absichtlich nicht: `IL-A 123` enthält selbst eines.
- Dopplungen fallen nach der Normalisierung weg – `IL-A 123` und `ila123` sind
  derselbe Wagen; gedruckt wird die erste Schreibweise.
- Ein unbrauchbares Stück verwirft die **ganze** Eingabe und nennt es beim
  Namen. Die halbe Liste anzulegen wäre schlimmer: niemand wüsste, was schon
  drin ist.
- Die Zusage geht je Fahrzeug einmal hinaus, mit Nummer und Kennzeichen.

Das öffentliche Formular bleibt bei einem Kennzeichen.

### Kontingente – nicht in Gebrauch

Kontingente werden nicht verwaltet, `KONTINGENTE` bleibt leer und es warnt
nichts. Die Funktion ist trotzdem da und getestet, weil sie nichts kostet,
solange sie ausgeschaltet ist: `KONTINGENTE=camping:120,vip:40` zählt genehmigte
und ausgegebene Anträge je Kategorie, warnt beim Erreichen der Grenze in der
Detailansicht und markiert die Kachel in der Liste. **Kein harter Block** – so
will es der Plan.

## CSV-Export

`/kennzeichen/export.csv` liefert **dieselbe Auswahl wie die Liste** – der Verweis
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
maskiert – das prüft [tests/test_export.py](../tests/test_export.py) mit.

## Durchfahrtsliste

`/kennzeichen/durchfahrt` ist die Ansicht für die Straßensperre – eigener Reiter im
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

Das ist das einzige eigene Skript dieses Bereichs. Es hat einen Grund: eine
Suche, die an der Sperre auf eine Antwort vom Server wartet, ist keine.

Die **Normalisierung passiert auf dem Server**: jede Zeile trägt `data-name`
als durchsuchbaren Text ([kern/suchen.py](../kern/suchen.py), Umlaute in beiden
Schreibweisen) und `data-kfz` ohne Trennzeichen (`db.kfz_normalisieren`). Das
Skript richtet nur die Eingabe genauso zu und vergleicht – für den Namen mit
[kern/static/suchtext.js](../kern/static/suchtext.js). Dass Python und
JavaScript wirklich dasselbe liefern, prüfen
[tests/test_durchfahrt.py](../tests/test_durchfahrt.py) und
[tests/test_suchen.py](../tests/test_suchen.py). Weichen sie ab, findet die
Suche nichts, und zwar lautlos.

`kaab101`, `ka ab 101`, `KA-AB-101` und `ab101` finden alle `KA-AB 101`. Dieselbe
Toleranz gilt inzwischen auch für die Suche in der Antragsliste.

### Sortieren

Vorgabe ist **Kennzeichen aufsteigend** – danach wird an der Sperre gesucht.
Ein Tipp auf eine Spaltenüberschrift sortiert danach um, ein zweiter dreht die
Richtung. Läuft ebenfalls im Browser, also ohne Netz. Die Überschriften sind
echte Knöpfe und melden ihren Zustand über `aria-sort`.

Die Serverabfrage sortiert bereits nach Kennzeichen (normalisiert, Leere ans
Ende) – ohne JavaScript stimmt die Reihenfolge also auch. Das Skript sortiert
beim Laden trotzdem einmal nach, damit die Anzeige auf die Stelle genau dem
entspricht, was ein Klick auf dieselbe Spalte ergibt.

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
`/kennzeichen/durchfahrt` ein Link erzeugen:

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

`/kennzeichen/karten` liefert die Ausweise als Druckseite. Der Verweis steht in der
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
URL geht trotzdem jeder Status: `/kennzeichen/karten?status=ausgegeben`.

### QR-Code und Logo

- `KARTEN_URL_BASIS=https://admin.example.de` – dann führt der QR-Code in
  die Detailansicht des Antrags (`…/kennzeichen/antrag/<nr>`). Die verlangt eine
  Anmeldung, taugt also für die Orga an der Einfahrt und gibt Fremden nichts
  preis. **Die Backoffice-Adresse, nicht `kennzeichen.example.de`** – dort
  beantwortet nginx alles unter `/kennzeichen` mit 404. Ohne den Wert enthält
  der Code nur Antragsnummer und Veranstaltung als Text.
- `LOGO_DATEI=logo.svg` – Dateiname **direkt** in `kennzeichen/app/static/`. Fehlt die Datei
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

Unter `/kennzeichen/einstellungen` lässt sich eine Adresse hinterlegen, die bei jedem
eingegangenen Antrag eine kurze Nachricht bekommt – mit den Daten und einem
Verweis in die Detailansicht. Leer lassen schaltet es ab.

Der Verweis zeigt auf die Backoffice-Adresse aus `HOST_ADMIN`, obwohl der
Antrag über die öffentliche hereinkam: unter `kennzeichen.example.de` gibt
nginx für `/kennzeichen/…` 404. Ist `HOST_ADMIN` leer, etwa beim Einzelstart,
bleibt es bei der Adresse der Anfrage.

Die Adresse steht in der Tabelle `einstellung`, nicht in der Env: sie lässt sich
damit ohne Neustart ändern. Die Nachricht läuft über dieselbe Queue wie alles
andere, wird also nicht im Request verschickt.

Der Plan warnt an dieser Stelle vor Lärm und schlägt eine tägliche
Sammelmeldung vor. Bei ein paar Dutzend Anträgen über mehrere Wochen ist eine
Nachricht je Antrag brauchbar; wenn es zu viel wird, ist das Feld in zehn
Sekunden geleert.

### Anträge ohne Mailadresse

`/kennzeichen/telefon` listet **abgelehnte** Anträge ohne Mailadresse, die noch niemand
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

Gemeinsam mit den anderen beiden Bereichen, siehe
[deploy/README.md](../deploy/README.md): ein Container, eine Unit, eine
nginx-Konfiguration, eine Sicherung. Die eigenen Werte dieses Bereichs stehen
in `/etc/abfahrt/kennzeichen.env`, Vorlage
[deploy/kennzeichen.env.example](../deploy/kennzeichen.env.example).

Eigen ist diesem Bereich das Rate Limit fürs Formular. Es sitzt im nginx und
greift nur bei `POST` – wer die Seite neu lädt oder nach einem
Validierungsfehler noch einmal absendet, läuft nicht gegen die Wand.

## Was noch fehlt

Alle elf Schritte des Plans sind gebaut. Offen sind noch Dinge, die nicht am
Code hängen:

- **Schritt 7 zu Ende bringen**: IONOS-Postfach anlegen, DKIM aktivieren,
  Testmails an Gmail, GMX und Outlook. Solange `SMTP_HOST` fehlt, sammeln sich
  die Mails in `mail_out`, ohne dass etwas verloren geht.
- **Jubiläums-Logo** in `kennzeichen/app/static/` ablegen und `LOGO_DATEI` setzen.
- **Offene Frage 4** aus dem Plan: der Text für die Kartenübergabe in der
  Genehmigungsmail (`ABHOLUNG`). Eine Env-Zeile, sobald Ort und Zeit feststehen.

Die **Löschung nach der Veranstaltung** (Abschnitt 8 des Plans, Datenschutz)
gibt es inzwischen – für alle drei Bereiche, als Werkzeug und nicht als
Cron-Job: [deploy/README.md, Abschnitt 8](../deploy/README.md#8-nach-der-veranstaltung-personendaten-löschen).
