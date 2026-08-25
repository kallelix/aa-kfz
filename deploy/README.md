# Deployment

Drei Anwendungen aus einem Repository, je ein **LXC-Container**
(Debian/Ubuntu), davor ein **nginx auf einem anderen Host** mit öffentlicher IP,
der HTTPS terminiert.

- Abschnitte 1 bis 6: **Kennzeichen-App** unter `kennzeichen.example.de`
- Abschnitt 7: **Presse-Akkreditierung** unter `presse.example.de`
- Abschnitt 8: **Helfer-Dashboard** unter `helfer.example.de`

Der Aufbau ist für alle drei gleich; die Abschnitte 7 und 8 nennen nur die
Unterschiede. Das Helfer-Dashboard hat davon die meisten – es ist die einzige
der drei, die **von sich aus nach draußen telefoniert** und einen Teil ihrer
Oberfläche **ohne Anmeldung** ausliefert.

```text
Internet ──HTTPS──▶ nginx (10.0.0.10)  ──HTTP──▶ LXC (10.0.0.42:8080)
                    Zertifikat              nur von 10.0.0.10 erreichbar
                    Rate Limit
```

Die beiden IPs sind Platzhalter. Sie kommen an drei Stellen vor und müssen
zusammenpassen:

| Wert | Wo eintragen |
| --- | --- |
| IP des Containers | `BIND` in der env, `upstream abfahrt` in der nginx-Config |
| IP des nginx | `FORWARDED_ALLOW_IPS` in der env, Firewall-Regel im Container |

`FORWARDED_ALLOW_IPS` falsch zu setzen ist der Fehler mit den unangenehmsten
Folgen: dann steht bei jedem Antrag die IP des nginx als Absender, und das
Login-Rate-Limit zählt alle Fehlversuche auf einen Topf – ein Tippfehler beim
Passwort sperrt die ganze Orga für eine Minute aus. Die App warnt beim Start,
wenn sie nicht auf localhost lauscht und der Wert trotzdem `127.0.0.1` ist.

---

## 1. Im Container

```bash
apt update
apt install -y python3 python3-venv sqlite3 git

adduser --system --group --no-create-home --home /nonexistent --shell /usr/sbin/nologin abfahrt

mkdir -p /var/lib/abfahrt /etc/abfahrt /var/backups/abfahrt
chown abfahrt:abfahrt /var/lib/abfahrt /var/backups/abfahrt
chmod 750 /var/lib/abfahrt /var/backups/abfahrt
```

**Dem Dienstbenutzer gehören nur diese beiden Verzeichnisse.** `/opt/abfahrt`
bleibt bei root: der Dienst liest seinen Code nur, und die systemd-Unit setzt
`ProtectSystem=strict`, macht `/opt` für ihn also ohnehin schreibgeschützt. Root
als Eigentümer ist zusätzlich sicherer, weil der Dienstbenutzer sein eigenes
Programm dann nicht verändern kann – und `git pull` als root funktioniert nur
so (siehe Abschnitt 6).

### Code und virtuelle Umgebung

```bash
git clone https://github.com/kallelix/aa-kfz.git /opt/abfahrt
cd /opt/abfahrt
python3 -m venv .venv
.venv/bin/pip install --no-cache-dir -r requirements.txt
```

Alles bleibt root:root mit den Standardrechten – `abfahrt` darf lesen und
ausführen, das genügt. **Kein `chown` auf `/opt/abfahrt`.**

`.venv/` und `data/` stehen in `.gitignore`, ein späteres `git pull` fasst sie
also nicht an. Die Datenbank liegt ohnehin unter `/var/lib/abfahrt`.

### Konfiguration

```bash
install -o root -g root -m 600 deploy/kennzeichen.env.example /etc/abfahrt/kennzeichen.env

# Passwort-Hash und Session-Schlüssel erzeugen und eintragen
/opt/abfahrt/.venv/bin/python -m app.passwort
/opt/abfahrt/.venv/bin/python -c "import secrets; print('APP_SECRET_KEY=' + secrets.token_urlsafe(32))"

editor /etc/abfahrt/kennzeichen.env
```

Mindestens setzen: `BIND`, `FORWARDED_ALLOW_IPS`, `ADMIN_PASSWORD_HASH`,
`APP_SECRET_KEY`, `SMTP_PASS`.

Die Datei gehört **root und ist 0600**. systemd liest sie, bevor es die Rechte
auf den Benutzer `abfahrt` fallen lässt – der Dienst selbst braucht keinen
Zugriff darauf.

