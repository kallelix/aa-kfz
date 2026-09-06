"""SQLite-Zugriff. Eine Datei, ein `cp` als Backup."""

from __future__ import annotations

import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import config

SCHEMA = Path(__file__).resolve().parent / "schema.sql"


def jetzt() -> str:
    """Zeitstempel in ISO-8601 mit Sekundenauflösung, immer UTC."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _lower_u(wert):
    return wert.lower() if isinstance(wert, str) else wert


def kfz_normalisieren(wert):
    """Kennzeichen auf Buchstaben und Ziffern eindampfen, in Grossschrift.

    "ka-xy 123", "KA XY 123" und "kaxy123" ergeben alle "KAXY123". An der
    Strassensperre tippt niemand Bindestriche mit.
    """
    if not isinstance(wert, str):
        return wert
    return "".join(zeichen for zeichen in wert if zeichen.isalnum()).upper()


def verbinden() -> sqlite3.Connection:
    con = sqlite3.connect(config.DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 5000")
    # SQLite kennt nur ASCII-Groß/Kleinschreibung; für die Suche nach "Müller"
    # brauchen wir Pythons Unicode-Variante.
    con.create_function("lower_u", 1, _lower_u, deterministic=True)
    con.create_function("kfz_norm", 1, kfz_normalisieren, deterministic=True)
    return con


@contextmanager
def transaktion():
    """Verbindung mit Commit bei Erfolg, Rollback bei Ausnahme."""
    con = verbinden()
    try:
        with con:
            yield con
    finally:
        con.close()


# Spalten, die nach dem ersten Ausliefern dazugekommen sind. SQLite kann
# ADD COLUMN, mehr brauchen wir fuer eine Datei mit ein paar hundert Zeilen nicht.
NACHTRAEGLICHE_SPALTEN = (
    ("mail_out", "naechster_versuch", "TEXT"),
)


# Spalten von mail_out in der Reihenfolge, in der beim Umbau kopiert wird.
_MAIL_OUT_SPALTEN = (
    "id", "antrag_id", "typ", "empfaenger", "betreff", "body",
    "versuche", "gesendet_am", "letzter_fehler", "naechster_versuch", "created_at",
)


def _mail_out_umbauen(con: sqlite3.Connection) -> bool:
    """Zieht den CHECK auf mail_out.typ nach.

    SQLite kann Constraints nicht aendern, deshalb die uebliche Prozedur: neue
    Tabelle daneben, Daten hinueber, alte weg, umbenennen. Laeuft nur, wenn die
    gespeicherte Definition den Typ 'orga' noch nicht kennt.
    """
    zeile = con.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'mail_out'"
    ).fetchone()
    if zeile is None or "'orga'" in zeile["sql"]:
        return False

    # Fremdschluessel fuer den Umbau abschalten - so steht es in der
    # SQLite-Anleitung. Sonst scheitert das Kopieren an Zeilen, deren Antrag es
    # nicht mehr gibt; die alte Tabelle kannte diese Bedingung noch nicht.
    # PRAGMA wirkt nur ausserhalb einer Transaktion, deshalb hier und nicht im
    # Skript.
    con.execute("PRAGMA foreign_keys = OFF")
    spalten = ", ".join(_MAIL_OUT_SPALTEN)
    try:
        con.executescript(
            f"""
        BEGIN;
        CREATE TABLE mail_out_neu (
          id          INTEGER PRIMARY KEY,
          antrag_id   INTEGER REFERENCES antrag(id) ON DELETE CASCADE,
          typ         TEXT NOT NULL
                      CHECK (typ IN ('eingang', 'genehmigt', 'abgelehnt', 'orga')),
          empfaenger  TEXT NOT NULL,
          betreff     TEXT NOT NULL,
          body        TEXT NOT NULL,
          versuche    INTEGER NOT NULL DEFAULT 0,
          gesendet_am TEXT,
          letzter_fehler TEXT,
          naechster_versuch TEXT,
          created_at  TEXT NOT NULL
        );
        INSERT INTO mail_out_neu ({spalten}) SELECT {spalten} FROM mail_out;
        DROP TABLE mail_out;
        ALTER TABLE mail_out_neu RENAME TO mail_out;
        CREATE INDEX IF NOT EXISTS idx_mail_out_offen ON mail_out (gesendet_am, versuche);
        COMMIT;
        """
        )
    finally:
        con.execute("PRAGMA foreign_keys = ON")
    return True


def _spalten_nachtragen(con: sqlite3.Connection) -> list:
    ergaenzt = []
    for tabelle, spalte, typ in NACHTRAEGLICHE_SPALTEN:
        vorhanden = {z["name"] for z in con.execute(f"PRAGMA table_info({tabelle})")}
        if spalte not in vorhanden:
            con.execute(f"ALTER TABLE {tabelle} ADD COLUMN {spalte} {typ}")
            ergaenzt.append(f"{tabelle}.{spalte}")
    return ergaenzt


def init() -> list:
    """Legt Verzeichnis, Datei und Schema an und zieht fehlende Spalten nach.

    Liefert die nachgetragenen Spalten, damit der Start sie protokollieren kann.
    """
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = verbinden()
    try:
        # WAL, damit der Mail-Worker nebenläufig lesen kann.
        con.execute("PRAGMA journal_mode = WAL")
        with con:
            con.executescript(SCHEMA.read_text(encoding="utf-8"))
            ergaenzt = _spalten_nachtragen(con)
        # Der Tabellenumbau braucht abgeschaltete Fremdschluessel und damit
        # eine eigene Transaktion – deshalb ausserhalb des with-Blocks.
        if _mail_out_umbauen(con):
            ergaenzt.append("mail_out.typ (Umbau: Typ 'orga' ergaenzt)")
        return ergaenzt
    finally:
        con.close()


def antrag_anlegen(werte: dict, remote_ip: str | None) -> int:
    """Speichert einen validierten Antrag und liefert dessen Nummer."""
    with transaktion() as con:
        cur = con.execute(
            """
            INSERT INTO antrag (
                vorname, nachname, funktion, kategorie, email, telefon,
                kennzeichen, bemerkung, status, created_at, remote_ip
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'neu', ?, ?)
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
                jetzt(),
                remote_ip,
            ),
        )
        return int(cur.lastrowid)


