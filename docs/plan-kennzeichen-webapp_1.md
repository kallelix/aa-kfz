# Kennzeichen-Antrag "Die absolute Abfahrt" – Projektplan

## 1. Ziel

Kleine Webanwendung, über die Helfer/Beteiligte Fahrzeug-Kennzeichen (Durchfahrtsberechtigungen) beantragen können. Dazu ein Backoffice, in dem die Liste eingesehen und exportiert werden kann.

Die App spricht **nur HTTP** und lauscht auf `127.0.0.1:<Port>`. TLS, HTTP→HTTPS-Redirect und Zertifikate macht der Reverse Proxy (nginx/Caddy/Traefik) davor.

---

## 2. Funktionsumfang (MVP)

### 2.1 Öffentliches Formular (`GET/POST /`)

Felder:

| Feld | Typ | Pflicht | Bemerkung |
|---|---|---|---|
| Vorname | Text | ja | |
| Name | Text | ja | |
| Funktion | Freitext | ja | Platzhalter im Feld: „z. B. Streckenposten, Aufbau, Sanität, Presse" |
| Kategorie | Auswahl | ja | siehe unten |
| E-Mail | E-Mail | nein | wenn vorhanden, laufen Eingangs- und Entscheidungsmail darüber |
| Telefon | Text | nein | für Rückfragen und für alle ohne Mailadresse |

**Regel: mindestens eines von beiden.** Beide Felder einzeln optional, aber die Validierung lehnt ab, wenn weder Mail noch Telefon eingetragen ist – sonst hast du Anträge, bei denen niemand die Person erreichen kann.

Kategorien (konfigurierbar, nicht fest im Code):
- `campingplatz` – Durchfahrt Campingplatz
- `vip_parkplatz` – VIP-Parkplatz

Optional sinnvoll, kostet fast nichts:
- Kfz-Kennzeichen (amtliches) – hilft beim Abgleich vor Ort
- Bemerkungsfeld

Nach dem Absenden: Bestätigungsseite ("Antrag eingegangen") plus Eingangsmail, kein Login nötig.

Hinweis zu **Freitext bei „Funktion"**: für die spätere Auswertung leidet die Sauberkeit (aus „Sani", „Sanitäter", „Sanität" werden drei Gruppen). Wenn du im Backoffice nach Funktion gruppieren willst, lohnt sich dort ein Korrekturfeld – der Antragsteller schreibt frei, die Redaktion räumt beim Genehmigen auf.

**Missbrauchsschutz** (weil öffentlich erreichbar):
- Honeypot-Feld (verstecktes Input, wenn befüllt → verwerfen)
- Rate Limit pro IP (z. B. 10 Anträge/Stunde), am einfachsten im Reverse Proxy
- Optional: Formular nur über nicht-geratenen Pfad, z. B. `/antrag/abfahrt30`

### 2.2 Backoffice (`/admin`)

- Tabellenansicht aller Anträge (sortier-/filterbar nach Kategorie, Status, Datum)
- Einzelne Anträge bearbeiten und löschen
- **CSV-Export** (wichtig für Druck der Karten / Serienbrief)
- Zähler pro Kategorie (Kontingente im Blick behalten)

### 2.3 Redaktionelle Freigabe

Kern des Backoffice. Statusmodell:

```
neu ──▶ genehmigt ──▶ ausgegeben
  └───▶ abgelehnt
```

Pro Antrag in der Detailansicht:

- **Genehmigen** – optional mit korrigierten Werten (Kategorie umbiegen, Funktion vereinheitlichen, Schreibfehler im Namen)
- **Ablehnen** – mit Pflicht-Begründung als Freitext, geht in die Mail an den Antragsteller
- **Zurücksetzen** auf `neu`, falls versehentlich entschieden
- **Ausgegeben** – Häkchen bei der Kartenübergabe vor Ort

Festhalten bei jeder Entscheidung: Zeitpunkt und Begründung. Wer entschieden hat, lässt sich beim gemeinsamen Passwort nicht sauber protokollieren – wenn das wichtig wird, ein Freitextfeld „bearbeitet von" mit Kürzel, das genügt in der Praxis.

Arbeitserleichterung, wenn viele Anträge kommen:
- Sammelaktion: mehrere markieren → alle genehmigen
- Standardansicht ist gefiltert auf `neu`, damit man die offenen Fälle sofort sieht
- Vor dem Genehmigen prüfen, ob das Kontingent der Kategorie schon voll ist (Warnung, kein harter Block)

