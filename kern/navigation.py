"""Die Navigation des Backoffice (Lastenheft 2.1b).

Seit die drei Anwendungen ein Dienst sind, liegt ihr Backoffice unter einer
Adresse. Damit ist es auch eine Oberfläche, gegliedert in drei Ebenen:

    Reiter    Kennzeichen · Presse · Helfer · Ausgabe · Verwaltung
    Gruppen   je Reiter nach dem Ablauf, im Helferbereich etwa
              Übersicht · Planen · Leute · Vor Ort
    Punkte    die Seiten der offenen Gruppe

Über allem steht die Veranstaltung, die man im Kopf wählt. Sie legt fest,
welche Reiter es gibt (V-08): was sie nicht nutzt, erscheint nicht.

Die Reiter folgen nicht ganz den Anwendungen. Funk und Schlüssel liegen
technisch im Helferbereich, stehen aber unter „Ausgabe“; Goodies, Import und
Zeitplan-Abruf ebenso, stehen aber unter „Verwaltung“ bei der Veranstaltung.
Die Adressen bleiben, wie sie sind – nur die Navigation ordnet sie ein.
"""

from __future__ import annotations

from kern import veranstaltungen as va

# (Schlüssel, Beschriftung, Ziel). Bei Kennzeichen, Presse und Helfer ist
# der Schlüssel zugleich das erste Pfadstück – daran erkennt der Verteiler
# in dienst/main.py die Anwendung.
REITER = (
    ("kennzeichen", "Kennzeichen", "/kennzeichen"),
    ("presse", "Presse", "/presse"),
    ("helfer", "Helfer", "/helfer"),
    ("ausgabe", "Ausgabe", "/helfer/funk"),
    ("verwaltung", "Verwaltung", "/veranstaltungen"),
)

# Seiten, die unter einem anderen Reiter stehen als dem ihrer Anwendung.
UMGEHAENGT = (
    ("/helfer/funk", "ausgabe"), ("/helfer/ausleihe", "ausgabe"),
    ("/helfer/schluessel", "ausgabe"), ("/helfer/fahrzeug", "ausgabe"),
    ("/helfer/goodies", "verwaltung"), ("/helfer/goodie", "verwaltung"),
    ("/helfer/import", "verwaltung"), ("/helfer/zeitplan", "verwaltung"),
    ("/helfer/programm", "verwaltung"), ("/helfer/einstellungen", "verwaltung"),
    ("/helfer/unterschriften", "verwaltung"),
    ("/veranstaltungen", "verwaltung"), ("/konten", "verwaltung"),
)


def _passt(pfad: str, anfang: str) -> bool:
    return pfad == anfang or pfad.startswith(anfang + "/")


def reiter_von(pfad: str) -> str:
    """Unter welchem Reiter eine Seite steht – leer, wenn unter keinem."""
    for anfang, reiter in UMGEHAENGT:
        if _passt(pfad, anfang):
            return reiter
    erstes = pfad.strip("/").split("/")[0]
    return erstes if erstes in ("kennzeichen", "presse", "helfer") else ""


def punkte(eintraege, pfad: str) -> list:
    """Navigationspunkte mit dem der offenen Seite markiert.

    Ein Eintrag ist (Ziel, Name, weitere Pfade). Die weiteren Pfade sind
    nötig, weil Einzelansichten in der Einzahl heißen – /helfer/schicht/7
    gehört zu „Bereiche & Schichten“, fängt aber nicht mit /helfer/bereiche an.

    Es gewinnt der längste passende Pfadanfang. Ein blosses „fängt damit an“
    reichte nicht: /helfer ist der Anfang von allem im Helferbereich und wäre
    sonst auf jeder seiner Seiten hervorgehoben.
    """

    def treffer(eintrag) -> int:
        ziel, _, weitere = eintrag
        laenge = 0
        for anfang in (ziel,) + tuple(weitere):
            if _passt(pfad, anfang):
                laenge = max(laenge, len(anfang))
        return laenge

    eintraege = list(eintraege)
    laengster = max([treffer(e) for e in eintraege], default=0)
    gemacht = []
    for eintrag in eintraege:
        ziel, name, _ = eintrag
        eigen = treffer(eintrag)
        gemacht.append({"ziel": ziel, "name": name,
                        "hier": eigen > 0 and eigen == laengster,
                        # Eine Zahl neben dem Namen, etwa offene Anrufe.
                        # Wird nach dem Bauen gesetzt, nicht hier.
                        "marke": ""})
    return gemacht


def gegliedert(gruppen, pfad: str) -> dict:
    """Gruppen mit ihren Punkten, für die beiden unteren Zeilen.

    `gruppen` ist eine Liste aus (Name, Einträge wie bei punkte()). Zurück
    kommen `gruppen` für die mittlere Zeile und `bereichsnav` für die untere:
    die Punkte der offenen Gruppe. Eine Zeile mit nur einem Eintrag fällt
    weg – sie zeigte nur, was die Überschrift ohnehin sagt.
    """
    alle = [e for _, eintraege in gruppen for e in eintraege]
    markiert = punkte(alle, pfad)
    zeile, offen, anfang = [], None, 0
    for name, eintraege in gruppen:
        eigene = markiert[anfang:anfang + len(eintraege)]
        anfang += len(eintraege)
        hier = any(p["hier"] for p in eigene)
        zeile.append({"name": name, "ziel": eintraege[0][0], "hier": hier})
        if hier:
            offen = eigene
        elif len(gruppen) == 1:
            offen = eigene
    return {"gruppen": zeile if len(zeile) > 1 else [],
            "bereichsnav": offen if offen and len(offen) > 1 else []}