# --- Backoffice-Abfragen (Schritt 4) ---------------------------------------

# Whitelist: die Sortierung kommt aus der URL und darf nie ins SQL durchgereicht
# werden.
SORTIERUNGEN = {
    "neueste": "created_at DESC, id DESC",
    "aelteste": "created_at ASC, id ASC",
    "name": "nachname COLLATE NOCASE, vorname COLLATE NOCASE",
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
    if suche:
        heuhaufen = " || ' ' || ".join(f"COALESCE({feld}, '')" for feld in _SUCHFELDER)
        teile = [f"INSTR(lower_u({heuhaufen}), lower_u(?)) > 0"]
        parameter.append(suche)
        # "kaxy123" soll auch "KA-XY 123" finden.
        gesuchtes_kfz = kfz_normalisieren(suche)
        if gesuchtes_kfz:
            teile.append("INSTR(kfz_norm(COALESCE(kennzeichen, '')), ?) > 0")
            parameter.append(gesuchtes_kfz)
        bedingungen.append("(" + " OR ".join(teile) + ")")

    wo = f"WHERE {' AND '.join(bedingungen)}" if bedingungen else ""
    ordnung = SORTIERUNGEN.get(sortierung, SORTIERUNGEN["neueste"])

    con = verbinden()
    try:
        return con.execute(
            f"SELECT * FROM antrag {wo} ORDER BY {ordnung}", parameter
        ).fetchall()
    finally:
        con.close()


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
    """Alle berechtigten Fahrzeuge, sortiert nach Nachname.

    Bewusst ohne Suchparameter: an der Strassensperre ist der Empfang mies,
    deshalb geht die vollstaendige Liste einmal in die Seite und gefiltert wird
    im Browser (app/static/durchfahrt.js).
    """
    con = verbinden()
    try:
        return con.execute(
            "SELECT * FROM antrag WHERE status IN (%s)"
            # Nach Kennzeichen, denn danach wird an der Sperre gesucht.
            # Normalisiert, damit KA-AB 1 und KAAB1 beieinander stehen, und
            # Zeilen ohne Kennzeichen ans Ende statt nach vorn.
            " ORDER BY (COALESCE(TRIM(kennzeichen), '') = ''),"
            "          kfz_norm(COALESCE(kennzeichen, '')),"
            "          nachname COLLATE NOCASE, vorname COLLATE NOCASE"
            % ", ".join("?" for _ in DURCHFAHRT_STATUS),
            DURCHFAHRT_STATUS,
        ).fetchall()
    finally:
        con.close()


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
