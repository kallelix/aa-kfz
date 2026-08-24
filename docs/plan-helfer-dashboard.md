# Helfer-Dashboard „Die absolute Abfahrt" – Projektplan

Dritte Anwendung neben Kennzeichen und Presse. Ersetzt das bisherige
Timetable-Projekt vollständig.

---

## 1. Ziel

Auf einem **zentralen Monitor** läuft ein Dashboard, das zeigt, wer wann wo
eingeteilt ist. Daneben pflegt die Orga im Backoffice Schichten, Helfer,
Zuordnungen und den Aufgabenplan.

Das Dashboard ist die eine Ansicht, auf die alle schauen – es muss ohne
Bedienung aktuell bleiben und aus einigen Metern lesbar sein.

---

## 2. Abgrenzung zum Timetable

Übernommen wird **alles Fachliche**:

| Timetable | im Dashboard |
| --- | --- |
| Programm der Rennserien (`kind=programm`) | bleibt, jetzt per Abruf statt abgetippt |
| Aufgabenplan (`kind=aufgabe`, Phasen, Status, Pool) | bleibt |
| Programm-Band mit Zeitachse | bleibt, ergänzt um Schichten |
| Zwei Rollen über geteilte Passwörter | wird die Anmeldung der anderen beiden Apps |
| Planner-Import (.xlsx, 3-Wege-Merge) | **entfällt** |
| PWA / Offline / Service Worker | siehe offene Fragen |

Neu dazu: **Schichten, Helfer und deren Zuordnung** – der eigentliche Anlass.

Der Wechsel bedeutet auch: Node/Express und `node:sqlite` weichen
Python/FastAPI und SQLite, damit alle drei Anwendungen dasselbe Deployment,
dieselbe Anmeldung und dieselbe Testweise haben. Das Design wird nachgebaut,
nicht der Code – Vereinsfarben, Kopfzeile, Badges und Programm-Band sind
übernehmenswert.

---

## 3. Der Zeitplan-Abruf

Entschieden: **echter HTTP-Abruf** von den Serien-Websites statt Abtippen.
Ich habe beide Seiten geprüft, das trägt – mit drei Fallstricken.

### Was da steht

Beide Seiten liefern den Zeitplan als saubere HTML-Tabelle:

```
Tag      | Beschreibung                      | Zeit
Freitag  | Startnummerausgabe                | 09.00 - 18.00 Uhr
         | Track Walk                        | 10.00 - 12.00 Uhr
```

