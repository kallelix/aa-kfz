# Deployment

Aufbau: die App läuft in einem **LXC-Container** (Debian/Ubuntu), ein
**nginx auf einem anderen Host** mit öffentlicher IP terminiert HTTPS und leitet
weiter. Adresse: `kennzeichen.example.de`.

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

Im Protokoll gehören nach dem Start keine Warnungen zu `FORWARDED_ALLOW_IPS`,
`APP_SECRET_KEY` oder `ADMIN_PASSWORD_HASH` zu sehen. Steht dort eine Zeile
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
