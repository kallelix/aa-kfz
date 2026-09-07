# Deployment

**Eine Anwendung, ein Dienst, ein Container.** Darin laufen die drei Programme
– Kennzeichen, Presse, Helfer – in einem Prozess; welcher antwortet,
entscheidet der Hostname.

Ein **LXC-Container** (Debian/Ubuntu), davor ein **nginx auf einem anderen
Host** mit öffentlicher IP, der HTTPS terminiert.

```text
Internet ──HTTPS──▶ nginx (10.0.0.10) ──HTTP──▶ LXC (10.0.0.42:8080)
                    Zertifikate                 nur von 10.0.0.10 erreichbar
                    Rate Limit                         │
                                                       └──HTTPS──▶ ixsdownhillcup.com
                                                                   kidscup.bike
                                                                   helferliste.online
```

Vier Adressen zeigen auf denselben Dienst:

| Adresse | was dort liegt |
| --- | --- |
| `kennzeichen.example.de` | Antragsformular, öffentlich |
| `presse.example.de` | Akkreditierung, öffentlich |
| `helfer.example.de` | Monitor und Unterschriften-Tablet, per Token |
| `admin.example.de` | **alle drei Backoffices**, eine Anmeldung |

Die öffentlichen Adressen stehen auf Plakaten, in Mails und in QR-Codes –
deshalb wird nach Hostname verteilt und nicht nach Pfad. Das Backoffice liegt
umgekehrt unter einer Adresse, weil dieselben paar Leute alle drei betreuen:
`admin.example.de/kennzeichen/…`, `/presse/…`, `/helfer/…`.

Die beiden IPs oben sind Platzhalter. Sie kommen an drei Stellen vor und
müssen zusammenpassen:

| Wert | Wo eintragen |
| --- | --- |
| IP des Containers | `BIND` in `dienst.env`, `upstream abfahrt` in der nginx-Config |
| IP des nginx | `FORWARDED_ALLOW_IPS` in `dienst.env`, Firewall-Regel im Container |

`FORWARDED_ALLOW_IPS` falsch zu setzen ist der Fehler mit den unangenehmsten
Folgen: dann steht bei jedem Antrag die IP des nginx als Absender, und das
Login-Rate-Limit zählt alle Fehlversuche auf einen Topf – ein Tippfehler beim
Passwort sperrt die ganze Orga für eine Minute aus.

**Drei Dinge, die nur wegen des Helfer-Teils gelten** und die erst im Betrieb
auffallen, wenn man sie beim Aufsetzen übersieht:

1. **Ausgehende Verbindungen.** Der Dienst holt den Zeitplan von den Websites
   der Rennserien und die Helferlisten beim Registrierungstool. Der Container
   braucht Egress auf Port 443 und `ca-certificates`. Fehlt eines von beidem,
   bleibt der letzte Stand stehen und das Backoffice zeigt den Fehler.
2. **Ein Teil ist öffentlich.** Monitor und Tablet laufen ohne Anmeldung,
   geschützt nur durch einen langen Token im Pfad. Der optionale
   Basic-Auth-Riegel vor dem Backoffice darf **nicht** auf
   `helfer.example.de` ausgedehnt werden – der Bildschirm im Zelt kann kein
   Passwort eingeben.
3. **Die Content-Security-Policy braucht `connect-src 'self'`.** Monitor und
   Tablet holen sich ihren Inhalt per `fetch`. Ohne die Direktive fällt das
   auf `default-src 'none'` zurück und wird geblockt: der Monitor bliebe
   stumm auf dem ersten Stand stehen, und das Tablet bekäme nie mit, dass
   etwas ansteht.

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

Vier Dateien: eine gemeinsame und je Anwendung eine.

```bash
install -o root -g root -m 600 deploy/dienst.env.example      /etc/abfahrt/dienst.env
install -o root -g root -m 600 deploy/kennzeichen.env.example /etc/abfahrt/kennzeichen.env
install -o root -g root -m 600 deploy/presse.env.example      /etc/abfahrt/presse.env
install -o root -g root -m 600 deploy/helfer.env.example      /etc/abfahrt/helfer.env

# Passwort-Hash und Session-Schluessel - EINMAL, sie gelten fuer alle drei
/opt/abfahrt/.venv/bin/python -m kern.passwort
/opt/abfahrt/.venv/bin/python -c "import secrets; print('APP_SECRET_KEY=' + secrets.token_urlsafe(32))"

editor /etc/abfahrt/dienst.env
```

