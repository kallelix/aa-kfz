-- Helfer-Dashboard. Angelegt beim ersten Start, danach nur ergänzt
-- (siehe NACHTRAEGLICHE_SPALTEN in db.py).
--
-- Die CHECK-Bedingungen hängen an den Spalten und nicht als eigene Zeilen
-- dazwischen: SQLite lässt Tabellenbedingungen nur nach der letzten Spalte zu.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Eine Person, die Dienst tut. Aus dem alten Registrierungstool importiert
-- oder von Hand angelegt.
CREATE TABLE IF NOT EXISTS helfer (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL DEFAULT '',
    telefon       TEXT NOT NULL DEFAULT '',

    -- NULL heißt: nicht erhoben. Sonst 0 = Fleisch, 1 = vegetarisch.
    veggie        INTEGER CHECK (veggie IS NULL OR veggie IN (0, 1)),

    -- Normalisierte Größe und daneben, was die Person wirklich eingetippt
    -- hat. "Damen L" ist beim Bestellen eine Information, die "L" allein
    -- nicht mehr hergibt.
    tshirt        TEXT CHECK (tshirt IS NULL OR tshirt IN
                              ('XS', 'S', 'M', 'L', 'XL', 'XXL', '3XL', '4XL')),
    tshirt_roh    TEXT NOT NULL DEFAULT '',

    bemerkung     TEXT NOT NULL DEFAULT '',

    -- Name und Mail in Kleinschreibung. Verhindert, dass derselbe Mensch beim
    -- zweiten Import ein zweites Mal entsteht. Mehrere Namen unter einer
    -- Adresse sind ausdrücklich erlaubt: das sind mehrere Personen, die eine
    -- von ihnen angemeldet hat.
    schluessel    TEXT NOT NULL UNIQUE,

    aktiv         INTEGER NOT NULL DEFAULT 1 CHECK (aktiv IN (0, 1)),
    angelegt_am   TEXT NOT NULL,
    geaendert_am  TEXT
);

-- Ein Zeitslot, für den Leute gebraucht werden. Fachlicher Schlüssel ist
-- (liste, beginn, ende) – so steht es in den CSVs des alten Tools.
CREATE TABLE IF NOT EXISTS schicht (
    id            INTEGER PRIMARY KEY,
    liste         TEXT NOT NULL,

    -- Volle Zeitstempel, 'YYYY-MM-DD HH:MM'. Schichten über Mitternacht
    -- ("20:00 - 08:00") brauchen so keinen Sonderfall in den Abfragen.
    beginn        TEXT NOT NULL,
    ende          TEXT NOT NULL,

    -- Der Kalendertag, unter dem die Schicht einsortiert wird. Bei einer
    -- Nachtschicht ist das der Tag des Beginns, damit sie beim Abend steht
    -- und nicht am nächsten Morgen auftaucht.
    datum         TEXT NOT NULL,

    -- Wie viele Leute gebraucht werden. In den CSVs ist das die Anzahl der
    -- Zeilen: eine Zeile ist ein Platz, besetzt oder offen.
    bedarf        INTEGER NOT NULL DEFAULT 0 CHECK (bedarf >= 0),

    ort           TEXT NOT NULL DEFAULT '',
    hinweis       TEXT NOT NULL DEFAULT '',
    angelegt_am   TEXT NOT NULL,
    geaendert_am  TEXT,

    CHECK (ende > beginn),
    UNIQUE (liste, beginn, ende)
);

CREATE INDEX IF NOT EXISTS idx_schicht_zeit ON schicht (beginn, ende);
CREATE INDEX IF NOT EXISTS idx_schicht_tag  ON schicht (datum, beginn);

