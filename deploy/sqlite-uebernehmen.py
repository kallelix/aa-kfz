#!/usr/bin/env python3
"""Die SQLite-Bestände einmalig nach PostgreSQL übernehmen.

    cd /opt/abfahrt
    runuser -u abfahrt -- .venv/bin/python deploy/sqlite-uebernehmen.py \\
        --kennzeichen /var/lib/abfahrt/antraege.db \\
        --presse /var/lib/abfahrt/presse.db \\
        --helfer /var/lib/abfahrt/helfer.db

Ohne ``--wirklich`` läuft alles einmal durch – lesen, schreiben, die Regeln
der Tabellen prüfen – und wird am Ende zurückgerollt. Was dann „bereit"
meldet, geht mit ``--wirklich`` genauso durch.

Übernommen wird Spalte für Spalte nach Namen, samt der Nummern: auf eine
Antragsnummer verweisen Mails und Karten, auf eine Helfernummer die
Einteilungen. Die Zähler dahinter werden danach hochgesetzt, sonst vergäbe
die nächste neue Zeile eine Nummer, die es schon gibt.

Alle drei Bereiche laufen in EINER Transaktion: entweder steht danach alles
in PostgreSQL oder nichts. Die Zielschemas müssen leer sein – ein zweiter
Lauf würde sonst verdoppeln. Die SQLite-Dateien werden nur gelesen.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402

from kern.db import migrieren  # noqa: E402

BETRIEB_URL = "postgresql://abfahrt@/abfahrt?host=/var/run/postgresql"
BEREICHE = ("kennzeichen", "presse", "helfer")


class Abbruch(Exception):
    """Ein Grund, nichts zu übernehmen – mit einem Satz für den Menschen."""


def tabellen_in_reihenfolge(con: psycopg.Connection, schema: str) -> list[str]:
    """Die Tabellen des Schemas so, dass jede nach denen kommt, auf die sie
    zeigt. Sonst schlüge der Fremdschlüssel einer Einteilung fehl, deren
    Helfer noch nicht da ist."""
    namen = [z[0] for z in con.execute(
        "SELECT table_name FROM information_schema.tables"
        " WHERE table_schema = %s AND table_type = 'BASE TABLE'"
        "   AND table_name <> 'migration' ORDER BY table_name", (schema,))]
    abhaengig: dict[str, set[str]] = {name: set() for name in namen}
    for kind, eltern in con.execute(
            "SELECT k.relname, e.relname FROM pg_constraint c"
            " JOIN pg_class k ON k.oid = c.conrelid"
            " JOIN pg_class e ON e.oid = c.confrelid"
            " JOIN pg_namespace n ON n.oid = k.relnamespace"
            " WHERE c.contype = 'f' AND n.nspname = %s", (schema,)):
        if kind != eltern and kind in abhaengig:
            abhaengig[kind].add(eltern)

    reihe: list[str] = []
    while abhaengig:
        bereit = sorted(n for n, e in abhaengig.items() if not e - set(reihe))
        if not bereit:
            raise Abbruch("Die Fremdschlüssel in " + schema + " bilden einen Kreis.")
        for name in bereit:
            reihe.append(name)
            del abhaengig[name]
    return reihe


def spalten_pg(con: psycopg.Connection, schema: str, tabelle: str) -> list[str]:
    return [z[0] for z in con.execute(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
        (schema, tabelle))]


def uebernehmen(con: psycopg.Connection, schema: str, datei: Path) -> list[str]:
    """Kopiert eine SQLite-Datei in ein Schema. Gibt den Bericht zurück."""
    bericht = []
    quelle = sqlite3.connect("file:" + datei.as_posix() + "?mode=ro", uri=True)
    try:
        in_sqlite = {z[0] for z in quelle.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%'")}
        reihe = tabellen_in_reihenfolge(con, schema)

        for tabelle in reihe:
            ziel = sql.Identifier(schema, tabelle)
            if con.execute(sql.SQL("SELECT EXISTS (SELECT 1 FROM {})").format(ziel)
                           ).fetchone()[0]:
                raise Abbruch(schema + "." + tabelle + " ist nicht leer. "
                              "Wurde schon übernommen, oder lief der Dienst "
                              "schon gegen PostgreSQL?")
            if tabelle not in in_sqlite:
                bericht.append("   %-14s fehlt in der Datei, bleibt leer" % tabelle)
                continue

            pg = spalten_pg(con, schema, tabelle)
            alt = [z[1] for z in quelle.execute(
                "PRAGMA table_info(" + tabelle + ")")]
            gemeinsam = [s for s in pg if s in alt]
            for spalte in alt:
                if spalte not in pg:
                    bericht.append("   %-14s Spalte %s gibt es nicht mehr, "
                                   "wird nicht übernommen" % (tabelle, spalte))
            for spalte in pg:
                if spalte not in alt:
                    bericht.append("   %-14s Spalte %s fehlt in der Datei, "
                                   "bekommt den Vorgabewert" % (tabelle, spalte))

            zeilen = quelle.execute(
                "SELECT " + ", ".join('"' + s + '"' for s in gemeinsam)
                + " FROM " + tabelle).fetchall()
            befehl = sql.SQL("COPY {} ({}) FROM STDIN").format(
                ziel, sql.SQL(", ").join(map(sql.Identifier, gemeinsam)))
            with con.cursor() as zeiger:
                with zeiger.copy(befehl) as kopie:
                    for zeile in zeilen:
                        kopie.write_row(zeile)

            angekommen = con.execute(
                sql.SQL("SELECT COUNT(*) FROM {}").format(ziel)).fetchone()[0]
            if angekommen != len(zeilen):
                raise Abbruch("%s.%s: %d gelesen, %d angekommen"
                              % (schema, tabelle, len(zeilen), angekommen))

            # Den Zähler hinter id auf die höchste übernommene Nummer setzen.
            if "id" in pg:
                con.execute(sql.SQL(
                    "SELECT setval(pg_get_serial_sequence(%s, 'id'),"
                    " COALESCE((SELECT MAX(id) FROM {}), 0) + 1, false)"
                ).format(ziel), (schema + "." + tabelle,))
            bericht.append("   %-14s %6d Zeilen" % (tabelle, len(zeilen)))

        for tabelle in sorted(in_sqlite - set(reihe)):
            bericht.append("   %-14s steht nur in der Datei, wird nicht übernommen"
                           % tabelle)
    finally:
        quelle.close()
    return bericht


def main() -> int:
    zerleger = argparse.ArgumentParser(
        description="Die SQLite-Bestände einmalig nach PostgreSQL übernehmen.")
    for bereich in BEREICHE:
        zerleger.add_argument("--" + bereich, type=Path, metavar="DATEI",
                              help="SQLite-Datei des Bereichs " + bereich)
    zerleger.add_argument("--url", default=os.environ.get("DATABASE_URL") or BETRIEB_URL,
                          help="Verbindung zur Datenbank (Vorgabe: DATABASE_URL "
                               "oder der Unix-Socket wie im Betrieb)")
    zerleger.add_argument("--wirklich", action="store_true",
                          help="festschreiben (sonst wird am Ende zurückgerollt)")
    werte = zerleger.parse_args()

    auftrag = {b: getattr(werte, b) for b in BEREICHE if getattr(werte, b)}
    if not auftrag:
        zerleger.error("mindestens eine Datei angeben")
    for bereich, datei in auftrag.items():
        if not datei.is_file():
            print("Es gibt keine Datei " + str(datei), file=sys.stderr)
            return 1

    # Die Schemas anlegen, wie es der Dienst beim Start täte. Das ist das
    # Einzige, was auch ohne --wirklich bleibt – leere Tabellen.
    for bereich in auftrag:
        migrieren(werte.url, bereich, WURZEL / bereich / "app" / "migrationen")

    try:
        with psycopg.connect(werte.url, connect_timeout=10) as con:
            for bereich, datei in auftrag.items():
                print(bereich + " ← " + str(datei))
                for zeile in uebernehmen(con, bereich, datei):
                    print(zeile)
                print()
            if not werte.wirklich:
                con.rollback()
                print("Bereit. Nichts festgeschrieben – mit --wirklich wird es ernst.")
                return 0
        print("Übernommen. Die SQLite-Dateien sind unverändert; sie gehören "
              "nach dem ersten Blick ins Backoffice weggeräumt.")
        return 0
    except Abbruch as grund:
        print("Abgebrochen, nichts übernommen: " + str(grund), file=sys.stderr)
        return 1
    except psycopg.Error as fehler:
        print("Abgebrochen, nichts übernommen: " + str(fehler).strip(), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
