"""PostgreSQL für alle drei Bereiche: Verbindung, Zeilen, Migrationen.

Eine Datenbank für den ganzen Dienst, ein Schema je Bereich – kennzeichen,
presse, helfer. Gemeinsam ist der Server, getrennt bleiben die Tabellen:
einstellung und mail_out gibt es in mehreren Bereichen, und keiner soll die
des anderen sehen. Welches Schema gilt, steht im search_path der Verbindung;
die Abfragen selbst nennen kein Schema.

Der Code der Bereiche ist mit sqlite3 groß geworden und spricht dessen
Sprache. Statt 250 Aufrufstellen umzuschreiben, spricht diese Schicht sie
weiter – an genau den Stellen, an denen PostgreSQL und psycopg anders sind:

- Platzhalter bleiben `?`. psycopg will `%s`; übersetzt wird hier, einmal
  je Abfrage, und dabei wird jedes andere `%` verdoppelt.
- Zeilen lassen sich per Name UND per Position lesen, wie sqlite3.Row.
- `with con:` bestätigt oder verwirft die Transaktion und lässt die
  Verbindung offen. psycopg würde sie dabei schließen.
- Ein Wahrheitswert wird als 0/1 gespeichert. SQLite tat das stillschweigend,
  PostgreSQL lehnt True in einer INTEGER-Spalte ab.

Was sich NICHT übersetzen lässt, steht in den Bereichen selbst: kein
lastrowid (dafür RETURNING id), keine in Python registrierten SQL-Funktionen,
keine PRAGMAs.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Callable

import psycopg
from psycopg import sql as _sql

IntegrityError = psycopg.IntegrityError

# Für die Entwicklung: der Container aus compose.yaml. Im Betrieb steht die
# Verbindung in dienst.env (DATABASE_URL).
ENTWICKLUNG_URL = "postgresql://abfahrt:abfahrt@127.0.0.1:55432/abfahrt"


# --- Zeilen ------------------------------------------------------------------

class Zeile(dict):
    """Eine Ergebniszeile, lesbar wie sqlite3.Row: `zeile["name"]` und
    `zeile[0]`.

    Ein dict, damit `dict(zeile)`, `zeile.keys()` und Jinjas `zeile.name`
    gehen wie bisher. Bei gleichnamigen Spalten gewinnt – wie bei sqlite3.Row
    – die erste: `SELECT e.id AS einteilung_id, h.*` liefert unter "id" die
    des Helfers, weil e.id umbenannt ist, und bei `SELECT a.*, b.*` die von a.
    """

    __slots__ = ("_werte",)

    def __init__(self, namen, werte):
        super().__init__()
        for name, wert in zip(namen, werte):
            if name not in self:
                dict.__setitem__(self, name, wert)
        self._werte = tuple(werte)

    def __getitem__(self, schluessel):
        if isinstance(schluessel, int):
            return self._werte[schluessel]
        return dict.__getitem__(self, schluessel)


def _zeilen(cursor) -> Callable:
    namen = [spalte.name for spalte in cursor.description or ()]
    return lambda werte: Zeile(namen, werte)


# --- Platzhalter -------------------------------------------------------------

@lru_cache(maxsize=1024)
def platzhalter(sql: str) -> str:
    """`?` wird `%s`, jedes andere `%` wird `%%`.

    Ein `?` in einem Text in einfachen Anführungszeichen bleibt stehen – das
    ist ein Fragezeichen, kein Platzhalter. Ein `%` dagegen wird überall
    verdoppelt, auch im Text: psycopg liest die Abfrage, bevor PostgreSQL es
    tut, und kennt keine Anführungszeichen.
    """
    teile = []
    im_text = False
    for zeichen in sql:
        if zeichen == "'":
            im_text = not im_text
            teile.append(zeichen)
        elif zeichen == "%":
            teile.append("%%")
        elif zeichen == "?" and not im_text:
            teile.append("%s")
        else:
            teile.append(zeichen)
    return "".join(teile)


def _wert(wert):
    # bool ist eine Unterklasse von int, die psycopg als boolean schickt.
    return int(wert) if isinstance(wert, bool) else wert


# --- Verbindung --------------------------------------------------------------

class Verbindung:
    """Eine Verbindung mit sqlite3-Benehmen, siehe oben."""

    def __init__(self, roh: psycopg.Connection):
        self.roh = roh

    def execute(self, sql: str, parameter=None):
        if not parameter:
            # Ohne Parameter liest psycopg die Abfrage nicht – ein `%` darin
            # bleibt, wie es ist.
            return self.roh.execute(sql)
        return self.roh.execute(platzhalter(sql), [_wert(w) for w in parameter])

    def commit(self) -> None:
        self.roh.commit()

    def rollback(self) -> None:
        self.roh.rollback()

    def close(self) -> None:
        self.roh.close()

    def __enter__(self) -> "Verbindung":
        return self

    def __exit__(self, typ, wert, spur) -> bool:
        if typ is None:
            self.roh.commit()
        else:
            self.roh.rollback()
        return False


def verbinden(url: str, schema: str) -> Verbindung:
    roh = psycopg.connect(
        url,
        options=f"-c search_path={schema}",
        application_name=f"abfahrt-{schema}",
        connect_timeout=10,
    )
    roh.row_factory = _zeilen
    return Verbindung(roh)


# --- Migrationen -------------------------------------------------------------

def _jetzt() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def migrieren(url: str, schema: str, ordner: Path) -> list[str]:
    """Legt das Schema an und spielt fehlende Migrationen ein.

    Eine Migration ist eine Datei `NNNN_name.sql` im Ordner des Bereichs.
    Welche schon gelaufen sind, steht in `<schema>.migration`. Alle fehlenden
    laufen in EINER Transaktion – PostgreSQL kann Tabellen transaktional
    anlegen und ändern, also bleibt bei einem Fehler alles, wie es war.

    Das ersetzt, was unter SQLite Handarbeit war: Spalten per PRAGMA suchen
    und nachtragen, Tabellen für eine geänderte CHECK-Regel neu aufbauen.

    Gibt die Namen der eingespielten Dateien zurück, damit der Start sie
    protokollieren kann.
    """
    dateien = sorted(ordner.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    ident = _sql.Identifier(schema)
    eingespielt = []
    with psycopg.connect(url, connect_timeout=10) as con:
        # Starten zwei Prozesse gleichzeitig, wartet der zweite hier, bis der
        # erste fertig ist, und findet dann alles erledigt vor.
        con.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                    ("abfahrt-migration-" + schema,))
        con.execute(_sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(ident))
        con.execute(_sql.SQL(
            "CREATE TABLE IF NOT EXISTS {}.migration ("
            " nummer INTEGER PRIMARY KEY,"
            " name TEXT NOT NULL,"
            " eingespielt_am TEXT NOT NULL)").format(ident))
        erledigt = {zeile[0] for zeile in con.execute(
            _sql.SQL("SELECT nummer FROM {}.migration").format(ident))}
        con.execute(_sql.SQL("SET LOCAL search_path TO {}").format(ident))
        for datei in dateien:
            nummer = int(datei.name[:4])
            if nummer in erledigt:
                continue
            con.execute(datei.read_text(encoding="utf-8"))
            con.execute(
                _sql.SQL("INSERT INTO {}.migration (nummer, name, eingespielt_am)"
                         " VALUES (%s, %s, %s)").format(ident),
                (nummer, datei.name, _jetzt()))
            eingespielt.append(datei.name)
    return eingespielt


# --- Ein Bereich ---------------------------------------------------------------

class Datenbank:
    """Die Datenbank eines Bereichs: Verbindung, Transaktion, Start.

    Die URL wird bei jeder Verbindung neu gelesen und nicht beim Anlegen
    festgehalten – die Tests setzen sie nachträglich auf ihre
    Wegwerf-Datenbank.
    """

    def __init__(self, url: Callable[[], str], schema: str, migrationen: Path):
        self._url = url
        self.schema = schema
        self.migrationen = migrationen

    @property
    def url(self) -> str:
        return self._url() or ENTWICKLUNG_URL

    def verbinden(self) -> Verbindung:
        return verbinden(self.url, self.schema)

    @contextmanager
    def transaktion(self):
        """Verbindung mit Commit bei Erfolg, Rollback bei Ausnahme."""
        con = self.verbinden()
        try:
            with con:
                yield con
        finally:
            con.close()

    def init(self) -> list[str]:
        return migrieren(self.url, self.schema, self.migrationen)
