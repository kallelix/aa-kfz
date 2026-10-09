"""Der zusammengesetzte Dienst: Verteilung nach Hostname, eine Anmeldung.

    python tests/test_dienst.py

Startet den Dienst selbst mit einer Wegwerf-Datenbank und prüft das, was durch
die Zusammenführung neu ist – nicht noch einmal, was die drei Anwendungen
je für sich schon prüfen.
"""

import http.client
import os
import socket
import subprocess
import sys
import tempfile
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


def freier_hafen():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PASSWORT = "dienst-test-123"
HASH = subprocess.run(
    [str(PYTHON), "-m", "kern.passwort", PASSWORT],
    cwd=str(WURZEL), capture_output=True, text=True,
    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
).stdout.strip().split("=", 1)[1]

verzeichnis = Path(tempfile.mkdtemp(prefix="dienst-"))
DB = testdb.wegwerf("dienst")
hafen = freier_hafen()

# Je Anwendung eine eigene Datei mit eigenen Werten - genau der Fall, der in
# einem Prozess vorher nicht ging. Die Datenbank teilen sich alle drei.
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
    "APP_SECRET_KEY": "gemeinsamer-test-schluessel",
    "COOKIE_SECURE": "0",
    # Ausdruecklich setzen: ohne DATABASE_URL griffe jeder Bereich zur
    # Entwicklungsdatenbank aus compose.yaml.
    "DATABASE_URL": DB,
    "KENNZEICHEN_ENV": str(verzeichnis / "kennzeichen.env"),
    "PRESSE_ENV": str(verzeichnis / "presse.env"),
    "HELFER_ENV": str(verzeichnis / "helfer.env"),
}
umgebung.pop("JETZT_FEST", None)