### Dienst

```bash
install -m 644 deploy/kennzeichen.service /etc/systemd/system/kennzeichen.service
systemctl daemon-reload
systemctl enable --now kennzeichen
systemctl status kennzeichen
journalctl -u kennzeichen -f
```

Prüfen, dass wirklich nur der gewünschte Port offen ist:

```bash
ss -lntp
curl -sS -o /dev/null -w '%{http_code}\n' http://10.0.0.42:8080/
```

### Firewall

Der Port darf nur vom nginx erreichbar sein:

```bash
apt install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow from 10.0.0.10 to any port 8080 proto tcp
ufw allow from 10.0.0.0/24 to any port 22 proto tcp
ufw enable
```

**In unprivilegierten LXC-Containern funktioniert das oft nicht** – nftables und
iptables brauchen Rechte, die der Container nicht hat. Dann greift die
Beschränkung eine Ebene höher: Firewall des LXC-Hosts (bei Proxmox die
Container-Firewall in der GUI) oder ein Bridge-Netz, das ohnehin nur vom
nginx-Host erreichbar ist. Wichtig ist nur, dass `10.0.0.42:8080` aus dem
Internet nicht antwortet – das gehört auf die Prüfliste unten.

---

## 2. Auf dem nginx-Host

```bash
install -m 644 deploy/abfahrt-proxy.conf /etc/nginx/snippets/abfahrt-proxy.conf
install -m 644 deploy/nginx-kennzeichen.conf \
    /etc/nginx/sites-available/kennzeichen.example.de
ln -s ../sites-available/kennzeichen.example.de /etc/nginx/sites-enabled/

# IP des Containers in der Datei anpassen, dann:
nginx -t
```

### DNS und Zertifikat

1. A-Record (und ggf. AAAA) für `kennzeichen.example.de` auf die öffentliche IP
   des nginx
2. Zertifikat holen:

```bash
certbot --nginx -d kennzeichen.example.de
```

Falls schon ein Wildcard-Zertifikat für `*.example.de` vorliegt, stattdessen
dessen Pfade in der Config eintragen und certbot überspringen.

```bash
systemctl reload nginx
```

---

## 3. Sicherung

Das Skript liegt bereits im Klon und ist ausführbar. Es läuft als `abfahrt`,
liest die Datenbank und schreibt nach `/var/backups/abfahrt` – beides gehört
diesem Benutzer.

```bash
crontab -u abfahrt -e
```

```cron
15 3 * * * /opt/abfahrt/deploy/backup.sh >> /var/log/abfahrt-backup.log 2>&1
```

Das Skript nutzt `sqlite3 ".backup"` statt `cp`. Die Datenbank läuft im
WAL-Modus; ein blosses Kopieren der `.db` erwischt die noch nicht
eingearbeiteten Änderungen aus der `-wal`-Datei nicht. Anschliessend prüft es
die Kopie mit `PRAGMA integrity_check` – eine kaputte Sicherung fällt sonst erst
auf, wenn man sie braucht. Sicherungen älter als 30 Tage werden gelöscht.

**Der Dateiname folgt der Datenbank**: `antraege.db` wird zu
`antraege-2026-08-25.db`, `presse.db` zu `presse-2026-08-25.db`, `helfer.db` zu
`helfer-2026-08-25.db`. Bis zum Hinzukommen der dritten Anwendung hieß jede
Sicherung `antraege-`, auch die der Presse-App – drei gleich benannte Dateien
auseinanderzuhalten wäre genau dann schwierig geworden, wenn es eilt. Wer
schon einen Presse-Container betreibt, findet dort noch Dateien mit dem alten
Namen; das Skript räumt sie mit auf, sobald sie alt genug sind.

Einmal von Hand laufen lassen und nachsehen, dass eine Datei entsteht.

Und: einmal eine Rücksicherung geprobt haben, bevor es darauf ankommt.

---

## 4. Prüfliste vor dem Livegang

Vom eigenen Rechner aus, nicht vom Server:

```bash
# erreichbar und verschlüsselt
curl -sS -o /dev/null -w '%{http_code}\n' https://kennzeichen.example.de/

# HTTP leitet weiter
curl -sS -o /dev/null -w '%{http_code} %{redirect_url}\n' http://kennzeichen.example.de/

# Der Container ist NICHT direkt erreichbar (muss scheitern)
curl -sS --max-time 5 http://<oeffentliche-ip-des-containers>:8080/ || echo "gut so"

# Backoffice verlangt Anmeldung
curl -sS -o /dev/null -w '%{http_code}\n' https://kennzeichen.example.de/admin
```

