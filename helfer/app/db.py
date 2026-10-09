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

from datetime import datetime, timedelta
from pathlib import Path

from kern import veranstaltungen as va
from kern.db import Datenbank, IntegrityError, Verbindung, Zeile

from . import config, normalisieren

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
            "SELECT e.id AS einteilung_id, e.quelle, s.*"
            " FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
            " WHERE e.helfer_id = ? AND s.veranstaltung_id = ? ORDER BY s.beginn",
            (helfer_id, vid)).fetchall()
    finally:
        con.close()


# --- Schichten -------------------------------------------------------------

def schicht_sichern(con: Verbindung, vid: int, liste: str, beginn: str,
                    ende: str, datum: str,
                    bedarf: int | None = None) -> tuple[int, bool]:
    """Legt eine Schicht an oder aktualisiert sie. Gibt (id, neu) zurück.

    `bedarf` wird GESETZT, nicht addiert. Der Import rechnet den Bedarf aus
    beiden CSV-Dateien neu aus; würde hier addiert, verdoppelte ein zweiter
    Lauf derselben Dateien den Bedarf. None lässt den Wert stehen.
    """
    vorhanden = con.execute(
        "SELECT id FROM schicht WHERE veranstaltung_id = ? AND liste = ?"
        " AND beginn = ? AND ende = ?", (vid, liste, beginn, ende)).fetchone()
    if vorhanden is None:
        zeiger = con.execute(
            "INSERT INTO schicht (veranstaltung_id, liste, beginn, ende, datum,"
            " bedarf, angelegt_am) VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (vid, liste, beginn, ende, datum, bedarf or 0, jetzt()))
        return int(zeiger.fetchone()[0]), True
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
    " GREATEST(0, s.bedarf - (SELECT COUNT(*) FROM einteilung e"
    "                         WHERE e.schicht_id = s.id)) AS fehlt"
)

# Woraus `suche` für eine Schicht entsteht, siehe _mit_suche().
_SCHICHT_SUCHE = ("liste", "ort")


def schichten(vid: int, liste: str = "", tag: str = "",
              nur_luecken: bool = False) -> list[Zeile]:
    bedingungen, werte = ["s.veranstaltung_id = ?"], [vid]
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
    wo = " WHERE " + " AND ".join(bedingungen)

    con = verbinden()
    try:
        return _mit_suche(con.execute(
            "SELECT " + _SCHICHT_SPALTEN + " FROM schicht s" + wo +
            " ORDER BY s.beginn, lower(s.liste)", werte).fetchall(),
            *_SCHICHT_SUCHE)
    finally:
        con.close()


def schicht_laden(schicht_id: int) -> Zeile | None:
    con = verbinden()
    try:
        zeile = con.execute(
            "SELECT " + _SCHICHT_SPALTEN + " FROM schicht s WHERE s.id = ?",
            (schicht_id,)).fetchone()
        return _mit_suche([zeile], *_SCHICHT_SUCHE)[0] if zeile else None
    finally:
        con.close()


def besetzung(schicht_id: int) -> list[Zeile]:
    con = verbinden()
    try:
        return con.execute(
            "SELECT e.id AS einteilung_id, e.quelle, e.bemerkung AS notiz,"
            " e.eingeteilt_am, h.*"
            " FROM einteilung e JOIN helfer h ON h.id = e.helfer_id"
            " WHERE e.schicht_id = ?"
            " ORDER BY lower(h.name), e.id", (schicht_id,)).fetchall()
    finally:
        con.close()


def listen(vid: int) -> list[str]:
    con = verbinden()
    try:
        return [z["liste"] for z in con.execute(
            "SELECT liste FROM schicht WHERE veranstaltung_id = ?"
            " GROUP BY liste ORDER BY lower(liste)", (vid,))]
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


# --- Einteilung ------------------------------------------------------------

def einteilen(schicht_id: int, helfer_id: int, quelle: str = "hand",
              kuerzel: str = "",
              con: Verbindung | None = None) -> int:
    eigene = con is None
    con = con or verbinden()
    try:
        with (con if eigene else _offen()):
            zeiger = con.execute(
                "INSERT INTO einteilung (schicht_id, helfer_id, quelle,"
                " kuerzel, eingeteilt_am) VALUES (?, ?, ?, ?, ?)"
                " RETURNING id",
                (schicht_id, helfer_id, quelle, kuerzel, jetzt()))
            nummer = int(zeiger.fetchone()[0])
        return nummer
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
            "   AND a.veranstaltung_id = ? AND b.veranstaltung_id = ?"
            " GROUP BY h.id, a.id, b.id"
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
            " s.liste, s.beginn, COUNT(*) AS anzahl"
            " FROM einteilung e"
            " JOIN helfer h ON h.id = e.helfer_id"
            " JOIN schicht s ON s.id = e.schicht_id"
            " WHERE s.veranstaltung_id = ?"
            " GROUP BY h.id, s.id HAVING COUNT(*) > 1"
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

        bedarf = eine("SELECT COALESCE(SUM(bedarf), 0) FROM schicht"
                      " WHERE veranstaltung_id = ?", vid)
        besetzt = eine("SELECT COUNT(*) FROM einteilung e JOIN schicht s"
                       " ON s.id = e.schicht_id WHERE s.veranstaltung_id = ?", vid)
        return {
            "schichten": eine("SELECT COUNT(*) FROM schicht WHERE veranstaltung_id = ?",
                              vid),
            "helfer": eine("SELECT COUNT(*) FROM helfer WHERE aktiv = 1"),
            "bedarf": bedarf,
            "besetzt": besetzt,
            "offen": max(0, bedarf - besetzt),
            "luecken": eine(
                "SELECT COUNT(*) FROM schicht s WHERE s.veranstaltung_id = ?"
                " AND s.bedarf > (SELECT COUNT(*) FROM einteilung e"
                "                 WHERE e.schicht_id = s.id)", vid),
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
        "SELECT " + _SCHICHT_SPALTEN + " FROM schicht s WHERE " + bedingung +
        " ORDER BY s.beginn, lower(s.liste)", werte)], *_SCHICHT_SUCHE)
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
            " WHERE s.liste ILIKE '%shuttle%' AND s.veranstaltung_id = ?"
            " GROUP BY h.name ORDER BY lower(h.name)", (vid,))]
        gesehen = set(shuttle)
        rest = [z["name"] for z in con.execute(
            "SELECT name FROM helfer ORDER BY lower(name)")
            if z["name"] not in gesehen]
        return shuttle + rest
    finally:
        con.close()
