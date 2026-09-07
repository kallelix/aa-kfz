"""Die Bereiche des Backoffice und die Navigation darüber.

Seit die drei Anwendungen ein Dienst sind, liegt ihr Backoffice unter einer
Adresse. Damit ist es auch eine Oberfläche: oben die drei Bereiche, darunter
die Punkte des Bereichs, in dem man gerade ist.

Zwei Zeilen und nicht eine: die drei Bereiche bringen zusammen über zwanzig
Punkte mit, und eine Zeile mit allen zwanzig hilft niemandem mehr.
"""

from __future__ import annotations

# (Schlüssel, Beschriftung, Pfad). Der Schlüssel ist zugleich das erste
# Pfadstück – daran erkennt der Verteiler in dienst/main.py den Bereich.
BEREICHE = (
    ("kennzeichen", "Kennzeichen", "/kennzeichen"),
    ("presse", "Presse", "/presse"),
    ("helfer", "Helfer", "/helfer"),
)


def punkte(eintraege, pfad: str) -> list:
    """Navigationspunkte mit dem der offenen Seite markiert.

    Ein Eintrag ist (Ziel, Name, weitere Pfade). Die weiteren Pfade sind
    nötig, weil Einzelansichten in der Einzahl heißen – /helfer/schicht/7
    gehört zu „Schichten“, fängt aber nicht mit /helfer/schichten an.

    Es gewinnt der längste passende Pfadanfang. Ein blosses „fängt damit an“
    reichte nicht: /helfer ist der Anfang von allem im Helferbereich und wäre
    sonst auf jeder seiner Seiten hervorgehoben.
    """

    def treffer(eintrag) -> int:
        ziel, _, weitere = eintrag
        laenge = 0
        for anfang in (ziel,) + tuple(weitere):
            if pfad == anfang or pfad.startswith(anfang + "/"):
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


def bereiche(pfad: str) -> list:
    """Die drei Bereiche, der offene markiert."""
    erstes = pfad.strip("/").split("/")[0] if pfad.strip("/") else ""
    return [{"schluessel": s, "name": n, "ziel": z, "hier": s == erstes}
            for s, n, z in BEREICHE]
