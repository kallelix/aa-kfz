"""Zeitplan der Rennserien von deren Websites holen und lesen.

Beide Serien veröffentlichen ihren Zeitplan als HTML-Tabelle:

    Tag      | Beschreibung          | Zeit
    Freitag  | Startnummerausgabe    | 09.00 - 18.00 Uhr
             | Track Walk            | 10.00 - 12.00 Uhr

Drei Dinge machen daraus mehr als ein Dreizeiler:

1. Auf der DHC-Seite stehen ZWEI Zeitpläne untereinander – einer allgemein,
   einer für Willingen, mit anderen Zeiten. Unterschieden werden sie nur durch
   die Überschrift davor. Wer die erste oder letzte Tabelle nimmt, erwischt
   irgendwann die falsche, ohne es zu merken. Deshalb wird über die
   Überschrift ausgewählt, und bei Uneindeutigkeit brechen wir ab.
2. Auf beiden Seiten stehen unten noch vier Cookie-Tabellen. Die fallen schon
   durch die Kopfzeile heraus: ohne Tag- und Zeitspalte ist es kein Zeitplan.
3. In den Tabellen stehen Wochentage, keine Daten. Die Zuordnung läuft über
   die konfigurierten Veranstaltungstage; Zeilen ohne Tag erben den vorigen.

Kein zusätzliches Paket: html.parser und urllib reichen. Reguläre Ausdrücke
auf HTML wären hier heikel, weil beide Seiten verschachtelte Tabellen und
Markup in den Zellen haben.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html.parser import HTMLParser

from . import config, normalisieren

# Mehr als das liest niemand mehr ein – schützt davor, dass eine kaputte oder
# feindliche Antwort den Dienst vollsaugt.
MAX_BYTES = 4 * 1024 * 1024
ZEITSPERRE = 20

KOPF_TAG = ("tag", "wochentag")
KOPF_ZEIT = ("zeit", "uhrzeit")


class Fehler(Exception):
    """Abruf oder Auswertung ist gescheitert – es wird nichts übernommen."""


@dataclass
class Eintrag:
    serie: str
    titel: str
    datum: str
    beginn: str | None
    ende: str | None
    tag_roh: str
    zeit_roh: str


@dataclass
class Ergebnis:
    serie: str
    ueberschrift: str
    eintraege: list[Eintrag] = field(default_factory=list)
    # probleme = Zeile wurde verworfen. hinweise = Zeile wurde uebernommen,
    # ist aber erwaehnenswert. Der Unterschied zaehlt: was auf jeder Seite
    # normal ist, darf nicht bei jedem Abruf wie ein Fehler aussehen.
    probleme: list[str] = field(default_factory=list)
    hinweise: list[str] = field(default_factory=list)


# --- HTML einsammeln -------------------------------------------------------

class _Sammler(HTMLParser):
    """Liest Überschriften und Tabellen in Dokumentreihenfolge ein.

    Verschachtelte Tabellen werden mitgezählt, damit eine innere Tabelle nicht
    die äußere beendet.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stuecke: list[tuple[str, object]] = []
        self._ueberschrift: list[str] | None = None
        self._tiefe = 0
        self._tabelle: list[list[str]] | None = None
        self._zeile: list[str] | None = None
        self._zelle: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3", "h4"):
            self._ueberschrift = []
        elif tag == "table":
            self._tiefe += 1
            if self._tiefe == 1:
                self._tabelle = []
        elif self._tiefe == 1:
            if tag == "tr":
                self._zeile = []
            elif tag in ("td", "th"):
                self._zelle = []
            elif tag == "br" and self._zelle is not None:
                self._zelle.append(" ")

    def handle_endtag(self, tag):
        if tag in ("h1", "h2", "h3", "h4"):
            if self._ueberschrift is not None:
                text = normalisieren.text("".join(self._ueberschrift))
                if text:
                    self.stuecke.append(("ueberschrift", text))
            self._ueberschrift = None
        elif tag == "table":
            if self._tiefe == 1 and self._tabelle is not None:
                self.stuecke.append(("tabelle", self._tabelle))
                self._tabelle = None
            self._tiefe = max(0, self._tiefe - 1)
        elif self._tiefe == 1:
            if tag in ("td", "th") and self._zelle is not None:
                if self._zeile is not None:
                    self._zeile.append(normalisieren.text("".join(self._zelle)))
                self._zelle = None
            elif tag == "tr" and self._zeile is not None:
                if self._tabelle is not None:
                    self._tabelle.append(self._zeile)
                self._zeile = None

    def handle_data(self, daten):
        if self._zelle is not None:
            self._zelle.append(daten)
        elif self._ueberschrift is not None:
            self._ueberschrift.append(daten)