prozess = subprocess.Popen(
    [str(PYTHON), "-m", "dienst"], cwd=str(WURZEL), env=umgebung,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ruf(host, pfad, methode="GET", daten=None, keks=""):
    c = http.client.HTTPConnection("127.0.0.1", hafen, timeout=15)
    koerper = urllib.parse.urlencode(daten).encode() if daten else None
    kopf = {"Host": host}
    if daten:
        kopf["Content-Type"] = "application/x-www-form-urlencoded"
    if keks:
        kopf["Cookie"] = keks
    c.request(methode, pfad, body=koerper, headers=kopf)
    r = c.getresponse()
    ergebnis = (r.status, r.getheader("Location", ""),
                r.read().decode("utf-8", "replace"), r.getheader("Set-Cookie", ""))
    c.close()
    return ergebnis


try:
    for _ in range(150):
        try:
            with socket.create_connection(("127.0.0.1", hafen), timeout=0.2):
                break
        except OSError:
            time.sleep(0.2)
    else:
        raise RuntimeError("Dienst ist nicht hochgekommen")

    print("Jede Anwendung hat ihr eigenes Schema")
    # Eine Datenbank, drei Bereiche darin. Jeder spielt beim Start seine
    # Migrationen selbst ein.
    schemas = {z[0] for z in testdb.abfrage(
        DB, "public", "SELECT table_schema FROM information_schema.tables"
        " WHERE table_name = 'migration'")}
    for name in ("kennzeichen", "presse", "helfer"):
        pruefe(name in schemas, "Schema " + name + " ist angelegt")
    pruefe(testdb.abfrage(DB, "helfer", "SELECT COUNT(*) FROM schicht")[0][0] == 0,
           "und die Tabellen liegen im richtigen")

    print("Oeffentliche Seiten haengen am Hostnamen")
    status, _, seite, _ = ruf("kennzeichen.test", "/")
    pruefe(status == 200 and "Kennzeichen" in seite,
           "kennzeichen.test zeigt das Antragsformular")
    status, _, seite, _ = ruf("presse.test", "/")
    pruefe(status == 200 and "Presse" in seite,
           "presse.test zeigt die Akkreditierung")

    print("Das Backoffice liegt unter einer eigenen Adresse")
    status, ort, _, _ = ruf("admin.test", "/")
    pruefe(status == 303 and ort.startswith("/konto/login"),
           "admin.test fuehrt ohne Anmeldung zur Anmeldung")

    print("Ohne Anmeldung kommt niemand hinein")
    for pfad, bereich in (("/kennzeichen", "kennzeichen"),
                          ("/kennzeichen/antrag/neu", "kennzeichen"),
                          ("/presse", "presse"), ("/presse/abholung", "presse"),
                          ("/helfer", "helfer"), ("/helfer/schichten", "helfer")):
        status, ort, _, _ = ruf("admin.test", pfad)
        pruefe(status == 303 and ort.startswith("/" + bereich + "/login"),
               pfad + " fuehrt zur Anmeldung des eigenen Bereichs: " + ort)

    print("Die Anmeldeseite gehoert zu ihrem Bereich")
    # Die Vorlage ist gemeinsam, ihr Formularziel darf es nicht sein. Sie
    # kam mit kern/ aus der Zeit vor der Pfadumbenennung und schickte noch
    # an /admin/login - das gibt es nicht mehr, und niemand kam hinein.
    for bereich in ("kennzeichen", "presse", "helfer"):
        status, _, seite, _ = ruf("admin.test", "/%s/login?weiter=/%s"
                                  % (bereich, bereich))
        pruefe(status == 200, "/" + bereich + "/login laedt")
        pruefe(('action="/%s/login"' % bereich) in seite,
               "und schickt an den eigenen Bereich zurueck")
        pruefe('href="/static/admin.css"' in seite,
               "auch die Anmeldeseite hat ihr Stilblatt")

    print("Einmal anmelden reicht fuer alle drei")
    status, ort, _, gesetzt = ruf(
        "admin.test", "/helfer/login", "POST",
        {"passwort": PASSWORT, "kuerzel": "KK", "weiter": "/helfer"})
    pruefe(status == 303, "die Anmeldung im Helferbereich klappt")
    keks = gesetzt.split(";")[0]
    # Der Keks muss fuer die ganze Adresse gelten, sonst schickte ihn der
    # Browser in den anderen beiden Bereichen gar nicht erst mit.
    pruefe("Path=/;" in gesetzt or gesetzt.rstrip().endswith("Path=/"),
           "und der Keks gilt fuer die ganze Adresse: " + gesetzt[:70])

    for bereich in ("kennzeichen", "presse", "helfer"):
        status, ort, _, _ = ruf("admin.test", "/" + bereich, keks=keks)
        pruefe(status == 200,
               "/" + bereich + " ist ohne zweite Anmeldung offen")
    status, _, seite, _ = ruf("admin.test", "/", keks=keks)
    pruefe(status == 200 and all(('href="/%s"' % b) in seite
                                 for b in ("kennzeichen", "presse", "helfer")),
           "die Startseite zeigt danach alle drei Bereiche")

    print("Das Backoffice ist eine Oberflaeche")
    # Genau der Fehler, der beim ersten Zusammenbau durchrutschte: die
    # Vorlagen verwiesen auf /static/style.css, der Verteiler waehlt aber am
    # ersten Pfadstueck - und "static" ist keiner der drei Bereiche. Das
    # Backoffice kam ohne jedes Stilblatt.
    status, _, seite, _ = ruf("admin.test", "/static/admin.css", keks=keks)
    pruefe(status == 200 and len(seite) > 10000,
           "das gemeinsame Stilblatt kommt an (%d Bytes)" % len(seite))
    status, _, seite, _ = ruf("admin.test", "/static/ilrc-logo.svg", keks=keks)
    pruefe(status == 200, "das Wappen auch")

    for bereich, datei in (("helfer", "liste.js"), ("presse", "liste.js")):
        status, _, _, _ = ruf("admin.test", "/%s/static/%s" % (bereich, datei),
                              keks=keks)
        pruefe(status == 200,
               "was nur einen Bereich betrifft, liegt unter seinem Pfad: "
               + bereich + "/static/" + datei)

    for bereich, name in (("kennzeichen", "Kennzeichen"), ("presse", "Presse"),
                          ("helfer", "Helfer")):
        status, _, seite, _ = ruf("admin.test", "/" + bereich, keks=keks)
        pruefe('href="/static/admin.css"' in seite,
               "/" + bereich + " holt dasselbe Stilblatt")
        pruefe('class="bereiche"' in seite,
               "und zeigt die Zeile zum Wechseln der Bereiche")
        # Der offene Bereich ist markiert, die anderen zwei sind Links.
        marke = 'class="bereich ist-hier"'
        pruefe(seite.count(marke) == 1,
               "genau ein Bereich ist hervorgehoben")
        anfang = seite.index('class="bereiche"')
        zeile = seite[anfang:seite.index("</nav>", anfang)]
        pruefe(all(('"/%s"' % b) in zeile for b in ("kennzeichen", "presse", "helfer")),
               "und von jedem Bereich kommt man in die anderen beiden")

    print("Verweise aus dem Formular zeigen ins Backoffice")
    # Das Formular kommt ueber kennzeichen.test, die Meldung an die Orga
    # verweist aber in die Detailansicht - und die liegt unter admin.test.
    # Auf der oeffentlichen Adresse gaebe nginx dort 404.
    status, _, seite, _ = ruf("admin.test", "/kennzeichen/einstellungen", keks=keks)
    marke = seite.split('name="csrf" value="', 1)
    csrf = marke[1].split('"', 1)[0] if len(marke) > 1 else ""
    status, _, _, _ = ruf("admin.test", "/kennzeichen/einstellungen", "POST",
                          {"csrf": csrf, "benachrichtigung": "orga@example.org"},
                          keks=keks)
    pruefe(status == 303, "die Orga-Adresse ist gepflegt")
    status, _, _, _ = ruf("kennzeichen.test", "/", "POST", {
        "vorname": "Vera", "nachname": "Verweis", "funktion": "Aufbau",
        "kategorie": "camping", "kennzeichen": "KA-VV 1",
        "email": "vera@example.org"})
    pruefe(status == 303, "ein Antrag ueber die oeffentliche Adresse")
    zeilen = testdb.abfrage(DB, "kennzeichen",
                            "SELECT body FROM mail_out WHERE typ = 'orga'")
    text = zeilen[0][0] if zeilen else ""
    pruefe("http://admin.test/kennzeichen/antrag/" in text,
           "die Meldung verweist auf admin.test")
    pruefe("kennzeichen.test/kennzeichen" not in text,
           "und nicht auf die oeffentliche Adresse")

    print("Ein falscher Keks kommt nirgends durch")
    kaputt = keks[:-4] + "xxxx"
    status, ort, _, _ = ruf("admin.test", "/presse", keks=kaputt)
    pruefe(status == 303, "veraenderte Unterschrift wird abgewiesen")

    print("Abmelden gilt ebenfalls fuer alle drei")
    status, _, seite, _ = ruf("admin.test", "/presse", keks=keks)
    marke = seite.split('name="csrf" value="', 1)
    csrf = marke[1].split('"', 1)[0] if len(marke) > 1 else ""
    status, ort, _, geloescht = ruf("admin.test", "/presse/logout", "POST",
                                    {"csrf": csrf}, keks=keks)
    pruefe(status == 303, "das Abmelden im Pressebereich klappt")
    pruefe("Path=/" in geloescht,
           "und raeumt den Keks fuer die ganze Adresse weg")

    print("Ein unbekannter Hostname fuehrt nicht ins Leere")
    status, ort, _, _ = ruf("irgendwas.test", "/")
    pruefe(status == 303 and ort.startswith("/konto/login"),
           "es geht zur Anmeldung, kein Fehler")

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
