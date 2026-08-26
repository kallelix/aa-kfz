"""Einlesen der beiden CSV-Dateien aus dem bisherigen Helfer-Registrierungstool.

Die Dateien heißen dort „Offene Posten" und „Vergebene Posten". Beide zählen
Plätze, nicht Schichten: eine Zeile ist ein Platz.

    Offene Posten:    Liste, Datum, Zeit, Aufgabe
    Vergebene Posten: Name, Zusatz1, Zusatz2, Liste, Datum, Zeit, Aufgabe,
                      Email, Phone

Daraus folgt, warum der Import IMMER beide Dateien zusammen braucht: eine voll
besetzte Schicht steht nur in „Vergebene", eine leere nur in „Offene". Der
Bedarf einer Schicht ist die Summe der Zeilen aus beiden Dateien, und nur wenn
beide vorliegen, ist er vollständig. Mit einer Datei allein würde stillschweigend
die halbe Wahrheit in die Datenbank geschrieben.

Der Import ist deshalb wiederholbar: er rechnet den Bedarf neu aus und ersetzt
alle Einteilungen mit quelle='import'. Von Hand Eingetragenes bleibt stehen.
"""

from __future__ import annotations

import csv
import http.cookiejar
import io
import urllib.error
import urllib.request
from collections import Counter, defaultdict

from . import config, db, normalisieren

SPALTEN_OFFEN = ("Liste", "Datum", "Zeit")
SPALTEN_VERGEBEN = ("Name", "Liste", "Datum", "Zeit")


class Fehler(Exception):
    """Die Datei ist so nicht verwendbar – nichts wird geschrieben."""


def _text_lesen(rohdaten: bytes) -> str:
    """UTF-8, notfalls cp1252. Das alte Tool liefert UTF-8 ohne BOM, aber
    einmal durch Excel gedreht kann beides herauskommen."""
    for kodierung in ("utf-8-sig", "cp1252"):
        try:
            return rohdaten.decode(kodierung)
        except UnicodeDecodeError:
            continue
    return rohdaten.decode("utf-8", errors="replace")


def _zeilen(rohdaten: bytes, pflichtspalten: tuple[str, ...],
            bezeichnung: str) -> list[dict]:
    text = _text_lesen(rohdaten)
    if not text.strip():
        raise Fehler(bezeichnung + ": die Datei ist leer.")

    kopf = text.splitlines()[0]
    trenner = ";" if kopf.count(";") > kopf.count(",") else ","

    leser = csv.DictReader(io.StringIO(text, newline=""), delimiter=trenner)
    vorhanden = {(name or "").strip() for name in (leser.fieldnames or [])}
    fehlend = [s for s in pflichtspalten if s not in vorhanden]
    if fehlend:
        raise Fehler(
            bezeichnung + ": es fehlen die Spalten " + ", ".join(fehlend) +
            ". Gefunden wurden: " + (", ".join(sorted(vorhanden)) or "keine") + ".")

    return [{(k or "").strip(): v for k, v in zeile.items()} for zeile in leser]


def _schicht_schluessel(zeile: dict, nummer: int,
                        probleme: list[str], bezeichnung: str):
    liste = normalisieren.text(zeile.get("Liste"))
    if not liste:
        probleme.append(bezeichnung + ", Zeile " + str(nummer) +
                        ": ohne Liste – übersprungen.")
        return None
    zeit = normalisieren.zeitspanne(zeile.get("Datum"), zeile.get("Zeit"))
    if zeit is None:
        probleme.append(
            bezeichnung + ", Zeile " + str(nummer) + ": Datum oder Zeit nicht "
            "lesbar (" + repr(normalisieren.text(zeile.get("Datum"))) + " / " +
            repr(normalisieren.text(zeile.get("Zeit"))) + ") – übersprungen.")
        return None
    beginn, ende, datum = zeit
    return liste, beginn, ende, datum


