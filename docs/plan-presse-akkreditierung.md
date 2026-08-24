# Presse-Akkreditierung „Die absolute Abfahrt" – Projektplan

Schwesterprojekt zur Kennzeichen-App. Eigener Container, eigene URL, eigene
Datenbank; gemeinsam sind Oberfläche, Anmeldung, Mailversand und Deployment.

---

## 1. Ziel

Fotografen und Videografen melden sich vorab an. Wer kommerziell verwertet,
wählt dabei zwischen Akkreditierungsgebühr und Bilderspende. Das Presse-Badge
wird **immer physisch am Orga-Büro abgeholt**; die Badges sind vorproduziert und
nicht personalisiert.

Damit ersetzt die App die heutige Handarbeit: Interessent schreibt eine Mail →
Orga antwortet mit der Infomail → Person taucht am Orga-Büro auf. Künftig füllt
die Person ein Formular aus und bekommt die Infomail automatisch, passend zur
gewählten Variante.

**Es gibt keine Genehmigung.** Wer sich anmeldet, bekommt ein Badge.

---

## 2. Funktionsumfang

### 2.1 Öffentliches Formular

| Feld | Typ | Pflicht | Bemerkung |
|---|---|---|---|
| Vorname | Text | ja | |
| Name | Text | ja | |
| Firma | Text | ja | Redaktion, Agentur oder „freiberuflich" |
| E-Mail | E-Mail | **ja** | Die Bestätigungsmail trägt die Bedingungen – sie muss ankommen |
| Telefon | Text | nein | für Rückfragen |
| Kommerzielle Nutzung | ja/nein | ja | |
| Gegenleistung | Auswahl | nur bei „ja" | Gebühr **oder** Bilderspende |
| Sicherheitshinweis gelesen | Häkchen | ja | siehe unten |
| Bildrechte akzeptiert | Häkchen | nur bei Bilderspende | siehe unten |
| Bemerkung | Freitext | nein | |

**E-Mail ist hier Pflicht**, anders als bei den Kennzeichen. Dort ging es auch
telefonisch; hier hängt an der Mail die Zustimmung zu Sicherheitshinweis und
Bildrechten. Telefon bleibt freiwillig.

### 2.2 Die beiden Häkchen

**Sicherheitshinweis.** Der Text aus der heutigen Infomail – keine Sonderrechte
beim Betreten abgesperrter Bereiche, Strecke und Sturzzonen, Anweisungen des
Personals – steht im Formular und muss angehakt werden. Gespeichert wird der
Zeitpunkt. Heute steht das in einer Mail, die jemand von Hand verschickt, und
ist nirgends belegt. Bei einer Veranstaltung mit Sturzzonen ist das mehr als
Formalie.

**Bildrechte.** Wer die Bilderspende wählt, räumt Nutzungsrechte ein: Promotion
der Veranstaltung, Social Media, Print, Merch. Das ist eine Lizenz und gehört
dokumentiert – Bedingungen im Formular sichtbar, Zustimmung mit Zeitstempel.

Beide Texte liegen als Vorlage im Code, nicht in Env-Variablen: eine
Rechtsaussage gehört in die Versionsverwaltung, wo nachvollziehbar bleibt, wer
wann welchen Wortlaut zugestimmt hat.

### 2.3 Backoffice

Dieselbe Anmeldung wie in der Kennzeichen-App (gemeinsames Passwort, siehe
dort), aber eigene Instanz und damit eigenes Passwort.

- **Liste** aller Anmeldungen: Name, Firma, kommerziell, Gegenleistung, Status.
  Filter und Freitextsuche wie gehabt.
- **Detailansicht** mit Korrekturmöglichkeit und Löschen.
- **Abholliste** fürs Orga-Büro – der wichtigste Teil, siehe 2.4.
- **Bilder ausstehend** – siehe 2.5.
- **CSV-Export**.

### 2.4 Abholliste (Orga-Büro)