def verwaltung(sitzung, aktuell) -> list:
    """Die Gruppen des Reiters Verwaltung: die gewählte Veranstaltung mit
    allem, was man für sie einrichtet, alle Veranstaltungen, die Konten.

    Was zur Veranstaltung gehört, richtet sich nach dem, was sie nutzt: ohne
    Helfer keine Goodies, ohne Materialausgabe kein Material und kein Tablet.
    """
    if sitzung is None or sitzung.ist_bereichsleitung:
        return []
    gruppen = []
    helfer = sitzung.darf("helfer")
    if aktuell is not None and sitzung.pflegt_veranstaltungen:
        nutzt = aktuell.get("nutzt") or []
        eintraege = []
        # Die Stammdaten pflegt nur der gemeinsame Dienst.
        if sitzung.verwaltung:
            eintraege.append((f"/veranstaltungen/{aktuell['id']}", "Allgemein", ()))
        if "helfer" in nutzt and helfer:
            eintraege += [("/helfer/goodies", "Goodies & Verpflegung", ("/helfer/goodie",)),
                          ("/helfer/import", "Import", ()),
                          ("/helfer/zeitplan", "Zeitplan-Abruf", ("/helfer/programm",))]
        if "ausgabe" in nutzt and helfer:
            eintraege += [("/helfer/einstellungen", "Material", ()),
                          ("/helfer/unterschriften", "Tablet", ())]
        if eintraege:
            gruppen.append((aktuell["kurz"], eintraege))
    if sitzung.verwaltung and sitzung.pflegt_veranstaltungen:
        gruppen.append(("Alle Veranstaltungen",
                        [("/veranstaltungen", "Alle Veranstaltungen", ())]))
    if sitzung.verwaltung and sitzung.ist_admin:
        gruppen.append(("Konten", [("/konten", "Konten", ())]))
    return gruppen


def bereiche(pfad: str, sitzung=None, nutzt=None, verwaltung_ziel=None) -> list:
    """Die Reiter, die das Konto sehen darf und die Veranstaltung nutzt, der
    offene markiert. Ohne Sitzung alle; ohne `nutzt` keine Einschränkung
    durch die Veranstaltung; ohne `verwaltung_ziel` kein Reiter Verwaltung."""
    hier = reiter_von(pfad)
    liste = []
    for schluessel, name, ziel in REITER:
        if schluessel == "verwaltung":
            if not verwaltung_ziel:
                continue
            ziel = verwaltung_ziel
        else:
            # Die Ausgabe liegt im Helferbereich und gehört der Orga.
            anwendung = "helfer" if schluessel == "ausgabe" else schluessel
            if sitzung is not None and not sitzung.darf(anwendung):
                continue
            if schluessel == "ausgabe" and sitzung is not None and sitzung.ist_bereichsleitung:
                continue
            if nutzt is not None and schluessel not in nutzt:
                continue
        liste.append({"schluessel": schluessel, "name": name, "ziel": ziel,
                      "hier": schluessel == hier})
    return liste


def _weiter(pfad: str) -> str:
    """Wohin es nach dem Wechsel der Veranstaltung geht: zurück auf dieselbe
    Seite – außer auf eine Einzelansicht, die zur alten gehört. Dann auf die
    erste Seite des Reiters; bei einer Veranstaltung auf die neu gewählte
    (der Platzhalter {id} wird je Eintrag ersetzt)."""
    teile = pfad.strip("/").split("/")
    if not any(t.isdigit() for t in teile):
        return pfad
    if teile[0] == "veranstaltungen":
        return "/veranstaltungen/{id}"
    reiter = reiter_von(pfad)
    return dict((s, z) for s, _, z in REITER).get(reiter, "/")


def kopf(request, sitzung, veranstaltungen=None, aktuell=None, wahl=None) -> dict:
    """Was jede Seite des Backoffice für Kopf und Reiter braucht.

    `veranstaltungen` ist ein kern.veranstaltungen.Veranstaltungen; ohne ihn
    gibt es keine Auswahl. `aktuell` überschreibt die Wahl aus dem Keks – der
    Helferbereich geht nach seiner eigenen Uhr. `wahl` ist die Adresse, die
    eine Wahl entgegennimmt; im gemeinsamen Dienst /veranstaltung.
    """
    pfad = request.url.path
    auswahl = veranstaltungen.liste() if veranstaltungen is not None else []
    if aktuell is None and veranstaltungen is not None:
        aktuell = veranstaltungen.gewaehlt(request.cookies.get(va.KEKS, ""))
    gruppen = verwaltung(sitzung, aktuell)
    ziel = gruppen[0][1][0][0] if gruppen else None
    if wahl is None and sitzung is not None and sitzung.verwaltung:
        wahl = "/veranstaltung"
    return {
        "bereiche": bereiche(pfad, sitzung, nutzt=aktuell["nutzt"] if aktuell else None,
                             verwaltung_ziel=ziel),
        "va_aktuell": aktuell,
        "va_auswahl": auswahl,
        "va_wahl": wahl if auswahl else None,
        "va_weiter": _weiter(pfad),
        # Der kurze Weg aus der Auswahl in die Einrichtung der gewählten.
        "va_einrichten": ziel if aktuell and gruppen and gruppen[0][0] == aktuell["kurz"] else None,
    }
