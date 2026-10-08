"""Wegwerf-Datenbanken für die Tests.

Unter SQLite legte sich jeder Test eine Datei im Temp-Verzeichnis an. Das
Gegenstück hier: eine frisch angelegte Datenbank auf dem Entwicklungsserver
(compose.yaml), die am Ende des Testlaufs wieder verschwindet.

    from kern import testdb
    url = testdb.wegwerf()          # an DATABASE_URL des Servers übergeben

Welcher Server, sagt TEST_DATABASE_URL; die Vorgabe ist der Container aus
compose.yaml. Der Benutzer braucht das Recht, Datenbanken anzulegen – der
Container-Benutzer hat es.
"""

from __future__ import annotations

import atexit
import os
import secrets

import psycopg
from psycopg import conninfo, sql

VERWALTUNG_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://abfahrt:abfahrt@127.0.0.1:55432/postgres")


def wegwerf(praefix: str = "test") -> str:
    """Legt eine leere Datenbank an und gibt ihre Verbindungsangabe zurück.

    Weggeräumt wird sie beim Ende des Prozesses – auch, wenn der Test
    scheitert. Bricht er hart ab, bleibt sie liegen; `aufraeumen()` entfernt
    solche Reste.
    """
    name = f"{praefix}_{secrets.token_hex(5)}"
    with psycopg.connect(VERWALTUNG_URL, autocommit=True, connect_timeout=10) as con:
        con.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    atexit.register(_entfernen, name)
    return conninfo.make_conninfo(VERWALTUNG_URL, dbname=name)


def abfrage(url: str, schema: str, sql_text: str, parameter=()):
    """Eine Abfrage zum Nachsehen oder Vorbereiten, ohne den Server.

    Gibt bei SELECT die Zeilen zurück (lesbar wie sqlite3.Row), sonst die
    Zahl der betroffenen Zeilen. Bestätigt sofort.
    """
    from kern.db import verbinden

    con = verbinden(url, schema)
    try:
        with con:
            zeiger = con.execute(sql_text, parameter)
            if zeiger.description is None:
                return zeiger.rowcount
            return zeiger.fetchall()
    finally:
        con.close()


def _entfernen(name: str) -> None:
    try:
        with psycopg.connect(VERWALTUNG_URL, autocommit=True,
                             connect_timeout=10) as con:
            # FORCE: ein Server, den der Test gestartet hat, hält womöglich
            # noch eine Verbindung.
            con.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)")
                        .format(sql.Identifier(name)))
    except psycopg.Error:
        pass


def aufraeumen(praefix: str = "test") -> int:
    """Entfernt liegengebliebene Wegwerf-Datenbanken. Gibt ihre Zahl zurück."""
    with psycopg.connect(VERWALTUNG_URL, autocommit=True, connect_timeout=10) as con:
        namen = [zeile[0] for zeile in con.execute(
            "SELECT datname FROM pg_database WHERE datname LIKE %s",
            (praefix + "\\_%",))]
    for name in namen:
        _entfernen(name)
    return len(namen)


if __name__ == "__main__":
    print(f"{aufraeumen()} liegengebliebene Testdatenbanken entfernt")