Strukturell dieselbe Ansicht wie die Durchfahrtsliste an der Straßensperre, nur
mit anderen Spalten:

| Vorname | Name | Firma | Gegenleistung | Badge | Gebühr |

- Suche im Browser über Vorname, Name und Firma – ohne Netz, wie an der Sperre.
- Häkchen **„Badge ausgegeben"** setzt den Status auf `ausgegeben`.
- Häkchen **„Gebühr bezahlt"** nur bei denen, die die Gebühr gewählt haben.
  Bezahlt wird bar bei der Abholung, deshalb genügt das Häkchen – kein
  Verwendungszweck, kein Zahlungsabgleich, keine Mahnung.
- Wer die Bilderspende gewählt hat, zeigt statt der Gebührenspalte den Hinweis
  „Bilderspende".

Ob diese Ansicht auch über einen widerrufbaren Link ohne Anmeldung erreichbar
sein soll wie die Durchfahrtsliste: siehe offene Fragen.

### 2.5 Bilder ausstehend

Nach der Veranstaltung: wer Bilderspende gewählt und ein Badge bekommen hat,
aber noch nicht geliefert hat. Mit Häkchen „Bilder erhalten" und einem Knopf
„Erinnerung senden" je Zeile sowie als Sammelaktion.

Die Erinnerung wird **von Hand ausgelöst**, nicht nach Datum automatisch. Ein
Zeitplan bräuchte ein konfiguriertes Veranstaltungsdatum und einen Cron-Job, und
die Orga weiß besser als ein Kalender, wann der richtige Moment ist. Wann die
letzte Erinnerung rausging, merkt sich die App.

---

## 3. Datenmodell

```sql
CREATE TABLE antrag (
  id          INTEGER PRIMARY KEY,
  vorname     TEXT NOT NULL,
  nachname    TEXT NOT NULL,
  firma       TEXT NOT NULL,
  email       TEXT NOT NULL,
  telefon     TEXT,
  kommerziell INTEGER NOT NULL,              -- 0 | 1
  gegenleistung TEXT,                        -- NULL | gebuehr | bilderspende
  bemerkung   TEXT,

  status      TEXT NOT NULL DEFAULT 'neu',   -- neu | ausgegeben
  badge_am    TEXT,                          -- Abholung am Orga-Büro
  badge_durch TEXT,                          -- Kürzel

  gebuehr_bezahlt_am   TEXT,                 -- nur bei gegenleistung = gebuehr
  bilder_erhalten_am   TEXT,                 -- nur bei bilderspende
  erinnerung_am        TEXT,                 -- letzte Erinnerung an die Bilder

  sicherheit_ok_am  TEXT NOT NULL,           -- Zeitpunkt der Bestätigung
  bildrechte_ok_am  TEXT,                    -- nur bei bilderspende

  created_at  TEXT NOT NULL,
  remote_ip   TEXT,

  CHECK (kommerziell IN (0, 1)),
  CHECK (gegenleistung IS NULL OR gegenleistung IN ('gebuehr', 'bilderspende')),
  -- Kommerziell heißt: eine Gegenleistung ist gewählt. Nicht kommerziell heißt:
  -- keine. Die Regel steht in der Validierung und hier nochmal als Netz.
  CHECK ((kommerziell = 1) = (gegenleistung IS NOT NULL)),
  CHECK (gegenleistung <> 'bilderspende' OR bildrechte_ok_am IS NOT NULL)
);
```

Dazu `mail_out` und `einstellung` unverändert aus der Kennzeichen-App.

**Statusmodell:** `neu ──▶ ausgegeben`. Mehr braucht es nicht. Wer doch nicht
kommen soll, wird gelöscht.

---

## 4. Mails

Nur noch **zwei** statt drei – es gibt keine Genehmigung und keine Absage.

### 4.1 Eingangsbestätigung

Die heutige Infomail, aber schon auf die getroffene Wahl zugeschnitten. Entwurf:

```
Hallo {Vorname},

vielen Dank für dein Interesse, die Absolute Abfahrt in Ilmenau mit Fotos und
Videos zu begleiten – wir freuen uns auf euch!

Deine Anmeldung ist bei uns angekommen:

  Anmeldenummer: {Nr}
  Name:          {Vorname} {Name}
  Firma:         {Firma}
  Nutzung:       kommerziell

  >> Variante A, Gebühr:
  Akkreditierung: 20 EUR Gebühr, bar am Orga-Büro zu zahlen

  >> Variante B, Bilderspende:
  Akkreditierung: ca. 10 Bilder als Spende an den Verein

  Interessiert sind wir vor allem an emotionalen Stimmungsbildern, aber auch
  an Aufnahmen von 1–2 Fahrern unserer Wahl, die wir im Nachgang auf eurer
  Vertriebsplattform auswählen können.

  Die gespendeten Bilder nutzen wir für die zukünftige Promotion der
  Veranstaltung – vor allem für Social Media, Print und Merch. Eine
  Verlinkung auf Social Media ist, wenn gewünscht, selbstverständlich möglich.

  >> nicht kommerziell:
  Akkreditierung: keine Gebühr

Ablauf vor Ort

Meldet euch bitte am Orga-Büro mit euren Kontaktdaten – dort erhaltet ihr euer
Presse-Badge. Das Presse-Badge ist für die kommerzielle Verwertung eures
Contents obligatorisch.

Wichtiger Hinweis

Durch das Presse-Badge habt ihr keine Sonderrechte, was das Betreten der
abgesperrten Bereiche betrifft. Dies gilt insbesondere für die Strecke und die
ausgewiesenen Sturzzonen. Bitte haltet euch aus Sicherheitsgründen unbedingt an
die Absperrungen und die Anweisungen des Veranstaltungspersonals.

Bei Fragen melde dich gerne jederzeit.

Wir freuen uns auf euch und eure Bilder!

Sportliche Grüße
{Kontakt}
```

Der Sicherheitshinweis steht bewusst **doppelt** – im Formular zum Anhaken und
nochmal in der Mail zum Nachlesen.

### 4.2 Erinnerung an die Bilderspende

Kurz, freundlich, nennt die Anmeldenummer und wohin die Bilder sollen.

---

## 5. Konfiguration

Neu gegenüber der Kennzeichen-App:

```
GEBUEHR_BETRAG=20
GEBUEHR_WAEHRUNG=EUR
BILDER_ANZAHL=10
ABHOLORT=Orga-Büro
BILDER_ABGABE=...        # wohin die Bilder sollen, für die Erinnerungsmail
```

Übernommen: `BIND`, `FORWARDED_ALLOW_IPS`, `DB_PATH`, `ADMIN_PASSWORD_HASH`,
`APP_SECRET_KEY`, `COOKIE_SECURE`, die SMTP-Werte, `CSV_TRENNER`,
`KUERZEL_ABFRAGEN`, `IP_SPEICHERN`.

Der Mailversand läuft über dieselbe Absenderdomain – SPF, DKIM und DMARC sind
damit schon erledigt.

---

## 6. Was übernommen wird, was wegfällt

**Übernommen, praktisch unverändert:**
`auth.py` (Anmeldung, Sitzung, CSRF, Rate Limit), `worker.py` und der
SMTP-Versand aus `mail.py`, die SQLite-Grundlagen samt Spalten-Migration,
der Env-Loader, `style.css` und die Basis-Templates, der CSV-Export, die
Suche und Sortierung im Browser (`durchfahrt.js`), das komplette `deploy/`.

**Fällt weg:**
Genehmigen/Ablehnen samt Begründung und Absagemail, Kartendruck mit QR-Code,
Kategorien, Kennzeichen und dessen Normalisierung, Kontingente, Telefonliste
(ohne Absagen gibt es nichts telefonisch mitzuteilen).

