"""Datenbankzugriff. sqlite3 aus der Standardbibliothek, kein ORM.

Wie in den Schwester-Apps: eine Verbindung je Anfrage, Schreibvorgänge in
einem `with con`-Block, damit sie ganz oder gar nicht passieren.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from . import config, normalisieren

SCHEMA = Path(__file__).resolve().parent / "schema.sql"

# Spalten, die nach dem ersten Ausrollen dazugekommen sind. Beim Start wird
# jede fehlende per ALTER TABLE ergänzt – CREATE TABLE IF NOT EXISTS allein
# würde eine bestehende Tabelle nicht anfassen.
NACHTRAEGLICHE_SPALTEN: list[tuple[str, str, str]] = [
    # (Tabelle, Spalte, vollständige Definition)
]


# --- Uhr -------------------------------------------------------------------

def _zone():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(config.ZEITZONE)
    except Exception:
        # Ohne Zeitzonendatenbank lieber die Systemzeit als ein Absturz. Auf
        # dem Server ist sie ohnehin auf Europe/Berlin gestellt.
        return None


def jetzt_lokal() -> datetime:
    """Die Uhr, nach der das Dashboard geht. JETZT_FEST verstellt sie für
    Durchsichten; im Betrieb ist die Variable leer."""
    if config.JETZT_FEST:
        try:
            return datetime.fromisoformat(config.JETZT_FEST)
        except ValueError:
            pass
    zone = _zone()
    return datetime.now(zone).replace(tzinfo=None) if zone else datetime.now()


def jetzt() -> str:
    """Zeitstempel für Datenbankspalten: Sekunden, lokale Zeit der
    Veranstaltung. Bewusst dasselbe Format wie schicht.beginn."""
    return jetzt_lokal().strftime("%Y-%m-%d %H:%M:%S")


def marke(zeitpunkt: datetime) -> str:
    return zeitpunkt.strftime("%Y-%m-%d %H:%M")


# --- Verbindung ------------------------------------------------------------

def verbinden() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.create_function(
        "suchtext", -1,
        lambda *teile: normalisieren.suchtext(*[t or "" for t in teile]))
    return con


def init() -> list[str]:
    """Legt das Schema an und trägt fehlende Spalten nach. Gibt zurück, was
    nachgetragen wurde – der Start schreibt das ins Protokoll."""
    nachgetragen = []
    con = verbinden()
    try:
        with con:
            con.executescript(SCHEMA.read_text(encoding="utf-8"))
            for tabelle, spalte, definition in NACHTRAEGLICHE_SPALTEN:
                vorhanden = {z["name"] for z in
                             con.execute("PRAGMA table_info(" + tabelle + ")")}
                if vorhanden and spalte not in vorhanden:
                    con.execute("ALTER TABLE " + tabelle +
                                " ADD COLUMN " + definition)
                    nachgetragen.append(tabelle + "." + spalte)
    finally:
        con.close()
    return nachgetragen


class _offen:
    """Platzhalter, wenn die Transaktion schon außen aufgemacht wurde."""

    def __enter__(self):
        return None

    def __exit__(self, *_):
        return False


# --- Einstellungen ---------------------------------------------------------

def einstellung(schluessel: str, vorgabe: str = "") -> str:
    con = verbinden()
    try:
        zeile = con.execute(
            "SELECT wert FROM einstellung WHERE schluessel = ?",
            (schluessel,)).fetchone()
        return zeile["wert"] if zeile else vorgabe
    finally:
        con.close()


def einstellung_setzen(schluessel: str, wert: str) -> None:
    con = verbinden()
    try:
        with con:
            con.execute(
                "INSERT INTO einstellung (schluessel, wert, geaendert_am)"
                " VALUES (?, ?, ?)"
                " ON CONFLICT (schluessel) DO UPDATE SET wert = excluded.wert,"
                " geaendert_am = excluded.geaendert_am",
                (schluessel, wert, jetzt()))
    finally:
        con.close()


# --- Helfer ----------------------------------------------------------------

def helfer_anlegen(con: sqlite3.Connection, daten: dict) -> tuple[int, bool]:
    """Legt an oder ergänzt eine vorhandene Person. Gibt (id, neu) zurück.

    Ergänzen heißt: leere Felder werden gefüllt, gefüllte bleiben stehen. Ein
    zweiter Import überschreibt also nichts, was jemand von Hand gepflegt hat.
    """
    schluessel = normalisieren.schluessel(daten.get("name", ""),
                                          daten.get("email", ""))
    vorhanden = con.execute(
        "SELECT * FROM helfer WHERE schluessel = ?", (schluessel,)).fetchone()

    if vorhanden is None:
        zeiger = con.execute(
            "INSERT INTO helfer (name, email, telefon, veggie, tshirt,"
            " tshirt_roh, bemerkung, schluessel, angelegt_am)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (normalisieren.text(daten.get("name")),
             normalisieren.text(daten.get("email")),
             normalisieren.text(daten.get("telefon")),
             daten.get("veggie"),
             daten.get("tshirt"),
             normalisieren.text(daten.get("tshirt_roh")),
             normalisieren.text(daten.get("bemerkung")),
             schluessel, jetzt()))
        return int(zeiger.lastrowid), True

    aenderungen, werte = [], []
    for spalte in ("telefon", "tshirt_roh", "bemerkung"):
        neu = normalisieren.text(daten.get(spalte))
        if neu and not vorhanden[spalte]:
            aenderungen.append(spalte + " = ?")
            werte.append(neu)
    for spalte in ("veggie", "tshirt"):
        neu = daten.get(spalte)
        if neu is not None and vorhanden[spalte] is None:
            aenderungen.append(spalte + " = ?")
            werte.append(neu)
    if aenderungen:
        con.execute(
            "UPDATE helfer SET " + ", ".join(aenderungen) +
            ", geaendert_am = ? WHERE id = ?",
            (*werte, jetzt(), vorhanden["id"]))
    return int(vorhanden["id"]), False


def helfer_liste() -> list[sqlite3.Row]:
    con = verbinden()
    try:
        return con.execute(
            "SELECT h.*,"
            " (SELECT COUNT(*) FROM einteilung e WHERE e.helfer_id = h.id)"
            "   AS schichten,"
            " suchtext(h.name, h.email, h.tshirt_roh) AS suche"
            " FROM helfer h ORDER BY h.name COLLATE NOCASE").fetchall()
    finally:
        con.close()


def helfer_laden(helfer_id: int) -> sqlite3.Row | None:
    con = verbinden()
    try:
        return con.execute("SELECT * FROM helfer WHERE id = ?",
                           (helfer_id,)).fetchone()
    finally:
        con.close()


def helfer_schichten(helfer_id: int) -> list[sqlite3.Row]:
    con = verbinden()
    try:
        return con.execute(
            "SELECT e.id AS einteilung_id, e.quelle, s.*"
            " FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
            " WHERE e.helfer_id = ? ORDER BY s.beginn", (helfer_id,)).fetchall()
    finally:
        con.close()


# --- Schichten -------------------------------------------------------------

def schicht_sichern(con: sqlite3.Connection, liste: str, beginn: str,
                    ende: str, datum: str,
                    bedarf: int | None = None) -> tuple[int, bool]:
    """Legt eine Schicht an oder aktualisiert sie. Gibt (id, neu) zurück.

    `bedarf` wird GESETZT, nicht addiert. Der Import rechnet den Bedarf aus
    beiden CSV-Dateien neu aus; würde hier addiert, verdoppelte ein zweiter
    Lauf derselben Dateien den Bedarf. None lässt den Wert stehen.
    """
    vorhanden = con.execute(
        "SELECT id FROM schicht WHERE liste = ? AND beginn = ? AND ende = ?",
        (liste, beginn, ende)).fetchone()
    if vorhanden is None:
        zeiger = con.execute(
            "INSERT INTO schicht (liste, beginn, ende, datum, bedarf, angelegt_am)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (liste, beginn, ende, datum, bedarf or 0, jetzt()))
        return int(zeiger.lastrowid), True
    if bedarf is not None:
        con.execute(
            "UPDATE schicht SET bedarf = ?, geaendert_am = ? WHERE id = ?",
            (bedarf, jetzt(), vorhanden["id"]))
    return int(vorhanden["id"]), False


# besetzt/fehlt werden immer mitgerechnet – jede Ansicht braucht sie, und eine
# eigene Zählspalte in schicht wäre eine zweite Wahrheit, die veralten kann.
_SCHICHT_SPALTEN = (
    "s.*,"
    " (SELECT COUNT(*) FROM einteilung e WHERE e.schicht_id = s.id) AS besetzt,"
    " MAX(0, s.bedarf - (SELECT COUNT(*) FROM einteilung e"
    "                    WHERE e.schicht_id = s.id)) AS fehlt,"
    " suchtext(s.liste, s.ort) AS suche"
)


def schichten(liste: str = "", tag: str = "",
              nur_luecken: bool = False) -> list[sqlite3.Row]:
    bedingungen, werte = [], []
    if liste:
        bedingungen.append("s.liste = ?")
        werte.append(liste)
    if tag:
        bedingungen.append("s.datum = ?")
        werte.append(tag)
    if nur_luecken:
        bedingungen.append(
            "s.bedarf > (SELECT COUNT(*) FROM einteilung e"
            " WHERE e.schicht_id = s.id)")
    wo = (" WHERE " + " AND ".join(bedingungen)) if bedingungen else ""

    con = verbinden()
    try:
        return con.execute(
            "SELECT " + _SCHICHT_SPALTEN + " FROM schicht s" + wo +
            " ORDER BY s.beginn, s.liste COLLATE NOCASE", werte).fetchall()
    finally:
        con.close()


def schicht_laden(schicht_id: int) -> sqlite3.Row | None:
    con = verbinden()
    try:
        return con.execute(
            "SELECT " + _SCHICHT_SPALTEN + " FROM schicht s WHERE s.id = ?",
            (schicht_id,)).fetchone()
    finally:
        con.close()


def besetzung(schicht_id: int) -> list[sqlite3.Row]:
    con = verbinden()
    try:
        return con.execute(
            "SELECT e.id AS einteilung_id, e.quelle, e.bemerkung AS notiz,"
            " e.eingeteilt_am, h.*"
            " FROM einteilung e JOIN helfer h ON h.id = e.helfer_id"
            " WHERE e.schicht_id = ?"
            " ORDER BY h.name COLLATE NOCASE, e.id", (schicht_id,)).fetchall()
    finally:
        con.close()


def listen() -> list[str]:
    con = verbinden()
    try:
        return [z["liste"] for z in con.execute(
            "SELECT DISTINCT liste FROM schicht ORDER BY liste COLLATE NOCASE")]
    finally:
        con.close()


def tage() -> list[str]:
    con = verbinden()
    try:
        return [z["datum"] for z in con.execute(
            "SELECT DISTINCT datum FROM schicht ORDER BY datum")]
    finally:
        con.close()


# --- Einteilung ------------------------------------------------------------

def einteilen(schicht_id: int, helfer_id: int, quelle: str = "hand",
              kuerzel: str = "",
              con: sqlite3.Connection | None = None) -> int:
    eigene = con is None
    con = con or verbinden()
    try:
        with (con if eigene else _offen()):
            zeiger = con.execute(
                "INSERT INTO einteilung (schicht_id, helfer_id, quelle,"
                " kuerzel, eingeteilt_am) VALUES (?, ?, ?, ?, ?)",
                (schicht_id, helfer_id, quelle, kuerzel, jetzt()))
        return int(zeiger.lastrowid)
    finally:
        if eigene:
            con.close()


def austragen(einteilung_id: int) -> bool:
    con = verbinden()
    try:
        with con:
            zeiger = con.execute("DELETE FROM einteilung WHERE id = ?",
                                 (einteilung_id,))
        return zeiger.rowcount > 0
    finally:
        con.close()


def steht_schon_drin(schicht_id: int, helfer_id: int) -> bool:
    con = verbinden()
    try:
        return con.execute(
            "SELECT 1 FROM einteilung WHERE schicht_id = ? AND helfer_id = ?",
            (schicht_id, helfer_id)).fetchone() is not None
    finally:
        con.close()


# --- Auswertung ------------------------------------------------------------

def konflikte() -> list[dict]:
    """Wer ist zur selben Zeit auf zwei Schichten eingeteilt?

    Reine Überlappung der Zeitstempel, deshalb geht das in einer Abfrage –
    Schichten über Mitternacht inbegriffen, weil beginn und ende volle
    Zeitpunkte sind. Die Bedingung a.id < b.id nennt jedes Paar genau einmal.
    """
    con = verbinden()
    try:
        return [dict(z) for z in con.execute(
            "SELECT h.id AS helfer_id, h.name,"
            " a.id AS schicht_a, a.liste AS liste_a, a.beginn AS beginn_a,"
            " a.ende AS ende_a,"
            " b.id AS schicht_b, b.liste AS liste_b, b.beginn AS beginn_b,"
            " b.ende AS ende_b"
            " FROM einteilung ea"
            " JOIN einteilung eb ON eb.helfer_id = ea.helfer_id"
            " JOIN schicht a ON a.id = ea.schicht_id"
            " JOIN schicht b ON b.id = eb.schicht_id"
            " JOIN helfer h ON h.id = ea.helfer_id"
            " WHERE a.id < b.id AND a.beginn < b.ende AND b.beginn < a.ende"
            " GROUP BY h.id, a.id, b.id"
            " ORDER BY a.beginn, h.name COLLATE NOCASE").fetchall()]
    finally:
        con.close()


def doppelt_besetzt() -> list[dict]:
    """Dieselbe Person mehrfach auf demselben Platz. Kommt in den
    Bestandsdaten vor und ist immer entweder ein Sammeleintrag oder eine
    Doppelanmeldung – die Orga muss draufschauen."""
    con = verbinden()
    try:
        return [dict(z) for z in con.execute(
            "SELECT h.id AS helfer_id, h.name, h.email, s.id AS schicht_id,"
            " s.liste, s.beginn, COUNT(*) AS anzahl"
            " FROM einteilung e"
            " JOIN helfer h ON h.id = e.helfer_id"
            " JOIN schicht s ON s.id = e.schicht_id"
            " GROUP BY e.helfer_id, e.schicht_id HAVING COUNT(*) > 1"
            " ORDER BY s.beginn, h.name COLLATE NOCASE").fetchall()]
    finally:
        con.close()


def zaehler() -> dict:
    con = verbinden()
    try:
        def eine(sql: str) -> int:
            return con.execute(sql).fetchone()[0]

        bedarf = eine("SELECT COALESCE(SUM(bedarf), 0) FROM schicht")
        besetzt = eine("SELECT COUNT(*) FROM einteilung")
        return {
            "schichten": eine("SELECT COUNT(*) FROM schicht"),
            "helfer": eine("SELECT COUNT(*) FROM helfer WHERE aktiv = 1"),
            "bedarf": bedarf,
            "besetzt": besetzt,
            "offen": max(0, bedarf - besetzt),
            "luecken": eine(
                "SELECT COUNT(*) FROM schicht s WHERE s.bedarf >"
                " (SELECT COUNT(*) FROM einteilung e WHERE e.schicht_id = s.id)"),
            "tshirts": {z["tshirt"]: z["anzahl"] for z in con.execute(
                "SELECT tshirt, COUNT(*) AS anzahl FROM helfer"
                " WHERE tshirt IS NOT NULL GROUP BY tshirt")},
            "tshirt_offen": eine(
                "SELECT COUNT(*) FROM helfer WHERE tshirt IS NULL"),
            "veggie": eine("SELECT COUNT(*) FROM helfer WHERE veggie = 1"),
            "fleisch": eine("SELECT COUNT(*) FROM helfer WHERE veggie = 0"),
            "verpflegung_offen": eine(
                "SELECT COUNT(*) FROM helfer WHERE veggie IS NULL"),
        }
    finally:
        con.close()


# --- Programm der Rennserien -----------------------------------------------

def programm(serie: str = "", tag: str = "",
             mit_entfallenen: bool = True) -> list[sqlite3.Row]:
    bedingungen, werte = [], []
    if serie:
        bedingungen.append("serie = ?")
        werte.append(serie)
    if tag:
        bedingungen.append("datum = ?")
        werte.append(tag)
    if not mit_entfallenen:
        bedingungen.append("entfallen_am IS NULL")
    wo = (" WHERE " + " AND ".join(bedingungen)) if bedingungen else ""

    con = verbinden()
    try:
        # Einträge ohne Uhrzeit ("anschließend") ganz nach hinten, sonst
        # stünden sie wegen NULL am Anfang des Tages.
        return con.execute(
            "SELECT * FROM programm" + wo +
            " ORDER BY datum, beginn IS NULL, beginn, titel COLLATE NOCASE",
            werte).fetchall()
    finally:
        con.close()


def programm_eintrag(programm_id: int) -> sqlite3.Row | None:
    con = verbinden()
    try:
        return con.execute("SELECT * FROM programm WHERE id = ?",
                           (programm_id,)).fetchone()
    finally:
        con.close()


def abruf_vermerken(serie: str, erfolg: bool, meldung: str = "",
                    bericht: str = "", ausloeser: str = "") -> None:
    con = verbinden()
    try:
        with con:
            con.execute(
                "INSERT INTO abruf_lauf (serie, erfolg, meldung, bericht,"
                " ausloeser, gelaufen_am) VALUES (?, ?, ?, ?, ?, ?)",
                (serie, 1 if erfolg else 0, meldung, bericht, ausloeser,
                 jetzt()))
    finally:
        con.close()


def abrufe(grenze: int = 20) -> list[sqlite3.Row]:
    con = verbinden()
    try:
        return con.execute(
            "SELECT * FROM abruf_lauf ORDER BY id DESC LIMIT ?",
            (grenze,)).fetchall()
    finally:
        con.close()


def letzter_erfolg(serie: str) -> sqlite3.Row | None:
    con = verbinden()
    try:
        return con.execute(
            "SELECT * FROM abruf_lauf WHERE serie = ? AND erfolg = 1"
            " ORDER BY id DESC LIMIT 1", (serie,)).fetchone()
    finally:
        con.close()


def import_vermerken(art: str, datei: str, zeilen: int, bericht: str,
                     kuerzel: str = "") -> None:
    con = verbinden()
    try:
        with con:
            con.execute(
                "INSERT INTO import_lauf (art, datei, zeilen, bericht, kuerzel,"
                " gelaufen_am) VALUES (?, ?, ?, ?, ?, ?)",
                (art, datei, zeilen, bericht, kuerzel, jetzt()))
    finally:
        con.close()


def importe() -> list[sqlite3.Row]:
    con = verbinden()
    try:
        return con.execute(
            "SELECT * FROM import_lauf ORDER BY id DESC LIMIT 20").fetchall()
    finally:
        con.close()
