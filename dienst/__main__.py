"""Startet den zusammengesetzten Dienst.

    python -m dienst

Bind-Adresse und vertraute Proxys stehen in der Umgebung bzw. der
systemd-Unit, nicht in einer Kommandozeile, in der man `--proxy-headers`
vergessen kann. Das ist bei diesem Aufbau der häufigste Fehler: ohne das Flag
steht in jedem Protokoll die IP des Proxys statt die des Besuchers.

Für die Entwicklung mit Neuladen:

    uvicorn dienst.main:app --reload --port 8080
"""

from __future__ import annotations

import os

import uvicorn


def _bind() -> tuple[str, int]:
    roh = os.environ.get("BIND", "127.0.0.1:8080").strip()
    host, _, hafen = roh.rpartition(":")
    if not host:
        host, hafen = roh, "8080"
    try:
        return host, int(hafen)
    except ValueError:
        return "127.0.0.1", 8080


def main() -> None:
    host, hafen = _bind()
    uvicorn.run(
        "dienst.main:app",
        host=host,
        port=hafen,
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        access_log=True,
    )


if __name__ == "__main__":
    main()
