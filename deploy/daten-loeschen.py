#!/usr/bin/env python3
"""Personendaten nach der Veranstaltung löschen.

    python3 deploy/daten-loeschen.py --art helfer --db /var/lib/helfer/helfer.db
    python3 deploy/daten-loeschen.py --art helfer --db … --wirklich

Ohne ``--wirklich`` wird nichts geschrieben: der Aufruf zeigt nur, was
verschwinden würde. Das ist Absicht – ein Löschlauf lässt sich nicht
zurücknehmen, und die Zahlen davor sind die einzige Gelegenheit, es zu merken.

Warum überhaupt: den Antragstellern der Kennzeichen-App ist zugesagt, dass
ihre Daten „spätestens vier Wochen nach der Veranstaltung" gelöscht werden,
und den Helfern am Unterschriften-Tablet, dass die Unterschrift „nach der
Veranstaltung gelöscht" wird. Beides sind Zusagen mit Datum, nicht Absichten.

Was bleibt, steht unten bei jeder Anwendung dabei. Grundsatz: weg muss, was
eine Person benennt oder erreichbar macht. Was rein sachlich ist – die
Schichtzeiten, der Zeitplan der Rennserien, die Aufgabenliste ohne die Namen
dahinter – kann stehenbleiben und ist nächstes Jahr eine Vorlage.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import date
from pathlib import Path

# Je Anwendung: (SQL, was es in Worten ist). Reihenfolge zählt – zuerst die
# Tabellen, die auf andere zeigen.
PLAENE: dict[str, list[tuple[str, str]]] = {
    "kennzeichen": [
        ("DELETE FROM antrag",
         "Anträge samt Name, Anschrift, Mail, Telefon, Kennzeichen und IP"),
        ("DELETE FROM mail_out",
         "verschickte und wartende Mails samt Empfänger und Text"),
        # Der Token in der Adresse ersetzt eine Anmeldung. Nach der
        # Veranstaltung hat ihn niemand mehr zu brauchen.
        ("DELETE FROM einstellung WHERE schluessel = 'durchfahrt_token'",
         "Token der Durchfahrtsliste"),
    ],
    "presse": [
        ("DELETE FROM anmeldung",
         "Akkreditierungen samt Name, Medium und Kontakt"),
        ("DELETE FROM mail_out",
         "verschickte und wartende Mails samt Empfänger und Text"),
    ],
    "helfer": [
        ("DELETE FROM unterschrift",
         "Unterschriften samt Namenszug und Person"),
        ("DELETE FROM schluessel", "Schlüsselvorgänge samt Namen"),
        ("DELETE FROM fahrzeug", "Fahrzeugstamm samt Haltern"),
        # helfer zieht einteilung und ausleihe über ON DELETE CASCADE mit.
        ("DELETE FROM helfer",
         "Helfer samt Kontakt – und darüber Einteilungen und Ausleihen"),
        # In den Berichten stehen Hinweise wie „Julia Johren: in der
        # Verpflegungsspalte stand 'L'".
        ("DELETE FROM import_lauf", "Importprotokolle samt Namen darin"),
        ("UPDATE aufgabe SET verantwortlich = '', kontakt = '', kuerzel = ''",
         "Namen an den Aufgaben (die Aufgaben selbst bleiben)"),
        ("DELETE FROM einstellung"
         " WHERE schluessel IN ('monitor_token', 'tablet_token')",
         "Monitor- und Tablet-Token"),
    ],
}

# Was ausdrücklich stehenbleibt. Steht hier, damit der Bericht es benennt und
# niemand raten muss, ob etwas vergessen wurde.
BLEIBT: dict[str, str] = {
    "kennzeichen": "die Einstellungen (ohne den Token)",
    "presse": "die Einstellungen",
    "helfer": ("Schichten und Zeiten, der Zeitplan der Rennserien, die "
               "Aufgabenliste ohne Namen, die Materialvorgaben"),
}


def zaehlen(con: sqlite3.Connection, sql: str) -> int:
    """Wie viele Zeilen der Schritt anfassen würde – ohne ihn auszuführen."""
    rest = sql.split(" FROM ", 1)[1] if " FROM " in sql else ""
    if sql.startswith("UPDATE "):
        tabelle = sql.split()[1]
        wo = sql.split(" WHERE ", 1)
        bedingung = (" WHERE " + wo[1]) if len(wo) > 1 else ""
        rest = tabelle + bedingung
    try:
        return con.execute("SELECT COUNT(*) FROM " + rest).fetchone()[0]
    except sqlite3.Error as fehler:
        print("   ! Zählen ging nicht (" + str(fehler) + ")", file=sys.stderr)
        return -1


def main() -> int:
    zerleger = argparse.ArgumentParser(
        description="Personendaten nach der Veranstaltung löschen.")
    zerleger.add_argument("--art", required=True, choices=sorted(PLAENE),
                          help="welche Anwendung")
    zerleger.add_argument("--db", required=True, type=Path,
                          help="Pfad zur Datenbank")
    zerleger.add_argument("--wirklich", action="store_true",
                          help="tatsächlich löschen (sonst nur zeigen)")
    zerleger.add_argument("--ohne-sicherung", action="store_true",
                          help="keine Kopie anlegen – nur, wenn es schon eine gibt")
    werte = zerleger.parse_args()

    if not werte.db.exists():
        print("Es gibt keine Datenbank unter " + str(werte.db), file=sys.stderr)
        return 1

    plan = PLAENE[werte.art]
    con = sqlite3.connect(werte.db)
    # CASCADE muss greifen, sonst blieben Einteilungen und Ausleihen stehen.
    con.execute("PRAGMA foreign_keys = ON")
    # Gelöschte Inhalte mit Nullen überschreiben statt nur freizugeben.
    con.execute("PRAGMA secure_delete = ON")

    print(werte.art + " – " + str(werte.db))
    print()
    betroffen = 0
    for sql, worte in plan:
        anzahl = zaehlen(con, sql)
        betroffen += max(0, anzahl)
        print("   %6s  %s" % (anzahl if anzahl >= 0 else "?", worte))
    print()
    print("   bleibt: " + BLEIBT[werte.art])
    print()

    if not werte.wirklich:
        print("Nichts geschrieben. Mit --wirklich wird es ernst.")
        con.close()
        return 0

    if not werte.ohne_sicherung:
        ziel = werte.db.with_suffix(
            werte.db.suffix + ".vor-loeschung-" + date.today().isoformat())
        if ziel.exists():
            print("Es gibt schon " + str(ziel) + " – erst wegräumen.",
                  file=sys.stderr)
            con.close()
            return 1
        # Über die Datenbank selbst, nicht über das Dateisystem: ein laufender
        # Dienst könnte gerade mitten in einer Schreibung stecken.
        sicherung = sqlite3.connect(ziel)
        with sicherung:
            con.backup(sicherung)
        sicherung.close()
        print("Sicherung: " + str(ziel))

    with con:
        for sql, worte in plan:
            zeiger = con.execute(sql)
            print("   %6d  %s" % (zeiger.rowcount, worte))
    # VACUUM erst nach der Transaktion, und es braucht Platz für eine zweite
    # Fassung der Datei. Ohne das blieben die geloeschten Seiten als freier
    # Raum in der Datei stehen.
    con.execute("VACUUM")
    con.close()

    print()
    print("Fertig. Die Sicherung liegt getrennt – wer sie nicht mehr braucht,")
    print("löscht sie auch, sonst war der Lauf umsonst.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