In **`dienst.env`** steht, was für alle gilt: `BIND`,
`FORWARDED_ALLOW_IPS`, die vier `HOST_…`, `ADMIN_PASSWORD_HASH`,
`APP_SECRET_KEY` und die drei Zeiger `KENNZEICHEN_ENV`, `PRESSE_ENV`,
`HELFER_ENV`.

In den **drei anderen** steht, was sich unterscheidet – vor allem `DB_PATH`,
dazu `BASIS_URL`, die Mailkonfiguration (Kennzeichen und Presse) und beim
Helfer der Abruf der Helferliste.

> `ADMIN_PASSWORD_HASH` und `APP_SECRET_KEY` gehören **nur** in `dienst.env`.
> Die Umgebung schlägt die Datei, also gälten sie ohnehin für alle drei –
> aber genau daran hängt, dass eine Anmeldung alle drei Bereiche öffnet.
> Stünden dort verschiedene Schlüssel, läge zwar ein Keks im Browser, seine
> Unterschrift passte im nächsten Bereich aber nicht.

Alle vier gehören **root und sind 0600**. systemd liest `dienst.env`, bevor
es die Rechte auf den Benutzer `abfahrt` fallen lässt; die drei anderen liest
der Dienst selbst – deshalb müssen sie für ihn lesbar sein:

```bash
chgrp abfahrt /etc/abfahrt/kennzeichen.env /etc/abfahrt/presse.env /etc/abfahrt/helfer.env
chmod 640     /etc/abfahrt/kennzeichen.env /etc/abfahrt/presse.env /etc/abfahrt/helfer.env
```

### Dienst

```bash
install -m 644 deploy/dienst.service /etc/systemd/system/abfahrt.service
systemctl daemon-reload
systemctl enable --now abfahrt
systemctl status abfahrt
journalctl -u abfahrt -f
```

Im Protokoll muss **dreimal `starte Bereich …`** stehen – Kennzeichen,
Presse, Helfer. Fehlt einer, hat seine `.env` oder sein `DB_PATH` nicht
gepasst. Die Datenbanken legt der Dienst beim ersten Start selbst an.

Prüfen, dass wirklich nur der gewünschte Port offen ist:

```bash
ss -lntp
curl -sS -o /dev/null -w '%{http_code}
' -H 'Host: kennzeichen.example.de'      http://10.0.0.42:8080/
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
install -m 644 deploy/dienst-proxy.conf /etc/nginx/snippets/abfahrt-dienst-proxy.conf
install -m 644 deploy/nginx-dienst.conf /etc/nginx/sites-available/abfahrt
ln -s ../sites-available/abfahrt /etc/nginx/sites-enabled/

# Die vier Adressen und die IP des Containers in der Datei anpassen, dann:
nginx -t
```

Eine Datei für alle vier Adressen. Der Proxy-Schnipsel reicht `Host` durch –
**daran** entscheidet der Dienst, welcher Bereich antwortet. Ohne die Zeile
bekäme er den Namen des Upstreams zu sehen und fände gar keinen.

### DNS und Zertifikate

1. A-Record (und ggf. AAAA) für alle vier Namen auf die öffentliche IP des
   nginx: `kennzeichen`, `presse`, `helfer`, `admin`.
2. Zertifikate holen – zwei Server-Blöcke, also zwei Zertifikate:

```bash
certbot --nginx -d kennzeichen.example.de -d presse.example.de -d helfer.example.de
certbot --nginx -d admin.example.de
```

Falls schon ein Wildcard-Zertifikat für `*.example.de` vorliegt, stattdessen
dessen Pfade in der Config eintragen und certbot überspringen – dann genügt
eines für alle vier.

```bash
systemctl reload nginx
```

---

## 3. Sicherung

Ein Lauf für alle drei Datenbanken. Ohne `DB_PATH` sichert das Skript
**jede** `.db` in `/var/lib/abfahrt` – vorher waren das drei Cron-Einträge in
drei Containern.

