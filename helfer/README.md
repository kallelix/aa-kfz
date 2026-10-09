# Helfer-Dashboard

Einer der drei Bereiche im gemeinsamen Dienst – wie das Ganze zusammenhängt,
steht in der [Übersicht](../README.md). Schichten, Helfer und ihre Einteilung,
der Aufgabenplan, die Ausgabe von T-Shirts, Funkgeräten und KFZ-Schlüsseln –
und ein Monitor, auf den alle schauen. Grundlage ist
[docs/plan-helfer-dashboard.md](../docs/plan-helfer-dashboard.md).

| Adresse | was dort liegt |
| --- | --- |
| `helfer.example.de/` | die öffentliche Anmeldung: welche Veranstaltung Helfer sucht |
| `helfer.example.de/aa-2027` | die Anmeldung einer Veranstaltung, Kurzlink aus ihrem Kurznamen |
| `helfer.example.de/monitor/<token>` | Monitoransicht, ohne Anmeldung |
| `helfer.example.de/unterschrift/<token>` | Unterschriften-Tablet, ohne Anmeldung |
| `admin.example.de/helfer` | Backoffice |

Monitor und Tablet sind über einen langen, widerrufbaren Token geschützt statt
über ein Passwort – der Bildschirm im Zelt kann keines eingeben. Beide Links
werden im Backoffice erzeugt.

## Öffentliche Anmeldung

Helfer melden sich selbst an (Lastenheft 2.2), ohne Konto: Schichten in einer
Liste ankreuzen, nach Tag gegliedert, mit freien Plätzen im Klartext – dann
die Angaben, dann eine Dankeseite. Was dabei gilt:

- Zu sehen ist eine Veranstaltung erst ab dem Status *angekündigt*; dann gibt
  es nur ihre Startseite, auf der man Interesse vormerken kann. Anmelden geht
  bei *Anmeldung offen* und innerhalb des Anmeldezeitraums.
- Je Schicht gibt es zuerst Plätze bis zum Soll, dann Reserve; ist auch die
  voll, ist die Schicht voll. Belegt wird unter Sperre, gleichzeitige
  Anmeldungen überholen sich nicht.
- Was sich überschneidet, geht nicht – zwei Schichten, eine Schicht und eine
  Springer-Zeit, eine neue Schicht und eine, für die jemand schon eingetragen
  ist. Mit Skript ist es in der Liste gleich ausgegraut; geprüft wird beim
  Absenden ohnehin.
- Vor- und Nachname, Mail und das Alter sind Pflicht; Shirt (mit Schnitt) und
  Essen nur, wenn die Veranstaltung sie anbietet. Unter 12 geht es nicht, das
  Mindestalter der Schichten wird geprüft, Voraussetzungen werden bestätigt.
- Weitere Personen lassen sich mitanmelden; sie stehen auf denselben
  Schichten, zählen eigens, und Ansprechpartner bleibt, wer anmeldet.
- Statt Schichten geht auch Springer: Tag mal Vormittag, Nachmittag, Abend.

Wer sich anmeldet, steht danach in denselben Tabellen wie importierte oder von
Hand eingeteilte Helfer – im Backoffice mit der Quelle „selbst angemeldet“ und
gegebenenfalls als Reserve. Bestätigung per Mail und „Mein Helferplatz“ folgen
mit Schritt 2.4.

## Einsatzgrenzen

Für Helfer mit Einschränkungen, die aus dem Gedanken der Inklusion dabei sind
(Lastenheft 2.3, K-05 bis K-09). Die Orga setzt sie auf der Seite der Person:
einen Bereich oder eine Schicht **nicht anbieten**, einen Bereich **nur zu
zweit**. Gespeichert wird nur die Grenze, nie der Grund – es gibt dafür auch
kein Feld.

- Die Grenzen wirken still. Wer sich für eine Schicht hinter einer Grenze
  anmeldet, bekommt wortgleich dieselbe Antwort wie bei einer vollen Schicht.
  Erkannt wird die Person wie beim Import an Name und Adresse.
- Steht jemand mit „nur zu zweit“ allein in einer Schicht, zeigen die
  Übersicht, die Schicht und – für die Bereichsleitung – „Meine Bereiche“ einen
  Hinweis, ohne Begründung. Auf dem Monitor steht nichts davon.
- Sehen dürfen die Grenzen Orga und Admin, die Bereichsleitung nur die in
  ihren Bereichen; lesende Konten nicht. In der CSV-Ausfuhr stehen sie nicht.
