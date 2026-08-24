"""Das Programm-Band: ein Tag als Zeitachse.

Oben die Programmpunkte der Rennserien als Balken, darunter die Schichten.
Damit sieht man auf einen Blick, was woran hängt – dass um 11:00 die Strecke
gesperrt wird und die Streckenposten deshalb ab 06:30 stehen.

Alles wird hier ausgerechnet und als Prozentwerte an die Vorlage gegeben. Im
Browser läuft dafür kein Skript: die Monitoransicht holt sich das Band beim
Auffrischen ohnehin neu, und was der Server schon weiß, muss er nicht zweimal
sagen.

Drei Dinge, die das Band von einer simplen Liste unterscheiden:

* **Offene Enden bleiben offen.** "ab 13.30 Uhr" bekommt keinen Balken mit
  erfundenem Ende, sondern einen, der nach rechts ausläuft.
* **Schichten werden in Spuren gepackt.** An einem Renntag gibt es bis zu 17;
  je eine eigene Zeile wäre ein halber Bildschirm. Was sich zeitlich nicht
  überschneidet, teilt sich eine Spur.
* **Der Tag darf über Mitternacht hinausreichen.** Eine Schicht von 20:00 bis
  08:00 endet bei Minute 1920. Die Achse wächst dann mit, und an jedem
  Tageswechsel steht ein eigener Strich – sonst läse sich "08" wie der Morgen
  desselben Tages.
"""

from __future__ import annotations

from datetime import datetime

# Unter dieser Breite (in Prozent der Achse) passt kein Text mehr in einen
# Balken, ohne dass er zu "Str…" verstümmelt wird. Dann bleibt er leer und
# spricht nur über Farbe und Titel-Attribut.
MINDESTBREITE_TEXT = 4.0

# Ab hier passt auch noch der Name der Rennserie davor.
MINDESTBREITE_SERIE = 14.0

# Wenn der Tag sonst zu schmal wäre, mindestens so viele Stunden zeigen.
MINDESTSPANNE = 4 * 60


def minuten(zeitstempel: str | None, basis: str) -> int | None:
    """'2026-08-31 08:00' bezogen auf den 30.08. -> 1920.

    Werte über 1440 sind gewollt: eine Nachtschicht endet am Folgetag, und die
    Achse soll sie zeigen, statt sie bei Mitternacht abzuschneiden.
    """
    if not zeitstempel:
        return None
    try:
        zeit = datetime.fromisoformat(zeitstempel)
        tag = datetime.fromisoformat(basis)
    except ValueError:
        return None
    return round((zeit - tag.replace(hour=0, minute=0)).total_seconds() / 60)


def packen(eintraege: list[dict]) -> list[list[dict]]:
    """Verteilt Balken auf möglichst wenige Spuren.

    Gieriges Verfahren: der Reihe nach nach Beginn, jeder Balken kommt in die
    erste Spur, in der er hinter das bisher Letzte passt. Das ist nicht
    beweisbar optimal, kommt aber bei einem Tagesplan immer auf dieselbe Zahl
    Spuren wie die optimale Lösung – und ist in drei Zeilen zu lesen.
    """
    spuren: list[list[dict]] = []
    for eintrag in sorted(eintraege, key=lambda e: (e["von"], e["bis"])):
        for spur in spuren:
            if spur[-1]["bis"] <= eintrag["von"]:
                spur.append(eintrag)
                break
        else:
            spuren.append([eintrag])
    return spuren