Im Browser:

- [ ] Antrag absenden, Bestätigungsseite erscheint
- [ ] Antrag steht im Backoffice
- [ ] Anmeldung klappt, Abmelden klappt
- [ ] Cookie hat `Secure` und `HttpOnly` (Entwicklertools → Anwendung → Cookies)
- [ ] `journalctl -u kennzeichen` zeigt beim Antrag die **echte** Client-IP,
      nicht `10.0.0.10`
- [ ] Beim Start keine Warnung über `FORWARDED_ALLOW_IPS` oder fehlende
      Geheimnisse
- [ ] Eingangsmail kommt an – zuerst an eine eigene Adresse, dann an Gmail, GMX
      und Outlook (siehe Schritt 7 im Haupt-README)
- [ ] CSV-Export öffnet in Excel ohne Nachfrage und mit korrekten Umlauten

---

## 5. Aktualisieren

```bash
# 1. Sichern, bevor irgendetwas angefasst wird
/opt/abfahrt/deploy/backup.sh

# 2. Stand holen
cd /opt/abfahrt
git pull

# 3. Abhängigkeiten nachziehen (schadet nie, dauert ohne Änderung Sekunden)
.venv/bin/pip install --no-cache-dir -r requirements.txt

# 4. Neu starten und nachsehen
systemctl restart kennzeichen
systemctl status kennzeichen --no-pager
journalctl -u kennzeichen -n 30 --no-pager
```

Dieselben vier Schritte gelten in jedem der drei Container, nur mit dem
jeweiligen Dienstnamen: `kennzeichen`, `presse` oder `helfer`. Jeder Container
hat seinen eigenen Klon von `/opt/abfahrt` und wird einzeln aktualisiert – ein
`git pull` im einen ändert am anderen nichts.

Im Protokoll gehören nach dem Start keine Warnungen zu `FORWARDED_ALLOW_IPS`,
`APP_SECRET_KEY` oder `ADMIN_PASSWORD_HASH` zu sehen. Im Helfer-Container
zusätzlich keine zu `JETZT_FEST`. Steht dort eine Zeile
`Datenbank ergaenzt: …`, hat die App ein Schema-Update selbst erledigt – das ist
normal und gewollt.

Danach einmal im Browser: Formular lädt, Backoffice lädt, ein Antrag lässt sich
öffnen.

### Schema-Änderungen

Die App zieht fehlende Spalten und geänderte Tabellen beim Start selbst nach und
schreibt es ins Protokoll. Ein Datenbankumbau (etwa als `mail_out.typ` um den
Typ `orga` erweitert wurde) läuft in einer Transaktion: entweder ganz oder gar
nicht. Trotzdem gilt Schritt 1 – eine Sicherung kostet zwei Sekunden.

### Wenn das Update schiefgeht

```bash
# Auf den vorherigen Stand zurück
cd /opt/abfahrt
git log --oneline -5          # Commit von vorher heraussuchen
git checkout <commit>
.venv/bin/pip install --no-cache-dir -r requirements.txt
systemctl restart kennzeichen
```

Zurück auf die aktuelle Spitze geht es mit `git checkout main`.

Ist die **Datenbank** das Problem, hilft der Code-Rollback allein nicht – dann
die Sicherung aus Schritt 1 zurückspielen:

```bash
systemctl stop kennzeichen
cp /var/backups/abfahrt/antraege-JJJJ-MM-TT.db /var/lib/abfahrt/antraege.db
rm -f /var/lib/abfahrt/antraege.db-wal /var/lib/abfahrt/antraege.db-shm
chown abfahrt:abfahrt /var/lib/abfahrt/antraege.db
systemctl start kennzeichen
```

Die beiden `-wal`- und `-shm`-Dateien müssen weg: sie gehören zur alten
Datenbank und passen nicht zur zurückgespielten.

### Lokale Änderungen am Server

Wenn jemand direkt auf dem Server etwas editiert hat, bricht `git pull` ab. Was
lokal abweicht, zeigt `git status`. Entweder verwerfen (`git checkout -- <datei>`)
oder vorher sichern. Die Konfiguration ist davon nicht betroffen – die liegt in
`/etc/abfahrt/kennzeichen.env` und damit außerhalb des Repos.

