"""Unterschriften bei Ausgabe und Rücknahme.

Das Tablet steht dauerhaft auf einer Adresse und fragt im Takt nach, ob etwas
ansteht. Schließt jemand im Backoffice eine Ausgabe ab und fordert eine
Unterschrift an, springt das Tablet beim nächsten Nachfragen um, zeigt den
Vorgang groß und nimmt die Unterschrift entgegen.

Drei Entscheidungen, die den Aufbau bestimmen:

* **Die Übergabe hängt nicht an der Unterschrift.** Der Vorgang ist längst
  gespeichert, wenn die Anforderung entsteht. Reißt das WLAN ab oder startet
  das Tablet neu, geht die Ausgabe trotzdem durch und die Unterschrift lässt
  sich nachholen. Alles andere hieße: eine Schlange am Tisch, weil ein Gerät
  hakt.
* **Der Wortlaut wird mitgespeichert**, nicht nur ein Verweis auf den Vorgang.
  Wer eine Zeile unterschreibt, hat diese Zeile unterschrieben – wird der
  Vorgang später korrigiert, dokumentiert die Unterschrift weiter den Stand,
  der auf dem Tablet stand.
* **Die Anforderung verfällt.** Die Tablet-Adresse nimmt Eingaben entgegen,
  anders als die Monitoransicht. Solange nichts ansteht, kann ein
  abhandengekommener Link nichts anrichten.

Was er NICHT ist: eine qualifizierte elektronische Signatur. Eine auf Glas
gemalte Unterschrift belegt nicht, wer gezeichnet hat. Ihr Wert liegt in der
Verbindlichkeit im Kopf – wer unterschreibt, hat gesehen, was er mitnimmt.
Zeitpunkt, Kürzel und Prüfsumme heben den Beweiswert, sie ersetzen ihn nicht.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta

from . import config, db

ARTEN = ("tshirt", "material", "schluessel")
RICHTUNGEN = ("ausgabe", "rueckgabe")

RICHTUNG_TEXT = {"ausgabe": "Ausgabe", "rueckgabe": "Rückgabe"}

# Ein Pfad besteht aus M/L-Befehlen und Zahlen, mehr nicht. Alles andere wird
# abgewiesen, statt es in ein SVG zu schreiben, das die Seite später ausliefert.
_PFAD = re.compile(r"^[ML0-9 .,\-]+$")

# Mehr als das zeichnet niemand mit dem Finger.
MAX_PFAD = 60_000


def wortlaut(art: str, vorgang_id: int, richtung: str) -> tuple[str, str, str]:
    """(Titel, Wortlaut, Person) für einen Vorgang. Leerer Titel = gibt es nicht."""
    if art == "tshirt":
        person = db.helfer_laden(vorgang_id)
        if person is None:
            return "", "", ""
        groesse = person["tshirt_ausgegeben"] or person["tshirt"] or "ohne Größe"
        return ("T-Shirt " + RICHTUNG_TEXT[richtung],
                "T-Shirt in Größe " + groesse, person["name"])

    if art == "material":
        for zeile in db.ausleihen_liste():
            if zeile["id"] != vorgang_id:
                continue
            teile = []
            for stueck in db.MATERIAL:
                if zeile[stueck]:
                    teile.append(str(zeile[stueck]) + "× "
                                 + db.MATERIAL_TEXT[stueck])
            text = ", ".join(teile) or "nichts"
            if zeile["datum"]:
                text += " – für " + zeile["datum"]
            return ("Material " + RICHTUNG_TEXT[richtung], text, zeile["name"])
        return "", "", ""

    if art == "schluessel":
        for zeile in db.schluessel_liste():
            if zeile["id"] != vorgang_id:
                continue
            text = "Fahrzeugschlüssel " + zeile["kennzeichen"]
            if zeile["bemerkung"]:
                text += " – " + zeile["bemerkung"]
            return ("Schlüssel " + RICHTUNG_TEXT[richtung], text,
                    zeile["name"] or "")
        return "", "", ""

    return "", "", ""


def anfordern(art: str, vorgang_id: int, richtung: str,
              kuerzel: str = "") -> tuple[int | None, str]:
    """Stellt einen Vorgang aufs Tablet. (id, Meldung).

    Es gibt nur EINE Warteschlange. Steht schon etwas an, wird es abgelöst –
    am Tisch steht immer nur eine Person, und ein Stapel unerledigter
    Anforderungen wäre nur eine Falle für den nächsten.
    """
    if art not in ARTEN or richtung not in RICHTUNGEN:
        return None, "unbekannt"

    titel, text, person = wortlaut(art, vorgang_id, richtung)
    if not titel:
        return None, "unbekannt"

    jetzt = db.jetzt_lokal()
    ablauf = jetzt + timedelta(minutes=config.UNTERSCHRIFT_MINUTEN)

    con = db.verbinden()
    try:
        with con:
            con.execute(
                "UPDATE unterschrift SET abgebrochen_am = ?"
                " WHERE unterschrieben_am IS NULL AND abgebrochen_am IS NULL",
                (db.jetzt(),))
            zeiger = con.execute(
                "INSERT INTO unterschrift (art, vorgang_id, richtung, titel,"
                " wortlaut, person, angefordert_am, laeuft_ab_am, kuerzel)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (art, vorgang_id, richtung, titel, text, person,
                 db.jetzt(), ablauf.strftime("%Y-%m-%d %H:%M:%S"), kuerzel))
        return int(zeiger.lastrowid), "angefordert"
    finally:
        con.close()


def offen() -> dict | None:
    """Was gerade auf dem Tablet stehen soll – oder nichts."""
    con = db.verbinden()
    try:
        zeile = con.execute(
            "SELECT * FROM unterschrift WHERE unterschrieben_am IS NULL"
            " AND abgebrochen_am IS NULL AND laeuft_ab_am > ?"
            " ORDER BY id DESC LIMIT 1", (db.jetzt(),)).fetchone()
        return dict(zeile) if zeile else None
    finally:
        con.close()


def abbrechen(unterschrift_id: int | None = None) -> bool:
    """Nimmt die Anforderung zurück. Ohne Nummer alles, was offen ist."""
    con = db.verbinden()
    try:
        with con:
            if unterschrift_id is None:
                zeiger = con.execute(
                    "UPDATE unterschrift SET abgebrochen_am = ?"
                    " WHERE unterschrieben_am IS NULL AND abgebrochen_am IS NULL",
                    (db.jetzt(),))
            else:
                zeiger = con.execute(
                    "UPDATE unterschrift SET abgebrochen_am = ?"
                    " WHERE id = ? AND unterschrieben_am IS NULL"
                    " AND abgebrochen_am IS NULL",
                    (db.jetzt(), unterschrift_id))
        return zeiger.rowcount > 0
    finally:
        con.close()


def pfad_pruefen(roh: str) -> str:
    """Der gezeichnete Pfad, oder '' wenn er nicht taugt.

    Nur M, L, Ziffern und Trennzeichen. Der Pfad landet später unverändert in
    einem ausgelieferten SVG – was hier durchkommt, steht dort im Markup.
    """
    wert = (roh or "").strip()
    if not wert or len(wert) > MAX_PFAD:
        return ""
    if not _PFAD.match(wert):
        return ""
    if "M" not in wert:
        return ""
    return wert


def zeichnen(unterschrift_id: int, pfad: str) -> str:
    """Nimmt die Unterschrift entgegen. 'ok', 'leer', 'weg' oder 'zu-spaet'."""
    sauber = pfad_pruefen(pfad)
    if not sauber:
        return "leer"

    jetzt = db.jetzt_lokal()
    con = db.verbinden()
    try:
        with con:
            zeile = con.execute(
                "SELECT * FROM unterschrift WHERE id = ?",
                (unterschrift_id,)).fetchone()
            if (zeile is None or zeile["unterschrieben_am"]
                    or zeile["abgebrochen_am"]):
                return "weg"

            # Wer beim Ablaufen gerade zeichnet, soll nicht von vorn anfangen
            # müssen: angezeigt wird der Eintrag dann nicht mehr, angenommen
            # innerhalb der Nachfrist schon.
            try:
                grenze = (datetime.fromisoformat(zeile["laeuft_ab_am"])
                          + timedelta(minutes=config.UNTERSCHRIFT_NACHFRIST))
            except ValueError:
                return "weg"
            if jetzt > grenze:
                return "zu-spaet"

            zeitpunkt = db.jetzt()
            pruefsumme = hashlib.sha256(
                (zeile["wortlaut"] + "|" + sauber + "|" + zeitpunkt)
                .encode("utf-8")).hexdigest()
            con.execute(
                "UPDATE unterschrift SET unterschrieben_am = ?, bild = ?,"
                " pruefsumme = ? WHERE id = ?",
                (zeitpunkt, sauber, pruefsumme, unterschrift_id))
        return "ok"
    finally:
        con.close()


def liste(grenze: int = 100) -> list[dict]:
    con = db.verbinden()
    try:
        return [dict(z) for z in con.execute(
            "SELECT * FROM unterschrift WHERE unterschrieben_am IS NOT NULL"
            " ORDER BY unterschrieben_am DESC LIMIT ?", (grenze,))]
    finally:
        con.close()


def je_vorgang(art: str) -> dict[int, dict]:
    """Was zu welchem Vorgang unterschrieben wurde – für die Listen."""
    con = db.verbinden()
    try:
        ergebnis: dict[int, dict] = {}
        for zeile in con.execute(
                "SELECT * FROM unterschrift WHERE art = ?"
                " AND unterschrieben_am IS NOT NULL"
                " ORDER BY unterschrieben_am", (art,)):
            eintrag = ergebnis.setdefault(zeile["vorgang_id"], {})
            eintrag[zeile["richtung"]] = dict(zeile)
        return ergebnis
    finally:
        con.close()


def zaehler() -> dict:
    con = db.verbinden()
    try:
        def eine(sql, *werte):
            return con.execute(sql, werte).fetchone()[0]

        return {
            "unterschrieben": eine(
                "SELECT COUNT(*) FROM unterschrift"
                " WHERE unterschrieben_am IS NOT NULL"),
            "abgebrochen": eine(
                "SELECT COUNT(*) FROM unterschrift"
                " WHERE abgebrochen_am IS NOT NULL"),
        }
    finally:
        con.close()