def pruefen(offen_roh: bytes, vergeben_roh: bytes) -> dict:
    """Liest beide Dateien und rechnet aus, was der Import täte – ohne zu
    schreiben. Ergebnis füttert sowohl die Vorschau als auch den Import."""
    probleme: list[str] = []
    hinweise: list[str] = []

    offen = _zeilen(offen_roh, SPALTEN_OFFEN, "Offene Posten")
    vergeben = _zeilen(vergeben_roh, SPALTEN_VERGEBEN, "Vergebene Posten")

    # --- Bedarf: jede Zeile aus beiden Dateien ist ein Platz ---------------
    bedarf: Counter = Counter()
    tage: dict[tuple, str] = {}

    for nummer, zeile in enumerate(offen, start=2):
        treffer = _schicht_schluessel(zeile, nummer, probleme, "Offene Posten")
        if treffer:
            liste, beginn, ende, datum = treffer
            bedarf[(liste, beginn, ende)] += 1
            tage[(liste, beginn, ende)] = datum

    # --- Besetzung ---------------------------------------------------------
    einteilungen: list[dict] = []
    personen: dict[str, dict] = {}

    for nummer, zeile in enumerate(vergeben, start=2):
        treffer = _schicht_schluessel(zeile, nummer, probleme, "Vergebene Posten")
        if not treffer:
            continue
        liste, beginn, ende, datum = treffer
        bedarf[(liste, beginn, ende)] += 1
        tage[(liste, beginn, ende)] = datum

        name = normalisieren.text(zeile.get("Name"))
        email = normalisieren.text(zeile.get("Email"))
        if not name:
            probleme.append("Vergebene Posten, Zeile " + str(nummer) +
                            ": ohne Namen – Platz zählt zum Bedarf, bleibt "
                            "aber unbesetzt.")
            continue

        veggie_wert, veggie_klar = normalisieren.veggie(zeile.get("Zusatz1"))
        groesse_roh = normalisieren.text(zeile.get("Zusatz2"))
        if not veggie_klar:
            roh = normalisieren.text(zeile.get("Zusatz1"))
            ersatz, klar = normalisieren.tshirt(roh)
            if ersatz and klar and not groesse_roh:
                groesse_roh = roh
                hinweise.append(
                    name + ": in der Verpflegungsspalte stand " + repr(roh) +
                    " – als T-Shirt-Größe übernommen, Verpflegung offen.")
            else:
                hinweise.append(
                    name + ": Verpflegung " + repr(roh) +
                    " nicht verstanden – bleibt offen.")

        groesse, groesse_klar = normalisieren.tshirt(groesse_roh)
        if groesse_roh and not groesse_klar:
            hinweise.append(
                name + ": T-Shirt-Größe " + repr(groesse_roh) +
                " nicht eindeutig – Rohwert bleibt stehen, Größe offen.")

        schluessel = normalisieren.schluessel(name, email)
        person = personen.setdefault(schluessel, {
            "name": name, "email": email, "telefon": "",
            "veggie": None, "tshirt": None, "tshirt_roh": "",
        })
        telefon = normalisieren.text(zeile.get("Phone"))
        if telefon and not person["telefon"]:
            person["telefon"] = telefon
        if veggie_wert is not None and person["veggie"] is None:
            person["veggie"] = veggie_wert
        if groesse and person["tshirt"] is None:
            person["tshirt"] = groesse
        if groesse_roh and not person["tshirt_roh"]:
            person["tshirt_roh"] = groesse_roh

        einteilungen.append({"schluessel": schluessel,
                             "schicht": (liste, beginn, ende)})

    # --- Auffälligkeiten, die die Orga sehen muss --------------------------
    mehrfach = Counter((e["schluessel"], e["schicht"]) for e in einteilungen)
    for (schluessel, schicht), anzahl in sorted(mehrfach.items()):
        if anzahl > 1:
            hinweise.append(
                personen[schluessel]["name"] + " belegt " + str(anzahl) +
                " Plätze derselben Schicht (" + schicht[0] + ", " +
                schicht[1] + "). Sammeleintrag oder Doppelanmeldung – bleibt "
                "so stehen, bitte prüfen.")

    namen_je_adresse = defaultdict(set)
    for person in personen.values():
        if person["email"]:
            namen_je_adresse[person["email"].casefold()].add(person["name"])
    for adresse, namen in sorted(namen_je_adresse.items()):
        if len(namen) > 1:
            hinweise.append(
                str(len(namen)) + " Namen unter " + adresse +
                " – als eigene Personen angelegt: " +
                ", ".join(sorted(namen)) + ".")

    return {
        "bedarf": dict(bedarf),
        "tage": tage,
        "personen": personen,
        "einteilungen": einteilungen,
        "probleme": probleme,
        "hinweise": hinweise,
        "zeilen_offen": len(offen),
        "zeilen_vergeben": len(vergeben),
    }