| Quelle | Zeilen | Zustand |
| --- | --- | --- |
| [ixsdownhillcup.com](https://www.ixsdownhillcup.com/zeitplan/dhc-zeitplan) | 13 | abrufbar, HTTP 200 |
| [kidscup.bike](https://www.kidscup.bike/zeitplan) | 9 | abrufbar, HTTP 200 |

Die Zeiten stimmen exakt mit dem überein, was heute in `seed.js` steht.

### Fallstrick 1: die DHC-Seite hat zwei Zeitpläne

Auf der DHC-Seite stehen **zwei** Tabellen untereinander, unterschieden nur
durch die Überschrift davor:

| Überschrift | Track Walk | Training |
| --- | --- | --- |
| „DHC Zeitplan allgemein" | 10.00 – 12.00 | 12.00 – 18.00 |
| „Willingen" | 11.00 – 13.00 | 13.00 – 18.00 |

Ein Parser, der einfach die erste oder die letzte Tabelle nimmt, holt
irgendwann die falsche. **Die Auswahl muss über die Überschrift laufen**, und
findet er sie nicht eindeutig, bricht er ab, statt zu raten. Ilmenau braucht
den allgemeinen Plan – so steht es auch heute in `seed.js`.

### Fallstrick 2: keine Daten, nur Wochentage

In den Tabellen steht „Freitag", nicht „28.08.2026". Die Zuordnung passiert
über die konfigurierten Veranstaltungstage (`EVENT_VON` / `EVENT_BIS`). Zeilen
ohne Tag erben den vorherigen.

### Fallstrick 3: offene Enden

„ab 13.30 Uhr" und „anschließend" haben kein Ende. Das bleibt so – im Band
laufen solche Blöcke als Verlauf aus, wie im Timetable.

### Wie der Abruf sich verhält

- **Nicht beim Start, sondern auf Knopfdruck und per Zeitplan** (täglich).
  Ein Abruf beim Hochfahren würde den Dienst von fremden Servern abhängig
  machen.
- **Der letzte erfolgreiche Stand bleibt in der Datenbank.** Schlägt der Abruf
  fehl oder passt die Seite nicht mehr, ändert sich nichts und das Backoffice
  zeigt eine Warnung mit Zeitpunkt des letzten Erfolgs.
- **Änderungen werden angezeigt, nicht stillschweigend übernommen.** Der Abruf
  liefert einen Bericht: neu, geändert, verschwunden. Was die Orga selbst
  angefasst hat, gewinnt – dasselbe Prinzip wie beim Planner-Merge, nur ohne
  dessen Komplexität.
- Ein hinterlegter Rohstand (das geparste Ergebnis des letzten Laufs) macht
  nachvollziehbar, warum etwas als geändert gilt.

---

## 4. Die Monitor-Ansicht

Erreichbar über einen **widerrufbaren Link ohne Anmeldung**, wie die
Durchfahrtsliste – kein Passwort auf einem Bildschirm, den alle sehen.

- **Aktualisiert sich selbst**, ohne dass jemand F5 drückt.
- **Große Schrift**, hoher Kontrast, keine Bedienelemente.
- Zeigt: aktueller und nächster Zeitblock, wer gerade Dienst hat, wer als
  Nächstes dran ist, unbesetzte Schichten.
- Läuft die Verbindung weg, bleibt der letzte Stand stehen – mit sichtbarem
  Zeitstempel, damit niemand veraltete Daten für aktuell hält.

Was auf dem Monitor **nicht** zu sehen sein sollte: Telefonnummern und
Mailadressen der Helfer. Der Bildschirm hängt öffentlich.

---

## 5. Die beiden CSVs

`docs/Offene Posten.csv` und `docs/Vergebene Posten.csv`, beide UTF-8 mit BOM,
Komma als Trenner. **Beide sind vom Git ausgeschlossen** – die zweite enthält
Namen, Mailadressen, Verpflegungswünsche und T-Shirt-Größen, und das Repo ist
öffentlich.

| Datei | Spalten | Zeilen |
| --- | --- | --- |
| Offene Posten | Liste, Datum, Zeit, Aufgabe | 176 |
| Vergebene Posten | Name, Zusatz1, Zusatz2, Liste, Datum, Zeit, Aufgabe, Email, Phone | 237 |

`Zusatz1` ist die Verpflegung (Fleisch/Vegetarisch), `Zusatz2` die
T-Shirt-Größe.

### Eine Zeile ist ein Platz, keine Schicht

Das ist der entscheidende Punkt fürs Modell: „Streckenposten, 28.08.2026,
10:00 – 18:00" steht **zehnmal** in den offenen Posten – das sind zehn
unbesetzte Plätze derselben Schicht.

Eine Schicht ist also `(Liste, Datum, Zeit)`, und ihr Bedarf ist die Summe aus
besetzten und offenen Zeilen:

| | |
| --- | --- |
| Schichten insgesamt | **51** |
| Plätze insgesamt | **413** |
| davon besetzt | 237 |
| davon offen | 176 (57 %) |

Sechs Listen: Aufbau und Abbau (61 offen), Ordner Zeltplatz (53),
Straßensperre (41), Streckenposten (10), Shuttle (8), Absoluter Wiesenslalom
(3). Zeitraum 25.08. – 01.09.2026 – also Aufbau und Abbau mit drin, nicht nur
die Veranstaltungstage.

### Was in den Daten nicht stimmt

Der Import muss damit umgehen, sonst wandert der Ärger mit:

- **`Aufgabe` ist in beiden Dateien durchgehend leer**, ebenso **`Phone`**
  (237 von 237). Zwei tote Spalten – die Schichtbezeichnung steckt in `Liste`.
- **104 Namen, aber nur 90 Mailadressen.** Eine Adresse trägt **acht**
  verschiedene Namen: jemand hat mehrere Leute unter seiner Adresse
  angemeldet. Die Mailadresse taugt damit **nicht** als Identität – der Import
  muss über `(Name, Email)` gehen, und das Backoffice braucht eine Möglichkeit,
  Dubletten zusammenzuführen.
- **T-Shirt-Größen sind Freitext und entsprechend wild**: neben `S`–`XXXL` auch
  `xs`, `4xl`, `Xl`, `L.`, `Damen L`, `Shirt Gr.M`, `Größe L` und
  `Straßensperrung Aufbau Größe M`. Sechs Personen haben widersprüchliche
  Angaben auf verschiedenen Zeilen. Der Import normalisiert, was er erkennt,
  und lässt den Rest als Freitext stehen – erfunden wird nichts.
- **Eine T-Shirt-Größe steht im Verpflegungsfeld** (`Zusatz1 = "L"`).
  Vertauschte Spalte beim Ausfüllen.
- **Vieles ist leer**: 19 von 90 ohne T-Shirt-Größe, 39 von 90 ohne
  Verpflegungsangabe. Das Dashboard muss mit Lücken leben können.

## 6. Datenmodell

```sql
-- Aus dem Timetable uebernommen (ohne planner_id / planner_snapshot)
eintrag(id, kind, datum, phase, start, ende, titel, notiz, ort, kategorie,
        verantwortlich, kontakt, status, updated_at, quelle, quelle_stand)

-- Eine Schicht, nicht ein Platz. bedarf = wie viele gebraucht werden.
schicht(id, liste, datum, start, ende, bedarf, ort, hinweis, updated_at)

helfer(id, name, email, verpflegung, shirt_groesse, shirt_roh, bemerkung)

einteilung(id, schicht_id, helfer_id, quelle, angelegt_am,
           UNIQUE(schicht_id, helfer_id))
```

`quelle` unterscheidet, was aus Import oder Abruf stammt und was die Orga
selbst angelegt hat – nur Ersteres darf ein erneuter Lauf überhaupt anfassen.

`shirt_roh` behält die Originaleingabe neben der normalisierten Größe. Wenn
jemand `Damen L` geschrieben hat, ist das eine Information, die beim Bestellen
zählt.

---

## 7. Was aus dem Timetable erhalten bleibt

- **`updated_at`-Konfliktschutz**: jeder Schreibvorgang setzt ihn neu, der
  Client schickt seinen Stand mit, bei Abweichung `409` statt stillem
  Überschreiben. Bei mehreren Leuten am selben Plan ist das kein Luxus.
- **Programm-Band** mit Zeitachse, roter Linie für „jetzt", Balken nach Serie
  gefärbt.
- **Vorschlagslisten** aus dem Bestand statt fester Auswahlfelder.
- **Aufgabenpool** für alles ohne Datum.

---

## 8. Umsetzungsschritte

| # | Schritt | Aufwand |
|---|---|---|
| 1 | Gerüst `helfer/`, Config, Schema, Anmeldung (aus den Schwester-Apps) | 1,5 h |
| 2 | Einträge: Liste, Detail, Anlegen, Ändern, Löschen, `updated_at`-Schutz | 3 h |
| 3 | Zeitplan-Abruf mit Tabellenwahl, Wochentag-Zuordnung, Bericht | 3 h |
| 4 | CSV-Import für Schichten und Helfer | 2 h |
| 5 | Einteilung: Helfer auf Schichten, Bedarf und Lücken sichtbar | 3 h |
| 6 | Programm-Band mit Schichten darunter | 3 h |
| 7 | Monitor-Ansicht mit Token-Link und Selbstaktualisierung | 2,5 h |
| 8 | CSV-Export | 0,5 h |
| 9 | Deployment: dritte Unit, dritter nginx-Block, drittes Backup | 1 h |
| 10 | Timetable ablösen: Daten übernehmen, alten Dienst abschalten | 1,5 h |

---

## 9. Geklärt

- Python/FastAPI als dritte App im selben Repo
- Übernimmt **alles** vom Timetable, auch den Aufgabenplan
- Zeitplan per **echtem HTTP-Abruf** von den Serien-Websites
- Monitor über **Token-Link ohne Anmeldung**
- Planner-Import entfällt

## 10. Offene Fragen

1. **Dubletten**: Soll der Import die acht Namen unter einer Adresse als acht
   Helfer anlegen (vermutlich richtig – es sind acht Personen), und das
   Backoffice bekommt ein „zusammenführen"? Oder anders herum?
2. **T-Shirt-Größen**: normalisieren auf XS–4XL und Abweichungen wie
   „Damen L" als Zusatz behalten – oder alles als Freitext lassen und nur beim
   Bestellen sortieren?
3. **Veranstaltungstage**: 28.–30.08.2026 wie in `seed.js`? Der Abruf braucht
   sie, um Wochentage auf Daten abzubilden.
4. **Bestandsdaten aus dem Timetable**: Gibt es dort schon gepflegte Aufgaben,
   die übernommen werden müssen, oder ist die Datenbank noch leer?
5. **PWA und Offline**: Der Timetable ist eine installierbare App mit Service
   Worker. Braucht das Dashboard das auch – etwa für Helfer, die es auf dem
   Handy dabeihaben – oder genügt die Monitor-Ansicht plus Backoffice?
6. **Sehen Helfer ihre eigene Einteilung?** Ein zweiter Token-Link mit einer
   „Wer hat wann Dienst"-Ansicht wäre naheliegend, ist aber nicht gefordert.
7. **Benachrichtigung**: Sollen Helfer per Mail erfahren, wann sie eingeteilt
   sind? Der Mailversand steht in beiden Schwester-Apps bereits.