def _grenzen(stuecke: list[dict]) -> tuple[int, int]:
    """Volle Stunde vor dem ersten Beginn bis volle Stunde nach dem letzten
    Ende. Ohne das Abrunden stünde der erste Balken an der Kante."""
    von = min(s["von"] for s in stuecke)
    bis = max(s["bis"] for s in stuecke)
    von = (von // 60) * 60
    bis = -((-bis) // 60) * 60
    if bis - von < MINDESTSPANNE:
        bis = von + MINDESTSPANNE
    return von, bis


def bauen(datum: str, programm: list[dict], schichten: list[dict],
          jetzt: datetime | None = None,
          farben: dict[str, str] | None = None,
          aufgaben: list[dict] | None = None) -> dict | None:
    """Baut das Band eines Tages. None, wenn es nichts zu zeigen gibt."""
    farben = farben or {}
    aufgaben = aufgaben or []

    balken = []
    ohne_zeit = []
    for eintrag in programm:
        beginn = minuten(eintrag["beginn"], datum)
        if beginn is None:
            # "anschließend" – lässt sich nicht auf einer Achse verorten.
            ohne_zeit.append(eintrag)
            continue
        ende = minuten(eintrag["ende"], datum)
        balken.append({
            "art": "programm",
            "titel": eintrag["titel"],
            "serie": eintrag["serie"],
            "von": beginn,
            # Ein offenes Ende bekommt vorläufig eine Stunde, damit es beim
            # Packen Platz beansprucht; gezeichnet wird es bis zum Rand.
            "bis": ende if ende is not None else beginn + 60,
            "offen": ende is None,
            "zeit": eintrag.get("zeit_roh", ""),
        })

    schichtbalken = []
    for eintrag in schichten:
        beginn = minuten(eintrag["beginn"], datum)
        ende = minuten(eintrag["ende"], datum)
        if beginn is None or ende is None:
            continue
        schichtbalken.append({
            "art": "schicht",
            "id": eintrag["id"],
            "titel": eintrag["liste"],
            "von": beginn,
            "bis": ende,
            "offen": False,
            "besetzt": eintrag["besetzt"],
            "bedarf": eintrag["bedarf"],
            "fehlt": eintrag["fehlt"],
        })

    # Aufgaben mit Uhrzeit kommen als dritte Gruppe unter die Schichten. Die
    # ohne stehen im Pool und haben auf einer Zeitachse nichts verloren.
    aufgabenbalken = []
    for eintrag in aufgaben:
        beginn = minuten(eintrag["beginn"], datum)
        if beginn is None:
            continue
        ende = minuten(eintrag["ende"], datum)
        aufgabenbalken.append({
            "art": "aufgabe",
            "id": eintrag["id"],
            "titel": eintrag["titel"],
            "von": beginn,
            "bis": ende if ende is not None else beginn + 30,
            "offen": False,
            "status": eintrag["status"],
        })

    if not balken and not schichtbalken and not aufgabenbalken:
        return None

    von, bis = _grenzen(balken + schichtbalken + aufgabenbalken)
    spanne = max(1, bis - von)

    def prozent(minute: int) -> float:
        return round((minute - von) / spanne * 100, 3)

    def zeichnen(eintrag: dict) -> dict:
        links = prozent(eintrag["von"])
        rechts = 100.0 if eintrag["offen"] else prozent(eintrag["bis"])
        breite = max(0.4, rechts - links)
        # Die Mindestbreite kann einen Balken ganz am rechten Rand über die
        # Achse hinausschieben. Dann rückt er nach links statt hinauszuragen –
        # sonst steht die Ansicht mit einem Rollbalken für zwei Pixel da.
        if links + breite > 100:
            links = max(0.0, 100 - breite)
        beschriftung = ""
        if breite >= MINDESTBREITE_SERIE and eintrag["art"] == "programm":
            beschriftung = eintrag["titel"]
        elif breite >= MINDESTBREITE_TEXT:
            beschriftung = eintrag["titel"]
        return {**eintrag,
                "links": links,
                "breite": round(breite, 3),
                "beschriftung": beschriftung,
                "farbe": farben.get(eintrag.get("serie", ""), ""),
                "von_uhr": _uhr(eintrag["von"]),
                "bis_uhr": "" if eintrag["offen"] else _uhr(eintrag["bis"])}

    # Programm nach Serie gruppieren und je Serie packen: zusammengehörige
    # Balken liegen dann untereinander, und trotzdem teilen sich aufeinander
    # folgende Punkte eine Spur.
    programm_spuren = []
    for serie in sorted({b["serie"] for b in balken}):
        eigene = [b for b in balken if b["serie"] == serie]
        for spur in packen(eigene):
            programm_spuren.append([zeichnen(b) for b in spur])

    schicht_spuren = [[zeichnen(b) for b in spur]
                      for spur in packen(schichtbalken)]
    aufgaben_spuren = [[zeichnen(b) for b in spur]
                       for spur in packen(aufgabenbalken)]

    stunden = []
    marken = list(range(von, bis + 1, 60))
    for nummer, minute in enumerate(marken):
        stunde = (minute // 60) % 24
        stunden.append({
            "prozent": prozent(minute),
            "text": "%02d" % stunde,
            # Mitternacht bekommt einen eigenen Strich: sonst läse sich die
            # "08" einer Nachtschicht wie der Morgen desselben Tages.
            "tageswechsel": minute > von and minute % 1440 == 0,
            # Die Zahlen stehen mittig über ihrem Strich. Bei der ersten und
            # der letzten ragt damit die halbe Zahl über die Achse hinaus –
            # und schon zeigt der Browser einen waagerechten Rollbalken für
            # zehn Pixel. Deshalb werden die beiden nach innen gerückt.
            "rand": "links" if nummer == 0 else
                    ("rechts" if nummer == len(marken) - 1 else ""),
        })

    jetzt_prozent = None
    jetzt_rand = ""
    if jetzt is not None:
        marke = minuten(jetzt.strftime("%Y-%m-%d %H:%M"), datum)
        if marke is not None and von <= marke <= bis:
            jetzt_prozent = prozent(marke)
            # Aus demselben Grund wie bei den Stundenzahlen: nah am Rand würde
            # die Beschriftung "jetzt" hinausragen.
            if jetzt_prozent < 4:
                jetzt_rand = "links"
            elif jetzt_prozent > 96:
                jetzt_rand = "rechts"

    return {
        "datum": datum,
        "von": von,
        "bis": bis,
        "von_uhr": _uhr(von),
        "bis_uhr": _uhr(bis),
        "stunden": stunden,
        "jetzt_prozent": jetzt_prozent,
        "jetzt_rand": jetzt_rand,
        "programm_spuren": programm_spuren,
        "schicht_spuren": schicht_spuren,
        "aufgaben_spuren": aufgaben_spuren,
        "ohne_zeit": ohne_zeit,
        "serien": sorted({b["serie"] for b in balken}),
    }


def _uhr(minute: int) -> str:
    return "%02d:%02d" % ((minute // 60) % 24, minute % 60)
