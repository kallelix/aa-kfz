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
gegebenenfalls als Reserve.

## Der Assistent

Neben der Liste der zweite Weg (Lastenheft 3.1, A-01 bis A-05): *Ich sage,
wann ich Zeit habe*. Drei Seiten, die nichts speichern – die Wahl reist als
Parameter mit, bis zu denselben Angaben wie aus der Liste.

1. **Wann hast du Zeit?** Je Tag Vormittag, Nachmittag und Abend. Tage mit
   Schichten vor und nach der Veranstaltung stehen als Aufbau und Abbau
   getrennt davor und danach; als Springer geht es dort jetzt auch aus der
   Liste.
2. **Was machst du gern?** Draußen an der Strecke, mit Menschen, anpacken,
   fahren, egal. Wozu ein Bereich passt, hakt die Orga im Bereich an
   („Passt zu“). Ein Bereich ohne Haken passt zu allem.
3. **Das passt zu dir.** Nur Schichten, von denen mindestens drei Viertel in
   den angetippten Zeiten liegen – eine Nachtschicht zählt zum Abend ihres
   ersten Tages – und die zu den Vorlieben passen; volle nicht. Unter
   Minimum zuerst, dann unter Soll, dann als Reserve. Antippen genügt; mit
   Skript graut aus, was sich überschneidet. Darunter der Springer für die
   angetippten Zeiten, offen, wenn jemand „egal“ sagt oder nichts passt.

Die Vorlieben stehen danach an der Teilnahme; die Orga sieht sie bei der
Person unter „Macht gern“.

## Mein Helferplatz

Nach der Anmeldung geht es ohne Konto und ohne Passwort weiter (Lastenheft
2.4, 7.4) – jeder Weg hängt an einem persönlichen Link:

- **Bestätigen:** Die erste Mail enthält einen Link und einen sechsstelligen
  Code. Der Link öffnet nur eine Seite mit dem Knopf „Ja, das bin ich“, weil
  Mailscanner Links vorab aufrufen; den Code nimmt die Dankeseite, für wen die
  Mail auf einem anderen Gerät ankommt (nach fünf falschen nur noch der Link).
  Unbestätigt halten die Plätze 72 Stunden, nach 24 kommt eine Erinnerung;
  danach sind sie frei und die Angaben gelöscht.
- **Mein Helferplatz** (`/platz/<link>`): alle Schichten mit Treffpunkt und
  Ansprechpartner samt Nummer, auch die der Mitangemeldeten; Schichten
  dazunehmen für sich, für die eigenen Leute und für neue, die mitkommen.
  Was hinter einer Einsatzgrenze liegt, steht dort gar nicht erst.
- **Kalender-Abo** (`/kalender/<link>.ics`): aktualisiert sich selbst und
  darf nur lesen – der Link zu Mein Helferplatz steht nicht darin.
- **Wer wiederkommt**, wird an Name und Adresse erkannt und bekommt seinen
  Link mit der eben getroffenen Auswahl, statt ein zweites Mal angelegt zu
  werden. Ein Name in anderer Schreibweise mit derselben Adresse oder Nummer
  löst „Bist du schon bei uns?“ aus; solche Paare stehen in der Übersicht.
  „Link anfordern“ auf der Startseite verrät nicht, ob eine Adresse bekannt ist.

Die Links stehen nirgends gespeichert: sie sind ein Siegel über Person und
Zweck mit `APP_SECRET_KEY` (`app/zugang.py`). Wer den Schlüssel wechselt,
macht jeden Link in jeder verschickten Mail ungültig.

Mails gehen wie in Kennzeichen und Presse über `mail_out` und einen Worker
(`app/versand.py`), der auch die Fristen wahrt – beides nur, wenn `SMTP_HOST`
und `MAIL_FROM` gesetzt sind. Verschickte Mails werden nach einem Monat
gelöscht.

## Noch eine Schicht? und das gemeinsame Ziel

Die erste Schicht ist leicht – es geht um die zweite und dritte (Lastenheft
2.6, G-03, G-04):

- Gleich nach dem Eintragen schlagen Dankeseite und Mein Helferplatz bis zu
  drei Schichten vor: am liebsten direkt davor oder danach im selben
  Bereich, dann am selben Tag, dann was dringend gebraucht wird. Nur was für
  alle frei ist, sich mit nichts überschneidet, zum Alter passt und keine
  Voraussetzung verlangt, die noch niemand bestätigt hat. Fehlt für ein
  Goodie genau eine Schicht, heißt es „Noch eine Schicht bis: …“. Auf der
  Dankeseite trägt ein Klick ein, für alle, die zusammen angemeldet sind.
- Die Startseite zeigt je Tag, wie viele der geplanten Plätze besetzt sind –
  das Wir, keine Rangliste.

## Unter Last

Der Lasttest (Lastenheft 2.10, `tests/test_last.py`) prüft, was bei einem
Hilferuf passiert, wenn viele gleichzeitig klicken:

