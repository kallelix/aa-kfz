# Helfer-Dashboard

Einer der drei Bereiche im gemeinsamen Dienst – wie das Ganze zusammenhängt,
steht in der [Übersicht](../README.md). Schichten, Helfer und ihre Einteilung,
der Aufgabenplan, die Ausgabe von T-Shirts, Funkgeräten und KFZ-Schlüsseln –
und ein Monitor, auf den alle schauen. Grundlage ist
[docs/plan-helfer-dashboard.md](../docs/plan-helfer-dashboard.md).

| Adresse | was dort liegt |
| --- | --- |
| `helfer.example.de/monitor/<token>` | Monitoransicht, ohne Anmeldung |
| `helfer.example.de/unterschrift/<token>` | Unterschriften-Tablet, ohne Anmeldung |
| `admin.example.de/helfer` | Backoffice |

Monitor und Tablet sind über einen langen, widerrufbaren Token geschützt statt
über ein Passwort – der Bildschirm im Zelt kann keines eingeben. Beide Links
werden im Backoffice erzeugt.

## Starten

Im Alltag als Teil des Dienstes, siehe [Übersicht](../README.md#lokal-starten).
Einzeln geht es weiterhin – so starten auch die Tests ihren Server:

```bash
cp helfer/.env.example helfer/.env
.venv/Scripts/python.exe -m kern.passwort      # Hash in helfer/.env
cd helfer
../.venv/Scripts/python.exe -m app
```

Vorgabeport ist dann 8082, Backoffice unter <http://127.0.0.1:8082/helfer>.

## Was der Bereich macht

Das Backoffice hat sieben Punkte, in denen gearbeitet wird:

- **Übersicht** – der Stand auf einen Blick
- **Zeitplan** – das Programm-Band der Rennserien mit den Schichten darunter
- **Aufgaben** – der Aufgabenplan mit Phasen und Status. Arbeiten zwei Leute
  gleichzeitig am selben Eintrag, überschreibt keiner den anderen, ohne es
  zu merken.
- **Schichten** – Soll, Besetzung und Lücken; Helfer zuordnen und entfernen
- **Helfer** – Stammdaten, T-Shirt-Ausgabe, CSV-Ausfuhr
- **Funken**, **Schlüssel** – Ausgabe und Rücknahme von Funkgeräten und
  KFZ-Schlüsseln. Der Fahrzeugstamm baut sich bei der Schlüsselausgabe
  nebenbei auf.

Ein Konto mit der Rolle *Bereichsleitung* sieht nur zwei Punkte: *Meine
Bereiche* und *Schichten* – beides beschränkt auf die Bereiche, die es
leitet. Dort ändert es Angaben und Schichten, teilt ein und trägt aus und
sieht die Leute auf seinen Schichten. Neue Bereiche, die Ausgabetische, die
ganze Helferliste, Monitor und Import bleiben der Orga.

Dahinter, was man einmal einrichtet: Bereiche, Goodies, Einstellungen,
Monitor-Link, Import, Unterschriften und Zeitplan-Abruf.

- **Bereiche**: wo geholfen wird – Shuttle, Streckenposten, Orgabüro – mit
  Beschreibung, Treffpunkt, Bereichsleitung, Mindestalter, Voraussetzungen
  und dem Haken *intern*. Die Bereichsleitung sind ein oder mehrere Konten;
  Name und Nummer kommen von dort. Darin die Schichten, jede mit drei Zahlen:
  **Minimum** (darunter geht es nicht), **Soll** (so ist es geplant) und
  **Reserve** (zusätzlich willkommen, fehlt nie). Eine Schicht kann ein
  eigenes Mindestalter haben und eigens intern sein. Hat eine Veranstaltung
  noch keine Bereiche, lassen sie sich samt Schichten und Goodies aus einer
  früheren übernehmen; die Schichten wandern dabei auf die neuen Tage.
- **Goodies**: was die Veranstaltung ihren Helfern bietet – Helfershirt,
  Verpflegung, Helferparty – und kleine Dankeschöns mit Schwelle („ab 2
  Schichten ein Bier am Bierwagen, unter 16 eine Eistüte“).

- **Import**: die beiden CSV-Dateien aus dem Registrierungstool hochladen –
  oder sie abrufen lassen, von Hand oder selbsttätig im Takt. Ein
  selbsttätiger Lauf übernimmt nichts, was nach einem Ausfall aussieht.
- **Zeitplan-Abruf**: holt die Zeitpläne der Rennserien täglich von deren
  Websites und bildet die Wochentage auf die Renntage ab.
- **Unterschriften**: bei der Ausgabe von Material und Schlüsseln unterschreibt
  der Helfer auf dem Tablet. Bei der Rücknahme nicht – wer etwas hinlegt, ist
  meist schon wieder weg.

Kein Mailversand. Damit entfallen `mail.py`, `worker.py` und die Tabelle
`mail_out`, die die anderen beiden Bereiche haben.

## Konfiguration

Siehe [.env.example](.env.example). Gelesen wird `helfer/.env`, im Betrieb die
Datei, auf die `HELFER_ENV` zeigt. Was für alle drei Bereiche gilt, steht in
der [Übersicht](../README.md#konfiguration). Erwähnenswert:

- `ZEITZONE` – die Uhr, nach der Dashboard und Monitor gehen, unabhängig
  davon, wie der Server gestellt ist. Die Renntage stehen nicht mehr hier,
  sondern an der Veranstaltung (siehe unten)
- `JETZT_FEST` – stellt die Uhr auf einen festen Zeitpunkt, für Durchsichten
  außerhalb der Veranstaltung. **Im Betrieb leer lassen.** Eine gestellte Uhr
  schaltet außerdem Zeitplan-Abruf und Helferabgleich ab.
- `ZEITPLAN_SERIEN`, `ZEITPLAN_STUNDE` – welche Serien wann abgerufen werden
- `IMPORT_LOGIN_URL`, `IMPORT_URL_VERGEBEN`, `IMPORT_URL_OFFEN` – die Adressen
  für den Abruf der Helferliste. **Sie enthalten Zugangstoken und gehören nur
  in die `.env`**, nie ins Repository – es ist öffentlich.
- `IMPORT_TAKT_MINUTEN` – Abstand der selbsttätigen Abgleiche, 0 schaltet ab
- `MONITOR_…` – Auffrischung, Vorschau und Rücksprung der Monitoransicht
- `UNTERSCHRIFT_…` – wie lange eine Anforderung auf dem Tablet steht und was
  dort über die Aufbewahrung gesagt wird

## Tests

Aus dem Hauptordner:

```bash
.venv/Scripts/python.exe helfer/tests/test_band.py         # Programm-Band, reine Rechnerei
.venv/Scripts/python.exe helfer/tests/test_zeitplan.py     # Zeitplan-Abruf, ohne Netz
.venv/Scripts/python.exe helfer/tests/test_abruf.py        # Abruf der Helferliste, ohne Netz
.venv/Scripts/python.exe helfer/tests/test_import.py       # CSV-Import und Backoffice
.venv/Scripts/python.exe helfer/tests/test_aufgaben.py     # Aufgabenplan, Konfliktschutz
.venv/Scripts/python.exe helfer/tests/test_material.py     # T-Shirts, Funkgeräte, Schlüssel
.venv/Scripts/python.exe helfer/tests/test_unterschrift.py # Unterschriften am Tablet
.venv/Scripts/python.exe helfer/tests/test_monitor.py      # Monitor mit gestellter Uhr
.venv/Scripts/python.exe helfer/tests/test_bereiche.py     # Bereiche, Schichten, Goodies, Vorlage
```

Die ersten drei laufen ohne Server, die übrigen starten ihn selbst und legen
sich eine Wegwerf-Datenbank an, im PostgreSQL aus `compose.yaml`. Es geht
nichts nach draußen: die Seiten der
Rennserien und des Registrierungstools sind nachgebaut.

## Deployment

Gemeinsam mit den anderen beiden Bereichen, siehe
[deploy/README.md](../deploy/README.md). Was nur für diesen Bereich gilt –
ausgehende Verbindungen, Monitor-Link, Import und Ausfuhr – steht dort gesammelt
in [Abschnitt 7](../deploy/README.md#7-was-nur-für-einen-bereich-gilt). Die
eigenen Werte stehen in `/etc/abfahrt/helfer.env`, Vorlage
[deploy/helfer.env.example](../deploy/helfer.env.example).
