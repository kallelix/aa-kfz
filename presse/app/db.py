"""Datenbankzugriff. PostgreSQL, Schema presse – siehe kern/db.py."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from kern import suchen
from kern.db import Datenbank, Verbindung

from . import config

_DATENBANK = Datenbank(lambda: config.DATABASE_URL, config.DB_SCHEMA,
                       Path(__file__).resolve().parent / "migrationen")


def jetzt() -> str:
    """Zeitstempel in ISO-8601 mit Sekundenauflösung, immer UTC."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def verbinden() -> Verbindung:
    return _DATENBANK.verbinden()


def transaktion():
    """Verbindung mit Commit bei Erfolg, Rollback bei Ausnahme."""
    return _DATENBANK.transaktion()


def init() -> list:
    """Spielt fehlende Migrationen ein und liefert ihre Namen fürs Protokoll."""
    return _DATENBANK.init()


# --- Anmeldungen ------------------------------------------------------------

# Felder, die im Backoffice korrigiert werden duerfen.
BEARBEITBAR = (
    "vorname",
    "nachname",
    "firma",
    "email",
    "telefon",
    "kommerziell",
    "gegenleistung",
    "verlinkung",
    "social_media",
    "bemerkung",
)

STATUS_WERTE = ("neu", "ausgegeben")

SORTIERUNGEN = {
    "neueste": "created_at DESC, id DESC",
    "aelteste": "created_at ASC, id ASC",
    "name": "lower(nachname), lower(vorname)",
    "firma": "lower(firma), lower(nachname)",
}

_SUCHFELDER = ("vorname", "nachname", "firma", "email", "telefon",
               "social_media", "bemerkung")


def anmeldung_anlegen(werte: dict, remote_ip: str | None) -> int:
    """Speichert eine validierte Anmeldung und liefert deren Nummer.

    Die Zeitstempel der Zustimmungen entstehen hier und nicht im Formular –
    massgeblich ist, wann der Server sie entgegengenommen hat.
    """
    zeitpunkt = jetzt()
    kommerziell = 1 if werte["kommerziell"] else 0
    gegenleistung = werte["gegenleistung"] or None

    with transaktion() as con:
        cur = con.execute(
            """
            INSERT INTO anmeldung (
                vorname, nachname, firma, email, telefon, kommerziell,
                gegenleistung, verlinkung, social_media, bemerkung, status,
                sicherheit_ok_am, bildrechte_ok_am, created_at, remote_ip
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'neu', ?, ?, ?, ?)
            RETURNING id
            """,
            (
                werte["vorname"],
                werte["nachname"],
                werte["firma"],
                werte["email"],
                werte["telefon"] or None,
                kommerziell,
                gegenleistung,
                1 if werte.get("verlinkung") else 0,
                werte.get("social_media") or None,
                werte["bemerkung"] or None,
                zeitpunkt,
                zeitpunkt if gegenleistung == "bilderspende" else None,
                zeitpunkt,
                remote_ip,
            ),
        )
        return int(cur.fetchone()[0])


def anmeldung_laden(anmeldung_id: int):
    con = verbinden()
    try:
        return con.execute(
            "SELECT * FROM anmeldung WHERE id = ?", (anmeldung_id,)
        ).fetchone()
    finally:
        con.close()


def anmeldungen_suchen(
    status: str = "",
    gegenleistung: str = "",
    suche: str = "",
    sortierung: str = "neueste",
) -> list:
    bedingungen: list[str] = []
    parameter: list = []

    if status:
        bedingungen.append("status = ?")
        parameter.append(status)
    if gegenleistung == "keine":
        bedingungen.append("gegenleistung IS NULL")
    elif gegenleistung:
        bedingungen.append("gegenleistung = ?")
        parameter.append(gegenleistung)

    wo = f"WHERE {' AND '.join(bedingungen)}" if bedingungen else ""
    ordnung = SORTIERUNGEN.get(sortierung, SORTIERUNGEN["neueste"])

    con = verbinden()
    try:
        zeilen = con.execute(
            f"SELECT * FROM anmeldung {wo} ORDER BY {ordnung}", parameter
        ).fetchall()
    finally:
        con.close()
    if suche and suche.strip():
        # Die Suche laeuft in Python, wie in kennzeichen/app/db.py: dieselbe
        # Regel wie im Browser, an einer Stelle (kern/suchen.py).
        zeilen = [zeile for zeile in zeilen if suchen.passt(
            suchen.suchtext(*(zeile[feld] or "" for feld in _SUCHFELDER)), suche)]
    return zeilen


