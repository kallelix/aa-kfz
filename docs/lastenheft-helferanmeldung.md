# Helferanmeldung – Lastenheft und Umsetzungsplan

Ablösung von helferliste.online durch eine eigene Anmeldung im Helferbereich.
Stand: Entwurf zur Diskussion, Oktober 2026.

---

## 0. Kurzfassung

Heute melden sich die Helfer bei helferliste.online an, und das Dashboard holt
sich die Daten von dort per CSV-Abruf. Das funktioniert, aber die Daten kommen
schmutzig an, die Anmeldung ist unübersichtlich, und alles, was die Orga mit
den Helfern über die Jahre aufbauen will, liegt bei einem fremden Werkzeug,
das an einer Einzelperson hängt.

Die neue Anmeldung wird Teil des Helferbereichs, den es schon gibt. Sechs Dinge
ändern sich grundlegend:

1. **Die Daten entstehen sauber, statt nachträglich geputzt zu werden.** Vor-
   und Nachname getrennt und Pflicht, T-Shirt-Größe und Verpflegung als
   Auswahl, Mailadresse bestätigt, Dubletten werden beim Anmelden erkannt.
2. **Verfügbarkeit zuerst.** Wer möchte, sagt zuerst, wann er Zeit hat, und
   bekommt nur passende Schichten angeboten – die dringendsten zuerst. Wer
   schon weiß, was er will, nimmt die Liste.
3. **Parallele Schichten gehen nicht mehr.** Eine Überschneidung wird
   verhindert, nicht nur gemeldet.
4. **Helfer verwalten sich selbst**: Schichten stornieren und umbuchen, ganz
   abmelden, Daten löschen – ohne die Orga anschreiben zu müssen.
5. **Ein Helferstamm über die Jahre** – mit Einwilligung, Ankündigung der
   nächsten Veranstaltungen, Hilferufen bei knappen Schichten und einer
   Anerkennung, die zur zweiten und dritten Schicht motiviert.
6. **Echte Benutzer im Backoffice** statt eines gemeinsamen Passworts, und
   beliebig viele Veranstaltungen statt nur der Absoluten Abfahrt.

Ziel ist, dass die Anmeldung **im Dezember 2026** auf dem neuen System
öffnet – für die Absolute Abfahrt 2027 (1.–4. Juli, mit Auf- und Abbau
davor und danach) und für jede andere Veranstaltung des ILRC, die Helfer
braucht. Dafür reichen Phase 1 und 2 aus Abschnitt 9; der
Assistent folgt im Januar, der Rest wächst bis zum Frühjahr nach.

---

## 1. Ausgangslage

### Was heute läuft

```text
helferliste.online ──CSV──▶ Abruf/Import ──▶ Helferbereich ──▶ Dashboard, Monitor,
 (Anmeldung)                (stündlich)     (PostgreSQL)        Material, Unterschriften
```

Der Helferbereich kann schon viel: Schichten mit Bedarf und Lücken, Einteilen
von Hand, Programm-Band, Monitor, T-Shirt-, Funk- und Schlüsselausgabe,
Unterschriften am Tablet. **Was fehlt, ist nur die Anmeldung selbst** – und
genau die ist die Quelle der meisten Probleme.

### Was die Daten von 2026 zeigen

Aus [plan-helfer-dashboard.md](plan-helfer-dashboard.md), Abschnitt 5, und
dem Schichtbestand in der Datenbank:

| | |
| --- | --- |
| Schichten | 51, in 8 Bereichen, 25.08.–01.09. |
| Plätze | 413, davon 237 besetzt, 176 offen |
| Freitag bis Sonntag | 42 Schichten, 319 Plätze (77 %) |
| Schichtdauer | meist 5–8 h (41 von 51), 6 kurze (1–4 h), 4 lange (10–12 h) |
| Anfangszeiten | gehäuft 6–8 Uhr, 12–13 Uhr, 20 Uhr; drei Nachtschichten |
| Zeitlich überlappende Schichtpaare | **160** |
| Namen / Mailadressen | 104 / 90 – eine Adresse trägt acht Namen |
| T-Shirt-Größen | Freitext: `Damen L`, `Shirt Gr.M`, `Straßensperrung Aufbau Größe M` |
| Leere Felder | Telefon und Aufgabe in allen Einträgen; Größe bei 19, Verpflegung bei 39 Personen |

### Was helferliste.online kann – und was nicht

Zur Fairness: laut eigener Seite ist das Werkzeug für Vereine kostenlos;
betrieben wird es von einer Einzelperson (Quellen in Anhang B).

| kann | kann nicht |
| --- | --- |
| Vorlage aus dem Vorjahr kopieren | Pflichtfelder nachträglich verschärfen – nur solange sich niemand eingetragen hat |
| andere Personen miteintragen | Mindestangaben erzwingen – „die Eingabe eines Namens genügt" |
| CSV, PDF, Kalenderdatei, Kioskmodus, JSON-API | Erinnerungen vor dem Einsatz, Warteliste, Überschneidungsprüfung, Check-in |
| Austragen per Link | Helferkonten, Helferstamm über die Jahre |

Die eigentlichen Probleme liegen in der rechten Spalte.

### Schmerzpunkte und wohin sie führen