---

## 6. Wenn etwas klemmt

| Symptom | Ursache, die es meistens ist |
| --- | --- |
| `git pull` sagt „detected dubious ownership" | `/opt/abfahrt` gehört nicht root. Frühere Fassungen dieser Anleitung haben es fälschlich auf `abfahrt` gesetzt. Richtigstellen mit `chown -R root:root /opt/abfahrt` – der Dienst braucht dort keine Schreibrechte. `git config --global --add safe.directory` behebt zwar die Meldung, lässt aber den Dienstbenutzer weiter seinen eigenen Code beschreiben. |
| Anmeldung wirft einen zurück auf die Anmeldeseite | Cookie mit `Secure`, aber die Verbindung kam als HTTP an. `X-Forwarded-Proto` fehlt im Proxy. |
| Alle Anträge haben dieselbe IP | `FORWARDED_ALLOW_IPS` zeigt nicht auf den nginx. |
| Ein Fehlversuch sperrt alle aus | dasselbe. |
| 502 vom nginx | Dienst läuft nicht oder Firewall blockt. `systemctl status kennzeichen`, dann vom nginx-Host `curl http://10.0.0.42:8080/`. |
| Mails bleiben liegen | `SMTP_HOST`/`MAIL_FROM` fehlen, oder Zugangsdaten stimmen nicht. Der Fehler steht in der Detailansicht des Antrags und im Journal. |
| 429 beim Absenden | Rate Limit im nginx. Bei geteilten NAT-Adressen `rate=` in der Config hochsetzen. |
| Monitor zeigt dauerhaft die orange „Keine Verbindung"-Leiste, obwohl die Seite lädt | `connect-src 'self'` fehlt in der Content-Security-Policy. Die Seite selbst kommt durch, ihre Nachladeanfragen nicht. In der Browserkonsole steht die geblockte Anfrage. Siehe `nginx-helfer.conf`. |
| Zeitplan-Abruf schlägt immer fehl | Der Container kommt nicht nach draußen (Egress auf 443 und DNS), oder `ca-certificates` fehlt. Der genaue Text steht im Backoffice unter *Einstellungen › Zeitplan-Abruf* bei den bisherigen Abrufen. |
| Monitor zeigt eine Uhrzeit, die nicht stimmt | Entweder steht `JETZT_FEST` noch gesetzt (Warnung im Journal), oder die Containeruhr geht falsch – `timedatectl`. Die Uhr auf dem Bildschirm kommt vom Server, nicht vom Bildschirmrechner. |
| Monitor zeigt nichts, obwohl Schichten erfasst sind | `TAGE` oder die Daten in den CSV-Dateien liegen in einem anderen Jahr als die Containeruhr. Im Backoffice unter *Schichten* steht, für welche Tage etwas erfasst ist. |

---

## 7. Zweite Anwendung: Presse-Akkreditierung

Eigener LXC-Container, eigene Adresse, eigene Datenbank – aber **dasselbe
Repository**. Der Klon liegt auch dort unter `/opt/abfahrt`, der Dienst läuft
aus dem Unterverzeichnis `presse/`.

```text
Internet ──HTTPS──▶ nginx (10.0.0.10) ──┬─▶ LXC kfz    (10.0.0.42:8080)
                                        └─▶ LXC presse (10.0.0.43:8081)
```

Ein `git pull` je Container aktualisiert die jeweilige App; der gemeinsame Code
bleibt automatisch in Sicht. Die Pfade sind absichtlich in beiden Containern
gleich – nur `WorkingDirectory` unterscheidet sich.

### Im Presse-Container

```bash
apt update
apt install -y python3 python3-venv sqlite3 git

adduser --system --group --no-create-home --home /nonexistent --shell /usr/sbin/nologin presse

mkdir -p /var/lib/presse /etc/abfahrt /var/backups/presse
chown presse:presse /var/lib/presse /var/backups/presse
chmod 750 /var/lib/presse /var/backups/presse

git clone https://github.com/kallelix/aa-kfz.git /opt/abfahrt
cd /opt/abfahrt
python3 -m venv .venv
.venv/bin/pip install --no-cache-dir -r requirements.txt
```

`/opt/abfahrt` bleibt **root:root** – der Dienst liest seinen Code nur. Siehe
Abschnitt 1, die Begründung gilt hier genauso.