def abschnitte(html: str) -> list[tuple[str, list[list[str]]]]:
    """Alle Tabellen samt der Überschrift, die unmittelbar davor steht."""
    sammler = _Sammler()
    sammler.feed(html)
    sammler.close()

    ergebnis = []
    letzte = ""
    for art, wert in sammler.stuecke:
        if art == "ueberschrift":
            letzte = str(wert)
        else:
            ergebnis.append((letzte, wert))  # type: ignore[arg-type]
    return ergebnis


def ist_zeitplan(zeilen: list[list[str]]) -> bool:
    """Erkennt einen Zeitplan an seiner Kopfzeile: eine Tag- und eine
    Zeitspalte. Die Cookie-Tabellen am Seitenende fallen damit heraus, ohne
    dass wir sie einzeln kennen müssen."""
    if len(zeilen) < 2 or not zeilen[0]:
        return False
    kopf = [z.casefold().strip(": ") for z in zeilen[0]]
    return (len(kopf) >= 3
            and any(k in KOPF_TAG for k in kopf)
            and any(k in KOPF_ZEIT for k in kopf))


def tabelle_waehlen(html: str, muster: str) -> tuple[str, list[list[str]]]:
    """Sucht die Zeitplantabelle, deren Überschrift `muster` enthält.

    Bricht ab, wenn keine oder mehrere passen – lieber gar kein Zeitplan als
    heimlich der von Willingen.
    """
    kandidaten = [(kopf, zeilen) for kopf, zeilen in abschnitte(html)
                  if ist_zeitplan(zeilen)]
    if not kandidaten:
        raise Fehler("Auf der Seite steht keine Tabelle mit Tag- und "
                     "Zeitspalte. Vermutlich wurde die Seite umgebaut.")

    gesucht = muster.casefold().strip()
    passend = [(kopf, zeilen) for kopf, zeilen in kandidaten
               if gesucht in kopf.casefold()]

    if len(passend) == 1:
        return passend[0]
    ueberschriften = ", ".join(repr(kopf) for kopf, _ in kandidaten)
    if not passend:
        raise Fehler(
            "Keine Tabelle steht unter einer Überschrift mit " + repr(muster) +
            ". Gefunden wurden: " + ueberschriften + ".")
    raise Fehler(
        str(len(passend)) + " Tabellen passen auf " + repr(muster) +
        " – das ist nicht eindeutig. Gefunden wurden: " + ueberschriften + ".")


# --- Zeilen auswerten ------------------------------------------------------

_UHRZEIT = re.compile(r"\b(\d{1,2})[.:](\d{2})\b")


def zeiten(datum: str, roh: str) -> tuple[str | None, str | None]:
    """('2026-08-28', '09.00 - 18.00 Uhr') -> ('2026-08-28 09:00', '… 18:00').

    Offene Enden bleiben offen: 'ab 13.30 Uhr' liefert nur einen Beginn,
    'anschließend' und 'ca. 30 min nach Rennschluss' gar nichts. Das ist keine
    Panne, sondern steht so auf den Seiten – im Band laufen solche Blöcke aus.
    """
    treffer = _UHRZEIT.findall(roh or "")
    gueltig = [(int(s), int(m)) for s, m in treffer if int(s) <= 23 and int(m) <= 59]
    if not gueltig:
        return None, None

    try:
        tag = datetime.fromisoformat(datum)
    except ValueError:
        return None, None

    beginn = tag.replace(hour=gueltig[0][0], minute=gueltig[0][1])
    if len(gueltig) < 2:
        return beginn.strftime("%Y-%m-%d %H:%M"), None

    ende = tag.replace(hour=gueltig[1][0], minute=gueltig[1][1])
    if ende <= beginn:
        ende += timedelta(days=1)
    return beginn.strftime("%Y-%m-%d %H:%M"), ende.strftime("%Y-%m-%d %H:%M")


