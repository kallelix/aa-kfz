#!/usr/bin/env python3
"""Personendaten nach der Veranstaltung löschen.

    cd /opt/abfahrt
    runuser -u abfahrt -- .venv/bin/python deploy/daten-loeschen.py --art helfer
    runuser -u abfahrt -- .venv/bin/python deploy/daten-loeschen.py --art helfer --wirklich

Ohne ``--wirklich`` wird nichts geschrieben: der Aufruf zeigt nur, was
verschwinden würde. Das ist Absicht – ein Löschlauf lässt sich nicht
zurücknehmen, und die Zahlen davor sind die einzige Gelegenheit, es zu merken.

Warum überhaupt: den Antragstellern der Kennzeichen-App ist zugesagt, dass
ihre Daten „spätestens vier Wochen nach der Veranstaltung" gelöscht werden,
und den Helfern am Unterschriften-Tablet, dass die Unterschrift „nach der
Veranstaltung gelöscht" wird. Beides sind Zusagen mit Datum, nicht Absichten.

Was bleibt, steht unten bei jeder Anwendung dabei. Grundsatz: weg muss, was
eine Person benennt oder erreichbar macht. Was rein sachlich ist – die
Schichtzeiten, der Zeitplan der Rennserien, die Aufgabenliste ohne die Namen
dahinter – kann stehenbleiben und ist nächstes Jahr eine Vorlage.

Mit der venv-Python aufrufen, nicht mit python3: psycopg liegt nur dort.
Und als Benutzer abfahrt – der meldet sich ohne Passwort an, wie der Dienst.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

import psycopg  # noqa: E402

from kern.db import Verbindung, verbinden  # noqa: E402

# Wie in dienst.env: über den Unix-Socket, als der Systembenutzer, der das
# Skript aufruft.
BETRIEB_URL = "postgresql://abfahrt@/abfahrt?host=/var/run/postgresql"

# Je Anwendung: (SQL, was es in Worten ist). Reihenfolge zählt – zuerst die
# Tabellen, die auf andere zeigen.
PLAENE: dict[str, list[tuple[str, str]]] = {
    "kennzeichen": [
        ("DELETE FROM antrag",
         "Anträge samt Name, Anschrift, Mail, Telefon, Kennzeichen und IP"),
        ("DELETE FROM mail_out",
         "verschickte und wartende Mails samt Empfänger und Text"),
        # Der Token in der Adresse ersetzt eine Anmeldung. Nach der
        # Veranstaltung hat ihn niemand mehr zu brauchen.
        ("DELETE FROM einstellung WHERE schluessel = 'durchfahrt_token'",
         "Token der Durchfahrtsliste"),
    ],
    "presse": [
        ("DELETE FROM anmeldung",
         "Akkreditierungen samt Name, Medium und Kontakt"),
        ("DELETE FROM mail_out",
         "verschickte und wartende Mails samt Empfänger und Text"),
    ],
    # Seit Lastenheft 2.9 nur, was zu Veranstaltungen gehört, die vorbei sind
    # – eine andere kann gerade laufen –, und Personen nur, wenn sie nicht im
    # Helferstamm stehen (D-03) oder seit drei Jahren nicht mehr dabei waren
    # (D-04).
    "helfer": [
        ("DELETE FROM unterschrift u WHERE NOT ("
         " (u.art = 'material' AND u.vorgang_id IN (SELECT id FROM ausleihe"
         "   WHERE veranstaltung_id IN " + "{LAUFEND}" + "))"
         " OR (u.art = 'schluessel' AND u.vorgang_id IN (SELECT id FROM schluessel"
         "   WHERE veranstaltung_id IN " + "{LAUFEND}" + "))"
         " OR (u.art = 'tshirt' AND u.vorgang_id IN " + "{DABEI}" + "))",
         "Unterschriften samt Namenszug, außer für laufende Veranstaltungen"),
        ("DELETE FROM schluessel WHERE veranstaltung_id IN {VORBEI}",
         "Schlüsselvorgänge samt Namen"),
        ("DELETE FROM fahrzeug f WHERE NOT EXISTS"
         " (SELECT 1 FROM schluessel s WHERE s.fahrzeug_id = f.id)",
         "Fahrzeugstamm samt Haltern, soweit nicht mehr gebraucht"),
        ("DELETE FROM ausleihe WHERE veranstaltung_id IN {VORBEI}",
         "Ausleihen (Funk und Material)"),
        ("DELETE FROM absage WHERE veranstaltung_id IN {VORBEI}", "Absagen samt Namen"),
        ("DELETE FROM warteliste WHERE schicht_id IN"
         " (SELECT id FROM schicht WHERE veranstaltung_id IN {VORBEI})", "Wartelisten"),
        ("DELETE FROM verfuegbarkeit WHERE veranstaltung_id IN {VORBEI}",
         "Springer-Zeiten"),
        ("DELETE FROM interesse WHERE veranstaltung_id IN {VORBEI}",
         "vorgemerktes Interesse samt Adresse"),
        ("DELETE FROM protokoll WHERE veranstaltung_id IN {VORBEI}",
         "Protokoll zu vergangenen Veranstaltungen"),
        ("DELETE FROM mail_out WHERE gesendet_am IS NOT NULL",
         "verschickte Mails samt Empfänger und Text"),
        # helfer zieht einteilung, teilnahme, einsatzgrenze und protokoll über
        # ON DELETE CASCADE mit.
        ("DELETE FROM helfer h WHERE NOT ({BLEIBT})",
         "Helfer ohne Einwilligung in den Helferstamm – und darüber ihre Einteilungen"),
        # In den Berichten stehen Hinweise wie „Erika Mustermann: in der
        # Verpflegungsspalte stand 'L'".
        ("DELETE FROM import_lauf", "Importprotokolle samt Namen darin"),
        ("UPDATE aufgabe SET verantwortlich = '', kontakt = '', kuerzel = ''"
         " WHERE veranstaltung_id IN {VORBEI}",
         "Namen an den Aufgaben vergangener Veranstaltungen (die Aufgaben bleiben)"),
        ("DELETE FROM einstellung"
         " WHERE schluessel IN ('monitor_token', 'tablet_token')",
         "Monitor- und Tablet-Token"),
    ],
}

# Bausteine der Bedingungen im Helferbereich. Eine Veranstaltung ist vorbei,
# wenn ihr letzter Tag vor heute liegt.
_VORBEI = "(SELECT id FROM kern.veranstaltung WHERE ende < CURRENT_DATE)"
_LAUFEND = "(SELECT id FROM kern.veranstaltung WHERE ende >= CURRENT_DATE)"
# Wer in einer laufenden oder kommenden Veranstaltung dabei ist.
_DABEI = ("(SELECT helfer_id FROM teilnahme WHERE veranstaltung_id IN " + _LAUFEND +
          " UNION SELECT e.helfer_id FROM einteilung e JOIN schicht s ON s.id = e.schicht_id"
          " WHERE s.veranstaltung_id IN " + _LAUFEND +
          " UNION SELECT w.helfer_id FROM warteliste w JOIN schicht s ON s.id = w.schicht_id"
          " WHERE s.veranstaltung_id IN " + _LAUFEND + ")")
# D-03, D-04: im Helferstamm – selbst eingewilligt oder von jemandem
# mitgebracht, der eingewilligt hat –, und zuletzt dabei vor höchstens drei
# Jahren (ohne Teilnahme zählt der Tag der Einwilligung).
_STAMM = ("((h.stamm_einwilligung_am IS NOT NULL OR EXISTS (SELECT 1 FROM helfer a"
          " WHERE a.id = h.angemeldet_von AND a.stamm_einwilligung_am IS NOT NULL))"
          " AND COALESCE((SELECT MAX(v.ende) FROM kern.veranstaltung v WHERE v.id IN"
          "  (SELECT veranstaltung_id FROM teilnahme WHERE helfer_id = h.id"
          "   UNION SELECT s.veranstaltung_id FROM einteilung e JOIN schicht s"
          "   ON s.id = e.schicht_id WHERE e.helfer_id = h.id)),"
          "  CAST(LEFT(COALESCE(h.stamm_einwilligung_am, ''), 10) AS date))"
          " >= CURRENT_DATE - INTERVAL '3 years')")
_BAUSTEINE = {"{VORBEI}": _VORBEI, "{LAUFEND}": _LAUFEND, "{DABEI}": _DABEI,
              "{BLEIBT}": "h.id IN " + _DABEI + " OR " + _STAMM}
for _art, _plan in PLAENE.items():
    for _i, (_sql, _worte) in enumerate(_plan):
        for _platzhalter, _text in _BAUSTEINE.items():
            _sql = _sql.replace(_platzhalter, _text)
        _plan[_i] = (_sql, _worte)

# Was ausdrücklich stehenbleibt. Steht hier, damit der Bericht es benennt und
# niemand raten muss, ob etwas vergessen wurde.
BLEIBT: dict[str, str] = {
    "kennzeichen": "die Einstellungen (ohne den Token)",
    "presse": "die Einstellungen",
    "helfer": ("Schichten und Zeiten, der Zeitplan der Rennserien, die "
               "Aufgabenliste ohne Namen, die Materialvorgaben – und wer in einer "
               "laufenden oder kommenden Veranstaltung dabei ist oder in den "
               "Helferstamm eingewilligt hat (samt Mitgebrachten), höchstens drei "
               "Jahre nach der letzten Teilnahme"),
}


def _tabelle_und_bedingung(sql: str) -> str:
    """'antrag' oder 'einstellung WHERE …' – das, worüber gezählt wird."""
    if sql.startswith("UPDATE "):
        tabelle = sql.split()[1]
        wo = sql.split(" WHERE ", 1)
        return tabelle + ((" WHERE " + wo[1]) if len(wo) > 1 else "")
    return sql.split(" FROM ", 1)[1]


def zaehlen(con: Verbindung, sql: str) -> int:
    """Wie viele Zeilen der Schritt anfassen würde – ohne ihn auszuführen."""
    try:
        return con.execute(
            "SELECT COUNT(*) FROM " + _tabelle_und_bedingung(sql)).fetchone()[0]
    except psycopg.Error as fehler:
        # Nach einem Fehler nimmt PostgreSQL in dieser Transaktion nichts mehr
        # an; ohne das Zurückrollen scheiterte jede weitere Zeile mit.
        con.rollback()
        print("   ! Zählen ging nicht (" + str(fehler).strip() + ")",
              file=sys.stderr)
        return -1


def sichern(url: str, schema: str, ordner: Path) -> Path | None:
    """Ein pg_dump nur dieses Bereichs, bevor gelöscht wird."""
    if shutil.which("pg_dump") is None:
        print("pg_dump fehlt – erst deploy/backup.sh laufen lassen und dann "
              "mit --ohne-sicherung aufrufen.", file=sys.stderr)
        return None
    ziel = ordner / (schema + "-vor-loeschung-" + date.today().isoformat() + ".dump")
    if ziel.exists():
        print("Es gibt schon " + str(ziel) + " – erst wegräumen.", file=sys.stderr)
        return None
    ordner.mkdir(parents=True, exist_ok=True)
    alte_maske = os.umask(0o077)
    try:
        subprocess.run(["pg_dump", "--format=custom", "--schema=" + schema,
                        "--dbname=" + url, "--file=" + str(ziel)], check=True)
    except subprocess.CalledProcessError:
        print("pg_dump ist gescheitert, es wurde nichts gelöscht.", file=sys.stderr)
        return None
    finally:
        os.umask(alte_maske)
    return ziel


def main() -> int:
    zerleger = argparse.ArgumentParser(
        description="Personendaten nach der Veranstaltung löschen.")
    zerleger.add_argument("--art", required=True, choices=sorted(PLAENE),
                          help="welcher Bereich")
    zerleger.add_argument("--url", default=os.environ.get("DATABASE_URL") or BETRIEB_URL,
                          help="Verbindung zur Datenbank (Vorgabe: DATABASE_URL "
                               "oder der Unix-Socket wie im Betrieb)")
    zerleger.add_argument("--wirklich", action="store_true",
                          help="tatsächlich löschen (sonst nur zeigen)")
    zerleger.add_argument("--sicherung-nach", type=Path,
                          default=Path("/var/backups/abfahrt"),
                          help="wohin die Sicherung vor dem Löschen geht")
    zerleger.add_argument("--ohne-sicherung", action="store_true",
                          help="keine Sicherung anlegen – nur, wenn es schon eine gibt")
    werte = zerleger.parse_args()

    plan = PLAENE[werte.art]
    try:
        con = verbinden(werte.url, werte.art)
    except psycopg.OperationalError as fehler:
        print("Keine Verbindung zur Datenbank: " + str(fehler).strip(),
              file=sys.stderr)
        return 1

    print(werte.art + " – Schema " + werte.art)
    print()
    for sql, worte in plan:
        anzahl = zaehlen(con, sql)
        print("   %6s  %s" % (anzahl if anzahl >= 0 else "?", worte))
    print()
    print("   bleibt: " + BLEIBT[werte.art])
    print()

    if not werte.wirklich:
        print("Nichts geschrieben. Mit --wirklich wird es ernst.")
        con.close()
        return 0

    if not werte.ohne_sicherung:
        ziel = sichern(werte.url, werte.art, werte.sicherung_nach)
        if ziel is None:
            con.close()
            return 1
        print("Sicherung: " + str(ziel))

    # Alles in einer Transaktion: geht ein Schritt schief, bleibt alles stehen.
    with con:
        for sql, worte in plan:
            zeiger = con.execute(sql)
            print("   %6d  %s" % (zeiger.rowcount, worte))

    # PostgreSQL gibt gelöschte Zeilen nur zum Überschreiben frei. VACUUM FULL
    # schreibt die Tabellen neu, und die alten Dateien gehen ans Dateisystem
    # zurück. Geht nicht in einer Transaktion, deshalb danach und einzeln.
    con.roh.autocommit = True
    tabellen = sorted({_tabelle_und_bedingung(sql).split()[0] for sql, _ in plan})
    if werte.art == "helfer":
        tabellen += ["einteilung", "teilnahme", "einsatzgrenze"]
    for tabelle in tabellen:
        con.execute("VACUUM FULL " + tabelle)
    con.close()

    print()
    print("Fertig. Die Sicherung liegt getrennt – wer sie nicht mehr braucht,")
    print("löscht sie auch, sonst war der Lauf umsonst. Dasselbe gilt für die")
    print("nächtlichen Sicherungen aus der Zeit der Veranstaltung.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
