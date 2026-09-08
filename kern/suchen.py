"""Suchen, die mit Umlauten zurechtkommen.

Der Fehler, aus dem das hier entstanden ist: im Helferbereich fand ein
getippter Umlaut gar nichts. Der durchsuchte Text war umgeschrieben –
„Öztürk“ lag als „oeztuerk“ da –, der Suchbegriff aber nur kleingeschrieben.
„öztürk“ kam in „oeztuerk“ nicht vor. In den beiden anderen Anwendungen war
es andersherum: dort blieben die Umlaute stehen, dafür fand „Mueller“ kein
„Müller“.

Die Regel ist deshalb: **dieselbe Umformung auf beide Seiten.** Und weil man
denselben Namen auf zwei Arten schreiben kann, wird beides hinterlegt:

    „Müller“  ->  Heuhaufen „mueller muller“
    getippt „Müller“, „mueller“ oder „muller“  ->  alle drei finden ihn

Die deutsche Auflösung (ä→ae) und die blosse Entkleidung (ä→a) stehen
nebeneinander, weil beide vorkommen: „Mueller“ schreibt, wer keine Umlaute
auf der Tastatur hat, „Muller“, wer sie einfach weglässt.

Dieselbe Umformung gibt es ein zweites Mal in kern/static/suchtext.js – die
clientseitigen Listen filtern im Browser. Dass beide dasselbe tun, prüft
tests/test_suchen_js.js gegen genau diese Datei.
"""

from __future__ import annotations

import re
import unicodedata

# Was aufgelöst wird, bevor die Diakritika fallen. Reihenfolge egal, die
# Zeichen kommen nicht ineinander vor.
#
# Das scharfe S steht NICHT hier, sondern schon in _grundform: es hat nur
# eine sinnvolle Schreibweise ohne Umlaut, und Pythons casefold() löst es
# ohnehin auf – JavaScripts toLowerCase() aber nicht. Beide machen es
# deshalb ausdrücklich, sonst gingen sie auseinander. Genau daran ist der
# Abgleich in tests/test_suchen.py beim ersten Lauf hängengeblieben.
DEUTSCH = (("ä", "ae"), ("ö", "oe"), ("ü", "ue"))

_LEERRAUM = re.compile(r"\s+")


def _grundform(roh: str) -> str:
    """Klein, ohne doppelten Leerraum, ohne führende und folgende Leerzeichen."""
    klein = (roh or "").casefold().replace("ß", "ss")
    return _LEERRAUM.sub(" ", klein).strip()


def _entkleidet(roh: str) -> str:
    """Diakritika weg: „ä“ wird „a“, „é“ wird „e“."""
    zerlegt = unicodedata.normalize("NFKD", roh)
    return "".join(z for z in zerlegt if not unicodedata.combining(z))


def varianten(roh: str) -> list[str]:
    """Die Schreibweisen, unter denen ein Text zu finden sein soll.

    Immer mindestens eine; die zweite nur, wenn sie sich unterscheidet –
    „Meier“ hat nichts aufzulösen und steht deshalb nur einmal da.
    """
    grund = _grundform(roh)
    if not grund:
        return []
    deutsch = grund
    for zeichen, ersatz in DEUTSCH:
        deutsch = deutsch.replace(zeichen, ersatz)
    deutsch = _entkleidet(deutsch)
    blank = _entkleidet(grund)
    return [deutsch] if deutsch == blank else [deutsch, blank]


def suchtext(*teile: str) -> str:
    """Der durchsuchbare Text zu einem Datensatz.

    Alle Schreibweisen hintereinander, damit ein einfaches „steckt darin“
    genügt – im Browser wie in SQL.
    """
    zusammen = " ".join(t for t in teile if t)
    return " ".join(varianten(zusammen))


def passt(heuhaufen: str, nadel: str) -> bool:
    """Ob der Suchbegriff in irgendeiner seiner Schreibweisen vorkommt."""
    gesucht = varianten(nadel)
    if not gesucht:
        return True
    return any(v in heuhaufen for v in gesucht)