def importieren(offen_roh: bytes, vergeben_roh: bytes,
                dateinamen: str = "", kuerzel: str = "") -> dict:
    """Führt den Import in einer Transaktion aus und gibt den Bericht zurück."""
    ergebnis = pruefen(offen_roh, vergeben_roh)

    neue_schichten = 0
    neue_personen = 0
    verschwunden: list[str] = []

    con = db.verbinden()
    try:
        with con:
            # Alles aus früheren Läufen weg – der Bedarf wird gleich neu
            # gesetzt, und ohne das Löschen stünden abgemeldete Helfer für
            # immer auf ihrer Schicht.
            entfernt = con.execute(
                "DELETE FROM einteilung WHERE quelle = 'import'").rowcount

            schicht_ids: dict[tuple, int] = {}
            for schluessel, anzahl in ergebnis["bedarf"].items():
                liste, beginn, ende = schluessel
                schicht_id, neu = db.schicht_sichern(
                    con, liste, beginn, ende, ergebnis["tage"][schluessel],
                    bedarf=anzahl)
                schicht_ids[schluessel] = schicht_id
                neue_schichten += 1 if neu else 0

            # Schichten, die es in der Datenbank gibt, aber nicht mehr in den
            # Dateien. Nicht anfassen: dort können Einteilungen von Hand
            # hängen. Nur melden.
            for zeile in con.execute(
                    "SELECT id, liste, beginn, ende FROM schicht"):
                merkmal = (zeile["liste"], zeile["beginn"], zeile["ende"])
                if merkmal not in ergebnis["bedarf"]:
                    verschwunden.append(
                        zeile["liste"] + " am " + zeile["beginn"] +
                        " steht nicht mehr in den Dateien – unverändert "
                        "gelassen.")

            personen_ids: dict[str, int] = {}
            for schluessel, person in ergebnis["personen"].items():
                helfer_id, neu = db.helfer_anlegen(con, person)
                personen_ids[schluessel] = helfer_id
                neue_personen += 1 if neu else 0

            for eintrag in ergebnis["einteilungen"]:
                db.einteilen(schicht_ids[eintrag["schicht"]],
                             personen_ids[eintrag["schluessel"]],
                             quelle="import", kuerzel=kuerzel, con=con)
    finally:
        con.close()

    bericht = {
        "zeilen_offen": ergebnis["zeilen_offen"],
        "zeilen_vergeben": ergebnis["zeilen_vergeben"],
        "schichten": len(ergebnis["bedarf"]),
        "schichten_neu": neue_schichten,
        "bedarf": sum(ergebnis["bedarf"].values()),
        "personen": len(ergebnis["personen"]),
        "personen_neu": neue_personen,
        "einteilungen": len(ergebnis["einteilungen"]),
        "ersetzt": entfernt,
        "probleme": ergebnis["probleme"],
        "hinweise": ergebnis["hinweise"] + verschwunden,
    }

    db.import_vermerken(
        "schichten", dateinamen,
        bericht["zeilen_offen"] + bericht["zeilen_vergeben"],
        bericht_als_text(bericht), kuerzel)
    return bericht