Nice-to-have, wenn Zeit bleibt:
- Druckansicht: A6-Karten mit Name, Funktion, Kategorie, Jubiläums-Logo, QR-Code
- Kontingent-Limit pro Kategorie mit Warnung bei Überschreitung

---

## 3. Datenmodell

```sql
CREATE TABLE antrag (
  id          INTEGER PRIMARY KEY,
  vorname     TEXT NOT NULL,
  nachname    TEXT NOT NULL,
  funktion    TEXT NOT NULL,
  kategorie   TEXT NOT NULL,        -- campingplatz | vip_parkplatz
  email       TEXT,                 -- optional, mind. eines von email/telefon
  telefon     TEXT,                 -- optional
  kennzeichen TEXT,                 -- optional
  bemerkung   TEXT,
  status      TEXT NOT NULL DEFAULT 'neu',  -- neu | genehmigt | abgelehnt | ausgegeben
  entscheidung_am    TEXT,
  entscheidung_durch TEXT,          -- Kürzel, frei eingetragen
  begruendung        TEXT,          -- Pflicht bei Ablehnung
  tel_informiert_am  TEXT,          -- für Anträge ohne Mailadresse
  created_at  TEXT NOT NULL,
  remote_ip   TEXT                  -- nur für Missbrauchsfälle, kurz aufbewahren
);

CREATE TABLE mail_out (            -- Ausgangs-Queue, siehe Abschnitt 5
  id          INTEGER PRIMARY KEY,
  antrag_id   INTEGER REFERENCES antrag(id) ON DELETE CASCADE,
  typ         TEXT NOT NULL,       -- eingang | genehmigt | abgelehnt
  empfaenger  TEXT NOT NULL,
  betreff     TEXT NOT NULL,
  body        TEXT NOT NULL,
  versuche    INTEGER NOT NULL DEFAULT 0,
  gesendet_am TEXT,
  letzter_fehler TEXT
);
```

SQLite reicht vollkommen – es sind vermutlich einige hundert Datensätze. Eine Datei, ein `cp` als Backup.

---

## 4. Authentifizierung fürs Backoffice

**Entscheidung: gemeinsames Passwort (Variante A).** Magic Link bleibt als Option dokumentiert, wird aber nicht gebaut.

### Variante A: Ein gemeinsames Passwort *(gewählt)*

- Passwort als Hash (bcrypt/argon2) in der Env-Variable, nicht im Code
- Nach Login Session-Cookie: `HttpOnly`, `Secure`, `SameSite=Lax`, Laufzeit z. B. 12 h
- Rate Limit auf den Login (z. B. 5 Versuche/Minute/IP)

**Pro:** in einer Stunde gebaut, keine Abhängigkeiten, funktioniert auch wenn kein Mailversand läuft.
**Contra:** geteiltes Geheimnis – wandert in WhatsApp-Gruppen, kein Nachvollziehen wer was gemacht hat, Wechsel nur global.

### Variante B: Magic Link

Ablauf:
1. `/admin/login` → E-Mail eingeben
2. App prüft gegen **Allowlist** erlaubter Adressen (Env-Variable, z. B. 3–5 Orga-Leute). Nicht auf der Liste → trotzdem "Wenn die Adresse berechtigt ist, wurde eine Mail verschickt" anzeigen (kein Enumerieren).
3. Token: 32 Byte Zufall, URL-safe, **nur der Hash** in der DB, Gültigkeit 15 Minuten, einmalig verwendbar
4. Mail mit `https://…/admin/auth?token=…`
5. Klick → Token entwerten, Session-Cookie setzen (Laufzeit 30 Tage, damit man nicht ständig Mails braucht)

**Pro:** keine Passwörter zu verwalten, personenbezogen (Audit möglich), Zugang einfach entziehen.
**Contra:** braucht funktionierenden SMTP-Versand, Mails landen gern im Spam, ein Rechtsklick auf den Link und die Berechtigung ist weitergeleitet.

### Empfehlung

**Für dieses Projekt: Variante A.** Ein temporäres Event, eine Handvoll Leute, die Daten sind Namen und Funktionen – kein hohes Schutzniveau. Der Magic Link kostet dich SMTP-Konfiguration, Spam-Debugging und Token-Handling für einen Sicherheitsgewinn, der hier kaum ins Gewicht fällt.

