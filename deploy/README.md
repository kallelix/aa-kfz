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
apt install -y python3 python3-venv postgresql git

adduser --system --group --no-create-home --home /nonexistent --shell /usr/sbin/nologin abfahrt

mkdir -p /etc/abfahrt /var/backups/abfahrt
chown abfahrt:abfahrt /var/backups/abfahrt
chmod 750 /var/backups/abfahrt
```

**Dem Dienstbenutzer gehört nur das Sicherungsverzeichnis.** `/opt/abfahrt`
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
also nicht an. Die Daten liegen ohnehin in PostgreSQL.

### Datenbank

Eine Datenbank für alle drei Bereiche; jeder legt darin beim Start sein
eigenes Schema an (`kennzeichen`, `presse`, `helfer`). Rolle und Datenbank
heißen wie der Systembenutzer:

```bash
runuser -u postgres -- createuser abfahrt
runuser -u postgres -- createdb --owner=abfahrt abfahrt

# Probe: als abfahrt, ohne Passwort
runuser -u abfahrt -- psql -d abfahrt -c 'SELECT current_user'
```

**Kein Passwort.** Der Dienst verbindet sich über den Unix-Socket, und
PostgreSQL prüft dort nur, ob der Systembenutzer so heißt wie die Rolle
(`peer`, unter Debian und Ubuntu voreingestellt). Es gibt also kein
Datenbankpasswort, das in einer Datei stehen oder durchsickern könnte, und
`DATABASE_URL` in `dienst.env` enthält keins. PostgreSQL lauscht von Haus aus
nur auf `localhost` – von außen ist nichts zu erreichen, und das soll so
bleiben.

### Konfiguration

Vier Dateien: eine gemeinsame und je Anwendung eine.

```bash
install -o root -g root -m 600 deploy/dienst.env.example      /etc/abfahrt/dienst.env
install -o root -g root -m 600 deploy/kennzeichen.env.example /etc/abfahrt/kennzeichen.env
install -o root -g root -m 600 deploy/presse.env.example      /etc/abfahrt/presse.env
install -o root -g root -m 600 deploy/helfer.env.example      /etc/abfahrt/helfer.env

# Session-Schluessel - EINMAL, er gilt fuer alle drei
/opt/abfahrt/.venv/bin/python -c "import secrets; print('APP_SECRET_KEY=' + secrets.token_urlsafe(32))"

editor /etc/abfahrt/dienst.env
```

In **`dienst.env`** steht, was für alle gilt: `BIND`,
`FORWARDED_ALLOW_IPS`, `DATABASE_URL`, die vier `HOST_…`,
`APP_SECRET_KEY` und die drei Zeiger `KENNZEICHEN_ENV`, `PRESSE_ENV`,
`HELFER_ENV`.

In den **drei anderen** steht, was sich unterscheidet – vor allem
`BASIS_URL`, die Mailkonfiguration (Kennzeichen und Presse) und beim Helfer
der Abruf der Helferliste.

> `APP_SECRET_KEY` gehört **nur** in `dienst.env`. Die Umgebung schlägt die
> Datei, also gälte er ohnehin für alle drei – aber daran hängen die
> CSRF-Token, und stünden in den Bereichen verschiedene Schlüssel, passte das
> Token eines Formulars nicht zum Bereich, an den es geht.

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
Presse, Helfer. Fehlt einer, ist seine `.env` nicht lesbar. Die Tabellen legt
der Dienst beim ersten Start selbst an; dann steht je Bereich
`Migrationen eingespielt: 0001_anfang.sql` im Protokoll.

### Das erste Admin-Konto

Ins Backoffice meldet sich jeder mit seinem **eigenen Konto** an:
Mailadresse und Passwort. Ein Admin lädt die anderen unter
`admin.example.de/konten` ein; sie bekommen eine Mail mit einem Link, über
den sie ihr Passwort festlegen. Jedes Konto hat eine Rolle – *Admin*, *Orga*
oder *Lesend* – und die Bereiche, die es sehen darf. Sein Kürzel landet als
„bearbeitet von“ in den Daten.

Den ersten Admin legt man auf dem Server an:

```bash
cd /opt/abfahrt
runuser -u abfahrt -- env DATABASE_URL='postgresql://abfahrt@/abfahrt?host=/var/run/postgresql' \
    .venv/bin/python -m kern.konto admin
