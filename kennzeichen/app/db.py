"""Datenbankzugriff. PostgreSQL, Schema kennzeichen – siehe kern/db.py."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path

from kern import suchen
from kern.db import Datenbank, Verbindung

from . import config

_DATENBANK = Datenbank(lambda: config.DATABASE_URL, config.DB_SCHEMA,
                       Path(__file__).resolve().parent / "migrationen")


def jetzt() -> str:
    """Zeitstempel in ISO-8601 mit Sekundenauflösung, immer UTC."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def kfz_normalisieren(wert):
    """Kennzeichen auf Buchstaben und Ziffern eindampfen, in Grossschrift.

    "ka-xy 123", "KA XY 123" und "kaxy123" ergeben alle "KAXY123". An der
    Strassensperre tippt niemand Bindestriche mit.
    """
    if not isinstance(wert, str):
        return wert
    return "".join(zeichen for zeichen in wert if zeichen.isalnum()).upper()


def verbinden() -> Verbindung:
    return _DATENBANK.verbinden()


def transaktion():
    """Verbindung mit Commit bei Erfolg, Rollback bei Ausnahme."""
    return _DATENBANK.transaktion()


def init() -> list:
    """Spielt fehlende Migrationen ein und liefert ihre Namen fürs Protokoll."""
    return _DATENBANK.init()