Die `requirements.txt` im Wurzelverzeichnis deckt beide Anwendungen ab; `segno`
braucht nur die Kennzeichen-App und stört hier nicht.

### Konfiguration

```bash
install -o root -g root -m 600 deploy/presse.env.example /etc/abfahrt/presse.env

cd /opt/abfahrt/presse
/opt/abfahrt/.venv/bin/python -m app.passwort
/opt/abfahrt/.venv/bin/python -c "import secrets; print('APP_SECRET_KEY=' + secrets.token_urlsafe(32))"

editor /etc/abfahrt/presse.env
```

Mindestens setzen: `BIND`, `FORWARDED_ALLOW_IPS`, `ADMIN_PASSWORD_HASH`,
`APP_SECRET_KEY`, `SMTP_PASS`, `KONTAKT_MAIL`.

**Eigenes Passwort.** Beide Anwendungen haben getrennte Anmeldungen – eigene
Adresse heißt eigene Cookie-Domain, ein gemeinsames Passwort brächte also
nichts als ein zweites Geheimnis mit demselben Wert.

### Dienst

```bash
install -m 644 deploy/presse.service /etc/systemd/system/presse.service
systemctl daemon-reload
systemctl enable --now presse
systemctl status presse
journalctl -u presse -f
```

### Firewall

Wie in Abschnitt 1, nur mit dem anderen Port:

```bash
ufw default deny incoming
ufw allow from 10.0.0.10 to any port 8081 proto tcp
ufw allow from 10.0.0.0/24 to any port 22 proto tcp
ufw enable
```

### Auf dem nginx-Host

```bash
install -m 644 deploy/presse-proxy.conf /etc/nginx/snippets/presse-proxy.conf
install -m 644 deploy/nginx-presse.conf /etc/nginx/sites-available/presse.example.de
ln -s ../sites-available/presse.example.de /etc/nginx/sites-enabled/

# Adresse und Container-IP in der Datei anpassen, dann:
nginx -t
certbot --nginx -d presse.example.de
systemctl reload nginx
```

Die Rate-Limit-Zonen und der `map`-Block heißen **anders** als in
`nginx-kennzeichen.conf`. Gleiche Namen zweimal zu definieren ist ein
Konfigurationsfehler, und `nginx -t` sagt das erst beim Einbinden.

### Sicherung

`backup.sh` ist nicht auf eine Datenbank festgelegt – Pfade kommen aus der
Umgebung. Im Presse-Container:

```bash
crontab -u presse -e
```

```cron
15 3 * * * DB_PATH=/var/lib/presse/presse.db BACKUP_DIR=/var/backups/presse /opt/abfahrt/deploy/backup.sh >> /var/log/presse-backup.log 2>&1
```

### Prüfliste

Wie in Abschnitt 4, zusätzlich:

- [ ] Anmeldung absenden, Bestätigungsmail kommt an – einmal je Variante
      (Gebühr, Bilderspende, nicht kommerziell)
- [ ] Die Mail nennt den richtigen Betrag und den richtigen Abholort
- [ ] Abholliste: Suche filtert beim Tippen, Badge- und Gebühren-Häkchen wirken
- [ ] `BILDER_ABGABE` gesetzt – sonst nennt die Erinnerungsmail keinen Weg
- [ ] `BADGES_GESAMT` auf die Zahl der vorproduzierten Badges gesetzt

---

## 8. Dritte Anwendung: Helfer-Dashboard

Eigener LXC-Container, eigene Adresse, eigene Datenbank – wieder **dasselbe
Repository**, Dienst aus dem Unterverzeichnis `helfer/`.

```text
Internet ──HTTPS──▶ nginx (10.0.0.10) ──┬─▶ LXC kfz    (10.0.0.42:8080)
                                        ├─▶ LXC presse (10.0.0.43:8081)
                                        └─▶ LXC helfer (10.0.0.44:8082)
                                                  │
                                                  └──HTTPS──▶ ixsdownhillcup.com
                                                              kidscup.bike
```

**Drei Unterschiede zu den Schwester-Apps.** Sie stehen hier vorn, weil jeder
von ihnen erst im Betrieb auffällt, wenn man ihn beim Aufsetzen übersieht:

1. **Ausgehende Verbindungen.** Der Dienst holt einmal täglich den Zeitplan
   von den Websites der Rennserien. Der Container braucht dafür Egress auf
   Port 443 und `ca-certificates`. Fehlt eines von beidem, bleibt der letzte
   erfolgreiche Stand stehen und das Backoffice zeigt den Fehler – der Dienst
   läuft weiter, aber der Zeitplan veraltet still.