```bash
crontab -u abfahrt -e
```

```cron
15 3 * * * /opt/abfahrt/deploy/backup.sh >> /var/log/abfahrt-backup.log 2>&1
```

Das Skript nutzt `sqlite3 ".backup"` statt `cp`. Die Datenbanken laufen im
WAL-Modus; ein blosses Kopieren der `.db` erwischt die noch nicht
eingearbeiteten Änderungen aus der `-wal`-Datei nicht. Anschliessend prüft es
jede Kopie mit `PRAGMA integrity_check` – eine kaputte Sicherung fällt sonst
erst auf, wenn man sie braucht. Sicherungen älter als 30 Tage werden gelöscht.

> Die Sicherungen enthalten Personendaten. Nach der Veranstaltung gehören sie
> mit gelöscht, siehe Abschnitt 7 – sonst war der Löschlauf auf der Datenbank
> umsonst.

---

## 4. Prüfliste vor dem Livegang

Vom eigenen Rechner aus, nicht vom Server:

```bash
# Alle vier erreichbar und verschluesselt
for n in kennzeichen presse helfer admin; do
    printf '%-12s ' "$n"
    curl -sS -o /dev/null -w '%{http_code}
' "https://$n.example.de/"
done

# HTTP leitet weiter
curl -sS -o /dev/null -w '%{http_code} %{redirect_url}
' http://kennzeichen.example.de/

# Der Container ist NICHT direkt erreichbar (muss scheitern)
curl -sS --max-time 5 http://<oeffentliche-ip-des-containers>:8080/ || echo "gut so"

# Backoffice verlangt Anmeldung
curl -sS -o /dev/null -w '%{http_code}
' https://admin.example.de/helfer

# Das Backoffice liegt NICHT auf den oeffentlichen Adressen (muss 404 sein)
curl -sS -o /dev/null -w '%{http_code}
' https://kennzeichen.example.de/kennzeichen
```

Im Browser:

- [ ] `journalctl -u abfahrt` zeigt beim Start **dreimal** `starte Bereich …`
- [ ] Antrag absenden, Bestätigungsseite erscheint
- [ ] Presse-Anmeldung absenden, Bestätigungsseite erscheint
- [ ] `admin.example.de` zeigt die Startseite mit drei Kacheln
- [ ] **Eine** Anmeldung öffnet alle drei Bereiche
- [ ] Abmelden in einem Bereich meldet aus allen dreien ab
- [ ] Cookie hat `Secure`, `HttpOnly` und `Path=/`
      (Entwicklertools → Anwendung → Cookies)
- [ ] `journalctl -u abfahrt` zeigt beim Antrag die **echte** Client-IP,
      nicht `10.0.0.10`
- [ ] Beim Start keine Warnung über `FORWARDED_ALLOW_IPS` oder fehlende
      Geheimnisse
- [ ] Eingangsmail kommt an – zuerst an eine eigene Adresse, dann an Gmail,
      GMX und Outlook
- [ ] CSV-Export öffnet in Excel ohne Nachfrage und mit korrekten Umlauten
- [ ] Monitor-Link erzeugt und auf dem Bildschirmrechner geprüft
- [ ] Eine Sicherung von Hand angestoßen, **drei** Dateien im Zielordner

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
systemctl restart abfahrt
systemctl status abfahrt --no-pager
journalctl -u abfahrt -n 30 --no-pager
```

Dieselben vier Schritte gelten in jedem der drei Container, nur mit dem
Dienstnamen `abfahrt`. Der Container
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
systemctl restart abfahrt
```

Zurück auf die aktuelle Spitze geht es mit `git checkout main`.

Ist die **Datenbank** das Problem, hilft der Code-Rollback allein nicht – dann
die Sicherung aus Schritt 1 zurückspielen:

```bash
systemctl stop abfahrt
cp /var/backups/abfahrt/antraege-JJJJ-MM-TT.db /var/lib/abfahrt/antraege.db
rm -f /var/lib/abfahrt/antraege.db-wal /var/lib/abfahrt/antraege.db-shm
chown abfahrt:abfahrt /var/lib/abfahrt/antraege.db
systemctl start abfahrt
```