def anmeldung_aktualisieren(anmeldung_id: int, werte: dict) -> bool:
    """Uebernimmt korrigierte Werte. Status und Haekchen bleiben unberuehrt.

    Wechselt jemand nachtraeglich auf Bilderspende, wird der Zeitstempel der
    Bildrechte gesetzt – dann hat allerdings die Orga zugestimmt, nicht der
    Antragsteller. Das steht so in der Detailansicht.
    """
    parameter = []
    for feld in BEARBEITBAR:
        wert = werte.get(feld)
        if feld in ("kommerziell", "verlinkung"):
            parameter.append(1 if wert else 0)
        else:
            parameter.append(wert or None)

    with transaktion() as con:
        vorher = con.execute(
            "SELECT bildrechte_ok_am FROM anmeldung WHERE id = ?", (anmeldung_id,)
        ).fetchone()
        if vorher is None:
            return False

        # Gegenleistung und Bildrechte muessen in EINEM Statement wandern: die
        # CHECK-Regel verlangt bei Bilderspende einen Zeitstempel, und
        # Zwischenzustaende gibt es dabei nicht.
        if werte.get("gegenleistung") == "bilderspende":
            bildrechte = vorher["bildrechte_ok_am"] or jetzt()
        else:
            bildrechte = None

        zuweisungen = ", ".join(feld + " = ?" for feld in BEARBEITBAR)
        cur = con.execute(
            f"UPDATE anmeldung SET {zuweisungen}, bildrechte_ok_am = ? WHERE id = ?",
            parameter + [bildrechte, anmeldung_id],
        )
        return cur.rowcount > 0


def anmeldung_loeschen(anmeldung_id: int) -> bool:
    with transaktion() as con:
        return con.execute(
            "DELETE FROM anmeldung WHERE id = ?", (anmeldung_id,)
        ).rowcount > 0


def zaehler() -> dict:
    """Zahlen fuer die Kopfzeile im Backoffice."""
    con = verbinden()
    try:
        gesamt = con.execute("SELECT COUNT(*) FROM anmeldung").fetchone()[0]
        ausgegeben = con.execute(
            "SELECT COUNT(*) FROM anmeldung WHERE status = 'ausgegeben'"
        ).fetchone()[0]
        je_gegenleistung = {
            zeile["schluessel"]: zeile["anzahl"]
            for zeile in con.execute(
                "SELECT COALESCE(gegenleistung, 'keine') AS schluessel,"
                " COUNT(*) AS anzahl FROM anmeldung GROUP BY schluessel"
            )
        }
        gebuehr_offen = con.execute(
            "SELECT COUNT(*) FROM anmeldung"
            " WHERE gegenleistung = 'gebuehr' AND gebuehr_bezahlt_am IS NULL"
        ).fetchone()[0]
        bilder_offen = con.execute(
            "SELECT COUNT(*) FROM anmeldung"
            " WHERE gegenleistung = 'bilderspende' AND bilder_erhalten_am IS NULL"
        ).fetchone()[0]
    finally:
        con.close()

    return {
        "gesamt": gesamt,
        "ausgegeben": ausgegeben,
        "offen": gesamt - ausgegeben,
        "je_gegenleistung": je_gegenleistung,
        "gebuehr_offen": gebuehr_offen,
        "bilder_offen": bilder_offen,
        "badges_gesamt": config.BADGES_GESAMT,
        "badges_knapp": bool(config.BADGES_GESAMT) and gesamt >= config.BADGES_GESAMT,
    }


def badges_erschoepft() -> bool:
    """Ob so viele Anmeldungen vorliegen wie Badges vorproduziert sind.

    Angenommen wird trotzdem weiter – abgeriegelt wuerde sonst auch der
    Fotograf, den die Orga eigentlich dabeihaben will.
    """
    if not config.BADGES_GESAMT:
        return False
    con = verbinden()
    try:
        return con.execute("SELECT COUNT(*) FROM anmeldung").fetchone()[0] >= config.BADGES_GESAMT
    finally:
        con.close()