def bericht_als_text(bericht: dict) -> str:
    zeilen = [
        "%d Zeilen offen, %d Zeilen vergeben" % (
            bericht["zeilen_offen"], bericht["zeilen_vergeben"]),
        "%d Schichten (%d neu), Bedarf %d Plätze" % (
            bericht["schichten"], bericht["schichten_neu"], bericht["bedarf"]),
        "%d Helfer (%d neu), %d Einteilungen (%d ersetzt)" % (
            bericht["personen"], bericht["personen_neu"],
            bericht["einteilungen"], bericht["ersetzt"]),
    ]
    for art, eintraege in (("Problem", bericht["probleme"]),
                           ("Hinweis", bericht["hinweise"])):
        for eintrag in eintraege:
            zeilen.append(art + ": " + eintrag)
    return "\n".join(zeilen)


# --- Abruf statt Hochladen --------------------------------------------------

# Die drei Adressen in der Konfiguration enthalten persoenliche Zugangstoken.
# Deshalb steht hier nirgends eine Adresse in einer Meldung, in einem
# Protokoll oder im Importvermerk - eine Fehlermeldung wandert schnell in
# einen Chat, und der Token gaebe die ganze Helferliste preis. Gemeldet wird
# nur, WELCHE der drei nicht ging, nie wie sie lautet.

ABRUF_ZEITSPERRE = 30
ABRUF_MAX_BYTES = 10 * 1024 * 1024

# Was im Importvermerk steht. Die Datei heisst beim Dienst
# "statistik_<token>.csv" - dieser Name darf nirgends hin.
ABRUF_NAME = "Helferliste (Abruf)"