```

Das fragt Mailadresse, Name, Kürzel und Passwort. Danach unter
`admin.example.de` anmelden, unter **Konten** die anderen einladen und unter
**Veranstaltungen** die erste Veranstaltung anlegen: Schichten, Programm,
Aufgaben und Ausgaben des Helferbereichs gehören immer zu einer. Mit welcher
gearbeitet wird, wählt jeder oben im Helferbereich; ohne Wahl gilt die
nächste, die noch nicht vorbei ist. Monitor, Zeitplan-Abruf und
Helferabgleich nehmen immer diese.

Die Einladungen gehen über das **Postfach des Kennzeichen-Bereichs**
(`SMTP_…` und `MAIL_FROM` in `kennzeichen.env`). Kommt eine nicht hinaus,
zeigt die Seite den Link an; dann gibt ihn der Admin selbst weiter.

> **Gemeinsames Passwort.** Wer schon mit `ADMIN_PASSWORD_HASH` gearbeitet
> hat, kann auch so umsteigen: mit dem gemeinsamen Passwort anmelden, unter
> **Konten** das eigene Konto als Admin anlegen und die Einladung einlösen.
> Ab diesem Moment gilt das gemeinsame Passwort nicht mehr – für niemanden,
> auch nicht für schon angemeldete Browser. Die Zeile kann dann aus
> `dienst.env` heraus.

Kommt niemand mehr hinein – der einzige Admin hat sein Passwort vergessen,
und die Mail kommt nicht an –, hilft dasselbe Werkzeug:

```bash
runuser -u abfahrt -- env DATABASE_URL='postgresql://abfahrt@/abfahrt?host=/var/run/postgresql' \
    .venv/bin/python -m kern.konto passwort ada@example.org
```

`python -m kern.konto liste` zeigt alle Konten.

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

Ein Lauf, eine Datei: `pg_dump` sichert die ganze Datenbank, also alle drei
Bereiche.

```bash
crontab -u abfahrt -e
```

```cron
15 3 * * * /opt/abfahrt/deploy/backup.sh >> /var/log/abfahrt-backup.log 2>&1
```

Die Datei heißt `abfahrt-JJJJ-MM-TT-HHMM.dump` und ist im Custom-Format von
`pg_dump`: komprimiert, und mit `pg_restore` lässt sich auch nur ein Bereich
zurückholen. Das Skript prüft jede Datei mit `pg_restore --list` – eine
kaputte Sicherung fällt sonst erst auf, wenn man sie braucht. Sicherungen
älter als 30 Tage werden gelöscht.

Es läuft als `abfahrt` und meldet sich wie der Dienst ohne Passwort an. Von
root aufgerufen, wechselt es selbst dorthin – `deploy/backup.sh` von Hand
geht also auch als root.

> Die Sicherungen enthalten Personendaten. Nach der Veranstaltung gehören sie
> mit gelöscht, siehe Abschnitt 8 – sonst war der Löschlauf auf der Datenbank
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
- [ ] Admin-Konto angelegt, ein zweites Konto per Mail eingeladen – die
      Einladung kommt an, der Link setzt das Passwort
- [ ] **Eine** Anmeldung öffnet alle Bereiche des Kontos; ein Konto nur für
      die Presse sieht Kennzeichen und Helfer **nicht**
- [ ] Das gemeinsame Passwort wird abgewiesen, `ADMIN_PASSWORD_HASH` ist aus
      `dienst.env` heraus
- [ ] Abmelden in einem Bereich meldet aus allen ab
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
- [ ] `runuser -u abfahrt -- psql -d abfahrt -c '\dn'` zeigt die drei
      Schemas `kennzeichen`, `presse`, `helfer`
- [ ] Eine Sicherung von Hand angestoßen, eine `.dump`-Datei im Zielordner

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

Im Protokoll gehören nach dem Start keine Warnungen zu `FORWARDED_ALLOW_IPS`,
`APP_SECRET_KEY` oder `JETZT_FEST` zu sehen. Steht dort
eine Zeile `Migrationen eingespielt: …`, hat ein Bereich seine Tabellen auf den
neuen Stand gebracht – das ist normal und gewollt.

Danach einmal im Browser: Formular lädt, Backoffice lädt, ein Antrag lässt sich
öffnen.

### Schema-Änderungen

Jede Änderung am Aufbau der Tabellen liegt als nummerierte Datei im Ordner
`migrationen/` ihres Bereichs. Beim Start spielt jeder Bereich ein, was ihm
noch fehlt, und vermerkt es in seiner Tabelle `migration`. Alle fehlenden
laufen in **einer** Transaktion: entweder ganz oder gar nicht. Trotzdem gilt
Schritt 1 – eine Sicherung kostet ein paar Sekunden.

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

Ist die **Datenbank** das Problem, hilft der Code-Rollback allein nicht: eine
Migration, die der neue Stand eingespielt hat, bleibt eingespielt. Dann die
Sicherung aus Schritt 1 zurückspielen:

```bash
systemctl stop abfahrt
runuser -u abfahrt -- pg_restore --clean --if-exists --dbname=abfahrt \
    /var/backups/abfahrt/abfahrt-JJJJ-MM-TT-HHMM.dump