def antrag_anlegen(werte: dict, remote_ip: str | None,
                   status: str = "neu", kuerzel: str = "",
                   mail: tuple | None = None) -> int:
    """Speichert einen validierten Antrag und liefert dessen Nummer.

    `status` ist normalerweise 'neu' – so kommt jeder Antrag aus dem
    oeffentlichen Formular. Legt die Orga selbst einen an, steht die Person
    meist davor, und die Entscheidung ist mit dem Eintragen schon gefallen.
    Dann wird gleich 'genehmigt' geschrieben, samt Zeitpunkt und Kuerzel.

    Kein Umweg ueber antrag_status_setzen: der prueft einen Uebergang, den es
    hier nicht gibt – der Antrag entsteht ja erst. Zwei Schreibvorgaenge
    daraus zu machen hiesse nur, dass zwischen ihnen etwas schiefgehen kann.
    """
    entscheidung = jetzt() if status in ("genehmigt", "abgelehnt") else None
    with transaktion() as con:
        cur = con.execute(
            """
            INSERT INTO antrag (
                vorname, nachname, funktion, kategorie, email, telefon,
                kennzeichen, bemerkung, status, created_at, remote_ip,
                entscheidung_am, entscheidung_durch
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                werte["vorname"],
                werte["nachname"],
                werte["funktion"],
                werte["kategorie"],
                werte["email"] or None,
                werte["telefon"] or None,
                werte["kennzeichen"] or None,
                werte["bemerkung"] or None,
                status,
                jetzt(),
                remote_ip,
                entscheidung,
                (kuerzel or None) if entscheidung else None,
            ),
        )
        nummer = int(cur.fetchone()[0])
        if mail is not None:
            # In derselben Transaktion wie der Antrag: sonst gaebe es einen
            # genehmigten Antrag, zu dem die Zusage nie eingereiht wurde.
            _mail_einreihen(con, nummer, mail)
        return nummer


# --- Backoffice-Abfragen (Schritt 4) ---------------------------------------

# Whitelist: die Sortierung kommt aus der URL und darf nie ins SQL durchgereicht
# werden.
SORTIERUNGEN = {
    "neueste": "created_at DESC, id DESC",
    "aelteste": "created_at ASC, id ASC",
    "name": "lower(nachname), lower(vorname)",
    "kategorie": "kategorie, created_at DESC",
}

STATUS_WERTE = ("neu", "genehmigt", "abgelehnt", "ausgegeben")

# Felder, über die die Freitextsuche läuft.
_SUCHFELDER = (
    "vorname",
    "nachname",
    "funktion",
    "email",
    "telefon",
    "kennzeichen",
    "bemerkung",
)


def _passt(antrag, suche: str) -> bool:
    """Ob ein Antrag zum Suchbegriff passt.

    Unter SQLite lief das als SQL-Funktion, die Python registrierte.
    PostgreSQL kann keine Python-Funktion aufrufen; die Regel bleibt deshalb
    in Python, an EINER Stelle (kern/suchen.py), und wird auf die geladenen
    Zeilen angewandt. Bei ein paar hundert Antraegen kostet das nichts.
    """
    heuhaufen = suchen.suchtext(*(antrag[feld] or "" for feld in _SUCHFELDER))
    # Ein Suchbegriff kann zwei Schreibweisen haben - "Müller" wird zu
    # "mueller" UND "muller". Eine davon muss vorkommen.
    if suchen.passt(heuhaufen, suche):
        return True
    # "kaxy123" soll auch "KA-XY 123" finden.
    gesuchtes_kfz = kfz_normalisieren(suche)
    return bool(gesuchtes_kfz) and gesuchtes_kfz in kfz_normalisieren(
        antrag["kennzeichen"] or "")


def antraege_suchen(
    status: str = "",
    kategorie: str = "",
    suche: str = "",
    sortierung: str = "neueste",
) -> list:
    bedingungen: list[str] = []
    parameter: list = []

    if status:
        bedingungen.append("status = ?")
        parameter.append(status)
    if kategorie:
        bedingungen.append("kategorie = ?")
        parameter.append(kategorie)

    wo = f"WHERE {' AND '.join(bedingungen)}" if bedingungen else ""
    ordnung = SORTIERUNGEN.get(sortierung, SORTIERUNGEN["neueste"])

    con = verbinden()
    try:
        zeilen = con.execute(
            f"SELECT * FROM antrag {wo} ORDER BY {ordnung}", parameter
        ).fetchall()
    finally:
        con.close()
    if suche and suche.strip():
        zeilen = [zeile for zeile in zeilen if _passt(zeile, suche)]
    return zeilen


def antrag_laden(antrag_id: int):
    con = verbinden()
    try:
        return con.execute("SELECT * FROM antrag WHERE id = ?", (antrag_id,)).fetchone()
    finally:
        con.close()


def antrag_loeschen(antrag_id: int) -> bool:
    with transaktion() as con:
        cur = con.execute("DELETE FROM antrag WHERE id = ?", (antrag_id,))
        return cur.rowcount > 0


def zaehler() -> dict:
    """Anzahl pro Kategorie und Status, plus Gesamtzahlen – für die Kopfzeile
    im Backoffice (Kontingente im Blick behalten)."""
    con = verbinden()
    try:
        zeilen = con.execute(
            "SELECT kategorie, status, COUNT(*) AS anzahl FROM antrag"
            " GROUP BY kategorie, status"
        ).fetchall()
    finally:
        con.close()

    je_kategorie: dict[str, dict[str, int]] = {}
    je_status: dict[str, int] = {s: 0 for s in STATUS_WERTE}
    gesamt = 0
    for zeile in zeilen:
        eintrag = je_kategorie.setdefault(
            zeile["kategorie"], {s: 0 for s in STATUS_WERTE} | {"gesamt": 0}
        )
        eintrag[zeile["status"]] = zeile["anzahl"]
        eintrag["gesamt"] += zeile["anzahl"]
        je_status[zeile["status"]] = je_status.get(zeile["status"], 0) + zeile["anzahl"]
        gesamt += zeile["anzahl"]

    return {"je_kategorie": je_kategorie, "je_status": je_status, "gesamt": gesamt}


# --- Redaktionelle Freigabe (Schritt 5) ------------------------------------

# Erlaubte Statuswechsel, Zielstatus -> zulaessige Ausgangsstatus. Der Plan
# zeichnet neu -> genehmigt -> ausgegeben und neu -> abgelehnt; zusaetzlich darf
# eine Fehlentscheidung direkt ins Gegenteil gedreht werden.
UEBERGAENGE = {
    "genehmigt": ("neu", "abgelehnt"),
    "abgelehnt": ("neu", "genehmigt"),
    "ausgegeben": ("genehmigt",),
    "neu": ("genehmigt", "abgelehnt", "ausgegeben"),
}

# Felder, die im Backoffice korrigiert werden duerfen.
BEARBEITBAR = (
    "vorname",
    "nachname",
    "funktion",
    "kategorie",
    "email",
    "telefon",
    "kennzeichen",
    "bemerkung",
)


def antrag_aktualisieren(antrag_id: int, werte: dict) -> bool:
    """Uebernimmt korrigierte Werte. Status und Entscheidung bleiben unberuehrt."""
    zuweisungen = ", ".join(feld + " = ?" for feld in BEARBEITBAR)
    parameter = [werte.get(feld) or None for feld in BEARBEITBAR]
    with transaktion() as con:
        cur = con.execute(
            f"UPDATE antrag SET {zuweisungen} WHERE id = ?", parameter + [antrag_id]
        )
        return cur.rowcount > 0


def antrag_status_setzen(
    antrag_id: int,
    neuer_status: str,
    kuerzel: str = "",
    begruendung: str | None = None,
    mail: tuple | None = None,
) -> bool:
    """Setzt den Status nur, wenn der Uebergang erlaubt ist.

    Der Ausgangsstatus steckt als Bedingung im UPDATE, damit zwei gleichzeitige
    Klicks sich nicht ueberholen. Liefert False, wenn nichts geaendert wurde.

    `mail` wird nur eingereiht, wenn der Wechsel tatsaechlich stattgefunden hat –
    beides in einer Transaktion, damit es keine Entscheidung ohne Mail gibt.
    """
    erlaubt = UEBERGAENGE.get(neuer_status)
    if erlaubt is None:
        return False
    platzhalter = ", ".join("?" for _ in erlaubt)

    if neuer_status == "neu":
        # Zuruecksetzen: die Entscheidung war ein Versehen, also weg damit.
        sql = (
            "UPDATE antrag SET status = 'neu', entscheidung_am = NULL,"
            " entscheidung_durch = NULL, begruendung = NULL"
            f" WHERE id = ? AND status IN ({platzhalter})"
        )
        parameter = [antrag_id, *erlaubt]
    elif neuer_status == "ausgegeben":
        # Nur ein Haekchen bei der Kartenuebergabe – die Entscheidungsdaten der
        # Genehmigung bleiben stehen.
        sql = f"UPDATE antrag SET status = 'ausgegeben' WHERE id = ? AND status IN ({platzhalter})"
        parameter = [antrag_id, *erlaubt]
    else:
        sql = (
            "UPDATE antrag SET status = ?, entscheidung_am = ?,"
            " entscheidung_durch = ?, begruendung = ?"
            f" WHERE id = ? AND status IN ({platzhalter})"
        )
        parameter = [
            neuer_status,
            jetzt(),
            kuerzel or None,
            begruendung or None,
            antrag_id,
            *erlaubt,
        ]

    with transaktion() as con:
        geaendert = con.execute(sql, parameter).rowcount > 0
        if geaendert and mail is not None:
            _mail_einreihen(con, antrag_id, mail)
        return geaendert


def sammel_genehmigen(ids: list, kuerzel: str = "", mails: dict | None = None) -> list:
    """Genehmigt mehrere Antraege auf einmal.

    Liefert die Nummern, die tatsaechlich gewechselt sind. `mails` ordnet
    Antragsnummern die vorbereitete Mail zu; eingereiht wird nur fuer die
    Antraege, die der Wechsel wirklich erfasst hat.
    """
    if not ids:
        return []
    erlaubt = UEBERGAENGE["genehmigt"]
    id_platzhalter = ", ".join("?" for _ in ids)
    status_platzhalter = ", ".join("?" for _ in erlaubt)
    with transaktion() as con:
        betroffen = [
            zeile["id"]
            for zeile in con.execute(
                f"SELECT id FROM antrag WHERE id IN ({id_platzhalter})"
                f" AND status IN ({status_platzhalter})",
                [*ids, *erlaubt],
            )
        ]
        if not betroffen:
            return []
        con.execute(
            "UPDATE antrag SET status = 'genehmigt', entscheidung_am = ?,"
            " entscheidung_durch = ?, begruendung = NULL"
            f" WHERE id IN ({', '.join('?' for _ in betroffen)})",
            [jetzt(), kuerzel or None, *betroffen],
        )
        for antrag_id in betroffen:
            mail = (mails or {}).get(antrag_id)
            if mail is not None:
                _mail_einreihen(con, antrag_id, mail)
        return betroffen


def kontingent_belegt(kategorie: str) -> int:
    """Genehmigte und bereits ausgegebene Karten einer Kategorie."""
    con = verbinden()
    try:
        return con.execute(
            "SELECT COUNT(*) FROM antrag WHERE kategorie = ?"
            " AND status IN ('genehmigt', 'ausgegeben')",
            (kategorie,),
        ).fetchone()[0]
    finally:
        con.close()


# --- Mail-Queue (Schritt 6) -------------------------------------------------


def _mail_einreihen(con, antrag_id: int, mail: tuple) -> None:
    """mail = (typ, empfaenger, betreff, body). Laeuft in der Transaktion des
    Aufrufers, damit Entscheidung und Mail zusammen stehen oder gar nicht."""
    typ, empfaenger, betreff, body = mail
    con.execute(
        "INSERT INTO mail_out (antrag_id, typ, empfaenger, betreff, body, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (antrag_id, typ, empfaenger, betreff, body, jetzt()),
    )


def mail_einreihen(antrag_id: int, mail: tuple) -> None:
    with transaktion() as con:
        _mail_einreihen(con, antrag_id, mail)


def mails_faellig(grenze: int = 20) -> list:
    """Unversendete Mails, deren Backoff abgelaufen ist."""
    con = verbinden()
    try:
        return con.execute(
            "SELECT * FROM mail_out"
            " WHERE gesendet_am IS NULL AND versuche < ?"
            "   AND (naechster_versuch IS NULL OR naechster_versuch <= ?)"
            " ORDER BY id LIMIT ?",
            (config.MAIL_MAX_VERSUCHE, jetzt(), grenze),
        ).fetchall()
    finally:
        con.close()


def mail_gesendet(mail_id: int) -> None:
    with transaktion() as con:
        con.execute(
            "UPDATE mail_out SET gesendet_am = ?, versuche = versuche + 1,"
            " letzter_fehler = NULL, naechster_versuch = NULL WHERE id = ?",
            (jetzt(), mail_id),
        )


def mail_fehlgeschlagen(mail_id: int, fehler: str, naechster_versuch: str | None) -> None:
    with transaktion() as con:
        con.execute(
            "UPDATE mail_out SET versuche = versuche + 1, letzter_fehler = ?,"
            " naechster_versuch = ? WHERE id = ?",
            (fehler[:500], naechster_versuch, mail_id),
        )


def mail_erneut(mail_id: int) -> bool:
    """Aufgegebene Mail von Hand wieder in die Schlange stellen."""
    with transaktion() as con:
        cur = con.execute(
            "UPDATE mail_out SET versuche = 0, naechster_versuch = NULL,"
            " letzter_fehler = NULL WHERE id = ? AND gesendet_am IS NULL",
            (mail_id,),
        )
        return cur.rowcount > 0


def mails_zu_antrag(antrag_id: int) -> list:
    con = verbinden()
    try:
        return con.execute(
            "SELECT * FROM mail_out WHERE antrag_id = ? ORDER BY id", (antrag_id,)
        ).fetchall()
    finally:
        con.close()


def mails_aufgegeben() -> int:
    """Zahl der Mails, die nach MAIL_MAX_VERSUCHE liegengeblieben sind."""
    con = verbinden()
    try:
        return con.execute(
            "SELECT COUNT(*) FROM mail_out WHERE gesendet_am IS NULL AND versuche >= ?",
            (config.MAIL_MAX_VERSUCHE,),
        ).fetchone()[0]
    finally:
        con.close()


# --- Telefonisch zu informieren ---------------------------------------------


# Angerufen wird nur bei einer Absage. Wer genehmigt ist, steht an der
# Strassensperre ohnehin auf der Liste und bekommt den Aufkleber dort - da
# waere ein Anruf Arbeit ohne Ertrag. Eine Absage dagegen muss ankommen, sonst
# faehrt jemand umsonst hin.
TELEFONISCH_STATUS = ("abgelehnt",)

_TELEFONISCH_WO = (
    " WHERE COALESCE(TRIM(email), '') = ''"
    "   AND status IN (%s)"
    "   AND tel_informiert_am IS NULL"
) % ", ".join("?" for _ in TELEFONISCH_STATUS)


def antraege_telefonisch() -> list:
    """Abgelehnte Antraege ohne Mailadresse, bei denen noch niemand angerufen hat."""
    con = verbinden()
    try:
        return con.execute(
            "SELECT * FROM antrag" + _TELEFONISCH_WO + " ORDER BY entscheidung_am, id",
            TELEFONISCH_STATUS,
        ).fetchall()
    finally:
        con.close()


def telefonisch_offen() -> int:
    con = verbinden()
    try:
        return con.execute(
            "SELECT COUNT(*) FROM antrag" + _TELEFONISCH_WO, TELEFONISCH_STATUS
        ).fetchone()[0]
    finally:
        con.close()


def tel_informiert_setzen(antrag_id: int, erledigt: bool) -> bool:
    with transaktion() as con:
        cur = con.execute(
            "UPDATE antrag SET tel_informiert_am = ? WHERE id = ?",
            (jetzt() if erledigt else None, antrag_id),
        )
        return cur.rowcount > 0


# --- Durchfahrtsliste fuer die Strassensperre -------------------------------

# Wer durchfahren darf: genehmigt, und wer die Karte schon hat. Alles andere
# hat an der Sperre nichts zu suchen - eine Liste, auf der auch abgelehnte
# Antraege stehen, waere dort gefaehrlich.
DURCHFAHRT_STATUS = ("genehmigt", "ausgegeben")


def antraege_durchfahrt() -> list:
    """Alle berechtigten Fahrzeuge, sortiert nach Kennzeichen.

    Bewusst ohne Suchparameter: an der Strassensperre ist der Empfang mies,
    deshalb geht die vollstaendige Liste einmal in die Seite und gefiltert wird
    im Browser (app/static/durchfahrt.js).
    """
    con = verbinden()
    try:
        zeilen = con.execute(
            "SELECT * FROM antrag WHERE status IN (%s)"
            % ", ".join("?" for _ in DURCHFAHRT_STATUS),
            DURCHFAHRT_STATUS,
        ).fetchall()
    finally:
        con.close()
    # Nach Kennzeichen, denn danach wird an der Sperre gesucht. Normalisiert,
    # damit KA-AB 1 und KAAB1 beieinander stehen, und Zeilen ohne Kennzeichen
    # ans Ende statt nach vorn. In Python und nicht in SQL: dieselbe
    # Normalisierung, die auch data-kfz in der Seite traegt.
    return sorted(zeilen, key=lambda z: (
        not (z["kennzeichen"] or "").strip(),
        kfz_normalisieren(z["kennzeichen"] or ""),
        (z["nachname"] or "").lower(),
        (z["vorname"] or "").lower(),
    ))


# --- Einstellungen und der Token fuer die offene Durchfahrtsliste -----------

TOKEN_SCHLUESSEL = "durchfahrt_token"


def einstellung_lesen(schluessel: str) -> str | None:
    con = verbinden()
    try:
        zeile = con.execute(
            "SELECT wert FROM einstellung WHERE schluessel = ?", (schluessel,)
        ).fetchone()
        return zeile["wert"] if zeile else None
    finally:
        con.close()


def einstellung_setzen(schluessel: str, wert: str) -> None:
    with transaktion() as con:
        con.execute(
            "INSERT INTO einstellung (schluessel, wert, geaendert_am)"
            " VALUES (?, ?, ?)"
            " ON CONFLICT(schluessel) DO UPDATE SET wert = excluded.wert,"
            " geaendert_am = excluded.geaendert_am",
            (schluessel, wert, jetzt()),
        )


def einstellung_loeschen(schluessel: str) -> bool:
    with transaktion() as con:
        return con.execute(
            "DELETE FROM einstellung WHERE schluessel = ?", (schluessel,)
        ).rowcount > 0


def durchfahrt_token() -> str | None:
    """Der aktuelle Token, oder None – dann gibt es keinen offenen Zugang."""
    return einstellung_lesen(TOKEN_SCHLUESSEL)


def durchfahrt_token_erzeugen() -> str:
    """Erzeugt einen neuen Token. Ein vorhandener wird damit ungueltig."""
    token = secrets.token_urlsafe(32)
    einstellung_setzen(TOKEN_SCHLUESSEL, token)
    return token


def durchfahrt_token_zuruecknehmen() -> bool:
    return einstellung_loeschen(TOKEN_SCHLUESSEL)


# --- Benachrichtigung der Orga bei neuen Antraegen --------------------------

BENACHRICHTIGUNG_SCHLUESSEL = "benachrichtigung_mail"


def benachrichtigung_mail() -> str:
    """Adresse, die bei jedem neuen Antrag eine Nachricht bekommt.

    Leer heisst: niemand wird benachrichtigt. Steht bewusst in der Datenbank
    und nicht in der Env, damit sie sich ohne Neustart aendern laesst.
    """
    return einstellung_lesen(BENACHRICHTIGUNG_SCHLUESSEL) or ""


def benachrichtigung_mail_setzen(adresse: str) -> None:
    adresse = (adresse or "").strip()
    if adresse:
        einstellung_setzen(BENACHRICHTIGUNG_SCHLUESSEL, adresse)
    else:
        einstellung_loeschen(BENACHRICHTIGUNG_SCHLUESSEL)