- 200 Anmeldungen auf dieselben zehn Plätze aus 50 Threads: genau zehn drin,
  190 freundlich abgewiesen, nichts anderes. Ebenso über HTTP mit 200
  gleichzeitigen Anfragen.
- Dreißig wollen in fünf Plätze tauschen: fünf schaffen es, niemand steht
  doppelt oder nirgends. Paare, die in Gegenrichtung tauschen, blockieren
  sich nicht – jede Transaktion sperrt Schichten in derselben Reihenfolge,
  aufsteigend nach id (`db._sperren`). Der Test hatte vorher genau diesen
  Deadlock gefunden.
- Die Anmeldung und die öffentlichen Seiten laufen in Threads, nicht im
  Hauptstrang des Servers: sie sprechen viel mit der Datenbank, und sonst
  hielte jede alle anderen auf. Lokal (Docker unter Windows, gut 20 ms je
  Verbindungsaufbau) wartet die letzte von 200 gleichzeitigen Anmeldungen
  rund 5 Sekunden, die letzte von 200 Schichtlisten rund 2. Auf dem Server
  über den Unix-Socket ist der Verbindungsaufbau schneller.

## Datenschutz und Jugendschutz

Seit Lastenheft 2.9 (D-01 bis D-07):

- Jedes Formular sagt kurz, wofür die Angaben sind, und verweist auf
  `/datenschutz` – Verantwortlicher (`VERANTWORTLICH`), Zwecke mit
  Rechtsgrundlagen, Speicherdauer, Rechte. Der Text ist ein Entwurf und
  gehört vor dem Start fachkundig geprüft (D-09).
- **Helferstamm** nur mit eigener Einwilligung: ein freiwilliges, nicht
  vorangekreuztes Häkchen bei der Anmeldung, in Mein Helferplatz unter
  „Angaben ändern“ genauso leicht wieder weg. Ohne Einwilligung wird nach der
  Veranstaltung gelöscht.
- **Unter 18** fragt das Formular nach einer erziehungsberechtigten Person.
  Sie bekommt eine Mail mit den Schichten und einem Knopf; erst dann gilt die
  Anmeldung. Nach 24 Stunden geht eine Erinnerung, nach 72 sind die Plätze
  frei. Wer jemanden mitanmeldet und sich selbst als erziehungsberechtigt
  einträgt (gleiche Adresse), bestätigt das Einverständnis mit der eigenen
  Adresse. Im Backoffice und auf den Listen steht „Eltern fehlen“.
- **Richtschnur für Jugendliche**: wer unter 18 an einem Tag mehr als 8
  Stunden eingeteilt ist oder vor 6 bzw. nach 20 Uhr, steht in der Übersicht
  unter „Bitte prüfen“ – ein Hinweis, keine Sperre.

## Stufen, Springer und der Monitor

Seit Lastenheft 2.7 (R-02, R-06, T-04) färben Übersicht, Schichtliste,
Bereich und Monitor nach Stufen statt nach Bedarf: **rot** unter Minimum –
darunter geht es nicht –, **gelb** unter Soll, **grün** ab Soll. Die Reserve
zählt nie als fehlend, steht aber als „+1“ dabei. Die Übersicht hat eine
Kachel „Unter Minimum“ und zeigt rot vor gelb.

Wer als Springer gerade da ist und nirgends eingeteilt, steht in der
Übersicht mit Nummer und auf dem Monitor mit Namen – dazu, wie viele in den
nächsten drei Stunden kommen. Kurzfristige Absagen stehen auf dem Monitor
oben, ohne Namen und Grund: der Bildschirm hängt im Zelt. Hervorgehoben wird
dort wie bisher erst ab `MONITOR_WARNUNG` fehlenden Leuten.

## Drucken

Unter Vor Ort → Drucken (Lastenheft 2.8, L-01 bis L-04), jederzeit aktuell –
die Seite ist die Liste, gedruckt wird aus dem Browser, A4 hoch:

- **Schicht** (an der Schicht), **Bereich** je Tag oder alle Tage, **Tag**
  gesamt, **Person** (an der Person).
- Kopf mit Bereich, Zeit, Treffpunkt und Bereichsleitung samt Nummer; Spalten
  zum Abhaken für *da*, Shirt (wenn es welche gibt) und Funk; zwei leere
  Zeilen für die, die am Tag dazukommen; die Warteliste darunter. Wer
  mitangemeldet ist, steht mit der Nummer der Person, die angemeldet hat.
- **Notfallmappe** je Tag: Deckblatt mit Orga, Bereichsleitungen und den
  Springern des Tages, dann je Bereich eine Seite. Am Vorabend drucken.
- Eine Bereichsleitung druckt nur ihre Bereiche. Einsatzgrenzen stehen auf
  keinem Ausdruck.

## Selbstbedienung

