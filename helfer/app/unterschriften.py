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

from . import config, db, normalisieren

ARTEN = ("tshirt", "material", "schluessel")
RICHTUNGEN = ("ausgabe", "rueckgabe")

RICHTUNG_TEXT = {"ausgabe": "Ausgabe", "rueckgabe": "Rückgabe"}

# Ein Pfad besteht aus M/L-Befehlen und Zahlen, mehr nicht. Alles andere wird
# abgewiesen, statt es in ein SVG zu schreiben, das die Seite später ausliefert.
_PFAD = re.compile(r"^[ML0-9 .,\-]+$")

# Mehr als das zeichnet niemand mit dem Finger.
MAX_PFAD = 60_000

# Für den Ausschnitt: alle Zahlen aus einem Pfad herausholen.
_ZAHL = re.compile(r"-?\d+(?:\.\d+)?")


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
            # Bei der Rücknahme zählt, was zurückkam, nicht was einmal
            # rausging: wer das Funkgerät bringt und den Akku behält, soll
            # nicht quittieren, alles abgegeben zu haben.
            spalte = (lambda s: s + "_zurueck") if richtung == "rueckgabe" \
                else (lambda s: s)
            teile = []
            for stueck in db.MATERIAL:
                menge = zeile[spalte(stueck)]
                if menge:
                    teile.append(str(menge) + "× " + db.MATERIAL_TEXT[stueck])
            text = ", ".join(teile) or "nichts"
            if richtung == "ausgabe" and zeile["datum"]:
                text += " – für " + zeile["datum"]
            if richtung == "rueckgabe":
                offen_teile = []
                for stueck in db.MATERIAL:
                    rest = zeile[stueck] - zeile[stueck + "_zurueck"]
                    if rest:
                        offen_teile.append(str(rest) + "× "
                                           + db.MATERIAL_TEXT[stueck])
                if offen_teile:
                    text += " (noch draußen: " + ", ".join(offen_teile) + ")"
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


def namen_uebernehmen(art: str, vorgang_id: int, name: str) -> bool:
    """Schreibt einen am Tablet korrigierten Namen in den Bestand zurück.

    Die importierten Namen sind stellenweise unbrauchbar – "Krelli",
    "Pössneck1", "hüttner m". Wer gerade unterschreibt, ist die einzige
    Person, die es besser weiß, und der einzige Moment, in dem sie gefragt
    werden kann, ohne dass jemand extra hinterherlaufen muss.
    """
    if art == "tshirt":
        return db.helfer_umbenennen(vorgang_id, name)
    if art == "material":
        zeile = db.ausleihe_laden(vorgang_id)
        return db.helfer_umbenennen(zeile["helfer_id"], name) if zeile else False
    if art == "schluessel":
        return db.schluessel_umbenennen(vorgang_id, name)
    return False


def zeichnen(unterschrift_id: int, pfad: str, name: str = "") -> str:
    """Nimmt die Unterschrift entgegen. 'ok', 'leer', 'weg' oder 'zu-spaet'.

    `name` ist der am Tablet bestätigte oder korrigierte Name. Er landet im
    Beleg und, falls er sich geändert hat, auch im Bestand.
    """
    sauber = pfad_pruefen(pfad)
    if not sauber:
        return "leer"

    jetzt = db.jetzt_lokal()
    nachtragen = None

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

            person = normalisieren.text(name) or zeile["person"]
            zeitpunkt = db.jetzt()
            pruefsumme = hashlib.sha256(
                (zeile["wortlaut"] + "|" + person + "|" + sauber + "|"
                 + zeitpunkt).encode("utf-8")).hexdigest()
            con.execute(
                "UPDATE unterschrift SET unterschrieben_am = ?, bild = ?,"
                " person = ?, pruefsumme = ? WHERE id = ?",
                (zeitpunkt, sauber, person, pruefsumme, unterschrift_id))

            if person != zeile["person"]:
                nachtragen = (zeile["art"], zeile["vorgang_id"], person)
    finally:
        con.close()

    # Erst nach der Transaktion: das Umbenennen fasst andere Tabellen an und
    # gehört nicht in dieselbe Klammer wie der Beleg.
    if nachtragen:
        namen_uebernehmen(*nachtragen)
    return "ok"


def ausschnitt(pfad: str, rand: float = 8.0) -> str:
    """Die viewBox für einen gespeicherten Pfad.

    Ein festes Seitenverhältnis ginge nicht: gezeichnet wird auf der
    Canvasfläche des Tablets, und wie groß die ist, weiß niemand vorher. Der
    Ausschnitt wird deshalb aus dem Pfad selbst bestimmt – dann sitzt die
    Unterschrift mittig und füllt die Vorschau, statt verrutscht am Rand zu
    kleben.
    """
    werte = [float(z) for z in _ZAHL.findall(pfad or "")]
    if len(werte) < 4:
        return "0 0 100 40"

    xs, ys = werte[0::2], werte[1::2]
    links, rechts = min(xs) - rand, max(xs) + rand
    oben, unten = min(ys) - rand, max(ys) + rand
    breite = max(1.0, rechts - links)
    hoehe = max(1.0, unten - oben)

    # Sehr flache oder sehr schmale Unterschriften nicht bis zur
    # Unkenntlichkeit strecken: der Ausschnitt bekommt ein Mindestverhältnis.
    if breite / hoehe > 4:
        fehlt = breite / 4 - hoehe
        oben -= fehlt / 2
        hoehe = breite / 4
    elif hoehe / breite > 1.5:
        fehlt = hoehe * 1.5 - breite
        links -= fehlt / 2
        breite = hoehe * 1.5

    return "%.1f %.1f %.1f %.1f" % (links, oben, breite, hoehe)


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


def stand(seit: int = 0, art: str = "") -> dict:
    """Was sich seit `seit` getan hat – für das Nachfragen im Backoffice.

    Bewusst nur die Änderungen und nicht der ganze Zustand: die Antwort geht
    alle paar Sekunden über die Leitung und soll klein bleiben. `marke` ist
    die höchste vergebene Nummer; sie kommt beim nächsten Mal als `seit`
    zurück.

    Kein WebSocket: der bräuchte einen Umbau am nginx, Wiederverbinden nach
    jedem Netzzucken und trotzdem einen Abgleich für die verpassten
    Nachrichten – also am Ende beides. Zwei Sekunden Verzögerung sind an einem
    Ausgabetisch nicht wahrnehmbar.
    """
    bedingungen = ["unterschrieben_am IS NOT NULL", "id > ?"]
    werte: list = [max(0, int(seit or 0))]
    if art in ARTEN:
        bedingungen.append("art = ?")
        werte.append(art)

    con = db.verbinden()
    try:
        marke = con.execute(
            "SELECT COALESCE(MAX(id), 0) FROM unterschrift").fetchone()[0]
        neue = [
            {"art": z["art"], "vorgang_id": z["vorgang_id"],
             "richtung": z["richtung"], "person": z["person"],
             "wann": (z["unterschrieben_am"] or "")[:16]}
            for z in con.execute(
                "SELECT * FROM unterschrift WHERE " + " AND ".join(bedingungen)
                + " ORDER BY id", werte)]

        offen = con.execute(
            "SELECT id, titel, person FROM unterschrift"
            " WHERE unterschrieben_am IS NULL AND abgebrochen_am IS NULL"
            " AND laeuft_ab_am > ? ORDER BY id DESC LIMIT 1",
            (db.jetzt(),)).fetchone()
    finally:
        con.close()

    return {
        "marke": marke,
        "neu": neue,
        "offen": dict(offen) if offen else None,
    }


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
