"""Startet den Server mit den Werten aus der Umgebung.

    python -m app

Damit stehen Bind-Adresse und vertraute Proxys an genau einer Stelle – in der
`.env` bzw. der systemd-Unit – statt in einer Kommandozeile, in der man
`--proxy-headers` vergessen kann. Das ist bei diesem Aufbau der häufigste
Fehler: ohne das Flag steht in jedem Log die IP des Proxys.

Für die Entwicklung mit Neuladen weiterhin direkt uvicorn aufrufen:

    uvicorn app.main:app --reload --port 8080
"""

from __future__ import annotations

import uvicorn

from . import config


def main() -> None:
    host, hafen = config.bind_adresse()
    uvicorn.run(
        "app.main:app",
        host=host,
        port=hafen,
        proxy_headers=True,
        forwarded_allow_ips=config.FORWARDED_ALLOW_IPS,
        access_log=True,
        server_header=False,
    )


if __name__ == "__main__":
    main()