def _spalten(kopf: list[str]) -> tuple[int, int, int]:
    """Welche Spalte ist Tag, welche Bezeichnung, welche Zeit? Die mittlere
    heißt mal 'Beschreibung', mal 'Bezeichnung' – darauf ist kein Verlass,
    also wird sie als die übrige bestimmt."""
    klein = [z.casefold().strip(": ") for z in kopf]
    tag = next(i for i, z in enumerate(klein) if z in KOPF_TAG)
    zeit = next(i for i, z in enumerate(klein) if z in KOPF_ZEIT)
    rest = [i for i in range(len(kopf)) if i not in (tag, zeit)]
    return tag, (rest[0] if rest else 1), zeit


def auswerten(serie: str, ueberschrift: str,
              zeilen: list[list[str]]) -> Ergebnis:
    ergebnis = Ergebnis(serie=serie, ueberschrift=ueberschrift)
    spalte_tag, spalte_titel, spalte_zeit = _spalten(zeilen[0])

    letzter_tag = ""
    gesehen: set[tuple[str, str]] = set()

    for nummer, zeile in enumerate(zeilen[1:], start=2):
        if len(zeile) <= max(spalte_tag, spalte_titel, spalte_zeit):
            continue

        titel = normalisieren.text(zeile[spalte_titel])
        if not titel:
            continue

        tag_roh = normalisieren.text(zeile[spalte_tag]) or letzter_tag
        if not tag_roh:
            ergebnis.probleme.append(
                "Zeile " + str(nummer) + " (" + titel + "): kein Wochentag, "
                "auch nicht in den Zeilen darüber – übersprungen.")
            continue
        letzter_tag = tag_roh

        datum = config.tag_zu_datum(tag_roh)
        if datum is None:
            ergebnis.probleme.append(
                "Zeile " + str(nummer) + " (" + titel + "): " + repr(tag_roh) +
                " lässt sich keinem der Veranstaltungstage zuordnen – "
                "übersprungen.")
            continue

        merkmal = (datum.isoformat(), titel)
        if merkmal in gesehen:
            ergebnis.probleme.append(
                "Zeile " + str(nummer) + ": " + repr(titel) + " steht am " +
                tag_roh + " zweimal – nur der erste Eintrag wird übernommen.")
            continue
        gesehen.add(merkmal)

        zeit_roh = normalisieren.text(zeile[spalte_zeit])
        beginn, ende = zeiten(datum.isoformat(), zeit_roh)
        if beginn is None and zeit_roh:
            ergebnis.hinweise.append(
                titel + " am " + tag_roh + ": " + repr(zeit_roh) +
                " nennt keine Uhrzeit – der Block läuft im Band aus.")

        ergebnis.eintraege.append(Eintrag(
            serie=serie, titel=titel, datum=datum.isoformat(),
            beginn=beginn, ende=ende, tag_roh=tag_roh, zeit_roh=zeit_roh))

    if not ergebnis.eintraege:
        raise Fehler("Die Tabelle unter " + repr(ueberschrift) +
                     " enthält keine verwertbare Zeile.")
    return ergebnis


# --- Abruf -----------------------------------------------------------------

