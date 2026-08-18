"""Legt drei Testanträge über das öffentliche Formular an.

Erwartet einen laufenden Server (siehe tests/README.md). Die Reihenfolge ist
wichtig: tests/test_http.py rechnet mit den Nummern 1 bis 3.
"""

import os
import urllib.parse
import urllib.request

BASIS = os.environ.get("TEST_BASIS", "http://127.0.0.1:8099")

ANTRAEGE = [
    {
        "vorname": "Max", "nachname": "Mustermann", "funktion": "Sanität",
        "kategorie": "camping", "telefon": "0171 1234567",
        "kennzeichen": "ka-xy 123", "bemerkung": "Kommt Freitag",
    },
    {
        "vorname": "Erika", "nachname": "Beispiel", "funktion": "Presse",
        "kategorie": "vip", "email": "Erika@Example.ORG",
        "kennzeichen": "F-EB 200",
    },
    {
        "vorname": "Jörg", "nachname": "Weiß", "funktion": "Aufbau",
        "kategorie": "camping", "email": "joerg@example.org",
        "kennzeichen": "HD-JW 30",
        "bemerkung": "Straße 5 – Zufahrt über Süd",
    },
]

for eintrag in ANTRAEGE:
    daten = urllib.parse.urlencode(eintrag, encoding="utf-8").encode("utf-8")
    with urllib.request.urlopen(urllib.request.Request(BASIS + "/", data=daten)) as antwort:
        print(eintrag["nachname"], "->", antwort.status, antwort.url)