Die beiden `-wal`- und `-shm`-Dateien müssen weg: sie gehören zur alten
Datenbank und passen nicht zur zurückgespielten.

### Lokale Änderungen am Server

Wenn jemand direkt auf dem Server etwas editiert hat, bricht `git pull` ab. Was
lokal abweicht, zeigt `git status`. Entweder verwerfen (`git checkout -- <datei>`)
oder vorher sichern. Die Konfiguration ist davon nicht betroffen – die liegt in
`/etc/abfahrt/` und damit außerhalb des Repos.

---

## 6. Wenn etwas klemmt

| Symptom | Ursache, die es meistens ist |
| --- | --- |
| `git pull` sagt „detected dubious ownership" | `/opt/abfahrt` gehört nicht root. Frühere Fassungen dieser Anleitung haben es fälschlich auf `abfahrt` gesetzt. Richtigstellen mit `chown -R root:root /opt/abfahrt` – der Dienst braucht dort keine Schreibrechte. `git config --global --add safe.directory` behebt zwar die Meldung, lässt aber den Dienstbenutzer weiter seinen eigenen Code beschreiben. |
| Anmeldung wirft einen zurück auf die Anmeldeseite | Cookie mit `Secure`, aber die Verbindung kam als HTTP an. `X-Forwarded-Proto` fehlt im Proxy. |
| Alle Anträge haben dieselbe IP | `FORWARDED_ALLOW_IPS` zeigt nicht auf den nginx. |
| Ein Fehlversuch sperrt alle aus | dasselbe. |
| 502 vom nginx | Dienst läuft nicht oder Firewall blockt. `systemctl status abfahrt`, dann vom nginx-Host `curl http://10.0.0.42:8080/`. |
| Mails bleiben liegen | `SMTP_HOST`/`MAIL_FROM` fehlen, oder Zugangsdaten stimmen nicht. Der Fehler steht in der Detailansicht des Antrags und im Journal. |
| 429 beim Absenden | Rate Limit im nginx. Bei geteilten NAT-Adressen `rate=` in der Config hochsetzen. |
| Monitor zeigt dauerhaft die orange „Keine Verbindung"-Leiste, obwohl die Seite lädt | `connect-src 'self'` fehlt in der Content-Security-Policy. Die Seite selbst kommt durch, ihre Nachladeanfragen nicht. In der Browserkonsole steht die geblockte Anfrage. Siehe `nginx-dienst.conf`. |
| Zeitplan-Abruf schlägt immer fehl | Der Container kommt nicht nach draußen (Egress auf 443 und DNS), oder `ca-certificates` fehlt. Der genaue Text steht im Backoffice unter *Einstellungen › Zeitplan-Abruf* bei den bisherigen Abrufen. |
| Monitor zeigt eine Uhrzeit, die nicht stimmt | Entweder steht `JETZT_FEST` noch gesetzt (Warnung im Journal), oder die Containeruhr geht falsch – `timedatectl`. Die Uhr auf dem Bildschirm kommt vom Server, nicht vom Bildschirmrechner. |
| Monitor zeigt nichts, obwohl Schichten erfasst sind | `TAGE` oder die Daten in den CSV-Dateien liegen in einem anderen Jahr als die Containeruhr. Im Backoffice unter *Schichten* steht, für welche Tage etwas erfasst ist. |
| Eine Adresse zeigt den falschen Bereich | Der Host-Kopf kommt nicht durch. `proxy_set_header Host $host;` fehlt im Schnipsel, oder der Name steht nicht in `HOST_…`. Ohne Treffer landet alles beim Pfad-Rückfall. |
| Anmeldung gilt nur in einem Bereich | `APP_SECRET_KEY` steht noch in einer der drei Anwendungs-Dateien und überschreibt dort den gemeinsamen. Er gehört nur nach `dienst.env`. |
| Im Protokoll fehlt ein `starte Bereich …` | Die `.env` dieses Bereichs ist nicht lesbar oder ihr `DB_PATH` zeigt ins Leere. |

---

## 7. Was nur für einen Bereich gilt

### Helfer: Daten hereinholen

Der Helfer-Bereich startet nicht leer und wartet auf Eingaben – er braucht
erst seinen Datenbestand:

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