systemctl start abfahrt
```

`--clean` räumt vorher ab, was in der Sicherung steht – Tabellen, Zähler,
Schemas – und baut es aus der Datei neu auf. Nur einen Bereich zurückholen
geht mit zusätzlich `--schema=helfer`.

### Einmalig: von SQLite nach PostgreSQL

Bis Oktober 2026 lagen die Daten in drei SQLite-Dateien unter
`/var/lib/abfahrt`. **Übernommen wird daraus nichts** – PostgreSQL beginnt
leer, und das Backoffice mit der ersten Veranstaltung, die man anlegt. Die
Personendaten aus 2026 waren ohnehin zu löschen (Abschnitt 8).

```bash
# 1. Sichern - noch mit dem alten Skript, es sichert die drei .db-Dateien
/opt/abfahrt/deploy/backup.sh
systemctl stop abfahrt

# 2. PostgreSQL einrichten, wie in Abschnitt 1 unter "Datenbank"
apt install -y postgresql
runuser -u postgres -- createuser abfahrt
runuser -u postgres -- createdb --owner=abfahrt abfahrt

# 3. Neuer Stand
cd /opt/abfahrt
git pull
.venv/bin/pip install --no-cache-dir -r requirements.txt

# 4. DATABASE_URL in /etc/abfahrt/dienst.env eintragen (siehe
#    deploy/dienst.env.example) und die neue Unit installieren
editor /etc/abfahrt/dienst.env
install -m 644 deploy/dienst.service /etc/systemd/system/abfahrt.service
systemctl daemon-reload
systemctl start abfahrt
```

Danach wie in Abschnitt 1 das erste Admin-Konto anlegen und unter
**Veranstaltungen** die erste Veranstaltung. Dann:

- die Zeilen `DB_PATH=` aus den drei `.env`-Dateien nehmen, dazu `TAGE=` aus
  `helfer.env` – sie wirken nicht mehr;
- die SQLite-Dateien unter `/var/lib/abfahrt` löschen und das Verzeichnis
  dazu. **Sie enthalten Personendaten**; liegen lassen hieße, sie beim
  Löschlauf zu vergessen. Die alten `.db`-Sicherungen unter
  `/var/backups/abfahrt` laufen nach 30 Tagen von selbst aus.

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
| Monitor zeigt nichts, obwohl Schichten erfasst sind | Der Monitor zeigt die nächste Veranstaltung, die noch nicht vorbei ist – die Schichten hängen an einer anderen, oder deren Tage stimmen nicht. Unter **Veranstaltungen** nachsehen. |
| Eine Adresse zeigt den falschen Bereich | Der Host-Kopf kommt nicht durch. `proxy_set_header Host $host;` fehlt im Schnipsel, oder der Name steht nicht in `HOST_…`. Ohne Treffer landet alles beim Pfad-Rückfall. |
| Anmeldung gilt nur in einem Bereich | Das Konto ist nur für diesen Bereich freigegeben – unter **Konten** nachsehen. Sonst: `APP_SECRET_KEY` fehlt in `dienst.env`, und jeder Bereich hat einen eigenen. |
| Das gemeinsame Passwort geht nicht mehr | So gewollt: es gibt einen Admin mit eigenem Konto. Jeder meldet sich mit seinem eigenen an. |
| Niemand kommt mehr hinein | `python -m kern.konto passwort <mail>` auf dem Server, siehe Abschnitt 1, *Das erste Admin-Konto*. |
| Einladung kommt nicht an | `SMTP_…` und `MAIL_FROM` in `kennzeichen.env` prüfen; die Einladungen gehen über dieses Postfach. Bis dahin zeigt die Kontenseite den Link zum Weitergeben. |
| Im Protokoll fehlt ein `starte Bereich …` | Die `.env` dieses Bereichs ist nicht lesbar. |
| Dienst startet nicht, im Journal `connection failed` mit `/var/run/postgresql` | PostgreSQL läuft nicht: `systemctl status postgresql`. |
| Im Journal `role "abfahrt" does not exist` oder `Peer authentication failed` | Rolle oder Datenbank fehlen (Abschnitt 1, *Datenbank*), oder `DATABASE_URL` nennt einen anderen Benutzer als den, unter dem der Dienst läuft. |

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
journalctl -u abfahrt -g Helferabgleich --no-pager | tail -20
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



> Der Helfer-Bereich ist der einzige der drei, der sich **nicht** aus dem
> wiederherstellen lässt, was die Leute eingereicht haben: Schichten und
> Helfer kommen zwar aus den Listen des Registrierungstools, jede Einteilung
> von Hand aber nur von hier. Vor der Veranstaltung lohnt sich ein zweiter
> Sicherungszeitpunkt am Abend.

### Prüfliste für den Helfer-Bereich

Zusätzlich zu Abschnitt 4:

- [ ] `JETZT_FEST` ist leer, im Journal steht keine Warnung dazu
- [ ] Die Veranstaltung steht unter **Veranstaltungen** mit den richtigen
      Tagen, und oben im Helferbereich ist sie gewählt
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
    runuser -u abfahrt -- .venv/bin/python deploy/daten-loeschen.py --art "$a"
done
```

Mit der Python aus `.venv`, nicht mit `python3`: nur dort liegt der
Datenbanktreiber. Sieht die Aufstellung richtig aus, denselben Aufruf mit
`--wirklich`. Der Dienst sollte dabei stehen (`systemctl stop abfahrt`), sonst
schreibt er möglicherweise gerade mit. Vorher legt das Skript eine Sicherung
des Bereichs nach `/var/backups/abfahrt/<bereich>-vor-loeschung-<datum>.dump`
– **die gehört anschließend auch gelöscht**, sonst war der Lauf umsonst.
Danach schreibt es die betroffenen Tabellen mit `VACUUM FULL` neu, damit die
gelöschten Zeilen nicht als freier Platz in den Dateien stehenbleiben.

Was verschwindet: Anträge, Akkreditierungen, Helfer samt Einteilungen und
Ausleihen, Schlüsselvorgänge, Fahrzeugstamm, Unterschriften, alle Mails samt
Empfängern, die Namen an den Aufgaben, die Importprotokolle (dort stehen
Hinweise wie „Erika Mustermann: in der Verpflegungsspalte stand ‚L'") – und die
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
