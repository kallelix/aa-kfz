"""Die öffentliche Anmeldung (Lastenheft 2.2): Prüfen der Angaben.

Ohne Datenbank und ohne Web, wie planung.py. Was hier steht, gilt für die
Person, die sich anmeldet, und für jede, die sie mitanmeldet (A-08). Ob noch
Platz ist und ob sich etwas mit schon gebuchten Schichten überschneidet, weiß
erst die Datenbank – das prüft db.anmelden() unter Sperre.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import date, datetime, timedelta

from . import normalisieren

# D-06: wer jünger ist, hilft noch nicht mit.
MINDESTALTER = 12

# Springer-Zeiten (R-05) in drei Fenstern je Tag, wie im Prototyp. Sie
# überlappen bewusst: wer „Nachmittag“ sagt, ist um 12 meist schon da.
TAGESZEITEN = (
    ("frueh", "Vormittag", "bis 13 Uhr", "06:00", "13:00"),
    ("mittag", "Nachmittag", "12 bis 18 Uhr", "12:00", "18:00"),
    ("abend", "Abend", "ab 17 Uhr", "17:00", "24:00"),
)

# Der Assistent (A-03): was einem liegt. Die Orga hakt je Bereich an, wozu
# er passt (bereich.vorlieben); die Person wählt hier. Schlüssel, Name, und
# was darunter fällt.
VORLIEBEN = (
    ("strecke", "Draußen an der Strecke", "Posten, Sperren, Ordner – an der frischen Luft"),
    ("menschen", "Mit Menschen", "Einlass, Stand, Fragen beantworten"),
    ("anpacken", "Anpacken", "Aufbauen, tragen, abbauen"),
    ("fahren", "Fahren", "Shuttle und Transporte – mit Führerschein"),
)
# A-05: setzt mich ein, wo es brennt. Passt zu allem und legt den Springer
# nahe.
EGAL = "egal"

# A-04: so viel einer Schicht muss in den angetippten Zeiten liegen.
ANTEIL = 0.75

# Für die Vorschläge reicht der Abend bis drei Uhr: eine Nachtschicht gehört
# zum Abend ihres ersten Tages. Als Springer-Zeit endet er um Mitternacht.
ABEND_BIS = "03:00"

VERPFLEGUNG = {"fleisch": "mit Fleisch", "vegetarisch": "vegetarisch"}
SCHNITTE = {"damen": "Damen", "herren": "Herren"}
KEIN_SHIRT = "kein"

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


MONATE = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember")


def tage_text(v) -> str:
    """'1. bis 4. Juli 2027' – oder ein einzelner Tag. Für Seiten und Mails."""
    beginn, ende = v["beginn"], v["ende"]
    if beginn == ende:
        return f"{beginn.day}. {MONATE[beginn.month - 1]} {beginn.year}"
    if (beginn.month, beginn.year) == (ende.month, ende.year):
        return f"{beginn.day}. bis {ende.day}. {MONATE[ende.month - 1]} {ende.year}"
    return (f"{beginn.day}. {MONATE[beginn.month - 1]} bis "
            f"{ende.day}. {MONATE[ende.month - 1]} {ende.year}")


def va_text(v) -> str:
    """'Die absolute Abfahrt 2027 (1. bis 4. Juli 2027)' – für Mails."""
    return f"{v['name']} ({tage_text(v)})"


def alter_am(geburtsdatum: date, stichtag: date) -> int:
    jahre = stichtag.year - geburtsdatum.year
    if (stichtag.month, stichtag.day) < (geburtsdatum.month, geburtsdatum.day):
        jahre -= 1
    return jahre


def person_pruefen(daten: dict, praefix: str, angebot: dict, stichtag: date,
                   mit_kontakt: bool) -> tuple[dict, dict]:
    """Die Angaben einer Person aus dem Formular. Felder heißen
    `<praefix>vorname` usw.; die Fehler tragen dieselben Schlüssel.

    `mit_kontakt`: die anmeldende Person, mit Mail und Handy. Wer
    mitangemeldet wird, braucht beides nicht – Ansprechpartner bleibt, wer
    anmeldet.
    """
    fehler: dict[str, str] = {}

    def feld(name: str) -> str:
        return normalisieren.text(daten.get(praefix + name))

    vorname, nachname = feld("vorname")[:60], feld("nachname")[:60]
    if not vorname:
        fehler[praefix + "vorname"] = "Bitte den Vornamen."
    if not nachname:
        fehler[praefix + "nachname"] = "Bitte den Nachnamen."

    email = telefon = ""
    if mit_kontakt:
        email = feld("email").lower()[:120]
        if not _EMAIL.match(email):
            fehler[praefix + "email"] = ("Bitte deine Mailadresse – an sie geht die Bestätigung."
                                         if not email else "Diese Mailadresse sieht nicht vollständig aus.")
        telefon = normalisieren.telefon(feld("telefon"))
        if telefon is None:
            fehler[praefix + "telefon"] = "Diese Nummer können wir nicht lesen."
            telefon = ""

    volljaehrig = {"ja": 1, "nein": 0}.get(feld("volljaehrig"))
    geburtsdatum, alter = None, None
    if volljaehrig is None:
        fehler[praefix + "volljaehrig"] = "Bitte angeben."
    elif volljaehrig == 0:
        tag = normalisieren.datum(feld("geburtsdatum"))
        if tag is None:
            fehler[praefix + "geburtsdatum"] = "Bitte das Geburtsdatum."
        else:
            alter = alter_am(tag, stichtag)
            geburtsdatum = tag.isoformat()
            if alter < MINDESTALTER:
                fehler[praefix + "geburtsdatum"] = (
                    f"Mithelfen geht ab {MINDESTALTER} Jahren – schön, dass du "
                    "Lust hast! Bis dahin gern mit deinen Eltern zum Zuschauen.")
            elif alter >= 18:
                volljaehrig = 1

    # D-06: unter 18 eine erziehungsberechtigte Person, die per Mail
    # bestätigt. Wer selbst erziehungsberechtigt ist und mitanmeldet, trägt
    # sich hier ein – dann zählt die eigene Bestätigung.
    eltern_name = eltern_email = ""
    if volljaehrig == 0 and alter is not None and MINDESTALTER <= alter < 18:
        eltern_name = feld("eltern_name")[:120]
        eltern_email = feld("eltern_email").lower()[:120]
        if not eltern_name:
            fehler[praefix + "eltern_name"] = "Unter 18 brauchen wir eine erziehungsberechtigte Person."
        if not _EMAIL.match(eltern_email):
            fehler[praefix + "eltern_email"] = (
                "An diese Adresse geht die Bitte um Einverständnis." if not eltern_email
                else "Diese Mailadresse sieht nicht vollständig aus.")
        elif mit_kontakt and eltern_email == email:
            fehler[praefix + "eltern_email"] = "Bitte die Adresse deiner Eltern – nicht deine eigene."

    shirt_essen = _shirt_essen(feld, praefix, angebot, fehler)
    werte = {
        "vorname": vorname, "nachname": nachname,
        "name": (vorname + " " + nachname).strip(),
        "email": email, "telefon": telefon,
        "volljaehrig": volljaehrig, "geburtsdatum": geburtsdatum, "alter": alter,
        "eltern_name": eltern_name, "eltern_email": eltern_email,
        "tshirt": None, "tshirt_roh": "", "veggie": None, **shirt_essen,
    }
    return werte, fehler


def _shirt_essen(feld, praefix: str, angebot: dict, fehler: dict) -> dict:
    """Shirt (mit Schnitt) und Verpflegung – nur, was die Veranstaltung
    anbietet (I-02). Zurück kommen nur die Felder, nach denen gefragt war."""
    werte: dict = {}
    if angebot.get("shirt"):
        groesse = feld("tshirt")
        schnitt = feld("schnitt")
        if groesse == KEIN_SHIRT:
            werte.update(tshirt=None, tshirt_roh="kein Shirt")
        elif groesse not in normalisieren.GROESSEN:
            fehler[praefix + "tshirt"] = "Bitte eine Größe wählen – oder „kein Shirt“."
        elif angebot.get("schnitte") and schnitt not in SCHNITTE:
            fehler[praefix + "schnitt"] = "Bitte Damen- oder Herrenschnitt."
        else:
            werte.update(tshirt=groesse, tshirt_roh=(SCHNITTE[schnitt] + " " + groesse)
                         if angebot.get("schnitte") else groesse)
    if angebot.get("verpflegung"):
        essen = feld("verpflegung")
        if essen not in VERPFLEGUNG:
            fehler[praefix + "verpflegung"] = "Bitte wählen, damit genug von allem da ist."
        else:
            werte["veggie"] = 1 if essen == "vegetarisch" else 0
    return werte


def angaben_pruefen(daten: dict, praefix: str, angebot: dict,
                    mit_telefon: bool) -> tuple[dict, dict]:
    """Angaben ändern aus Mein Helferplatz (S-04): Telefon, Shirt,
    Verpflegung. Name und Alter ändert hier niemand."""
    fehler: dict[str, str] = {}

    def feld(name: str) -> str:
        return normalisieren.text(daten.get(praefix + name))

    werte = _shirt_essen(feld, praefix, angebot, fehler)
    if mit_telefon:
        telefon = normalisieren.telefon(feld("telefon"))
        if telefon is None:
            fehler[praefix + "telefon"] = "Diese Nummer können wir nicht lesen."
        else:
            werte["telefon"] = telefon
    return werte, fehler


def vorbelegen(person, praefix: str) -> dict:
    """Die Formularfelder aus dem, was gespeichert ist – Umkehrung von
    angaben_pruefen."""
    werte = {praefix + "telefon": person["telefon"] or ""}
    roh = person["tshirt_roh"] or ""
    if roh == "kein Shirt":
        werte[praefix + "tshirt"] = KEIN_SHIRT
    elif person["tshirt"]:
        werte[praefix + "tshirt"] = person["tshirt"]
        for wert, name in SCHNITTE.items():
            if roh.startswith(name + " "):
                werte[praefix + "schnitt"] = wert
    if person["veggie"] is not None:
        werte[praefix + "verpflegung"] = "vegetarisch" if person["veggie"] else "fleisch"
    return werte


def springer_fenster(roh_werte, tage: list[date]) -> list[tuple[str, str, str]]:
    """Gewählte Springer-Zeiten als (Schlüssel, Beginn, Ende). Ein Schlüssel
    ist 'YYYY-MM-DD|frueh'. Was nicht zu einem Tag der Veranstaltung passt,
    fällt weg – das kann nur ein gebastelter Link sein."""
    erlaubt = {t.isoformat() for t in tage}
    zeiten = {k: (von, bis) for k, _, _, von, bis in TAGESZEITEN}
    fenster = []
    for roh in roh_werte:
        tag, _, zeit = str(roh).partition("|")
        if tag not in erlaubt or zeit not in zeiten:
            continue
        von, bis = zeiten[zeit]
        beginn = tag + " " + von
        if bis == "24:00":
            ende = (date.fromisoformat(tag) + timedelta(days=1)).isoformat() + " 00:00"
        else:
            ende = tag + " " + bis
        fenster.append((tag + "|" + zeit, beginn, ende))
    return sorted(set(fenster), key=lambda f: f[1])


def vorlieben_aus(roh_werte) -> list[str]:
    """Die gewählten Vorlieben, in fester Reihenfolge – Unbekanntes fällt
    weg."""
    gewaehlt = {str(r) for r in roh_werte}
    return [k for k in [k for k, *_ in VORLIEBEN] + [EGAL] if k in gewaehlt]


def zeitspannen(roh_werte, tage: list[date]) -> list[tuple[str, str]]:
    """Die angetippten Tageszeiten (A-02) als zusammenhängende Spannen:
    überlappende verschmolzen, nach Beginn sortiert."""
    spannen = []
    for schluessel, beginn, ende in springer_fenster(roh_werte, tage):
        if schluessel.endswith("|abend"):
            ende = ende[:11] + ABEND_BIS
        spannen.append((beginn, ende))
    vereint: list[tuple[str, str]] = []
    for von, bis in sorted(spannen):
        if vereint and von <= vereint[-1][1]:
            vereint[-1] = (vereint[-1][0], max(vereint[-1][1], bis))
        else:
            vereint.append((von, bis))
    return vereint


def _minuten(von: str, bis: str) -> float:
    return (datetime.fromisoformat(bis) - datetime.fromisoformat(von)).total_seconds() / 60


def passt_zur_zeit(beginn: str, ende: str, spannen: list[tuple[str, str]]) -> bool:
    """Mindestens drei Viertel der Schicht liegen in den angetippten Zeiten
    (A-04). Die Tageszeiten überlappen, damit eine Schicht von 8 bis 14 Uhr
    auch zu „Vormittag“ allein passt."""
    dauer = _minuten(beginn, ende)
    drin = sum(_minuten(max(von, beginn), min(bis, ende))
               for von, bis in spannen if von < ende and beginn < bis)
    return dauer > 0 and drin >= ANTEIL * dauer


def passt_zu_vorlieben(bereich: list[str], gewaehlt: list[str]) -> bool:
    """Ohne Wahl, mit „egal“ oder bei einem Bereich ohne Haken passt alles."""
    if not gewaehlt or EGAL in gewaehlt or not bereich:
        return True
    return bool(set(bereich) & set(gewaehlt))


def vorschlaege(schichten: list[dict], spannen: list[tuple[str, str]],
                vorlieben: list[str]) -> list[dict]:
    """A-04: was in die Zeit passt und zu den Vorlieben, ohne volle – die
    dringendsten zuerst: unter Minimum, dann unter Soll, dann als Reserve;
    gleich dringende nach Beginn."""
    def rang(s):
        return 0 if s["dringend"] else 1 if s["lage"] == "frei" else 2
    passend = [s for s in schichten
               if s["lage"] != "voll"
               and passt_zur_zeit(s["beginn"], s["ende"], spannen)
               and passt_zu_vorlieben(s.get("vorlieben") or [], vorlieben)]
    return sorted(passend, key=lambda s: (rang(s), s["beginn"]))


def ueberschneiden(a_beginn: str, a_ende: str, b_beginn: str, b_ende: str) -> bool:
    """Zeitstempel als 'YYYY-MM-DD HH:MM' – sie sortieren richtig."""
    return a_beginn < b_ende and b_beginn < a_ende


def ueberschneidungen(zeiten: list[tuple[str, str, str]]) -> list[tuple[str, str]]:
    """Paare von Bezeichnungen, deren Zeiten sich überschneiden (K-01)."""
    paare = []
    for i, (a, a_von, a_bis) in enumerate(zeiten):
        for b, b_von, b_bis in zeiten[i + 1:]:
            if ueberschneiden(a_von, a_bis, b_von, b_bis):
                paare.append((a, b))
    return paare


# --- Der Link auf die Dankeseite -------------------------------------------

def zeichen(geheimnis: str, *teile) -> str:
    """Ein kurzes Siegel, damit niemand durch Hochzählen fremde Dankeseiten
    sieht – dort stehen Namen und Schichten."""
    nachricht = "|".join(str(t) for t in teile).encode("utf-8")
    return hmac.new(geheimnis.encode("utf-8"), nachricht, hashlib.sha256).hexdigest()[:24]


def zeichen_stimmt(geheimnis: str, gegeben: str, *teile) -> bool:
    return hmac.compare_digest(zeichen(geheimnis, *teile), gegeben or "")