def holen(url: str) -> str:
    if not url.lower().startswith(("http://", "https://")):
        raise Fehler("Nur http und https sind erlaubt: " + url)

    anfrage = urllib.request.Request(url, headers={
        "User-Agent": "Abfahrt-Helferdashboard/1.0 (+Vereinsintern)",
        "Accept": "text/html,application/xhtml+xml",
    })
    try:
        with urllib.request.urlopen(anfrage, timeout=ZEITSPERRE) as antwort:
            # Auch nach einer Weiterleitung darf es nichts anderes als HTTP
            # sein – sonst liesse sich der Dienst auf file:// lenken.
            if not antwort.geturl().lower().startswith(("http://", "https://")):
                raise Fehler("Die Seite leitet auf etwas anderes als http(s) um.")
            rohdaten = antwort.read(MAX_BYTES + 1)
            if len(rohdaten) > MAX_BYTES:
                raise Fehler("Die Seite ist größer als "
                             + str(MAX_BYTES // 1024 // 1024) + " MB.")
            kodierung = antwort.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as fehler:
        raise Fehler("Der Server antwortet mit HTTP " + str(fehler.code) +
                     ".") from fehler
    except urllib.error.URLError as fehler:
        raise Fehler("Die Seite ist nicht erreichbar: " +
                     str(fehler.reason) + ".") from fehler
    except TimeoutError as fehler:
        raise Fehler("Die Seite hat länger als " + str(ZEITSPERRE) +
                     " Sekunden gebraucht.") from fehler

    return rohdaten.decode(kodierung, errors="replace")


def abrufen(serie: str, url: str, abschnitt: str) -> Ergebnis:
    """Holt eine Seite und liest den passenden Zeitplan heraus."""
    ueberschrift, zeilen = tabelle_waehlen(holen(url), abschnitt)
    return auswerten(serie, ueberschrift, zeilen)


# --- Übernehmen ------------------------------------------------------------

def _beschreibe(zeile) -> str:
    if zeile["beginn"] and zeile["ende"]:
        return zeile["beginn"][11:] + "–" + zeile["ende"][11:]
    if zeile["beginn"]:
        return "ab " + zeile["beginn"][11:]
    return zeile["zeit_roh"] or "ohne Zeit"


def uebernehmen(ergebnis: Ergebnis, ausloeser: str = "") -> dict:
    """Schreibt das Abrufergebnis in die Datenbank und sagt, was sich geändert
    hat.

    Drei Regeln, die zusammen dafür sorgen, dass niemand überrascht wird:

    * Was die Orga von Hand geändert hat (von_hand = 1), wird NICHT
      überschrieben. Die Abweichung steht im Bericht, die eigene Fassung
      bleibt stehen.
    * Was von der Website verschwindet, wird nicht gelöscht, sondern als
      entfallen markiert. Ein Eintrag, der später wieder auftaucht, lebt auf.
    * Alles andere wird übernommen – aber jede Änderung wird benannt, mit
      altem und neuem Wert.
    """
    from . import db  # spät, damit zeitplan.py ohne Datenbank prüfbar bleibt

    neu, geaendert, geschuetzt, entfallen, zurueck = [], [], [], [], []

    con = db.verbinden()
    try:
        with con:
            vorhanden = {
                z["titel"] + "|" + z["datum"]: z for z in con.execute(
                    "SELECT * FROM programm WHERE serie = ?",
                    (ergebnis.serie,))}

            gesehen = set()
            for eintrag in ergebnis.eintraege:
                merkmal = eintrag.titel + "|" + eintrag.datum
                gesehen.add(merkmal)
                alt = vorhanden.get(merkmal)

                if alt is None:
                    con.execute(
                        "INSERT INTO programm (serie, titel, datum, beginn,"
                        " ende, tag_roh, zeit_roh, angelegt_am)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (eintrag.serie, eintrag.titel, eintrag.datum,
                         eintrag.beginn, eintrag.ende, eintrag.tag_roh,
                         eintrag.zeit_roh, db.jetzt()))
                    neu.append(eintrag.titel + " am " + eintrag.tag_roh +
                               ", " + (eintrag.zeit_roh or "ohne Zeit"))
                    continue

                gleich = (alt["beginn"] == eintrag.beginn
                          and alt["ende"] == eintrag.ende
                          and alt["zeit_roh"] == eintrag.zeit_roh)

                # Steht wieder auf der Website: die Markierung muss weg,
                # unabhängig davon, ob die Zeiten inzwischen abweichen. Sonst
                # bliebe ein von Hand geänderter Eintrag für immer als
                # entfallen stehen, obwohl es ihn wieder gibt.
                if alt["entfallen_am"]:
                    con.execute(
                        "UPDATE programm SET entfallen_am = NULL,"
                        " geaendert_am = ? WHERE id = ?",
                        (db.jetzt(), alt["id"]))
                    zurueck.append(eintrag.titel + " am " + eintrag.tag_roh)

                if gleich:
                    continue

                if alt["von_hand"]:
                    geschuetzt.append(
                        eintrag.titel + " am " + eintrag.tag_roh +
                        ": auf der Website steht jetzt " +
                        (eintrag.zeit_roh or "keine Zeit") + ", hier steht " +
                        _beschreibe(alt) + " – deine Fassung bleibt.")
                    continue

                con.execute(
                    "UPDATE programm SET beginn = ?, ende = ?, tag_roh = ?,"
                    " zeit_roh = ?, entfallen_am = NULL, geaendert_am = ?,"
                    " version = version + 1"
                    " WHERE id = ?",
                    (eintrag.beginn, eintrag.ende, eintrag.tag_roh,
                     eintrag.zeit_roh, db.jetzt(), alt["id"]))
                geaendert.append(
                    eintrag.titel + " am " + eintrag.tag_roh + ": " +
                    _beschreibe(alt) + " wird " +
                    (eintrag.zeit_roh or "ohne Zeit"))

            for merkmal, alt in vorhanden.items():
                if merkmal in gesehen or alt["entfallen_am"]:
                    continue
                con.execute(
                    "UPDATE programm SET entfallen_am = ?, geaendert_am = ?"
                    " WHERE id = ?", (db.jetzt(), db.jetzt(), alt["id"]))
                entfallen.append(alt["titel"] + " am " + (alt["tag_roh"] or
                                 alt["datum"]) + " steht nicht mehr auf der "
                                 "Website – bleibt hier als entfallen stehen.")
    finally:
        con.close()

    bericht = {
        "serie": ergebnis.serie,
        "ueberschrift": ergebnis.ueberschrift,
        "gelesen": len(ergebnis.eintraege),
        "neu": neu,
        "geaendert": geaendert,
        "geschuetzt": geschuetzt,
        "entfallen": entfallen,
        "zurueck": zurueck,
        "probleme": ergebnis.probleme,
        "hinweise": ergebnis.hinweise,
    }
    db.abruf_vermerken(ergebnis.serie, True, "", bericht_als_text(bericht),
                       ausloeser)
    return bericht


def bericht_als_text(bericht: dict) -> str:
    zeilen = [str(bericht["gelesen"]) + " Zeilen unter " +
              repr(bericht["ueberschrift"])]
    for titel, schluessel in (("neu", "neu"), ("geändert", "geaendert"),
                              ("nicht überschrieben", "geschuetzt"),
                              ("entfallen", "entfallen"),
                              ("wieder da", "zurueck"),
                              ("Problem", "probleme"),
                              ("Hinweis", "hinweise")):
        for eintrag in bericht[schluessel]:
            zeilen.append(titel + ": " + eintrag)
    return "\n".join(zeilen)


def unveraendert(bericht: dict) -> bool:
    return not any(bericht[s] for s in
                   ("neu", "geaendert", "geschuetzt", "entfallen", "zurueck"))


def alle_abrufen(ausloeser: str = "") -> list[dict]:
    """Ruft jede eingerichtete Serie ab. Ein Fehler bei einer Serie hält die
    anderen nicht auf – er wird vermerkt und gemeldet."""
    from . import db

    berichte = []
    for eintrag in config.serien():
        try:
            ergebnis = abrufen(eintrag["schluessel"], eintrag["url"],
                               eintrag["abschnitt"])
            bericht = uebernehmen(ergebnis, ausloeser)
            bericht["titel"] = eintrag["titel"]
            bericht["fehler"] = ""
        except Fehler as fehler:
            db.abruf_vermerken(eintrag["schluessel"], False, str(fehler), "",
                               ausloeser)
            bericht = {"serie": eintrag["schluessel"], "titel": eintrag["titel"],
                       "fehler": str(fehler), "gelesen": 0, "neu": [],
                       "geaendert": [], "geschuetzt": [], "entfallen": [],
                       "zurueck": [], "probleme": [], "hinweise": [],
                       "ueberschrift": ""}
        berichte.append(bericht)
    return berichte