- Einteilen von Hand trotz Grenze geht nur für die Orga und nur mit Vermerk.
- Jede Änderung steht im Protokoll der Person; geht die Person, gehen
  Grenzen und Protokoll mit. Die Vorlage aus dem Vorjahr nimmt Grenzen auf
  ganze Bereiche mit, die auf einzelne Schichten nicht.

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

Das Backoffice gliedert sich in Reiter, Gruppen und Seiten (siehe
[README](../README.md#navigation)). Der Helferbereich liefert Seiten für drei
Reiter.

**Helfer**, nach dem Ablauf:

- **Übersicht** – der Stand auf einen Blick
- **Planen**
  - **Bereiche & Schichten** – wo geholfen wird (Shuttle, Streckenposten,
    Orgabüro) mit Beschreibung, Treffpunkt, Bereichsleitung, Mindestalter,
    Voraussetzungen und dem Haken *intern*; darin die Schichten, jede mit
    **Minimum** (darunter geht es nicht), **Soll** (so ist es geplant) und
    **Reserve** (zusätzlich willkommen, fehlt nie). Drei Ansichten: Bereiche,
    alle Schichten, nur Lücken. Hat eine Veranstaltung noch keine Bereiche,
    lassen sie sich samt Schichten und Goodies aus einer früheren übernehmen;
    die Schichten wandern dabei auf die neuen Tage.
  - **Aufgaben** – der Aufgabenplan mit Phasen und Status. Arbeiten zwei Leute
    gleichzeitig am selben Eintrag, überschreibt keiner den anderen, ohne es
    zu merken.
  - **Zeitplan** – das Programm-Band der Rennserien mit den Schichten darunter
- **Leute** – **Helfer**: Stammdaten, CSV-Ausfuhr
- **Vor Ort**
  - **Shirts & Goodies** – die T-Shirt-Ausgabe, nur wenn die Veranstaltung
    Goodies mit Shirt ausgibt
  - **Monitor** – der Link für den Bildschirm

**Ausgabe** – Funkgeräte und KFZ-Schlüssel ausgeben und zurücknehmen. Der
Fahrzeugstamm baut sich bei der Schlüsselausgabe nebenbei auf. Bei der Ausgabe
unterschreibt der Helfer auf dem Tablet, bei der Rücknahme nicht – wer etwas
hinlegt, ist meist schon wieder weg.

**Verwaltung**, bei der gewählten Veranstaltung – was man für sie einmal
einrichtet:

- **Goodies & Verpflegung** – ob es Goodies gibt (ein Schalter); wenn ja, das
  Helfershirt mit einem Schnitt oder Damen- und Herrenschnitt und kleine
  Dankeschöns mit Schwelle („ab 2 Schichten ein Bier am Bierwagen, unter 16
  eine Eistüte“). Dazu Verpflegung und Helferparty.
- **Import** – die beiden CSV-Dateien aus dem Registrierungstool hochladen
  oder abrufen lassen, von Hand oder selbsttätig im Takt. Ein selbsttätiger
  Lauf übernimmt nichts, was nach einem Ausfall aussieht.
- **Zeitplan-Abruf** – holt die Zeitpläne der Rennserien täglich von deren
  Websites und bildet die Wochentage auf die Renntage ab.
- **Material** und **Tablet** – was bei einer Ausgabe vorgeschlagen wird, und
  der Link fürs Tablet, auf dem unterschrieben wird.

Die Adressen sind dieselben geblieben (`/helfer/funk`, `/helfer/goodies` …);
nur die Navigation ordnet sie anders ein.

Ein Konto mit der Rolle *Bereichsleitung* sieht nur den Reiter Helfer und
darin *Meine Bereiche* – beschränkt auf die Bereiche, die es leitet. Dort
ändert es Angaben und Schichten, teilt ein und trägt aus und sieht die Leute
auf seinen Schichten. Neue Bereiche, die Ausgabe, die ganze Helferliste,
Monitor und Verwaltung bleiben der Orga. Die Bereichsleitung sind ein oder
mehrere Konten am Bereich; Name und Nummer kommen von dort.

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
.venv/Scripts/python.exe helfer/tests/test_anmeldung.py    # die öffentliche Anmeldung
.venv/Scripts/python.exe helfer/tests/test_grenzen.py      # Einsatzgrenzen
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
