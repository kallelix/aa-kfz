"""Backoffice-Konten im zusammengesetzten Dienst, von außen gesehen.

    python tests/test_konten.py

Startet den Dienst mit einer Wegwerf-Datenbank und einem SMTP-Nachbau im
selben Prozess und spielt durch: Umstieg vom gemeinsamen Passwort, Einladung
per Mail, Rechte je Bereich und Rolle, das Kürzel in den Daten, Sperren,
Passwort vergessen. Es geht nichts nach draußen.
"""

import email
import email.policy
import http.client
import os
import re
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))
from kern import testdb  # noqa: E402

PYTHON = WURZEL / ".venv" / "Scripts" / "python.exe"
if not PYTHON.exists():
    PYTHON = WURZEL / ".venv" / "bin" / "python"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

fehler = []


def pruefe(bedingung, text):
    print(("  ok   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        fehler.append(text)


# --- SMTP-Nachbau --------------------------------------------------------------

empfangen = []


class SmtpAttrappe(socketserver.StreamRequestHandler):
    """Spricht gerade so viel SMTP, dass smtplib zufrieden ist."""

    def handle(self):
        self.wfile.write(b"220 attrappe bereit\r\n")
        an = []
        while True:
            zeile = self.rfile.readline()
            if not zeile:
                return
            befehl = zeile.decode("utf-8", "replace").strip()
            gross = befehl.upper()
            if gross.startswith(("EHLO", "HELO")):
                self.wfile.write(b"250-attrappe\r\n250 SIZE 10485760\r\n")
            elif gross.startswith("RCPT TO"):
                an.append(befehl.split(":", 1)[1].strip(" <>"))
                self.wfile.write(b"250 ok\r\n")
            elif gross == "DATA":
                self.wfile.write(b"354 los\r\n")
                zeilen = []
                while True:
                    rohzeile = self.rfile.readline()
                    if not rohzeile or rohzeile in (b".\r\n", b".\n"):
                        break
                    zeilen.append(rohzeile)
                nachricht = email.message_from_bytes(b"".join(zeilen), policy=email.policy.default)
                empfangen.append({"an": list(an), "betreff": str(nachricht["Subject"]),
                                  "text": nachricht.get_content()})
                an = []
                self.wfile.write(b"250 angenommen\r\n")
            elif gross == "QUIT":
                self.wfile.write(b"221 tschuess\r\n")
                return
            else:
                self.wfile.write(b"250 ok\r\n")


class SmtpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def freier_hafen():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


smtp_hafen = freier_hafen()
smtp = SmtpServer(("127.0.0.1", smtp_hafen), SmtpAttrappe)
threading.Thread(target=smtp.serve_forever, daemon=True).start()


def letzte_mail(an):
    for _ in range(50):
        for m in reversed(empfangen):
            if an in m["an"]:
                return m
        time.sleep(0.1)
    return None


def link_aus(mail):
    treffer = re.search(r"https?://[^/\s]+(/konto/passwort/[A-Za-z0-9_-]+)", mail["text"] if mail else "")
    return treffer.group(1) if treffer else ""


# --- Dienst ------------------------------------------------------------------

GEMEINSAM = "gemeinsam-123"
HASH = subprocess.run(
    [str(PYTHON), "-m", "kern.passwort", GEMEINSAM],
    cwd=str(WURZEL), capture_output=True, text=True,
    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
).stdout.strip().split("=", 1)[1]

DB = testdb.wegwerf("konten")
verzeichnis = Path(tempfile.mkdtemp(prefix="konten-"))
hafen = freier_hafen()
for name in ("kennzeichen", "presse", "helfer"):
    (verzeichnis / (name + ".env")).write_text(
        "COOKIE_SECURE=0\n",
        encoding="utf-8")

umgebung = {
    **os.environ,
    "PYTHONIOENCODING": "utf-8",
    "BIND": "127.0.0.1:" + str(hafen),
    "HOST_KENNZEICHEN": "kennzeichen.test",
    "HOST_PRESSE": "presse.test",
    "HOST_HELFER": "helfer.test",
    "HOST_ADMIN": "admin.test",
    "ADMIN_PASSWORD_HASH": HASH,
    "APP_SECRET_KEY": "konten-test-schluessel",
    "COOKIE_SECURE": "0",
    "LOGIN_VERSUCHE": "3",
    "DATABASE_URL": DB,
    "SMTP_HOST": "127.0.0.1",
    "SMTP_PORT": str(smtp_hafen),
    "SMTP_TLS": "keine",
    "SMTP_USER": "",
    "MAIL_FROM": "Orga <orga@example.org>",
    "KENNZEICHEN_ENV": str(verzeichnis / "kennzeichen.env"),
    "PRESSE_ENV": str(verzeichnis / "presse.env"),
    "HELFER_ENV": str(verzeichnis / "helfer.env"),
}
umgebung.pop("JETZT_FEST", None)

prozess = subprocess.Popen(
    [str(PYTHON), "-m", "dienst"], cwd=str(WURZEL), env=umgebung,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ruf(pfad, methode="GET", daten=None, keks="", host="admin.test"):
    c = http.client.HTTPConnection("127.0.0.1", hafen, timeout=20)
    koerper = urllib.parse.urlencode(daten, doseq=True).encode() if daten else None
    kopf = {"Host": host}
    if daten:
        kopf["Content-Type"] = "application/x-www-form-urlencoded"
    if keks:
        kopf["Cookie"] = keks
    c.request(methode, pfad, body=koerper, headers=kopf)
    r = c.getresponse()
    gesetzt = r.getheader("Set-Cookie", "") or ""
    ergebnis = (r.status, r.getheader("Location", ""), r.read().decode("utf-8", "replace"),
                gesetzt.split(";")[0] if gesetzt else "")
    c.close()
    return ergebnis


def csrf(seite):
    treffer = re.search(r'name="csrf" value="([^"]+)"', seite)
    return treffer.group(1) if treffer else ""


def anmelden(email_adresse, passwort, bereich="konto"):
    status, ort, _, keks = ruf(f"/{bereich}/login", "POST",
                               {"email": email_adresse, "passwort": passwort, "weiter": "/"})
    return keks if status == 303 else ""


def konto_anlegen(keks, **werte):
    _, _, seite, _ = ruf("/konten/neu", keks=keks)
    daten = {"csrf": csrf(seite), **werte}
    for b in werte.pop("bereiche", []):
        daten["bereich_" + b] = "1"
    daten.pop("bereiche", None)
    return ruf("/konten/neu", "POST", daten, keks=keks)


def sql(schema, befehl, *parameter):
    return testdb.abfrage(DB, schema, befehl, parameter)


try:
    for _ in range(150):
        try:
            with socket.create_connection(("127.0.0.1", hafen), timeout=0.2):
                break
        except OSError:
            time.sleep(0.2)
    else:
        raise RuntimeError("Dienst ist nicht hochgekommen")

    print("Übergang: noch kein Admin, das gemeinsame Passwort gilt")
    status, ort, _, _ = ruf("/")
    pruefe(status == 303 and ort.startswith("/konto/login"),
           "die Startseite verlangt eine Anmeldung")
    _, _, seite, _ = ruf("/konto/login")
    pruefe('name="passwort"' in seite and 'name="email"' not in seite,
           "die Anmeldeseite fragt nur das gemeinsame Passwort")
    status, _, _, alt = ruf("/konto/login", "POST", {"passwort": GEMEINSAM, "kuerzel": "XX",
                                                     "weiter": "/konten"})
    pruefe(status == 303 and alt, "mit dem gemeinsamen Passwort angemeldet")
    _, _, seite, _ = ruf("/konten", keks=alt)
    pruefe("gemeinsamen Passwort angemeldet" in seite,
           "die Kontenseite sagt, was zu tun ist")
    _, _, seite, _ = ruf("/", keks=alt)
    pruefe(all(n in seite for n in ("Kennzeichen", "Presse", "Helfer", 'href="/konten"')),
           "die Startseite zeigt alle drei Bereiche und die Konten")

    print("Den ersten Admin anlegen und einladen")
    status, ort, _, _ = konto_anlegen(alt, name="Ada Admin", email="ada@example.org",
                                      kuerzel="aa", rolle="admin")
    pruefe(status == 303 and "eingeladen" in ort, "angelegt, Einladung verschickt")
    mail = letzte_mail("ada@example.org")
    pruefe(mail is not None and "Backoffice" in mail["betreff"], "die Einladung kommt an")
    link = link_aus(mail)
    pruefe(link.startswith("/konto/passwort/"), "und trägt einen Link: " + link[:30])
    pruefe(ruf("/kennzeichen", keks=alt)[0] == 200,
           "bis zum Einlösen gilt das gemeinsame Passwort weiter")
    pruefe(ruf(link)[0] == 200, "der Link öffnet das Formular, ohne etwas einzulösen")
    pruefe(ruf(link)[0] == 200, "auch beim zweiten Aufruf (Mailscanner)")
    status, _, seite, _ = ruf(link, "POST", {"neu": "zu-kurz", "wiederholung": "zu-kurz"})
    pruefe(status == 400 and "mindestens" in seite, "ein zu kurzes Passwort wird abgewiesen")
    status, _, seite, _ = ruf(link, "POST", {"neu": "ada-passwort-1", "wiederholung": "anders-123"})
    pruefe(status == 400 and "nicht gleich" in seite, "verschiedene Eingaben auch")
    status, ort, _, ada = ruf(link, "POST", {"neu": "ada-passwort-1", "wiederholung": "ada-passwort-1"})
    pruefe(status == 303 and ada, "Passwort gesetzt und gleich angemeldet")
    pruefe(ruf(link)[0] == 410, "der Link gilt danach nicht mehr")

    print("Jetzt gilt das gemeinsame Passwort nicht mehr")
    status, ort, _, _ = ruf("/kennzeichen", keks=alt)
    pruefe(status == 303 and "login" in ort, "der alte Keks wird abgewiesen")
    status, _, _, _ = ruf("/konto/login", "POST", {"passwort": GEMEINSAM, "weiter": "/"})
    pruefe(status == 401, "eine neue Anmeldung damit auch")
    _, _, seite, _ = ruf("/presse/login")
    pruefe('name="email"' in seite and "Passwort vergessen" in seite,
           "die Anmeldeseite fragt nach Mailadresse und Passwort")
    _, _, seite, _ = ruf("/", keks=ada)
    pruefe("Hallo Ada" in seite and 'href="/konten"' in seite, "Ada sieht ihre Startseite")
    _, _, seite, _ = ruf("/helfer", keks=ada)
    pruefe(">AA<" in seite and 'href="/konto"' in seite,
           "im Bereich stehen Kürzel und „Mein Konto“ im Kopf")

    print("Eine Orga-Person nur für die Presse")
    konto_anlegen(ada, name="Pia Presse", email="pia@example.org", kuerzel="PP",
                  rolle="orga", bereiche=["presse"])
    pia_link = link_aus(letzte_mail("pia@example.org"))
    ruf(pia_link, "POST", {"neu": "pia-passwort-1", "wiederholung": "pia-passwort-1"})
    pia = anmelden("pia@example.org", "pia-passwort-1", "presse")
    pruefe(bool(pia), "Pia meldet sich im Pressebereich an")
    pruefe(ruf("/presse", keks=pia)[0] == 200, "die Presse ist offen")
    status, _, seite, _ = ruf("/kennzeichen", keks=pia)
    pruefe(status == 403 and "nicht freigegeben" in seite, "Kennzeichen nicht")
    pruefe(ruf("/helfer/schichten", keks=pia)[0] == 403, "Helfer auch nicht")
    status, _, seite, _ = ruf("/konten", keks=pia)
    pruefe(status == 403 and "nur ein Admin" in seite, "die Konten sind nur für Admins")
    _, _, seite, _ = ruf("/presse", keks=pia)
    pruefe('href="/kennzeichen"' not in seite and 'href="/konten"' not in seite,
           "die Navigation zeigt nur, was offen ist")

    print("Das Kürzel kommt aus dem Konto")
    ruf("/", "POST", {
        "vorname": "Bea", "nachname": "Blende", "firma": "Licht GmbH",
        "email": "bea@example.org", "kommerziell": "nein", "sicherheit": "1",
    }, host="presse.test")
    nummer = sql("presse", "SELECT max(id) FROM anmeldung")[0][0]
    pruefe(nummer is not None, "eine Presse-Anmeldung liegt vor")
    _, _, seite, _ = ruf(f"/presse/anmeldung/{nummer}", keks=pia)
    ruf(f"/presse/anmeldung/{nummer}/badge", "POST",
        {"csrf": csrf(seite), "ausgeben": "1", "zurueck": f"/presse/anmeldung/{nummer}"}, keks=pia)
    pruefe(sql("presse", "SELECT badge_durch FROM anmeldung WHERE id = ?", nummer)[0][0] == "PP",
           "die Badge-Ausgabe trägt Pias Kürzel, ohne dass sie es eingetippt hat")

    print("Veranstaltungen")
    _, _, seite, _ = ruf("/helfer", keks=ada)
    pruefe("Noch keine Veranstaltung" in seite,
           "ohne Veranstaltung sagt der Helferbereich, was zu tun ist")
    _, _, seite, _ = ruf("/veranstaltungen/neu", keks=ada)
    status, _, seite, _ = ruf("/veranstaltungen/neu", "POST", {
        "csrf": csrf(seite), "name": "Nichts", "kurz": "N", "beginn": "2027-01-01",
        "ende": "2027-01-01", "status": "planung"}, keks=ada)
    pruefe(status == 400 and "mindestens einen Bereich" in seite,
           "eine Veranstaltung, die nichts nutzt, gibt es nicht")
    # Die AA nutzt alles, der XCO nur Helfer und Materialausgabe (V-08).
    for name, kurz, beginn, ende, nutzt in (
            ("Die absolute Abfahrt 2027", "AA 2027", "2027-07-01", "2027-07-04",
             ("kennzeichen", "presse", "helfer", "ausgabe")),
            ("Cross-Country 2027", "XCO 2027", "2027-05-15", "2027-05-15", ("helfer", "ausgabe"))):
        _, _, seite, _ = ruf("/veranstaltungen/neu", keks=ada)
        status, ort, _, _ = ruf("/veranstaltungen/neu", "POST", {
            "csrf": csrf(seite), "name": name, "kurz": kurz, "beginn": beginn,
            "ende": ende, "ort": "Ilmenau", "status": "planung",
            **{"nutzt_" + b: "1" for b in nutzt}}, keks=ada)
        pruefe(status == 303, kurz + " angelegt")
    aa = sql("kern", "SELECT id FROM veranstaltung WHERE kurz = 'AA 2027'")[0][0]
    def gewaehlt_im_kopf(seite):
        treffer = re.search(r'title="Veranstaltung wechseln">\s*([^<]+?)\s*<', seite)
        return treffer.group(1) if treffer else ""

    def reiter(seite):
        stueck = seite[seite.index('class="bereiche"'):]
        return re.findall(r'class="bereich[^"]*"\s+href="[^"]*"[^>]*>([^<]+)</a>',
                          stueck[:stueck.index("</nav>")])

    _, _, seite, _ = ruf("/helfer", keks=ada)
    pruefe(gewaehlt_im_kopf(seite) == "XCO 2027",
           "ohne Wahl gilt die nächste, die noch nicht vorbei ist: der XCO")
    pruefe(reiter(seite) == ["Helfer", "Ausgabe", "Verwaltung"],
           "beim XCO nur die Reiter dessen, was er nutzt: " + ", ".join(reiter(seite)))
    _, _, seite, _ = ruf("/presse", keks=ada)
    pruefe(gewaehlt_im_kopf(seite) == "XCO 2027" and "Presse" not in reiter(seite),
           "die Auswahl steht auch über der Presse, deren Reiter dann fehlt")
    status, ort, _, gewaehlt = ruf(f"/veranstaltung?id={aa}&weiter=/presse", keks=ada)
    pruefe(status == 303 and ort == "/presse" and gewaehlt.startswith("abfahrt_veranstaltung="),
           "die Auswahl merkt sich der Browser, für alle Bereiche, und führt zurück")
    status, ort, _, _ = ruf(f"/veranstaltung?id={aa}&weiter=https://example.org/", keks=ada)
    pruefe(status == 303 and ort == "/", "nach draußen führt sie nicht")
    _, _, seite, _ = ruf("/helfer", keks=ada + "; " + gewaehlt)
    pruefe(gewaehlt_im_kopf(seite) == "AA 2027", "danach gilt die AA")
    pruefe(reiter(seite) == ["Kennzeichen", "Presse", "Helfer", "Ausgabe", "Verwaltung"],
           "und mit ihr alle Reiter")
    _, _, seite, _ = ruf(f"/veranstaltungen/{aa}", keks=ada + "; " + gewaehlt)
    gruppen = re.findall(r'>([^<]+)</a>', seite[seite.index('class="gruppen-nav"'):].split("</nav>")[0])
    pruefe(gruppen == ["AA 2027", "Alle Veranstaltungen", "Konten"],
           "unter Verwaltung die gewählte, alle und die Konten: " + ", ".join(gruppen))
    pruefe('href="/helfer/goodies"' in seite and 'href="/helfer/einstellungen"' in seite,
           "bei der Veranstaltung, was man für sie einrichtet")
    pruefe(ruf("/veranstaltungen", keks=pia)[0] == 403,
           "wer den Helferbereich nicht sieht, pflegt auch keine Veranstaltungen")

    print("Ein Lesekonto")
    konto_anlegen(ada, name="Lea Lesend", email="lea@example.org", kuerzel="LL",
                  rolle="lesend", bereiche=["kennzeichen"])
    ruf(link_aus(letzte_mail("lea@example.org")), "POST",
        {"neu": "lea-passwort-1", "wiederholung": "lea-passwort-1"})
    lea = anmelden("lea@example.org", "lea-passwort-1", "kennzeichen")
    status, _, seite, _ = ruf("/kennzeichen", keks=lea)
    pruefe(status == 200 and "nur lesen" in seite, "Lea sieht die Anträge, mit Hinweis im Kopf")
    _, _, seite, _ = ruf("/kennzeichen/einstellungen", keks=lea)
    status, _, seite, _ = ruf("/kennzeichen/einstellungen", "POST",
                              {"csrf": csrf(seite), "benachrichtigung": "x@example.org"}, keks=lea)
    pruefe(status == 403 and "nur lesen" in seite, "Ändern wird abgewiesen")
    _, _, seite, _ = ruf("/konto", keks=lea)
    status, ort, _, _ = ruf("/konto/passwort", "POST", {
        "csrf": csrf(seite), "alt": "lea-passwort-1",
        "neu": "lea-passwort-2", "wiederholung": "lea-passwort-2"}, keks=lea)
    pruefe(status == 303 and "passwort" in ort, "ihr eigenes Passwort ändert sie trotzdem")
    pruefe(bool(anmelden("lea@example.org", "lea-passwort-2", "kennzeichen")),
           "und meldet sich damit an")

    print("Eine Bereichsleitung")
    konto_anlegen(ada, name="Kalle Beispiel", email="kalle@example.org", kuerzel="KB",
                  rolle="bereichsleitung", bereiche=["presse"], telefon="0151 000000")
    pruefe(sql("kern", "SELECT bereiche, telefon FROM konto WHERE kuerzel = 'KB'")[0]
           == {"bereiche": ["helfer"], "telefon": "0151 000000"},
           "das Formular legt sie mit Nummer an, nur für den Helferbereich")
    pruefe("Bereichsleitung – sieht im Helferbereich nur die Bereiche"
           in letzte_mail("kalle@example.org")["text"],
           "die Einladung erklärt die Rolle")
    ruf(link_aus(letzte_mail("kalle@example.org")), "POST",
        {"neu": "kalle-passwort-1", "wiederholung": "kalle-passwort-1"})
    kalle = anmelden("kalle@example.org", "kalle-passwort-1", "helfer")
    pruefe(bool(kalle), "Kalle meldet sich im Helferbereich an")
    pruefe(ruf("/veranstaltungen", keks=kalle)[0] == 403,
           "Veranstaltungen pflegt eine Bereichsleitung nicht")
    _, _, seite, _ = ruf("/", keks=kalle)
    pruefe('href="/helfer"' in seite and 'href="/veranstaltungen"' not in seite,
           "auf der Startseite nur der Helferbereich")
    pruefe(ruf("/helfer/funk", keks=kalle)[0] == 403, "die Ausgabetische nicht")
    _, _, seite, _ = ruf("/konto", keks=kalle)
    status, ort, _, _ = ruf("/konto/telefon", "POST",
                            {"csrf": csrf(seite), "telefon": "0151 111111"}, keks=kalle)
    pruefe(status == 303 and "telefon" in ort
           and sql("kern", "SELECT telefon FROM konto WHERE kuerzel = 'KB'")[0][0]
           == "0151 111111", "seine Nummer pflegt Kalle selbst")

    print("Sperren wirkt sofort")
    _, _, seite, _ = ruf("/konten/2", keks=ada)
    status, _, _, _ = ruf("/konten/2", "POST", {
        "csrf": csrf(seite), "name": "Pia Presse", "email": "pia@example.org",
        "kuerzel": "PP", "rolle": "orga", "bereich_presse": "1"}, keks=ada)
    pruefe(status == 303, "Pia gesperrt (Haken „aktiv“ weg)")
    status, ort, _, _ = ruf("/presse", keks=pia)
    pruefe(status == 303 and "login" in ort, "ihre offene Sitzung ist beendet")
    pruefe(not anmelden("pia@example.org", "pia-passwort-1", "presse"), "anmelden geht nicht")

    print("Der letzte Admin bleibt Admin")
    _, _, seite, _ = ruf("/konten/1", keks=ada)
    status, _, seite, _ = ruf("/konten/1", "POST", {
        "csrf": csrf(seite), "name": "Ada Admin", "email": "ada@example.org",
        "kuerzel": "AA", "rolle": "orga", "bereich_presse": "1", "aktiv": "1"}, keks=ada)
    pruefe(status == 400 and "letzte Admin" in seite, "Ada kann sich nicht selbst herabstufen")

    print("Passwort vergessen")
    vorher = len(empfangen)
    _, _, seite, _ = ruf("/konto/vergessen", "POST", {"email": "gibt-es@nicht.org"})
    pruefe("Wenn es zu" in seite, "unbekannte Adresse: dieselbe Antwort")
    _, _, seite, _ = ruf("/konto/vergessen", "POST", {"email": "Ada@Example.org"})
    mail = letzte_mail("ada@example.org")
    pruefe("Wenn es zu" in seite and len(empfangen) == vorher + 1 and "Neues Passwort" in mail["betreff"],
           "bekannte Adresse: genau eine Mail, an Ada")
    status, _, _, ada2 = ruf(link_aus(mail), "POST", {"neu": "ada-passwort-2",
                                                      "wiederholung": "ada-passwort-2"})
    pruefe(status == 303 and ada2, "neues Passwort über den Link")
    pruefe(ruf("/", keks=ada)[0] == 303, "die alte Sitzung ist damit beendet")
    pruefe(not anmelden("ada@example.org", "ada-passwort-1"), "das alte Passwort gilt nicht mehr")
    ada = anmelden("ada@example.org", "ada-passwort-2")
    pruefe(bool(ada), "das neue schon")

    print("Ohne CSRF-Token passiert nichts")
    status, _, _, _ = ruf("/konten/neu", "POST", {"name": "X", "email": "x@example.org",
                                                  "kuerzel": "X", "rolle": "admin"}, keks=ada)
    pruefe(status == 303 and not sql("kern", "SELECT 1 FROM konto WHERE email = 'x@example.org'"),
           "kein Konto angelegt")

    print("Geht die Mail nicht hinaus, bekommt der Admin den Link")
    smtp.shutdown()
    smtp.server_close()
    status, _, seite, _ = konto_anlegen(ada, name="Max Mailfrei", email="max@example.org",
                                        kuerzel="MM", rolle="orga", bereiche=["helfer"])
    pruefe(status == 200 and "/konto/passwort/" in seite and "nicht hinaus" in seite,
           "die Seite zeigt den Link zum Weitergeben")

    print("Fehlversuche je Mailadresse")
    for _ in range(3):
        ruf("/konto/login", "POST", {"email": "lea@example.org", "passwort": "falsch-falsch"})
    status, _, _, _ = ruf("/konto/login", "POST",
                          {"email": "lea@example.org", "passwort": "lea-passwort-2"})
    pruefe(status == 429, "nach drei Fehlversuchen ist erst einmal Pause")

finally:
    prozess.terminate()
    try:
        prozess.wait(timeout=10)
    except subprocess.TimeoutExpired:
        prozess.kill()

print()
if fehler:
    print("FEHLGESCHLAGEN (" + str(len(fehler)) + "):")
    for eintrag in fehler:
        print("  - " + eintrag)
    sys.exit(1)
print("alle Pruefungen bestanden")
