"""Datenbankzugriff. PostgreSQL, Schema helfer – siehe kern/db.py. Kein ORM.

Wie in den Schwester-Apps: eine Verbindung je Anfrage, Schreibvorgänge in
einem `with con`-Block, damit sie ganz oder gar nicht passieren.

Schichten, Programm, Aufgaben, Ausleihen und Schlüssel gehören zu einer
Veranstaltung (kern/veranstaltungen.py). Wer sie liest oder anlegt, nennt
sie: ``vid`` ist überall der erste Parameter. Was über eine Nummer geht –
eine Schicht, eine Aufgabe –, braucht sie nicht; die Nummer gehört ohnehin
zu genau einer.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from kern import suchen
from kern import veranstaltungen as va
from kern.db import Datenbank, IntegrityError, Verbindung, Zeile

from . import config, normalisieren, planung, selbstanmeldung

_DATENBANK = Datenbank(lambda: config.DATABASE_URL, config.DB_SCHEMA,
                       Path(__file__).resolve().parent / "migrationen")

VERANSTALTUNGEN = va.Veranstaltungen(lambda: config.DATABASE_URL)


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

def verbinden() -> Verbindung:
    return _DATENBANK.verbinden()


def init() -> list[str]:
    """Spielt fehlende Migrationen ein und liefert ihre Namen fürs Protokoll.

    Erst die von kern: die Tabellen hier zeigen auf kern.veranstaltung.
    """
    return VERANSTALTUNGEN.init() + _DATENBANK.init()


def veranstaltung(gewaehlt="") -> Zeile | None:
    """Die gewählte Veranstaltung, sonst die Vorgabe – nach der Uhr des
    Dashboards, damit JETZT_FEST auch hier greift."""
    return VERANSTALTUNGEN.gewaehlt(gewaehlt, jetzt_lokal().date())


def tage_der(veranstaltung_zeile) -> list:
    return va.tage(veranstaltung_zeile)


def _mit_suche(zeilen, *felder):
    """Hängt jeder Zeile ihren durchsuchbaren Text an, als `suche`.

    Unter SQLite rechnete das eine SQL-Funktion, die Python registrierte.
    PostgreSQL kann keine Python-Funktion aufrufen; die Regel bleibt deshalb
    in kern/suchen.py, wo auch die Fassung für den Browser herkommt.
    """
    for zeile in zeilen:
        zeile["suche"] = normalisieren.suchtext(
            *(zeile[feld] or "" for feld in felder))
    return zeilen


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

def helfer_anlegen(con: Verbindung, daten: dict) -> tuple[int, bool]:
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
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (normalisieren.text(daten.get("name")),
             normalisieren.text(daten.get("email")),
             normalisieren.text(daten.get("telefon")),
             daten.get("veggie"),
             daten.get("tshirt"),
             normalisieren.text(daten.get("tshirt_roh")),
             normalisieren.text(daten.get("bemerkung")),
             schluessel, jetzt()))
        return int(zeiger.fetchone()[0]), True

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


def helfer_liste(vid: int) -> list[Zeile]:
    """Alle Helfer – sie gehören keiner Veranstaltung –, gezählt werden ihre
    Schichten in dieser."""
    con = verbinden()
    try:
        return _mit_suche(con.execute(
            "SELECT h.*,"
            " (SELECT COUNT(*) FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
            "  WHERE e.helfer_id = h.id AND s.veranstaltung_id = ?) AS schichten"
            " FROM helfer h ORDER BY lower(h.name)", (vid,)).fetchall(),
            "name", "email", "tshirt_roh")
    finally:
        con.close()


def helfer_laden(helfer_id: int) -> Zeile | None:
    con = verbinden()
    try:
        return con.execute("SELECT * FROM helfer WHERE id = ?",
                           (helfer_id,)).fetchone()
    finally:
        con.close()


def helfer_schichten(vid: int, helfer_id: int) -> list[Zeile]:
    con = verbinden()
    try:
        return con.execute(
            "SELECT e.id AS einteilung_id, e.quelle, e.art, e.vermerk, s.*,"
            " b.name AS bereich, b.treffpunkt"
            " FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
            " JOIN bereich b ON b.id = s.bereich_id"
            " WHERE e.helfer_id = ? AND s.veranstaltung_id = ? ORDER BY s.beginn",
            (helfer_id, vid)).fetchall()
    finally:
        con.close()


# --- Bereiche --------------------------------------------------------------

_BEREICH_FELDER = ("name", "beschreibung", "treffpunkt", "mindestalter",
                   "voraussetzungen", "intern")

# Nur die Bereiche, die dieses Konto leitet - für die Rolle Bereichsleitung.
_GELEITET = ("EXISTS (SELECT 1 FROM bereich_leitung bl"
             " WHERE bl.bereich_id = b.id AND bl.konto_id = ?)")


def bereiche(vid: int, leitung: int | None = None) -> list[Zeile]:
    """Die Bereiche der Veranstaltung mit ihren Zahlen: Schichten, Plätze
    nach Soll, davon besetzt. Mit `leitung` nur die, die dieses Konto leitet."""
    con = verbinden()
    try:
        return con.execute(
            "SELECT b.*,"
            " (SELECT COUNT(*) FROM schicht s WHERE s.bereich_id = b.id) AS schichten,"
            " (SELECT COALESCE(SUM(s.soll), 0) FROM schicht s"
            "  WHERE s.bereich_id = b.id) AS soll,"
            " (SELECT COUNT(*) FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
            "  WHERE s.bereich_id = b.id AND e.art = 'platz') AS besetzt"
            " FROM bereich b WHERE b.veranstaltung_id = ?" +
            (" AND " + _GELEITET if leitung else "") +
            " ORDER BY lower(b.name)",
            (vid, leitung) if leitung else (vid,)).fetchall()
    finally:
        con.close()


def bereich_laden(bereich_id: int) -> Zeile | None:
    con = verbinden()
    try:
        return con.execute("SELECT * FROM bereich WHERE id = ?",
                           (bereich_id,)).fetchone()
    finally:
        con.close()


def bereich_anlegen(vid: int, werte: dict) -> int | None:
    """None, wenn es den Namen in dieser Veranstaltung schon gibt."""
    con = verbinden()
    try:
        with con:
            return int(con.execute(
                "INSERT INTO bereich (veranstaltung_id, " + ", ".join(_BEREICH_FELDER) +
                ", angelegt_am) VALUES (?, " + ", ".join("?" for _ in _BEREICH_FELDER) +
                ", ?) RETURNING id",
                (vid, *(werte[f] for f in _BEREICH_FELDER), jetzt())).fetchone()[0])
    except IntegrityError:
        return None
    finally:
        con.close()


def bereich_aendern(bereich_id: int, werte: dict) -> bool | None:
    """False, wenn es den Bereich nicht mehr gibt; None, wenn der Name
    schon vergeben ist."""
    con = verbinden()
    try:
        with con:
            return con.execute(
                "UPDATE bereich SET " + ", ".join(f + " = ?" for f in _BEREICH_FELDER) +
                ", geaendert_am = ? WHERE id = ?",
                (*(werte[f] for f in _BEREICH_FELDER), jetzt(), bereich_id)).rowcount > 0
    except IntegrityError:
        return None
    finally:
        con.close()


def bereich_loeschen(bereich_id: int) -> bool:
    """Nur ein leerer Bereich. Mit Schichten weist die Datenbank das ab –
    die Schichten tragen Einteilungen, die sonst stillschweigend mitgingen."""
    con = verbinden()
    try:
        with con:
            con.execute("DELETE FROM bereich WHERE id = ?", (bereich_id,))
        return True
    except IntegrityError:
        return False
    finally:
        con.close()


def bereich_sichern(con: Verbindung, vid: int, name: str) -> int:
    """Für den Import: den Bereich mit diesem Namen, sonst einen neuen."""
    vorhanden = con.execute(
        "SELECT id FROM bereich WHERE veranstaltung_id = ? AND name = ?",
        (vid, name)).fetchone()
    if vorhanden is not None:
        return int(vorhanden["id"])
    return int(con.execute(
        "INSERT INTO bereich (veranstaltung_id, name, angelegt_am)"
        " VALUES (?, ?, ?) RETURNING id", (vid, name, jetzt())).fetchone()[0])


# --- Bereichsleitung (B-02) -------------------------------------------------

def leitung_moeglich() -> list[Zeile]:
    """Wer einen Bereich leiten kann: jedes aktive Konto, das den
    Helferbereich sieht. Die Rolle Bereichsleitung schränkt nur ein, was das
    Konto sonst noch sieht - leiten kann auch jemand von der Orga."""
    con = verbinden()
    try:
        return con.execute(
            "SELECT id, name, kuerzel, telefon, rolle FROM kern.konto"
            " WHERE aktiv = 1 AND (rolle = 'admin' OR 'helfer' = ANY(bereiche))"
            " ORDER BY lower(name)").fetchall()
    finally:
        con.close()


def leitungen(bereich_ids) -> dict[int, list[Zeile]]:
    """Je Bereich die Konten, die ihn leiten, mit Name und Nummer."""
    ergebnis: dict[int, list[Zeile]] = {nummer: [] for nummer in bereich_ids}
    if not ergebnis:
        return ergebnis
    con = verbinden()
    try:
        for zeile in con.execute(
                "SELECT bl.bereich_id, k.id, k.name, k.kuerzel, k.telefon"
                " FROM bereich_leitung bl JOIN kern.konto k ON k.id = bl.konto_id"
                " WHERE bl.bereich_id = ANY(?) ORDER BY lower(k.name)",
                (list(ergebnis),)):
            ergebnis[zeile["bereich_id"]].append(zeile)
    finally:
        con.close()
    return ergebnis


def leitung_setzen(bereich_id: int, konto_ids) -> None:
    con = verbinden()
    try:
        with con:
            con.execute("DELETE FROM bereich_leitung WHERE bereich_id = ?", (bereich_id,))
            for konto_id in sorted(set(konto_ids)):
                con.execute("INSERT INTO bereich_leitung (bereich_id, konto_id)"
                            " VALUES (?, ?)", (bereich_id, konto_id))
    finally:
        con.close()


def _gibt_es(sql: str, werte: tuple) -> bool:
    con = verbinden()
    try:
        return bool(con.execute("SELECT EXISTS (" + sql + ")", werte).fetchone()[0])
    finally:
        con.close()


def leitet_bereich(konto_id: int, bereich_id: int) -> bool:
    return _gibt_es("SELECT 1 FROM bereich_leitung WHERE konto_id = ? AND bereich_id = ?",
                    (konto_id, bereich_id))


def leitet_schicht(konto_id: int, schicht_id: int) -> bool:
    return _gibt_es(
        "SELECT 1 FROM schicht s JOIN bereich_leitung bl ON bl.bereich_id = s.bereich_id"
        " WHERE s.id = ? AND bl.konto_id = ?", (schicht_id, konto_id))


def leitet_einteilung(konto_id: int, einteilung_id: int) -> bool:
    return _gibt_es(
        "SELECT 1 FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
        " JOIN bereich_leitung bl ON bl.bereich_id = s.bereich_id"
        " WHERE e.id = ? AND bl.konto_id = ?", (einteilung_id, konto_id))


def leitet_helfer(konto_id: int, helfer_id: int) -> bool:
    """Ob die Person auf einer Schicht steht, die dieses Konto leitet - nur
    dann sieht eine Bereichsleitung sie."""
    return _gibt_es(
        "SELECT 1 FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
        " JOIN bereich_leitung bl ON bl.bereich_id = s.bereich_id"
        " WHERE e.helfer_id = ? AND bl.konto_id = ?", (helfer_id, konto_id))


# --- Schichten -------------------------------------------------------------

_SCHICHT_FELDER = ("beginn", "ende", "datum", "minimum", "soll", "reserve",
                   "mindestalter", "ort", "hinweis", "intern")


def schicht_sichern(con: Verbindung, vid: int, bereich: str, beginn: str,
                    ende: str, datum: str,
                    soll: int | None = None) -> tuple[int, bool]:
    """Für den Import: legt eine Schicht an oder aktualisiert sie. Gibt
    (id, neu) zurück. Der Bereich kommt als Name, wie er in den CSVs steht.

    `soll` wird GESETZT, nicht addiert. Der Import rechnet es aus beiden
    CSV-Dateien neu aus; würde hier addiert, verdoppelte ein zweiter Lauf
    derselben Dateien das Soll. None lässt den Wert stehen.

    Das alte Tool kennt nur eine Zahl. Eine neue Schicht bekommt sie als
    Minimum und Soll. Bei einer vorhandenen wandert das Minimum mit, solange
    es noch dem Soll gleicht, also niemand es von Hand gesenkt hat.
    """
    bereich_id = bereich_sichern(con, vid, bereich)
    vorhanden = con.execute(
        "SELECT id FROM schicht WHERE bereich_id = ? AND beginn = ? AND ende = ?",
        (bereich_id, beginn, ende)).fetchone()
    if vorhanden is None:
        zeiger = con.execute(
            "INSERT INTO schicht (veranstaltung_id, bereich_id, beginn, ende, datum,"
            " minimum, soll, angelegt_am) VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (vid, bereich_id, beginn, ende, datum, soll or 0, soll or 0, jetzt()))
        return int(zeiger.fetchone()[0]), True
    if soll is not None:
        con.execute(
            "UPDATE schicht SET"
            " minimum = CASE WHEN minimum = soll THEN ? ELSE LEAST(minimum, ?) END,"
            " soll = ?, geaendert_am = ? WHERE id = ?",
            (soll, soll, soll, jetzt(), vorhanden["id"]))
    return int(vorhanden["id"]), False


def schicht_anlegen(vid: int, bereich_id: int, werte: dict) -> int | None:
    """None, wenn der Bereich zu derselben Zeit schon eine Schicht hat."""
    con = verbinden()
    try:
        with con:
            return int(con.execute(
                "INSERT INTO schicht (veranstaltung_id, bereich_id, " +
                ", ".join(_SCHICHT_FELDER) + ", angelegt_am) VALUES (?, ?, " +
                ", ".join("?" for _ in _SCHICHT_FELDER) + ", ?) RETURNING id",
                (vid, bereich_id, *(werte[f] for f in _SCHICHT_FELDER),
                 jetzt())).fetchone()[0])
    except IntegrityError:
        return None
    finally:
        con.close()


def schicht_aendern(schicht_id: int, bereich_id: int, werte: dict) -> bool | None:
    """False, wenn es die Schicht nicht mehr gibt; None, wenn der Bereich zu
    der Zeit schon eine hat. Der Bereich muss zur selben Veranstaltung
    gehören – sonst weist der Fremdschlüssel ab, ebenfalls mit None."""
    con = verbinden()
    try:
        with con:
            return con.execute(
                "UPDATE schicht SET bereich_id = ?, " +
                ", ".join(f + " = ?" for f in _SCHICHT_FELDER) +
                ", geaendert_am = ? WHERE id = ?",
                (bereich_id, *(werte[f] for f in _SCHICHT_FELDER), jetzt(),
                 schicht_id)).rowcount > 0
    except IntegrityError:
        return None
    finally:
        con.close()


def schicht_loeschen(schicht_id: int) -> int:
    """Löscht eine Schicht, auf der niemand steht. Gibt zurück, wie viele
    darauf stehen – ist das mehr als 0, bleibt sie."""
    con = verbinden()
    try:
        with con:
            besetzt = con.execute(
                "SELECT COUNT(*) FROM einteilung WHERE schicht_id = ?",
                (schicht_id,)).fetchone()[0]
            if not besetzt:
                con.execute("DELETE FROM schicht WHERE id = ?", (schicht_id,))
        return int(besetzt)
    finally:
        con.close()


# besetzt/fehlt werden immer mitgerechnet – jede Ansicht braucht sie, und eine
# eigene Zählspalte in schicht wäre eine zweite Wahrheit, die veralten kann.
# Fehlen heißt: unter dem Soll. Die Reserve fehlt nie (R-02).
#
# Vom Bereich kommen sein Name und, was die Schicht von ihm erbt: das
# Mindestalter, wenn sie kein eigenes hat, und „intern", wenn einer von
# beiden es ist.
_SCHICHT_SPALTEN = (
    "s.*, b.name AS bereich, b.treffpunkt,"
    " COALESCE(s.mindestalter, b.mindestalter) AS alter_ab,"
    " GREATEST(s.intern, b.intern) AS ist_intern,"
    " (SELECT COUNT(*) FROM einteilung e"
    "  WHERE e.schicht_id = s.id AND e.art = 'platz') AS besetzt,"
    " (SELECT COUNT(*) FROM einteilung e"
    "  WHERE e.schicht_id = s.id AND e.art = 'reserve') AS reserve_besetzt,"
    " GREATEST(0, s.soll - (SELECT COUNT(*) FROM einteilung e"
    "                       WHERE e.schicht_id = s.id AND e.art = 'platz')) AS fehlt"
)
_SCHICHT_VON = " FROM schicht s JOIN bereich b ON b.id = s.bereich_id"

# Woraus `suche` für eine Schicht entsteht, siehe _mit_suche().
_SCHICHT_SUCHE = ("bereich", "ort")


def schichten(vid: int, bereich_id: int | None = None, tag: str = "",
              nur_luecken: bool = False, leitung: int | None = None) -> list[Zeile]:
    """Mit `leitung` nur die Schichten der Bereiche, die dieses Konto leitet."""
    bedingungen, werte = ["s.veranstaltung_id = ?"], [vid]
    if leitung:
        bedingungen.append(_GELEITET)
        werte.append(leitung)
    if bereich_id:
        bedingungen.append("s.bereich_id = ?")
        werte.append(bereich_id)
    if tag:
        bedingungen.append("s.datum = ?")
        werte.append(tag)
    if nur_luecken:
        bedingungen.append(
            "s.soll > (SELECT COUNT(*) FROM einteilung e"
            " WHERE e.schicht_id = s.id AND e.art = 'platz')")
    wo = " WHERE " + " AND ".join(bedingungen)

    con = verbinden()
    try:
        return _mit_suche(con.execute(
            "SELECT " + _SCHICHT_SPALTEN + _SCHICHT_VON + wo +
            " ORDER BY s.beginn, lower(b.name)", werte).fetchall(),
            *_SCHICHT_SUCHE)
    finally:
        con.close()


def schicht_laden(schicht_id: int) -> Zeile | None:
    con = verbinden()
    try:
        zeile = con.execute(
            "SELECT " + _SCHICHT_SPALTEN + _SCHICHT_VON + " WHERE s.id = ?",
            (schicht_id,)).fetchone()
        return _mit_suche([zeile], *_SCHICHT_SUCHE)[0] if zeile else None
    finally:
        con.close()


def besetzung(schicht_id: int) -> list[Zeile]:
    con = verbinden()
    try:
        return con.execute(
            "SELECT e.id AS einteilung_id, e.quelle, e.art, e.vermerk, e.bestaetigen_bis,"
            " e.bemerkung AS notiz, e.eingeteilt_am, h.*,"
            # Selbst angemeldet und noch nicht bestätigt (I-03) – bei
            # Mitangemeldeten zählt die Adresse dessen, der angemeldet hat.
            " (e.quelle = 'selbst' AND a.email_bestaetigt_am IS NULL) AS unbestaetigt,"
            " (h.eltern_email <> '' AND h.eltern_bestaetigt_am IS NULL) AS eltern_fehlt"
            " FROM einteilung e JOIN helfer h ON h.id = e.helfer_id"
            " JOIN helfer a ON a.id = COALESCE(h.angemeldet_von, h.id)"
            " WHERE e.schicht_id = ?"
            " ORDER BY lower(h.name), e.id", (schicht_id,)).fetchall()
    finally:
        con.close()


def tage(vid: int) -> list[str]:
    con = verbinden()
    try:
        return [z["datum"] for z in con.execute(
            "SELECT DISTINCT datum FROM schicht WHERE veranstaltung_id = ?"
            " ORDER BY datum", (vid,))]
    finally:
        con.close()


# --- Angebot und Goodies ---------------------------------------------------

# Die Häkchen im Formular. goodies und schnitte sind Schalter mit zwei
# Stellungen und kommen dort als Auswahl.
ANGEBOT_VORGABE = {"shirt": 0, "verpflegung": 1, "party": 0}
_ANGEBOT_FELDER = ("goodies", "shirt", "schnitte", "verpflegung", "party")


def angebot_roh(vid: int) -> dict:
    """Was gespeichert ist, ohne Rücksicht auf den Goodie-Schalter. Ohne
    gespeicherte Zeile die Vorgabe der Tabelle."""
    con = verbinden()
    try:
        zeile = con.execute("SELECT * FROM angebot WHERE veranstaltung_id = ?",
                            (vid,)).fetchone()
    finally:
        con.close()
    vorgabe = {**ANGEBOT_VORGABE, "goodies": 0, "schnitte": 0}
    return {f: (zeile[f] if zeile else vorgabe[f]) for f in _ANGEBOT_FELDER}


def angebot(vid: int) -> dict:
    """Was die Veranstaltung ihren Helfern bietet. Ohne Goodies auch kein
    Shirt und kein Schnitt – egal, was dafür noch gespeichert ist."""
    roh = angebot_roh(vid)
    if not roh["goodies"]:
        roh["shirt"] = roh["schnitte"] = 0
    return roh


def angebot_setzen(vid: int, werte: dict) -> None:
    con = verbinden()
    try:
        with con:
            con.execute(
                "INSERT INTO angebot (veranstaltung_id, " + ", ".join(_ANGEBOT_FELDER) +
                ", geaendert_am) VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (veranstaltung_id) DO UPDATE SET " +
                ", ".join(f + " = excluded." + f for f in _ANGEBOT_FELDER) +
                ", geaendert_am = excluded.geaendert_am",
                (vid, *(werte.get(f, 0) for f in _ANGEBOT_FELDER), jetzt()))
    finally:
        con.close()


_GOODIE_FELDER = ("name", "ab_schichten", "ab_stunden", "mindestalter", "alternative")


def goodies(vid: int) -> list[Zeile]:
    """Nach Schwelle: erst die nach Schichten, dann die nach Stunden."""
    con = verbinden()
    try:
        return con.execute(
            "SELECT * FROM goodie WHERE veranstaltung_id = ?"
            " ORDER BY ab_schichten IS NULL, ab_schichten, ab_stunden, lower(name)",
            (vid,)).fetchall()
    finally:
        con.close()


def goodie_laden(goodie_id: int) -> Zeile | None:
    con = verbinden()
    try:
        return con.execute("SELECT * FROM goodie WHERE id = ?",
                           (goodie_id,)).fetchone()
    finally:
        con.close()


def goodie_anlegen(vid: int, werte: dict) -> int:
    con = verbinden()
    try:
        with con:
            return int(con.execute(
                "INSERT INTO goodie (veranstaltung_id, " + ", ".join(_GOODIE_FELDER) +
                ", angelegt_am) VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
                (vid, *(werte[f] for f in _GOODIE_FELDER), jetzt())).fetchone()[0])
    finally:
        con.close()


def goodie_aendern(goodie_id: int, werte: dict) -> bool:
    con = verbinden()
    try:
        with con:
            return con.execute(
                "UPDATE goodie SET " + ", ".join(f + " = ?" for f in _GOODIE_FELDER) +
                ", geaendert_am = ? WHERE id = ?",
                (*(werte[f] for f in _GOODIE_FELDER), jetzt(), goodie_id)).rowcount > 0
    finally:
        con.close()


def goodie_loeschen(goodie_id: int) -> None:
    con = verbinden()
    try:
        with con:
            con.execute("DELETE FROM goodie WHERE id = ?", (goodie_id,))
    finally:
        con.close()


# --- Vorlage (V-04) --------------------------------------------------------

def vorlagen(vid: int) -> list[Zeile]:
    """Frühere Veranstaltungen, aus denen sich etwas übernehmen lässt: die
    mit mindestens einem Bereich."""
    con = verbinden()
    try:
        return con.execute(
            "SELECT v.id, v.name, v.kurz, v.beginn, COUNT(DISTINCT b.id) AS bereiche,"
            " COUNT(s.id) AS schichten"
            " FROM kern.veranstaltung v JOIN bereich b ON b.veranstaltung_id = v.id"
            " LEFT JOIN schicht s ON s.bereich_id = b.id"
            " WHERE v.id <> ? GROUP BY v.id ORDER BY v.beginn DESC", (vid,)).fetchall()
    finally:
        con.close()


def vorlage_uebernehmen(vid: int, quelle_id: int, wer: str = "") -> dict | None:
    """Bereiche, Schichten, Goodies und das Angebot einer früheren
    Veranstaltung in diese kopieren. Die Schichten wandern um so viele Tage,
    wie die beiden Veranstaltungen auseinanderliegen – gemessen am ersten
    Tag. Einteilungen bleiben, wo sie sind: die Leute haben sich für damals
    gemeldet, nicht für jetzt. Einsatzgrenzen auf ganze Bereiche kommen mit
    – sie gelten der Person, nicht dem Jahr; die auf einzelne Schichten
    nicht, die Schichten sind ja neue.

    Nur in eine Veranstaltung ohne Bereiche; sonst None. Zusammenführen
    hieße raten, welcher Bereich welcher ist.
    """
    ziel = VERANSTALTUNGEN.laden(vid)
    quelle = VERANSTALTUNGEN.laden(quelle_id)
    if ziel is None or quelle is None or ziel["id"] == quelle["id"]:
        return None
    tage = (ziel["beginn"] - quelle["beginn"]).days

    con = verbinden()
    try:
        with con:
            if con.execute("SELECT 1 FROM bereich WHERE veranstaltung_id = ?",
                           (vid,)).fetchone():
                return None
            neu: dict[int, int] = {}
            for b in con.execute("SELECT * FROM bereich WHERE veranstaltung_id = ?"
                                 " ORDER BY id", (quelle_id,)).fetchall():
                neu[b["id"]] = int(con.execute(
                    "INSERT INTO bereich (veranstaltung_id, " +
                    ", ".join(_BEREICH_FELDER) + ", angelegt_am) VALUES (?, " +
                    ", ".join("?" for _ in _BEREICH_FELDER) + ", ?) RETURNING id",
                    (vid, *(b[f] for f in _BEREICH_FELDER), jetzt())).fetchone()[0])
                # Meist leiten dieselben Leute im nächsten Jahr wieder.
                con.execute(
                    "INSERT INTO bereich_leitung (bereich_id, konto_id)"
                    " SELECT ?, konto_id FROM bereich_leitung WHERE bereich_id = ?",
                    (neu[b["id"]], b["id"]))
                for g in con.execute(
                        "SELECT * FROM einsatzgrenze WHERE bereich_id = ? ORDER BY id",
                        (b["id"],)).fetchall():
                    con.execute(
                        "INSERT INTO einsatzgrenze (helfer_id, bereich_id, art,"
                        " angelegt_von, angelegt_am) VALUES (?, ?, ?, ?, ?)",
                        (g["helfer_id"], neu[b["id"]], g["art"], g["angelegt_von"],
                         g["angelegt_am"]))
                    _protokollieren(con, g["helfer_id"], wer,
                                    f"Einsatzgrenze aus {quelle['kurz']} übernommen: "
                                    f"{b['name']} – {GRENZ_ARTEN[g['art']]}")
            schichten = con.execute(
                "SELECT * FROM schicht WHERE veranstaltung_id = ? ORDER BY beginn",
                (quelle_id,)).fetchall()
            for s in schichten:
                werte = dict(s)
                for feld in ("beginn", "ende", "datum"):
                    werte[feld] = planung.verschieben(s[feld], tage)
                con.execute(
                    "INSERT INTO schicht (veranstaltung_id, bereich_id, " +
                    ", ".join(_SCHICHT_FELDER) + ", angelegt_am) VALUES (?, ?, " +
                    ", ".join("?" for _ in _SCHICHT_FELDER) + ", ?)",
                    (vid, neu[s["bereich_id"]], *(werte[f] for f in _SCHICHT_FELDER),
                     jetzt()))
            goodies = con.execute("SELECT * FROM goodie WHERE veranstaltung_id = ?"
                                  " ORDER BY id", (quelle_id,)).fetchall()
            for g in goodies:
                con.execute(
                    "INSERT INTO goodie (veranstaltung_id, " + ", ".join(_GOODIE_FELDER) +
                    ", angelegt_am) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (vid, *(g[f] for f in _GOODIE_FELDER), jetzt()))
            # Das Angebot nur, wenn hier noch keins eingestellt ist.
            con.execute(
                "INSERT INTO angebot (veranstaltung_id, goodies, shirt, schnitte,"
                " verpflegung, party, geaendert_am)"
                " SELECT ?, goodies, shirt, schnitte, verpflegung, party, ? FROM angebot"
                " WHERE veranstaltung_id = ? ON CONFLICT (veranstaltung_id) DO NOTHING",
                (vid, jetzt(), quelle_id))
        return {"bereiche": len(neu), "schichten": len(schichten),
                "goodies": len(goodies), "tage": tage}
    finally:
        con.close()


# --- Öffentliche Anmeldung (Lastenheft 2.2) ---------------------------------

class AnmeldeFehler(Exception):
    """Was einer Anmeldung im Weg steht, als Sätze für den Menschen."""

    def __init__(self, gruende: list[str]) -> None:
        super().__init__("; ".join(gruende))
        self.gruende = gruende


def _lage(zeile) -> dict:
    """Frei, Reserve oder voll – und ob die Schicht dringend gebraucht wird
    (unter Minimum)."""
    frei = max(0, zeile["soll"] - zeile["besetzt"])
    reserve_frei = max(0, zeile["reserve"] - zeile["reserve_besetzt"])
    return {"frei": frei, "reserve_frei": reserve_frei,
            "lage": "frei" if frei else "reserve" if reserve_frei else "voll",
            "dringend": zeile["besetzt"] < zeile["minimum"]}


def oeffentliche_schichten(vid: int) -> list[dict]:
    """Was in der öffentlichen Liste steht (A-06): nicht intern, noch nicht
    begonnen, nach Tag und Uhrzeit."""
    con = verbinden()
    try:
        zeilen = [dict(z) for z in con.execute(
            "SELECT " + _SCHICHT_SPALTEN + ", b.beschreibung, b.voraussetzungen"
            + _SCHICHT_VON +
            " WHERE s.veranstaltung_id = ? AND s.intern = 0 AND b.intern = 0"
            " AND s.beginn > ? ORDER BY s.datum, s.beginn, lower(b.name)",
            (vid, marke(jetzt_lokal())))]
    finally:
        con.close()
    for zeile in zeilen:
        zeile.update(_lage(zeile))
    return zeilen


def _person_sichern(con: Verbindung, werte: dict, schluessel_email: str,
                    angemeldet_von: int | None) -> int:
    """Legt die Person an oder findet sie wieder – an Name und Adresse wie
    beim Import. Was sie selbst angibt, gilt: Name, Nummer, Alter, Shirt,
    Verpflegung werden überschrieben, alles andere bleibt."""
    schluessel = normalisieren.schluessel(werte["name"], schluessel_email)
    vorhanden = con.execute("SELECT id FROM helfer WHERE schluessel = ?",
                            (schluessel,)).fetchone()
    felder = ("name", "vorname", "nachname", "volljaehrig", "geburtsdatum",
              "veggie", "tshirt", "tshirt_roh", "eltern_name", "eltern_email")
    werte = {"eltern_name": "", "eltern_email": "", **werte}
    if vorhanden is None:
        return int(con.execute(
            "INSERT INTO helfer (" + ", ".join(felder) + ", email, telefon, schluessel,"
            " angemeldet_von, angelegt_am) VALUES (" + ", ".join("?" for _ in felder) +
            ", ?, ?, ?, ?, ?) RETURNING id",
            (*(werte[f] for f in felder), werte["email"], werte["telefon"], schluessel,
             angemeldet_von, jetzt())).fetchone()[0])
    # Andere Eltern, neue Bestätigung (D-06).
    con.execute("UPDATE helfer SET eltern_bestaetigt_am = NULL WHERE id = ?"
                " AND eltern_email <> ?", (vorhanden["id"], werte["eltern_email"]))
    con.execute(
        "UPDATE helfer SET " + ", ".join(f + " = ?" for f in felder) +
        ", telefon = CASE WHEN ? <> '' THEN ? ELSE telefon END,"
        " aktiv = 1, geaendert_am = ? WHERE id = ?",
        (*(werte[f] for f in felder), werte["telefon"], werte["telefon"], jetzt(),
         vorhanden["id"]))
    return int(vorhanden["id"])


def _schichten_sperren(con: Verbindung, vid: int, schicht_ids: list[int]) -> list[dict]:
    """Die gewählten Schichten, gesperrt (FOR UPDATE): wer gleichzeitig auf
    denselben letzten Platz will, wartet, bis der Erste fertig ist, und sieht
    dann, dass er weg ist."""
    schichten = [dict(z) for z in con.execute(
        "SELECT s.id, s.beginn, s.ende, s.soll, s.reserve, s.minimum, s.bereich_id,"
        " s.veranstaltung_id, b.name AS bereich,"
        " COALESCE(s.mindestalter, b.mindestalter) AS alter_ab,"
        " GREATEST(s.intern, b.intern) AS ist_intern"
        " FROM schicht s JOIN bereich b ON b.id = s.bereich_id"
        " WHERE s.id = ANY(?) AND s.veranstaltung_id = ?"
        " ORDER BY s.id FOR UPDATE OF s", (list(schicht_ids), vid))]
    if len(schichten) != len(set(schicht_ids)) or any(s["ist_intern"] for s in schichten):
        raise AnmeldeFehler(["Eine der gewählten Schichten gibt es nicht mehr. "
                             "Bitte noch einmal auswählen."])
    for s in schichten:
        s["text"] = _schicht_text(s)
    return schichten


def _pruefen(con: Verbindung, vid: int, schichten: list[dict],
             fenster: list[tuple[str, str, str]], teilnehmer: list[dict],
             warteliste=frozenset(), ausser: int | None = None) -> dict[int, list[str]]:
    """Alles, was einer Buchung im Weg steht – für alle Teilnehmer auf einmal.

    `teilnehmer` sind Dicts mit vorname, volljaehrig, alter (None: unbekannt)
    und helfer_id (None: neu). Wer schon da ist, bringt seine Schichten,
    Springer-Zeiten, Wartelisten und Einsatzgrenzen mit. Für die Schichten in
    `warteliste` ist die Warteliste recht, wenn kein Platz mehr frei ist
    (R-04). `ausser` ist eine Einteilung, die beim Umbuchen abgegeben wird –
    sie zählt nicht mit (S-02).

    Gibt je Schicht die Arten zurück (platz, reserve oder warteliste, in der
    Reihenfolge der Teilnehmer); wirft AnmeldeFehler mit allen Gründen.
    """
    gruende: list[str] = []
    jetzt_marke = marke(jetzt_lokal())
    for s in schichten:
        if s["beginn"] <= jetzt_marke:
            gruende.append(s["text"] + " hat schon begonnen.")

    gesperrt: set[int] = set()
    for person in teilnehmer:
        if person["helfer_id"] is not None:
            gesperrt |= _gesperrt(con, vid, person["helfer_id"])

    # Platz, Reserve, Warteliste oder voll – für alle zusammen. Eine Schicht
    # hinter einer Einsatzgrenze ist für die Person schlicht nicht frei:
    # dieselben Worte wie bei einer vollen, damit niemand an der Antwort
    # merkt, dass es um ihn geht (K-06).
    verteilung: dict[int, list[str]] = {}
    for s in schichten:
        zahlen = con.execute(
            "SELECT COUNT(*) FILTER (WHERE art = 'platz') AS platz,"
            " COUNT(*) FILTER (WHERE art = 'reserve') AS reserve"
            " FROM einteilung WHERE schicht_id = ? AND id <> ?",
            (s["id"], ausser or 0)).fetchone()
        frei = max(0, s["soll"] - zahlen["platz"])
        reserve_frei = max(0, s["reserve"] - zahlen["reserve"])
        arten = []
        for _ in teilnehmer:
            if frei:
                arten.append("platz")
                frei -= 1
            elif reserve_frei:
                arten.append("reserve")
                reserve_frei -= 1
            elif s["id"] in warteliste:
                arten.append("warteliste")
        if len(arten) < len(teilnehmer) or s["id"] in gesperrt:
            gruende.append(
                f"{s['text']} ist gerade nicht frei – in der Liste findest "
                "du andere, die Hilfe brauchen." if len(teilnehmer) == 1 else
                f"In {s['text']} ist gerade nicht für alle {len(teilnehmer)} Platz.")
        verteilung[s["id"]] = arten

    # K-01 und K-04: nichts darf sich überschneiden – keine zwei Schichten,
    # keine Schicht mit einer Springer-Zeit. Eine Warteliste zählt hier
    # nicht: bekommt jemand von dort ein Angebot, wird das noch einmal
    # geprüft.
    wirksam = [s for s in schichten
               if any(a != "warteliste" for a in verteilung.get(s["id"], ["platz"]))]
    zeiten = [(s["text"], s["beginn"], s["ende"]) for s in wirksam]
    for a, b in selbstanmeldung.ueberschneidungen(zeiten):
        gruende.append(f"{a} und {b} überschneiden sich.")
    for _, von, bis in fenster:
        for s in wirksam:
            if selbstanmeldung.ueberschneiden(von, bis, s["beginn"], s["ende"]):
                gruende.append(f"Als Springer bist du zur Zeit von {s['text']} "
                               "schon eingeplant – bitte eins von beiden.")

    # Das Mindestalter (D-07). Volljährig erfüllt jede Grenze bis 18.
    for person in teilnehmer:
        alter = 18 if person["volljaehrig"] else person["alter"]
        for s in schichten:
            if s["alter_ab"] and alter is not None and alter < s["alter_ab"]:
                gruende.append(f"{s['text']} ist erst ab {s['alter_ab']} – für "
                               f"{person['vorname']} geht das noch nicht.")

    # Wer schon da ist: seine Schichten, Wartelisten und Springer-Zeiten.
    for person in teilnehmer:
        if person["helfer_id"] is None:
            continue
        eigene = con.execute(
            "SELECT s.id, s.beginn, s.ende, b.name AS bereich FROM einteilung e"
            " JOIN schicht s ON s.id = e.schicht_id"
            " JOIN bereich b ON b.id = s.bereich_id"
            " WHERE e.helfer_id = ? AND s.veranstaltung_id = ? AND e.id <> ?",
            (person["helfer_id"], vid, ausser or 0)).fetchall()
        for alt in eigene:
            for s in schichten:
                if alt["id"] == s["id"]:
                    gruende.append(f"{person['vorname']} ist für {s['text']} "
                                   "schon eingetragen.")
                elif s in wirksam and selbstanmeldung.ueberschneiden(
                        alt["beginn"], alt["ende"], s["beginn"], s["ende"]):
                    gruende.append(f"{s['text']} überschneidet sich mit "
                                   f"{_schicht_text(alt)}, für die "
                                   f"{person['vorname']} schon eingetragen ist.")
            for _, von, bis in fenster:
                if selbstanmeldung.ueberschneiden(von, bis, alt["beginn"], alt["ende"]):
                    gruende.append(f"Als Springer überschneidet sich das mit "
                                   f"{_schicht_text(alt)}, für die "
                                   f"{person['vorname']} schon eingetragen ist.")
        wartet = {z["schicht_id"] for z in con.execute(
            "SELECT schicht_id FROM warteliste WHERE helfer_id = ?",
            (person["helfer_id"],)).fetchall()}
        for s in schichten:
            if s["id"] in wartet:
                gruende.append(f"{person['vorname']} steht für {s['text']} "
                               "schon auf der Warteliste.")
        schon = {z["beginn"] for z in con.execute(
            "SELECT beginn FROM verfuegbarkeit WHERE helfer_id = ? AND veranstaltung_id = ?",
            (person["helfer_id"], vid)).fetchall()}
        for _, von, _ in fenster:
            if von in schon:
                gruende.append(f"Diese Springer-Zeit hat {person['vorname']} schon.")

    if gruende:
        raise AnmeldeFehler(list(dict.fromkeys(gruende)))
    return verteilung


def _eintragen(con: Verbindung, vid: int, ids: list[int], schichten: list[dict],
               verteilung: dict[int, list[str]], fenster: list[tuple[str, str, str]],
               bemerkung: str = "", bemerkung_von: int | None = None) -> None:
    """Teilnahme, Einteilungen, Wartelisten und Springer-Zeiten – nach
    _pruefen."""
    for i, helfer_id in enumerate(ids):
        eigene_bemerkung = bemerkung if helfer_id == (bemerkung_von or ids[0]) else ""
        con.execute(
            "INSERT INTO teilnahme (veranstaltung_id, helfer_id, quelle, bemerkung,"
            " angemeldet_am) VALUES (?, ?, 'selbst', ?, ?)"
            " ON CONFLICT (veranstaltung_id, helfer_id) DO UPDATE SET bemerkung ="
            " CASE WHEN excluded.bemerkung <> '' THEN excluded.bemerkung"
            " ELSE teilnahme.bemerkung END",
            (vid, helfer_id, eigene_bemerkung, jetzt()))
        for s in schichten:
            art = verteilung[s["id"]][i]
            if art == "warteliste":
                con.execute("INSERT INTO warteliste (schicht_id, helfer_id, angelegt_am)"
                            " VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                            (s["id"], helfer_id, jetzt()))
            else:
                con.execute(
                    "INSERT INTO einteilung (schicht_id, helfer_id, quelle, art,"
                    " eingeteilt_am) VALUES (?, ?, 'selbst', ?, ?)",
                    (s["id"], helfer_id, art, jetzt()))
        for _, von, bis in fenster:
            con.execute(
                "INSERT INTO verfuegbarkeit (veranstaltung_id, helfer_id, beginn,"
                " ende, springer, angelegt_am) VALUES (?, ?, ?, ?, 1, ?)",
                (vid, helfer_id, von, bis, jetzt()))


def anmelden(vid: int, personen: list[dict], schicht_ids: list[int],
             fenster: list[tuple[str, str, str]], bemerkung: str = "",
             warteliste=frozenset()) -> dict:
    """Trägt eine Anmeldung ein – alles oder nichts.

    `personen[0]` meldet an, die übrigen kommen mit (A-08) und stehen auf
    denselben Schichten. Je Schicht bekommt, wer zuerst kommt, einen Platz;
    ist das Soll erreicht, Reserve (R-03); ist auch die voll, geht es nur
    auf die Warteliste, wenn sie gewählt ist (R-04). Wer schon da ist
    (A-11), kommt hier nicht an – das fängt main.py vorher ab und schickt
    den Link.

    Wirft AnmeldeFehler mit allen Gründen auf einmal.
    """
    con = verbinden()
    try:
        with con:
            schichten = _schichten_sperren(con, vid, schicht_ids)
            anmelder_email = personen[0]["email"]
            teilnehmer = []
            for person in personen:
                zeile = con.execute(
                    "SELECT id FROM helfer WHERE schluessel = ?",
                    (normalisieren.schluessel(person["name"], anmelder_email),)).fetchone()
                teilnehmer.append({**person, "helfer_id": zeile["id"] if zeile else None})
            verteilung = _pruefen(con, vid, schichten, fenster, teilnehmer, warteliste)

            ids: list[int] = []
            for i, person in enumerate(personen):
                ids.append(_person_sichern(con, person, anmelder_email,
                                           None if i == 0 else ids[0]))
            _eintragen(con, vid, ids, schichten, verteilung, fenster, bemerkung)
        return {"anmelder": ids[0], "personen": ids,
                "schichten": [{**s, "arten": verteilung[s["id"]]} for s in schichten]}
    finally:
        con.close()


def dazunehmen(vid: int, anmelder_id: int, helfer_ids: list[int], neue: list[dict],
               schicht_ids: list[int], fenster: list[tuple[str, str, str]],
               bemerkung: str = "", warteliste=frozenset(), bestaetigt: bool = True) -> dict:
    """Schichten dazunehmen aus Mein Helferplatz (A-09): für sich selbst, für
    die Mitangemeldeten und für neue, die mitkommen. Dieselben Prüfungen wie
    beim Anmelden. Wer hier bucht, hat den Link aus seiner Mail benutzt –
    damit ist die Adresse bestätigt. Von der Dankeseite aus (G-03) gilt das
    nicht: `bestaetigt=False`."""
    con = verbinden()
    try:
        with con:
            anmelder = con.execute("SELECT * FROM helfer WHERE id = ?",
                                   (anmelder_id,)).fetchone()
            erlaubt = {anmelder_id} | {z["id"] for z in con.execute(
                "SELECT id FROM helfer WHERE angemeldet_von = ?", (anmelder_id,)).fetchall()}
            if anmelder is None or not set(helfer_ids) <= erlaubt:
                raise AnmeldeFehler(["Diese Person gehört nicht zu deiner Anmeldung."])
            if not helfer_ids and not neue:
                raise AnmeldeFehler(["Wähle aus, wer kommt."])
            stichtag = VERANSTALTUNGEN.laden(vid)["beginn"]
            schichten = _schichten_sperren(con, vid, schicht_ids)
            teilnehmer = []
            for helfer_id in helfer_ids:
                zeile = con.execute("SELECT * FROM helfer WHERE id = ?", (helfer_id,)).fetchone()
                teilnehmer.append({"vorname": zeile["vorname"] or zeile["name"],
                                   "volljaehrig": zeile["volljaehrig"],
                                   "alter": _alter(zeile, stichtag), "helfer_id": helfer_id})
            for person in neue:
                zeile = con.execute(
                    "SELECT id FROM helfer WHERE schluessel = ?",
                    (normalisieren.schluessel(person["name"], anmelder["email"]),)).fetchone()
                teilnehmer.append({**person, "helfer_id": zeile["id"] if zeile else None})
            verteilung = _pruefen(con, vid, schichten, fenster, teilnehmer, warteliste)

            ids = list(helfer_ids) + [_person_sichern(con, person, anmelder["email"], anmelder_id)
                                      for person in neue]
            _eintragen(con, vid, ids, schichten, verteilung, fenster, bemerkung,
                       bemerkung_von=anmelder_id if anmelder_id in ids else None)
            if bestaetigt:
                con.execute("UPDATE helfer SET email_bestaetigt_am = ? WHERE id = ?"
                            " AND email_bestaetigt_am IS NULL", (jetzt(), anmelder_id))
            if con.execute("SELECT email_bestaetigt_am FROM helfer WHERE id = ?",
                           (anmelder_id,)).fetchone()["email_bestaetigt_am"]:
                _eltern_durch_anmelder(con, anmelder_id)
            for i, helfer_id in enumerate(ids):
                for s in schichten:
                    art = verteilung[s["id"]][i]
                    _protokollieren(con, helfer_id, "selbst",
                                    ("Auf die Warteliste: " if art == "warteliste"
                                     else "Dazugenommen: ") + s["text"], vid, s["bereich_id"])
                for _, von, bis in fenster:
                    _protokollieren(con, helfer_id, "selbst", "Als Springer dazu: "
                                    + _schicht_text({"bereich": "Springer", "beginn": von,
                                                     "ende": bis}), vid)
        return {"personen": ids,
                "schichten": [{**s, "arten": verteilung[s["id"]]} for s in schichten]}
    finally:
        con.close()


def _alter(zeile, stichtag) -> int | None:
    """Das Alter am ersten Veranstaltungstag, soweit bekannt."""
    if zeile["volljaehrig"]:
        return 18
    if not zeile["geburtsdatum"]:
        return None
    try:
        return selbstanmeldung.alter_am(date.fromisoformat(zeile["geburtsdatum"]), stichtag)
    except ValueError:
        return None


def _schicht_text(s) -> str:
    """'Shuttle Sa 03.07. 07:00–12:00' – für Meldungen."""
    try:
        tag = datetime.fromisoformat(s["beginn"])
        kurz = config.WOCHENTAGE[tag.weekday()][:2] + tag.strftime(" %d.%m. %H:%M")
    except ValueError:
        kurz = s["beginn"]
    return f"{s['bereich']} {kurz}–{s['ende'][11:16]}"


def anmeldung_laden(vid: int, anmelder_id: int) -> dict | None:
    """Was die Dankeseite zeigt: wer, auf welchen Schichten, als was, und
    die Springer-Zeiten."""
    con = verbinden()
    try:
        anmelder = con.execute("SELECT * FROM helfer WHERE id = ?", (anmelder_id,)).fetchone()
        if anmelder is None:
            return None
        personen = [anmelder] + con.execute(
            "SELECT * FROM helfer WHERE angemeldet_von = ? ORDER BY id", (anmelder_id,)).fetchall()
        ergebnis = []
        for person in personen:
            schichten = con.execute(
                "SELECT s.*, b.name AS bereich, b.treffpunkt, e.art, e.id AS einteilung_id,"
                " e.bestaetigen_bis"
                " FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
                " JOIN bereich b ON b.id = s.bereich_id"
                " WHERE e.helfer_id = ? AND s.veranstaltung_id = ? ORDER BY s.beginn",
                (person["id"], vid)).fetchall()
            fenster = con.execute(
                "SELECT * FROM verfuegbarkeit WHERE helfer_id = ? AND veranstaltung_id = ?"
                " AND springer = 1 ORDER BY beginn", (person["id"], vid)).fetchall()
            wartet = con.execute(
                "SELECT s.*, b.name AS bereich, w.id AS warteliste_id"
                " FROM warteliste w JOIN schicht s ON s.id = w.schicht_id"
                " JOIN bereich b ON b.id = s.bereich_id"
                " WHERE w.helfer_id = ? AND s.veranstaltung_id = ? ORDER BY s.beginn",
                (person["id"], vid)).fetchall()
            if schichten or fenster or wartet or person["id"] == anmelder_id:
                ergebnis.append({"person": person, "schichten": schichten, "fenster": fenster,
                                 "warteliste": wartet})
        return {"anmelder": anmelder, "personen": ergebnis}
    finally:
        con.close()


def interesse_vormerken(vid: int, email: str, vorname: str) -> bool:
    """True, wenn neu; False, wenn die Adresse schon vorgemerkt war."""
    con = verbinden()
    try:
        with con:
            return con.execute(
                "INSERT INTO interesse (veranstaltung_id, email, vorname, angelegt_am)"
                " VALUES (?, ?, ?, ?) ON CONFLICT (veranstaltung_id, email) DO NOTHING",
                (vid, email, vorname, jetzt())).rowcount > 0
    finally:
        con.close()


# --- Wiedererkennen, Bestätigen, Mein Helferplatz (Lastenheft 2.4) ---------

def _gleicher_name(a: str, b: str) -> bool:
    """„Müller“, „Mueller“ und „Muller“ sind derselbe Name (kern/suchen.py)."""
    return bool(set(suchen.varianten(a)) & set(suchen.varianten(b)))


def erkennen(person: dict) -> tuple[str, list[Zeile]]:
    """Ob es die anmeldende Person schon gibt (A-11, I-05).

    'bekannt': gleicher Name, gleiche Adresse – derselbe Mensch.
    'vielleicht': der Name in anderer Schreibweise mit derselben Adresse,
    oder derselbe Name mit derselben Nummer – „Bist du das?“. Nur Personen
    mit eigener Adresse, sonst gäbe es keinen Weg, den Link zu schicken.
    """
    con = verbinden()
    try:
        genau = con.execute("SELECT * FROM helfer WHERE schluessel = ?",
                            (normalisieren.schluessel(person["name"], person["email"]),)).fetchone()
        if genau is not None:
            return "bekannt", [genau]
        kandidaten = con.execute(
            "SELECT * FROM helfer WHERE email <> '' AND (lower(email) = ?"
            " OR (? <> '' AND telefon = ?)) ORDER BY id",
            (person["email"].lower(), person["telefon"] or "", person["telefon"] or "")).fetchall()
    finally:
        con.close()
    passend = [k for k in kandidaten if _gleicher_name(k["name"], person["name"])]
    return ("vielleicht", passend) if passend else ("", [])


def nach_email(email: str) -> list[Zeile]:
    """Wer diese Adresse als eigene hat – für „Link anfordern“."""
    con = verbinden()
    try:
        return con.execute("SELECT * FROM helfer WHERE lower(email) = ? AND email <> ''"
                           " ORDER BY id", ((email or "").lower(),)).fetchall()
    finally:
        con.close()


def bestaetigen(helfer_id: int) -> bool:
    """Die Adresse ist bestätigt (I-03). True, wenn sie es vorher nicht war."""
    con = verbinden()
    try:
        with con:
            geaendert = con.execute(
                "UPDATE helfer SET email_bestaetigt_am = ? WHERE id = ?"
                " AND email_bestaetigt_am IS NULL", (jetzt(), helfer_id)).rowcount > 0
            if geaendert:
                _protokollieren(con, helfer_id, "selbst", "Adresse bestätigt")
            _eltern_durch_anmelder(con, helfer_id)
        return geaendert
    finally:
        con.close()


def code_falsch(helfer_id: int) -> int:
    """Zählt einen falschen Code; gibt die Zahl der Fehlversuche zurück."""
    con = verbinden()
    try:
        with con:
            return int(con.execute(
                "UPDATE helfer SET code_versuche = code_versuche + 1 WHERE id = ?"
                " RETURNING code_versuche", (helfer_id,)).fetchone()[0])
    finally:
        con.close()


def teilnahmen(helfer_ids) -> list[int]:
    """Die Veranstaltungen, bei denen eine dieser Personen mitmacht – mit
    Teilnahme oder Schicht."""
    con = verbinden()
    try:
        return [int(z["vid"]) for z in con.execute(
            "SELECT DISTINCT vid FROM ("
            " SELECT veranstaltung_id AS vid FROM teilnahme WHERE helfer_id = ANY(?)"
            " UNION SELECT s.veranstaltung_id FROM einteilung e"
            " JOIN schicht s ON s.id = e.schicht_id WHERE e.helfer_id = ANY(?)) x",
            (list(helfer_ids), list(helfer_ids))).fetchall()]
    finally:
        con.close()


def mitangemeldete(helfer_id: int) -> list[Zeile]:
    con = verbinden()
    try:
        return con.execute("SELECT * FROM helfer WHERE angemeldet_von = ? ORDER BY id",
                           (helfer_id,)).fetchall()
    finally:
        con.close()


def kalender(helfer_id: int) -> list[Zeile]:
    """Alle Schichten und Springer-Zeiten der Person und ihrer
    Mitangemeldeten in Veranstaltungen, die nicht archiviert sind – fürs
    Kalender-Abo (A-10)."""
    con = verbinden()
    try:
        return con.execute(
            "SELECT 'e' || e.id AS uid, s.beginn, s.ende, b.name AS bereich,"
            " COALESCE(NULLIF(s.ort, ''), b.treffpunkt) AS ort, e.art, h.vorname, h.name,"
            " h.id AS helfer_id, v.kurz FROM einteilung e"
            " JOIN schicht s ON s.id = e.schicht_id JOIN bereich b ON b.id = s.bereich_id"
            " JOIN helfer h ON h.id = e.helfer_id"
            " JOIN kern.veranstaltung v ON v.id = s.veranstaltung_id"
            " WHERE (h.id = ? OR h.angemeldet_von = ?) AND v.status <> 'archiviert'"
            " UNION ALL"
            " SELECT 'v' || f.id, f.beginn, f.ende, 'Springer', '', 'platz', h.vorname, h.name,"
            " h.id, v.kurz FROM verfuegbarkeit f JOIN helfer h ON h.id = f.helfer_id"
            " JOIN kern.veranstaltung v ON v.id = f.veranstaltung_id"
            " WHERE (h.id = ? OR h.angemeldet_von = ?) AND f.springer = 1"
            " AND v.status <> 'archiviert'"
            " ORDER BY beginn", (helfer_id, helfer_id, helfer_id, helfer_id)).fetchall()
    finally:
        con.close()


def unbestaetigt(stunden: int, nur_unerinnert: bool = False) -> list[dict]:
    """Wer sich selbst angemeldet und vor mehr als `stunden` noch nicht
    bestätigt hat (I-03) – nur die Anmeldenden, Mitangemeldete hängen an
    ihnen. Mit der Veranstaltung der ersten Anmeldung."""
    grenze = (jetzt_lokal() - timedelta(hours=stunden)).strftime("%Y-%m-%d %H:%M:%S")
    con = verbinden()
    try:
        return [dict(z) for z in con.execute(
            "SELECT DISTINCT ON (h.id) h.*, t.veranstaltung_id, t.angemeldet_am"
            " FROM helfer h JOIN teilnahme t ON t.helfer_id = h.id AND t.quelle = 'selbst'"
            " WHERE h.email_bestaetigt_am IS NULL AND h.angemeldet_von IS NULL"
            " AND h.email <> '' AND t.angemeldet_am <= ?"
            + (" AND h.erinnert_am IS NULL" if nur_unerinnert else "") +
            " ORDER BY h.id, t.angemeldet_am", (grenze,)).fetchall()]
    finally:
        con.close()


def erinnert(helfer_id: int) -> None:
    con = verbinden()
    try:
        with con:
            con.execute("UPDATE helfer SET erinnert_am = ? WHERE id = ?", (jetzt(), helfer_id))
    finally:
        con.close()


def verfallen_lassen(helfer_id: int) -> list[int]:
    """Gibt die Plätze einer nie bestätigten Anmeldung frei (I-03): die
    selbst gebuchten Einteilungen, Springer-Zeiten und Teilnahmen der Person
    und ihrer Mitangemeldeten. Wer danach an nichts mehr hängt, wird
    gelöscht – Angaben, die niemand bestätigt hat, behalten wir nicht.
    Gibt die frei gewordenen Schichten zurück."""
    con = verbinden()
    try:
        with con:
            personen = [helfer_id] + [z["id"] for z in con.execute(
                "SELECT id FROM helfer WHERE angemeldet_von = ?", (helfer_id,)).fetchall()]
            frei = [int(z["schicht_id"]) for z in con.execute(
                "DELETE FROM einteilung WHERE helfer_id = ANY(?) AND quelle = 'selbst'"
                " RETURNING schicht_id", (personen,)).fetchall()]
            con.execute("DELETE FROM verfuegbarkeit WHERE helfer_id = ANY(?)", (personen,))
            con.execute("DELETE FROM warteliste WHERE helfer_id = ANY(?)", (personen,))
            con.execute("DELETE FROM teilnahme WHERE helfer_id = ANY(?) AND quelle = 'selbst'",
                        (personen,))
            # Mitangemeldete zuerst, sonst setzt das Löschen der Anmeldenden
            # angemeldet_von auf NULL, bevor sie geprüft sind.
            for nummer in reversed(personen):
                con.execute(
                    "DELETE FROM helfer h WHERE h.id = ? AND h.email_bestaetigt_am IS NULL"
                    " AND h.tshirt_ausgegeben_am IS NULL"
                    " AND NOT EXISTS (SELECT 1 FROM einteilung WHERE helfer_id = h.id)"
                    " AND NOT EXISTS (SELECT 1 FROM teilnahme WHERE helfer_id = h.id)"
                    " AND NOT EXISTS (SELECT 1 FROM ausleihe WHERE helfer_id = h.id)",
                    (nummer,))
            if con.execute("SELECT 1 FROM helfer WHERE id = ?", (helfer_id,)).fetchone():
                _protokollieren(con, helfer_id, "", "Nicht bestätigt – Plätze freigegeben")
        return sorted(set(frei))
    finally:
        con.close()


def moegliche_dubletten() -> list[dict]:
    """Paare, die vielleicht derselbe Mensch sind (I-05): Name in irgendeiner
    Schreibweise gleich und dazu Adresse oder Nummer. Zusammenführen kommt
    mit I-06; bis dahin sieht die Orga sie wenigstens."""
    con = verbinden()
    try:
        paare = con.execute(
            "SELECT a.id AS a_id, a.name AS a_name, a.email AS a_email,"
            " b.id AS b_id, b.name AS b_name, b.email AS b_email"
            " FROM helfer a JOIN helfer b ON a.id < b.id"
            " AND ((a.email <> '' AND lower(a.email) = lower(b.email))"
            "      OR (a.telefon <> '' AND a.telefon = b.telefon))"
            " ORDER BY a.id, b.id").fetchall()
    finally:
        con.close()
    return [dict(z) for z in paare if _gleicher_name(z["a_name"], z["b_name"])]


# --- Selbstbedienung (Lastenheft 2.5: S-01 bis S-08, R-04) -----------------
#
# Alles aus Mein Helferplatz, ohne Frist: es sind Ehrenamtliche. Wer absagt,
# tut das Richtige – hier wird es leicht gemacht und landet sofort bei der
# richtigen Person. Jede Funktion prüft selbst, ob die Person zur Anmeldung
# gehört; die Mails schreibt main.py aus dem, was zurückkommt.

def _gehoert(con: Verbindung, anmelder_id: int, helfer_id: int) -> bool:
    """Die Person selbst oder jemand, den sie mitangemeldet hat (S-06)."""
    return helfer_id == anmelder_id or con.execute(
        "SELECT 1 FROM helfer WHERE id = ? AND angemeldet_von = ?",
        (helfer_id, anmelder_id)).fetchone() is not None


def _einteilung(con: Verbindung, anmelder_id: int, einteilung_id: int):
    """Die Einteilung mit Schicht und Bereich – nur, wenn sie zur Anmeldung
    gehört."""
    zeile = con.execute(
        "SELECT e.*, s.veranstaltung_id, s.bereich_id, s.beginn, s.ende, s.datum,"
        " b.name AS bereich FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
        " JOIN bereich b ON b.id = s.bereich_id WHERE e.id = ?", (einteilung_id,)).fetchone()
    if zeile is None or not _gehoert(con, anmelder_id, zeile["helfer_id"]):
        return None
    return zeile


def einteilung_fuer(anmelder_id: int, einteilung_id: int):
    con = verbinden()
    try:
        zeile = _einteilung(con, anmelder_id, einteilung_id)
        return {**zeile, "text": _schicht_text(zeile)} if zeile else None
    finally:
        con.close()


def _belegt_zur_zeit(con: Verbindung, helfer_id: int, beginn: str, ende: str) -> bool:
    return con.execute(
        "SELECT 1 FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
        " WHERE e.helfer_id = ? AND s.beginn < ? AND ? < s.ende",
        (helfer_id, ende, beginn)).fetchone() is not None


def _nachruecken(con: Verbindung, schicht_id: int) -> list[dict]:
    """Ein Platz ist frei: erst rückt die Reserve auf, dann bekommt die
    Warteliste ihn angeboten (R-04). Wer ein Angebot bekommt, steht schon
    drin und hält den Platz bis `bestaetigen_bis`. Übersprungen wird, wer zu
    der Zeit inzwischen anderswo eingeteilt ist. Gibt die Angebote zurück."""
    s = con.execute("SELECT s.*, b.name AS bereich FROM schicht s"
                    " JOIN bereich b ON b.id = s.bereich_id WHERE s.id = ? FOR UPDATE OF s",
                    (schicht_id,)).fetchone()
    if s is None:
        return []
    text = _schicht_text(s)

    def zahl(art: str) -> int:
        return int(con.execute("SELECT COUNT(*) FROM einteilung WHERE schicht_id = ?"
                               " AND art = ?", (schicht_id, art)).fetchone()[0])

    platz, reserve = zahl("platz"), zahl("reserve")
    while platz < s["soll"]:
        e = con.execute("SELECT id, helfer_id FROM einteilung WHERE schicht_id = ?"
                        " AND art = 'reserve' AND bestaetigen_bis IS NULL"
                        " ORDER BY eingeteilt_am, id LIMIT 1", (schicht_id,)).fetchone()
        if e is None:
            break
        con.execute("UPDATE einteilung SET art = 'platz' WHERE id = ?", (e["id"],))
        _protokollieren(con, e["helfer_id"], "", "Von der Reserve auf einen Platz: " + text,
                        s["veranstaltung_id"], s["bereich_id"])
        platz, reserve = platz + 1, reserve - 1

    angebote: list[dict] = []
    jetzt_lokal_ = jetzt_lokal()
    if s["beginn"] <= marke(jetzt_lokal_):
        return angebote
    bis = min(marke(jetzt_lokal_ + timedelta(hours=config.WARTELISTE_STUNDEN)), s["beginn"])
    for w in con.execute("SELECT * FROM warteliste WHERE schicht_id = ?"
                         " ORDER BY angelegt_am, id", (schicht_id,)).fetchall():
        if platz >= s["soll"] and reserve >= s["reserve"]:
            break
        if _belegt_zur_zeit(con, w["helfer_id"], s["beginn"], s["ende"]):
            continue
        art = "platz" if platz < s["soll"] else "reserve"
        einteilung_id = con.execute(
            "INSERT INTO einteilung (schicht_id, helfer_id, quelle, art, eingeteilt_am,"
            " bestaetigen_bis) VALUES (?, ?, 'selbst', ?, ?, ?) RETURNING id",
            (schicht_id, w["helfer_id"], art, jetzt(), bis)).fetchone()[0]
        con.execute("DELETE FROM warteliste WHERE id = ?", (w["id"],))
        _protokollieren(con, w["helfer_id"], "", f"Von der Warteliste angeboten: {text}, bis {bis}",
                        s["veranstaltung_id"], s["bereich_id"])
        angebote.append({"einteilung_id": int(einteilung_id), "helfer_id": w["helfer_id"],
                         "schicht": {**dict(s), "text": text}, "bis": bis, "art": art})
        if art == "platz":
            platz += 1
        else:
            reserve += 1
    return angebote


def _abgeben(con: Verbindung, e, grund: str = "", wer: str = "selbst") -> dict:
    """Eine Einteilung abgeben (S-01): löschen, als Absage vermerken,
    nachrücken lassen. Ein abgelehntes Angebot der Warteliste ist keine
    Absage – die Person war ja nie fest eingeplant."""
    s = con.execute("SELECT s.*, b.name AS bereich FROM schicht s"
                    " JOIN bereich b ON b.id = s.bereich_id WHERE s.id = ? FOR UPDATE OF s",
                    (e["schicht_id"],)).fetchone()
    person = con.execute("SELECT * FROM helfer WHERE id = ?", (e["helfer_id"],)).fetchone()
    con.execute("DELETE FROM einteilung WHERE id = ?", (e["id"],))
    text = _schicht_text(s)
    angebot = e["bestaetigen_bis"] is not None
    jetzt_ = jetzt_lokal()
    v = VERANSTALTUNGEN.laden(s["veranstaltung_id"])
    # S-07: weniger als 24 Stunden vorher, oder während der Veranstaltung.
    kurz = (s["beginn"] <= marke(jetzt_ + timedelta(hours=24))
            or (v is not None and v["beginn"] <= jetzt_.date() <= v["ende"]))
    if not angebot:
        con.execute("INSERT INTO absage (veranstaltung_id, schicht_id, helfer_id, name, grund,"
                    " kurzfristig, am) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (s["veranstaltung_id"], s["id"], person["id"], person["name"], grund,
                     1 if kurz else 0, jetzt()))
    _protokollieren(con, person["id"], wer,
                    ("Angebot abgelehnt: " if angebot else "Abgesagt: ") + text
                    + (f" – {grund}" if grund else ""), s["veranstaltung_id"], s["bereich_id"])
    angebote = _nachruecken(con, s["id"])
    fest = int(con.execute("SELECT COUNT(*) FROM einteilung WHERE schicht_id = ?"
                           " AND art = 'platz' AND bestaetigen_bis IS NULL",
                           (s["id"],)).fetchone()[0])
    return {"schicht": {**dict(s), "text": text}, "person": person, "angebot": angebot,
            "grund": grund, "kurzfristig": kurz and not angebot, "fest": fest,
            "unter_minimum": not angebot and fest < s["minimum"], "angebote": angebote}


def stornieren(anmelder_id: int, einteilung_id: int, grund: str = "") -> dict | None:
    """Eine Schicht absagen – jederzeit (S-01)."""
    con = verbinden()
    try:
        with con:
            e = _einteilung(con, anmelder_id, einteilung_id)
            if e is None:
                return None
            return _abgeben(con, e, grund[:300])
    finally:
        con.close()


def angebot_annehmen(anmelder_id: int, einteilung_id: int) -> bool:
    """Den Platz von der Warteliste annehmen – solange das Angebot gilt."""
    con = verbinden()
    try:
        with con:
            e = _einteilung(con, anmelder_id, einteilung_id)
            if e is None or e["bestaetigen_bis"] is None or e["bestaetigen_bis"] < marke(jetzt_lokal()):
                return False
            con.execute("UPDATE einteilung SET bestaetigen_bis = NULL WHERE id = ?", (e["id"],))
            _protokollieren(con, e["helfer_id"], "selbst", "Angebot angenommen: "
                            + _schicht_text(e), e["veranstaltung_id"], e["bereich_id"])
        return True
    finally:
        con.close()


def angebote_abgelaufen() -> list[dict]:
    """Wer ein Angebot nicht bis zur Frist angenommen hat, gibt den Platz
    weiter – an die nächste auf der Warteliste. Gibt die neuen Angebote
    zurück."""
    con = verbinden()
    try:
        with con:
            neu: list[dict] = []
            for e in con.execute(
                    "SELECT e.*, s.veranstaltung_id, s.bereich_id, s.beginn, s.ende,"
                    " b.name AS bereich FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
                    " JOIN bereich b ON b.id = s.bereich_id"
                    " WHERE e.bestaetigen_bis IS NOT NULL AND e.bestaetigen_bis < ?",
                    (marke(jetzt_lokal()),)).fetchall():
                con.execute("DELETE FROM einteilung WHERE id = ?", (e["id"],))
                _protokollieren(con, e["helfer_id"], "", "Angebot verfallen: " + _schicht_text(e),
                                e["veranstaltung_id"], e["bereich_id"])
                neu += _nachruecken(con, e["schicht_id"])
            return neu
    finally:
        con.close()


def nachruecken(schicht_ids) -> list[dict]:
    """Für Plätze, die anderswo frei geworden sind – von Hand ausgetragen,
    eine Anmeldung verfallen."""
    con = verbinden()
    try:
        with con:
            angebote: list[dict] = []
            for schicht_id in sorted(set(schicht_ids)):
                angebote += _nachruecken(con, schicht_id)
            return angebote
    finally:
        con.close()


def warteliste_verlassen(anmelder_id: int, warteliste_id: int) -> bool:
    con = verbinden()
    try:
        with con:
            w = con.execute("SELECT w.*, s.veranstaltung_id, s.bereich_id, s.beginn, s.ende,"
                            " b.name AS bereich FROM warteliste w"
                            " JOIN schicht s ON s.id = w.schicht_id"
                            " JOIN bereich b ON b.id = s.bereich_id WHERE w.id = ?",
                            (warteliste_id,)).fetchone()
            if w is None or not _gehoert(con, anmelder_id, w["helfer_id"]):
                return False
            con.execute("DELETE FROM warteliste WHERE id = ?", (warteliste_id,))
            _protokollieren(con, w["helfer_id"], "selbst", "Von der Warteliste genommen: "
                            + _schicht_text(w), w["veranstaltung_id"], w["bereich_id"])
        return True
    finally:
        con.close()


def springer_absagen(anmelder_id: int, fenster_id: int) -> bool:
    con = verbinden()
    try:
        with con:
            f = con.execute("SELECT * FROM verfuegbarkeit WHERE id = ?", (fenster_id,)).fetchone()
            if f is None or not _gehoert(con, anmelder_id, f["helfer_id"]):
                return False
            con.execute("DELETE FROM verfuegbarkeit WHERE id = ?", (fenster_id,))
            _protokollieren(con, f["helfer_id"], "selbst", "Springer-Zeit abgesagt: "
                            + _schicht_text({"bereich": "Springer", "beginn": f["beginn"],
                                             "ende": f["ende"]}), f["veranstaltung_id"])
        return True
    finally:
        con.close()


def umbuchen(vid: int, anmelder_id: int, einteilung_id: int, neu_id: int) -> dict:
    """Eine Schicht gegen eine andere tauschen, in einem Schritt (S-02): die
    neue wird zuerst gebucht, erst dann die alte freigegeben. Geht die neue
    nicht, bleibt die alte. Die abzugebende zählt beim Prüfen nicht mit."""
    con = verbinden()
    try:
        with con:
            alt = _einteilung(con, anmelder_id, einteilung_id)
            if alt is None or alt["veranstaltung_id"] != vid:
                raise AnmeldeFehler(["Diese Schicht gehört nicht zu dir."])
            if neu_id == alt["schicht_id"]:
                raise AnmeldeFehler(["Das ist dieselbe Schicht."])
            schichten = _schichten_sperren(con, vid, [neu_id])
            person = con.execute("SELECT * FROM helfer WHERE id = ?",
                                 (alt["helfer_id"],)).fetchone()
            stichtag = VERANSTALTUNGEN.laden(vid)["beginn"]
            verteilung = _pruefen(con, vid, schichten, [], [{
                "vorname": person["vorname"] or person["name"],
                "volljaehrig": person["volljaehrig"], "alter": _alter(person, stichtag),
                "helfer_id": person["id"]}], ausser=einteilung_id)
            neu = schichten[0]
            art = verteilung[neu["id"]][0]
            con.execute("INSERT INTO einteilung (schicht_id, helfer_id, quelle, art,"
                        " eingeteilt_am) VALUES (?, ?, 'selbst', ?, ?)",
                        (neu["id"], person["id"], art, jetzt()))
            _protokollieren(con, person["id"], "selbst", "Dazugenommen: " + neu["text"],
                            vid, neu["bereich_id"])
            ergebnis = _abgeben(con, alt, "umgebucht auf " + neu["text"])
        return {**ergebnis, "neu": {**neu, "art": art}}
    finally:
        con.close()


def abmelden(vid: int, anmelder_id: int, helfer_ids: list[int], grund: str = "") -> list[dict]:
    """Ganz abmelden von einer Veranstaltung (S-03): alle Schichten,
    Wartelisten und Springer-Zeiten der gewählten Personen auf einmal. Gibt
    je abgegebener Schicht zurück, was _abgeben liefert."""
    con = verbinden()
    try:
        with con:
            abgaben: list[dict] = []
            for helfer_id in helfer_ids:
                if not _gehoert(con, anmelder_id, helfer_id):
                    continue
                for e in con.execute(
                        "SELECT e.*, s.veranstaltung_id, s.bereich_id, s.beginn, s.ende,"
                        " b.name AS bereich FROM einteilung e"
                        " JOIN schicht s ON s.id = e.schicht_id"
                        " JOIN bereich b ON b.id = s.bereich_id"
                        " WHERE e.helfer_id = ? AND s.veranstaltung_id = ? AND s.ende > ?",
                        (helfer_id, vid, marke(jetzt_lokal()))).fetchall():
                    abgaben.append(_abgeben(con, e, grund[:300]))
                con.execute("DELETE FROM warteliste WHERE helfer_id = ? AND schicht_id IN"
                            " (SELECT id FROM schicht WHERE veranstaltung_id = ?)", (helfer_id, vid))
                con.execute("DELETE FROM verfuegbarkeit WHERE helfer_id = ? AND veranstaltung_id = ?",
                            (helfer_id, vid))
                con.execute("DELETE FROM teilnahme WHERE helfer_id = ? AND veranstaltung_id = ?",
                            (helfer_id, vid))
                _protokollieren(con, helfer_id, "selbst", "Abgemeldet"
                                + (f" – {grund[:300]}" if grund else ""), vid)
            return abgaben
    finally:
        con.close()


def angaben_aendern(anmelder_id: int, helfer_id: int, werte: dict) -> bool:
    """Telefon, Shirt, Verpflegung (S-04). Die Adresse geht eigens – sie
    gilt erst, wenn sie bestätigt ist."""
    erlaubt = ("telefon", "tshirt", "tshirt_roh", "veggie")
    werte = {k: w for k, w in werte.items() if k in erlaubt}
    if not werte:
        return False
    con = verbinden()
    try:
        with con:
            if not _gehoert(con, anmelder_id, helfer_id):
                return False
            con.execute("UPDATE helfer SET " + ", ".join(k + " = ?" for k in werte) +
                        ", geaendert_am = ? WHERE id = ?", (*werte.values(), jetzt(), helfer_id))
            _protokollieren(con, helfer_id, "selbst", "Angaben geändert")
        return True
    finally:
        con.close()


def bemerkung(vid: int, helfer_id: int) -> str:
    con = verbinden()
    try:
        zeile = con.execute("SELECT bemerkung FROM teilnahme WHERE veranstaltung_id = ?"
                            " AND helfer_id = ?", (vid, helfer_id)).fetchone()
        return zeile["bemerkung"] if zeile else ""
    finally:
        con.close()


def bemerkung_setzen(vid: int, anmelder_id: int, helfer_id: int, text: str) -> bool:
    con = verbinden()
    try:
        with con:
            if not _gehoert(con, anmelder_id, helfer_id):
                return False
            return con.execute("UPDATE teilnahme SET bemerkung = ? WHERE veranstaltung_id = ?"
                               " AND helfer_id = ?", (text[:1000], vid, helfer_id)).rowcount > 0
    finally:
        con.close()


def email_vormerken(anmelder_id: int, helfer_id: int, email: str) -> str:
    """Eine neue Adresse vormerken (S-04) – oder für eine mitangemeldete
    Person die erste eigene (S-06). Gilt erst nach der Bestätigung. Gibt
    einen Grund zurück, wenn es nicht geht."""
    con = verbinden()
    try:
        with con:
            if not _gehoert(con, anmelder_id, helfer_id):
                return "Diese Person gehört nicht zu deiner Anmeldung."
            person = con.execute("SELECT * FROM helfer WHERE id = ?", (helfer_id,)).fetchone()
            if email == person["email"]:
                return "Das ist schon die Adresse."
            if con.execute("SELECT 1 FROM helfer WHERE schluessel = ? AND id <> ?",
                           (normalisieren.schluessel(person["name"], email), helfer_id)).fetchone():
                return ("Unter dieser Adresse gibt es schon jemanden mit demselben Namen – "
                        "sag uns Bescheid, dann führen wir das zusammen.")
            con.execute("UPDATE helfer SET email_neu = ? WHERE id = ?", (email, helfer_id))
        return ""
    finally:
        con.close()


def email_uebernehmen(helfer_id: int) -> bool:
    """Die vorgemerkte Adresse ist bestätigt: sie gilt jetzt. Wer
    mitangemeldet war, steht damit auf eigenen Füßen (S-06); wer andere
    mitangemeldet hat, nimmt sie mit."""
    con = verbinden()
    try:
        with con:
            person = con.execute("SELECT * FROM helfer WHERE id = ? FOR UPDATE",
                                 (helfer_id,)).fetchone()
            if person is None or not person["email_neu"]:
                return False
            email = person["email_neu"]
            schluessel = normalisieren.schluessel(person["name"], email)
            if con.execute("SELECT 1 FROM helfer WHERE schluessel = ? AND id <> ?",
                           (schluessel, helfer_id)).fetchone():
                return False
            con.execute("UPDATE helfer SET email = ?, email_neu = NULL, schluessel = ?,"
                        " email_bestaetigt_am = ?, angemeldet_von = NULL, geaendert_am = ?"
                        " WHERE id = ?", (email, schluessel, jetzt(), jetzt(), helfer_id))
            for m in con.execute("SELECT id, name FROM helfer WHERE angemeldet_von = ?"
                                 " AND email = ''", (helfer_id,)).fetchall():
                neu = normalisieren.schluessel(m["name"], email)
                if not con.execute("SELECT 1 FROM helfer WHERE schluessel = ?", (neu,)).fetchone():
                    con.execute("UPDATE helfer SET schluessel = ? WHERE id = ?", (neu, m["id"]))
            _protokollieren(con, helfer_id, "selbst",
                            "Eigene Adresse bestätigt" if person["angemeldet_von"]
                            else "Neue Adresse bestätigt")
        return True
    finally:
        con.close()


def _loeschen(con: Verbindung, helfer_id: int) -> None:
    con.execute("UPDATE absage SET name = '' WHERE helfer_id = ?", (helfer_id,))
    con.execute("DELETE FROM helfer WHERE id = ?", (helfer_id,))


def _nach_rueckgabe_loeschen(con: Verbindung) -> int:
    """Wer löschen wollte und nichts mehr ausgeliehen hat, ist jetzt weg."""
    zeilen = con.execute(
        "SELECT h.id FROM helfer h WHERE h.loeschen_beantragt_am IS NOT NULL"
        " AND NOT EXISTS (SELECT 1 FROM ausleihe a WHERE a.helfer_id = h.id"
        " AND a.zurueck_am IS NULL)").fetchall()
    for z in zeilen:
        _loeschen(con, z["id"])
    return len(zeilen)


def nach_rueckgabe_loeschen() -> int:
    con = verbinden()
    try:
        with con:
            return _nach_rueckgabe_loeschen(con)
    finally:
        con.close()


def loeschen(anmelder_id: int, helfer_ids: list[int]) -> dict:
    """Daten löschen (S-05): künftige Schichten werden dabei abgesagt. Wer
    noch etwas ausgeliehen hat (Funkgerät), wird erst nach der Rückgabe
    gelöscht, samt der Unterschrift als Beleg. Gibt zurück, wer weg ist, wer
    wartet und was abgesagt wurde."""
    con = verbinden()
    try:
        with con:
            ergebnis = {"geloescht": [], "wartet": [], "abgaben": []}
            # Mitangemeldete zuerst – sonst stünden sie kurz ohne Ansprechpartner da.
            reihenfolge = sorted(helfer_ids, key=lambda h: h == anmelder_id)
            for helfer_id in reihenfolge:
                if not _gehoert(con, anmelder_id, helfer_id):
                    continue
                person = con.execute("SELECT * FROM helfer WHERE id = ?", (helfer_id,)).fetchone()
                for e in con.execute(
                        "SELECT e.* FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
                        " WHERE e.helfer_id = ? AND s.ende > ?",
                        (helfer_id, marke(jetzt_lokal()))).fetchall():
                    ergebnis["abgaben"].append(_abgeben(con, e, "Daten gelöscht"))
                con.execute("DELETE FROM warteliste WHERE helfer_id = ?", (helfer_id,))
                offen = con.execute("SELECT 1 FROM ausleihe WHERE helfer_id = ?"
                                    " AND zurueck_am IS NULL", (helfer_id,)).fetchone()
                if offen:
                    con.execute("UPDATE helfer SET loeschen_beantragt_am = ? WHERE id = ?",
                                (jetzt(), helfer_id))
                    _protokollieren(con, helfer_id, "selbst",
                                    "Löschen gewünscht – nach der Rückgabe")
                    ergebnis["wartet"].append(person)
                else:
                    _loeschen(con, helfer_id)
                    ergebnis["geloescht"].append(person)
            return ergebnis
    finally:
        con.close()


def leitung_empfaenger(bereich_id: int) -> list[Zeile]:
    """Wen eine Absage sofort erreichen soll (S-07): die Leitung des Bereichs."""
    con = verbinden()
    try:
        return con.execute(
            "SELECT k.name, k.email FROM bereich_leitung bl JOIN kern.konto k"
            " ON k.id = bl.konto_id WHERE bl.bereich_id = ? AND k.aktiv = 1"
            " ORDER BY lower(k.name)", (bereich_id,)).fetchall()
    finally:
        con.close()


def _springer_jetzt(con: Verbindung, vid: int, beginn: str, ende: str) -> list[Zeile]:
    """Springer, die zu der Zeit können und nirgends eingeteilt sind (R-06)."""
    return con.execute(
        "SELECT DISTINCT h.id, h.name, h.telefon FROM verfuegbarkeit f"
        " JOIN helfer h ON h.id = f.helfer_id WHERE f.veranstaltung_id = ? AND f.springer = 1"
        " AND f.beginn < ? AND ? < f.ende AND NOT EXISTS ("
        "  SELECT 1 FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
        "  WHERE e.helfer_id = h.id AND s.beginn < ? AND ? < s.ende)"
        " ORDER BY h.name", (vid, ende, beginn, ende, beginn)).fetchall()


def kurzfristige_absagen(vid: int, leitung: int | None = None) -> list[dict]:
    """Kurzfristige Absagen für Schichten, die noch nicht vorbei sind (S-07)
    – mit den Springern, die jetzt einspringen könnten."""
    sql = ("SELECT a.*, s.beginn, s.ende, s.datum, s.minimum, s.soll, b.name AS bereich,"
           " (SELECT COUNT(*) FROM einteilung e WHERE e.schicht_id = s.id"
           "  AND e.art = 'platz') AS besetzt"
           " FROM absage a JOIN schicht s ON s.id = a.schicht_id"
           " JOIN bereich b ON b.id = s.bereich_id"
           " WHERE a.veranstaltung_id = ? AND a.kurzfristig = 1 AND s.ende > ?")
    werte: tuple = (vid, marke(jetzt_lokal()))
    if leitung is not None:
        sql += " AND " + _GELEITET
        werte += (leitung,)
    con = verbinden()
    try:
        zeilen = [dict(z) for z in con.execute(sql + " ORDER BY s.beginn, a.am", werte).fetchall()]
        for z in zeilen:
            z["springer"] = _springer_jetzt(con, vid, z["beginn"], z["ende"])
        return zeilen
    finally:
        con.close()


def aenderungen(vid: int, leitung: int | None = None, stunden: int = 24) -> dict:
    """„Änderungen seit gestern“ (S-08): Absagen und was Helfer selbst
    geändert haben. Eine Bereichsleitung sieht nur ihre Bereiche."""
    seit = (jetzt_lokal() - timedelta(hours=stunden)).strftime("%Y-%m-%d %H:%M:%S")
    filter_a = filter_p = ""
    werte_a: tuple = (vid, seit)
    werte_p: tuple = (vid, seit)
    if leitung is not None:
        filter_a = " AND " + _GELEITET
        filter_p = " AND b.id IS NOT NULL AND " + _GELEITET
        werte_a += (leitung,)
        werte_p += (leitung,)
    con = verbinden()
    try:
        absagen = con.execute(
            "SELECT a.*, s.beginn, s.ende, b.name AS bereich FROM absage a"
            " JOIN schicht s ON s.id = a.schicht_id JOIN bereich b ON b.id = s.bereich_id"
            " WHERE a.veranstaltung_id = ? AND a.am >= ?" + filter_a +
            " ORDER BY a.am DESC", werte_a).fetchall()
        sonst = con.execute(
            "SELECT p.*, h.name FROM protokoll p JOIN helfer h ON h.id = p.helfer_id"
            " LEFT JOIN bereich b ON b.id = p.bereich_id"
            " WHERE p.veranstaltung_id = ? AND p.am >= ? AND p.was NOT LIKE 'Abgesagt:%'"
            + filter_p + " ORDER BY p.am DESC, p.id DESC", werte_p).fetchall()
        return {"absagen": absagen, "sonst": sonst, "seit": seit}
    finally:
        con.close()


def warteliste_von(schicht_id: int) -> list[Zeile]:
    con = verbinden()
    try:
        return con.execute("SELECT w.*, h.name FROM warteliste w JOIN helfer h ON h.id = w.helfer_id"
                           " WHERE w.schicht_id = ? ORDER BY w.angelegt_am, w.id",
                           (schicht_id,)).fetchall()
    finally:
        con.close()


# --- Mails (Lastenheft 2.4, C-01) ------------------------------------------

def mail_einreihen(helfer_id: int | None, mail: tuple, con: Verbindung | None = None) -> None:
    """mail = (typ, empfänger, betreff, text) aus mail.py."""
    typ, empfaenger, betreff, text = mail
    eigene = con is None
    con = con or verbinden()
    try:
        with (con if eigene else _offen()):
            con.execute(
                "INSERT INTO mail_out (helfer_id, typ, empfaenger, betreff, body, angelegt_am)"
                " VALUES (?, ?, ?, ?, ?, ?)", (helfer_id, typ, empfaenger, betreff, text, jetzt()))
    finally:
        if eigene:
            con.close()


def mails_faellig(grenze: int = 20) -> list[Zeile]:
    con = verbinden()
    try:
        return con.execute(
            "SELECT * FROM mail_out WHERE gesendet_am IS NULL AND versuche < ?"
            " AND (naechster_versuch IS NULL OR naechster_versuch <= ?)"
            " ORDER BY id LIMIT ?", (config.MAIL_MAX_VERSUCHE, jetzt(), grenze)).fetchall()
    finally:
        con.close()


def mail_gesendet(mail_id: int) -> None:
    con = verbinden()
    try:
        with con:
            con.execute("UPDATE mail_out SET gesendet_am = ?, versuche = versuche + 1,"
                        " letzter_fehler = NULL, naechster_versuch = NULL WHERE id = ?",
                        (jetzt(), mail_id))
    finally:
        con.close()


def mail_fehlgeschlagen(mail_id: int, fehler: str, naechster_versuch: str | None) -> None:
    con = verbinden()
    try:
        with con:
            con.execute("UPDATE mail_out SET versuche = versuche + 1, letzter_fehler = ?,"
                        " naechster_versuch = ? WHERE id = ?",
                        (fehler[:500], naechster_versuch, mail_id))
    finally:
        con.close()


def mails_aufraeumen(tage: int = 30) -> int:
    """Verschickte Mails nach einem Monat weg – darin stehen Namen, Schichten
    und Links, und gebraucht wird davon nichts mehr."""
    grenze = (jetzt_lokal() - timedelta(days=tage)).strftime("%Y-%m-%d %H:%M:%S")
    con = verbinden()
    try:
        with con:
            return con.execute("DELETE FROM mail_out WHERE gesendet_am IS NOT NULL"
                               " AND gesendet_am < ?", (grenze,)).rowcount
    finally:
        con.close()


# --- Einsatzgrenzen (Lastenheft 2.3: K-05 bis K-09) ------------------------

# So steht es im Backoffice – und so könnte es die Person lesen (K-08).
GRENZ_ARTEN = {"nicht_anbieten": "nicht anbieten", "nur_zu_zweit": "nur zu zweit einplanen"}


def _protokollieren(con: Verbindung, helfer_id: int, wer: str, was: str,
                    vid: int | None = None, bereich_id: int | None = None) -> None:
    con.execute("INSERT INTO protokoll (helfer_id, wer, was, am, veranstaltung_id, bereich_id)"
                " VALUES (?, ?, ?, ?, ?, ?)", (helfer_id, wer, was, jetzt(), vid, bereich_id))


def protokoll(helfer_id: int) -> list[Zeile]:
    con = verbinden()
    try:
        return con.execute("SELECT * FROM protokoll WHERE helfer_id = ?"
                           " ORDER BY am DESC, id DESC", (helfer_id,)).fetchall()
    finally:
        con.close()


def _gesperrt(con: Verbindung, vid: int, helfer_id: int) -> set[int]:
    """Die Schichten, die dieser Person nicht angeboten werden – einzeln
    oder mit ihrem ganzen Bereich."""
    return {int(z["id"]) for z in con.execute(
        "SELECT s.id FROM schicht s JOIN einsatzgrenze g ON g.helfer_id = ?"
        " AND g.art = 'nicht_anbieten'"
        " AND (g.schicht_id = s.id OR g.bereich_id = s.bereich_id)"
        " WHERE s.veranstaltung_id = ?", (helfer_id, vid)).fetchall()}


def gesperrt(vid: int, helfer_id: int) -> set[int]:
    """Für Mein Helferplatz (2.4) und den Assistenten: was dort nicht
    erscheint."""
    con = verbinden()
    try:
        return _gesperrt(con, vid, helfer_id)
    finally:
        con.close()


def unter_grenze(schicht_id: int, helfer_id: int) -> bool:
    """Ob diese Schicht der Person nicht angeboten wird – fürs Einteilen von
    Hand (K-09)."""
    return _gibt_es(
        "SELECT 1 FROM schicht s JOIN einsatzgrenze g ON g.helfer_id = ?"
        " AND g.art = 'nicht_anbieten'"
        " AND (g.schicht_id = s.id OR g.bereich_id = s.bereich_id) WHERE s.id = ?",
        (helfer_id, schicht_id))


_GRENZE_VON = (
    " FROM einsatzgrenze g"
    " LEFT JOIN schicht s ON s.id = g.schicht_id"
    " JOIN bereich b ON b.id = COALESCE(g.bereich_id, s.bereich_id)")
_GRENZE_SPALTEN = "SELECT g.*, b.name AS bereich, b.veranstaltung_id, s.beginn, s.ende"


def _grenz_text(g) -> str:
    """'Shuttle – nicht anbieten' oder mit der Schicht davor."""
    ziel = _schicht_text(g) if g["schicht_id"] else g["bereich"]
    return f"{ziel} – {GRENZ_ARTEN[g['art']]}"


def grenzen(vid: int, helfer_id: int, leitung: int | None = None) -> list[dict]:
    """Die Einsatzgrenzen einer Person in dieser Veranstaltung. Eine
    Bereichsleitung sieht nur die in ihren Bereichen (K-08)."""
    sql = (_GRENZE_SPALTEN + _GRENZE_VON +
           " WHERE g.helfer_id = ? AND b.veranstaltung_id = ?")
    werte: tuple = (helfer_id, vid)
    if leitung is not None:
        sql += " AND " + _GELEITET
        werte += (leitung,)
    con = verbinden()
    try:
        zeilen = [dict(z) for z in con.execute(
            sql + " ORDER BY lower(b.name), s.beginn NULLS FIRST", werte).fetchall()]
    finally:
        con.close()
    for z in zeilen:
        z["text"] = _grenz_text(z)
    return zeilen


def grenze_laden(grenze_id: int) -> Zeile | None:
    con = verbinden()
    try:
        return con.execute(_GRENZE_SPALTEN + _GRENZE_VON + " WHERE g.id = ?",
                           (grenze_id,)).fetchone()
    finally:
        con.close()


def grenze_setzen(vid: int, helfer_id: int, art: str, bereich_id: int | None = None,
                  schicht_id: int | None = None, wer: str = "") -> bool:
    """Setzt die Grenze; eine auf dasselbe Ziel ersetzt die alte. False, wenn
    Bereich oder Schicht nicht zu dieser Veranstaltung gehören."""
    if art not in GRENZ_ARTEN or (bereich_id is None) == (schicht_id is None):
        return False
    if art == "nur_zu_zweit" and bereich_id is None:
        return False
    tabelle, nummer = ("bereich", bereich_id) if bereich_id else ("schicht", schicht_id)
    con = verbinden()
    try:
        with con:
            if con.execute(f"SELECT 1 FROM {tabelle} WHERE id = ? AND veranstaltung_id = ?",
                           (nummer, vid)).fetchone() is None:
                return False
            # Dieselbe Grenze noch einmal ist keine Änderung – auch nicht im
            # Protokoll.
            if con.execute(f"SELECT 1 FROM einsatzgrenze WHERE helfer_id = ?"
                           f" AND {tabelle}_id = ? AND art = ?",
                           (helfer_id, nummer, art)).fetchone() is not None:
                return True
            grenze_id = con.execute(
                "INSERT INTO einsatzgrenze (helfer_id, bereich_id, schicht_id, art,"
                " angelegt_von, angelegt_am) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (helfer_id, bereich_id, schicht_id) DO UPDATE SET"
                " art = excluded.art, angelegt_von = excluded.angelegt_von,"
                " angelegt_am = excluded.angelegt_am RETURNING id",
                (helfer_id, bereich_id, schicht_id, art, wer, jetzt())).fetchone()[0]
            g = con.execute(_GRENZE_SPALTEN + _GRENZE_VON + " WHERE g.id = ?",
                            (grenze_id,)).fetchone()
            _protokollieren(con, helfer_id, wer, "Einsatzgrenze gesetzt: " + _grenz_text(g))
        return True
    finally:
        con.close()


def grenze_aufheben(grenze_id: int, wer: str = "") -> int | None:
    """Hebt die Grenze auf; gibt die Person zurück, None, wenn es sie nicht gab."""
    con = verbinden()
    try:
        with con:
            g = con.execute(_GRENZE_SPALTEN + _GRENZE_VON + " WHERE g.id = ?",
                            (grenze_id,)).fetchone()
            if g is None:
                return None
            con.execute("DELETE FROM einsatzgrenze WHERE id = ?", (grenze_id,))
            _protokollieren(con, g["helfer_id"], wer,
                            "Einsatzgrenze aufgehoben: " + _grenz_text(g))
        return int(g["helfer_id"])
    finally:
        con.close()


def allein(vid: int, leitung: int | None = None,
           schicht_id: int | None = None) -> list[Zeile]:
    """Wer „nur zu zweit“ hat und in einer Schicht allein steht (K-07) – für
    den Hinweis an Orga und Bereichsleitung. Vorbei ist vorbei."""
    sql = ("SELECT s.id AS schicht_id, s.datum, s.beginn, s.ende, b.name AS bereich,"
           " h.id AS helfer_id, h.name"
           " FROM einsatzgrenze g"
           " JOIN schicht s ON s.bereich_id = g.bereich_id"
           " JOIN einteilung e ON e.schicht_id = s.id AND e.helfer_id = g.helfer_id"
           " JOIN bereich b ON b.id = s.bereich_id"
           " JOIN helfer h ON h.id = g.helfer_id"
           " WHERE g.art = 'nur_zu_zweit' AND s.veranstaltung_id = ? AND s.ende > ?"
           " AND (SELECT COUNT(DISTINCT x.helfer_id) FROM einteilung x"
           "      WHERE x.schicht_id = s.id) = 1")
    werte: tuple = (vid, marke(jetzt_lokal()))
    if leitung is not None:
        sql += " AND " + _GELEITET
        werte += (leitung,)
    if schicht_id is not None:
        sql += " AND s.id = ?"
        werte += (schicht_id,)
    con = verbinden()
    try:
        return con.execute(sql + " ORDER BY s.beginn, lower(b.name)", werte).fetchall()
    finally:
        con.close()


# --- Einteilung ------------------------------------------------------------

def einteilen(schicht_id: int, helfer_id: int, quelle: str = "hand",
              kuerzel: str = "", vermerk: str = "",
              con: Verbindung | None = None) -> int:
    """Von Hand oder aus dem Import. Ein Vermerk heißt: trotz Einsatzgrenze
    (K-09) – das steht dann auch im Protokoll der Person."""
    eigene = con is None
    con = con or verbinden()
    try:
        with (con if eigene else _offen()):
            zeiger = con.execute(
                "INSERT INTO einteilung (schicht_id, helfer_id, quelle,"
                " kuerzel, vermerk, eingeteilt_am) VALUES (?, ?, ?, ?, ?, ?)"
                " RETURNING id",
                (schicht_id, helfer_id, quelle, kuerzel, vermerk, jetzt()))
            nummer = int(zeiger.fetchone()[0])
            # Wer jetzt drin ist, wartet nicht mehr (R-04).
            con.execute("DELETE FROM warteliste WHERE schicht_id = ? AND helfer_id = ?",
                        (schicht_id, helfer_id))
            # B-05: wer von Hand eingeteilt hat. Der Import schreibt sein
            # eigenes Protokoll (import_vermerken).
            if quelle == "hand":
                s = con.execute("SELECT s.beginn, s.ende, s.veranstaltung_id, s.bereich_id,"
                                " b.name AS bereich FROM schicht s"
                                " JOIN bereich b ON b.id = s.bereich_id WHERE s.id = ?",
                                (schicht_id,)).fetchone()
                _protokollieren(con, helfer_id, kuerzel, "Eingeteilt: " + _schicht_text(s),
                                s["veranstaltung_id"], s["bereich_id"])
            if vermerk:
                schicht = con.execute(
                    "SELECT s.beginn, s.ende, b.name AS bereich FROM schicht s"
                    " JOIN bereich b ON b.id = s.bereich_id WHERE s.id = ?",
                    (schicht_id,)).fetchone()
                _protokollieren(con, helfer_id, kuerzel,
                                f"Trotz Einsatzgrenze eingeteilt: {_schicht_text(schicht)}"
                                f" – {vermerk}")
        return nummer
    finally:
        if eigene:
            con.close()


def austragen(einteilung_id: int, kuerzel: str = "") -> list[dict]:
    """Von Hand austragen, mit Protokoll (B-05). Der Platz ist frei –
    Reserve und Warteliste rücken nach (R-04); zurück kommen die Angebote."""
    con = verbinden()
    try:
        with con:
            zeile = con.execute("DELETE FROM einteilung WHERE id = ?"
                                " RETURNING schicht_id, helfer_id", (einteilung_id,)).fetchone()
            if zeile is None:
                return []
            s = con.execute("SELECT s.beginn, s.ende, s.veranstaltung_id, s.bereich_id,"
                            " b.name AS bereich FROM schicht s"
                            " JOIN bereich b ON b.id = s.bereich_id WHERE s.id = ?",
                            (zeile["schicht_id"],)).fetchone()
            _protokollieren(con, zeile["helfer_id"], kuerzel, "Ausgetragen: " + _schicht_text(s),
                            s["veranstaltung_id"], s["bereich_id"])
            return _nachruecken(con, zeile["schicht_id"])
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

def konflikte(vid: int) -> list[dict]:
    """Wer ist zur selben Zeit auf zwei Schichten eingeteilt?

    Reine Überlappung der Zeitstempel, deshalb geht das in einer Abfrage –
    Schichten über Mitternacht inbegriffen, weil beginn und ende volle
    Zeitpunkte sind. Die Bedingung a.id < b.id nennt jedes Paar genau einmal.
    """
    con = verbinden()
    try:
        return [dict(z) for z in con.execute(
            "SELECT h.id AS helfer_id, h.name,"
            " a.id AS schicht_a, ba.name AS bereich_a, a.beginn AS beginn_a,"
            " a.ende AS ende_a,"
            " b.id AS schicht_b, bb.name AS bereich_b, b.beginn AS beginn_b,"
            " b.ende AS ende_b"
            " FROM einteilung ea"
            " JOIN einteilung eb ON eb.helfer_id = ea.helfer_id"
            " JOIN schicht a ON a.id = ea.schicht_id"
            " JOIN schicht b ON b.id = eb.schicht_id"
            " JOIN bereich ba ON ba.id = a.bereich_id"
            " JOIN bereich bb ON bb.id = b.bereich_id"
            " JOIN helfer h ON h.id = ea.helfer_id"
            " WHERE a.id < b.id AND a.beginn < b.ende AND b.beginn < a.ende"
            "   AND a.veranstaltung_id = ? AND b.veranstaltung_id = ?"
            " GROUP BY h.id, a.id, b.id, ba.id, bb.id"
            " ORDER BY a.beginn, lower(h.name)", (vid, vid)).fetchall()]
    finally:
        con.close()


def doppelt_besetzt(vid: int) -> list[dict]:
    """Dieselbe Person mehrfach auf demselben Platz. Kommt in den
    Bestandsdaten vor und ist immer entweder ein Sammeleintrag oder eine
    Doppelanmeldung – die Orga muss draufschauen."""
    con = verbinden()
    try:
        return [dict(z) for z in con.execute(
            "SELECT h.id AS helfer_id, h.name, h.email, s.id AS schicht_id,"
            " b.name AS bereich, s.beginn, COUNT(*) AS anzahl"
            " FROM einteilung e"
            " JOIN helfer h ON h.id = e.helfer_id"
            " JOIN schicht s ON s.id = e.schicht_id"
            " JOIN bereich b ON b.id = s.bereich_id"
            " WHERE s.veranstaltung_id = ?"
            " GROUP BY h.id, s.id, b.id HAVING COUNT(*) > 1"
            " ORDER BY s.beginn, lower(h.name)", (vid,)).fetchall()]
    finally:
        con.close()


def zaehler(vid: int) -> dict:
    """Schichten und Besetzung zählen für die Veranstaltung; Helfer,
    T-Shirt-Größen und Verpflegung für alle – sie gehören keiner."""
    con = verbinden()
    try:
        def eine(sql: str, *werte) -> int:
            return con.execute(sql, werte).fetchone()[0]

        # Der Bedarf ist die Summe der Soll-Zahlen; Reserve zählt nicht mit.
        bedarf = eine("SELECT COALESCE(SUM(soll), 0) FROM schicht"
                      " WHERE veranstaltung_id = ?", vid)
        besetzt = eine("SELECT COUNT(*) FROM einteilung e JOIN schicht s"
                       " ON s.id = e.schicht_id WHERE s.veranstaltung_id = ?"
                       " AND e.art = 'platz'", vid)
        return {
            "schichten": eine("SELECT COUNT(*) FROM schicht WHERE veranstaltung_id = ?",
                              vid),
            "helfer": eine("SELECT COUNT(*) FROM helfer WHERE aktiv = 1"),
            "bedarf": bedarf,
            "besetzt": besetzt,
            "offen": max(0, bedarf - besetzt),
            "luecken": eine(
                "SELECT COUNT(*) FROM schicht s WHERE s.veranstaltung_id = ?"
                " AND s.soll > (SELECT COUNT(*) FROM einteilung e"
                "                 WHERE e.schicht_id = s.id AND e.art = 'platz')", vid),
            # R-02: rot ist, was unter dem Minimum liegt – darunter geht es nicht.
            "unter_minimum": eine(
                "SELECT COUNT(*) FROM schicht s WHERE s.veranstaltung_id = ?"
                " AND s.minimum > (SELECT COUNT(*) FROM einteilung e"
                "                    WHERE e.schicht_id = s.id AND e.art = 'platz')", vid),
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

def programm(vid: int, serie: str = "", tag: str = "",
             mit_entfallenen: bool = True) -> list[Zeile]:
    bedingungen, werte = ["veranstaltung_id = ?"], [vid]
    if serie:
        bedingungen.append("serie = ?")
        werte.append(serie)
    if tag:
        bedingungen.append("datum = ?")
        werte.append(tag)
    if not mit_entfallenen:
        bedingungen.append("entfallen_am IS NULL")
    wo = " WHERE " + " AND ".join(bedingungen)

    con = verbinden()
    try:
        # Einträge ohne Uhrzeit ("anschließend") ganz nach hinten, sonst
        # stünden sie wegen NULL am Anfang des Tages.
        return con.execute(
            "SELECT * FROM programm" + wo +
            " ORDER BY datum, beginn IS NULL, beginn, lower(titel)",
            werte).fetchall()
    finally:
        con.close()


def programm_eintrag(programm_id: int) -> Zeile | None:
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


def abrufe(grenze: int = 20) -> list[Zeile]:
    con = verbinden()
    try:
        return con.execute(
            "SELECT * FROM abruf_lauf ORDER BY id DESC LIMIT ?",
            (grenze,)).fetchall()
    finally:
        con.close()


def letzter_erfolg(serie: str) -> Zeile | None:
    con = verbinden()
    try:
        return con.execute(
            "SELECT * FROM abruf_lauf WHERE serie = ? AND erfolg = 1"
            " ORDER BY id DESC LIMIT 1", (serie,)).fetchone()
    finally:
        con.close()


def import_vermerken(art: str, datei: str, zeilen: int, bericht: str,
                     kuerzel: str = "", erfolg: bool = True) -> None:
    con = verbinden()
    try:
        with con:
            con.execute(
                "INSERT INTO import_lauf (art, datei, zeilen, bericht, kuerzel,"
                " erfolg, gelaufen_am) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (art, datei, zeilen, bericht, kuerzel,
                 1 if erfolg else 0, jetzt()))
    finally:
        con.close()


def letzter_import(nur_geglueckt: bool = True) -> Zeile | None:
    con = verbinden()
    try:
        return con.execute(
            "SELECT * FROM import_lauf"
            + (" WHERE erfolg = 1" if nur_geglueckt else "")
            + " ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        con.close()


def importe() -> list[Zeile]:
    con = verbinden()
    try:
        return con.execute(
            "SELECT * FROM import_lauf ORDER BY id DESC LIMIT 20").fetchall()
    finally:
        con.close()


# --- Monitor ---------------------------------------------------------------

MONITOR_SCHLUESSEL = "monitor_token"
# Eigener Token fuers Unterschriften-Tablet. Bewusst nicht derselbe wie beim
# Monitor: diese Adresse nimmt Eingaben entgegen, die andere nicht. Wer den
# Monitor an der Wand teilt, soll damit nicht das Tablet mitgeben.
TABLET_SCHLUESSEL = "tablet_token"


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


def tablet_token(anlegen: bool = False) -> str:
    vorhanden = einstellung(TABLET_SCHLUESSEL)
    if vorhanden or not anlegen:
        return vorhanden
    return tablet_token_neu()


def tablet_token_neu() -> str:
    import secrets
    neu = secrets.token_urlsafe(24)
    einstellung_setzen(TABLET_SCHLUESSEL, neu)
    return neu


def tablet_token_loeschen() -> None:
    einstellung_setzen(TABLET_SCHLUESSEL, "")


def _schichten_mit_namen(con: Verbindung, bedingung: str,
                         werte: tuple) -> list[dict]:
    """Schichten samt der Namen aller Eingeteilten.

    Die Namen kommen in einer zweiten Abfrage für alle Schichten zusammen,
    nicht in einer je Schicht – sonst wären es auf dem Monitor bei jedem
    Auffrischen zwei Dutzend Abfragen statt zwei.
    """
    zeilen = _mit_suche([dict(z) for z in con.execute(
        "SELECT " + _SCHICHT_SPALTEN + _SCHICHT_VON + " WHERE " + bedingung +
        " ORDER BY s.beginn, lower(b.name)", werte)], *_SCHICHT_SUCHE)
    if not zeilen:
        return []

    platzhalter = ",".join("?" for _ in zeilen)
    namen: dict[int, list[str]] = {z["id"]: [] for z in zeilen}
    for eintrag in con.execute(
            "SELECT e.schicht_id, h.name FROM einteilung e"
            " JOIN helfer h ON h.id = e.helfer_id"
            " WHERE e.schicht_id IN (" + platzhalter + ")"
            " ORDER BY lower(h.name)",
            [z["id"] for z in zeilen]):
        namen[eintrag["schicht_id"]].append(eintrag["name"])
    for zeile in zeilen:
        zeile["namen"] = namen[zeile["id"]]
    return zeilen


def monitor_tage(vid: int) -> list[dict]:
    """Alle Tage, an denen etwas ansteht – für die Tagesleiste im Monitor.

    Schicht- und Programmtage zusammen: der Aufbau am 25.08. hat kein
    Programm, ein reiner Programmtag hätte keine Schicht. Beides gehört in
    die Leiste.
    """
    con = verbinden()
    try:
        tage = {z["datum"] for z in con.execute(
            "SELECT DISTINCT datum FROM schicht WHERE veranstaltung_id = ?", (vid,))}
        tage |= {z["datum"] for z in con.execute(
            "SELECT DISTINCT datum FROM programm WHERE entfallen_am IS NULL"
            " AND veranstaltung_id = ?", (vid,))}
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


def tagesstand(vid: int, datum: str, zeitpunkt: datetime) -> dict:
    """Ein ganzer Tag am Stück – der Blick voraus, den die Kollegen brauchen.

    Bewusst eine eigene Ansicht und nicht derselbe Aufbau mit anderem Datum:
    "Jetzt im Dienst" und "Als Nächstes" beziehen sich auf diesen Moment. An
    einem künftigen Tag gibt es keinen, und zwei der drei Tafeln blieben leer.
    Hier zählt stattdessen der Tagesablauf von früh bis spät.
    """
    con = verbinden()
    try:
        schichten = _schichten_mit_namen(
            con, "s.veranstaltung_id = ? AND s.datum = ?", (vid, datum))
        programm = [dict(z) for z in con.execute(
            "SELECT * FROM programm WHERE entfallen_am IS NULL"
            " AND veranstaltung_id = ? AND datum = ?"
            " ORDER BY beginn IS NULL, beginn, lower(titel)",
            (vid, datum))]
    finally:
        con.close()

    try:
        zeit = datetime.fromisoformat(datum)
        lang = (config.WOCHENTAGE[zeit.weekday()] + ", " +
                zeit.strftime("%d.%m.%Y"))
    except ValueError:
        lang = datum

    bedarf = sum(s["soll"] for s in schichten)
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


def monitor_stand(vid: int, zeitpunkt: datetime,
                  vorschau_minuten: int = 120) -> dict:
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
        laufend = _schichten_mit_namen(
            con, "s.veranstaltung_id = ? AND s.beginn <= ? AND s.ende > ?",
            (vid, jetzt, jetzt))
        demnaechst = _schichten_mit_namen(
            con, "s.veranstaltung_id = ? AND s.beginn > ? AND s.beginn <= ?",
            (vid, jetzt, bis))

        # NUR der heutige Tag. Vorher stand hier zusätzlich "beginn >= jetzt",
        # und damit zog die Jetzt-Ansicht am 25.08. das Programm vom 28.08.
        # herein – drei Tage voraus, direkt neben den Schichten von jetzt.
        # Die Schichten daneben halten sich ans Vorschaufenster; das Programm
        # war als einziges unbegrenzt.
        programm = [dict(z) for z in con.execute(
            "SELECT * FROM programm WHERE entfallen_am IS NULL"
            " AND veranstaltung_id = ? AND datum = ?"
            " ORDER BY beginn IS NULL, beginn", (vid, heute))]

        # Damit die Tafel vor der Veranstaltung nicht bloß leer dasteht.
        naechster = con.execute(
            "SELECT datum FROM programm WHERE entfallen_am IS NULL"
            " AND veranstaltung_id = ? AND datum > ? ORDER BY datum LIMIT 1",
            (vid, heute)).fetchone()

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

        naechster_tag = None
        if naechster:
            try:
                zeit = datetime.fromisoformat(naechster["datum"])
                naechster_tag = {
                    "datum": naechster["datum"],
                    "lang": (config.WOCHENTAGE[zeit.weekday()] + ", " +
                             zeit.strftime("%d.%m.")),
                }
            except ValueError:
                naechster_tag = None

        gesamt = zaehler(vid)
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
            "programm_naechster_tag": naechster_tag,
            # Wie viele Punkte der heutige Tag insgesamt hat. Damit lässt sich
            # "heute ist noch nichts" von "heute ist alles durch" und von
            # "für heute gibt es gar keins" unterscheiden – drei Zustände, die
            # auf dem Bildschirm nicht gleich aussehen sollten.
            "programm_heute": len(programm),
            "offen_jetzt": sum(z["fehlt"] for z in laufend),
            "offen_gesamt": gesamt["offen"],
            # R-06, T-04: wer jetzt einspringen kann. S-07: kurzfristige
            # Absagen – auf dem Monitor ohne Namen, er hängt im Zelt.
            "springer": springer_lage(vid, zeitpunkt),
            "kurzfristig": [a for a in kurzfristige_absagen(vid)
                            if a["beginn"] <= (zeitpunkt + timedelta(hours=24))
                            .strftime("%Y-%m-%d %H:%M")],
        }
    finally:
        con.close()


# --- Aufgabenplan ----------------------------------------------------------

def aufgaben(vid: int, phase: str = "", status: str = "",
             tag: str = "") -> list[Zeile]:
    bedingungen, werte = ["veranstaltung_id = ?"], [vid]
    for spalte, wert in (("phase", phase), ("status", status), ("datum", tag)):
        if wert:
            bedingungen.append(spalte + " = ?")
            werte.append(wert)
    wo = " WHERE " + " AND ".join(bedingungen)

    con = verbinden()
    try:
        # Der Pool (ohne Datum) ganz nach hinten: er hat keinen Platz im
        # Ablauf, soll aber nicht zwischen den Tagen verschwinden.
        return _mit_suche(con.execute(
            "SELECT * FROM aufgabe" + wo +
            " ORDER BY datum IS NULL, datum, beginn IS NULL, beginn,"
            " lower(titel)", werte).fetchall(),
            "titel", "ort", "verantwortlich", "notiz")
    finally:
        con.close()


def aufgabe_laden(aufgabe_id: int) -> Zeile | None:
    con = verbinden()
    try:
        return con.execute("SELECT * FROM aufgabe WHERE id = ?",
                           (aufgabe_id,)).fetchone()
    finally:
        con.close()


_AUFGABE_SPALTEN = ("titel", "phase", "datum", "beginn", "ende", "ort",
                    "verantwortlich", "kontakt", "notiz", "status")


def aufgabe_anlegen(vid: int, werte: dict, kuerzel: str = "") -> int:
    con = verbinden()
    try:
        with con:
            zeiger = con.execute(
                "INSERT INTO aufgabe (veranstaltung_id, " + ", ".join(_AUFGABE_SPALTEN) +
                ", angelegt_am, geaendert_am, kuerzel) VALUES (?, " +
                ", ".join("?" for _ in _AUFGABE_SPALTEN) + ", ?, ?, ?)"
                " RETURNING id",
                (vid, *[werte.get(s) for s in _AUFGABE_SPALTEN],
                 jetzt(), jetzt(), kuerzel))
            nummer = int(zeiger.fetchone()[0])
        return nummer
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
            # FOR UPDATE: ohne Sperre liest ein zweiter, gleichzeitiger
            # Speichervorgang dieselbe Version, und beide gewinnen.
            vorhanden = con.execute(
                "SELECT version FROM aufgabe WHERE id = ? FOR UPDATE",
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


def aufgaben_zaehler(vid: int) -> dict:
    con = verbinden()
    try:
        je_status = {z["status"]: z["anzahl"] for z in con.execute(
            "SELECT status, COUNT(*) AS anzahl FROM aufgabe"
            " WHERE veranstaltung_id = ? GROUP BY status", (vid,))}
        return {
            "gesamt": sum(je_status.values()),
            "offen": je_status.get("offen", 0),
            "arbeit": je_status.get("arbeit", 0),
            "erledigt": je_status.get("erledigt", 0),
            "pool": con.execute(
                "SELECT COUNT(*) FROM aufgabe WHERE veranstaltung_id = ?"
                " AND datum IS NULL", (vid,)).fetchone()[0],
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
            "SELECT " + spalte + " FROM aufgabe"
            " WHERE TRIM(" + spalte + ") <> ''"
            " GROUP BY " + spalte +
            " ORDER BY lower(" + spalte + ") LIMIT 50")]
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
                "SELECT version FROM programm WHERE id = ? FOR UPDATE",
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


# --- T-Shirt-Ausgabe -------------------------------------------------------

def tshirt_ausgeben(helfer_id: int, groesse: str, kuerzel: str = "") -> bool:
    """Vermerkt die Ausgabe. `groesse` ist die TATSÄCHLICH ausgegebene – an
    der Ausgabe stellt sich oft heraus, dass es doch eine Nummer größer sein
    muss. Die angekündigte bleibt daneben stehen; beide zusammen sind für die
    Nachbestellung mehr wert als eine allein."""
    con = verbinden()
    try:
        with con:
            zeiger = con.execute(
                "UPDATE helfer SET tshirt_ausgegeben_am = ?,"
                " tshirt_ausgegeben = ?, tshirt_kuerzel = ?, geaendert_am = ?"
                " WHERE id = ?",
                (jetzt(), groesse or None, kuerzel, jetzt(), helfer_id))
        return zeiger.rowcount > 0
    finally:
        con.close()


def tshirt_zuruecknehmen(helfer_id: int) -> bool:
    """Für den Fall, dass jemand versehentlich abgehakt wurde."""
    con = verbinden()
    try:
        with con:
            zeiger = con.execute(
                "UPDATE helfer SET tshirt_ausgegeben_am = NULL,"
                " tshirt_ausgegeben = NULL, tshirt_kuerzel = '',"
                " geaendert_am = ? WHERE id = ?", (jetzt(), helfer_id))
        return zeiger.rowcount > 0
    finally:
        con.close()


def tshirt_zaehler() -> dict:
    con = verbinden()
    try:
        def eine(sql):
            return con.execute(sql).fetchone()[0]

        return {
            "ausgegeben": eine("SELECT COUNT(*) FROM helfer"
                               " WHERE tshirt_ausgegeben_am IS NOT NULL"),
            "offen": eine("SELECT COUNT(*) FROM helfer"
                          " WHERE tshirt_ausgegeben_am IS NULL"),
            "je_groesse": {z["g"]: z["n"] for z in con.execute(
                "SELECT tshirt_ausgegeben AS g, COUNT(*) AS n FROM helfer"
                " WHERE tshirt_ausgegeben IS NOT NULL"
                " GROUP BY tshirt_ausgegeben")},
            # Wo die ausgegebene von der angekündigten Größe abweicht – das
            # ist die Zahl, die bei der nächsten Bestellung zählt.
            "abweichend": eine(
                "SELECT COUNT(*) FROM helfer WHERE tshirt_ausgegeben IS NOT NULL"
                " AND tshirt IS NOT NULL AND tshirt_ausgegeben <> tshirt"),
        }
    finally:
        con.close()


def helfer_von_hand(daten: dict) -> tuple[int | None, str]:
    """Legt einen Helfer von Hand an. Gibt (id, Meldung) zurück.

    Für alle, die nicht im Registrierungstool stehen: Leute, die spontan
    mithelfen, auf keiner Schicht auftauchen und trotzdem ein T-Shirt oder ein
    Funkgerät bekommen.
    """
    name = normalisieren.text(daten.get("name"))
    if not name:
        return None, "ohne-namen"

    con = verbinden()
    try:
        merkmal = normalisieren.schluessel(name, daten.get("email", ""))
        vorhanden = con.execute(
            "SELECT id FROM helfer WHERE schluessel = ?", (merkmal,)).fetchone()
        if vorhanden is not None:
            # Nicht stillschweigend ein zweites Mal anlegen – der Schlüssel
            # ist eindeutig, das gäbe einen Fehler statt einer Erklärung.
            return int(vorhanden["id"]), "gibt-es-schon"
        with con:
            nummer, _ = helfer_anlegen(con, daten)
        return nummer, "angelegt"
    finally:
        con.close()


def helfer_aendern(helfer_id: int, daten: dict) -> bool:
    con = verbinden()
    try:
        name = normalisieren.text(daten.get("name"))
        if not name:
            return False
        with con:
            zeiger = con.execute(
                "UPDATE helfer SET name = ?, email = ?, telefon = ?,"
                " veggie = ?, tshirt = ?, tshirt_roh = ?, bemerkung = ?,"
                " schluessel = ?, geaendert_am = ? WHERE id = ?",
                (name, normalisieren.text(daten.get("email")),
                 normalisieren.text(daten.get("telefon")),
                 daten.get("veggie"), daten.get("tshirt"),
                 normalisieren.text(daten.get("tshirt_roh")),
                 normalisieren.text(daten.get("bemerkung")),
                 normalisieren.schluessel(name, daten.get("email", "")),
                 jetzt(), helfer_id))
        return zeiger.rowcount > 0
    except IntegrityError:
        # Name und Mailadresse zusammen gibt es schon ein zweites Mal.
        return False
    finally:
        con.close()


def helfer_umbenennen(helfer_id: int, name: str) -> bool:
    """Nur den Namen ändern – für die Korrektur am Tablet.

    Der Erkennungsschlüssel hängt am Namen und muss mitwandern, sonst entsteht
    beim nächsten Import ein zweiter Datensatz für dieselbe Person. Gibt es
    Name und Mailadresse zusammen schon, bleibt alles, wie es war: dann sind
    es zwei Menschen, nicht einer mit zwei Namen.
    """
    sauber = normalisieren.text(name)
    if not sauber:
        return False
    con = verbinden()
    try:
        vorhanden = con.execute("SELECT * FROM helfer WHERE id = ?",
                                (helfer_id,)).fetchone()
        if vorhanden is None or vorhanden["name"] == sauber:
            return False
        with con:
            con.execute(
                "UPDATE helfer SET name = ?, schluessel = ?, geaendert_am = ?"
                " WHERE id = ?",
                (sauber, normalisieren.schluessel(sauber, vorhanden["email"]),
                 jetzt(), helfer_id))
        return True
    except IntegrityError:
        return False
    finally:
        con.close()


def ausleihe_mit_name(ausleihe_id: int) -> Zeile | None:
    """Eine Ausleihe samt Name der Person – für den Wortlaut am Tablet."""
    con = verbinden()
    try:
        return con.execute(
            "SELECT a.*, h.name FROM ausleihe a JOIN helfer h ON h.id = a.helfer_id"
            " WHERE a.id = ?", (ausleihe_id,)).fetchone()
    finally:
        con.close()


def schluessel_mit_fahrzeug(schluessel_id: int) -> Zeile | None:
    """Ein Schlüsselvorgang samt Kennzeichen – für den Wortlaut am Tablet."""
    con = verbinden()
    try:
        return con.execute(
            "SELECT s.*, f.kennzeichen FROM schluessel s"
            " JOIN fahrzeug f ON f.id = s.fahrzeug_id WHERE s.id = ?",
            (schluessel_id,)).fetchone()
    finally:
        con.close()


def ausleihe_laden(ausleihe_id: int) -> Zeile | None:
    con = verbinden()
    try:
        return con.execute("SELECT * FROM ausleihe WHERE id = ?",
                           (ausleihe_id,)).fetchone()
    finally:
        con.close()


def schluessel_umbenennen(schluessel_id: int, name: str) -> bool:
    """Der Name am Schlüsselvorgang – und im Fahrzeugstamm, falls dort noch
    keiner steht."""
    sauber = normalisieren.text(name)
    if not sauber:
        return False
    con = verbinden()
    try:
        with con:
            zeile = con.execute("SELECT * FROM schluessel WHERE id = ?",
                                (schluessel_id,)).fetchone()
            if zeile is None:
                return False
            con.execute("UPDATE schluessel SET name = ? WHERE id = ?",
                        (sauber, schluessel_id))
            con.execute(
                "UPDATE fahrzeug SET name = ?, geaendert_am = ?"
                " WHERE id = ? AND TRIM(name) = ''",
                (sauber, jetzt(), zeile["fahrzeug_id"]))
        return True
    finally:
        con.close()


# --- Materialausleihe ------------------------------------------------------

MATERIAL = ("funke", "headset", "ersatzakku")
MATERIAL_TEXT = {"funke": "Funkgerät", "headset": "Headset",
                 "ersatzakku": "Ersatzakku"}


# Womit das Ausgabeformular vorbelegt ist, wenn nichts eingestellt wurde.
# Ein Funkgerät ist der Normalfall, der Rest die Ausnahme.
MATERIAL_VORGABE = {"funke": 1, "headset": 0, "ersatzakku": 0}

# Höher als das ist keine Vorbelegung mehr, sondern ein Tippfehler.
MATERIAL_VORGABE_MAX = 20


def material_vorgaben() -> dict[str, int]:
    """Die Vorbelegung des Ausgabeformulars.

    Steht in der Einstellungstabelle und nicht in der .env: das ist ein Wert,
    den die Orga im laufenden Betrieb ändern will, wenn sich herausstellt,
    dass jeder auch ein Headset bekommt. Ein Neustart des Dienstes dafür wäre
    unverhältnismäßig.
    """
    ergebnis = {}
    for stueck in MATERIAL:
        roh = einstellung("vorgabe_" + stueck)
        try:
            wert = int(roh)
        except (TypeError, ValueError):
            wert = MATERIAL_VORGABE[stueck]
        ergebnis[stueck] = min(max(0, wert), MATERIAL_VORGABE_MAX)
    return ergebnis


def material_vorgaben_setzen(werte: dict) -> dict[str, int]:
    """Speichert die Vorbelegung und gibt zurück, was tatsächlich gilt."""
    for stueck in MATERIAL:
        try:
            wert = int(str(werte.get(stueck, "")).strip())
        except (TypeError, ValueError):
            continue
        einstellung_setzen("vorgabe_" + stueck,
                           str(min(max(0, wert), MATERIAL_VORGABE_MAX)))
    return material_vorgaben()


def ausleihen(vid: int, helfer_id: int, mengen: dict, datum: str | None = None,
              bemerkung: str = "", kuerzel: str = "") -> int | None:
    def menge(stueck):
        try:
            return max(0, int(mengen.get(stueck, 0) or 0))
        except (TypeError, ValueError):
            return 0

    if sum(menge(s) for s in MATERIAL) <= 0:
        return None

    con = verbinden()
    try:
        with con:
            zeiger = con.execute(
                "INSERT INTO ausleihe (veranstaltung_id, helfer_id, datum, funke,"
                " headset, ersatzakku, bemerkung, ausgegeben_am, ausgegeben_von)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                (vid, helfer_id, datum or None, *[menge(s) for s in MATERIAL],
                 normalisieren.text(bemerkung), jetzt(), kuerzel))
            nummer = int(zeiger.fetchone()[0])
        return nummer
    finally:
        con.close()


def ausleihe_zurueck(ausleihe_id: int, mengen: dict | None = None,
                     kuerzel: str = "") -> bool:
    """Ohne `mengen` kommt alles zurück. Mit `mengen` nur ein Teil – wer das
    Funkgerät bringt und den Ersatzakku behält, ist der Normalfall und kein
    Sonderfall, für den man erst etwas erfinden müsste."""
    con = verbinden()
    try:
        with con:
            zeile = con.execute(
                "SELECT * FROM ausleihe WHERE id = ? FOR UPDATE",
                (ausleihe_id,)).fetchone()
            if zeile is None:
                return False

            neu = {}
            for stueck in MATERIAL:
                if mengen is None:
                    neu[stueck] = zeile[stueck]
                else:
                    try:
                        wert = int(mengen.get(stueck, 0) or 0)
                    except (TypeError, ValueError):
                        wert = 0
                    neu[stueck] = min(max(0, wert), zeile[stueck])

            vollstaendig = all(neu[s] >= zeile[s] for s in MATERIAL)
            con.execute(
                "UPDATE ausleihe SET funke_zurueck = ?, headset_zurueck = ?,"
                " ersatzakku_zurueck = ?, zurueck_am = ?, zurueck_von = ?"
                " WHERE id = ?",
                (*[neu[s] for s in MATERIAL],
                 jetzt() if vollstaendig else None,
                 kuerzel if vollstaendig else zeile["zurueck_von"],
                 ausleihe_id))
            # Wer seine Daten löschen wollte, als noch etwas ausgeliehen war,
            # ist jetzt dran (S-05) – samt der Unterschrift als Beleg.
            if vollstaendig:
                _nach_rueckgabe_loeschen(con)
        return True
    finally:
        con.close()


def ausleihe_loeschen(ausleihe_id: int) -> bool:
    con = verbinden()
    try:
        with con:
            zeiger = con.execute("DELETE FROM ausleihe WHERE id = ?",
                                 (ausleihe_id,))
        return zeiger.rowcount > 0
    finally:
        con.close()


def ausleihen_liste(vid: int, nur_offen: bool = False) -> list[Zeile]:
    con = verbinden()
    try:
        return _mit_suche(con.execute(
            "SELECT a.*, h.name, h.email, h.telefon,"
            " (a.funke - a.funke_zurueck) AS funke_offen,"
            " (a.headset - a.headset_zurueck) AS headset_offen,"
            " (a.ersatzakku - a.ersatzakku_zurueck) AS ersatzakku_offen"
            " FROM ausleihe a"
            " JOIN helfer h ON h.id = a.helfer_id"
            " WHERE a.veranstaltung_id = ?" +
            (" AND a.zurueck_am IS NULL" if nur_offen else "") +
            " ORDER BY a.zurueck_am IS NOT NULL, a.ausgegeben_am DESC", (vid,)
        ).fetchall(), "name", "bemerkung")
    finally:
        con.close()


def material_zaehler(vid: int) -> dict:
    """Was insgesamt herausging und was davon noch draußen ist."""
    con = verbinden()
    try:
        teile = []
        for stueck in MATERIAL:
            teile.append("COALESCE(SUM(" + stueck + "), 0) AS " + stueck + "_raus")
            teile.append("COALESCE(SUM(" + stueck + " - " + stueck +
                         "_zurueck), 0) AS " + stueck + "_offen")
        zeile = con.execute("SELECT " + ", ".join(teile) +
                            " FROM ausleihe WHERE veranstaltung_id = ?",
                            (vid,)).fetchone()
        return {s: {"raus": zeile[s + "_raus"], "offen": zeile[s + "_offen"]}
                for s in MATERIAL}
    finally:
        con.close()


# --- Fahrzeuge und Schlüssel -----------------------------------------------

def fahrzeug_sichern(kennzeichen: str, name: str = "",
                     bemerkung: str = "") -> tuple[int | None, bool]:
    """Legt das Fahrzeug an oder ergänzt es. Gibt (id, neu) zurück.

    Der Stamm baut sich damit nebenbei auf: wer ein Kennzeichen eintippt, das
    es noch nicht gibt, legt es an, und beim nächsten Mal steht der Name schon
    da. Leere Felder werden ergänzt, gefüllte bleiben stehen – eine spätere
    Ausgabe ohne Namen soll den vorhandenen nicht löschen.
    """
    norm = normalisieren.kennzeichen(kennzeichen)
    if not norm:
        return None, False

    con = verbinden()
    try:
        with con:
            vorhanden = con.execute(
                "SELECT * FROM fahrzeug WHERE kennzeichen_norm = ?",
                (norm,)).fetchone()
            if vorhanden is None:
                zeiger = con.execute(
                    "INSERT INTO fahrzeug (kennzeichen, kennzeichen_norm,"
                    " name, bemerkung, angelegt_am) VALUES (?, ?, ?, ?, ?)"
                    " RETURNING id",
                    (normalisieren.kennzeichen_anzeige(kennzeichen), norm,
                     normalisieren.text(name), normalisieren.text(bemerkung),
                     jetzt()))
                return int(zeiger.fetchone()[0]), True

            aenderungen, werte = [], []
            for spalte, wert in (("name", name), ("bemerkung", bemerkung)):
                sauber = normalisieren.text(wert)
                if sauber and not vorhanden[spalte]:
                    aenderungen.append(spalte + " = ?")
                    werte.append(sauber)
            if aenderungen:
                con.execute(
                    "UPDATE fahrzeug SET " + ", ".join(aenderungen) +
                    ", geaendert_am = ? WHERE id = ?",
                    (*werte, jetzt(), vorhanden["id"]))
            return int(vorhanden["id"]), False
    finally:
        con.close()


def fahrzeuge() -> list[Zeile]:
    con = verbinden()
    try:
        return con.execute(
            "SELECT f.*,"
            " (SELECT COUNT(*) FROM schluessel s WHERE s.fahrzeug_id = f.id"
            "  AND s.zurueck_am IS NULL) AS draussen,"
            " (SELECT COUNT(*) FROM schluessel s WHERE s.fahrzeug_id = f.id)"
            "  AS ausgaben"
            " FROM fahrzeug f ORDER BY lower(f.kennzeichen)").fetchall()
    finally:
        con.close()


def fahrzeug_loeschen(fahrzeug_id: int) -> str:
    """Nimmt ein Fahrzeug aus dem Stamm. Gibt zurueck, was daraus wurde.

    Nur, solange kein Vorgang daran haengt. schluessel.fahrzeug_id ist mit
    ON DELETE CASCADE verknuepft und die Fremdschluessel sind eingeschaltet:
    ein Loeschen risse also die ganze Ausgabehistorie des Wagens mit, und die
    Unterschriften dazu blieben als Verweise ins Leere stehen - die haengen
    ueber art und vorgang_id daran, ohne Fremdschluessel, der sie
    mitraeumte.

    Der Stamm baut sich von selbst auf; zu loeschen gibt es hier vor allem
    Vertipper, und an denen haengt in aller Regel nichts. Wo doch, ist erst
    der Vorgang zu loeschen - das ist eine bewusste Entscheidung mehr, aber
    keine, die still Daten verliert.
    """
    con = verbinden()
    try:
        with con:
            zeile = con.execute(
                "SELECT (SELECT COUNT(*) FROM schluessel s"
                "  WHERE s.fahrzeug_id = f.id) AS vorgaenge"
                " FROM fahrzeug f WHERE f.id = ?", (fahrzeug_id,)).fetchone()
            if zeile is None:
                return "unbekannt"
            if zeile["vorgaenge"]:
                return "hat-vorgaenge"
            con.execute("DELETE FROM fahrzeug WHERE id = ?", (fahrzeug_id,))
        return "weg"
    finally:
        con.close()


def fahrzeug_suchen(kennzeichen: str) -> Zeile | None:
    norm = normalisieren.kennzeichen(kennzeichen)
    if not norm:
        return None
    con = verbinden()
    try:
        return con.execute("SELECT * FROM fahrzeug WHERE kennzeichen_norm = ?",
                           (norm,)).fetchone()
    finally:
        con.close()


def schluessel_ausgeben(vid: int, fahrzeug_id: int, name: str, bemerkung: str = "",
                        kuerzel: str = "") -> int:
    con = verbinden()
    try:
        with con:
            zeiger = con.execute(
                "INSERT INTO schluessel (veranstaltung_id, fahrzeug_id, name,"
                " bemerkung, ausgegeben_am, ausgegeben_von)"
                " VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
                (vid, fahrzeug_id, normalisieren.text(name),
                 normalisieren.text(bemerkung), jetzt(), kuerzel))
            nummer = int(zeiger.fetchone()[0])
        return nummer
    finally:
        con.close()


def schluessel_zurueck(schluessel_id: int, kuerzel: str = "") -> bool:
    con = verbinden()
    try:
        with con:
            zeiger = con.execute(
                "UPDATE schluessel SET zurueck_am = ?, zurueck_von = ?"
                " WHERE id = ? AND zurueck_am IS NULL",
                (jetzt(), kuerzel, schluessel_id))
        return zeiger.rowcount > 0
    finally:
        con.close()


def schluessel_loeschen(schluessel_id: int) -> bool:
    con = verbinden()
    try:
        with con:
            zeiger = con.execute("DELETE FROM schluessel WHERE id = ?",
                                 (schluessel_id,))
        return zeiger.rowcount > 0
    finally:
        con.close()


def schluessel_liste(vid: int, nur_offen: bool = False) -> list[Zeile]:
    con = verbinden()
    try:
        return _mit_suche(con.execute(
            "SELECT s.*, f.kennzeichen, f.kennzeichen_norm,"
            " f.name AS halter"
            " FROM schluessel s JOIN fahrzeug f ON f.id = s.fahrzeug_id"
            " WHERE s.veranstaltung_id = ?" +
            (" AND s.zurueck_am IS NULL" if nur_offen else "") +
            " ORDER BY s.zurueck_am IS NOT NULL, s.ausgegeben_am DESC", (vid,)
        ).fetchall(), "kennzeichen", "kennzeichen_norm", "name", "bemerkung")
    finally:
        con.close()


def namen_vorschlaege(vid: int) -> list[str]:
    """Helfernamen für die Vorschlagsliste bei der Schlüsselausgabe.

    Die vom Shuttle zuerst: dort werden die meisten Schlüssel gebraucht. Alle
    anderen danach – ein Schlüssel kann auch an jemand anderen gehen, und eine
    Liste, die das ausschließt, wäre im entscheidenden Moment im Weg.
    """
    con = verbinden()
    try:
        shuttle = [z["name"] for z in con.execute(
            "SELECT h.name FROM helfer h"
            " JOIN einteilung e ON e.helfer_id = h.id"
            " JOIN schicht s ON s.id = e.schicht_id"
            " JOIN bereich b ON b.id = s.bereich_id"
            " WHERE b.name ILIKE '%shuttle%' AND s.veranstaltung_id = ?"
            " GROUP BY h.name ORDER BY lower(h.name)", (vid,))]
        gesehen = set(shuttle)
        rest = [z["name"] for z in con.execute(
            "SELECT name FROM helfer ORDER BY lower(name)")
            if z["name"] not in gesehen]
        return shuttle + rest
    finally:
        con.close()


# --- Noch eine Schicht? und das gemeinsame Ziel (Lastenheft 2.6) ------------

def tagesziele(vid: int) -> list[dict]:
    """G-04: je Tag, wie viele der geplanten Plätze besetzt sind – nur was
    öffentlich ist, Reserve zählt nicht und Überbuchung nicht doppelt."""
    con = verbinden()
    try:
        return [dict(z) for z in con.execute(
            "SELECT s.datum, SUM(s.soll) AS soll, SUM(LEAST(s.soll,"
            " (SELECT COUNT(*) FROM einteilung e WHERE e.schicht_id = s.id"
            "  AND e.art = 'platz'))) AS besetzt"
            " FROM schicht s JOIN bereich b ON b.id = s.bereich_id"
            " WHERE s.veranstaltung_id = ? AND s.intern = 0 AND b.intern = 0"
            " GROUP BY s.datum HAVING SUM(s.soll) > 0 ORDER BY s.datum", (vid,)).fetchall()]
    finally:
        con.close()


def schicht_vorschlaege(vid: int, helfer_ids: list[int], anzahl: int = 3) -> list[dict]:
    """G-03: Schichten, die zu den eingetragenen passen – am liebsten am
    selben Tag im selben Bereich direkt davor oder danach, dann am selben
    Tag, dann die, die am dringendsten gebraucht werden. Nur was für alle
    frei ist, sich mit nichts überschneidet, nicht hinter einer Einsatzgrenze
    liegt, zum Alter passt und keine Voraussetzung verlangt, die noch
    niemand bestätigt hat."""
    if not helfer_ids:
        return []
    v = VERANSTALTUNGEN.laden(vid)
    con = verbinden()
    try:
        eigene = con.execute(
            "SELECT DISTINCT s.* FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
            " WHERE e.helfer_id = ANY(?) AND s.veranstaltung_id = ?",
            (list(helfer_ids), vid)).fetchall()
        wartet = {z["schicht_id"] for z in con.execute(
            "SELECT schicht_id FROM warteliste WHERE helfer_id = ANY(?)",
            (list(helfer_ids),)).fetchall()}
        gesperrt: set[int] = set()
        alter: list[int] = []
        for helfer_id in helfer_ids:
            gesperrt |= _gesperrt(con, vid, helfer_id)
            zeile = con.execute("SELECT * FROM helfer WHERE id = ?", (helfer_id,)).fetchone()
            jahre = _alter(zeile, v["beginn"]) if zeile else None
            if jahre is not None:
                alter.append(jahre)
    finally:
        con.close()
    eigene_ids = {s["id"] for s in eigene}
    bestaetigt = {s["bereich_id"] for s in eigene}
    juengste = min(alter) if alter else None

    def rang(s) -> tuple[int, str]:
        for e in eigene:
            if s["datum"] == e["datum"] and s["bereich_id"] == e["bereich_id"]:
                if s["beginn"] == e["ende"]:
                    return 0, "direkt danach"
                if s["ende"] == e["beginn"]:
                    return 0, "direkt davor"
        if any(s["datum"] == e["datum"] and s["bereich_id"] == e["bereich_id"] for e in eigene):
            return 1, "am selben Tag, im selben Bereich"
        if any(s["datum"] == e["datum"] for e in eigene):
            return 2, "am selben Tag"
        return 3, ""

    passend = []
    for s in oeffentliche_schichten(vid):
        if (s["id"] in eigene_ids or s["id"] in gesperrt or s["id"] in wartet
                or s["frei"] + s["reserve_frei"] < len(helfer_ids)
                or any(selbstanmeldung.ueberschneiden(s["beginn"], s["ende"], e["beginn"], e["ende"])
                       for e in eigene)
                or (s["alter_ab"] and juengste is not None and juengste < s["alter_ab"])
                or ((s["voraussetzungen"] or "").strip() and s["bereich_id"] not in bestaetigt)):
            continue
        stufe, warum = rang(s)
        passend.append({**s, "stufe": stufe, "warum": warum})
    passend.sort(key=lambda s: (s["stufe"], not s["dringend"], s["beginn"]))
    return passend[:anzahl]


def naechstes_goodie(vid: int, schichten: int) -> str:
    """„Noch eine Schicht bis …“ (G-03): das Goodie, für das genau eine
    Schicht fehlt – nur, wenn die Veranstaltung Goodies ausgibt (V-07)."""
    if not angebot(vid)["goodies"]:
        return ""
    for g in goodies(vid):
        if g["ab_schichten"] == schichten + 1:
            return g["name"]
    return ""


# --- Druckansichten und Notfallmappe (Lastenheft 2.8) ------------------------

def druckliste(vid: int, bereich_id: int | None = None, datum: str = "",
               schicht_id: int | None = None, leitung: int | None = None) -> list[dict]:
    """Die Schichten für eine Liste (L-01, L-04) – je Schicht, je Bereich und
    Tag, je Tag –, jede mit den Leuten darauf und der Warteliste. Wer keine
    eigene Nummer hat, weil mitangemeldet, wird über die Person erreicht, die
    angemeldet hat. Einsatzgrenzen stehen nirgends (K-07)."""
    sql = ("SELECT s.*, b.name AS bereich, b.treffpunkt,"
           " (SELECT COUNT(*) FROM einteilung e WHERE e.schicht_id = s.id"
           "  AND e.art = 'platz') AS besetzt"
           " FROM schicht s JOIN bereich b ON b.id = s.bereich_id"
           " WHERE s.veranstaltung_id = ?")
    werte: tuple = (vid,)
    if bereich_id is not None:
        sql += " AND s.bereich_id = ?"
        werte += (bereich_id,)
    if datum:
        sql += " AND s.datum = ?"
        werte += (datum,)
    if schicht_id is not None:
        sql += " AND s.id = ?"
        werte += (schicht_id,)
    if leitung is not None:
        sql += " AND " + _GELEITET
        werte += (leitung,)
    con = verbinden()
    try:
        schichten = [dict(z) for z in con.execute(
            sql + " ORDER BY lower(b.name), s.beginn, s.id", werte).fetchall()]
        for s in schichten:
            s["leute"] = con.execute(
                "SELECT e.art, e.bestaetigen_bis, h.id, h.name, h.telefon, h.tshirt,"
                " h.tshirt_roh, h.veggie, a.name AS ueber_name, a.telefon AS ueber_telefon,"
                " (e.quelle = 'selbst' AND COALESCE(a.email_bestaetigt_am,"
                "  h.email_bestaetigt_am) IS NULL) AS unbestaetigt,"
                " (h.eltern_email <> '' AND h.eltern_bestaetigt_am IS NULL) AS eltern_fehlt"
                " FROM einteilung e JOIN helfer h ON h.id = e.helfer_id"
                " LEFT JOIN helfer a ON a.id = h.angemeldet_von"
                " WHERE e.schicht_id = ?"
                " ORDER BY e.art = 'reserve', lower(h.name)", (s["id"],)).fetchall()
            s["warteliste"] = con.execute(
                "SELECT h.name, COALESCE(NULLIF(h.telefon, ''), a.telefon, '') AS telefon"
                " FROM warteliste w JOIN helfer h ON h.id = w.helfer_id"
                " LEFT JOIN helfer a ON a.id = h.angemeldet_von"
                " WHERE w.schicht_id = ? ORDER BY w.angelegt_am, w.id", (s["id"],)).fetchall()
        return schichten
    finally:
        con.close()


def springer_am(vid: int, datum: str) -> list[Zeile]:
    """Wer an dem Tag als Springer kommt – für die Notfallmappe (L-03)."""
    con = verbinden()
    try:
        return con.execute(
            "SELECT f.beginn, f.ende, h.name,"
            " COALESCE(NULLIF(h.telefon, ''), a.telefon, '') AS telefon"
            " FROM verfuegbarkeit f JOIN helfer h ON h.id = f.helfer_id"
            " LEFT JOIN helfer a ON a.id = h.angemeldet_von"
            " WHERE f.veranstaltung_id = ? AND f.springer = 1 AND left(f.beginn, 10) = ?"
            " ORDER BY f.beginn, lower(h.name)", (vid, datum)).fetchall()
    finally:
        con.close()


# --- Springer jetzt (Lastenheft 2.7, R-06) ----------------------------------

def springer_lage(vid: int, zeitpunkt: datetime | None = None, stunden: int = 3) -> dict:
    """Wer gerade als Springer da ist und nirgends eingeteilt – mit Name,
    Nummer und bis wann –, und wie viele in den nächsten Stunden dazukommen
    (R-06). Für Übersicht und Monitor."""
    zeitpunkt = zeitpunkt or jetzt_lokal()
    jetzt_ = zeitpunkt.strftime("%Y-%m-%d %H:%M")
    bis = (zeitpunkt + timedelta(hours=stunden)).strftime("%Y-%m-%d %H:%M")
    con = verbinden()
    try:
        frei = con.execute(
            "SELECT DISTINCT ON (h.id) h.id, h.name,"
            " COALESCE(NULLIF(h.telefon, ''), a.telefon, '') AS telefon, f.ende"
            " FROM verfuegbarkeit f JOIN helfer h ON h.id = f.helfer_id"
            " LEFT JOIN helfer a ON a.id = h.angemeldet_von"
            " WHERE f.veranstaltung_id = ? AND f.springer = 1"
            " AND f.beginn <= ? AND f.ende > ?"
            " AND NOT EXISTS (SELECT 1 FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
            "  WHERE e.helfer_id = h.id AND s.beginn <= ? AND s.ende > ?)"
            " ORDER BY h.id, f.ende DESC", (vid, jetzt_, jetzt_, jetzt_, jetzt_)).fetchall()
        bald = con.execute(
            "SELECT COUNT(DISTINCT helfer_id) FROM verfuegbarkeit"
            " WHERE veranstaltung_id = ? AND springer = 1 AND beginn > ? AND beginn <= ?",
            (vid, jetzt_, bis)).fetchone()[0]
    finally:
        con.close()
    return {"jetzt": sorted(frei, key=lambda z: z["name"].lower()), "bald": int(bald),
            "stunden": stunden}


# --- Datenschutz und Jugendschutz (Lastenheft 2.9) --------------------------

def _eltern_durch_anmelder(con: Verbindung, anmelder_id: int) -> None:
    """D-06: Wer jemanden mitanmeldet und dabei selbst als erziehungs-
    berechtigt eingetragen ist – gleiche Adresse –, bestätigt mit der
    eigenen Adresse auch das Einverständnis."""
    anmelder = con.execute("SELECT email FROM helfer WHERE id = ?", (anmelder_id,)).fetchone()
    if anmelder is None or not anmelder["email"]:
        return
    for z in con.execute(
            "UPDATE helfer SET eltern_bestaetigt_am = ? WHERE angemeldet_von = ?"
            " AND eltern_bestaetigt_am IS NULL AND eltern_email <> ''"
            " AND lower(eltern_email) = lower(?) RETURNING id",
            (jetzt(), anmelder_id, anmelder["email"])).fetchall():
        _protokollieren(con, z["id"], "selbst", "Einverständnis der Eltern bestätigt")


def eltern_bestaetigen(helfer_id: int) -> bool:
    """Die erziehungsberechtigte Person ist einverstanden (D-06)."""
    con = verbinden()
    try:
        with con:
            geaendert = con.execute(
                "UPDATE helfer SET eltern_bestaetigt_am = ? WHERE id = ?"
                " AND eltern_bestaetigt_am IS NULL AND eltern_email <> ''",
                (jetzt(), helfer_id)).rowcount > 0
            if geaendert:
                _protokollieren(con, helfer_id, "eltern", "Einverständnis der Eltern bestätigt")
        return geaendert
    finally:
        con.close()


def stamm_einwilligung(anmelder_id: int, helfer_id: int, ja: bool) -> bool:
    """D-03, D-05: in den Helferstamm – oder wieder heraus. Gibt zurück, ob
    sich etwas geändert hat."""
    con = verbinden()
    try:
        with con:
            if not _gehoert(con, anmelder_id, helfer_id):
                return False
            if ja:
                geaendert = con.execute(
                    "UPDATE helfer SET stamm_einwilligung_am = ? WHERE id = ?"
                    " AND stamm_einwilligung_am IS NULL", (jetzt(), helfer_id)).rowcount > 0
            else:
                geaendert = con.execute(
                    "UPDATE helfer SET stamm_einwilligung_am = NULL WHERE id = ?"
                    " AND stamm_einwilligung_am IS NOT NULL", (helfer_id,)).rowcount > 0
            if geaendert:
                _protokollieren(con, helfer_id, "selbst", "Einwilligung Helferstamm "
                                + ("erteilt" if ja else "widerrufen"))
        return geaendert
    finally:
        con.close()


def eltern_offen(stunden: int, nur_unerinnert: bool = False) -> list[dict]:
    """Minderjährige, deren Eltern nach `stunden` noch nicht eingewilligt
    haben – mit der Veranstaltung ihrer Anmeldung und der Person, die
    angemeldet hat."""
    grenze = (jetzt_lokal() - timedelta(hours=stunden)).strftime("%Y-%m-%d %H:%M:%S")
    con = verbinden()
    try:
        return [dict(z) for z in con.execute(
            "SELECT DISTINCT ON (h.id) h.*, t.veranstaltung_id, t.angemeldet_am,"
            " COALESCE(h.angemeldet_von, h.id) AS anmelder_id"
            " FROM helfer h JOIN teilnahme t ON t.helfer_id = h.id AND t.quelle = 'selbst'"
            " WHERE h.eltern_email <> '' AND h.eltern_bestaetigt_am IS NULL"
            " AND t.angemeldet_am <= ?"
            + (" AND h.eltern_erinnert_am IS NULL" if nur_unerinnert else "") +
            " ORDER BY h.id, t.angemeldet_am", (grenze,)).fetchall()]
    finally:
        con.close()


def eltern_erinnert(helfer_id: int) -> None:
    con = verbinden()
    try:
        with con:
            con.execute("UPDATE helfer SET eltern_erinnert_am = ? WHERE id = ?",
                        (jetzt(), helfer_id))
    finally:
        con.close()


def eltern_verfallen_lassen(helfer_id: int) -> list[int]:
    """Ohne Einverständnis gilt die Anmeldung nicht (D-06): die selbst
    gebuchten Plätze der minderjährigen Person werden frei, und wenn danach
    nichts mehr an ihr hängt, ist sie gelöscht. Gibt die frei gewordenen
    Schichten zurück."""
    con = verbinden()
    try:
        with con:
            frei = [int(z["schicht_id"]) for z in con.execute(
                "DELETE FROM einteilung WHERE helfer_id = ? AND quelle = 'selbst'"
                " RETURNING schicht_id", (helfer_id,)).fetchall()]
            con.execute("DELETE FROM verfuegbarkeit WHERE helfer_id = ?", (helfer_id,))
            con.execute("DELETE FROM warteliste WHERE helfer_id = ?", (helfer_id,))
            con.execute("DELETE FROM teilnahme WHERE helfer_id = ? AND quelle = 'selbst'",
                        (helfer_id,))
            weg = con.execute(
                "DELETE FROM helfer h WHERE h.id = ? AND h.tshirt_ausgegeben_am IS NULL"
                " AND NOT EXISTS (SELECT 1 FROM einteilung WHERE helfer_id = h.id)"
                " AND NOT EXISTS (SELECT 1 FROM teilnahme WHERE helfer_id = h.id)"
                " AND NOT EXISTS (SELECT 1 FROM ausleihe WHERE helfer_id = h.id)"
                " AND NOT EXISTS (SELECT 1 FROM helfer m WHERE m.angemeldet_von = h.id)",
                (helfer_id,)).rowcount
            if not weg:
                _protokollieren(con, helfer_id, "", "Ohne Einverständnis der Eltern – Plätze freigegeben")
        return sorted(set(frei))
    finally:
        con.close()


def jugendschutz(vid: int) -> list[dict]:
    """D-07 als Richtschnur, keine Sperre: wer unter 18 ist und an einem Tag
    mehr als 8 Stunden eingeteilt ist oder vor 6 oder nach 20 Uhr – für
    „Bitte prüfen“ in der Übersicht."""
    v = VERANSTALTUNGEN.laden(vid)
    con = verbinden()
    try:
        zeilen = con.execute(
            "SELECT h.id, h.name, h.volljaehrig, h.geburtsdatum, s.datum, s.beginn, s.ende"
            " FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
            " JOIN helfer h ON h.id = e.helfer_id"
            " WHERE s.veranstaltung_id = ? AND h.volljaehrig = 0"
            " ORDER BY h.id, s.beginn", (vid,)).fetchall()
    finally:
        con.close()
    je_tag: dict[tuple[int, str], dict] = {}
    for z in zeilen:
        alter = _alter(z, v["beginn"])
        if alter is None or alter >= 18:
            continue
        try:
            von, bis = datetime.fromisoformat(z["beginn"]), datetime.fromisoformat(z["ende"])
        except ValueError:
            continue
        eintrag = je_tag.setdefault((z["id"], z["datum"]), {
            "helfer_id": z["id"], "name": z["name"], "alter": alter, "datum": z["datum"],
            "stunden": 0.0, "randzeit": False})
        eintrag["stunden"] += (bis - von).total_seconds() / 3600
        if von.hour < 6 or bis.hour > 20 or (bis.hour == 20 and bis.minute) or bis.date() > von.date():
            eintrag["randzeit"] = True
    return [e for e in je_tag.values() if e["stunden"] > 8 or e["randzeit"]]
