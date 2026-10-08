"""Backoffice-Konten von der Kommandozeile – für den ersten Admin und den Notfall.

    python -m kern.konto admin              # Admin anlegen oder wiederherstellen
    python -m kern.konto passwort <mail>    # Passwort neu setzen
    python -m kern.konto liste

Im Normalfall braucht es das nicht: Konten legt ein Admin im Backoffice unter
/konten an, und solange es noch keinen Admin gibt, kommt man dort mit dem
gemeinsamen Passwort hinein. Dieses Werkzeug ist für den Fall, dass niemand
mehr hineinkommt – etwa weil der einzige Admin sein Passwort vergessen hat
und die Mail nicht ankommt.

Die Datenbank kommt aus DATABASE_URL, sonst der Entwicklungs-Container. Auf
dem Server als Benutzer abfahrt aufrufen, siehe deploy/README.md.
"""

from __future__ import annotations

import getpass
import os
import sys

from kern.db import ENTWICKLUNG_URL
from kern.konten import ROLLEN, Fehler, Konten


def _konten() -> Konten:
    konten = Konten(lambda: os.environ.get("DATABASE_URL", "").strip() or ENTWICKLUNG_URL)
    konten.init()
    return konten


def _passwort_abfragen() -> str | None:
    passwort = getpass.getpass("Neues Passwort: ")
    if passwort != getpass.getpass("Wiederholen: "):
        print("Die Eingaben stimmen nicht überein.", file=sys.stderr)
        return None
    return passwort


def admin() -> int:
    konten = _konten()
    email = input("Mailadresse: ").strip()
    vorhanden = konten.nach_email(email)
    if vorhanden is not None:
        print(f"Das Konto gibt es: {vorhanden['name']} ({vorhanden['kuerzel']}). "
              "Es wird Admin, wird entsperrt und bekommt ein neues Passwort.")
        name, kuerzel = vorhanden["name"], vorhanden["kuerzel"]
    else:
        name = input("Name: ").strip()
        kuerzel = input("Kürzel (z. B. KK): ").strip()
    passwort = _passwort_abfragen()
    if passwort is None:
        return 1
    try:
        if vorhanden is None:
            konto_id = konten.anlegen(email=email, name=name, kuerzel=kuerzel,
                                      rolle="admin", von="Kommandozeile",
                                      passwort=passwort)
        else:
            konto_id = vorhanden["id"]
            konten.aendern(konto_id, email=email, name=name, kuerzel=kuerzel,
                           rolle="admin", bereiche=vorhanden["bereiche"], aktiv=True)
            konten.passwort_setzen(konto_id, passwort)
    except Fehler as fehler:
        print(str(fehler), file=sys.stderr)
        return 1
    print(f"Admin-Konto {konto_id} bereit. Das gemeinsame Passwort gilt ab jetzt nicht mehr.")
    return 0


def passwort(email: str) -> int:
    konten = _konten()
    konto = konten.nach_email(email)
    if konto is None:
        print("Kein Konto mit dieser Adresse.", file=sys.stderr)
        return 1
    neu = _passwort_abfragen()
    if neu is None:
        return 1
    try:
        konten.passwort_setzen(konto["id"], neu)
    except Fehler as fehler:
        print(str(fehler), file=sys.stderr)
        return 1
    print("Passwort gesetzt, alle Sitzungen des Kontos sind beendet.")
    return 0


def liste() -> int:
    for k in _konten().liste():
        zustand = "aktiv" if k["aktiv"] else "gesperrt"
        if not k["hat_passwort"]:
            zustand += ", Einladung offen"
        bereiche = "alle" if k["rolle"] == "admin" else ", ".join(k["bereiche"])
        print(f"{k['kuerzel']:<6} {k['email']:<32} {ROLLEN[k['rolle']]:<7} "
              f"{bereiche:<28} {zustand}")
    return 0


def main(argumente: list[str]) -> int:
    if argumente == ["admin"]:
        return admin()
    if len(argumente) == 2 and argumente[0] == "passwort":
        return passwort(argumente[1])
    if argumente == ["liste"]:
        return liste()
    print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
