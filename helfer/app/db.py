"""Datenbankzugriff. sqlite3 aus der Standardbibliothek, kein ORM.

Wie in den Schwester-Apps: eine Verbindung je Anfrage, Schreibvorgänge in
einem `with con`-Block, damit sie ganz oder gar nicht passieren.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from . import config, normalisieren

SCHEMA = Path(__file__).resolve().parent / "schema.sql"

# Spalten, die nach dem ersten Ausrollen dazugekommen sind. Beim Start wird
# jede fehlende per ALTER TABLE ergänzt – CREATE TABLE IF NOT EXISTS allein
# würde eine bestehende Tabelle nicht anfassen.
NACHTRAEGLICHE_SPALTEN: list[tuple[str, str, str]] = [
    # (Tabelle, Spalte, vollständige Definition)
    # Die Notiz kam mit dem Bearbeiten von Programmpunkten dazu. Bestehende
    # Datenbanken haben die Spalte nicht, CREATE TABLE IF NOT EXISTS würde sie
    # dort nicht ergänzen.
    ("programm", "notiz", "notiz TEXT NOT NULL DEFAULT ''"),
    # Versionszaehler fuer den Konfliktschutz, siehe aufgabe.version.
    ("programm", "version", "version INTEGER NOT NULL DEFAULT 1"),
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


# --- Monitor ---------------------------------------------------------------

MONITOR_SCHLUESSEL = "monitor_token"


def monitor_token(anlegen: bool = False) -> str:
    """Der Token für den Monitor-Link. Wie bei der Durchfahrtsliste: lang,
    zufällig, jederzeit widerrufbar."""
    vorhanden = einstellung(MONITOR_SCHLUESSEL)
    if vorhanden or not anlegen:
        return vorhanden
    return monitor_token_neu()


def monitor_token_neu() -> str:
    import secrets
    neu = secrets.token_urlsafe(24)
    einstellung_setzen(MONITOR_SCHLUESSEL, neu)
    return neu


def monitor_token_loeschen() -> None:
    einstellung_setzen(MONITOR_SCHLUESSEL, "")


def _schichten_mit_namen(con: sqlite3.Connection, bedingung: str,
                         werte: tuple) -> list[dict]:
    """Schichten samt der Namen aller Eingeteilten.

    Die Namen kommen in einer zweiten Abfrage für alle Schichten zusammen,
    nicht in einer je Schicht – sonst wären es auf dem Monitor bei jedem
    Auffrischen zwei Dutzend Abfragen statt zwei.
    """
    zeilen = [dict(z) for z in con.execute(
        "SELECT " + _SCHICHT_SPALTEN + " FROM schicht s WHERE " + bedingung +
        " ORDER BY s.beginn, s.liste COLLATE NOCASE", werte)]
    if not zeilen:
        return []

    platzhalter = ",".join("?" for _ in zeilen)
    namen: dict[int, list[str]] = {z["id"]: [] for z in zeilen}
    for eintrag in con.execute(
            "SELECT e.schicht_id, h.name FROM einteilung e"
            " JOIN helfer h ON h.id = e.helfer_id"
            " WHERE e.schicht_id IN (" + platzhalter + ")"
            " ORDER BY h.name COLLATE NOCASE",
            [z["id"] for z in zeilen]):
        namen[eintrag["schicht_id"]].append(eintrag["name"])
    for zeile in zeilen:
        zeile["namen"] = namen[zeile["id"]]
    return zeilen


def monitor_tage() -> list[dict]:
    """Alle Tage, an denen etwas ansteht – für die Tagesleiste im Monitor.

    Schicht- und Programmtage zusammen: der Aufbau am 25.08. hat kein
    Programm, ein reiner Programmtag hätte keine Schicht. Beides gehört in
    die Leiste.
    """
    con = verbinden()
    try:
        tage = {z["datum"] for z in con.execute(
            "SELECT DISTINCT datum FROM schicht")}
        tage |= {z["datum"] for z in con.execute(
            "SELECT DISTINCT datum FROM programm WHERE entfallen_am IS NULL")}
    finally:
        con.close()

    ergebnis = []
    for datum in sorted(tage):
        try:
            zeit = datetime.fromisoformat(datum)
        except ValueError:
            continue
        ergebnis.append({
            "datum": datum,
            "kurz": config.WOCHENTAGE[zeit.weekday()][:2] + zeit.strftime(" %d.%m."),
            "lang": config.WOCHENTAGE[zeit.weekday()] + ", " + zeit.strftime("%d.%m.%Y"),
        })
    return ergebnis


def tagesstand(datum: str, zeitpunkt: datetime) -> dict:
    """Ein ganzer Tag am Stück – der Blick voraus, den die Kollegen brauchen.

    Bewusst eine eigene Ansicht und nicht derselbe Aufbau mit anderem Datum:
    "Jetzt im Dienst" und "Als Nächstes" beziehen sich auf diesen Moment. An
    einem künftigen Tag gibt es keinen, und zwei der drei Tafeln blieben leer.
    Hier zählt stattdessen der Tagesablauf von früh bis spät.
    """
    con = verbinden()
    try:
        schichten = _schichten_mit_namen(con, "s.datum = ?", (datum,))
        programm = [dict(z) for z in con.execute(
            "SELECT * FROM programm WHERE entfallen_am IS NULL AND datum = ?"
            " ORDER BY beginn IS NULL, beginn, titel COLLATE NOCASE",
            (datum,))]
    finally:
        con.close()

    try:
        zeit = datetime.fromisoformat(datum)
        lang = (config.WOCHENTAGE[zeit.weekday()] + ", " +
                zeit.strftime("%d.%m.%Y"))
    except ValueError:
        lang = datum

    bedarf = sum(s["bedarf"] for s in schichten)
    besetzt = sum(s["besetzt"] for s in schichten)
    return {
        "jetzt": zeitpunkt,
        "datum": datum,
        "tag_lang": lang,
        "ist_heute": datum == zeitpunkt.strftime("%Y-%m-%d"),
        "schichten": schichten,
        "programm": programm,
        "bedarf": bedarf,
        "besetzt": besetzt,
        "offen": max(0, bedarf - besetzt),
        "luecken": sum(1 for s in schichten if s["fehlt"]),
    }


def monitor_stand(zeitpunkt: datetime, vorschau_minuten: int = 120) -> dict:
    """Alles, was der Monitor anzeigt, in einem Rutsch.

    Die Uhr kommt von außen, damit sich die Ansicht für eine Durchsicht auf
    einen beliebigen Zeitpunkt stellen lässt (JETZT_FEST) und der Test nicht
    auf den Renntag warten muss.
    """
    jetzt = zeitpunkt.strftime("%Y-%m-%d %H:%M")
    bis = (zeitpunkt + timedelta(minutes=vorschau_minuten)).strftime(
        "%Y-%m-%d %H:%M")
    heute = zeitpunkt.strftime("%Y-%m-%d")

    con = verbinden()
    try:
        laufend = _schichten_mit_namen(con, "s.beginn <= ? AND s.ende > ?",
                                       (jetzt, jetzt))
        demnaechst = _schichten_mit_namen(con, "s.beginn > ? AND s.beginn <= ?",
                                          (jetzt, bis))

        programm = [dict(z) for z in con.execute(
            "SELECT * FROM programm WHERE entfallen_am IS NULL"
            " AND (datum = ? OR beginn >= ?)"
            " ORDER BY datum, beginn IS NULL, beginn LIMIT 40",
            (heute, jetzt))]

        laufendes_programm = [
            p for p in programm
            if p["beginn"] and p["beginn"] <= jetzt
            and (p["ende"] or p["beginn"]) > jetzt]
        # Ohne Ende gilt ein Programmpunkt eine Stunde lang als "laufend" –
        # sonst verschwaende "ab 11.30 Uhr" sofort nach seinem Beginn.
        for p in programm:
            if (p["beginn"] and not p["ende"] and p["beginn"] <= jetzt
                    and p not in laufendes_programm):
                ende = datetime.fromisoformat(p["beginn"]) + timedelta(hours=1)
                if ende.strftime("%Y-%m-%d %H:%M") > jetzt:
                    laufendes_programm.append(p)

        kommendes_programm = [p for p in programm
                              if p["beginn"] and p["beginn"] > jetzt][:6]
        ohne_zeit = [p for p in programm
                     if not p["beginn"] and p["datum"] == heute]

        gesamt = zaehler()
        return {
            "jetzt": zeitpunkt,
            "heute": heute,
            "bis": bis,
            "vorschau_minuten": vorschau_minuten,
            "laufend": laufend,
            "demnaechst": demnaechst,
            "programm_laufend": sorted(laufendes_programm,
                                       key=lambda p: p["beginn"] or ""),
            "programm_kommend": kommendes_programm,
            "programm_ohne_zeit": ohne_zeit,
            "offen_jetzt": sum(z["fehlt"] for z in laufend),
            "offen_gesamt": gesamt["offen"],
        }
    finally:
        con.close()


# --- Aufgabenplan ----------------------------------------------------------

def aufgaben(phase: str = "", status: str = "",
             tag: str = "") -> list[sqlite3.Row]:
    bedingungen, werte = [], []
    for spalte, wert in (("phase", phase), ("status", status), ("datum", tag)):
        if wert:
            bedingungen.append(spalte + " = ?")
            werte.append(wert)
    wo = (" WHERE " + " AND ".join(bedingungen)) if bedingungen else ""

    con = verbinden()
    try:
        # Der Pool (ohne Datum) ganz nach hinten: er hat keinen Platz im
        # Ablauf, soll aber nicht zwischen den Tagen verschwinden.
        return con.execute(
            "SELECT *, suchtext(titel, ort, verantwortlich, notiz) AS suche"
            " FROM aufgabe" + wo +
            " ORDER BY datum IS NULL, datum, beginn IS NULL, beginn,"
            " titel COLLATE NOCASE", werte).fetchall()
    finally:
        con.close()


def aufgabe_laden(aufgabe_id: int) -> sqlite3.Row | None:
    con = verbinden()
    try:
        return con.execute("SELECT * FROM aufgabe WHERE id = ?",
                           (aufgabe_id,)).fetchone()
    finally:
        con.close()


_AUFGABE_SPALTEN = ("titel", "phase", "datum", "beginn", "ende", "ort",
                    "verantwortlich", "kontakt", "notiz", "status")


def aufgabe_anlegen(werte: dict, kuerzel: str = "") -> int:
    con = verbinden()
    try:
        with con:
            zeiger = con.execute(
                "INSERT INTO aufgabe (" + ", ".join(_AUFGABE_SPALTEN) +
                ", angelegt_am, geaendert_am, kuerzel) VALUES (" +
                ", ".join("?" for _ in _AUFGABE_SPALTEN) + ", ?, ?, ?)",
                (*[werte.get(s) for s in _AUFGABE_SPALTEN],
                 jetzt(), jetzt(), kuerzel))
        return int(zeiger.lastrowid)
    finally:
        con.close()


def aufgabe_speichern(aufgabe_id: int, werte: dict, stand,
                      kuerzel: str = "") -> str:
    """'ok', 'konflikt' oder 'weg'.

    `stand` ist die Version, die dem Formular beim Laden mitgegeben wurde.
    Weicht sie von der aktuellen ab, hat jemand anderes dazwischen
    gespeichert – dann wird nichts überschrieben, sondern zurückgemeldet.

    Der Vergleich passiert INNERHALB der Transaktion. Läge er davor, könnte
    zwischen Lesen und Schreiben genau das passieren, wovor er schützen soll.
    """
    try:
        stand = int(stand)
    except (TypeError, ValueError):
        stand = 0

    con = verbinden()
    try:
        with con:
            vorhanden = con.execute(
                "SELECT version FROM aufgabe WHERE id = ?",
                (aufgabe_id,)).fetchone()
            if vorhanden is None:
                return "weg"
            if stand and vorhanden["version"] != stand:
                return "konflikt"
            con.execute(
                "UPDATE aufgabe SET " +
                ", ".join(s + " = ?" for s in _AUFGABE_SPALTEN) +
                ", geaendert_am = ?, kuerzel = ?, version = version + 1"
                " WHERE id = ?",
                (*[werte.get(s) for s in _AUFGABE_SPALTEN],
                 jetzt(), kuerzel, aufgabe_id))
        return "ok"
    finally:
        con.close()


def aufgabe_status(aufgabe_id: int, status: str, kuerzel: str = "") -> bool:
    """Schneller Statuswechsel aus der Liste heraus – ohne Konfliktprüfung.

    Absicht: ein Status ist ein einzelner Wert, kein Formular. Wer ihn
    umstellt, überschreibt niemandes Text; das Schlimmste, was passieren kann,
    ist ein zweimal gesetzter Haken.
    """
    con = verbinden()
    try:
        with con:
            zeiger = con.execute(
                "UPDATE aufgabe SET status = ?, geaendert_am = ?, kuerzel = ?"
                " WHERE id = ?", (status, jetzt(), kuerzel, aufgabe_id))
        return zeiger.rowcount > 0
    finally:
        con.close()


def aufgabe_loeschen(aufgabe_id: int) -> bool:
    con = verbinden()
    try:
        with con:
            zeiger = con.execute("DELETE FROM aufgabe WHERE id = ?",
                                 (aufgabe_id,))
        return zeiger.rowcount > 0
    finally:
        con.close()


def aufgaben_zaehler() -> dict:
    con = verbinden()
    try:
        je_status = {z["status"]: z["anzahl"] for z in con.execute(
            "SELECT status, COUNT(*) AS anzahl FROM aufgabe GROUP BY status")}
        return {
            "gesamt": sum(je_status.values()),
            "offen": je_status.get("offen", 0),
            "arbeit": je_status.get("arbeit", 0),
            "erledigt": je_status.get("erledigt", 0),
            "pool": con.execute(
                "SELECT COUNT(*) FROM aufgabe WHERE datum IS NULL").fetchone()[0],
        }
    finally:
        con.close()


def vorschlaege(spalte: str) -> list[str]:
    """Was in dieser Spalte schon vorkommt – für die Vorschlagsliste am Feld.

    Feste Auswahlfelder wären hier falsch: welche Orte und Verantwortlichen es
    gibt, weiß die Orga und nicht diese Anwendung.
    """
    if spalte not in ("ort", "verantwortlich", "kontakt"):
        return []
    con = verbinden()
    try:
        return [z[0] for z in con.execute(
            "SELECT DISTINCT " + spalte + " FROM aufgabe"
            " WHERE TRIM(" + spalte + ") <> ''"
            " ORDER BY " + spalte + " COLLATE NOCASE LIMIT 50")]
    finally:
        con.close()


def programm_speichern(programm_id: int, werte: dict, stand) -> str:
    """Ein Programmpunkt von Hand. Setzt von_hand, damit der nächste Abruf
    die Änderung meldet statt sie zu überschreiben. Konfliktschutz wie bei den
    Aufgaben."""
    try:
        stand = int(stand)
    except (TypeError, ValueError):
        stand = 0

    con = verbinden()
    try:
        with con:
            vorhanden = con.execute(
                "SELECT version FROM programm WHERE id = ?",
                (programm_id,)).fetchone()
            if vorhanden is None:
                return "weg"
            if stand and vorhanden["version"] != stand:
                return "konflikt"
            con.execute(
                "UPDATE programm SET titel = ?, beginn = ?, ende = ?,"
                " zeit_roh = ?, notiz = ?, von_hand = 1, geaendert_am = ?,"
                " version = version + 1 WHERE id = ?",
                (werte["titel"], werte["beginn"], werte["ende"],
                 werte["zeit_roh"], werte["notiz"], jetzt(), programm_id))
        return "ok"
    finally:
        con.close()


def programm_freigeben(programm_id: int) -> bool:
    """Nimmt von_hand zurück: ab dem nächsten Abruf gilt wieder, was auf der
    Website steht."""
    con = verbinden()
    try:
        with con:
            zeiger = con.execute(
                "UPDATE programm SET von_hand = 0, geaendert_am = ?"
                " WHERE id = ?", (jetzt(), programm_id))
        return zeiger.rowcount > 0
    finally:
        con.close()
