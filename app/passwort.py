"""Erzeugt den bcrypt-Hash für ADMIN_PASSWORD_HASH.

    python -m app.passwort              # fragt interaktiv (Eingabe unsichtbar)
    python -m app.passwort 'geheim'     # nicht interaktiv, landet in der History
"""

from __future__ import annotations

import getpass
import sys

from .auth import hash_erzeugen


def main() -> int:
    if len(sys.argv) > 1:
        klartext = sys.argv[1]
    else:
        klartext = getpass.getpass("Passwort: ")
        if klartext != getpass.getpass("Wiederholen: "):
            print("Die Eingaben stimmen nicht überein.", file=sys.stderr)
            return 1

    if len(klartext) < 8:
        print("Bitte mindestens 8 Zeichen verwenden.", file=sys.stderr)
        return 1

    print("ADMIN_PASSWORD_HASH=" + hash_erzeugen(klartext))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
