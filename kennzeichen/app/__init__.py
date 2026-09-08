"""Die Anwendung selbst.

Hier steht nur eines: die Repo-Wurzel kommt auf den Suchpfad, damit `kern`
gefunden wird. Das gehoert ins Paket und nicht erst in main.py - db.py und
normalisieren.py greifen ebenfalls darauf zu, und Tests laden die einzeln.
"""

import sys as _sys
from pathlib import Path as _Path

WURZEL = _Path(__file__).resolve().parents[2]
if str(WURZEL) not in _sys.path:
    _sys.path.insert(0, str(WURZEL))
