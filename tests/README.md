# Tests

Keine Testbibliothek, nur Standardbibliothek – `python datei.py`, Rückgabewert 0
heißt bestanden.

## Ohne Server

```bash
.venv/Scripts/python.exe tests/test_auth.py
.venv/Scripts/python.exe tests/test_mail.py
.venv/Scripts/python.exe tests/test_versand.py
.venv/Scripts/python.exe tests/test_proxy.py
.venv/Scripts/python.exe tests/test_kategorien.py
.venv/Scripts/python.exe tests/test_durchfahrt.py
node tests/test_durchfahrt_js.js
```

- `test_auth.py` – Passwort-Hashing, Session-Token (Signatur, getauschte
  Nutzlast, Ablauf), CSRF-Bindung, Login-Rate-Limit.
- `test_mail.py` – Vorlagen, Kopplung von Entscheidung und Mail, Fälligkeit,
  Backoff, erneutes Anstoßen, Telefonliste, Spalten-Migration einer alten
  Datenbank.
- `test_versand.py` – echter smtplib-Weg gegen einen Wegwerf-SMTP-Server im
  selben Prozess: Kopfzeilen, Umlaute, Fehlerfall, Start und Stopp der
  Worker-Schleife. Es geht nichts nach draußen.
- `test_proxy.py` – startet den Server mehrfach selbst und prüft das Verhalten
  hinter einem Reverse Proxy: welche IP in `remote_ip` landet, dass ein vom
  Client erfundenes `X-Forwarded-For` sich nicht durchsetzt, und wann das
  Session-Cookie `Secure` bekommt.
- `test_kategorien.py` – startet den Server selbst und führt **jede** Kategorie
  aus der Konfiguration einmal durch: Formular, Absenden, Liste, Filter, CSV.
  Die Seed-Daten decken nur zwei ab, deshalb dieser eigene Durchlauf.

- `test_durchfahrt.py` – Durchfahrtsliste: nur Berechtigte, nur die vier
  Spalten, korrekt vorgekaute `data`-Attribute, und ein Abgleich, dass Python
  und JavaScript Kennzeichen identisch normalisieren (überspringt den Abgleich,
  wenn `node` fehlt). Dazu der offene Link: erzeugen, erneuern, zurückziehen,
  falsche Token, und dass die offene Ansicht nichts über die vier Spalten
  hinaus preisgibt.
- `test_durchfahrt_js.js` – die Filterlogik selbst, unter **node**, gegen
  dieselbe Datei, die der Browser lädt.

Die sechs legen sich eigene Wegwerf-Datenbanken unter dem Temp-Verzeichnis an.

## Mit Server

`tests/test_http.py` löscht Antrag 2 und sperrt am Ende die Anmeldung für die
eigene IP. **Nur gegen eine Wegwerf-Datenbank laufen lassen**, nie gegen die
echte.

```bash
DB=/tmp/test-abfahrt.db
rm -f "$DB"*

# 1. Server mit Testkonfiguration starten (eigenes Terminal)
DB_PATH="$DB" \
ADMIN_PASSWORD_HASH="$(.venv/Scripts/python.exe -m app.passwort 'test-passwort-123' | cut -d= -f2-)" \
APP_SECRET_KEY=test-schluessel \
COOKIE_SECURE=0 \
LOGIN_VERSUCHE=3 \
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8099 \
  --proxy-headers --forwarded-allow-ips 127.0.0.1

# 2. Testdaten anlegen und Test laufen lassen (anderes Terminal)
.venv/Scripts/python.exe tests/seed.py
TEST_DB="$DB" .venv/Scripts/python.exe tests/test_http.py
```

`COOKIE_SECURE=0` ist nötig, weil der Test über `http` läuft; `LOGIN_VERSUCHE=3`
erwartet der Rate-Limit-Abschnitt.

`tests/test_http.py` sperrt am Ende die Anmeldung für die eigene IP. Danach
entweder eine Minute warten oder den Server neu starten – der Zähler liegt im
Prozessspeicher.

## Freigabe (Schritt 5)

Gleicher Aufbau, aber der Server braucht zusätzlich `KONTINGENTE=camping:1`,
weil der Test die Kontingentwarnung prüft. Eigene Datenbank, frisch geseedet:

```bash
KONTINGENTE=camping:1  # beim Serverstart mitgeben
.venv/Scripts/python.exe tests/seed.py
TEST_DB="$DB" .venv/Scripts/python.exe tests/test_freigabe.py
```

## Mails über HTTP (Schritt 6)

```bash
.venv/Scripts/python.exe tests/seed.py
TEST_DB="$DB" .venv/Scripts/python.exe tests/test_mail_http.py
```

Prüft, dass Formular, Genehmigung, Ablehnung und Sammelaktion die Mails an der
richtigen Stelle einreihen, dazu Telefonliste und erneutes Anstoßen. Der Server
darf dafür **kein** `SMTP_HOST` gesetzt haben – sonst schickt der Worker die
Testmails wirklich los.

## CSV-Export (Schritt 8)

```bash
.venv/Scripts/python.exe tests/seed.py
TEST_DB="$DB" .venv/Scripts/python.exe tests/test_export.py
```

Prüft Kopfzeilen, BOM, CRLF, Maskierung von Trennzeichen, Anführungszeichen und
Zeilenumbrüchen, dass die Filter durchschlagen und dass keine IP-Spalte im
Export landet. Läuft der Server mit `CSV_TRENNER=,`, muss der Test
`TEST_CSV_TRENNER=,` mitbekommen.

## Karten drucken (Schritt 11)

Der Server braucht dafür `KARTEN_URL_BASIS=https://kennzeichen.example.de` und
**kein** `LOGO_DATEI` – der Test prüft auch den Hinweis, wenn kein Logo hinterlegt
ist.

```bash
.venv/Scripts/python.exe tests/seed.py
TEST_DB="$DB" .venv/Scripts/python.exe tests/test_karten.py
```

Prüft Anmeldepflicht, Inhalt der Karten, vier Stück je Bogen samt Umbruch, die
Filter, dass der QR-Code wirklich auf die Detailansicht zeigt (gegen ein selbst
erzeugtes SVG verglichen) und dass der Verweis aus der Liste nur Genehmigte
druckt.

`test_http.py`, `test_freigabe.py`, `test_mail_http.py`, `test_export.py` und
`test_karten.py` verändern alle die Daten und erwarten den Seed-Zustand – also je
einen eigenen Durchlauf mit frischer Datenbank, nicht hintereinander auf
derselben.

Steuerung über Env-Variablen: `TEST_BASIS` (Vorgabe
`http://127.0.0.1:8099`), `TEST_DB` (Pflicht), `TEST_PASSWORT` (Vorgabe
`test-passwort-123`).

Unter Windows gibt `PYTHONIOENCODING=utf-8` lesbare Umlaute in der Konsole.