**Von selbst, im Takt.** Stehen die Adressen, gleicht der Dienst zusätzlich
alle `IMPORT_TAKT_MINUTEN` Minuten ab (Vorgabe 60, `0` schaltet es ab, unter 5
wird auf 5 angehoben). Der erste Lauf kommt nach dem ersten Abstand, nicht
beim Hochfahren – der Start soll nicht an einem fremden Server hängen. Jeder
Lauf sind drei Aufrufe dort; stündlich also 72 am Tag.

Ein selbsttätiger Lauf ist vorsichtiger als der Knopf:

- **Keine Zeile** oder **weniger als die Hälfte des letzten geglückten Laufs**
  wird nicht übernommen. Der Grund ist eine Ausfuhr, die nur aus Kopfzeilen
  besteht: technisch tadellos, läuft ohne Fehler durch – und setzt den Bedarf
  jeder Schicht auf null und löscht alle Einteilungen aus dem Import. Wer den
  Knopf drückt, sieht „0 Zeilen“ im Bericht und stutzt; einem Lauf um vier Uhr
  morgens sieht niemand zu. Von Hand geht derselbe Abruf durch – wer hinschaut,
  darf auch einen kleinen Bestand übernehmen.
- **Gescheiterte Läufe hinterlassen einen Vermerk.** Unter *Import* steht dann
  eine Warnung mit dem Grund, und die Liste der Läufe zeigt „gescheitert“ statt
  „übernommen“. Ohne das stünde dort nur ein alter geglückter Lauf, und nichts
  sagte, dass seither nichts mehr ankommt – der häufigste Fall dafür ist ein
  abgelaufener Login-Link.

Was der Dienst dabei tut, steht auch im Journal:

```bash
journalctl -u abfahrt-helfer -g Helferabgleich --no-pager | tail -20
```

### Helfer: Daten ausführen

Unter **Helfer** steht neben *Helfer hinzufügen* ein Knopf **Als CSV**. Die
Datei enthält **eine Zeile je Helfer** mit Name, Kontakt, Verpflegung, den
T-Shirt-Größen (angekündigt, Rohwert, tatsächlich ausgegeben samt Zeitpunkt
und Kürzel), der Zahl der Schichten und der Bemerkung.

**Funkgeräte und Schlüssel stehen nicht darin**, die T-Shirt-Ausgabe schon.
Der Unterschied liegt an der Form der Daten: das T-Shirt hängt als *ein* Feld
an der Person, es gibt höchstens eine Ausgabe je Helfer. Funk und Schlüssel
sind eigene Vorgänge, davon beliebig viele je Person – sie hier anzuhängen
hieße, die Zeile zu vervielfachen. Dafür bräuchte es eigene Ausfuhren.

Trennzeichen ist `CSV_TRENNER` (Vorgabe `;`, was deutsches Excel erwartet),
und der Datei geht ein BOM voran – ohne das zeigt Excel unter Windows
Umlaute als Buchstabensalat.

Zwei Dinge dazu:

- **Die Suche der Liste filtert nicht mit.** Sie läuft im Browser über das,
  was schon auf der Seite steht; die Datei enthält immer alle. Ein Ausschnitt
  lässt sich in der Tabellenkalkulation ohnehin leichter ziehen.
- **Es sind Personendaten** – Namen, Mailadressen, Telefonnummern. Der Abruf
  verlangt eine Anmeldung und wird mit `Cache-Control: no-store` ausgeliefert.
  Was danach mit der Datei geschieht, liegt außerhalb der Anwendung; sie
  gehört nach der Veranstaltung gelöscht wie der Rest.

Neben `Größe angekündigt` steht `Größe wie eingetippt`. Das ist Absicht: aus
dem Registrierungstool kommen Werte wie „Damen L“ oder „Large“ – die erste
Spalte ist leer, wenn sich daraus keine eindeutige Größe lesen lässt, die
zweite zeigt dann, was dastand.

### Helfer: der Monitor-Link

Er steht in der Datenbank, nicht in der Konfiguration – ein Neustart ändert ihn
also nicht, ein neuer `APP_SECRET_KEY` auch nicht. Wer ihn hat, sieht die
Einteilung samt Namen. Also auf den Bildschirmrechner geben, nicht in einen
offenen Verteiler.