# --- Mail-Queue -------------------------------------------------------------


def _mail_einreihen(con, anmeldung_id: int, mail: tuple) -> None:
    """mail = (typ, empfaenger, betreff, body). Laeuft in der Transaktion des
    Aufrufers, damit Vorgang und Mail zusammen stehen oder gar nicht."""
    typ, empfaenger, betreff, body = mail
    con.execute(
        "INSERT INTO mail_out (anmeldung_id, typ, empfaenger, betreff, body, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (anmeldung_id, typ, empfaenger, betreff, body, jetzt()),
    )


def mail_einreihen(anmeldung_id: int, mail: tuple) -> None:
    with transaktion() as con:
        _mail_einreihen(con, anmeldung_id, mail)


def mails_faellig(grenze: int = 20) -> list:
    con = verbinden()
    try:
        return con.execute(
            "SELECT * FROM mail_out"
            " WHERE gesendet_am IS NULL AND versuche < ?"
            "   AND (naechster_versuch IS NULL OR naechster_versuch <= ?)"
            " ORDER BY id LIMIT ?",
            (config.MAIL_MAX_VERSUCHE, jetzt(), grenze),
        ).fetchall()
    finally:
        con.close()


def mail_gesendet(mail_id: int) -> None:
    with transaktion() as con:
        con.execute(
            "UPDATE mail_out SET gesendet_am = ?, versuche = versuche + 1,"
            " letzter_fehler = NULL, naechster_versuch = NULL WHERE id = ?",
            (jetzt(), mail_id),
        )


def mail_fehlgeschlagen(mail_id: int, fehler: str, naechster_versuch: str | None) -> None:
    with transaktion() as con:
        con.execute(
            "UPDATE mail_out SET versuche = versuche + 1, letzter_fehler = ?,"
            " naechster_versuch = ? WHERE id = ?",
            (fehler[:500], naechster_versuch, mail_id),
        )


def mail_erneut(mail_id: int) -> bool:
    with transaktion() as con:
        return con.execute(
            "UPDATE mail_out SET versuche = 0, naechster_versuch = NULL,"
            " letzter_fehler = NULL WHERE id = ? AND gesendet_am IS NULL",
            (mail_id,),
        ).rowcount > 0


def mails_zu_anmeldung(anmeldung_id: int) -> list:
    con = verbinden()
    try:
        return con.execute(
            "SELECT * FROM mail_out WHERE anmeldung_id = ? ORDER BY id",
            (anmeldung_id,),
        ).fetchall()
    finally:
        con.close()


def mails_aufgegeben() -> int:
    con = verbinden()
    try:
        return con.execute(
            "SELECT COUNT(*) FROM mail_out WHERE gesendet_am IS NULL AND versuche >= ?",
            (config.MAIL_MAX_VERSUCHE,),
        ).fetchone()[0]
    finally:
        con.close()


# --- Einstellungen ----------------------------------------------------------


def einstellung_lesen(schluessel: str) -> str | None:
    con = verbinden()
    try:
        zeile = con.execute(
            "SELECT wert FROM einstellung WHERE schluessel = ?", (schluessel,)
        ).fetchone()
        return zeile["wert"] if zeile else None
    finally:
        con.close()


def einstellung_setzen(schluessel: str, wert: str) -> None:
    with transaktion() as con:
        con.execute(
            "INSERT INTO einstellung (schluessel, wert, geaendert_am)"
            " VALUES (?, ?, ?)"
            " ON CONFLICT(schluessel) DO UPDATE SET wert = excluded.wert,"
            " geaendert_am = excluded.geaendert_am",
            (schluessel, wert, jetzt()),
        )


# --- Abholung am Orga-Buero -------------------------------------------------


