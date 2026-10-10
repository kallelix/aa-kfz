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
                   "voraussetzungen", "intern", "vorlieben")

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
    werte = {"vorlieben": [], **werte}
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
    werte = {"vorlieben": [], **werte}
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
ANGEBOT_VORGABE = {"shirt": 0, "verpflegung": 1, "party": 0, "checkin": 0}
_ANGEBOT_FELDER = ("goodies", "shirt", "schnitte", "verpflegung", "party", "checkin")


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
                ", geaendert_am) VALUES (?, " + ", ".join("?" for _ in _ANGEBOT_FELDER) +
                ", ?)"
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
    """Bereiche, Schichten, Goodies, das Angebot und die Materialien der
    Ausgabe einer früheren Veranstaltung in diese kopieren. Die Schichten wandern um so viele Tage,
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
                " verpflegung, party, checkin, geaendert_am)"
                " SELECT ?, goodies, shirt, schnitte, verpflegung, party, checkin, ? FROM angebot"
                " WHERE veranstaltung_id = ? ON CONFLICT (veranstaltung_id) DO NOTHING",
                (vid, jetzt(), quelle_id))
            # Die Materialien der Ausgabe (V-09), soweit es sie hier noch
            # nicht gibt.
            material = sum(1 for m in con.execute(
                "SELECT * FROM material WHERE veranstaltung_id = ? ORDER BY reihenfolge, id",
                (quelle_id,)).fetchall() if _material_einfuegen(con, vid, dict(m)) is not None)
        return {"bereiche": len(neu), "schichten": len(schichten),
                "goodies": len(goodies), "material": material, "tage": tage}
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
            "SELECT " + _SCHICHT_SPALTEN + ", b.beschreibung, b.voraussetzungen,"
            " b.vorlieben" + _SCHICHT_VON +
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
               bemerkung: str = "", bemerkung_von: int | None = None,
               vorlieben: list[str] = ()) -> None:
    """Teilnahme, Einteilungen, Wartelisten und Springer-Zeiten – nach
    _pruefen. Die Vorlieben aus dem Assistenten (A-03) gelten für alle, die
    zusammen angemeldet werden; ohne bleiben die alten stehen."""
    for i, helfer_id in enumerate(ids):
        eigene_bemerkung = bemerkung if helfer_id == (bemerkung_von or ids[0]) else ""
        con.execute(
            "INSERT INTO teilnahme (veranstaltung_id, helfer_id, quelle, bemerkung,"
            " vorlieben, angemeldet_am) VALUES (?, ?, 'selbst', ?, CAST(? AS TEXT[]), ?)"
            " ON CONFLICT (veranstaltung_id, helfer_id) DO UPDATE SET bemerkung ="
            " CASE WHEN excluded.bemerkung <> '' THEN excluded.bemerkung"
            " ELSE teilnahme.bemerkung END, vorlieben ="
            " CASE WHEN cardinality(excluded.vorlieben) > 0 THEN excluded.vorlieben"
            " ELSE teilnahme.vorlieben END",
            (vid, helfer_id, eigene_bemerkung, list(vorlieben), jetzt()))
        for s in schichten:
            art = verteilung[s["id"]][i]
            if art == "warteliste":
                con.execute("INSERT INTO warteliste (schicht_id, helfer_id, angelegt_am)"
                            " VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                            (s["id"], helfer_id, jetzt()))
            else:
                # G-05: wer sich einträgt, solange die Schicht unter ihrem
                # Minimum ist, hat sie gerettet.
                retter = art == "platz" and con.execute(
                    "SELECT COUNT(*) FROM einteilung WHERE schicht_id = ? AND art = 'platz'",
                    (s["id"],)).fetchone()[0] < s["minimum"]
                con.execute(
                    "INSERT INTO einteilung (schicht_id, helfer_id, quelle, art,"
                    " eingeteilt_am, retter) VALUES (?, ?, 'selbst', ?, ?, ?)",
                    (s["id"], helfer_id, art, jetzt(), 1 if retter else 0))
        for _, von, bis in fenster:
            con.execute(
                "INSERT INTO verfuegbarkeit (veranstaltung_id, helfer_id, beginn,"
                " ende, springer, angelegt_am) VALUES (?, ?, ?, ?, 1, ?)",
                (vid, helfer_id, von, bis, jetzt()))


def anmelden(vid: int, personen: list[dict], schicht_ids: list[int],
             fenster: list[tuple[str, str, str]], bemerkung: str = "",
             warteliste=frozenset(), vorlieben: list[str] = ()) -> dict:
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
            _eintragen(con, vid, ids, schichten, verteilung, fenster, bemerkung,
                       vorlieben=vorlieben)
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


def interesse_faellig() -> list[Zeile]:
    """Vorgemerkte (V-02), deren Veranstaltung jetzt zur Anmeldung offen ist
    – Status *offen* und im Anmeldezeitraum (C-08)."""
    heute = jetzt_lokal().date()
    con = verbinden()
    try:
        return con.execute(
            "SELECT i.* FROM interesse i JOIN kern.veranstaltung v ON v.id = i.veranstaltung_id"
            " WHERE i.benachrichtigt_am IS NULL AND v.status = 'offen'"
            " AND (v.anmeldung_ab IS NULL OR v.anmeldung_ab <= ?)"
            " AND (v.anmeldung_bis IS NULL OR v.anmeldung_bis >= ?) ORDER BY i.id",
            (heute, heute)).fetchall()
    finally:
        con.close()


def interesse_benachrichtigen(interesse_id: int, mail: tuple) -> None:
    """Reiht die Mail ein und vergisst die Adresse – „Danach löschen wir die
    Adresse wieder“, steht auf der Seite. Beides oder keins."""
    con = verbinden()
    try:
        with con:
            if con.execute("DELETE FROM interesse WHERE id = ?", (interesse_id,)).rowcount:
                mail_einreihen(None, mail, con)
    finally:
        con.close()


# --- Den Helferstamm einladen (Lastenheft 3.3: C-08) ------------------------

# Wen Einladungen und Hilferufe erreichen: der Helferstamm (D-03), mit
# Adresse, nicht auf dem Weg hinaus, und nicht abbestellt (C-09).
_AUFRUFBAR = ("h.stamm_einwilligung_am IS NOT NULL AND h.email <> '' AND h.aktiv = 1"
              " AND h.loeschen_beantragt_am IS NULL AND h.aufrufe_abbestellt_am IS NULL")

def stamm_einzuladen(vid: int) -> list[Zeile]:
    """Wer aus dem Helferstamm (D-03) zu dieser Veranstaltung noch keine
    Einladung hat und nicht ohnehin schon dabei ist."""
    con = verbinden()
    try:
        return con.execute(
            "SELECT h.* FROM helfer h WHERE " + _AUFRUFBAR +
            " AND NOT EXISTS (SELECT 1 FROM teilnahme t WHERE t.helfer_id = h.id"
            "                 AND t.veranstaltung_id = ?)"
            " AND NOT EXISTS (SELECT 1 FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
            "                 WHERE e.helfer_id = h.id AND s.veranstaltung_id = ?)"
            " AND NOT EXISTS (SELECT 1 FROM einladung x WHERE x.helfer_id = h.id"
            "                 AND x.veranstaltung_id = ?)"
            " ORDER BY lower(h.name)", (vid, vid, vid)).fetchall()
    finally:
        con.close()


def eingeladen(vid: int) -> int:
    con = verbinden()
    try:
        return int(con.execute("SELECT COUNT(*) FROM einladung WHERE veranstaltung_id = ?",
                               (vid,)).fetchone()[0])
    finally:
        con.close()


def einladen(vid: int, einladungen: list[tuple[int, tuple]], wer: str) -> int:
    """Je Person die Einladung vermerken und die Mail einreihen – wer schon
    eine hat, bekommt keine zweite. Gibt zurück, wie viele es waren."""
    con = verbinden()
    try:
        with con:
            neu = 0
            for helfer_id, mail in einladungen:
                if con.execute("INSERT INTO einladung (veranstaltung_id, helfer_id, wer, am)"
                               " VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                               (vid, helfer_id, wer, jetzt())).rowcount:
                    mail_einreihen(helfer_id, mail, con)
                    neu += 1
            return neu
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
                    " AND NOT EXISTS (SELECT 1 FROM ausgabe WHERE helfer_id = h.id)",
                    (nummer,))
            if con.execute("SELECT 1 FROM helfer WHERE id = ?", (helfer_id,)).fetchone():
                _protokollieren(con, helfer_id, "", "Nicht bestätigt – Plätze freigegeben")
        return sorted(set(frei))
    finally:
        con.close()


def moegliche_dubletten(helfer_id: int | None = None) -> list[dict]:
    """Paare, die vielleicht derselbe Mensch sind (I-05): Name in irgendeiner
    Schreibweise gleich und dazu Adresse oder Nummer. Ohne die, von denen die
    Orga gesagt hat, es sind zwei (I-06). Mit `helfer_id` nur die Paare mit
    dieser Person."""
    con = verbinden()
    try:
        paare = con.execute(
            "SELECT a.id AS a_id, a.name AS a_name, a.email AS a_email,"
            " b.id AS b_id, b.name AS b_name, b.email AS b_email"
            " FROM helfer a JOIN helfer b ON a.id < b.id"
            " AND ((a.email <> '' AND lower(a.email) = lower(b.email))"
            "      OR (a.telefon <> '' AND a.telefon = b.telefon))"
            " WHERE NOT EXISTS (SELECT 1 FROM keine_dublette k"
            "                   WHERE k.a_id = a.id AND k.b_id = b.id)" +
            (" AND ? IN (a.id, b.id)" if helfer_id else "") +
            " ORDER BY a.id, b.id", (helfer_id,) if helfer_id else ()).fetchall()
    finally:
        con.close()
    return [dict(z) for z in paare if _gleicher_name(z["a_name"], z["b_name"])]


# --- Hilferuf (Lastenheft 3.4: C-03, C-04, C-09) ---------------------------

def aufrufe_setzen(helfer_id: int, ja: bool) -> bool:
    """C-09: Hilferufe und Einladungen bestellen oder abbestellen. True, wenn
    sich etwas geändert hat."""
    con = verbinden()
    try:
        with con:
            if ja:
                return con.execute("UPDATE helfer SET aufrufe_abbestellt_am = NULL WHERE id = ?"
                                   " AND aufrufe_abbestellt_am IS NOT NULL",
                                   (helfer_id,)).rowcount > 0
            if con.execute("UPDATE helfer SET aufrufe_abbestellt_am = ? WHERE id = ?"
                           " AND aufrufe_abbestellt_am IS NULL",
                           (jetzt(), helfer_id)).rowcount:
                _protokollieren(con, helfer_id, "selbst", "Hilferufe und Einladungen abbestellt")
                return True
            return False
    finally:
        con.close()


def hilferuf_kandidaten(vid: int) -> list[dict]:
    """Wer einen Hilferuf bekommen kann (C-03) – je Person, was für die
    Auswahl zählt: ihre Einteilungen und Wartelisten in dieser
    Veranstaltung, ihre Zeiten hier, ihre zuletzt genannten Vorlieben und
    was ihr nicht angeboten wird (K-06). Fünf Abfragen statt fünf je Person."""
    con = verbinden()
    try:
        personen = con.execute("SELECT h.* FROM helfer h WHERE " + _AUFRUFBAR +
                               " ORDER BY h.id").fetchall()
        kandidaten = {p["id"]: {"person": p, "belegt": [], "warteliste": set(), "fenster": [],
                                "vorlieben": [], "gesperrt": set()} for p in personen}

        def zu(zeile):
            return kandidaten.get(zeile["helfer_id"])

        for z in con.execute("SELECT e.helfer_id, s.id, s.beginn, s.ende FROM einteilung e"
                             " JOIN schicht s ON s.id = e.schicht_id"
                             " WHERE s.veranstaltung_id = ?", (vid,)).fetchall():
            if zu(z):
                zu(z)["belegt"].append((z["beginn"], z["ende"], z["id"]))
        for z in con.execute("SELECT w.helfer_id, w.schicht_id FROM warteliste w"
                             " JOIN schicht s ON s.id = w.schicht_id"
                             " WHERE s.veranstaltung_id = ?", (vid,)).fetchall():
            if zu(z):
                zu(z)["warteliste"].add(z["schicht_id"])
        for z in con.execute("SELECT helfer_id, beginn, ende FROM verfuegbarkeit"
                             " WHERE veranstaltung_id = ?", (vid,)).fetchall():
            if zu(z):
                zu(z)["fenster"].append((z["beginn"], z["ende"]))
        # Die Vorlieben dieser Veranstaltung, sonst die der letzten davor.
        for z in con.execute(
                "SELECT DISTINCT ON (t.helfer_id) t.helfer_id, t.vorlieben FROM teilnahme t"
                " JOIN kern.veranstaltung v ON v.id = t.veranstaltung_id"
                " WHERE cardinality(t.vorlieben) > 0"
                " ORDER BY t.helfer_id, (t.veranstaltung_id = ?) DESC, v.beginn DESC",
                (vid,)).fetchall():
            if zu(z):
                zu(z)["vorlieben"] = list(z["vorlieben"])
        for z in con.execute(
                "SELECT g.helfer_id, s.id FROM schicht s JOIN einsatzgrenze g"
                " ON g.art = 'nicht_anbieten'"
                " AND (g.schicht_id = s.id OR g.bereich_id = s.bereich_id)"
                " WHERE s.veranstaltung_id = ?", (vid,)).fetchall():
            if zu(z):
                zu(z)["gesperrt"].add(z["id"])
        return list(kandidaten.values())
    finally:
        con.close()


def letzte_hilferufe(vid: int) -> dict[int, str]:
    """Je Schicht, wann zuletzt per Mail gerufen wurde (C-04)."""
    con = verbinden()
    try:
        return {z["schicht_id"]: z["am"] for z in con.execute(
            "SELECT schicht_id, max(am) AS am FROM hilferuf WHERE veranstaltung_id = ?"
            " GROUP BY schicht_id", (vid,)).fetchall()}
    finally:
        con.close()


def hilferuf_senden(vid: int, mails: list[tuple[int, list[int], tuple]], wer: str,
                    seit: str) -> int | None:
    """Vermerkt den Hilferuf je Schicht und reiht die Mails ein (C-03, C-04).
    `mails`: je Person (helfer_id, ihre Schichten, Mail). Unter Sperre wird
    noch einmal geprüft, ob für eine der Schichten seit `seit` schon gerufen
    wurde – dann geht nichts raus (None), und die Seite rechnet neu."""
    zahl: dict[int, int] = {}
    for _, schicht_ids, _ in mails:
        for schicht_id in schicht_ids:
            zahl[schicht_id] = zahl.get(schicht_id, 0) + 1
    con = verbinden()
    try:
        with con:
            _sperren(con, list(zahl))
            if zahl and con.execute("SELECT 1 FROM hilferuf WHERE schicht_id = ANY(?)"
                                    " AND am >= ?", (list(zahl), seit)).fetchone():
                return None
            for schicht_id, anzahl in sorted(zahl.items()):
                con.execute("INSERT INTO hilferuf (veranstaltung_id, schicht_id, empfaenger,"
                            " wer, am) VALUES (?, ?, ?, ?, ?)",
                            (vid, schicht_id, anzahl, wer, jetzt()))
            for helfer_id, _, mail in mails:
                mail_einreihen(helfer_id, mail, con)
            return len(mails)
    finally:
        con.close()


def schicht_veranstaltung(schicht_id: int) -> int | None:
    """Zu welcher Veranstaltung eine Schicht gehört – für den kurzen Link."""
    con = verbinden()
    try:
        zeile = con.execute("SELECT veranstaltung_id FROM schicht WHERE id = ?",
                            (schicht_id,)).fetchone()
        return zeile["veranstaltung_id"] if zeile else None
    finally:
        con.close()


# --- Erinnerung und Danke (Lastenheft 3.5: C-02, G-07) ---------------------
#
# Eine Mail geht an jede Person mit eigener Adresse. Wer mitangemeldet ist
# und keine eigene hat, steht in der Mail dessen, der ihn angemeldet hat
# (A-08). Ein Angebot der Warteliste, das noch nicht angenommen ist, zählt
# nicht; ebenso wenig eine Anmeldung, deren Adresse nicht bestätigt ist.

_BETEILIGT = (
    "SELECT x.vid, x.empfaenger, min(x.beginn) AS erste FROM ("
    "  SELECT s.veranstaltung_id AS vid, s.beginn,"
    "    CASE WHEN h.email = '' AND h.angemeldet_von IS NOT NULL"
    "         THEN h.angemeldet_von ELSE h.id END AS empfaenger"
    "  FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
    "  JOIN helfer h ON h.id = e.helfer_id WHERE e.bestaetigen_bis IS NULL"
    "  UNION ALL"
    "  SELECT f.veranstaltung_id, f.beginn,"
    "    CASE WHEN h.email = '' AND h.angemeldet_von IS NOT NULL"
    "         THEN h.angemeldet_von ELSE h.id END"
    "  FROM verfuegbarkeit f JOIN helfer h ON h.id = f.helfer_id WHERE f.springer = 1"
    ") x JOIN helfer r ON r.id = x.empfaenger"
    " WHERE r.email <> '' AND r.aktiv = 1 AND r.loeschen_beantragt_am IS NULL"
    " AND NOT (r.email_bestaetigt_am IS NULL AND EXISTS (SELECT 1 FROM teilnahme t"
    "          WHERE t.helfer_id = r.id AND t.veranstaltung_id = x.vid AND t.quelle = 'selbst'))"
    " AND NOT EXISTS (SELECT 1 FROM erinnerung n WHERE n.veranstaltung_id = x.vid"
    "                 AND n.helfer_id = x.empfaenger AND n.art = ?)")


def erinnerung_faellig(von: str, bis: str) -> list[Zeile]:
    """C-02: wessen erste Schicht – oder Springer-Zeit – zwischen `von` und
    `bis` beginnt und wer noch nicht erinnert ist. Je (Veranstaltung,
    Empfänger) eine Zeile."""
    con = verbinden()
    try:
        return con.execute(_BETEILIGT + " GROUP BY x.vid, x.empfaenger"
                           " HAVING min(x.beginn) > ? AND min(x.beginn) <= ?"
                           " ORDER BY erste", ("vorher", von, bis)).fetchall()
    finally:
        con.close()


def danke_offen(vid: int, art: str = "danke") -> list[Zeile]:
    """G-07: wer bei dieser Veranstaltung dabei war und noch keinen Dank hat
    – oder, mit `art`, keine andere Mail dieser Art (die Einladung zur
    Party, G-09)."""
    con = verbinden()
    try:
        return con.execute(_BETEILIGT + " AND x.vid = ? GROUP BY x.vid, x.empfaenger"
                           " ORDER BY x.empfaenger", (art, vid)).fetchall()
    finally:
        con.close()


def gedankt(vid: int, art: str = "danke") -> int:
    con = verbinden()
    try:
        return int(con.execute("SELECT COUNT(*) FROM erinnerung WHERE veranstaltung_id = ?"
                               " AND art = ?", (vid, art)).fetchone()[0])
    finally:
        con.close()


# --- Helferparty (Lastenheft 4.4: G-09) -------------------------------------

def party_laden(vid: int) -> Zeile | None:
    con = verbinden()
    try:
        return con.execute("SELECT * FROM party WHERE veranstaltung_id = ?", (vid,)).fetchone()
    finally:
        con.close()


def party_setzen(vid: int, beginn: str, ort: str, hinweis: str) -> None:
    con = verbinden()
    try:
        with con:
            con.execute(
                "INSERT INTO party (veranstaltung_id, beginn, ort, hinweis, geaendert_am)"
                " VALUES (?, ?, ?, ?, ?) ON CONFLICT (veranstaltung_id) DO UPDATE SET"
                " beginn = excluded.beginn, ort = excluded.ort, hinweis = excluded.hinweis,"
                " geaendert_am = excluded.geaendert_am", (vid, beginn, ort, hinweis, jetzt()))
    finally:
        con.close()


def party_gruppe(vid: int, helfer_id: int) -> list[dict]:
    """Wer zu einer Antwort gehört: die Person und alle, die sie ohne eigene
    Adresse mitangemeldet hat – je mit ihrer bisherigen Antwort."""
    con = verbinden()
    try:
        leute = con.execute(
            "SELECT h.*, z.kommt, z.begleitung FROM helfer h"
            " LEFT JOIN party_zusage z ON z.helfer_id = h.id AND z.veranstaltung_id = ?"
            " WHERE h.id = ? OR (h.angemeldet_von = ? AND h.email = '')"
            " ORDER BY h.id = ? DESC, h.id", (vid, helfer_id, helfer_id, helfer_id)).fetchall()
        return [dict(z) for z in leute]
    finally:
        con.close()


def party_antworten(vid: int, helfer_id: int, kommen: set[int], begleitung: int) -> None:
    """Die Antwort für die Gruppe: wer kommt, wer nicht, und wie viele
    Begleitpersonen – die stehen bei der, die geantwortet hat."""
    gruppe = [p["id"] for p in party_gruppe(vid, helfer_id)]
    con = verbinden()
    try:
        with con:
            for nummer in gruppe:
                con.execute(
                    "INSERT INTO party_zusage (veranstaltung_id, helfer_id, kommt, begleitung, am)"
                    " VALUES (?, ?, ?, ?, ?) ON CONFLICT (veranstaltung_id, helfer_id) DO UPDATE"
                    " SET kommt = excluded.kommt, begleitung = excluded.begleitung, am = excluded.am",
                    (vid, nummer, 1 if nummer in kommen else 0,
                     min(max(0, begleitung), 20) if nummer == helfer_id else 0, jetzt()))
    finally:
        con.close()


def party_eingeladen(vid: int, helfer_id: int) -> bool:
    """Ob die Person zu dieser Party eingeladen ist – oder schon geantwortet
    hat, etwa als Mitangemeldete."""
    return _gibt_es(
        "SELECT 1 WHERE EXISTS (SELECT 1 FROM erinnerung WHERE veranstaltung_id = ?"
        " AND helfer_id = ? AND art = 'party') OR EXISTS (SELECT 1 FROM party_zusage"
        " WHERE veranstaltung_id = ? AND helfer_id = ?)", (vid, helfer_id, vid, helfer_id))


def party_stand(vid: int) -> dict:
    """Für die Planung: wer kommt, mit wie vielen, wer abgesagt hat."""
    con = verbinden()
    try:
        zeilen = [dict(z) for z in con.execute(
            "SELECT z.*, h.name FROM party_zusage z JOIN helfer h ON h.id = z.helfer_id"
            " WHERE z.veranstaltung_id = ? ORDER BY lower(h.name)", (vid,)).fetchall()]
    finally:
        con.close()
    kommen = [z for z in zeilen if z["kommt"]]
    begleitung = sum(z["begleitung"] for z in zeilen)
    return {"kommen": kommen, "absagen": [z for z in zeilen if not z["kommt"]],
            "begleitung": begleitung, "gesamt": len(kommen) + begleitung}


def party_heute(vid: int) -> list[Zeile]:
    """Wer zugesagt hat und am Party-Tag noch nicht erinnert ist – je
    Antwort einmal, an die Person mit Adresse."""
    con = verbinden()
    try:
        return con.execute(
            "SELECT DISTINCT h.id FROM party_zusage z JOIN helfer h ON h.id = z.helfer_id"
            " WHERE z.veranstaltung_id = ? AND z.kommt = 1 AND h.email <> ''"
            " AND NOT EXISTS (SELECT 1 FROM erinnerung n WHERE n.veranstaltung_id = ?"
            "                 AND n.helfer_id = h.id AND n.art = 'party_tag')",
            (vid, vid)).fetchall()
    finally:
        con.close()


def partys_heute(tag: str) -> list[Zeile]:
    con = verbinden()
    try:
        return con.execute("SELECT p.* FROM party p JOIN angebot a"
                           " ON a.veranstaltung_id = p.veranstaltung_id AND a.party = 1"
                           " WHERE left(p.beginn, 10) = ?", (tag,)).fetchall()
    finally:
        con.close()


def erinnerung_vermerken(vid: int, helfer_id: int, art: str, mail: tuple | None,
                         qr: str = "") -> bool:
    """Vermerkt die Mail und reiht sie ein – beides oder keins, und nur
    einmal. Ohne Mail (nichts zu sagen) nur der Vermerk."""
    con = verbinden()
    try:
        with con:
            neu = con.execute("INSERT INTO erinnerung (veranstaltung_id, helfer_id, art, am)"
                              " VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                              (vid, helfer_id, art, jetzt())).rowcount > 0
            if neu and mail is not None:
                mail_einreihen(helfer_id, mail, con, qr=qr)
            return neu
    finally:
        con.close()


# --- Dubletten zusammenführen (Lastenheft 3.2: I-06) ------------------------

# Was die bleibende Person von der anderen übernimmt, wenn es ihr fehlt.
_ERGAENZEN = ("vorname", "nachname", "email", "telefon", "veggie", "tshirt", "tshirt_roh",
              "volljaehrig", "geburtsdatum", "stamm_einwilligung_am", "aufrufe_abbestellt_am")
# Was nur zusammen übernommen wird – sonst passte das eine nicht zum anderen.
_ERGAENZEN_ZUSAMMEN = (("tshirt_ausgegeben_am", "tshirt_ausgegeben", "tshirt_kuerzel"),
                       ("eltern_email", "eltern_name", "eltern_bestaetigt_am"))


def _leer(wert) -> bool:
    return wert is None or wert == ""


def zusammenfuehren(behalten: int, weg: int, wer: str) -> list[dict] | None:
    """Zwei Personen zu einer (I-06): `weg` geht in `behalten` auf.

    Schichten, Warteliste, Springer-Zeiten, Teilnahmen, Einsatzgrenzen,
    Ausleihen, die Shirt-Unterschrift, Absagen, Mails und der Verlauf
    wandern mit; was danach doppelt wäre, bleibt einmal. Wen `weg`
    mitangemeldet hatte, hat jetzt `behalten` mitangemeldet. Fehlt
    `behalten` eine Angabe, kommt sie von `weg`.

    Stand dieselbe Person zweimal auf einer Schicht, wird ein Platz frei –
    der geht wie jeder andere an Reserve und Warteliste. Zurück kommen die
    Angebote dafür; None, wenn es eine der beiden nicht gibt.
    """
    if behalten == weg:
        return None
    beide = [behalten, weg]
    con = verbinden()
    try:
        with con:
            # Erst die Schichten, dann die Personen – in dieser Reihenfolge
            # sperrt auch die Anmeldung.
            _sperren(con, [z["schicht_id"] for z in con.execute(
                "SELECT schicht_id FROM einteilung WHERE helfer_id = ANY(?)"
                " UNION SELECT schicht_id FROM warteliste WHERE helfer_id = ANY(?)",
                (beide, beide)).fetchall()])
            zeilen = {z["id"]: z for z in con.execute(
                "SELECT * FROM helfer WHERE id = ANY(?) ORDER BY id FOR UPDATE",
                (beide,)).fetchall()}
            if len(zeilen) != 2:
                return None
            neu, alt = zeilen[behalten], zeilen[weg]

            # Schichten. Steht `behalten` schon drauf, bleibt die eine
            # Einteilung – als Platz, wenn eine der beiden einer war.
            frei: list[int] = []
            for e in con.execute("SELECT * FROM einteilung WHERE helfer_id = ? ORDER BY id",
                                 (weg,)).fetchall():
                da = con.execute("SELECT id, art FROM einteilung WHERE helfer_id = ?"
                                 " AND schicht_id = ? ORDER BY id", (behalten, e["schicht_id"])).fetchone()
                if da is None:
                    con.execute("UPDATE einteilung SET helfer_id = ? WHERE id = ?",
                                (behalten, e["id"]))
                    continue
                if da["art"] == "reserve" and e["art"] == "platz":
                    con.execute("UPDATE einteilung SET art = 'platz' WHERE id = ?", (da["id"],))
                elif e["art"] == "platz":
                    frei.append(e["schicht_id"])
                con.execute("DELETE FROM einteilung WHERE id = ?", (e["id"],))

            # Warteliste: einmal je Schicht, und nicht, wo man schon drin ist.
            con.execute("DELETE FROM warteliste w WHERE helfer_id = ? AND EXISTS"
                        " (SELECT 1 FROM warteliste x WHERE x.helfer_id = ?"
                        "  AND x.schicht_id = w.schicht_id)", (weg, behalten))
            con.execute("UPDATE warteliste SET helfer_id = ? WHERE helfer_id = ?", (behalten, weg))
            con.execute("DELETE FROM warteliste w WHERE helfer_id = ? AND EXISTS"
                        " (SELECT 1 FROM einteilung e WHERE e.helfer_id = ?"
                        "  AND e.schicht_id = w.schicht_id)", (behalten, behalten))

            # Teilnahme je Veranstaltung: eine, mit beiden Bemerkungen und
            # allen Vorlieben.
            for t in con.execute("SELECT * FROM teilnahme WHERE helfer_id = ?",
                                 (weg,)).fetchall():
                da = con.execute("SELECT * FROM teilnahme WHERE helfer_id = ?"
                                 " AND veranstaltung_id = ?",
                                 (behalten, t["veranstaltung_id"])).fetchone()
                if da is None:
                    con.execute("UPDATE teilnahme SET helfer_id = ? WHERE helfer_id = ?"
                                " AND veranstaltung_id = ?", (behalten, weg, t["veranstaltung_id"]))
                    continue
                con.execute(
                    "UPDATE teilnahme SET vorlieben = CAST(? AS TEXT[]), bemerkung = ?,"
                    " angemeldet_am = LEAST(angemeldet_am, ?)"
                    " WHERE helfer_id = ? AND veranstaltung_id = ?",
                    (list(dict.fromkeys([*da["vorlieben"], *t["vorlieben"]])),
                     "\n".join(x for x in dict.fromkeys([da["bemerkung"], t["bemerkung"]]) if x),
                     t["angemeldet_am"], behalten, t["veranstaltung_id"]))
                con.execute("DELETE FROM teilnahme WHERE helfer_id = ? AND veranstaltung_id = ?",
                            (weg, t["veranstaltung_id"]))

            # Springer-Zeiten und Einsatzgrenzen: dieselbe nur einmal.
            con.execute("DELETE FROM verfuegbarkeit v WHERE helfer_id = ? AND EXISTS"
                        " (SELECT 1 FROM verfuegbarkeit x WHERE x.helfer_id = ?"
                        "  AND x.veranstaltung_id = v.veranstaltung_id"
                        "  AND x.beginn = v.beginn AND x.ende = v.ende)", (weg, behalten))
            con.execute("DELETE FROM party_zusage g WHERE helfer_id = ? AND EXISTS"
                        " (SELECT 1 FROM party_zusage x WHERE x.helfer_id = ?"
                        "  AND x.veranstaltung_id = g.veranstaltung_id)", (weg, behalten))
            con.execute("DELETE FROM goodie_ausgabe g WHERE helfer_id = ? AND EXISTS"
                        " (SELECT 1 FROM goodie_ausgabe x WHERE x.helfer_id = ?"
                        "  AND x.goodie_id = g.goodie_id)", (weg, behalten))
            con.execute("DELETE FROM erinnerung g WHERE helfer_id = ? AND EXISTS"
                        " (SELECT 1 FROM erinnerung x WHERE x.helfer_id = ?"
                        "  AND x.veranstaltung_id = g.veranstaltung_id AND x.art = g.art)",
                        (weg, behalten))
            con.execute("DELETE FROM einladung g WHERE helfer_id = ? AND EXISTS"
                        " (SELECT 1 FROM einladung x WHERE x.helfer_id = ?"
                        "  AND x.veranstaltung_id = g.veranstaltung_id)", (weg, behalten))
            con.execute("DELETE FROM einsatzgrenze g WHERE helfer_id = ? AND EXISTS"
                        " (SELECT 1 FROM einsatzgrenze x WHERE x.helfer_id = ?"
                        "  AND x.bereich_id IS NOT DISTINCT FROM g.bereich_id"
                        "  AND x.schicht_id IS NOT DISTINCT FROM g.schicht_id)", (weg, behalten))
            for tabelle in ("verfuegbarkeit", "einsatzgrenze", "einladung", "erinnerung",
                            "goodie_ausgabe", "party_zusage", "ausgabe", "protokoll",
                            "absage", "mail_out"):
                con.execute("UPDATE " + tabelle + " SET helfer_id = ? WHERE helfer_id = ?",
                            (behalten, weg))
            # Die Unterschrift unter der Shirt-Ausgabe hängt an der Person.
            con.execute("UPDATE unterschrift SET vorgang_id = ? WHERE art = 'tshirt'"
                        " AND vorgang_id = ?", (behalten, weg))
            con.execute("UPDATE helfer SET angemeldet_von = ? WHERE angemeldet_von = ?"
                        " AND id <> ?", (behalten, weg, behalten))

            # Die Angaben: was `behalten` fehlt, kommt von `weg`.
            werte = {f: alt[f] for f in _ERGAENZEN if _leer(neu[f]) and not _leer(alt[f])}
            for gruppe in _ERGAENZEN_ZUSAMMEN:
                if _leer(neu[gruppe[0]]) and not _leer(alt[gruppe[0]]):
                    werte.update({f: alt[f] for f in gruppe})
            email = werte.get("email", neu["email"])
            if neu["email_bestaetigt_am"] is None and alt["email_bestaetigt_am"] \
                    and email.lower() == alt["email"].lower():
                werte["email_bestaetigt_am"] = alt["email_bestaetigt_am"]
            if alt["bemerkung"] and alt["bemerkung"] not in neu["bemerkung"]:
                werte["bemerkung"] = (neu["bemerkung"] + "\n" + alt["bemerkung"]).strip()
            if neu["angemeldet_von"] == weg:
                werte["angemeldet_von"] = None
            werte["aktiv"] = max(neu["aktiv"], alt["aktiv"])

            con.execute("DELETE FROM helfer WHERE id = ?", (weg,))
            # Mit einer neuen Adresse auch der Schlüssel, an dem Import und
            # Anmeldung die Person wiederfinden – wenn ihn niemand sonst hat.
            schluessel = normalisieren.schluessel(neu["name"], email)
            if schluessel != neu["schluessel"] and con.execute(
                    "SELECT 1 FROM helfer WHERE schluessel = ?", (schluessel,)).fetchone() is None:
                werte["schluessel"] = schluessel
            con.execute("UPDATE helfer SET " + ", ".join(f + " = ?" for f in werte) +
                        ", geaendert_am = ? WHERE id = ?", (*werte.values(), jetzt(), behalten))
            _protokollieren(con, behalten, wer,
                            f"Zusammengeführt mit {alt['name']} (Nr. {weg})")

            angebote: list[dict] = []
            for schicht_id in sorted(set(frei)):
                angebote += _nachruecken(con, schicht_id)
            return angebote
    finally:
        con.close()


def vergleich(helfer_id: int) -> dict | None:
    """Was an einer Person hängt – für die Entscheidung, wer bleibt (I-06)."""
    con = verbinden()
    try:
        person = con.execute("SELECT * FROM helfer WHERE id = ?", (helfer_id,)).fetchone()
        if person is None:
            return None

        def zahl(sql: str) -> int:
            return int(con.execute(sql, (helfer_id,)).fetchone()[0])
        return {"person": person,
                "schichten": zahl("SELECT COUNT(*) FROM einteilung WHERE helfer_id = ?"),
                "warteliste": zahl("SELECT COUNT(*) FROM warteliste WHERE helfer_id = ?"),
                "springer": zahl("SELECT COUNT(*) FROM verfuegbarkeit WHERE helfer_id = ?"),
                "ausleihen": zahl("SELECT COUNT(*) FROM ausgabe WHERE helfer_id = ?"),
                "mitgebracht": zahl("SELECT COUNT(*) FROM helfer WHERE angemeldet_von = ?")}
    finally:
        con.close()


def keine_dublette(a: int, b: int, wer: str) -> None:
    """Die Orga sagt: das sind zwei Menschen. Das Paar steht dann nicht mehr
    unter den möglichen Dubletten."""
    a, b = sorted((a, b))
    if a == b:
        return
    con = verbinden()
    try:
        with con:
            con.execute("INSERT INTO keine_dublette (a_id, b_id, wer, am) VALUES (?, ?, ?, ?)"
                        " ON CONFLICT DO NOTHING", (a, b, wer, jetzt()))
    finally:
        con.close()


# --- Selbstbedienung (Lastenheft 2.5: S-01 bis S-08, R-04) -----------------
#
# Alles aus Mein Helferplatz, ohne Frist: es sind Ehrenamtliche. Wer absagt,
# tut das Richtige – hier wird es leicht gemacht und landet sofort bei der
# richtigen Person. Jede Funktion prüft selbst, ob die Person zur Anmeldung
# gehört; die Mails schreibt main.py aus dem, was zurückkommt.

def _sperren(con: Verbindung, schicht_ids) -> None:
    """Schichten sperren – immer aufsteigend nach id. Wer mehrere Schichten
    in einer Transaktion anfasst, muss sie in derselben Reihenfolge sperren
    wie alle anderen, sonst können sich zwei gegenseitig blockieren."""
    con.execute("SELECT id FROM schicht WHERE id = ANY(?) ORDER BY id FOR UPDATE",
                (sorted(set(schicht_ids)),)).fetchall()


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
                    " WHERE e.bestaetigen_bis IS NOT NULL AND e.bestaetigen_bis < ?"
                    " ORDER BY e.schicht_id, e.id",
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
            # Beide Schichten gleich zu Beginn sperren, in fester Reihenfolge.
            # Sonst sperrt, wer von links nach rechts tauscht, erst rechts und
            # dann links – und wer gleichzeitig andersherum tauscht, umgekehrt:
            # beide warten aufeinander (Lastenheft 2.10 hat genau das gefunden).
            _sperren(con, [alt["schicht_id"], neu_id])
            alt = _einteilung(con, anmelder_id, einteilung_id)
            if alt is None:
                raise AnmeldeFehler(["Diese Schicht gehört nicht mehr zu dir."])
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
            # Alle Schichten vorab sperren, aufsteigend (siehe _sperren).
            _sperren(con, [z["schicht_id"] for z in con.execute(
                "SELECT e.schicht_id FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
                " WHERE e.helfer_id = ANY(?) AND s.veranstaltung_id = ?",
                (list(helfer_ids), vid)).fetchall()])
            for helfer_id in helfer_ids:
                if not _gehoert(con, anmelder_id, helfer_id):
                    continue
                for e in con.execute(
                        "SELECT e.*, s.veranstaltung_id, s.bereich_id, s.beginn, s.ende,"
                        " b.name AS bereich FROM einteilung e"
                        " JOIN schicht s ON s.id = e.schicht_id"
                        " JOIN bereich b ON b.id = s.bereich_id"
                        " WHERE e.helfer_id = ? AND s.veranstaltung_id = ? AND s.ende > ?"
                        " ORDER BY s.id",
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


def vorlieben(vid: int, helfer_id: int) -> list[str]:
    """Was der Person liegt – aus dem Assistenten (A-03)."""
    con = verbinden()
    try:
        zeile = con.execute("SELECT vorlieben FROM teilnahme WHERE veranstaltung_id = ?"
                            " AND helfer_id = ?", (vid, helfer_id)).fetchone()
        return list(zeile["vorlieben"]) if zeile else []
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
        " AND NOT EXISTS (SELECT 1 FROM ausgabe a WHERE a.helfer_id = h.id"
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
            # Alle Schichten vorab sperren, aufsteigend (siehe _sperren).
            _sperren(con, [z["schicht_id"] for z in con.execute(
                "SELECT schicht_id FROM einteilung WHERE helfer_id = ANY(?)",
                (list(helfer_ids),)).fetchall()])
            # Mitangemeldete zuerst – sonst stünden sie kurz ohne Ansprechpartner da.
            reihenfolge = sorted(helfer_ids, key=lambda h: h == anmelder_id)
            for helfer_id in reihenfolge:
                if not _gehoert(con, anmelder_id, helfer_id):
                    continue
                person = con.execute("SELECT * FROM helfer WHERE id = ?", (helfer_id,)).fetchone()
                for e in con.execute(
                        "SELECT e.* FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
                        " WHERE e.helfer_id = ? AND s.ende > ? ORDER BY s.id",
                        (helfer_id, marke(jetzt_lokal()))).fetchall():
                    ergebnis["abgaben"].append(_abgeben(con, e, "Daten gelöscht"))
                con.execute("DELETE FROM warteliste WHERE helfer_id = ?", (helfer_id,))
                offen = con.execute("SELECT 1 FROM ausgabe WHERE helfer_id = ?"
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

def mail_einreihen(helfer_id: int | None, mail: tuple, con: Verbindung | None = None,
                   qr: str = "") -> None:
    """mail = (typ, empfänger, betreff, text) aus mail.py. `qr`: was der
    QR-Code im Anhang enthalten soll – das Bild entsteht beim Verschicken."""
    typ, empfaenger, betreff, text = mail
    eigene = con is None
    con = con or verbinden()
    try:
        with (con if eigene else _offen()):
            con.execute(
                "INSERT INTO mail_out (helfer_id, typ, empfaenger, betreff, body, qr, angelegt_am)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (helfer_id, typ, empfaenger, betreff, text, qr, jetzt()))
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


# --- Materialausgabe (Lastenheft 3.8, V-09) ---------------------------------
#
# Je Veranstaltung eine Liste von Materialien. Ausgegeben wird in Vorgängen
# (ausgabe): eine Person – Helfer oder jemand anderes –, ein Zeitpunkt, eine
# Unterschrift, und je Material ein Posten mit Menge und, wo verlangt,
# Nummer oder Kennzeichen. Funkgerät, Headset, Ersatzakku und
# Fahrzeugschlüssel sind vier Materialien unter vielen; Migration 0014 hat
# sie aus den alten Tabellen ausleihe und schluessel übernommen.
#
# Ein Vorgang ist offen, solange zurueck_am leer ist – bis alles zurück ist,
# was zurückkommen muss. Ohne Rückgabe ist er mit der Übergabe erledigt.

ERFASSEN = {"": "nichts", "nummer": "Nummer", "kennzeichen": "Kennzeichen"}

# Höher als das ist keine Vorbelegung mehr, sondern ein Tippfehler.
MATERIAL_VORGABE_MAX = 20

# Was eine Veranstaltung mit einem Klick bekommt: das, was es bisher gab.
MATERIAL_STANDARD = (
    {"name": "Funkgerät", "rueckgabe": 1, "unterschrift": 1, "erfassen": "", "vorgabe": 1},
    {"name": "Headset", "rueckgabe": 1, "unterschrift": 1, "erfassen": "", "vorgabe": 0},
    {"name": "Ersatzakku", "rueckgabe": 1, "unterschrift": 1, "erfassen": "", "vorgabe": 0},
    {"name": "Fahrzeugschlüssel", "rueckgabe": 1, "unterschrift": 1, "erfassen": "kennzeichen",
     "vorgabe": 0},
)

_MATERIAL_FELDER = ("name", "rueckgabe", "unterschrift", "erfassen", "vorgabe")


def materialien(vid: int) -> list[Zeile]:
    """Was die Veranstaltung ausgibt, in der eingestellten Reihenfolge – je
    Material mit der Zahl der Vorgänge, in denen es schon herausging."""
    con = verbinden()
    try:
        return con.execute(
            "SELECT m.*, (SELECT COUNT(*) FROM ausgabe_posten p"
            "  WHERE p.material_id = m.id) AS ausgegeben"
            " FROM material m WHERE m.veranstaltung_id = ?"
            " ORDER BY m.reihenfolge, lower(m.name)", (vid,)).fetchall()
    finally:
        con.close()


def material_laden(material_id: int) -> Zeile | None:
    con = verbinden()
    try:
        return con.execute("SELECT * FROM material WHERE id = ?", (material_id,)).fetchone()
    finally:
        con.close()


def _material_einfuegen(con: Verbindung, vid: int, werte: dict) -> int | None:
    reihenfolge = con.execute("SELECT COALESCE(max(reihenfolge), 0) + 1 FROM material"
                              " WHERE veranstaltung_id = ?", (vid,)).fetchone()[0]
    zeile = con.execute(
        "INSERT INTO material (veranstaltung_id, " + ", ".join(_MATERIAL_FELDER) +
        ", reihenfolge, angelegt_am) VALUES (?, " + ", ".join("?" for _ in _MATERIAL_FELDER) +
        ", ?, ?) ON CONFLICT (veranstaltung_id, name) DO NOTHING RETURNING id",
        (vid, *(werte[f] for f in _MATERIAL_FELDER), reihenfolge, jetzt())).fetchone()
    return int(zeile[0]) if zeile else None


def material_anlegen(vid: int, werte: dict) -> int | None:
    """None, wenn es ein Material dieses Namens schon gibt."""
    con = verbinden()
    try:
        with con:
            return _material_einfuegen(con, vid, werte)
    finally:
        con.close()


def material_aendern(material_id: int, werte: dict) -> bool | None:
    """False, wenn es das Material nicht mehr gibt; None, wenn der Name schon
    vergeben ist."""
    con = verbinden()
    try:
        with con:
            return con.execute(
                "UPDATE material SET " + ", ".join(f + " = ?" for f in _MATERIAL_FELDER) +
                " WHERE id = ?", (*(werte[f] for f in _MATERIAL_FELDER), material_id)
            ).rowcount > 0
    except IntegrityError:
        return None
    finally:
        con.close()


def material_loeschen(material_id: int) -> str:
    """'weg', 'ausgegeben' (dann bleibt es – sonst verschwände, was jemand
    unterschrieben hat) oder 'unbekannt'."""
    con = verbinden()
    try:
        with con:
            if con.execute("SELECT 1 FROM ausgabe_posten WHERE material_id = ?",
                           (material_id,)).fetchone():
                return "ausgegeben"
            return "weg" if con.execute("DELETE FROM material WHERE id = ?",
                                        (material_id,)).rowcount else "unbekannt"
    finally:
        con.close()


def material_standard(vid: int) -> int:
    """Funkgerät, Headset, Ersatzakku und Fahrzeugschlüssel – was es davon
    noch nicht gibt. Gibt zurück, wie viele dazukamen."""
    con = verbinden()
    try:
        with con:
            return sum(1 for werte in MATERIAL_STANDARD
                       if _material_einfuegen(con, vid, werte) is not None)
    finally:
        con.close()


def _fahrzeug_sichern(con: Verbindung, kennzeichen: str, name: str = "",
                      bemerkung: str = "") -> tuple[int | None, bool]:
    norm = normalisieren.kennzeichen(kennzeichen)
    if not norm:
        return None, False
    vorhanden = con.execute("SELECT * FROM fahrzeug WHERE kennzeichen_norm = ?",
                            (norm,)).fetchone()
    if vorhanden is None:
        zeiger = con.execute(
            "INSERT INTO fahrzeug (kennzeichen, kennzeichen_norm, name, bemerkung, angelegt_am)"
            " VALUES (?, ?, ?, ?, ?) RETURNING id",
            (normalisieren.kennzeichen_anzeige(kennzeichen), norm,
             normalisieren.text(name), normalisieren.text(bemerkung), jetzt()))
        return int(zeiger.fetchone()[0]), True
    aenderungen, werte = [], []
    for spalte, wert in (("name", name), ("bemerkung", bemerkung)):
        sauber = normalisieren.text(wert)
        if sauber and not vorhanden[spalte]:
            aenderungen.append(spalte + " = ?")
            werte.append(sauber)
    if aenderungen:
        con.execute("UPDATE fahrzeug SET " + ", ".join(aenderungen) +
                    ", geaendert_am = ? WHERE id = ?", (*werte, jetzt(), vorhanden["id"]))
    return int(vorhanden["id"]), False


def fahrzeug_sichern(kennzeichen: str, name: str = "",
                     bemerkung: str = "") -> tuple[int | None, bool]:
    """Legt das Fahrzeug an oder ergänzt es. Gibt (id, neu) zurück.

    Der Stamm baut sich damit nebenbei auf: wer ein Kennzeichen eintippt, das
    es noch nicht gibt, legt es an, und beim nächsten Mal steht der Name schon
    da. Leere Felder werden ergänzt, gefüllte bleiben stehen – eine spätere
    Ausgabe ohne Namen soll den vorhandenen nicht löschen.
    """
    con = verbinden()
    try:
        with con:
            return _fahrzeug_sichern(con, kennzeichen, name, bemerkung)
    finally:
        con.close()


def ausgeben(vid: int, helfer_id: int | None, name: str, posten: list[dict],
             datum: str | None = None, bemerkung: str = "",
             kuerzel: str = "") -> tuple[int | None, bool]:
    """Ein Vorgang: an einen Helfer oder an jemanden, von dem nur der Name
    bekannt ist. `posten`: je Material {material_id, menge, nummer}. Bei
    Kennzeichen baut sich der Fahrzeugstamm mit auf.

    Gibt (id, neues_fahrzeug) zurück; (None, False), wenn nichts herausgeht
    oder niemand genannt ist."""
    posten = [p for p in posten if p["menge"] > 0]
    name = normalisieren.text(name)[:120]
    if not posten or (helfer_id is None and not name):
        return None, False
    con = verbinden()
    try:
        with con:
            material = {m["id"]: m for m in con.execute(
                "SELECT * FROM material WHERE veranstaltung_id = ? AND id = ANY(?)",
                (vid, [p["material_id"] for p in posten])).fetchall()}
            if any(p["material_id"] not in material for p in posten):
                return None, False
            if helfer_id is not None:
                person = con.execute("SELECT name FROM helfer WHERE id = ?",
                                     (helfer_id,)).fetchone()
                if person is None:
                    return None, False
                name = person["name"]
            rueckgabe = any(material[p["material_id"]]["rueckgabe"] for p in posten)
            ausgabe_id = int(con.execute(
                "INSERT INTO ausgabe (veranstaltung_id, helfer_id, name, datum, bemerkung,"
                " ausgegeben_am, ausgegeben_von, zurueck_am) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " RETURNING id",
                (vid, helfer_id, name, datum or None, normalisieren.text(bemerkung)[:200],
                 jetzt(), kuerzel, None if rueckgabe else jetzt())).fetchone()[0])
            fahrzeug_neu = False
            for p in posten:
                nummer = normalisieren.text(p.get("nummer"))[:60]
                fahrzeug_id = None
                if material[p["material_id"]]["erfassen"] == "kennzeichen" and nummer:
                    fahrzeug_id, neu = _fahrzeug_sichern(con, nummer, name)
                    fahrzeug_neu = fahrzeug_neu or neu
                    # Die Schreibweise aus dem Stamm: „ILX999“ getippt ist
                    # der Wagen, der dort als „IL-X 999“ steht.
                    nummer = con.execute("SELECT kennzeichen FROM fahrzeug WHERE id = ?",
                                         (fahrzeug_id,)).fetchone()[0]
                con.execute("INSERT INTO ausgabe_posten (ausgabe_id, material_id, menge, nummer,"
                            " fahrzeug_id) VALUES (?, ?, ?, ?, ?)",
                            (ausgabe_id, p["material_id"], p["menge"], nummer, fahrzeug_id))
            return ausgabe_id, fahrzeug_neu
    finally:
        con.close()


def _posten(con: Verbindung, ausgabe_ids) -> dict[int, list[dict]]:
    ergebnis: dict[int, list[dict]] = {}
    for z in con.execute(
            "SELECT p.*, m.name AS material, m.rueckgabe, m.erfassen, m.unterschrift"
            " FROM ausgabe_posten p JOIN material m ON m.id = p.material_id"
            " WHERE p.ausgabe_id = ANY(?) ORDER BY m.reihenfolge, lower(m.name), p.id",
            (list(ausgabe_ids),)).fetchall():
        ergebnis.setdefault(z["ausgabe_id"], []).append(dict(z))
    return ergebnis


def ausgabe_laden(ausgabe_id: int) -> dict | None:
    """Ein Vorgang samt Posten und dem Namen, unter dem die Person jetzt
    steht – für Wortlaut und Rücknahme."""
    con = verbinden()
    try:
        zeile = con.execute(
            "SELECT a.*, COALESCE(h.name, a.name) AS wer FROM ausgabe a"
            " LEFT JOIN helfer h ON h.id = a.helfer_id WHERE a.id = ?",
            (ausgabe_id,)).fetchone()
        if zeile is None:
            return None
        return {**zeile, "posten": _posten(con, [ausgabe_id]).get(ausgabe_id, [])}
    finally:
        con.close()


def ausgabe_zurueck(ausgabe_id: int, mengen: dict | None = None, kuerzel: str = "") -> bool:
    """Ohne `mengen` kommt alles zurück. Mit `mengen` – je Posten, was
    zurück ist – nur ein Teil: wer das Funkgerät bringt und den Ersatzakku
    behält, ist der Normalfall und kein Sonderfall."""
    con = verbinden()
    try:
        with con:
            zeile = con.execute("SELECT * FROM ausgabe WHERE id = ? FOR UPDATE",
                                (ausgabe_id,)).fetchone()
            if zeile is None:
                return False
            vollstaendig = True
            for p in _posten(con, [ausgabe_id]).get(ausgabe_id, []):
                if not p["rueckgabe"]:
                    continue
                if mengen is None:
                    neu = p["menge"]
                else:
                    try:
                        neu = int(mengen.get(p["id"], 0) or 0)
                    except (TypeError, ValueError):
                        neu = 0
                    neu = min(max(0, neu), p["menge"])
                vollstaendig = vollstaendig and neu >= p["menge"]
                con.execute("UPDATE ausgabe_posten SET zurueck = ? WHERE id = ?", (neu, p["id"]))
            con.execute("UPDATE ausgabe SET zurueck_am = ?, zurueck_von = ? WHERE id = ?",
                        (jetzt() if vollstaendig else None,
                         kuerzel if vollstaendig else zeile["zurueck_von"], ausgabe_id))
            # Wer seine Daten löschen wollte, als noch etwas ausgeliehen war,
            # ist jetzt dran (S-05) – samt der Unterschrift als Beleg.
            if vollstaendig:
                _nach_rueckgabe_loeschen(con)
        return True
    finally:
        con.close()


def ausgabe_loeschen(ausgabe_id: int) -> bool:
    con = verbinden()
    try:
        with con:
            return con.execute("DELETE FROM ausgabe WHERE id = ?", (ausgabe_id,)).rowcount > 0
    finally:
        con.close()


def ausgaben_liste(vid: int, nur_offen: bool = False) -> list[dict]:
    """Die Vorgänge, die offenen zuerst, je mit ihren Posten und dem, wonach
    die Liste sucht: Name, Bemerkung, Nummern und Kennzeichen."""
    con = verbinden()
    try:
        zeilen = [dict(z) for z in con.execute(
            "SELECT a.*, COALESCE(h.name, a.name) AS wer FROM ausgabe a"
            " LEFT JOIN helfer h ON h.id = a.helfer_id WHERE a.veranstaltung_id = ?" +
            (" AND a.zurueck_am IS NULL" if nur_offen else "") +
            " ORDER BY a.zurueck_am IS NOT NULL, a.ausgegeben_am DESC, a.id DESC",
            (vid,)).fetchall()]
        posten = _posten(con, [z["id"] for z in zeilen])
    finally:
        con.close()
    for z in zeilen:
        z["posten"] = posten.get(z["id"], [])
        z["rueckgabe"] = any(p["rueckgabe"] for p in z["posten"])
        nummern = " ".join(p["nummer"] for p in z["posten"] if p["nummer"])
        z["suche"] = normalisieren.suchtext(z["wer"], z["bemerkung"], nummern,
                                            normalisieren.kennzeichen(nummern) or "")
    return zeilen


def ausgabe_zaehler(vid: int) -> list[dict]:
    """Je Material, was insgesamt herausging und was davon noch draußen ist."""
    con = verbinden()
    try:
        return [dict(z) for z in con.execute(
            "SELECT m.id, m.name, m.rueckgabe,"
            " COALESCE(SUM(p.menge), 0) AS raus,"
            " COALESCE(SUM(CASE WHEN m.rueckgabe = 1 THEN p.menge - p.zurueck END), 0) AS offen"
            " FROM material m LEFT JOIN ausgabe_posten p ON p.material_id = m.id"
            " WHERE m.veranstaltung_id = ? GROUP BY m.id"
            " ORDER BY m.reihenfolge, lower(m.name)", (vid,)).fetchall()]
    finally:
        con.close()


def ausgabe_umbenennen(ausgabe_id: int, name: str) -> bool:
    """Der am Tablet korrigierte Name: bei Helfern im Bestand, sonst am
    Vorgang – und im Fahrzeugstamm, falls dort noch keiner steht."""
    sauber = normalisieren.text(name)
    if not sauber:
        return False
    zeile = ausgabe_laden(ausgabe_id)
    if zeile is None:
        return False
    if zeile["helfer_id"]:
        return helfer_umbenennen(zeile["helfer_id"], sauber)
    con = verbinden()
    try:
        with con:
            con.execute("UPDATE ausgabe SET name = ? WHERE id = ?", (sauber, ausgabe_id))
            con.execute("UPDATE fahrzeug SET name = ?, geaendert_am = ? WHERE TRIM(name) = ''"
                        " AND id IN (SELECT fahrzeug_id FROM ausgabe_posten WHERE ausgabe_id = ?)",
                        (sauber, jetzt(), ausgabe_id))
        return True
    finally:
        con.close()


def fahrzeuge() -> list[Zeile]:
    con = verbinden()
    try:
        return con.execute(
            "SELECT f.*,"
            " (SELECT COUNT(*) FROM ausgabe_posten p WHERE p.fahrzeug_id = f.id"
            "  AND p.zurueck < p.menge) AS draussen,"
            " (SELECT COUNT(*) FROM ausgabe_posten p WHERE p.fahrzeug_id = f.id) AS ausgaben"
            " FROM fahrzeug f ORDER BY lower(f.kennzeichen)").fetchall()
    finally:
        con.close()


def fahrzeug_loeschen(fahrzeug_id: int) -> str:
    """Nimmt ein Fahrzeug aus dem Stamm. Gibt zurück, was daraus wurde.

    Nur, solange kein Vorgang daran hängt – sonst risse das Löschen die
    Ausgabehistorie des Wagens mit, samt Unterschriften. Zu löschen gibt es
    hier vor allem Vertipper, und an denen hängt in aller Regel nichts."""
    con = verbinden()
    try:
        with con:
            zeile = con.execute(
                "SELECT (SELECT COUNT(*) FROM ausgabe_posten p WHERE p.fahrzeug_id = f.id)"
                " AS vorgaenge FROM fahrzeug f WHERE f.id = ?", (fahrzeug_id,)).fetchone()
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


def namen_vorschlaege(vid: int) -> list[str]:
    """Namen für „jemand anderes“: wer bei dieser Veranstaltung schon ohne
    Helfereintrag etwas bekam, und die Halter aus dem Fahrzeugstamm."""
    con = verbinden()
    try:
        return [z["name"] for z in con.execute(
            "SELECT DISTINCT name FROM ("
            " SELECT name FROM ausgabe WHERE veranstaltung_id = ? AND helfer_id IS NULL"
            " UNION SELECT name FROM fahrzeug) x WHERE name <> '' ORDER BY name", (vid,))]
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


# --- Check-in zentral bei der Orga (Lastenheft 4.1: T-01 bis T-03) ---------
#
# Eingecheckt wird je Einteilung, und zwar alles vom selben Tag auf einmal:
# wer morgens am Tisch steht, ist für die Schicht am Nachmittag auch da.
# Ein Angebot der Warteliste, das noch nicht angenommen ist, zählt nicht.

# T-02: so lange vor Beginn ist jemand „noch nicht da“.
NOCH_NICHT_DA_MINUTEN = 15


def _heute(zeitpunkt: datetime | None = None) -> tuple[str, str]:
    zeitpunkt = zeitpunkt or jetzt_lokal()
    return zeitpunkt.strftime("%Y-%m-%d"), marke(zeitpunkt)


def einchecken(vid: int, helfer_id: int, wer: str) -> int:
    """Checkt die Person für heute ein: alle Schichten, die heute beginnen
    oder gerade laufen, und ihre Springer-Zeiten von heute. Gibt zurück, wie
    viele Schichten es waren."""
    tag, jetzt_ = _heute()
    con = verbinden()
    try:
        with con:
            schichten = con.execute(
                "UPDATE einteilung e SET eingecheckt_am = ?, eingecheckt_von = ?"
                " FROM schicht s WHERE s.id = e.schicht_id AND e.helfer_id = ?"
                " AND s.veranstaltung_id = ? AND e.eingecheckt_am IS NULL"
                " AND e.bestaetigen_bis IS NULL"
                " AND (s.datum = ? OR (s.beginn <= ? AND s.ende > ?))",
                (jetzt(), wer, helfer_id, vid, tag, jetzt_, jetzt_)).rowcount
            fenster = con.execute(
                "UPDATE verfuegbarkeit SET eingecheckt_am = ? WHERE helfer_id = ?"
                " AND veranstaltung_id = ? AND eingecheckt_am IS NULL"
                " AND (left(beginn, 10) = ? OR (beginn <= ? AND ende > ?))",
                (jetzt(), helfer_id, vid, tag, jetzt_, jetzt_)).rowcount
            if schichten or fenster:
                _protokollieren(con, helfer_id, wer, "Eingecheckt", vid)
            return schichten
    finally:
        con.close()


def auschecken(vid: int, helfer_id: int, wer: str) -> bool:
    """Nimmt den Check-in von heute zurück – für den Fall, dass die falsche
    Person erwischt wurde."""
    tag, jetzt_ = _heute()
    con = verbinden()
    try:
        with con:
            weg = con.execute(
                "UPDATE einteilung e SET eingecheckt_am = NULL, eingecheckt_von = ''"
                " FROM schicht s WHERE s.id = e.schicht_id AND e.helfer_id = ?"
                " AND s.veranstaltung_id = ? AND e.eingecheckt_am IS NOT NULL"
                " AND (s.datum = ? OR (s.beginn <= ? AND s.ende > ?))",
                (helfer_id, vid, tag, jetzt_, jetzt_)).rowcount
            weg += con.execute(
                "UPDATE verfuegbarkeit SET eingecheckt_am = NULL WHERE helfer_id = ?"
                " AND veranstaltung_id = ? AND eingecheckt_am IS NOT NULL"
                " AND (left(beginn, 10) = ? OR (beginn <= ? AND ende > ?))",
                (helfer_id, vid, tag, jetzt_, jetzt_)).rowcount
            if weg:
                _protokollieren(con, helfer_id, wer, "Check-in zurückgenommen", vid)
            return weg > 0
    finally:
        con.close()


_ERWARTET = (
    "SELECT e.id AS einteilung_id, e.art, e.eingecheckt_am, s.id AS schicht_id,"
    " s.beginn, s.ende, s.datum, s.bereich_id, b.name AS bereich, h.id, h.name,"
    " COALESCE(NULLIF(h.telefon, ''), a.telefon, '') AS telefon"
    " FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
    " JOIN bereich b ON b.id = s.bereich_id JOIN helfer h ON h.id = e.helfer_id"
    " LEFT JOIN helfer a ON a.id = h.angemeldet_von"
    " WHERE s.veranstaltung_id = ? AND e.bestaetigen_bis IS NULL")


def noch_nicht_da(vid: int, leitung: int | None = None,
                  zeitpunkt: datetime | None = None) -> list[Zeile]:
    """T-02: wer in 15 Minuten anfängt oder schon angefangen hat und keinen
    Haken hat – früh genug, um anzurufen oder einen Springer zu schicken.
    Mit `leitung` nur die Bereiche dieses Kontos."""
    zeitpunkt = zeitpunkt or jetzt_lokal()
    jetzt_ = marke(zeitpunkt)
    gleich = marke(zeitpunkt + timedelta(minutes=NOCH_NICHT_DA_MINUTEN))
    con = verbinden()
    try:
        return con.execute(
            _ERWARTET + " AND e.eingecheckt_am IS NULL AND s.beginn <= ? AND s.ende > ?" +
            (" AND " + _GELEITET if leitung else "") +
            " ORDER BY s.beginn, lower(b.name), lower(h.name)",
            (vid, gleich, jetzt_, *((leitung,) if leitung else ()))).fetchall()
    finally:
        con.close()


def gleich_dran(vid: int, stunden: int = 2, zeitpunkt: datetime | None = None) -> list[Zeile]:
    """Wer in den nächsten Stunden anfängt und noch nicht da ist – damit am
    Tisch keiner gesucht werden muss."""
    zeitpunkt = zeitpunkt or jetzt_lokal()
    von = marke(zeitpunkt + timedelta(minutes=NOCH_NICHT_DA_MINUTEN))
    bis = marke(zeitpunkt + timedelta(hours=stunden))
    con = verbinden()
    try:
        return con.execute(
            _ERWARTET + " AND e.eingecheckt_am IS NULL AND s.beginn > ? AND s.beginn <= ?"
            " ORDER BY s.beginn, lower(h.name)", (vid, von, bis)).fetchall()
    finally:
        con.close()


def checkin_zaehler(vid: int) -> dict:
    """Heute: wie viele Leute erwartet werden und wie viele schon da sind."""
    tag, _ = _heute()
    con = verbinden()
    try:
        zeile = con.execute(
            "SELECT COUNT(DISTINCT e.helfer_id) AS erwartet,"
            " COUNT(DISTINCT e.helfer_id) FILTER (WHERE e.eingecheckt_am IS NOT NULL) AS da"
            " FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
            " WHERE s.veranstaltung_id = ? AND s.datum = ? AND e.bestaetigen_bis IS NULL",
            (vid, tag)).fetchone()
        return {"erwartet": zeile["erwartet"], "da": zeile["da"]}
    finally:
        con.close()


def checkin_gruppe(vid: int, helfer_id: int) -> list[dict]:
    """Die Person und alle, die mit ihr angemeldet sind (A-08) – eine
    Familie kommt zusammen an den Tisch. Je Person ihre Schichten von heute
    und was gerade läuft, ihre Springer-Zeiten von heute und ihre offenen
    Ausgaben."""
    tag, jetzt_ = _heute()
    con = verbinden()
    try:
        person = con.execute("SELECT * FROM helfer WHERE id = ?", (helfer_id,)).fetchone()
        if person is None:
            return []
        kopf = person["angemeldet_von"] or person["id"]
        leute = con.execute(
            "SELECT * FROM helfer WHERE id = ? OR angemeldet_von = ?"
            " ORDER BY id = ? DESC, id", (kopf, kopf, helfer_id)).fetchall()
        ergebnis = []
        for p in leute:
            schichten = con.execute(
                "SELECT e.id AS einteilung_id, e.art, e.eingecheckt_am, e.bestaetigen_bis,"
                " s.*, b.name AS bereich, b.treffpunkt"
                " FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
                " JOIN bereich b ON b.id = s.bereich_id"
                " WHERE e.helfer_id = ? AND s.veranstaltung_id = ?"
                " AND (s.datum = ? OR (s.beginn <= ? AND s.ende > ?))"
                " ORDER BY s.beginn", (p["id"], vid, tag, jetzt_, jetzt_)).fetchall()
            fenster = con.execute(
                "SELECT * FROM verfuegbarkeit WHERE helfer_id = ? AND veranstaltung_id = ?"
                " AND springer = 1 AND (left(beginn, 10) = ? OR (beginn <= ? AND ende > ?))"
                " ORDER BY beginn", (p["id"], vid, tag, jetzt_, jetzt_)).fetchall()
            alle = con.execute(
                "SELECT COUNT(*) AS anzahl, COUNT(e.eingecheckt_am) AS angetreten,"
                " COALESCE(SUM(EXTRACT(EPOCH FROM (s.ende::timestamp - s.beginn::timestamp))"
                "  / 3600) FILTER (WHERE e.eingecheckt_am IS NOT NULL), 0) AS stunden"
                " FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
                " WHERE e.helfer_id = ? AND s.veranstaltung_id = ? AND e.bestaetigen_bis IS NULL",
                (p["id"], vid)).fetchone()
            offen = con.execute("SELECT COUNT(*) FROM ausgabe WHERE helfer_id = ?"
                                " AND veranstaltung_id = ? AND zurueck_am IS NULL",
                                (p["id"], vid)).fetchone()[0]
            ergebnis.append({
                "person": p, "schichten": schichten, "fenster": fenster,
                "da": any(s["eingecheckt_am"] for s in schichten)
                or any(f["eingecheckt_am"] for f in fenster),
                "erwartet": bool([s for s in schichten if not s["bestaetigen_bis"]] or fenster),
                "schichten_gesamt": int(alle["anzahl"]), "angetreten": int(alle["angetreten"]),
                "stunden": float(alle["stunden"]), "ausgaben_offen": int(offen)})
        return ergebnis
    finally:
        con.close()


def goodies_fuer(vid: int, helfer_id: int, schichten: int, stunden: float,
                 alter: int | None) -> dict:
    """G-02, T-03: was einer Person nach ihren angetretenen Schichten oder
    Stunden zusteht – bei einer Altersgrenze, unter der sie liegt oder bei
    der wir ihr Alter nicht kennen, die Alternative –, ob es schon
    ausgegeben ist, und was als Nächstes kommt. Nur, wenn die Veranstaltung
    Goodies ausgibt (V-07)."""
    ergebnis: dict = {"verdient": [], "naechstes": ""}
    if not angebot(vid)["goodies"]:
        return ergebnis
    con = verbinden()
    try:
        schon = {z["goodie_id"]: z for z in con.execute(
            "SELECT * FROM goodie_ausgabe WHERE helfer_id = ?", (helfer_id,)).fetchall()}
    finally:
        con.close()
    for g in goodies(vid):
        if g["ab_schichten"]:
            fehlt, einheit = g["ab_schichten"] - schichten, ("Schicht", "Schichten")
        else:
            fehlt, einheit = g["ab_stunden"] - stunden, ("Stunde", "Stunden")
        if fehlt > 0:
            if not ergebnis["naechstes"]:
                zahl = f"{fehlt:g}"
                ergebnis["naechstes"] = (f"noch {zahl} {einheit[0] if zahl == '1' else einheit[1]}"
                                         f" bis {g['name']}")
            continue
        # Unbekanntes Alter: der Tisch fragt nach dem Ausweis, sonst gibt es
        # die Alternative.
        unbekannt = bool(g["mindestalter"]) and alter is None
        alternative = bool(g["mindestalter"]) and (unbekannt or alter < g["mindestalter"])
        if alternative and not unbekannt and not g["alternative"]:
            continue
        ergebnis["verdient"].append({
            "id": g["id"], "name": g["name"], "alternative": alternative,
            "unbekannt": unbekannt,
            "was": g["alternative"] if alternative and g["alternative"] else g["name"],
            "mindestalter": g["mindestalter"], "ausgabe": schon.get(g["id"])})
    return ergebnis


# --- Stempelkarte und Abzeichen (Lastenheft 4.3: G-01, G-02, G-05) -------

# So viele Kreise höchstens – sonst bricht die Reihe auf dem Handy dreimal um.
STEMPEL_HOECHSTENS = 12

ABZEICHEN = {
    "retter": ("Schicht-Retter", "eingetragen, als die Schicht unter ihrem Minimum war"),
    "frueh": ("Frühaufsteher", "eine Schicht vor 7 Uhr"),
    "nacht": ("Nachtwache", "eine Schicht über Mitternacht oder ab 22 Uhr"),
    "stamm": ("Stammhelfer", "das dritte Jahr in Folge dabei"),
}


def _kurz(text: str) -> str:
    """Was in einen Kreis passt: das erste Wort."""
    return (text or "").split(" ")[0]


def stempelkarte(vid: int, helfer_id: int) -> dict:
    """G-01, G-02: je eingetragener Schicht ein Stempel, und in den Kreisen,
    was es auf welcher Stufe gibt – das Shirt ab der ersten, die Goodies nach
    ihrer Schwelle, unter der Altersgrenze die Alternative. Goodies nach
    Stunden stehen darunter. Gibt die Veranstaltung keine Goodies aus (V-07),
    bleibt der Dank."""
    con = verbinden()
    try:
        zeile = con.execute(
            "SELECT COUNT(*) AS schichten,"
            " COALESCE(SUM(EXTRACT(EPOCH FROM (s.ende::timestamp - s.beginn::timestamp))"
            "  / 3600), 0) AS stunden"
            " FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
            " WHERE e.helfer_id = ? AND s.veranstaltung_id = ? AND e.bestaetigen_bis IS NULL",
            (helfer_id, vid)).fetchone()
        person = con.execute("SELECT * FROM helfer WHERE id = ?", (helfer_id,)).fetchone()
    finally:
        con.close()
    schichten, stunden = int(zeile["schichten"]), float(zeile["stunden"])
    v = VERANSTALTUNGEN.laden(vid)
    alter = _alter(person, v["beginn"]) if person is not None and v is not None else None
    angebot_ = angebot(vid)
    stufen: dict[int, list[str]] = {}
    nach_stunden = []
    if angebot_["goodies"]:
        if angebot_["shirt"]:
            stufen.setdefault(1, []).append("Helfershirt")
        for g in goodies(vid):
            text = g["name"]
            if g["mindestalter"] and alter is not None and alter < g["mindestalter"]:
                if not g["alternative"]:
                    continue
                text = g["alternative"]
            if g["ab_schichten"]:
                stufen.setdefault(g["ab_schichten"], []).append(text)
            else:
                nach_stunden.append({"text": text, "ab": g["ab_stunden"],
                                     "erreicht": stunden >= g["ab_stunden"]})
    felder = min(max([schichten, 1, *stufen]), STEMPEL_HOECHSTENS)
    naechste = next(((ab, stufen[ab]) for ab in sorted(stufen) if ab > schichten), None)
    satz = ""
    if stufen:
        if naechste:
            fehlt = naechste[0] - schichten
            satz = (f"Noch {fehlt} {'Schicht' if fehlt == 1 else 'Schichten'} bis "
                    + " und ".join(naechste[1]) + ".")
        else:
            satz = "Alle Goodies sind deine – danke, dass du so viel mithilfst!"
    return {"schichten": schichten, "stunden": round(stunden, 1), "goodies": bool(stufen or nach_stunden),
            "felder": [{"voll": i <= schichten,
                        "kurz": " + ".join(_kurz(t) for t in stufen.get(i, []))}
                       for i in range(1, felder + 1)],
            "satz": satz, "nach_stunden": nach_stunden}


def abzeichen(vid: int, helfer_id: int) -> list[dict]:
    """G-05: Abzeichen, die etwas Echtes würdigen – aus den Schichten dieser
    Veranstaltung und, beim Stammhelfer, aus den Jahren davor."""
    con = verbinden()
    try:
        hier = con.execute(
            "SELECT bool_or(e.retter = 1) AS retter,"
            " bool_or(substr(s.beginn, 12, 5) < '07:00') AS frueh,"
            " bool_or(left(s.ende, 10) > left(s.beginn, 10) AND substr(s.ende, 12, 5) > '00:00'"
            "         OR substr(s.beginn, 12, 5) >= '22:00') AS nacht"
            " FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
            " WHERE e.helfer_id = ? AND s.veranstaltung_id = ? AND e.bestaetigen_bis IS NULL",
            (helfer_id, vid)).fetchone()
        jahre = {int(z["jahr"]) for z in con.execute(
            "SELECT DISTINCT extract(year FROM v.beginn) AS jahr FROM einteilung e"
            " JOIN schicht s ON s.id = e.schicht_id"
            " JOIN kern.veranstaltung v ON v.id = s.veranstaltung_id WHERE e.helfer_id = ?",
            (helfer_id,)).fetchall()}
        jahr = con.execute("SELECT extract(year FROM beginn) FROM kern.veranstaltung WHERE id = ?",
                           (vid,)).fetchone()
    finally:
        con.close()
    erreicht = {k for k in ("retter", "frueh", "nacht") if hier[k]}
    if jahr is not None and {int(jahr[0]), int(jahr[0]) - 1, int(jahr[0]) - 2} <= jahre:
        erreicht.add("stamm")
    return [{"schluessel": k, "name": ABZEICHEN[k][0], "text": ABZEICHEN[k][1]}
            for k in ABZEICHEN if k in erreicht]


def goodie_ausgeben(goodie_id: int, helfer_id: int, was: str, wer: str) -> bool:
    """Abhaken (T-03) – einmal je Goodie und Person."""
    con = verbinden()
    try:
        with con:
            return con.execute(
                "INSERT INTO goodie_ausgabe (goodie_id, helfer_id, was, ausgegeben_am,"
                " ausgegeben_von) VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                (goodie_id, helfer_id, was, jetzt(), wer)).rowcount > 0
    finally:
        con.close()


def goodie_zuruecknehmen(goodie_id: int, helfer_id: int) -> bool:
    con = verbinden()
    try:
        with con:
            return con.execute("DELETE FROM goodie_ausgabe WHERE goodie_id = ? AND helfer_id = ?",
                               (goodie_id, helfer_id)).rowcount > 0
    finally:
        con.close()


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
                " AND NOT EXISTS (SELECT 1 FROM ausgabe WHERE helfer_id = h.id)"
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