Was Helfer heute die Orga anschreiben müssten, erledigen sie in Mein
Helferplatz selbst – ohne Frist, auch kurz vorher und während der
Veranstaltung (Lastenheft 2.5, 5.3):

- **Absagen** mit einer Rückfrage und freiwilligem Grund; die Seite bedankt
  sich. **Tauschen** in einem Schritt – die neue Schicht zuerst, dann wird
  die alte frei; geht die neue nicht, bleibt die alte. **Ganz abmelden**,
  **Springer-Zeiten absagen**.
- **Angaben ändern**: Handy, Shirt, Essen, Bemerkung. Eine neue Adresse gilt
  erst, wenn sie bestätigt ist; eine mitangemeldete Person mit eigener
  Adresse verwaltet sich danach selbst.
- **Daten löschen**, auch einzeln für Mitangemeldete. Ist noch ein
  Funkgerät ausgeliehen, wird nach der Rückgabe gelöscht, samt Unterschrift.
  Schlüssel hängen nur am Namen, nicht an der Person – die zählen hier nicht.
- **Warteliste**: Ist eine Schicht voll, lässt sie sich ankreuzen. Wird ein
  Platz frei – durch Absage, Tausch, Austragen von Hand oder eine verfallene
  Anmeldung –, rückt erst die Reserve auf, dann bekommt die Erste auf der
  Warteliste den Platz angeboten und hält ihn 24 Stunden (höchstens bis
  Schichtbeginn). Ohne Antwort geht er an die Nächste.
- **Meldung**: Ist eine Absage kurzfristig (unter 24 Stunden oder während
  der Veranstaltung) oder fällt die Schicht unter ihr Minimum, geht sofort
  eine Mail an die Bereichsleitung, ohne Bereichsleitung an `KONTAKT_MAIL`.
  Kurzfristige Absagen stehen oben in der Übersicht und unter „Meine
  Bereiche“, mit den Springern, die jetzt könnten – auf dem Monitor ohne
  Namen und Grund.
- **Protokoll und „Änderungen“**: Was Helfer selbst tun, was die Orga von
  Hand ein- und austrägt und was nachrückt, steht im Protokoll der Person und
  unter Übersicht → Änderungen (seit gestern, drei Tagen, einer Woche); die
  Bereichsleitung sieht dort nur ihre Bereiche.

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

## Dubletten

Wer zweimal angelegt ist – „Lena Müller“ und „Lena Mueller“ mit derselben
Adresse –, steht in der Übersicht unter „Vielleicht dieselbe Person“
(Lastenheft 2.4, I-05). Zusammengeführt wird im Backoffice (3.2, I-06): aus
der Übersicht oder von der Seite der Person, auch über die Nummer einer
anderen. Die Vergleichsseite zeigt beide nebeneinander; die Orga wählt, wer
bleibt.

- Mit dem zweiten Eintrag wandern Schichten, Warteliste, Springer-Zeiten,
  Teilnahmen mit Vorlieben und Bemerkung, Einsatzgrenzen, Ausleihen, die
  Unterschrift unter der Shirt-Ausgabe, Absagen, Mails und der Verlauf;
  wen er mitangemeldet hatte, hat danach der bleibende mitangemeldet. Was
  doppelt wäre, bleibt einmal.
- Stand die Person zweimal auf einer Schicht, wird ein Platz frei. Der geht
  wie jeder andere an Reserve und Warteliste.
- Was dem bleibenden fehlt – Nummer, Größe, Verpflegung, Alter, ausgegebenes
  Shirt –, kommt vom anderen; sein Name bleibt.
- Sind es zwei Menschen, etwa Geschwister mit einer Adresse, merkt die Orga
  das an; das Paar steht dann nicht mehr in der Liste.
- Das darf nur die Orga, nicht die Bereichsleitung und kein lesendes Konto.

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
.venv/Scripts/python.exe helfer/tests/test_helferplatz.py  # Bestätigen, Mein Helferplatz, Kalender
.venv/Scripts/python.exe helfer/tests/test_selbstbedienung.py  # Absagen, Tauschen, Warteliste, Löschen
.venv/Scripts/python.exe helfer/tests/test_druck.py        # Noch eine Schicht?, Tagesbalken, Drucken
.venv/Scripts/python.exe helfer/tests/test_stufen.py       # Stufen, Springer, Absagen auf dem Monitor
.venv/Scripts/python.exe helfer/tests/test_datenschutz.py  # Einwilligung, Eltern, Löschwerkzeug
.venv/Scripts/python.exe helfer/tests/test_last.py         # 200 gleichzeitig, Tauschen gegeneinander
.venv/Scripts/python.exe helfer/tests/test_assistent.py    # Zeit, Vorlieben, Vorschläge, Springer
.venv/Scripts/python.exe helfer/tests/test_dubletten.py    # zusammenführen, auseinanderhalten
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