def anmeldungen_abholung() -> list:
    """Alle Anmeldungen fuer den Schalter, sortiert nach Nachname.

    Bewusst ohne Statusfilter: wer schon ein Badge hat, muss ebenfalls
    auffindbar sein - sonst gibt man ihm versehentlich ein zweites.
    """
    con = verbinden()
    try:
        return con.execute(
            "SELECT * FROM anmeldung"
            " ORDER BY lower(nachname), lower(vorname)"
        ).fetchall()
    finally:
        con.close()


def badge_ausgeben(anmeldung_id: int, kuerzel: str = "") -> bool:
    """Badge uebergeben. Der Ausgangsstatus steckt in der Bedingung, damit
    zwei gleichzeitige Klicks sich nicht ueberholen."""
    with transaktion() as con:
        return con.execute(
            "UPDATE anmeldung SET status = 'ausgegeben', badge_am = ?,"
            " badge_durch = ? WHERE id = ? AND status = 'neu'",
            (jetzt(), kuerzel or None, anmeldung_id),
        ).rowcount > 0


def badge_zuruecknehmen(anmeldung_id: int) -> bool:
    """Versehentlich abgehakt - zurueck auf neu."""
    with transaktion() as con:
        return con.execute(
            "UPDATE anmeldung SET status = 'neu', badge_am = NULL,"
            " badge_durch = NULL WHERE id = ? AND status = 'ausgegeben'",
            (anmeldung_id,),
        ).rowcount > 0


def gebuehr_setzen(anmeldung_id: int, bezahlt: bool) -> bool:
    """Haekchen 'Gebuehr bezahlt'. Nur sinnvoll, wo die Gebuehr gewaehlt wurde -
    die Bedingung steht deshalb im UPDATE."""
    with transaktion() as con:
        return con.execute(
            "UPDATE anmeldung SET gebuehr_bezahlt_am = ?"
            " WHERE id = ? AND gegenleistung = 'gebuehr'",
            (jetzt() if bezahlt else None, anmeldung_id),
        ).rowcount > 0


def bilder_setzen(anmeldung_id: int, erhalten: bool) -> bool:
    with transaktion() as con:
        return con.execute(
            "UPDATE anmeldung SET bilder_erhalten_am = ?"
            " WHERE id = ? AND gegenleistung = 'bilderspende'",
            (jetzt() if erhalten else None, anmeldung_id),
        ).rowcount > 0


# --- Bilderspende nachhalten (Schritt 7) ------------------------------------


def anmeldungen_bilder_offen() -> list:
    """Wer Bilderspende gewaehlt, ein Badge bekommen und noch nicht geliefert hat.

    Der Badge-Status gehoert in die Bedingung: wer gar nicht aufgetaucht ist,
    schuldet auch keine Bilder.
    """
    con = verbinden()
    try:
        return con.execute(
            "SELECT * FROM anmeldung"
            " WHERE gegenleistung = 'bilderspende'"
            "   AND status = 'ausgegeben'"
            "   AND bilder_erhalten_am IS NULL"
            " ORDER BY erinnerung_am IS NOT NULL, erinnerung_am, lower(nachname)"
        ).fetchall()
    finally:
        con.close()


def bilder_offen_zaehlen() -> int:
    con = verbinden()
    try:
        return con.execute(
            "SELECT COUNT(*) FROM anmeldung"
            " WHERE gegenleistung = 'bilderspende' AND status = 'ausgegeben'"
            "   AND bilder_erhalten_am IS NULL"
        ).fetchone()[0]
    finally:
        con.close()


def erinnerung_einreihen(anmeldung_id: int, mail: tuple) -> bool:
    """Erinnerungsmail einreihen und den Zeitpunkt vermerken – in einem Vorgang.

    Die Bedingungen stecken im UPDATE: wer schon geliefert hat oder gar keine
    Bilderspende gewaehlt hat, bekommt keine Erinnerung, auch nicht bei einem
    zweiten Klick.
    """
    with transaktion() as con:
        geaendert = con.execute(
            "UPDATE anmeldung SET erinnerung_am = ?"
            " WHERE id = ? AND gegenleistung = 'bilderspende'"
            "   AND bilder_erhalten_am IS NULL",
            (jetzt(), anmeldung_id),
        ).rowcount > 0
        if geaendert and mail is not None:
            _mail_einreihen(con, anmeldung_id, mail)
        return geaendert
