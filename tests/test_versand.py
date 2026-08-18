"""Echter SMTP-Versand gegen einen Wegwerf-Server im selben Prozess.

    python tests/test_versand.py

Prüft, dass smtplib-Weg, Kopfzeilen und der Worker-Lauf zusammenpassen –
ohne je eine Mail nach draußen zu schicken.
"""

import asyncio
import os
import socket
import socketserver
import sys
import tempfile
import threading
from email import message_from_string, policy
from pathlib import Path

TEMP = Path(tempfile.mkdtemp(prefix="abfahrt-versand-"))
os.environ["DB_PATH"] = str(TEMP / "test.db")
os.environ["APP_SECRET_KEY"] = "test"
os.environ["SMTP_HOST"] = "127.0.0.1"
os.environ["SMTP_TLS"] = "keine"
os.environ["SMTP_USER"] = ""
os.environ["MAIL_FROM"] = "Absolute Abfahrt <kennzeichen@example.org>"
os.environ["MAIL_REPLY_TO"] = "orga@example.org"
os.environ["MAIL_INTERVALL"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

fehler = []
empfangen = []


def pruefe(bedingung, text):
    print(("  ok   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        fehler.append(text)


class SmtpAttrappe(socketserver.StreamRequestHandler):
    """Spricht gerade so viel SMTP, dass smtplib zufrieden ist."""

    def handle(self):
        self.wfile.write(b"220 attrappe bereit\r\n")
        umschlag = {"von": "", "an": []}
        while True:
            zeile = self.rfile.readline()
            if not zeile:
                return
            befehl = zeile.decode("utf-8", "replace").strip()
            gross = befehl.upper()
            if gross.startswith(("EHLO", "HELO")):
                self.wfile.write(b"250-attrappe\r\n250 SIZE 10485760\r\n")
            elif gross.startswith("MAIL FROM"):
                umschlag["von"] = befehl
                self.wfile.write(b"250 ok\r\n")
            elif gross.startswith("RCPT TO"):
                umschlag["an"].append(befehl)
                self.wfile.write(b"250 ok\r\n")
            elif gross == "DATA":
                self.wfile.write(b"354 los\r\n")
                zeilen = []
                while True:
                    rohzeile = self.rfile.readline()
                    if not rohzeile or rohzeile in (b".\r\n", b".\n"):
                        break
                    zeilen.append(rohzeile.decode("utf-8", "replace"))
                empfangen.append({"umschlag": dict(umschlag), "text": "".join(zeilen)})
                self.wfile.write(b"250 angenommen\r\n")
            elif gross == "QUIT":
                self.wfile.write(b"221 tschuess\r\n")
                return
            else:
                self.wfile.write(b"250 ok\r\n")


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    PORT = probe.getsockname()[1]

os.environ["SMTP_PORT"] = str(PORT)

server = Server(("127.0.0.1", PORT), SmtpAttrappe)
threading.Thread(target=server.serve_forever, daemon=True).start()

from app import config, db, mail, worker  # noqa: E402

db.init()
pruefe(config.MAIL_AKTIV, "MAIL_AKTIV ist gesetzt")

antrag_id = db.antrag_anlegen(
    {"vorname": "Erika", "nachname": "Beispiel", "funktion": "Presse",
     "kategorie": "vip", "email": "erika@example.org", "telefon": "",
     "kennzeichen": "F-EB 200", "bemerkung": ""},
    None,
)
antrag = db.antrag_laden(antrag_id)

print("Versand")
db.mail_einreihen(antrag_id, mail.fuer(antrag, "eingang"))
gesendet, misslungen = worker.runde()
pruefe(gesendet == 1 and misslungen == 0, "Worker verschickt die Mail")
pruefe(len(empfangen) == 1, "die Attrappe hat sie bekommen")

nachricht = message_from_string(empfangen[0]["text"], policy=policy.default)
pruefe(nachricht["From"] == config.MAIL_FROM, "From stimmt: " + str(nachricht["From"]))
pruefe(nachricht["To"] == "erika@example.org", "To stimmt")
pruefe(nachricht["Reply-To"] == "orga@example.org", "Reply-To stimmt")
pruefe(nachricht["Auto-Submitted"] == "auto-generated", "Auto-Submitted verhindert Autoantworten")
from email.utils import parseaddr  # noqa: E402

absenderbereich = parseaddr(config.MAIL_FROM)[1].partition("@")[2]
pruefe((nachricht["Message-ID"] or "").endswith("@" + absenderbereich + ">"),
       "Message-ID traegt die Absenderdomain " + absenderbereich + ": "
       + str(nachricht["Message-ID"]))
pruefe(bool(nachricht["Date"]), "Date ist gesetzt")
pruefe(nachricht.get_content_type() == "text/plain", "reiner Text")
pruefe("erika@example.org" in empfangen[0]["umschlag"]["an"][0], "Umschlagempfaenger stimmt")
inhalt = nachricht.get_content()
pruefe("Erika Beispiel" in inhalt and "VIP" in inhalt, "Inhalt passt")
pruefe("ä" in inhalt or "Grüße" in inhalt, "Umlaute kommen heil an")

zeile = db.mails_zu_antrag(antrag_id)[0]
pruefe(zeile["gesendet_am"] is not None, "Zeile ist als gesendet markiert")
pruefe(db.mails_faellig() == [], "nichts mehr faellig")

print("Fehlerfall")
server.shutdown()
server.server_close()
db.mail_einreihen(antrag_id, mail.fuer(antrag, "genehmigt"))
gesendet, misslungen = worker.runde()
pruefe(gesendet == 0 and misslungen == 1, "abgeschalteter Server -> Fehlversuch")
zeile = db.mails_zu_antrag(antrag_id)[1]
pruefe(zeile["versuche"] == 1 and zeile["letzter_fehler"], "Fehler ist notiert: " + str(zeile["letzter_fehler"])[:60])
pruefe(zeile["naechster_versuch"] is not None, "Backoff ist gesetzt")
pruefe(db.mails_faellig() == [], "waehrend des Backoffs nicht faellig")

print("Worker-Schleife")


async def schleife_starten_und_stoppen():
    stop = asyncio.Event()
    aufgabe = asyncio.create_task(worker.schleife(stop))
    await asyncio.sleep(0.2)
    laeuft = not aufgabe.done()
    stop.set()
    await asyncio.wait_for(aufgabe, timeout=5)
    return laeuft, aufgabe.done()


laeuft, beendet = asyncio.run(schleife_starten_und_stoppen())
pruefe(laeuft, "Schleife laeuft nach dem Start")
pruefe(beendet, "Schleife beendet sich auf Zuruf")

print()
if fehler:
    print("FEHLGESCHLAGEN (" + str(len(fehler)) + "):")
    for eintrag in fehler:
        print("  - " + eintrag)
else:
    print("alle Pruefungen bestanden")
print("Wegwerf-Datenbank lag in " + str(TEMP))
sys.exit(1 if fehler else 0)