**Neu:**
Bedingte Pflichtfelder (Gegenleistung nur bei kommerzieller Nutzung), die
beiden Zustimmungs-Häkchen, Gebühren- und Bilderverfolgung, Erinnerungsmail.

---

## 7. Struktur

Ein Repo, zwei Apps, gemeinsamer Kern – **aber der Kern wird erst gezogen,
wenn die Presse-App steht.** Eine Abstraktion aus einem einzigen Beispiel wird
fast immer falsch; der zweite Fall zeigt, wo die Naht wirklich liegt.

Zielbild:

```
kfz/       Kennzeichen-App
presse/    Akkreditierung
kern/      erst im Schritt „Kern ziehen"
deploy/    je Anwendung eine Unit und ein nginx-Block
docs/
```

### Achtung: die Kennzeichen-App läuft bereits

Auf dem Server zeigen systemd-Unit, nginx-Config und Cron auf `/opt/abfahrt`
mit `app/` direkt darunter. Verschiebt man den Bestand nach `kfz/`, bricht der
nächste `git pull` den laufenden Dienst, bis Unit und Pfade nachgezogen sind.

Deshalb der Vorschlag: **`presse/` neben dem bestehenden Layout aufbauen und den
Umzug von `kfz/` erst nach der Veranstaltung machen.** Sieht für eine Weile
unsymmetrisch aus, riskiert aber nichts an einem System, das gerade gebraucht
wird.

---

## 8. Umsetzungsschritte

| # | Schritt | Aufwand |
|---|---|---|
| 1 | Gerüst `presse/`, Config, Schema | 1 h |
| 2 | Formular mit bedingten Feldern und den zwei Häkchen | 2,5 h |
| 3 | Anmeldung und Backoffice-Liste (aus der Kennzeichen-App übernommen) | 1 h |
| 4 | Detailansicht, Korrigieren, Löschen | 1 h |
| 5 | Abholliste mit Badge- und Gebühren-Häkchen | 1,5 h |
| 6 | Mail-Queue, Bestätigungsmail in drei Varianten | 1,5 h |
| 7 | Ansicht „Bilder ausstehend" samt Erinnerungsmail | 1,5 h |
| 8 | CSV-Export | 0,5 h |
| 9 | Deployment: zweite Unit, zweiter nginx-Block, zweites Backup | 1 h |
| 10 | Später: Kern ziehen, `kfz/` umziehen | 3 h |

---

## 9. Geklärt

- Gebühr wird **bar bei der Abholung** bezahlt – ein Häkchen genügt
- **Alle** melden sich an, auch nicht-kommerzielle Fotografen
- Bilderspende wird nachgehalten, mit Häkchen **und** Erinnerungsmail
- Monorepo, Kern erst nach der Presse-App ziehen
- Keine Genehmigung, kein Kartendruck
- **Kein offener Link** für die Abholliste – sie bleibt hinter der Anmeldung
- Adresse der App über Env pflegbar, nicht im Code festgeschrieben
- Badge-Zahl ist begrenzt, Obergrenze über Env pflegbar
- Beim Abholen wird ein **Bearbeiter-Kürzel** erfasst
- Der **Zahlungshinweis** steht auf der Bestätigungsseite und in der Mail

### Zur Badge-Obergrenze

`BADGES_GESAMT` zählt gegen die Zahl der Anmeldungen. Ist sie erreicht, warnt
das Backoffice und das Formular weist darauf hin, dass die Badges knapp werden.

**Angenommen wird trotzdem weiter.** Ein hartes Abriegeln würde auch genau den
Fotografen abweisen, den die Orga eigentlich dabeihaben will – und die Orga sieht
in der Liste, wer zuletzt kam. Wer es strenger will: das ist eine Zeile.

## 10. Offene Fragen

1. Wohin sollen die gespendeten Bilder – Mailadresse, Cloud-Ordner, Upload?
   Steht als `BILDER_ABGABE` in der Konfiguration und blockiert nichts; nur der
   Text der Erinnerungsmail bleibt bis dahin allgemein.