-- Wer welchen Platz besetzt. Eine Zeile ist ein Platz.
--
-- Bewusst OHNE UNIQUE (schicht_id, helfer_id): in den Bestandsdaten belegt
-- derselbe Name mehrfach Plätze derselben Schicht. Das sind entweder
-- Sammeleinträge eines Vereins oder Doppelanmeldungen – beides muss die Orga
-- sehen, nicht der Import stillschweigend wegwerfen. Der Bericht listet sie.
CREATE TABLE IF NOT EXISTS einteilung (
    id            INTEGER PRIMARY KEY,
    schicht_id    INTEGER NOT NULL REFERENCES schicht (id) ON DELETE CASCADE,
    helfer_id     INTEGER NOT NULL REFERENCES helfer (id) ON DELETE CASCADE,

    -- 'import' oder 'hand'. Ein erneuter Import fasst nur seine eigenen an.
    quelle        TEXT NOT NULL DEFAULT 'hand'
                  CHECK (quelle IN ('import', 'hand')),
    kuerzel       TEXT NOT NULL DEFAULT '',
    bemerkung     TEXT NOT NULL DEFAULT '',
    eingeteilt_am TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_einteilung_schicht ON einteilung (schicht_id);
CREATE INDEX IF NOT EXISTS idx_einteilung_helfer  ON einteilung (helfer_id);

-- Was ein Import gemacht hat. Damit nachvollziehbar bleibt, woher die Daten
-- stammen, und ein zweiter Lauf sich mit dem ersten vergleichen lässt.
CREATE TABLE IF NOT EXISTS import_lauf (
    id            INTEGER PRIMARY KEY,
    art           TEXT NOT NULL CHECK (art IN ('schichten', 'helfer')),
    datei         TEXT NOT NULL DEFAULT '',
    zeilen        INTEGER NOT NULL DEFAULT 0,
    bericht       TEXT NOT NULL DEFAULT '',
    kuerzel       TEXT NOT NULL DEFAULT '',
    gelaufen_am   TEXT NOT NULL
);

-- Kleiner Schlüssel-Wert-Speicher, u. a. für den Monitor-Token.
CREATE TABLE IF NOT EXISTS einstellung (
    schluessel    TEXT PRIMARY KEY,
    wert          TEXT NOT NULL DEFAULT '',
    geaendert_am  TEXT NOT NULL
);

-- Das Programm der Rennserien, abgerufen von deren Websites.
--
-- Fachlicher Schlüssel ist (serie, datum, titel). beginn und ende dürfen NULL
-- sein: "ab 13.30 Uhr" hat kein Ende, "anschließend" nicht einmal einen
-- Anfang. Das steht so auf den Seiten und wird nicht erfunden.
CREATE TABLE IF NOT EXISTS programm (
    id            INTEGER PRIMARY KEY,
    serie         TEXT NOT NULL,
    titel         TEXT NOT NULL,
    datum         TEXT NOT NULL,
    beginn        TEXT,
    ende          TEXT,

    -- Was in der Tabelle stand, im Wortlaut. Macht nachvollziehbar, warum
    -- etwas als geändert gilt, und trägt die Fälle ohne Uhrzeit.
    tag_roh       TEXT NOT NULL DEFAULT '',
    zeit_roh      TEXT NOT NULL DEFAULT '',

    -- Von Hand geändert: der nächste Abruf meldet Abweichungen, überschreibt
    -- aber nicht. Die Orga gewinnt gegen die fremde Website.
    von_hand      INTEGER NOT NULL DEFAULT 0 CHECK (von_hand IN (0, 1)),

    -- Steht nicht mehr auf der Website. Bleibt stehen und wird angezeigt,
    -- statt still zu verschwinden.
    entfallen_am  TEXT,

    angelegt_am   TEXT NOT NULL,
    geaendert_am  TEXT,

    CHECK (ende IS NULL OR beginn IS NULL OR ende > beginn),
    UNIQUE (serie, datum, titel)
);

CREATE INDEX IF NOT EXISTS idx_programm_zeit ON programm (beginn, ende);

-- Jeder Abrufversuch, erfolgreich oder nicht. Das Backoffice zeigt daraus,
-- wann zuletzt etwas geklappt hat.
CREATE TABLE IF NOT EXISTS abruf_lauf (
    id            INTEGER PRIMARY KEY,
    serie         TEXT NOT NULL,
    erfolg        INTEGER NOT NULL DEFAULT 0 CHECK (erfolg IN (0, 1)),
    meldung       TEXT NOT NULL DEFAULT '',
    bericht       TEXT NOT NULL DEFAULT '',
    ausloeser     TEXT NOT NULL DEFAULT '',
    gelaufen_am   TEXT NOT NULL
);