| Schmerzpunkt | Anforderungen |
| --- | --- |
| Externes Werkzeug | Ziel 2, N-06 |
| Export unsauber | I-01 bis I-06 – die Daten entstehen gleich richtig |
| PDF-Listen müssen erzeugt werden, unübersichtliche Vielfalt | L-01 bis L-04 |
| Keine Prüfung der Personen, Dubletten, nur Vornamen | I-01 bis I-07 |
| Kaputte Stammdaten stören während der Veranstaltung | I-*, T-* |
| Unübersichtlich, große grafische Banner | A-*, N-01 bis N-04 |
| Parallele Schichten aus Versehen | K-01 bis K-04 |
| Helfer mit Einschränkungen sollen teilhaben, aber nicht überall eingesetzt werden | K-05 bis K-09 |
| Viele Helfer sind nicht IT-affin | A-05 bis A-10, N-01 bis N-04 |
| Mehr Schichten pro Helfer erwünscht | G-01 bis G-08 |
| WhatsApp-Gruppen, Helferstamm über Jahre | C-*, D-03 bis D-05 |
| Reserveplätze, die nicht als Lücke gelten | R-01 bis R-03 |
| Springer („Samstag nachmittag, mache alles") | R-05 bis R-08 |
| Mehr als eine Veranstaltung | V-01 bis V-05 |
| Echte Datenbank, echte Backend-Benutzer | Abschnitt 7, B-* |

---

## 2. Ziele und Nicht-Ziele

### Ziele

1. Helfer melden sich in wenigen Minuten auf dem Handy an, auch ohne
   IT-Erfahrung, und tragen sich dabei für mehr als eine Schicht ein.
2. Die Daten gehören dem Verein, liegen auf eigenem Server und sind von der
   ersten Eingabe an sauber genug, um damit am Veranstaltungstag zu arbeiten.
3. Die Orga sieht jederzeit, wo es brennt, und kann gezielt um Hilfe bitten.
4. Wer einmal geholfen hat, kommt leicht wieder – der Helferstamm wächst.
5. Das Werkzeug trägt jede Veranstaltung des Vereins, nicht nur eine.

### Nicht-Ziele

- Keine App zum Installieren. Eine Webseite, die auf jedem Handy geht.
- Keine automatische Einteilung durch einen Algorithmus. Vorschläge ja,
  entscheiden tut der Helfer oder die Orga.
- Keine Mitgliederverwaltung, keine Buchhaltung, keine Bezahlung.
- Kein Ersatz für die WhatsApp-Gruppen. Die Anmeldung arbeitet ihnen zu.

---

## 3. Beteiligte und Rollen

| Rolle | wer | was sie braucht |
| --- | --- | --- |
| **Interessent** | hat von der Veranstaltung gehört, noch nichts eingetragen | Ankündigung, „Bescheid geben, wenn's losgeht" |
| **Helfer** | hat mindestens eine Schicht oder Springer-Zeit | Anmeldung, Mein Helferplatz, Erinnerung, Ansprechpartner |
| **Anmeldende Person** | meldet Familie, Freunde oder Vereinskollegen mit an | mehrere Personen unter einer Adresse, aber jede mit Namen und Größe |
| **Bereichsleitung** | verantwortet z. B. Streckenposten | ihre Schichten, ihre Leute, Liste zum Ausdrucken, Hilferuf |
| **Orga** | betreut alle Bereiche | alles im Helferbereich, Veranstaltungen anlegen |
| **Admin** | ein, zwei Personen | Benutzer und Rechte, Einstellungen, Löschen |

Die Rolle *Anmeldende Person* ist eine bewusste Antwort auf die Daten: die
acht Namen unter einer Adresse waren keine Dubletten, sondern ein Mensch, der
seine Leute angemeldet hat. Statt das zu bekämpfen, wird es ein eigener,
sauberer Weg (A-08).

---

## 4. Leitideen

1. **Verfügbarkeit zuerst, Schichtliste als Abkürzung.** Die Frage „Wann hast
   du Zeit?" versteht jeder. Die Frage „Welche von 51 Schichten in 8 Bereichen
   willst du?" überfordert viele.
2. **Kein Passwort, aber eine eindeutige Person.** Die Mailadresse wird
   bestätigt, danach führt ein persönlicher Link zurück. Wer sich nichts merken
   muss, legt sich kein zweites Konto an.
3. **Das Handy ist das Gerät.** Große Knöpfe, eine Frage pro Bildschirm,
   einfache Sprache, kein Kleingedrucktes vor dem Ziel.
4. **Sauber an der Quelle.** Was eine Auswahl sein kann, ist eine Auswahl.
   Was Pflicht ist, wird geprüft, bevor es gespeichert wird.
5. **Papier bleibt erlaubt.** Jede Liste lässt sich jederzeit aktuell
   ausdrucken – am Veranstaltungstag ist Papier die Rückfallebene.
6. **Motivieren ohne Druck.** Persönlicher Fortschritt und gemeinsames Ziel
   ja, öffentliche Bestenlisten nein.
7. **Unsere Daten, unser Server.** Keine Werbung, keine Tracker, keine
   eingebundenen fremden Dienste.
8. **Inklusion ohne Etikett.** Grenzen für einzelne Helfer wirken still –
   niemand sieht, dass ihm etwas nicht angeboten wird.

---

## 5. Anforderungen

Priorität: **M** = Muss, **S** = Soll, **K** = Kann. Die Phase verweist auf
den Umsetzungsplan in Abschnitt 9.

### 5.1 Veranstaltungen und Schichten (V)

| Nr. | Anforderung | Prio | Phase |
| --- | --- | --- | --- |
| V-01 | Im Backoffice lassen sich beliebig viele Veranstaltungen anlegen: Name, Zeitraum, Ort, Beschreibung, Anmeldezeitraum. | M | 1 |
| V-02 | Eine Veranstaltung hat einen Status: *in Planung* (unsichtbar), *angekündigt* (sichtbar, Interesse vormerkbar), *Anmeldung offen*, *geschlossen*, *archiviert*. | M | 1 |
| V-03 | Bereiche (heute „Liste": Streckenposten, Straßensperre …) mit Beschreibung in einfacher Sprache, Treffpunkt, Bereichsleitung, Mindestalter und Voraussetzungen (Führerschein …); eine Schicht kann vom Mindestalter ihres Bereichs abweichen – meist strenger, niedriger nur bewusst (D-07). | M | 2 |
| V-04 | Eine Veranstaltung lässt sich aus einer früheren **als Vorlage** anlegen: Bereiche und Schichten werden übernommen und auf die neuen Tage verschoben. | S | 2 |
| V-05 | Schichten haben Beginn, Ende, Ort, Hinweis und drei Zahlen: **Minimum**, **Soll** und **Reserve** (siehe R-01). | M | 2 |
| V-06 | Schichten lassen sich als *intern* markieren – sie erscheinen nicht in der öffentlichen Anmeldung (z. B. Orgabüro). | S | 2 |
| V-07 | **Je Veranstaltung einstellbar, ob und welche Goodies es gibt**: das Helfershirt und frei benannte kleine Goodies – etwa ein Bier am Bierwagen, eine Eistüte, ein Getränkegutschein für die After-Hour. Nicht jede Veranstaltung bietet Goodies an – ein Schalter sagt „keine Goodies“. Beim Shirt außerdem, ob es einen Schnitt für alle gibt oder Damen- und Herrenschnitt. Verpflegung gibt es in der Regel ohnehin und ist kein Goodie; ob sie gestellt wird, ist ebenfalls einstellbar. Danach richtet sich, was bei der Anmeldung gefragt wird – ohne Shirt keine Größe, ohne Verpflegung keine Verpflegungsfrage (I-02) – und was Stempelkarte und Belohnungsstufen zeigen (G-01, G-02). | M | 2 |
| V-08 | **Je Veranstaltung einstellbar, welche Bereiche sie nutzt**: Kennzeichen, Presse, Helfer, Materialausgabe. Die Veranstaltung wählt man im Kopf des Backoffice, sie gilt für alles, und es zeigt nur die Bereiche, die sie nutzt. Was man für sie einrichtet – Goodies, Verpflegung, Import, Zeitplan-Abruf, Material, Tablet –, steht bei ihr. | M | 2 |
| V-09 | **Materialausgabe als eigener Bereich**: je Veranstaltung, ob es sie gibt und was ausgegeben wird – je Material mit oder ohne Rückgabe, Unterschrift am Tablet und erfasster Nummer oder Kennzeichen. Funkgeräte und Schlüssel sind dann zwei Materialien unter vielen; ausgegeben wird an Helfer und an jeden anderen. | S | 3 |

**Stand 09.10.2026:** V-01 und V-02 sind umgesetzt (Schritt 1.2).
Veranstaltungen stehen im Schema `kern`; Schichten, Programm, Aufgaben und
Ausgaben des Helferbereichs gehören zu einer. Mit welcher das Backoffice
arbeitet, wählt jeder im Browser; ohne Wahl gilt die nächste, die noch nicht
vorbei ist. Kennzeichen und Presse hängen noch an keiner.

V-03 bis V-07 sind im Backoffice umgesetzt (Schritt 2.1): Bereiche mit
Beschreibung, Treffpunkt, Bereichsleitung samt Nummer, Mindestalter,
Voraussetzungen (eine je Zeile) und *intern*; Schichten mit Minimum, Soll,
Reserve, eigenem Mindestalter und *intern*; je Veranstaltung Shirt,
Verpflegung, Helferparty und Goodies mit Schwelle und Altersgrenze; die
Vorlage aus einer früheren Veranstaltung. Die Bereichsleitung sind Konten
(B-02, Schritt 2.1a).

V-08 ist umgesetzt (Schritt 2.1b): Jede Veranstaltung legt fest, was sie
nutzt; gewählt wird sie im Kopf, für alle Bereiche, und das Backoffice zeigt
nur die Reiter dessen, was sie nutzt. Der Helferbereich gliedert sich in
Übersicht, Planen, Leute und Vor Ort; Goodies und Verpflegung, Import,
Zeitplan-Abruf, Material und Tablet stehen unter Verwaltung bei der
Veranstaltung; Funk und Schlüssel unter dem eigenen Reiter Ausgabe. Goodies
haben einen Schalter, das Shirt einen Schnitt (V-07). Die Daten von
Kennzeichen und Presse hängen weiter an keiner Veranstaltung. Der Import aus helferliste.online
macht aus jeder Liste einen Bereich und aus ihrem Bedarf Soll und Minimum.

### 5.2 Anmeldung (A)

| Nr. | Anforderung | Prio | Phase |
| --- | --- | --- | --- |
| A-01 | Öffentliche Startseite je Veranstaltung mit zwei Wegen: **„Ich sage, wann ich Zeit habe"** (Assistent) und **„Ich suche mir Schichten aus"** (Liste). Bis der Assistent steht, nur die Liste. | M | 2 |
| A-02 | **Assistent**, Schritt 1: Verfügbarkeit als Raster *Tag × Früh / Mittag / Abend* (aus den Anfangszeiten 2026 abgeleitet), Auf- und Abbautage getrennt. | M | 3 |
| A-03 | Assistent, Schritt 2: Was liegt dir? – *draußen an der Strecke*, *mit Menschen*, *anpacken*, *fahren*, *egal, setzt mich ein, wo es brennt*. Mehrfachauswahl. | S | 3 |
| A-04 | Assistent, Schritt 3: Vorschläge – nur Schichten, die in die Verfügbarkeit passen, keine überlappenden, **die dringendsten zuerst** (unter Minimum vor unter Soll). Antippen genügt zum Eintragen. | M | 3 |
| A-05 | Wer „egal" gewählt hat oder nichts Passendes findet, kann sich als **Springer** für seine Zeitfenster eintragen (R-05). | M | 3 |
| A-06 | **Schichtliste**: nach Tag gegliedert, je Schicht Bereich, Uhrzeit, Ort und freie Plätze als Klartext („noch 3 frei"), filterbar nach Tag und Bereich. | M | 2 |
| A-07 | Persönliche Angaben erst, **nachdem** Schichten gewählt sind – so ist der Einstieg niedrig. Pflicht: Vorname, Nachname, E-Mail; Handy dringend empfohlen. | M | 2 |
| A-08 | **Weitere Person mitanmelden**: Vorname, Nachname, T-Shirt-Größe, Verpflegung je Person; die anmeldende Person bleibt Ansprechpartner. Jede Person wird eigens gezählt und bekommt ihr eigenes Shirt. | M | 2 |
| A-09 | **Mein Helferplatz**: persönliche Seite mit allen Schichten, Treffpunkt, Ansprechpartner; **weitere Schichten dazunehmen**. Alles Weitere, was der Helfer selbst erledigt, steht in 5.3. | M | 2 |
| A-10 | Bestätigung als Seite **und** Mail, mit dem persönlichen Link und einem **Kalender-Abo**, das sich bei Änderungen selbst aktualisiert – nicht nur einer einmaligen Kalenderdatei. | M | 2 |
| A-11 | Wer schon angemeldet ist – in diesem Jahr oder früher –, wird beim Eintragen der Adresse erkannt und bekommt seinen Link zu Mein Helferplatz, statt ein zweites Mal angelegt zu werden. | M | 2 |
| A-12 | Ein **Link auf eine einzelne Schicht** (kurz, z. B. `…/s/k7`) führt direkt dorthin – für Hilferufe in WhatsApp. | S | 3 |

**Stand 09.10.2026:** Die Liste steht (Schritt 2.2): A-01 vorerst nur mit
der Liste, A-06 mit Filtern nach Tag und Bereich, A-07 und A-08 mit Mitanmeldung,
I-01, I-02 und I-04, K-01 und K-04, R-03 und R-05, dazu das Vormerken von
Interesse (V-02). Jede Veranstaltung hat ihren Kurzlink, etwa
`helfer.example.de/aa-2027`. Die Bestätigung per Mail, das Wiedererkennen und
Mein Helferplatz (A-09 bis A-11, I-03, I-05) kommen mit 2.4; bis dahin sagt
die Dankeseite nur, dass sich die Orga meldet.

**Stand 09.10.2026, Schritt 2.4:** A-09 (ansehen und dazunehmen, auch für
Mitangemeldete und neue, die mitkommen), A-10 mit Kalender-Abo, A-11, I-03
und I-05 sind umgesetzt, nach 7.4: Link mit Knopf und sechsstelliger Code,
kein Passwort. Die persönlichen Links sind signiert statt gespeichert (eine
Tabelle `zugangslink` gibt es deshalb nicht). Wer wiederkommt, bekommt seinen
Link mit der eben getroffenen Auswahl; die Seite verrät dabei nichts über
die Person. Unbestätigt halten die Plätze 72 Stunden, nach 24 kommt eine
Erinnerung. Mögliche Dubletten zeigt die Übersicht; zusammenführen kommt mit
I-06.

**Stand 09.10.2026, Schritt 3.1:** Der Assistent steht – A-01 mit beiden
Wegen, der Assistent zuerst, und A-02 bis A-05. Die Tageszeiten sind die
der Springer (Vormittag bis 13, Nachmittag 12 bis 18, Abend ab 17 Uhr); für
die Vorschläge reicht der Abend bis 3 Uhr, damit eine Nachtschicht zum
Abend ihres ersten Tages zählt. Eine Schicht passt, wenn drei Viertel davon
in den angetippten Zeiten liegen. Wozu ein Bereich passt, hakt die Orga im
Bereich an; ohne Haken passt er zu allem, damit nichts verschwindet, nur
weil die Haken fehlen. Die Vorlieben stehen an der Teilnahme und bei der
Person im Backoffice. Auf- und Abbautage ergeben sich aus den Schichten vor
und nach der Veranstaltung; als Springer kann man sich dort jetzt auch aus
der Liste eintragen.

### 5.3 Selbstbedienung (S)

Entschieden: Helfer erledigen selbst, wofür sie heute die Orga anschreiben
müssten – **abmelden, Daten löschen, Schichten stornieren, umbuchen**. Alles
in Mein Helferplatz, ohne Konto und ohne Passwort, und **ohne Frist**: es
sind Ehrenamtliche. Wer aus persönlichen Gründen absagt, auch spät, tut das
Richtige – das Werkzeug macht es ihm leicht und sorgt dafür, dass die Absage
sofort bei der richtigen Person ankommt.

| Nr. | Anforderung | Prio | Phase |
| --- | --- | --- | --- |
| S-01 | **Schicht stornieren – jederzeit**, auch kurz vorher und während der Veranstaltung: ein Klick und eine Rückfrage. Die Seite bedankt sich für die Absage, statt sie zu bemängeln – wer absagt, statt einfach nicht zu kommen, hilft der Orga. | M | 2 |
| S-02 | **Umbuchen**, ebenfalls jederzeit: eine Schicht gegen eine andere tauschen, in **einem** Schritt. Die neue wird zuerst gebucht, erst dann die alte freigegeben – ist die neue inzwischen voll oder überschneidet sich, bleibt die alte bestehen. Die Konfliktprüfung lässt die abzugebende Schicht dabei außen vor. Zuerst angeboten: Schichten am selben Tag und im selben Bereich. | M | 2 |
| S-03 | **Ganz abmelden** von einer Veranstaltung: alle Schichten auf einmal, mit Rückfrage. Ein Grund ist freiwillig und hilft der Orga beim Planen. | M | 2 |
| S-04 | **Angaben ändern**: Telefon, T-Shirt-Größe, Verpflegung, Bemerkung. Eine neue Mailadresse gilt erst, wenn sie bestätigt ist. | M | 2 |
| S-05 | **Daten löschen**: alles auf einmal, künftige Schichten werden dabei storniert. Ausnahme, solange noch etwas ausgeliehen ist (Funkgerät, Schlüssel): dann wird nach der Rückgabe gelöscht, samt der Unterschrift als Beleg der Übergabe – und die Seite sagt, warum. | M | 2 |
| S-06 | Mitangemeldete Personen (A-08) verwaltet die anmeldende Person mit: stornieren, umbuchen, löschen. Wer eine eigene Adresse hinterlegt, kann sich selbständig machen. | S | 2 |
| S-07 | Fällt eine Schicht durch Storno oder Umbuchen unter ihr Minimum, bekommt die Bereichsleitung sofort Bescheid. **Kurzfristige Absagen** – weniger als 24 Stunden vorher oder während der Veranstaltung – erscheinen zusätzlich oben im Dashboard und auf dem Monitor, zusammen mit den Springern, die jetzt einspringen könnten (R-06): am Veranstaltungstag liest niemand Mails. Ein frei gewordener Platz geht an die Warteliste (R-04). | M | 2 |
| S-08 | Jede Selbstbedienung steht im Protokoll (B-05) und in einer Übersicht „Änderungen seit gestern" für Orga und Bereichsleitung. | S | 2 |

**Stand 09.10.2026, Schritt 2.5:** S-01 bis S-08 sind umgesetzt, dazu die
Warteliste (R-04): wer eine volle Schicht ankreuzt, steht darauf; wird ein
Platz frei, rückt erst die Reserve auf, dann bekommt die Erste der
Warteliste ihn angeboten und hält ihn 24 Stunden. Beim Tauschen wird bestätigt,
was die neue Schicht verlangt (Führerschein). Kurzfristige Absagen stehen
oben in der Übersicht und gehen per Mail an die Bereichsleitung; seit 2.7
stehen sie auch auf dem Monitor, ohne Namen. Bei S-05 zählt nur, was an der Person hängt
(Funkgeräte); Schlüssel sind nur über den Namen vermerkt.

### 5.4 Identität und Datenqualität (I)

| Nr. | Anforderung | Prio | Phase |
| --- | --- | --- | --- |
| I-01 | Vor- und Nachname in **getrennten Feldern**, beide Pflicht; ein Wort allein wird mit freundlichem Hinweis abgewiesen. | M | 2 |
| I-02 | T-Shirt-Größe als **Auswahl** (XS bis 5XL, „kein Shirt"; Damen-/Herrenschnitt nur, wenn die Veranstaltung beide anbietet), Verpflegung als Auswahl – beides nur, wenn die Veranstaltung es anbietet (V-07). Freitext nur unter *Bemerkung*. | M | 2 |
| I-03 | Die Mailadresse wird per Link **bestätigt**. Unbestätigte Anmeldungen halten ihren Platz eine begrenzte Zeit und verfallen dann, mit Erinnerung. | M | 2 |
| I-04 | Handynummer wird beim Speichern in eine einheitliche Form gebracht (+49 …). | S | 2 |
| I-05 | **Dublettenprüfung beim Anmelden**: gleiche Adresse oder gleiche Nummer mit gleichem Namen (Umlaute in beiden Schreibweisen, `kern/suchen.py`) → „Bist du das?" statt einer zweiten Person. Mitangemeldete Personen derselben anmeldenden Person sind ausgenommen – das sind Familien und Vereinskollegen, keine Dubletten. | M | 2 |
| I-06 | **Zusammenführen im Backoffice**: zwei Personen zu einer machen, Schichten und Ausgaben wandern mit. | S | 3 |
| I-07 | Social Login (Google, Apple …) – geprüft und **nicht empfohlen**, siehe Abschnitt 7.4. | – | – |

**Stand 09.10.2026, Schritt 3.2:** I-06 ist umgesetzt. Die Orga vergleicht
zwei Einträge nebeneinander – aus der Übersicht oder über die Nummer – und
wählt, wer bleibt. Mit dem anderen wandern Schichten, Warteliste,
Springer-Zeiten, Teilnahmen, Einsatzgrenzen, Ausleihen, die Shirt-Ausgabe
samt Unterschrift, Absagen, Mails, Verlauf und wen er mitangemeldet hat;
Doppeltes bleibt einmal, ein so frei gewordener Platz geht an Reserve und
Warteliste. Fehlende Angaben kommen vom anderen. Paare, die zwei Menschen
sind, lassen sich als solche vermerken und verschwinden aus der Liste.

### 5.5 Konflikte, Belastung und Einsatzgrenzen (K)

| Nr. | Anforderung | Prio | Phase |
| --- | --- | --- | --- |
| K-01 | Zeitlich überlappende Schichten derselben Person sind **gesperrt** – in der Liste ausgegraut mit Grund („überschneidet sich mit Streckenposten Sa 8–14"), im Assistenten gar nicht erst angeboten. | M | 2 |
| K-02 | Die Orga darf im Backoffice bewusst überschreiben (z. B. zwei Kurzschichten am selben Ort), mit Vermerk. | S | 2 |
| K-03 | **Warnung** (nicht Sperre) bei knappen Übergängen zwischen verschiedenen Orten (unter 30 min) und bei mehr als 10 Stunden am Tag. | S | 2 |
| K-04 | Die Prüfung gilt auch für mitangemeldete Personen und für Springer-Zeiten. | M | 2 |

**Einsatzgrenzen** – im Brainstorming „Blacklist". Es gibt ehrenamtliche
Helfer mit Einschränkungen, die aus dem Gedanken der Inklusion dabei sein
sollen, aber etwa nicht Shuttle fahren oder nicht allein eine Straßensperre
begleiten können. Der Name ist bewusst ein anderer: das Wort steht im
Backoffice vor vielen Augen, und gemeint ist Teilhabe, nicht Ausschluss.
**Die Grenzen wirken still** – niemand soll sich ausgeschlossen fühlen.

| Nr. | Anforderung | Prio | Phase |
| --- | --- | --- | --- |
| K-05 | Die Orga pflegt je Person Einsatzgrenzen, nur im Backoffice: einen Bereich oder eine Schicht **nicht anbieten** (z. B. Shuttle), oder einen Bereich **nur zu zweit** (z. B. Straßensperre). | M | 2 |
| K-06 | **Still**: Schichten außerhalb der Grenzen erscheinen für diese Person weder in der Liste noch im Assistenten, noch in Vorschlägen und Hilferufen. Über einen Direktlink kommt dieselbe neutrale Antwort wie bei jeder anderen nicht buchbaren Schicht („Diese Schicht ist gerade nicht frei – hier sind andere, die Hilfe brauchen"). Kein Hinweis in Mein Helferplatz, in Mails, am Tablet. | M | 2 |
| K-07 | **Nur zu zweit**: die Anmeldung geht ganz normal durch. Steht die Person in einer Schicht allein, sieht die Bereichsleitung im Dashboard einen Hinweis – ohne Begründung – und plant eine zweite Person dazu. Auf dem Monitor und auf Ausdrucken, die am Treffpunkt herumliegen, steht nichts davon. | M | 2 |
| K-08 | Gespeichert wird **nur die Grenze, nie der Grund** – keine Diagnose, keine Beschreibung der Einschränkung; das wären Gesundheitsdaten nach Art. 9 DSGVO. Sichtbar nur für Orga und die Leitung des betroffenen Bereichs, nicht in der CSV-Ausfuhr; Änderungen stehen im Protokoll. Formuliert so, dass die Person es lesen könnte: bei einer Auskunft nach Art. 15 DSGVO gehört der Eintrag dazu. | M | 2 |
| K-09 | Die Orga kann trotzdem von Hand einteilen (wie K-02), mit Vermerk. | S | 2 |

**Stand 09.10.2026:** K-05 bis K-09 sind umgesetzt (Schritt 2.3). Eine Schicht
hinter einer Grenze bekommt in der Anmeldung dieselben Worte wie eine volle
(„… ist gerade nicht frei – in der Liste findest du andere, die Hilfe
brauchen“). Erkannt wird die Person bis 2.4 an Name und Adresse wie beim
Import; in Mein Helferplatz, im Assistenten und in Hilferufen greift dieselbe
Sperre, sobald es sie gibt. Grenzen auf ganze Bereiche wandern mit der Vorlage
ins nächste Jahr.

### 5.6 Reserve, Warteliste, Springer (R)

| Nr. | Anforderung | Prio | Phase |
| --- | --- | --- | --- |
| R-01 | Je Schicht **Minimum** (darunter geht es nicht), **Soll** (so ist es geplant) und **Reserve** (zusätzlich willkommen). | M | 2 |
| R-02 | Das Dashboard färbt nach diesen Stufen: rot unter Minimum, gelb unter Soll, grün ab Soll. **Reserveplätze zählen nie als fehlend.** | M | 2 |
| R-03 | Ist das Soll erreicht, wird eine Anmeldung als Reserve angenommen und so angezeigt („Du bist Reserve – danke, das hilft uns sehr"). | M | 2 |
| R-04 | Ist auch die Reserve voll: Warteliste. Wird ein Platz frei, bekommt die erste Person der Warteliste eine Mail mit Link zum Bestätigen. | K | 2 |
| R-05 | **Springer**: Person mit Zeitfenstern statt Schicht („Sa 12–18, mache alles"), optional mit Vorlieben. | M | 2 |
| R-06 | Dashboard und Monitor zeigen die Springer, die **jetzt** verfügbar sind, und wie viele es in den nächsten Stunden werden. | M | 2 |
| R-07 | Die Orga setzt einen Springer mit zwei Tipps in eine Schicht; er bekommt die Zuweisung als Mail bzw. per Anruf. Auch vorab möglich: wer bis zu einer Frist nur Zeiten angegeben hat, wird von der Orga eingeteilt und bekommt Bescheid. | S | 4 |
| R-08 | Springer-Zeit zählt für die Anerkennung wie eine Schicht. | M | 4 |

**Stand 09.10.2026, Schritt 2.7:** R-02 und R-06 sind umgesetzt, dazu T-04.
Übersicht, Schichtliste, Bereich und Monitor färben rot unter Minimum, gelb
unter Soll, grün ab Soll; die Reserve steht als „+1“ dabei und fehlt nie. Die
Springer, die jetzt können, stehen in der Übersicht mit Nummer, auf dem
Monitor mit Namen, jeweils mit der Zahl derer, die in den nächsten drei
Stunden kommen. Die Übersicht hat eine Kachel „Unter Minimum“.

### 5.7 Anerkennung und Gamification (G)

Ausgangspunkt: das Helfershirt gibt es schon ab einer kurzen Schicht. Die
Frage ist also nicht, wie man die erste Schicht bekommt, sondern **die zweite
und dritte**.

| Nr. | Anforderung | Prio | Phase |
| --- | --- | --- | --- |
| G-01 | **Stempelkarte** statt Punktestand: jede Schicht ein Stempel, sichtbar in Mein Helferplatz und in der Bestätigung. Ein Bild, das jeder kennt, auch ohne IT-Erfahrung. Gibt eine Veranstaltung keine Goodies aus (V-07), zeigt die Karte den Dank, aber keine Belohnungen. | S | 4 |
| G-02 | **Belohnungsstufen je Veranstaltung** frei pflegbar, nach Schichten *oder* Stunden, z. B. 1 Schicht → Helfershirt, 2 Schichten → ein Bier am Bierwagen oder eine Eistüte. Die zweite Stufe zielt genau auf die zweite Schicht. **Ein Goodie kann eine Altersgrenze tragen** (Bier ab 16); wer jünger ist, bekommt die Alternative – bei Helfern ab 12 keine Nebensache. Wahlweise zählen Nacht- und Frühschichten doppelt – das sind die, die sonst liegen bleiben. | S | 4 |
| G-03 | Direkt nach dem Eintragen: **„Noch eine Schicht bis …"** mit 2–3 passenden Vorschlägen – am liebsten am selben Tag und Ort, direkt davor oder danach. | M | 2 |
| G-04 | **Gemeinsames Ziel** auf der Startseite: „Samstag: 98 von 122 Plätzen besetzt", als Balken je Tag. Das Wir zählt, nicht die Rangliste. | S | 2 |
| G-05 | **Abzeichen**, die etwas Echtes würdigen: *Schicht-Retter* (in eine Schicht unter Minimum eingetragen), *Frühaufsteher* (vor 7 Uhr), *Nachtwache*, *Stammhelfer* (drittes Jahr in Folge). | K | 4 |
| G-06 | **Mit Freunden helfen**: nach dem Eintragen ein Knopf „Freunde mitbringen" – erzeugt einen WhatsApp-Text mit Link auf genau diese Schicht. Wer darüber kommt, zählt beim Einladenden mit. | S | 4 |
| G-07 | **Rückblick nach der Veranstaltung**: Danke-Mail mit „Du hast 11 Stunden geholfen", Fotos, Ankündigung der nächsten Veranstaltung. | S | 3 |
| G-08 | **Keine** öffentlichen Bestenlisten mit Namen. Studien aus Ehrenamtsprojekten zeigen: Ranglisten spornen wenige an und vergraulen andere (Anhang B). | M | – |
| G-09 | **Helferparty**: nach den Veranstaltungen gibt es in der Regel eine – Grillen und Beisammensein. Einladung an **alle** Helfer der Veranstaltung, mit Zu- oder Absage und der Zahl der Begleitpersonen, damit die Orga Grillgut und Getränke planen kann; Erinnerung am Tag. Keine Belohnungsstufe – eingeladen ist jeder, der geholfen hat. | S | 4 |

**Stand 09.10.2026, Schritt 2.6:** G-03 und G-04 sind umgesetzt. Die
Vorschläge kommen auf der Dankeseite – dort mit einem Klick eingetragen, für
alle, die zusammen angemeldet sind – und in Mein Helferplatz gleich nach dem
Dazunehmen. „Noch eine Schicht bis …“ nennt das Goodie, für das genau eine
Schicht fehlt. Vorgeschlagen wird nur, was passt: frei für alle, ohne
Überschneidung, im Alter, und keine Voraussetzung, die noch niemand bestätigt
hat.

### 5.8 Kommunikation und WhatsApp (C)

Die Recherche (Stand Oktober 2026, Quellen in Anhang A) ergibt ein klares
Bild: **WhatsApp lässt sich für diesen Zweck nicht sinnvoll automatisieren.**

- Die offizielle Gruppen-API erlaubt höchstens **8 Teilnehmer** je Gruppe und
  setzt einen „Official Business Account" voraus – für eine Community mit 200
  Leuten unbrauchbar.
- Für **Communities und Kanäle** gibt es keine offizielle API; Beiträge
  entstehen nur in der App.
- Inoffizielle Bibliotheken (Baileys, whatsapp-web.js) verstoßen gegen die
  Nutzungsbedingungen. Wird die Nummer gesperrt, verliert die Community
  womöglich ihren Admin.
- Einzelnachrichten über die Cloud API gingen, kosten aber je Nachricht
  (Erinnerung als „Utility" rund 5 Cent, ein Hilferuf zählt als „Marketing",
  rund 11 Cent) und brauchen ein eigenes Opt-in.
- Die bayerische Datenschutzaufsicht hält WhatsApp auch für Vereine nicht für
  ein geeignetes Mittel rechtssicherer Kommunikation.

Daraus folgt die Aufteilung: **E-Mail ist der verlässliche Pflichtkanal,
WhatsApp die freiwillige Gemeinschaft.** Die Anwendung arbeitet der Community
zu – mit fertigen Texten und Links –, gepostet wird von Hand. Das kostet die
Orga pro Hilferuf zehn Sekunden und erspart jede Abhängigkeit.

| Nr. | Anforderung | Prio | Phase |
| --- | --- | --- | --- |
| C-01 | **E-Mail ist der Pflichtkanal**: Bestätigung, Änderungen, Erinnerung, Hilferuf, Dank. Alles Wichtige kommt per Mail, auch wenn es zusätzlich in WhatsApp steht. | M | 2 |
| C-02 | Erinnerung zwei Tage vor der ersten Schicht: Treffpunkt, Ansprechpartner mit Nummer, was mitzubringen ist, Link auf Mein Helferplatz – und die Bitte, **15 Minuten vor Beginn** am Treffpunkt zu sein und sich bei der Bereichsleitung einzuchecken; den QR-Code dafür enthält die Mail (T-01). | S | 3 |
| C-03 | **Hilferuf**: das Backoffice zeigt Schichten unter Minimum bzw. Soll. Ein Klick erzeugt (a) eine Mail an Stamm-Helfer, deren Verfügbarkeit und Vorlieben passen und die zu der Zeit noch frei sind – mehrere knappe Schichten in einer Mail, **Zusagen direkt per Link aus der Mail** –, und (b) einen fertigen Text mit Direktlink (A-12) für die Ankündigungsgruppe der Community, zum Kopieren oder als `wa.me`-Link, der WhatsApp mit dem Text öffnet. | S | 3 |
| C-04 | Je Schicht höchstens ein Hilferuf in 24 Stunden; wer Hilferufe abbestellt hat, bekommt keine. | M | 3 |
| C-05 | Nach der Anmeldung – **nicht** auf öffentlichen Seiten – erscheint der Einladungslink zur Community und ggf. zur Gruppe des Bereichs. WhatsApp rät ausdrücklich davon ab, Einladungslinks öffentlich zu posten; Beitrittsanfragen bestätigt ein Admin. | S | 3 |
| C-06 | Teilen-Knöpfe sind gewöhnliche Links (`wa.me/?text=…`). Es wird **kein Skript** von WhatsApp oder Meta eingebunden. | M | 2 |
| C-07 | **Keine** automatisierte Anbindung: keine inoffiziellen Bibliotheken, und Nummern aus der Datenbank werden nicht nach WhatsApp übertragen. | M | – |
| C-08 | Interessenten einer angekündigten Veranstaltung bekommen eine Mail, sobald die Anmeldung öffnet. **Stamm-Helfer werden mit einem Klick eingeladen**; wer kommt, muss nur noch Zeiten wählen – Name, Größe und Verpflegung sind vorbelegt. | S | 3 |
| C-09 | Hilferufe und Ankündigungen lassen sich mit einem Klick abbestellen, getrennt von den Mails zu eigenen Schichten. | M | 3 |

**Zur Community selbst** (Orga, nicht Software): die zwei bestehenden Gruppen
in eine Community überführen, mit einer Ankündigungsgruppe für alle und je
einer Gruppe für die großen Bereiche. Admin ist eine Vereinsnummer, nicht ein
privates Handy – sonst hängt der Helferstamm an einer Person. In der
Ankündigungsgruppe niemanden mit @ erwähnen: das zeigt dessen Nummer allen.

**Stand 09.10.2026, Schritt 3.3:** C-08 ist umgesetzt. Wer Interesse
vorgemerkt hat, bekommt eine Mail, sobald die Anmeldung offen ist – Status
*offen* und im Anmeldezeitraum –, und seine Adresse ist danach gelöscht. Den
Helferstamm lädt die Orga im Backoffice mit einem Klick ein (Leute →
Einladen): wer eingewilligt hat und noch nicht dabei ist, bekommt seinen
Link direkt zu den Schichten, Name, Größe und Verpflegung sind vorbelegt.
Niemand bekommt dieselbe Einladung zweimal. „Bleibst du dabei?“ (D-04) steht
noch aus; bis dahin sagt jede Einladung, wo man sie abstellt.

**Stand 09.10.2026, Schritt 3.4:** C-03, C-04, C-09 und A-12 sind umgesetzt.
Der Hilferuf zeigt die Schichten unter Soll mit der Zahl passender Leute aus
dem Helferstamm; ausgewählt, entsteht der Text für die Ankündigungsgruppe –
mit kurzem Link je Schicht (`…/s/k7`) und als `wa.me`-Link – und je passender
Person eine Mail mit allen Schichten, die zu ihr passen, und einem Link je
Schicht, der die Zusage vorbereitet. Passend: zu der Zeit frei, Zeiten und
Vorlieben (dieses Jahr, sonst zuletzt), Alter und Einsatzgrenzen. Je Schicht
geht höchstens eine Mail-Runde in 24 Stunden. Hilferufe und Einladungen
bestellt man mit einem Klick ab, aus der Mail oder in Mein Helferplatz.

### 5.9 Listen und Ausdrucke (L)

| Nr. | Anforderung | Prio | Phase |
| --- | --- | --- | --- |
| L-01 | Druckansichten **jederzeit aktuell**, ohne Erzeugen und Warten: je Schicht, je Bereich und Tag, je Tag gesamt. A4, mit Spalten zum Abhaken (*da*, *Shirt*, *Funk*). | M | 2 |
| L-02 | Kopf jeder Liste: Bereich, Zeit, Treffpunkt, Bereichsleitung mit Nummer; Fuß: Stand mit Uhrzeit. | M | 2 |
| L-03 | **Notfallmappe**: ein Druck mit allen Listen eines Tages, nach Bereichen getrennt, mit Telefonnummern – für den Fall, dass am Tag nichts geht. | S | 2 |
| L-04 | Eine Auswahl an Ansichten statt vieler Varianten: *Schicht*, *Bereich*, *Tag*, *Person*. Mehr nicht. | M | 2 |
| L-05 | CSV-Ausfuhr wie heute, eine Zeile je Person. | M | 2 |

**Stand 09.10.2026, Schritt 2.8:** L-01 bis L-04 sind umgesetzt, L-05 gab es
schon. Die Listen sind Seiten, die der Browser druckt (A4 hoch), mit zwei
leeren Zeilen je Schicht für Nachzügler und der Warteliste darunter. Die
Notfallmappe hat ein Deckblatt mit Orga, Bereichsleitungen und den Springern
des Tages, dann je Bereich eine Seite. Eine Bereichsleitung druckt nur ihre
Bereiche; Einsatzgrenzen stehen auf keinem Ausdruck (K-07).

### 5.10 Am Veranstaltungstag (T)

| Nr. | Anforderung | Prio | Phase |
| --- | --- | --- | --- |
| T-01 | **Check-in bei der Bereichsleitung**: sie hat auf ihrem Handy die Liste derer, die an ihrem Treffpunkt in Kürze beginnen, und hakt ab – per Scan des QR-Codes, den jeder Helfer in der Mail und in Mein Helferplatz hat, auf dem Handy oder ausgedruckt, oder per Tipp auf den Namen, wenn jemand nichts dabeihat. Bei schlechtem Netz merkt sich das Gerät die Häkchen und reicht sie nach. Wo niemand von der Orga steht, etwa an einer Straßensperre, erscheint in Mein Helferplatz ab 30 Minuten vor Beginn ein Knopf *Ich bin da*. **Kein QR-Aushang**: nicht jeder hat ein Handy mit Netz dabei, ein abfotografierter Aushang ginge herum, und vergessenes Scannen löste bei T-02 Fehlalarme aus. Zur Not die Papierliste. | M | 4 |
| T-02 | Wer **15 Minuten vor Schichtbeginn** noch nicht eingecheckt ist, erscheint im Dashboard als *noch nicht da* – früh genug, um anzurufen oder einen Springer zu schicken (R-06). Die Bereichsleitung sieht es zuerst. | M | 4 |
| T-03 | Check-in und Ausgabe hängen zusammen: wer seine erste Schicht angetreten hat, ist für Shirt und Goodies freigegeben – sofern die Veranstaltung sie ausgibt (V-07), und bei Goodies mit Altersgrenze mit der passenden Alternative. Ausgegeben und abgehakt wird wie heute beim Shirt. | S | 4 |
| T-04 | Monitor zeigt neben den Schichten die verfügbaren Springer (R-06). | M | 2 |

### 5.11 Backoffice-Benutzer und Rechte (B)

| Nr. | Anforderung | Prio | Phase |
| --- | --- | --- | --- |
| B-01 | **Persönliche Konten** statt eines gemeinsamen Passworts – für alle drei Bereiche, also in `kern`. | M | 3 |
| B-02 | Rollen: *Admin*, *Orga*, *Bereichsleitung* (nur ihre Bereiche), *Lesend*. | M | 2 |
| B-03 | Einladen per Mail; der Eingeladene setzt sein Passwort selbst. Optional Passkey. | M | 3 |
| B-04 | Das Kürzel ergibt sich aus dem Konto – die Abfrage bei der Anmeldung entfällt. | M | 3 |
| B-05 | **Protokoll**: wer hat wann wen eingeteilt, ausgetragen, zusammengeführt, gelöscht. | S | 2 |
| B-06 | Eine Bereichsleitung kann für ihren Bereich einen Hilferuf auslösen (C-*). | S | 3 |

**Stand 09.10.2026:** B-01, B-03 und B-04 sind umgesetzt, vorgezogen vor die
Öffnung. B-02 mit *Admin*, *Orga* und *Lesend*, jeweils für einzelne der drei
Backoffice-Bereiche. Dazu seit Schritt 2.1a die *Bereichsleitung*: ein
Konto, das am Bereich eingetragen ist und im Helferbereich nur diese Bereiche
sieht – mit ihren Schichten und den Leuten darauf. Die Nummer steht am Konto
und wird selbst gepflegt. Offen: Passkeys (B-03). Das Protokoll (B-05) steht
seit 2.3 und 2.5 an jeder Person: Einsatzgrenzen, Einteilen und Austragen von
Hand mit Kürzel, alles, was Helfer selbst tun, und was nachrückt.

### 5.12 Datenschutz und Recht (D)

Kein Rechtsrat – die Recherche zeigt, worauf es ankommt; die
Datenschutzerklärung prüft jemand Fachkundiges (D-09). Vorbild für die
Gliederung ist das Helfertool eines Landesturnverbands, das genau diese
Trennung macht (Anhang A).

| Nr. | Anforderung | Prio | Phase |
| --- | --- | --- | --- |
| D-01 | Datenschutzhinweis nach Art. 13 DSGVO **an der Stelle der Erhebung**: kurz im Formular, ausführlich verlinkt. | M | 2 |
| D-02 | Rechtsgrundlagen getrennt: der Einsatz selbst (Art. 6 Abs. 1 lit. b), Planung und Kommunikation rund um die Veranstaltung (lit. f). | M | 2 |
| D-03 | **Helferstamm nur mit eigener Einwilligung**: getrennte, nicht vorangekreuzte Checkbox „Ihr dürft mich für künftige Veranstaltungen ansprechen". Ohne sie werden die Daten nach der Veranstaltung gelöscht. | M | 2 |
| D-04 | Mit Einwilligung: Löschung spätestens **drei Jahre nach der letzten Teilnahme**, automatisch. Einmal im Jahr die Frage „Bleibst du dabei?" mit einem Klick zum Bestätigen oder Austreten. | S | 3 |
| D-05 | Widerruf der Stamm-Einwilligung und Löschen (S-05) selbst in Mein Helferplatz – so einfach wie die Einwilligung. | M | 2 |
| D-06 | **Minderjährige**: Geburtsdatum ist Pflicht. **Mindestalter 12**, gerechnet auf den ersten Veranstaltungstag. Unter 18 werden Name und Mailadresse einer erziehungsberechtigten Person erfragt; die bekommt eine Mail zum Bestätigen, erst dann gilt die Anmeldung. | M | 2 |
| D-07 | Bereiche und Schichten tragen ein **Mindestalter**, das bei der Anmeldung geprüft wird. Gesetzt: **Shuttle-Fahrer ab 18**, mit Führerschein als Voraussetzung (V-03). **Ausschank** – bei der AA bisher nicht, aber etwa Bier und Radler am Bratwurststand beim XCO: Vorgabe ab 18. Wer 16- und 17-Jährige einsetzen will, setzt das Mindestalter dieser Schicht bewusst auf 16 – dann nur unter ständiger Aufsicht eines Erwachsenen. Als Richtschnur für 15- bis 17-Jährige: höchstens 8 Stunden am Tag, nur zwischen 6 und 20 Uhr. | M | 2 |
| D-08 | Keine Drittlandübermittlung; Hosting und Mail-Relay stehen im Verzeichnis der Verarbeitungstätigkeiten. | M | 2 |
| D-09 | Datenschutzerklärung und Einwilligungstexte vor dem Start fachkundig prüfen lassen. | M | 2 |
| D-10 | Unter 13 wird der Einladungslink zur WhatsApp-Community nicht angezeigt – das Mindestalter von WhatsApp in der EU. | M | 3 |

**Stand 09.10.2026, Schritt 2.9:** D-01 bis D-03, D-05 bis D-07 sind
umgesetzt. Jedes Formular verweist auf `/datenschutz`; der Text dort ist ein
Entwurf und wartet auf die Prüfung (D-09). Die Einwilligung in den
Helferstamm ist ein eigenes, nicht vorangekreuztes Häkchen und in Mein
Helferplatz so leicht widerrufen wie erteilt. Unter 18 bestätigt eine
erziehungsberechtigte Person per Link; ohne sie sind die Plätze nach 72
Stunden frei – wer selbst erziehungsberechtigt ist und mitanmeldet,
bestätigt mit der eigenen Adresse. D-07 steht als Richtschnur in der
Übersicht (mehr als 8 Stunden am Tag, vor 6 oder nach 20 Uhr), nicht als
Sperre. Das Löschwerkzeug (deploy/daten-loeschen.py) behält den Helferstamm
und löscht ihn drei Jahre nach der letzten Teilnahme; die jährliche Frage
„Bleibst du dabei?“ aus D-04 kommt mit Phase 3.

Zu D-06 und D-07: Die Altersgrenze 16 aus Art. 8 DSGVO gilt nach Auffassung
der Aufsichtsbehörden hier eher nicht – sie betrifft Online-Dienste, die sich
direkt an Kinder richten. Die Zustimmung der Eltern ist trotzdem richtig,
schon wegen Aufsicht und Geschäftsfähigkeit. Das Jugendarbeitsschutzgesetz
nimmt gelegentliche Hilfe aus Gefälligkeit aus, greift aber, sobald es keine
reine Gefälligkeit mehr ist; seine Grenzen (8 Stunden, 6–20 Uhr) als
Richtschnur zu nehmen, ist die vorsichtige Lesart. Beim Ausschank dürfen
Minderjährige nur unter lückenloser Aufsicht helfen – einfacher ist, solche
Schichten auf ab 18 zu setzen.

**Zum Mindestalter 12:** Für Kinder unter 15 ist das
Jugendarbeitsschutzgesetz streng – unter 13 gar keine Beschäftigung, ab 13
nur leichte Arbeit, höchstens 2 Stunden, zwischen 8 und 18 Uhr. Dass
12-Jährige trotzdem helfen dürfen, hängt an der Ausnahme für gelegentliche
Hilfe aus Gefälligkeit. Entschieden ist: **keine Begleitpflicht** für 12- bis
14-Jährige. Die Elternbestätigung (D-06) bleibt, und welche Schichten für
Jüngere passen, regelt das Mindestalter je Bereich und Schicht (D-07).

### 5.13 Nichtfunktionale Anforderungen (N)

| Nr. | Anforderung | Prio |
| --- | --- | --- |
| N-01 | **Mobil zuerst**: alles geht auf einem fünf Jahre alten Android-Handy mit schlechtem Netz. | M |
| N-02 | Große Tippflächen, mindestens 16 px Schrift, hoher Kontrast; WCAG 2.1 AA als Richtschnur. | M |
| N-03 | **Einfache Sprache**, Du-Form, keine Fachbegriffe. Jede Seite hat genau eine Hauptaktion. | M |
| N-04 | Der Kernweg (Liste → Eintragen → Bestätigen) funktioniert **ohne JavaScript**; der Assistent darf es nutzen, fällt aber auf die Liste zurück. | S |
| N-05 | **Last**: ein Hilferuf an 200 Leute erzeugt eine Spitze. Der letzte freie Platz wird genau einmal vergeben, nie doppelt. | M |
| N-06 | Keine Werbung, keine Tracker, keine fremden Schriften oder CDNs – wie die übrigen Bereiche. | M |
| N-07 | Rate Limit und Honeypot gegen Spam-Anmeldungen, wie beim Kennzeichen-Formular. | M |
| N-08 | Sicherung täglich, Wiederherstellung geübt; während der Veranstaltung zusätzlich stündlich. | M |

---

## 6. Ideenspeicher

Was in der Diskussion aufkam und nicht schon oben steht – bewertet, damit es
nicht verloren geht und nicht unbemerkt den Umfang sprengt.

| Idee | Nutzen | Aufwand | Einschätzung |
| --- | --- | --- | --- |
| **Kombi-Vorschlag**: „Direkt danach am selben Ort ist noch Platz" | hoch – die zweite Schicht ohne Ortswechsel | klein | in G-03 aufgenommen |
| **Helferticket** zum Ausdrucken: Schichten, Treffpunkt, Ansprechpartner, QR für Check-in | hoch für Ältere | klein | mit A-09 |
| **Bedarfsmatrix** fürs Backoffice: Tage × Tageszeiten, eingefärbt nach Lücken – zeigt, wann ein Hilferuf nötig ist | mittel | klein | Phase 3 |
| **Schicht tauschen**: „Ich kann nicht, wer übernimmt?" als Angebot an die Warteliste und die passenden Springer | mittel | mittel | nach R-04 |
| **Bereichsgruppen**: je Bereich ein WhatsApp-Einladungslink, der nach dem Eintragen angezeigt wird | hoch für Bereichsleitungen | klein | Phase 3 |
| **Helfer werben Helfer** mit eigener Abzeichenstufe | mittel | klein | in G-06 |
| **Jahresrückblick** über alle Veranstaltungen des Vereins | mittel | klein | nach G-07 |
| **Sehen, wer schon dabei ist** – nur Vorname, nur wer zustimmt; man hilft lieber mit Bekannten | mittel | klein | mit G-06 prüfen |
| **Pufferzeit je Ortspaar** (Start → Ziel dauert 20 min) statt einer pauschalen Grenze in K-03 – in keinem gefundenen Werkzeug vorhanden | mittel für Streckenposten | mittel | nach K-03 |
| Wer zweimal unentschuldigt fehlt, wird vor der nächsten Anmeldung **angesprochen** (nicht gesperrt wie im Engelsystem) | gering | klein | später |
| Automatische Einteilung per Algorithmus | gering – Menschen wollen wählen | groß | nicht verfolgen |
| Eigene App, Offline-PWA | gering | groß | nicht verfolgen |
| SMS-Erinnerungen | mittel für Ältere | laufende Kosten | erst, wenn Mail nachweislich nicht reicht |

---

## 7. Technische Leitentscheidungen

### 7.1 Bauen oder einsetzen?

Bevor gebaut wird, die naheliegende Frage: gibt es das nicht schon? Zwei
Open-Source-Werkzeuge kommen ernsthaft infrage (Anhang B):

| | Engelsystem | Helfertool |
| --- | --- | --- |
| Herkunft | Chaos Computer Club, „Schichtplanung für Chaos-Veranstaltungen" | Open-Source-Projekt für Helfer bei Veranstaltungen |
| Technik | PHP, MySQL/MariaDB, GPL-2.0 | Python, Django, AGPL-3.0 |
| stark in | Konfliktsperre, Austragefrist, Goodie- und Shirt-System, Kalender-Abo | Schichten, Shirt-Größen, Geschenke je Schicht, Ausweise, Mails, PDF-Ausfuhr |
| passt nicht | Helfer brauchen ein Konto (Passwort oder OAuth); zweite Technik neben unserer | eigenes Datenmodell neben unserem |

**Entschieden: selbst bauen, die Muster übernehmen.** Der Grund ist nicht,
dass die beiden schlecht wären, sondern dass der Helferbereich schon steht:
Dashboard, Monitor, Material, Schlüssel, Unterschriften. Ein fremdes
Anmeldewerkzeug daneben hieße wieder zwei Systeme und ein Abgleich dazwischen –
genau die Lage von heute, nur selbst gehostet. Was fehlt, ist eine Anmeldung,
die in dieselben Schichten schreibt.

Rückfallebene, falls die Bauzeit (Abschnitt 9) nicht aufzubringen ist: das
**Helfertool** – gleiche Sprache wie unser Code. Zu klären wäre dann zuerst,
wie sich Helfer dort anmelden: an genau dieser Frage hängt die Zielgruppe.

### 7.2 Einbettung in das Bestehende

Die Anmeldung wird **Teil des Helferbereichs**, kein vierter Bereich. Sie
schreibt in dieselben Schichten und Einteilungen, die Dashboard, Monitor,
Material und Unterschriften heute schon lesen – dort ändert sich wenig.

| Wo | was |
| --- | --- |
| `helfer.example.de/` | öffentliche Startseite: angekündigte und offene Veranstaltungen |
| `helfer.example.de/<veranstaltung>/` | Anmeldung (Assistent und Liste) |
| `helfer.example.de/mein/<token>` | Mein Helferplatz |
| `helfer.example.de/s/<kurz>` | Direktlink auf eine Schicht |
| `admin.example.de/helfer/…` | Backoffice wie heute, erweitert |

Monitor und Tablet bleiben, wo sie sind. Der Abruf von helferliste.online
bleibt bis nach der Veranstaltung 2027 im Code – als Rückfallebene – und
fliegt danach heraus.

Der **Mailversand** wird dabei endlich nach `kern` gezogen. Kennzeichen und
Presse haben ihn je für sich; mit dem Helferbereich kommt der dritte Nutzer –
genau der Zeitpunkt, den sich das Projekt für Abstraktionen vorgenommen hat.

### 7.3 Datenbank

Die Frage aus dem Brainstorming war, ob sich eine „echte" Datenbank lohnt.
Vorweg: **SQLite ist eine echte Datenbank**, und für 200 Helfer reicht sie
auch unter Last. Der Grund für einen Wechsel ist ein anderer.

**Entschieden: PostgreSQL, eine Datenbank für den Dienst, ein Schema je
Bereich und eines für `kern`.** Die Gründe, alle aus diesem Projekt:

- **Das Schema wird sich stark bewegen.** SQLite kann Spalten und Bedingungen
  nur durch Neuaufbau der Tabelle ändern – das ist hier schon zweimal passiert
  (T-Shirt-Größe 5XL, `mail_out.typ`), beide Male mit Handarbeit und einem
  Fehler beim ersten Versuch.
- **Personen und Benutzer gehören allen drei Bereichen.** Mit drei
  SQLite-Dateien geht das nur über Umwege; ein gemeinsames `kern`-Schema löst
  es direkt.
- **Mehrere Schreiber gleichzeitig**: Hilferuf-Spitze plus Backoffice plus
  Abgleich. Der letzte freie Platz lässt sich mit `SELECT … FOR UPDATE`
  sauber genau einmal vergeben.
- Viele Veranstaltungen über Jahre, Auswertungen über Jahre – Abfragen, die
  in einer Datenbank leicht und über drei Dateien mühsam sind.

**Was es kostet**, ehrlich: ein Dienst mehr im Container (Updates, Sicherung
mit `pg_dump` statt `.backup`), und die Tests brauchen eine laufende
PostgreSQL. Lokal kommt sie aus `compose.yaml` in Docker, und jeder Test legt
sich darin eine frische Datenbank an.

Umsetzung im Stil des Hauses: **psycopg 3 mit SQL von Hand, kein ORM**,
Migrationen als nummerierte SQL-Dateien.

**Stand Oktober 2026: umgesetzt, für alle drei Bereiche.** Statt erst den
Helferbereich umzuziehen, sind Kennzeichen und Presse gleich mitgegangen –
sie sind klein, und zwei Arten Datenbank im selben Dienst hätten Sicherung,
Löschlauf und Tests doppelt gebraucht. Aus der SQLite-Zeit wird nichts
übernommen: PostgreSQL beginnt leer (Abschnitt 8). Im Schema `kern` stehen
schon die Backoffice-Konten und die Veranstaltungen; die Personen folgen mit
Phase 2.

### 7.4 Anmeldung der Helfer

**Empfehlung: Bestätigungslink und Code per Mail, kein Passwort, kein Social
Login.**

- Jede Mail enthält einen Link **und** einen sechsstelligen Code. Der Link
  öffnet nur eine Seite mit einem Knopf „Ja, das bin ich"; eingelöst wird erst
  beim Klick darauf. Grund: Mail-Scanner wie Outlook Safe Links rufen Links
  vorab auf – ein Link, der sich beim bloßen Aufruf verbraucht, wäre für
  den Helfer schon tot, bevor er ihn anklickt. Der Code hilft, wenn die Mail
  auf dem PC ankommt und die Anmeldung auf dem Handy läuft.
- Danach führt ein persönlicher Link in jeder Mail zu Mein Helferplatz; ein
  neuer lässt sich jederzeit mit der Adresse anfordern.
- E-Mail als Anmeldeweg gilt in strengen Standards nicht als starker zweiter
  Faktor. Für ein Helferportal mit geringem Schutzbedarf ist das vertretbar –
  für das Backoffice gilt B-03 mit eigenem Passwort.
- **Passkeys** später als freiwillige Ergänzung, nicht als Voraussetzung.
- **Social Login streichen.** Jeder Anbieter will eigens eingerichtet werden
  (Apple nur mit kostenpflichtigem Entwicklerkonto), viele wissen später nicht
  mehr, mit welchem Konto sie sich angemeldet haben – genau das erzeugt
  Dubletten. Dazu kommt Datenschutz: das Skript des Anbieters dürfte nicht
  beim Laden der Seite mitlaufen, und die Übermittlung in die USA hängt am
  Data Privacy Framework, gegen das ein Rechtsmittel anhängig ist. Der Merker
  aus dem Brainstorming ist damit beantwortet, solange niemand danach fragt.
- **SMS** nur, falls sich Mail als unzureichend erweist: rund 8–11 Cent je
  Nachricht, dazu ein Vertrag zur Auftragsverarbeitung.

### 7.5 Datenmodell (Skizze)

```sql
-- kern: gehört allen Bereichen
veranstaltung (id, name, kurz, beginn, ende, ort, status,
               anmeldung_ab, anmeldung_bis, beschreibung)
person        (id, vorname, nachname, email, email_bestaetigt_am, telefon,
               geburtsdatum, eltern_name, eltern_email, eltern_bestaetigt_am,
               angemeldet_von_person_id, stamm_einwilligung_am, angelegt_am)
konto         (id, email, name, kuerzel, telefon, passwort_hash, rolle,
               bereiche, aktiv)                -- umgesetzt (B-01 bis B-04)
zugangslink   (token_hash, person_id, zweck, gueltig_bis, benutzt_am)
mail_out      (…)                                -- aus Kennzeichen/Presse
protokoll     (id, benutzer_id, was, objekt, vorher, nachher, am)

-- helfer
bereich       (id, veranstaltung_id, name, beschreibung, treffpunkt,
               mindestalter, voraussetzungen, intern)
bereich_leitung (bereich_id, konto_id)         -- wer leitet (B-02)
schicht       (id, bereich_id, beginn, ende, ort, hinweis,
               minimum, soll, reserve, mindestalter, intern)
angebot       (veranstaltung_id, shirt, verpflegung, party)
teilnahme     (veranstaltung_id, person_id, tshirt, verpflegung,
               vorlieben, bemerkung)            -- je Veranstaltung neu
zusage        (id, schicht_id, person_id, art, quelle, status,
               angelegt_am, abgesagt_am, eingecheckt_am)
               -- art: platz | reserve | warteliste
               -- quelle: selbst | orga | springer | import
verfuegbarkeit (id, veranstaltung_id, person_id, beginn, ende, springer)
goodie        (id, veranstaltung_id, name, ab_schichten, ab_stunden,
               mindestalter, alternative)         -- "Bier am Bierwagen", 16, "Eistüte"
einsatzgrenze (id, person_id, bereich_id, schicht_id, art,
               angelegt_von, angelegt_am)
               -- art: nicht_anbieten | nur_zu_zweit; bewusst ohne Grund
party_zusage  (veranstaltung_id, person_id, kommt, begleitung, am)
```

`teilnahme` trennt, was sich jedes Jahr ändern darf (Größe, Verpflegung),
von der Person, die bleibt. `zusage` ersetzt die heutige `einteilung` und
nimmt Reserve, Warteliste, Absage und Check-in mit auf.

**Umgesetzt mit 2.2 – ohne zweites Modell neben dem Backoffice:** `person`
ist die bestehende Tabelle `helfer`, erweitert um Vor- und Nachname, Alter,
„mitangemeldet von“ und die Bestätigung der Adresse; `zusage` ist die
bestehende `einteilung`, erweitert um `art` (Platz oder Reserve) und die
Quelle *selbst*. Schichten, Monitor und Ausgabe sehen Selbstanmeldungen so
ohne Umweg. `teilnahme`, `verfuegbarkeit` und `interesse` sind neu. Shirt und
Verpflegung stehen vorerst weiter an der Person; je Veranstaltung wandern sie
mit der Ausgabe am Check-in (4.2).

**Mit 2.3** kamen `einsatzgrenze` wie skizziert (ohne Feld für einen Grund)
und `protokoll` (id, helfer_id, wer, was, am) dazu, beide im Schema helfer;
an `einteilung` steht der Vermerk, wenn die Orga eine Grenze übersteuert.

**Mit 2.4** kam `mail_out` in den Helferbereich, wie in Kennzeichen und
Presse. Statt `zugangslink` trägt `helfer` eine `zugang_version`: die Links
sind ein Siegel über Person, Zweck und Version, und wer die Version
hochzählt, macht alle alten ungültig.

**Mit 2.5** kamen `warteliste` (eigene Tabelle, damit sie nirgends
mitzählt, wo Einteilungen gezählt werden) und `absage` dazu; an
`einteilung` hält `bestaetigen_bis` einen angebotenen Platz, an `helfer`
stehen `email_neu` und `loeschen_beantragt_am`, am `protokoll` Veranstaltung
und Bereich. `zusage` aus der Skizze bleibt damit `einteilung` plus
`warteliste` plus `absage`.

---

## 8. Ablösung von helferliste.online

1. **2027 wird nur noch im neuen System angemeldet.** Ein Parallelbetrieb
   verdoppelt die Pflege und erzeugt genau die Dubletten, um die es geht.
2. Bis die neue Anmeldung öffnet, bleibt helferliste.online für nichts
   Neues in Benutzung.
3. Der Abruf bleibt bis nach der Veranstaltung 2027 als Rückfallebene im Code.
4. **Begonnen wird mit leerer Datenbank** (entschieden am 09.10.2026). Aus
   der SQLite-Zeit wird nichts übernommen, auch nicht die Schichten 2026 –
   die Schichten 2027 entstehen neu (0.4). Eine Vorlage (V-04) gibt es ab der
   zweiten Veranstaltung im neuen System.
5. Die **Personendaten aus 2026** waren nach der Veranstaltung zu löschen
   (Deployment-Doku, Abschnitt 8). Sind sie gelöscht, beginnt der
   Helferstamm 2027 neu – über die WhatsApp-Gruppen und die Ankündigung. Sind
   sie noch da, dürfen sie nicht einfach in den Stamm wandern: die Helfer
   haben dafür nicht eingewilligt (siehe D-*).
6. **Die erste Veranstaltung auf dem neuen System muss nicht die AA sein.**
   Gibt es vorher eine kleinere des ILRC, ist sie der ideale Probelauf:
   echte Helfer, echte Absagen, kleineres Risiko.

---

## 9. Umsetzungsplan

Aufwände wie in den anderen Plänen: reine Bauzeit, grob geschätzt.

### Phase 0 – Klären und ausprobieren (bis Ende Oktober 2026)

| # | Schritt | Aufwand |
| --- | --- | --- |
| 0.1 | Die restlichen offenen Fragen aus Abschnitt 11 entscheiden | Orga |
| 0.2 | **Klickbarer Prototyp** der Anmeldung (Assistent und Liste, fünf Bildschirme, statisches HTML) | 4 h |
| 0.3 | Prototyp mit **3–5 Helfern testen, die nicht IT-affin sind** – ihnen das Handy in die Hand geben und zuschauen | Orga, 2 h |
| 0.4 | Bereiche, Schichten und Belohnungsstufen 2027 festlegen – bis Ende November, denn zur Öffnung stehen sie in der Anmeldung | Orga |

Der Test in 0.3 ist der wichtigste Schritt des ganzen Plans. Er kostet einen
Abend und zeigt, ob Liste und Assistent tragen – bevor eine Zeile davon
gebaut ist.

### Phase 1 – Fundament (Ende Oktober bis Anfang November 2026)

| # | Schritt | Aufwand |
| --- | --- | --- |
| 1.1 | PostgreSQL im Container, Verbindung, Migrationen, frische Testdatenbank je Lauf | **erledigt** |
| 1.2 | Veranstaltungen als eigene Größe | **erledigt** |
| 1.3 | ~~Mailversand nach `kern` ziehen~~ (erledigt); **DKIM für die Absenderdomain fertigstellen** | 2 h |

1.3 ist kein Nebenschauplatz: ohne verlässliche Zustellung landet der
Bestätigungslink im Spam, und die ganze Anmeldung hängt daran. In der
Kennzeichen-README steht DKIM noch als offen.

Die **persönlichen Backoffice-Konten** (3.7) sollten erst nach der Öffnung
kommen. Sie sind im Oktober 2026 vorgezogen worden und fertig: Konten mit
Rolle und Bereichen, Einladung per Mail, das gemeinsame Passwort nur noch für
den Übergang.

### Phase 2 – Öffnung (November bis Mitte Dezember 2026)

So schmal, dass die Anmeldung früh öffnen kann – aber mit allem, was die
Daten sauber hält: Pflichtfelder, Konfliktsperre, Bestätigung,
Selbstbedienung.

| # | Schritt | Aufwand |
| --- | --- | --- |
| 2.1 | Bereiche und Schichten pflegen: Minimum/Soll/Reserve, Mindestalter, Voraussetzungen, intern, Goodies je Veranstaltung, Vorlage aus dem Vorjahr | **erledigt** |
| 2.1a | **Bereichsleitung als Konto** (B-02, aus Phase 3): sieht und pflegt nur ihre Bereiche, Schichten und Leute; Empfänger für Meldungen und Ausdrucke | **erledigt** |
| 2.1b | **Navigation nach dem Klickentwurf**: Veranstaltung im Kopf, Reiter nach dem, was sie nutzt (V-08), Gruppen im Helferbereich (Übersicht, Planen, Leute, Vor Ort), Einrichten bei der Veranstaltung, Goodie-Schalter und Shirt-Schnitt; die Ausgabe als eigener Reiter, vorerst mit den heutigen Seiten für Funk und Schlüssel | **erledigt** |
| 2.2 | Öffentliche Schichtliste mit Konfliktsperre, Pflichtfeldern, Mitanmeldung weiterer Personen, Springer-Zeiten; **Interesse vormerken** bei angekündigten Veranstaltungen (aus 3.3); Verfügbarkeit und Vorlieben schon im Datenmodell, für den Assistenten | **erledigt** |
| 2.3 | **Einsatzgrenzen**: pflegen, still anwenden, Hinweis „nur zu zweit" für die Bereichsleitung | **erledigt** |
| 2.4 | Bestätigungslink mit Code, Wiedererkennen per Adresse, **Dubletten erkennen** über Name und Nummer (I-05, aus 3.2), Mein Helferplatz (ansehen, dazunehmen), Kalender-Abo | **erledigt** |
| 2.5 | **Selbstbedienung**: stornieren, umbuchen, ganz abmelden, Angaben ändern, Daten löschen, Mitangemeldete; **Warteliste mit Nachrücken** (R-04, aus 3.6); Meldung kurzfristiger Absagen; Protokoll | **erledigt** |
| 2.6 | „Noch eine Schicht?" nach dem Eintragen, Tagesbalken auf der Startseite | **erledigt** |
| 2.7 | Dashboard und Monitor: Stufen statt Bedarf, Reserve, Springer, kurzfristige Absagen | **erledigt** |
| 2.8 | Druckansichten und Notfallmappe | **erledigt** |
| 2.9 | Datenschutzhinweise, Einwilligungen, Altersprüfung, Elternbestätigung, Löschwerkzeug angepasst | **erledigt** |
| 2.10 | Lasttest: 200 gleichzeitige Anmeldungen auf dieselben zehn Plätze, Umbuchen gegeneinander | **erledigt** |

**Stand 09.10.2026, Schritt 2.10:** Der Lasttest steht im Repository
(`helfer/tests/test_last.py`) und läuft mit allen anderen. 200 auf zehn
Plätze – aus 50 Threads direkt an der Datenbank und mit 200 gleichzeitigen
HTTP-Anfragen – ergeben genau zehn Einteilungen; dreißig, die in fünf Plätze
tauschen wollen, genau fünf. Gefunden hat er einen Deadlock beim Tauschen in
Gegenrichtung: jetzt sperrt jede Transaktion Schichten aufsteigend nach id.
Und er hat gezeigt, dass der Server Anmeldungen nacheinander abarbeitete –
die letzte von 200 wartete über 30 Sekunden. Anmeldung und öffentliche
Seiten laufen seither in Threads; lokal wartet die letzte rund 5 Sekunden,
auf dem Server mit schnellerem Verbindungsaufbau weniger. Ein
Verbindungspool für alle drei Bereiche wäre der nächste Schritt, falls es
je nötig wird.

**Vorgezogen am 09.10.2026** aus Phase 3, weil es dieselben Stellen anfasst:
die Bereichsleitung als Konto, die Warteliste (sie gehört in dieselbe
Transaktion wie Stornieren und Umbuchen), das Vormerken von Interesse (die
öffentliche Startseite) und das Erkennen von Dubletten (derselbe Abgleich wie
das Wiedererkennen per Adresse). Später gebaut, hätte jedes davon Phase 2 ein
zweites Mal aufgemacht. Der Assistent bleibt in Phase 3.

**Navigation (2.1b):** Mit Phase 2 kommen Anmeldungen, Warteliste,
Ausdrucke und ein neues Dashboard dazu; die Leiste des Helferbereichs war
schon vorher voll und mischte Planung mit dem Veranstaltungstag. Die neue
Gliederung steht vor 2.2, damit jede neue Seite gleich ihren Platz hat. Der
Klickentwurf: <https://kallelix.github.io/aa-kfz/prototyp-navigation/>

**Meilenstein:** Anmeldung öffnet. Ab hier wird nur noch ergänzt, nichts
Bestehendes umgebaut.

**Ziel ist Mitte Dezember 2026.** Ab dem 12. Oktober sind das gut neun Wochen
für Prototyp, Phase 1 und 2 – mit dem Vorgezogenen und der Navigation rund
89 Stunden. Davon sind der Prototyp (0.2), Phase 1 bis auf DKIM und 2.1 bis
2.10 erledigt; es bleibt DKIM (1.3), rund 2 Stunden, die 8 Stunden pro Woche haben
also Luft.

| Öffnung | Bauzeit pro Woche für die restlichen ~2 h, ab 12. Oktober |
| --- | --- |
| Anfang Dezember 2026 | < 0,5 h |
| **Mitte Dezember 2026** | **< 0,5 h** |
| Rückfallebene: Anfang März 2027 | ~1 h |

Danach entspannt es sich: Phase 3 und 4 sind noch rund 54 Stunden, von Januar
bis Ende April gut 3 Stunden pro Woche – mit sechs Wochen Puffer bis zum
Stillstand Mitte Juni. Und die Helfer haben über sechs Monate Zeit, sich bis
zur AA am 1.–4. Juli anzumelden.

### Phase 3 – Assistent, Helferstamm, Backoffice-Konten (Januar bis Ende Februar 2027)

Der Assistent kommt bewusst erst nach der Öffnung. Annahme dahinter: in den
ersten Wochen melden sich vor allem die, die schon wissen, was sie wollen –
für sie ist die Liste der schnellere Weg. Der Assistent zielt auf die Breite,
die später kommt, oft erst nach einem Hilferuf. Er hat deshalb in dieser
Phase Vorrang.

| # | Schritt | Aufwand |
| --- | --- | --- |
| 3.1 | **Assistent**: Verfügbarkeit, Vorlieben, Vorschläge nach Dringlichkeit, Springer | **erledigt** |
| 3.2 | Dubletten zusammenführen (I-06); das Erkennen kommt mit 2.4 | **erledigt** |
| 3.3 | Mail bei Anmeldestart an die Vorgemerkten (C-08); das Vormerken kommt mit 2.2 | **erledigt** |
| 3.4 | Hilferuf: knappe Schichten, Mail an passende Stamm-Helfer, WhatsApp-Text | **erledigt** |
| 3.5 | Erinnerung vor der Schicht, Danke-Mail mit Rückblick | 3 h |
| 3.6 | ~~Warteliste mit Nachrücken~~ – vorgezogen in 2.5 | – |
| 3.8 | **Materialausgabe verallgemeinern** (V-09): Materialien je Veranstaltung, eine Ausgabe für alles mit Rückgabe, Unterschrift und Nummer; Funk und Schlüssel ziehen um | 8 h |
| 3.7 | Persönliche Backoffice-Konten mit Rollen und Einladen – für alle drei Bereiche | **erledigt** |

### Phase 4 – Veranstaltungstag und Anerkennung (März bis Ende April 2027)

| # | Schritt | Aufwand |
| --- | --- | --- |
| 4.1 | **Check-in bei der Bereichsleitung**: Liste je Treffpunkt, QR-Scan, Häkchen bei schlechtem Netz nachreichen, *Ich bin da* für Posten ohne Orga; *noch nicht da* ab 15 Minuten vor Beginn, Springer einsetzen | 9 h |
| 4.2 | Ausgabe von Shirt und Goodies an den Check-in koppeln, Altersgrenze je Goodie | 2 h |
| 4.3 | Stempelkarte, Belohnungsstufen, Abzeichen | 6 h |
| 4.4 | Helferparty: Einladung, Zusagen, Begleitpersonen | 3 h |
| 4.5 | Freunde mitbringen | 3 h |

Der Check-in steht vorn: erst mit ihm ist *noch nicht da* verlässlich, und
am Veranstaltungstag ersetzt er die Papierliste.

**Ab Mitte Juni 2027, zwei Wochen vor dem Aufbau: Stillstand.** Nur noch
Fehler beheben, nichts Neues.

### Zusammen

| Phase | Aufwand |
| --- | --- |
| 1 Fundament | ~20 h, davon ~18 h erledigt |
| 2 Öffnung | ~65 h, **erledigt** |
| 3 Assistent, Helferstamm, Backoffice-Konten, Materialausgabe | ~40 h, davon ~29 h erledigt |
| 4 Veranstaltungstag, Anerkennung | ~23 h |
| **gesamt** | **~148 h** |

Phase 1 und 2 sind die Öffnung. Fällt die Zeit knapp aus, wird Phase 4
verschoben, nicht Phase 2 gekürzt – bis auf den Check-in (4.1), der zur AA
stehen sollte.

Kommt eine andere Veranstaltung des ILRC vor der AA, ändert sich an der
Reihenfolge nichts – sie wird dann einfach die erste auf dem neuen System
(Abschnitt 8).

---

## 10. Risiken

| Risiko | Gegenmittel |
| --- | --- |
| Ältere Helfer kommen mit der Anmeldung nicht zurecht | Test in 0.3; Telefonnummer der Orga auf jeder Seite; Orga kann im Backoffice für jemanden anmelden |
| Bestätigungsmails landen im Spam | DKIM vor dem Start (1.3), Absender ist ein echtes Postfach, Testmails an die großen Anbieter |
| Server fällt am Veranstaltungstag aus | Notfallmappe (L-03) am Vorabend drucken; Wiederherstellung geübt |
| Ein Entwickler, viel Wissen | Dokumentation wie bisher, Tests, einfache Technik |
| Umfang wächst während des Baus | Ideenspeicher (Abschnitt 6) statt Sofortumsetzung; Phase 4 ist verschiebbar |
| Spam-Anmeldungen | Bestätigungslink, Rate Limit, Honeypot |
| Das Dezember-Ziel ist ehrgeizig: rund 8 Stunden Bauzeit pro Woche ab sofort | Umzug auf PostgreSQL und Backoffice-Konten sind schon fertig; Rückfallebene Anfang März, dann reichen rund 4 Stunden pro Woche (Abschnitt 9) |
| Die Öffnung verzögert sich | Phase 2 ist bewusst schmal, der Assistent kommt danach. Notfalls läuft eine Veranstaltung noch einmal über helferliste.online – der Abruf ist ja noch da |
| Jemand bemerkt seine Einsatzgrenze und fühlt sich ausgegrenzt | K-06: dieselbe neutrale Antwort wie bei jeder nicht buchbaren Schicht; nichts auf Monitor, Ausdrucken, in Mails |
| Kurzfristige Absagen am Veranstaltungstag gehen unter | S-07: oben im Dashboard und auf dem Monitor, mit den Springern, die einspringen könnten |

---

## 11. Entscheidungen und offene Fragen

### Geklärt (08.10.2026)

- **Selbst bauen**, nicht Engelsystem oder Helfertool einsetzen (7.1).
- **PostgreSQL** (7.3).
- **Die Anmeldung öffnet im Dezember 2026**, geplant auf Mitte Dezember –
  für die AA 2027 und für andere Veranstaltungen des ILRC, die Helfer
  brauchen (Abschnitt 9). Die nötigen rund 8 Stunden Bauzeit pro Woche sind
  realistisch.
- **Mindestalter 12**, für Shuttle-Fahrer 18 (D-06, D-07).
- **Ausschank**: bei der AA bisher nicht, bei anderen Veranstaltungen schon
  (Bier und Radler beim XCO) – Vorgabe ab 18 (D-07).
- **Selbstbedienung** für Helfer: abmelden, Daten löschen, Schichten
  stornieren, umbuchen (5.3) – **jederzeit, ohne Frist**, auch während der
  Veranstaltung. Eine späte Absage ist besser als keine.
- **Einsatzgrenzen** für Helfer mit Einschränkungen, die aus dem Gedanken
  der Inklusion dabei sind – **still**, ohne dass sich jemand ausgeschlossen
  fühlt (K-05 bis K-09).
- **Nicht jede Veranstaltung bietet Goodies an** (V-07).
- **Anerkennung**: Helfershirt und kleine Goodies, je Veranstaltung frei
  festgelegt – Bier am Bierwagen, Eistüte, Getränkegutschein für die
  After-Hour. Verpflegung gibt es in der Regel ohnehin. Nach der
  Veranstaltung meist eine Helferparty für alle (V-07, G-02, G-09).
- **Keine Begleitpflicht** für 12- bis 14-Jährige (D-06, D-07).
- **AA 2027: Donnerstag 1. bis Sonntag 4. Juli 2027**, mit Vor- und
  Nachbereitung – zwei Monate früher als 2026 (Abschnitt 9).
- **Weitere Veranstaltungen 2027 sind noch unklar.** Geplant wird auf die AA
  hin; kommt eine davor dazu, ist sie der Probelauf (Abschnitt 8).
- **Check-in bei der Bereichsleitung**: sie scannt den QR-Code des Helfers
  oder hakt ihn per Namen ab; *noch nicht da* ab 15 Minuten vor
  Schichtbeginn (T-01, T-02). Am 09.10.2026 umgedreht – vorher war ein
  Selbst-Check-in per QR-Aushang geplant.
- **Backoffice-Konten** (09.10.2026): Anmeldung mit Mailadresse und
  Passwort; Rollen *Admin*, *Orga*, *Lesend* und je Konto die freigegebenen
  Bereiche; Einladung per Mail über den vorhandenen Versand. Das gemeinsame
  Passwort gilt nur, bis ein Admin sein eigenes Konto hat (B-01 bis B-04).
- **Datenstand 0** (09.10.2026): Aus der SQLite-Zeit wird nichts
  übernommen; PostgreSQL beginnt leer (Abschnitt 8).
- **Veranstaltungen** (09.10.2026): Mit welcher das Backoffice arbeitet,
  wählt jeder im Browser; ohne Wahl gilt die nächste, die noch nicht vorbei
  ist. Kennzeichen und Presse kommen dazu, wenn eine zweite Veranstaltung
  sie braucht (V-01, V-02).
- **Reihenfolge** (09.10.2026): Bereichsleitung als Konto, Warteliste,
  Interesse vormerken und das Erkennen von Dubletten sind aus Phase 3 in
  Phase 2 vorgezogen – sie fassen dieselben Stellen an. Der Assistent bleibt
  in Phase 3 (Abschnitt 9).
- **Navigation** (09.10.2026): Die Veranstaltung ist der Ausgangspunkt. Sie
  legt fest, welche Bereiche sie nutzt, und bei ihr steht, was man für sie
  einrichtet; der Helferbereich gliedert sich in Übersicht, Planen, Leute und
  Vor Ort (2.1b, V-08). Die Materialausgabe wird ein eigener Bereich mit
  Materialien je Veranstaltung (3.8, V-09).

### Offen

Keine davon hält den Zeitplan auf; sie lassen sich nebenher klären.

1. Sind die **Personendaten 2026 auf dem Server** gelöscht (Abschnitt 8)?
2. **Wer betreut die WhatsApp-Community** – und gibt es eine Vereinsnummer?
   Sollen die zwei bestehenden Gruppen darin aufgehen?
3. **Bereichsleitungen**: wer, für welche Bereiche? Sie bekommen Konten (B-02).
4. **Wer ist Verantwortlicher** im Sinne der DSGVO (Verein, vertreten durch
   …), und wer prüft die Datenschutzerklärung (D-09)?

---

## Anhang A – Quellen zu WhatsApp, Anmeldung und Datenschutz

Abgerufen am 08.10.2026. Bei Sekundärquellen ist das vermerkt.

### WhatsApp

- Gruppen-API (höchstens 8 Teilnehmer, Official Business Account nötig):
  <https://developers.facebook.com/documentation/business-messaging/whatsapp/groups/>
- Voraussetzungen Official Business Account:
  <https://developers.facebook.com/documentation/business-messaging/whatsapp/official-business-accounts/>
- Einordnung Utility/Marketing:
  <https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/template-categorization/>
- Preise Deutschland (Sekundärquellen, Sept. 2026):
  <https://whautomate.com/whatsapp-business-api-pricing-germany>,
  <https://nordflux.de/en/insights/whatsapp-business-api-pricing-october-2026>
- Kanäle ohne offizielle API (Sekundärquelle):
  <https://getkanal.com/blog/whatsapp-channels-feature-guide>
- Business Messaging Policy (Opt-in, Abmeldung): <https://whatsappbusiness.com/policy/>
- Nutzungsbedingungen EWR (automatisierter Zugriff):
  <https://www.whatsapp.com/legal/terms-of-service-eea>
- Hinweise zu Communities (Einladungslinks nicht öffentlich posten):
  <https://www.whatsapp.com/communities/learning/buildingasafecommunity?lang=en>
- Vorbefüllter Text per `wa.me`: <https://faq.whatsapp.com/en/general/26000030>
- BayLDA zu WhatsApp im Verein: <https://lda.bayern.de/de/faq.html>

### Anmeldung

- Mail-Scanner verbrauchen Einmal-Links:
  <https://stytch.com/docs/b2b/guides/magic-links/overview>,
  <https://docs.descope.com/conditions/email-scanner>
- BSI zu Passkeys:
  <https://www.bsi.bund.de/DE/Themen/Verbraucherinnen-und-Verbraucher/Informationen-und-Empfehlungen/Cyber-Sicherheitsempfehlungen/Accountschutz/Passkeys/passkeys-anmelden-ohne-passwort_node.html>
- Google-Anmeldung und Einwilligung (Sekundärquelle):
  <https://datenrein.de/guides/tools/google-sign-in/>
- EuGH Fashion ID, C-40/17 (Mitverantwortung bei eingebundenen Plugins)

### Datenschutz und Jugendschutz

- Datenschutzhinweise eines Helfertools (Hessischer Turnverband, 2025):
  <https://www.landeskinderturnfest.de/fileadmin/img/Z_LKTF_2026/Dateien/2025_Datenschutzhinweise_Helfertool_Einsatz-Buchung.pdf>
- LfDI Baden-Württemberg, Datenschutz im Verein:
  <https://www.lda.bayern.de/media/info_bw_verein.pdf>
- Art. 13 DSGVO: <https://dsgvo-gesetz.de/art-13-dsgvo/>
- Jugendarbeitsschutzgesetz: <https://www.gesetze-im-internet.de/jarbschg/BJNR009650976.html>
- Ehrenamt und Jugendarbeitsschutz:
  <https://www.engagiert-in-nrw.de/landesservicestelle/rechtliche-hinweise/noch-mehr-rechtliches>
- Minderjährige beim Ausschank: <https://www.ajs-bw.de/media/files/ajs_sm-alkverkauf_jugendliche.pdf>

---

## Anhang B – Was andere machen

Abgerufen am 08.10.2026. Je Muster, wo es im Lastenheft gelandet ist.

### helferliste.online

- Preismodell, kostenlos für nichtkommerziellen Gebrauch:
  <https://www.helferliste.online/>
- Ein Name genügt, Pflichtfelder nur vor dem ersten Eintrag änderbar, andere
  Personen eintragen, CSV/PDF/ICS: <https://www.helferliste.online/hilfe-faq>
- Vorlage kopieren, Austragen moderieren: <https://www.helferliste.online/tipps>
- Betreiber, Hosting, eingebundene Dienste: <https://www.helferliste.online/datenschutz.php>

### Muster

| Muster | Werkzeug | im Lastenheft |
| --- | --- | --- |
| Zeiten mit „gern / ungern / kann nicht", danach Einteilen per Klick | WhenToHelp | A-02, R-07 |
| Selbst wählen bis zur Frist, den Rest teilt die Orga ein | Inzetrooster | R-07 |
| Überschneidung sperrt die Anmeldung (`COLLIDES`) | Engelsystem | K-01 |
| Wahlweise warnen oder sperren | VolunteerHub | K-02 |
| Mindestabstand zwischen zwei Schichten | Rosterfy | K-03 |
| Drei Wartelisten-Modi je Schicht | Bloomerang Volunteer | R-03, R-04 |
| Nachrücken mit Mail bei Absage | SignUpGenius | R-04 |
| Selbst austragen bis X Stunden vorher | Engelsystem | S-01 – bewusst ohne Frist |
| Goodie-Punkte, Nachtschichten doppelt, Shirt mit Größe | Engelsystem | G-02 |
| Geschenk je geleisteter Schicht, Ausgabe abgehakt | Helfertool | G-02, T-03 |
| Meilensteine, Jubiläen | Rosterfy, Track it Forward | G-05 |
| Plätze für ein Team reservieren | Golden Volunteer | A-08, G-06 |
| Sehen, wer schon eingetragen ist | Bloomerang Volunteer | Ideenspeicher |
| Bestätigungslink statt Passwort, mehrere Profile je Adresse | VolunteerHub, Inzetrooster | 7.4, A-08 |
| Dublettenvorschläge, Haushalte ausgenommen | Planning Center | I-05 |
| QR-Check-in, automatisch „nicht erschienen" | Rosterfy | T-01, T-02 |
| QR-Aushang, Selbst-Check-in | Bloomerang Volunteer | verworfen, siehe T-01 |
| Vorjahreshelfer mit einem Klick einladen | Helferstube, FestivalPro | C-08 |
| Mehrere offene Schichten in einer Mail, Zusage aus der Mail | Bloomerang Volunteer | C-03 |
| Kalender-Abo, das sich selbst aktualisiert | Engelsystem | A-10 |

### Quellen

- WhenToHelp: <https://whentohelp.com/volunteer-scheduling.htm>
- Rosterfy (automatische Einteilung, Abstand): <https://helpdesk.myvolunteer.bhf.org.uk/en/articles/11615162-automatic-rostering>
- Rosterfy (QR-Check-in, nicht erschienen): <https://rosterfy.com/knowledge/qr-code-scan-checkin>,
  <https://www.rosterfy.com/knowledge/automated-no-show-status-on-shift-attendance>
- Rosterfy (Anerkennung): <https://www.rosterfy.com/platform/retain-reward/>
- Inzetrooster: <https://inzetrooster.nl/sportclubs-met-bardiensten?locale=en>
- Engelsystem: <https://github.com/engelsystem/engelsystem>,
  Konfiguration <https://engelsystem.de/doc/admin/configuration/index.html>,
  Kalender-Abo <https://engelsystem.de/doc/user/ical/index.html>
- Helfertool: <https://github.com/helfertool/helfertool>, <https://www.helfertool.org/features/>
- VolunteerHub: <https://support.volunteerhub.com/support/solutions/articles/60000610885>,
  <https://support.volunteerhub.com/support/solutions/articles/60001378101>
- Bloomerang Volunteer: <https://help.bloomerang.com/en/articles/12648883-what-is-shift-waitlisting>,
  <https://help.bloomerang.com/en/articles/12649251-share-the-attendance-kiosk-qr-code-or-link>,
  <https://bloomerang.com/blog/feature-release-advanced-screening-emailing-and-scheduling-enhancements>
- SignUpGenius: <https://www.signupgenius.com/blog/waitlist-feature>
- Golden Volunteer: <https://support.goldenvolunteer.com/knowledge_base/team-signup-for-organizers>
- Planning Center: <https://help.planningcenter.com/en/138581-merge-duplicate-profiles.html>
- Track it Forward: <https://help.trackitforward.com/help/milestones-32eccaa4>
- Helferstube: <https://helferstube.de/>
- FestivalPro: <https://festivalpro.com/features/volunteers.html>
- Bestenlisten in Ehrenamtsprojekten: Eveleigh et al. 2013
  <https://discovery.ucl.ac.uk/id/eprint/1412171>; Ponti et al. 2018
  <https://theoryandpractice.citizenscienceassociation.org/articles/101>