def _oeffner():
    """Ein eigener Keksbehaelter je Abruf. Die Sitzung soll nicht laenger
    leben als der Vorgang und sich nicht mit einem zweiten mischen."""
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def _seite_holen(oeffner, url: str, bezeichnung: str) -> tuple[bytes, str]:
    if not url.lower().startswith("https://"):
        raise Fehler(bezeichnung + ": nur https ist erlaubt.")

    anfrage = urllib.request.Request(url, headers={
        "User-Agent": "Abfahrt-Helferdashboard/1.0 (+Vereinsintern)",
        "Accept": "text/csv,text/html;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9",
    })
    try:
        with oeffner.open(anfrage, timeout=ABRUF_ZEITSPERRE) as antwort:
            # Auch nach einer Weiterleitung darf es nichts anderes als https
            # sein, sonst liesse sich der Abruf samt Sitzungskeks umlenken.
            if not antwort.geturl().lower().startswith("https://"):
                raise Fehler(bezeichnung + ": die Adresse leitet auf etwas "
                             "anderes als https um.")
            rohdaten = antwort.read(ABRUF_MAX_BYTES + 1)
            if len(rohdaten) > ABRUF_MAX_BYTES:
                raise Fehler(bezeichnung + ": die Antwort ist größer als "
                             + str(ABRUF_MAX_BYTES // 1024 // 1024) + " MB.")
            typ = (antwort.headers.get_content_type() or "").lower()
    except urllib.error.HTTPError as fehler:
        raise Fehler(bezeichnung + ": der Dienst antwortet mit HTTP "
                     + str(fehler.code) + ".") from fehler
    except urllib.error.URLError as fehler:
        raise Fehler(bezeichnung + ": nicht erreichbar – "
                     + str(fehler.reason) + ".") from fehler
    except TimeoutError as fehler:
        raise Fehler(bezeichnung + ": keine Antwort binnen "
                     + str(ABRUF_ZEITSPERRE) + " Sekunden.") from fehler
    return rohdaten, typ


def _csv_holen(oeffner, url: str, bezeichnung: str) -> bytes:
    rohdaten, typ = _seite_holen(oeffner, url, bezeichnung)
    # Ohne gueltige Sitzung antwortet der Dienst mit HTTP 200 und der
    # Anmeldeseite statt der Datei. Das faellt sonst erst beim Einlesen auf,
    # und zwar als "Spalte Datum fehlt" - eine Meldung, mit der niemand
    # etwas anfangen kann.
    if typ.startswith("text/html") or rohdaten.lstrip()[:9].lower() == b"<!doctype":
        raise Fehler(bezeichnung + ": der Dienst schickt eine Webseite statt "
                     "einer CSV-Datei. Meist ist der Login-Link abgelaufen – "
                     "einen neuen anfordern und in der Konfiguration "
                     "eintragen.")
    return rohdaten


# Ein selbsttaetiger Lauf uebernimmt hoechstens diesen Schwund gegenueber dem
# letzten geglueckten. Darunter bricht er ab, statt zu schreiben.
ABRUF_MINDESTANTEIL = 0.5


def _plausibel(zeilen_neu: int, bezeichnung: str = "") -> None:
    """Wirft, wenn der Abruf zu wenig geliefert hat, um ihn ungesehen zu
    uebernehmen.

    Der Grund: eine Ausfuhr mit nur Kopfzeilen ist technisch tadellos. Sie
    laeuft ohne Fehler durch, setzt den Bedarf jeder Schicht auf null und
    loescht alle Einteilungen aus dem Import. Wer den Knopf drueckt, sieht
    "0 Zeilen" im Bericht und stutzt; einem Lauf um vier Uhr morgens sieht
    niemand zu.
    """
    if zeilen_neu <= 0:
        raise Fehler("Der Abruf hat keine einzige Zeile geliefert. "
                     "Übernommen wird das nicht – im Backoffice von Hand "
                     "nachsehen.")

    vorher = db.letzter_import()
    if vorher is None or not vorher["zeilen"]:
        return
    if zeilen_neu < vorher["zeilen"] * ABRUF_MINDESTANTEIL:
        raise Fehler(
            "Der Abruf hat %d Zeilen geliefert, zuletzt waren es %d. "
            "So viel weniger wird nicht ungesehen übernommen – im "
            "Backoffice von Hand nachsehen und dort abrufen."
            % (zeilen_neu, vorher["zeilen"]))


def abrufen(kuerzel: str = "", automatisch: bool = False) -> dict:
    """Holt beide Listen beim Dienst und importiert sie wie hochgeladene.

    automatisch=True fuegt die Plausibilitaetspruefung hinzu und vermerkt
    auch das Scheitern. Von Hand bleibt es dabei, dass der Bericht auf dem
    Bildschirm die Pruefung ist - wer hinschaut, darf auch einen Bestand mit
    drei Zeilen uebernehmen.
    """
    if not config.IMPORT_ABRUF_MOEGLICH:
        raise Fehler("Für den Abruf fehlen die Adressen in der "
                     "Konfiguration (IMPORT_LOGIN_URL, IMPORT_URL_VERGEBEN, "
                     "IMPORT_URL_OFFEN).")

    try:
        oeffner = _oeffner()
        # Erst anmelden: die Sitzung steckt danach im Keksbehaelter des
        # Oeffners.
        _seite_holen(oeffner, config.IMPORT_LOGIN_URL, "Anmeldung")
        vergeben = _csv_holen(oeffner, config.IMPORT_URL_VERGEBEN,
                              "Vergebene Posten")
        offen = _csv_holen(oeffner, config.IMPORT_URL_OFFEN, "Offene Posten")

        if automatisch:
            vorschau = pruefen(offen, vergeben)
            _plausibel(vorschau["zeilen_offen"] + vorschau["zeilen_vergeben"])

        return importieren(offen, vergeben, ABRUF_NAME, kuerzel)
    except Fehler as fehler:
        if automatisch:
            # Ein Lauf, dem niemand zusieht, muss sein Scheitern hinterlassen -
            # sonst steht im Backoffice nur ein alter geglueckter Lauf und
            # nichts sagt, dass seither nichts mehr ankommt.
            db.import_vermerken("schichten", ABRUF_NAME, 0, str(fehler),
                                kuerzel, erfolg=False)
        raise