2. **Ein Teil ist öffentlich.** Die Monitoransicht läuft ohne Anmeldung,
   geschützt nur durch einen langen Token im Pfad. Der optionale
   Basic-Auth-Riegel vor `/admin` darf **nicht** auf `/monitor/` ausgedehnt
   werden – der Bildschirm im Zelt kann kein Passwort eingeben.
3. **Die Content-Security-Policy braucht `connect-src 'self'`.** Die
   Monitoransicht holt sich ihren Inhalt per `fetch` selbst, das
   Unterschriften-Tablet ebenso. Ohne die Direktive fällt das auf
   `default-src 'none'` zurück und wird geblockt: der Monitor bliebe stumm auf
   dem ersten Stand stehen, und das Tablet bekäme nie mit, dass etwas
   ansteht. `nginx-helfer.conf` hat sie als einzige der drei.

Kein Mailversand – es gibt keine SMTP-Werte zu setzen.

### Im Helfer-Container

```bash
apt update
apt install -y python3 python3-venv sqlite3 git ca-certificates

# Die Uhr des Containers erscheint auf dem Monitor. Sie sollte stimmen.
timedatectl set-timezone Europe/Berlin
timedatectl set-ntp true

adduser --system --group --no-create-home --home /nonexistent --shell /usr/sbin/nologin helfer

mkdir -p /var/lib/helfer /etc/abfahrt /var/backups/helfer
chown helfer:helfer /var/lib/helfer /var/backups/helfer
chmod 750 /var/lib/helfer /var/backups/helfer

git clone https://github.com/kallelix/aa-kfz.git /opt/abfahrt
cd /opt/abfahrt
python3 -m venv .venv
.venv/bin/pip install --no-cache-dir -r requirements.txt
```

`/opt/abfahrt` bleibt **root:root** – die Begründung aus Abschnitt 1 gilt
unverändert.

`ca-certificates` ist neu gegenüber den anderen beiden Containern: ohne die
Wurzelzertifikate scheitert der Zeitplan-Abruf an der TLS-Prüfung. Der Fehler
liest sich dann wie ein Netzproblem, ist aber keines.

Die `requirements.txt` deckt alle drei Anwendungen ab. Neu darin ist `tzdata` –
damit verhält sich die Zeitzone überall gleich, unabhängig davon, was das
Betriebssystem mitbringt.

### Konfiguration

```bash
install -o root -g root -m 600 deploy/helfer.env.example /etc/abfahrt/helfer.env

cd /opt/abfahrt/helfer
/opt/abfahrt/.venv/bin/python -m app.passwort
/opt/abfahrt/.venv/bin/python -c "import secrets; print('APP_SECRET_KEY=' + secrets.token_urlsafe(32))"

editor /etc/abfahrt/helfer.env
```

Mindestens setzen: `BIND`, `FORWARDED_ALLOW_IPS`, `ADMIN_PASSWORD_HASH`,
`APP_SECRET_KEY`, `BASIS_URL`, `TAGE`.

**`JETZT_FEST` muss leer sein.** Die Variable stellt die Uhr auf einen festen
Zeitpunkt, damit sich die Monitoransicht außerhalb der Veranstaltung anschauen
lässt. Bleibt sie im Betrieb gesetzt, zeigt der Monitor eine erfundene Uhrzeit
– und niemandem fällt es auf, weil ja eine Uhr zu sehen ist. Der Dienst
schreibt beim Start eine Warnung ins Journal:

```bash
journalctl -u helfer | grep JETZT_FEST
```

**`TAGE` sind die drei Renntage.** Der Zeitplan-Abruf bildet damit die
Wochentage aus den Tabellen der Rennserien auf Daten ab. Steht dort das falsche
Jahr, landet das gesamte Programm auf falschen Tagen und der Monitor zeigt
dauerhaft nichts an.

### Dienst

```bash
install -m 644 deploy/helfer.service /etc/systemd/system/helfer.service
systemctl daemon-reload
systemctl enable --now helfer
systemctl status helfer
journalctl -u helfer -f
```

### Firewall

Wie in Abschnitt 1, mit dem dritten Port – **und mit Egress**, den die anderen
beiden Container nicht brauchen:

```bash
ufw default deny incoming
ufw default allow outgoing          # fuer den Zeitplan-Abruf
ufw allow from 10.0.0.10 to any port 8082 proto tcp
ufw allow from 10.0.0.0/24 to any port 22 proto tcp
ufw enable
```

Wer den ausgehenden Verkehr enger fassen will, braucht DNS und HTTPS:

```bash
ufw default deny outgoing
ufw allow out 53
ufw allow out 443/tcp
```

Auf feste Ziel-IPs sollte man es nicht einengen – beide Serien-Websites liegen
hinter Adressen, die sich ohne Ankündigung ändern.

### Auf dem nginx-Host

```bash
install -m 644 deploy/helfer-proxy.conf /etc/nginx/snippets/helfer-proxy.conf
install -m 644 deploy/nginx-helfer.conf /etc/nginx/sites-available/helfer.example.de
ln -s ../sites-available/helfer.example.de /etc/nginx/sites-enabled/

# Adresse und Container-IP in der Datei anpassen, dann:
nginx -t
certbot --nginx -d helfer.example.de
systemctl reload nginx
```

Die Rate-Limit-Zone und der `map`-Block heißen wieder **anders** als in den
beiden anderen Dateien. `client_max_body_size` steht hier auf 2 MB, weil über
das Backoffice zwei CSV-Dateien hochgeladen werden.

### Erste Inbetriebnahme

Anders als die Schwester-Apps startet diese nicht leer und wartet auf Anträge –
sie braucht erst ihren Datenbestand:

1. **Die beiden Listen** aus dem bisherigen Registrierungstool holen –
   *Offene Posten* und *Vergebene Posten*. Zwei Wege, siehe unten: abrufen
   oder hochladen. Einzeln geht keiner von beiden: eine Zeile ist ein Platz,
   nicht eine Schicht – eine voll besetzte Schicht steht nur in *Vergebene*,
   eine leere nur in *Offene*. Erst beide zusammen ergeben den richtigen
   Bedarf.
2. Den Bericht durchsehen. Übersprungene Zeilen sind **nicht** in der
   Datenbank gelandet, die Hinweise darunter schon – dort stehen
   Mehrfachbelegungen und uneindeutige Angaben, die jemand anschauen sollte.
3. Unter **Einstellungen › Zeitplan-Abruf** einmal *Jetzt abrufen* drücken.
   Ab dann läuft der Abruf täglich von selbst.
4. Unter **Einstellungen › Monitor** den Link erzeugen und auf den
   Bildschirmrechner übertragen.

Der Import lässt sich beliebig wiederholen: er rechnet den Bedarf neu aus und
ersetzt nur seine eigenen Einteilungen. Was im Dashboard von Hand eingetragen
wurde, bleibt stehen.

#### Abrufen statt hochladen

Stehen die drei Adressen in der Konfiguration, holt sich der Import beide
Listen selbst – ein Knopf unter **Einstellungen › Import** statt Herunterladen
und Hochladen:

```
IMPORT_LOGIN_URL=https://www.helferliste.online/home.php?i=…
IMPORT_URL_VERGEBEN=https://www.helferliste.online/helfer.php?vid=…&t=…&download_csv=1
IMPORT_URL_OFFEN=https://www.helferliste.online/helfer.php?vid=…&t=…&download_csv=2
```

Der Login-Link ist nötig, weil der Token in den beiden CSV-Adressen allein
nicht genügt: ohne Sitzung antwortet der Dienst mit **HTTP 200 und der
Anmeldeseite** statt mit der Datei. Der Abruf meldet sich deshalb jedes Mal
neu an – der Link ist mehrfach verwendbar. Anzufordern ist er beim Dienst
unter *„Ich benötige einen Login-Link“*. Kommt die Anmeldeseite trotzdem,
sagt das die Fehlermeldung im Backoffice; dann ist ein neuer Link fällig.

> **Alle drei Adressen sind Geheimnisse.** Der Login-Link ist der Sache nach
> ein Passwort: wer ihn hat, sieht die ganze Helferliste samt Adressen und
> Telefonnummern. Sie gehören nur in die `.env` (Rechte `600`, dem
> Dienstbenutzer gehörend), nie ins Repository und nie in eine Fehlermeldung
> nach außen. Die Anwendung schreibt sie deshalb weder in eine Meldung noch
> in den Importvermerk – dort steht nur „Helferliste (Abruf)“, nicht der
> Dateiname des Dienstes, der den Token enthält.