Verliert er sich oder war er an der falschen Stelle, im Backoffice unter
**Monitor** einen neuen erzeugen – der alte gilt sofort nicht mehr.

Auf dem Bildschirmrechner: Browser im Vollbild (F11), Bildschirmschoner und
Energiesparen aus. Die Seite hält sich selbst aktuell und braucht kein F5.



> `helfer.db` ist die einzige der drei, die sich **nicht** aus dem
> wiederherstellen lässt, was die Leute eingereicht haben: Schichten und
> Helfer kommen zwar aus den Listen des Registrierungstools, jede Einteilung
> von Hand aber nur von hier. Vor der Veranstaltung lohnt sich ein zweiter
> Sicherungszeitpunkt am Abend.

### Prüfliste für den Helfer-Bereich

Zusätzlich zu Abschnitt 4:

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
- [ ] `helfer.example.de/monitor/<token>` ist **ohne** Anmeldung
      erreichbar, `admin.example.de/helfer` nicht
- [ ] Ein falscher Token gibt 404
- [ ] Falls Unterschriften genutzt werden: sie werden **nur bei der Ausgabe**
      verlangt, nicht bei der Rücknahme – bei der Ausgabe steht die Person da
      und wartet, bei der Rückgabe legt sie das Gerät hin und ist weg
- [ ] Falls Unterschriften genutzt werden: Tablet-Link erzeugt, auf dem Tablet
      im Vollbild geöffnet, Bildschirmsperre aus. Eine Übergabe probeweise
      anfordern und unterschreiben
- [ ] Der Tablet-Link ist ein **anderer** als der des Monitors – die eine
      Adresse nimmt Eingaben entgegen, die andere nicht

---

## 8. Nach der Veranstaltung: Personendaten löschen

Zwei Zusagen stehen im Programm und haben ein Datum:

- Die Kennzeichen-App sagt den Antragstellern, die Daten würden **spätestens
  vier Wochen nach der Veranstaltung** gelöscht (`AUFBEWAHRUNG_HINWEIS`).
- Das Unterschriften-Tablet sagt den Helfern, die Unterschrift werde **nach
  der Veranstaltung** gelöscht – ohne Frist, also sofort fällig.

Dafür gibt es `deploy/daten-loeschen.py`. Ohne `--wirklich` schreibt es
nichts und zeigt nur, was verschwinden würde:

```bash
cd /opt/abfahrt
for a in kennzeichen presse helfer; do
    case $a in kennzeichen) d=antraege;; *) d=$a;; esac
    python3 deploy/daten-loeschen.py --art "$a" --db "/var/lib/abfahrt/$d.db"
done
```

Sieht die Aufstellung richtig aus, denselben Aufruf mit `--wirklich`. Der
Dienst sollte dabei stehen (`systemctl stop …`), sonst schreibt er
möglicherweise gerade mit. Es wird vorher eine Sicherung neben die Datenbank
gelegt – **die gehört anschließend auch gelöscht**, sonst war der Lauf
umsonst.

Was verschwindet: Anträge, Akkreditierungen, Helfer samt Einteilungen und
Ausleihen, Schlüsselvorgänge, Fahrzeugstamm, Unterschriften, alle Mails samt
Empfängern, die Namen an den Aufgaben, die Importprotokolle (dort stehen
Hinweise wie „Julia Johren: in der Verpflegungsspalte stand ‚L'") – und die
Token für Durchfahrtsliste, Monitor und Tablet, denn die ersetzen eine
Anmeldung.

Was bleibt: Schichtzeiten, der Zeitplan der Rennserien, die Aufgabenliste
ohne die Namen dahinter, die Materialvorgaben. Das ist nächstes Jahr eine
Vorlage und benennt niemanden.

Nicht vergessen, weil außerhalb der Datenbank:

- **Die Sicherungen** unter `/var/backups/…` aus der Zeit der Veranstaltung –
  die enthalten alles noch.
- **Die beiden Import-CSVs**, falls sie irgendwo liegengeblieben sind.
- **Der Login-Link zur Helferliste** in `IMPORT_LOGIN_URL`: er ist ein
  Passwort und gilt weiter. Beim Dienst widerrufen oder wenigstens aus der
  `.env` nehmen.
