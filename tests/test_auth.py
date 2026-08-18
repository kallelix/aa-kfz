"""Einheitentests für app/auth.py – ohne laufenden Server.

    python tests/test_auth.py
"""

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("APP_SECRET_KEY", "test-schluessel-fuer-die-pruefung")
os.environ.setdefault("ADMIN_PASSWORD_HASH", "")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import auth, config  # noqa: E402

fehler = []


def pruefe(bedingung, text):
    print(("  ok   " if bedingung else "  FEHL ") + text)
    if not bedingung:
        fehler.append(text)


print("Passwort")
hash_ = auth.hash_erzeugen("geheim-123")
config.ADMIN_PASSWORD_HASH = hash_
pruefe(auth.passwort_pruefen("geheim-123"), "richtiges Passwort wird akzeptiert")
pruefe(not auth.passwort_pruefen("geheim-124"), "falsches Passwort wird abgelehnt")
pruefe(not auth.passwort_pruefen(""), "leeres Passwort wird abgelehnt")
config.ADMIN_PASSWORD_HASH = "kein-gueltiger-hash"
pruefe(not auth.passwort_pruefen("geheim-123"), "kaputter Hash faellt nicht auf die Nase")
config.ADMIN_PASSWORD_HASH = hash_
pruefe(auth.eingerichtet(), "eingerichtet() erkennt gesetzten Hash")

print("Token")
token = auth.token_erzeugen("KK")
sitzung = auth.token_pruefen(token)
pruefe(sitzung is not None and sitzung.kuerzel == "KK", "gueltiges Token traegt das Kuerzel")
pruefe(
    auth.token_pruefen(token[:-1] + ("x" if token[-1] != "x" else "y")) is None,
    "veraenderte Signatur wird abgelehnt",
)
_, signatur = token.split(".")
gefaelscht = auth._b64(b'{"k":"BOESE","exp":9999999999}') + "." + signatur
pruefe(auth.token_pruefen(gefaelscht) is None, "getauschte Nutzlast wird abgelehnt")
pruefe(auth.token_pruefen("") is None, "leeres Token wird abgelehnt")
pruefe(auth.token_pruefen("kein.punkt.token") is None, "Unfug wird abgelehnt")

vorher = config.SESSION_STUNDEN
config.SESSION_STUNDEN = 0
abgelaufen = auth.token_erzeugen("KK")
time.sleep(1.1)
pruefe(auth.token_pruefen(abgelaufen) is None, "abgelaufenes Token wird abgelehnt")
config.SESSION_STUNDEN = vorher

print("CSRF")
sitzung = auth.token_pruefen(auth.token_erzeugen("KK"))
richtig = auth.csrf_token(sitzung.token)
pruefe(auth.csrf_pruefen(sitzung, richtig), "eigener CSRF-Token passt")
pruefe(not auth.csrf_pruefen(sitzung, "falsch"), "fremder CSRF-Token passt nicht")
pruefe(not auth.csrf_pruefen(sitzung, None), "fehlender CSRF-Token passt nicht")
andere = auth.token_pruefen(auth.token_erzeugen("XY"))
pruefe(not auth.csrf_pruefen(andere, richtig), "CSRF-Token einer anderen Sitzung passt nicht")

print("Rate Limit")
config.LOGIN_VERSUCHE = 3
ip = "10.0.0.1"
pruefe(not auth.login_gesperrt(ip), "frische IP ist nicht gesperrt")
for _ in range(3):
    auth.login_fehlversuch(ip)
pruefe(auth.login_gesperrt(ip), "nach 3 Fehlversuchen gesperrt")
pruefe(not auth.login_gesperrt("10.0.0.2"), "andere IP bleibt frei")
auth.login_zuruecksetzen(ip)
pruefe(not auth.login_gesperrt(ip), "Ruecksetzen hebt die Sperre auf")

config.LOGIN_FENSTER_SEKUNDEN = 1
for _ in range(3):
    auth.login_fehlversuch(ip)
pruefe(auth.login_gesperrt(ip), "gesperrt im Fenster")
time.sleep(1.2)
pruefe(not auth.login_gesperrt(ip), "Sperre laeuft nach dem Fenster aus")

print()
print("FEHLGESCHLAGEN: " + str(len(fehler)) if fehler else "alle Pruefungen bestanden")
sys.exit(1 if fehler else 0)