Konkrete Absicherung, die mehr bringt als der Link-Mechanismus:
- Passwort nach dem Event einmal wechseln bzw. Instanz abschalten
- `/admin` zusätzlich im Reverse Proxy per IP-Allowlist oder Basic Auth schützen (zweite Schicht, zwei Zeilen nginx-Config)

Wenn du den Magic Link trotzdem willst: baue die Session-Schicht so, dass der Login-Mechanismus austauschbar ist. Dann sind es später ~80 Zeilen Nachrüstung statt Umbau.

---

## 5. Mailversand

Drei Mails, alle als schlichter Text (kein HTML, keine Bilder – kommt besser durch Filter). Sie werden nur erzeugt, **wenn eine E-Mail-Adresse hinterlegt ist**:

| Auslöser | Empfänger | Inhalt |
|---|---|---|
| Antrag eingegangen | Antragsteller | Bestätigung der eingegangenen Daten, Hinweis „wird geprüft", Ansprechpartner |
| Genehmigt | Antragsteller | Kategorie, wo/wann die Karte abzuholen ist |
| Abgelehnt | Antragsteller | Begründung aus dem Backoffice, Kontakt für Rückfragen |

### Anträge ohne Mailadresse

Die brauchen einen sichtbaren Weg, sonst gehen sie unter:

- Beim Absenden bekommt der Antragsteller den Hinweis, dass die Rückmeldung telefonisch erfolgt
- Im Backoffice werden diese Anträge markiert (Spalte „Kontakt: Telefon")
- Nach dem Genehmigen/Ablehnen landen sie in einer Filteransicht **„telefonisch zu informieren"**, mit Häkchen „erledigt" – so sieht die Orga auf einen Blick, wen sie noch anrufen muss

Optional: eine Sammelbenachrichtigung an die Orga („5 neue Anträge offen"), täglich per Cron statt bei jedem Antrag – sonst nervt es.

### Umsetzung

**Nicht direkt im Request versenden.** Wenn der SMTP hängt, hängt sonst das Formular. Stattdessen:

1. Mail beim Speichern in die Tabelle `mail_out` schreiben, Antwortseite sofort ausliefern
2. Ein Hintergrund-Task (Thread oder `APScheduler`, alle 30 s) holt unversendete Zeilen und schickt sie
3. Bei Fehler: `versuche++`, Backoff, nach 5 Versuchen aufgeben und im Backoffice als „Mail fehlgeschlagen" markieren
4. Fehlgeschlagene Mails im Backoffice manuell erneut anstoßen können

Das kostet vielleicht 40 Zeilen extra und erspart dir am Eventwochenende die Situation, dass niemand ein Formular abschicken kann, weil der Mailserver zickt.

### Zustellbarkeit

Der wunde Punkt bei selbst gehostetem Versand aus dem Container. Damit die Mails nicht im Spam landen, brauchst du für die Absenderdomain:

- **SPF**-Record, der den sendenden Host erlaubt
- **DKIM**-Signatur (z. B. via opendkim oder direkt im Postfix/msmtp-Setup)
- **DMARC**-Record, mindestens `p=none`
- gültiger **PTR/Reverse-DNS** auf die sendende IP
- Absender in der eigenen Domain, nicht `noreply@localhost`

Wenn Reverse-DNS oder eigene IP-Reputation nicht sauber sind: **Smarthost/Relay** benutzen (dein Provider-Postfach, oder ein Transaktionsdienst). Die App spricht dann einfach SMTP mit Auth gegen den Relay – Konfiguration bleibt identisch, nur andere Env-Werte:

```
SMTP_HOST=…
SMTP_PORT=587
SMTP_USER=…
SMTP_PASS=…
MAIL_FROM="Absolute Abfahrt <kennzeichen@deine-domain.de>"
MAIL_REPLY_TO=orga@deine-domain.de
```

Vor dem Livegang einmal an Gmail, GMX und Outlook testen – das sind die drei, bei denen es typischerweise klemmt.

---

## 6. Technik-Stack

Vorschlag: **Python + FastAPI + Jinja2 + SQLite**

- kein Build-Step, kein npm, ein `requirements.txt`
- serverseitig gerendertes HTML, kein JS-Framework nötig
- CSV-Export über `csv` aus der Standardbibliothek
- Alternativen, falls dir näher: Go (ein Binary, sehr angenehm zu deployen) oder Node + Express + better-sqlite3

Konfiguration ausschließlich über Env-Variablen:

```
APP_SECRET_KEY=…          # Session-Signatur
ADMIN_PASSWORD_HASH=…
DB_PATH=/var/lib/abfahrt/anträge.db
KATEGORIEN=campingplatz:Durchfahrt Campingplatz,vip_parkplatz:VIP-Parkplatz
BIND=127.0.0.1:8080
SMTP_HOST=… SMTP_PORT=587 SMTP_USER=… SMTP_PASS=…
MAIL_FROM=… MAIL_REPLY_TO=…
```

---

## 7. Betrieb hinter dem Reverse Proxy

Wichtig, damit die App nicht falsch abbiegt:

1. **Nur an localhost binden** – die App darf nicht direkt aus dem Netz erreichbar sein.
2. **`X-Forwarded-For` / `X-Forwarded-Proto` auswerten**, sonst stimmen IP-Logging und Redirect-URLs nicht. Bei uvicorn: `--proxy-headers --forwarded-allow-ips 127.0.0.1`.
3. **Cookie `Secure=True`** trotz HTTP im Backend – der Browser sieht ja HTTPS.
4. Proxy setzt: `proxy_set_header X-Forwarded-Proto $scheme;` und `X-Forwarded-For $proxy_add_x_forwarded_for;`
5. Body-Size-Limit und Rate Limit im Proxy.
6. systemd-Unit mit `Restart=always`, oder Docker-Container mit Volume für die DB.
7. Backup: nächtlicher `sqlite3 db ".backup"` per Cron, Datei wegkopieren.

---

## 8. Datenschutz

Es werden personenbezogene Daten erhoben – wenig, aber echt:
- Kurzer Hinweis unter dem Formular: wer erhebt, wozu, wie lange, wer ist Ansprechpartner
- Aufbewahrung: Löschung X Wochen nach der Veranstaltung, am besten als kleiner Cron-Job oder manueller Button im Backoffice
- IP-Adressen nur kurz speichern (7 Tage), oder ganz weglassen wenn Rate Limiting im Proxy passiert
- Keine Daten an Dritte, kein externes Tracking, keine CDN-Fonts

---

## 9. Umsetzungsschritte

| # | Schritt | Aufwand |
|---|---|---|
| 1 | Projektgerüst, Config über Env, SQLite-Schema | 1 h |
| 2 | Öffentliches Formular + Validierung + Bestätigungsseite | 2 h |
| 3 | Login (Passwort) + Session-Cookie | 1 h |
| 4 | Backoffice: Liste, Filter, Detailansicht, Löschen | 2 h |
| 5 | Redaktionelle Freigabe: genehmigen/ablehnen mit Begründung | 1,5 h |
| 6 | Mail-Queue + Versand-Worker + Vorlagen | 2 h |
| 7 | SPF/DKIM/DMARC einrichten, Zustellung testen | 1–2 h |
| 8 | CSV-Export | 0,5 h |
| 9 | Honeypot, Rate Limit, Datenschutzhinweis | 1 h |
| 10 | Deployment: systemd/Docker, Proxy-Config, Backup-Cron | 1–2 h |
| 11 | Optional: Druckansicht der Karten | 2 h |

Realistisch zwei bis drei Abende. Schritt 7 ist der mit dem größten Frustpotenzial – den früh anfangen, nicht am Ende.

---

## 10. Geklärt

- Kategorien: Durchfahrt Campingplatz und VIP-Parkplatz
- „Funktion" ist ein freies Textfeld
- Backoffice-Login per gemeinsamem Passwort
- Kontakt: E-Mail und Telefon beide optional, mindestens eines muss angegeben werden
- Bestätigungs- und Entscheidungsmail, wenn Adresse vorhanden; sonst telefonische Rückmeldung über Backoffice-Liste. SMTP kommt aus einem eigenen Linux-Container
- Redaktionelle Freigabe (genehmigen/ablehnen) im Backoffice

## 11. Offene Fragen

1. Gibt es feste Kontingente pro Kategorie?
2. Welche Absenderdomain wird für die Mails verwendet, und liegen SPF/DKIM/DMARC dafür schon an?
3. Soll das amtliche Kfz-Kennzeichen mit erfasst werden?
4. Text für die Genehmigungsmail: wo und wann werden die Karten übergeben?
5. Eigene Bearbeiter-Kürzel bei Entscheidungen erfassen, oder ist das overkill?
