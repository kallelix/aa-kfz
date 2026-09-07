"""Der zusammengesetzte Dienst: Verteilung nach Hostname, eine Anmeldung.

    python tests/test_dienst.py

Startet den Dienst selbst mit Wegwerf-Datenbanken und prüft das, was durch
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
hafen = freier_hafen()

# Je Anwendung eine eigene Datei mit eigener Datenbank - genau der Fall, der
# in einem Prozess vorher nicht ging.
for name in ("kennzeichen", "presse", "helfer"):
    (verzeichnis / (name + ".env")).write_text(
        "DB_PATH=" + str(verzeichnis / (name + ".db")) + "\n"
        "COOKIE_SECURE=0\n"
        + ("TAGE=2026-08-28,2026-08-29,2026-08-30\n" if name == "helfer" else ""),
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
    "KENNZEICHEN_ENV": str(verzeichnis / "kennzeichen.env"),
    "PRESSE_ENV": str(verzeichnis / "presse.env"),
    "HELFER_ENV": str(verzeichnis / "helfer.env"),
}
# Nicht erben, sonst zeigte ein gesetztes DB_PATH alle drei auf dieselbe Datei.
umgebung.pop("DB_PATH", None)
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

    print("Jede Anwendung hat ihre eigene Datenbank")
    # Der Kern der Zusammenfuehrung: drei Konfigurationen in einem Prozess.
    for name in ("kennzeichen", "presse", "helfer"):
        pruefe((verzeichnis / (name + ".db")).exists(),
               name + ".db ist angelegt")

    print("Oeffentliche Seiten haengen am Hostnamen")
    status, _, seite, _ = ruf("kennzeichen.test", "/")
    pruefe(status == 200 and "Kennzeichen" in seite,
           "kennzeichen.test zeigt das Antragsformular")
    status, _, seite, _ = ruf("presse.test", "/")
    pruefe(status == 200 and "Presse" in seite,
           "presse.test zeigt die Akkreditierung")

    print("Das Backoffice liegt unter einer eigenen Adresse")
    status, _, seite, _ = ruf("admin.test", "/")
    pruefe(status == 200 and seite.count('<a href="/') >= 3,
           "admin.test zeigt die Startseite mit allen drei Bereichen")

    print("Ohne Anmeldung kommt niemand hinein")
    for bereich in ("kennzeichen", "presse", "helfer"):
        status, ort, _, _ = ruf("admin.test", "/" + bereich)
        pruefe(status == 303 and ort.startswith("/" + bereich + "/login"),
               "/" + bereich + " fuehrt zur Anmeldung")

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
    status, _, seite, _ = ruf("irgendwas.test", "/")
    pruefe(status == 200, "es kommt eine Seite, kein Fehler")

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
print("Wegwerf-Verzeichnis lag in " + str(verzeichnis))