Ohne die drei Adressen bleibt es beim Hochladen der beiden Dateien; die
Importseite sagt dann, was fehlt.

### Der Monitor-Link

Er steht in der Datenbank, nicht in der Konfiguration – ein Neustart ändert ihn
also nicht, ein neuer `APP_SECRET_KEY` auch nicht. Wer ihn hat, sieht die
Einteilung samt Namen. Also auf den Bildschirmrechner geben, nicht in einen
offenen Verteiler.

Verliert er sich oder war er an der falschen Stelle, im Backoffice unter
**Monitor** einen neuen erzeugen – der alte gilt sofort nicht mehr.

Auf dem Bildschirmrechner: Browser im Vollbild (F11), Bildschirmschoner und
Energiesparen aus. Die Seite hält sich selbst aktuell und braucht kein F5.

### Sicherung

Wie in Abschnitt 7, mit den Pfaden dieses Containers:

```bash
crontab -u helfer -e
```

```cron
15 3 * * * DB_PATH=/var/lib/helfer/helfer.db BACKUP_DIR=/var/backups/helfer /opt/abfahrt/deploy/backup.sh >> /var/log/helfer-backup.log 2>&1
```

Diese Datenbank ist die einzige der drei, die sich **nicht** aus den Anträgen
der Leute wiederherstellen lässt: Schichten und Helfer kommen zwar aus den
CSV-Dateien, jede Einteilung von Hand aber nur von hier. Vor der Veranstaltung
lohnt sich ein zweiter Zeitpunkt am Abend.

### Prüfliste

Wie in Abschnitt 4, zusätzlich:

- [ ] `JETZT_FEST` ist leer, im Journal steht keine Warnung dazu
- [ ] `TAGE` nennt die richtigen drei Renntage im richtigen Jahr
- [ ] Uhr des Containers geht richtig (`timedatectl`) – sie steht auf dem
      Monitor
- [ ] Import beider Listen gelaufen (Abruf oder Hochladen), Bericht durchgesehen
- [ ] Zeitplan-Abruf einmal von Hand ausgelöst, beide Serien melden Erfolg
- [ ] Der Abruf hat die **allgemeine** DHC-Tabelle erwischt, nicht die von
      Willingen – im Bericht steht, unter welcher Überschrift er gelesen hat
- [ ] Monitor-Link erzeugt, auf dem Bildschirmrechner geöffnet
- [ ] Am Monitor: Schicht antippen öffnet die Namensliste, ein Tag in der
      Leiste öffnet den Tagesblick, beide kehren von selbst zurück
- [ ] Netzstecker am Bildschirmrechner kurz gezogen: der letzte Stand bleibt
      stehen und die orange Leiste erscheint. Das ist zugleich die Probe
      darauf, dass `connect-src 'self'` sitzt – fehlt die Direktive, erscheint
      die Leiste sofort und dauerhaft
- [ ] `/monitor/<token>` ist **ohne** Anmeldung erreichbar, `/admin` nicht
- [ ] Ein falscher Token gibt 404
- [ ] Falls Unterschriften genutzt werden: Tablet-Link erzeugt, auf dem Tablet
      im Vollbild geöffnet, Bildschirmsperre aus. Eine Übergabe probeweise
      anfordern und unterschreiben
- [ ] Der Tablet-Link ist ein **anderer** als der des Monitors – die eine
      Adresse nimmt Eingaben entgegen, die andere nicht

---

## 9. Timetable ablösen

Das Helfer-Dashboard ersetzt das bisherige `timetable`-Projekt vollständig.
**Aus dessen Datenbank muss nichts übernommen werden** – der Aufgabenplan wird
neu gepflegt, das Programm kommt aus dem Zeitplan-Abruf, Schichten und Helfer
aus den beiden CSV-Dateien.

Erst abschalten, wenn die Prüfliste aus Abschnitt 8 abgehakt ist:

- [ ] Dienst des alten Projekts stoppen und aus dem Autostart nehmen
- [ ] Dessen nginx-Block entfernen oder auf die neue Adresse umleiten
- [ ] Eine letzte Sicherung der alten Datenbank wegheften und aufbewahren, bis
      die Veranstaltung vorbei ist
- [ ] Allen, die den alten Link gespeichert haben, die neue Adresse geben

Die konkreten Pfade und Dienstnamen stehen hier bewusst nicht: das alte Projekt
läuft nicht in diesem Aufbau, und geraten wäre schlimmer als nachgeschaut.
