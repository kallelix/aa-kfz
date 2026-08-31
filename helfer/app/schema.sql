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
    -- Bewusst OHNE CHECK auf die erlaubten Groessen. Die Liste steht in
    -- normalisieren.GROESSEN, und jeder Schreibweg prueft dagegen. Hier
    -- waere sie ein zweites Mal hinterlegt - an einer Stelle, die SQLite
    -- nicht aendern kann: eine Groesse dazuzunehmen hiesse, die Tabelle
    -- neu zu bauen. Genau das ist mit 5XL passiert.
    tshirt        TEXT,
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

-- Der Aufgabenplan der Orga: was rund um die Veranstaltung zu tun ist.
--
-- Bewusst eine eigene Tabelle und nicht, wie im Plan skizziert, eine
-- gemeinsame `eintrag`-Tabelle mit `kind` fuer Programm und Aufgabe. Im
-- Timetable waren beide von Hand gepflegt und teilten sich deshalb zurecht
-- eine Tabelle. Hier hat das Programm eine fremde Quelle und eine eigene
-- Abgleichlogik (von_hand, entfallen_am, serie, UNIQUE je Serie und Titel),
-- von der eine Aufgabe nichts braucht. Zusammengelegt haetten beide Haelften
-- Spalten getragen, die fuer sie nie gelten.
CREATE TABLE IF NOT EXISTS aufgabe (
    id            INTEGER PRIMARY KEY,
    titel         TEXT NOT NULL,

    -- Grobe Einordnung. 'sonstiges' faengt alles, was sich nicht zuordnen
    -- laesst - besser als eine erfundene Phase.
    phase         TEXT NOT NULL DEFAULT 'event'
                  CHECK (phase IN ('aufbau', 'event', 'abbau', 'sonstiges')),

    -- Ohne Datum landet die Aufgabe im Pool: zu tun, aber noch nicht
    -- terminiert. Das ist ein eigener Zustand und kein fehlender Wert.
    datum         TEXT,
    beginn        TEXT,
    ende          TEXT,

    ort           TEXT NOT NULL DEFAULT '',
    verantwortlich TEXT NOT NULL DEFAULT '',
    kontakt       TEXT NOT NULL DEFAULT '',
    notiz         TEXT NOT NULL DEFAULT '',

    status        TEXT NOT NULL DEFAULT 'offen'
                  CHECK (status IN ('offen', 'arbeit', 'erledigt')),

    angelegt_am   TEXT NOT NULL,
    geaendert_am  TEXT NOT NULL,
    kuerzel       TEXT NOT NULL DEFAULT '',

    -- Traegt den Konfliktschutz. Bewusst ein Zaehler und kein Zeitstempel:
    -- geaendert_am hat Sekundenaufloesung, zwei Speichervorgaenge in
    -- derselben Sekunde saehen damit gleich aus und der Schutz griffe nicht.
    -- Ein Zaehler ist exakt, unabhaengig von der Uhr - und bleibt es auch,
    -- wenn JETZT_FEST sie fuer eine Durchsicht anhaelt.
    version       INTEGER NOT NULL DEFAULT 1,

    -- Eine Zeit ohne Tag waere ortlos, und ein Ende vor dem Beginn falsch.
    CHECK (beginn IS NULL OR datum IS NOT NULL),
    CHECK (ende IS NULL OR (beginn IS NOT NULL AND ende > beginn))
);

CREATE INDEX IF NOT EXISTS idx_aufgabe_tag ON aufgabe (datum, beginn);

-- Ausleihe von Material: Funkgeraet, Headset, Ersatzakku.
--
-- Ausgegebene und zurueckgegebene Stueckzahlen stehen nebeneinander, statt
-- eine Ausleihe nur ganz oder gar nicht zurueckzunehmen: wer das Funkgeraet
-- bringt und den Ersatzakku behaelt, ist der Normalfall und kein Sonderfall.
CREATE TABLE IF NOT EXISTS ausleihe (
    id            INTEGER PRIMARY KEY,
    helfer_id     INTEGER NOT NULL REFERENCES helfer (id) ON DELETE CASCADE,

    -- Der Tag, fuer den ausgegeben wurde. Kein Schichtbezug: ein Funkgeraet
    -- wird fuer einen Tag geholt, nicht fuer eine einzelne Schicht, und wer
    -- es holt, steht oft auf mehreren. Optional bleibt es trotzdem.
    datum         TEXT,

    funke         INTEGER NOT NULL DEFAULT 0 CHECK (funke >= 0),
    headset       INTEGER NOT NULL DEFAULT 0 CHECK (headset >= 0),
    ersatzakku    INTEGER NOT NULL DEFAULT 0 CHECK (ersatzakku >= 0),

    funke_zurueck      INTEGER NOT NULL DEFAULT 0 CHECK (funke_zurueck >= 0),
    headset_zurueck    INTEGER NOT NULL DEFAULT 0 CHECK (headset_zurueck >= 0),
    ersatzakku_zurueck INTEGER NOT NULL DEFAULT 0 CHECK (ersatzakku_zurueck >= 0),

    bemerkung     TEXT NOT NULL DEFAULT '',
    ausgegeben_am TEXT NOT NULL,
    ausgegeben_von TEXT NOT NULL DEFAULT '',
    zurueck_am    TEXT,
    zurueck_von   TEXT NOT NULL DEFAULT '',

    -- Nichts auszugeben waere kein Vorgang.
    CHECK (funke + headset + ersatzakku > 0),
    -- Mehr zurueck als raus kann nicht sein.
    CHECK (funke_zurueck <= funke),
    CHECK (headset_zurueck <= headset),
    CHECK (ersatzakku_zurueck <= ersatzakku)
);

CREATE INDEX IF NOT EXISTS idx_ausleihe_offen ON ausleihe (zurueck_am);

-- Der Fahrzeugstamm. Baut sich beim Ausgeben von Schluesseln nebenbei auf:
-- wer ein Kennzeichen eintippt, das es noch nicht gibt, legt es damit an.
-- Beim naechsten Mal steht der Name schon da.
CREATE TABLE IF NOT EXISTS fahrzeug (
    id            INTEGER PRIMARY KEY,
    kennzeichen   TEXT NOT NULL,
    -- Nur Buchstaben und Ziffern, gross. Verhindert, dass "IL-A 123" und
    -- "ILA123" zwei Wagen werden.
    kennzeichen_norm TEXT NOT NULL UNIQUE,

    -- EIN Namensfeld, nicht Vorname und Nachname getrennt. Die Bestandsdaten
    -- geben die Trennung nicht her: dort stehen "Krelli", "Poessneck1" und
    -- "huettner m". Zwei Felder zu verlangen hiesse, an der Ausgabe eine
    -- Ordnung zu erzwingen, die es nicht gibt.
    name          TEXT NOT NULL DEFAULT '',
    bemerkung     TEXT NOT NULL DEFAULT '',
    angelegt_am   TEXT NOT NULL,
    geaendert_am  TEXT
);

-- Ausgabe und Ruecknahme eines Fahrzeugschluessels.
CREATE TABLE IF NOT EXISTS schluessel (
    id            INTEGER PRIMARY KEY,
    fahrzeug_id   INTEGER NOT NULL REFERENCES fahrzeug (id) ON DELETE CASCADE,

    -- Wer den Schluessel hat. Kann von der Person im Fahrzeugstamm
    -- abweichen: das Shuttle faehrt nicht immer derselbe.
    name          TEXT NOT NULL DEFAULT '',

    bemerkung     TEXT NOT NULL DEFAULT '',
    ausgegeben_am TEXT NOT NULL,
    ausgegeben_von TEXT NOT NULL DEFAULT '',
    zurueck_am    TEXT,
    zurueck_von   TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_schluessel_offen ON schluessel (zurueck_am);

-- Unterschriften bei Ausgabe und Ruecknahme.
--
-- Zwei Rollen in einer Tabelle: solange unterschrieben_am leer ist, ist die
-- Zeile die Warteschlange fuers Tablet; danach ist sie der Beleg.
--
-- Der WORTLAUT wird mitgespeichert, nicht nur ein Verweis auf den Vorgang.
-- Wer "1 Funkgeraet, 1 Headset, 2 Ersatzakkus" unterschreibt, hat das
-- unterschrieben - wird der Vorgang spaeter korrigiert, dokumentiert die
-- Unterschrift weiter den Stand, der auf dem Tablet stand. Ein Fremdschluessel
-- allein taete das nicht.
CREATE TABLE IF NOT EXISTS unterschrift (
    id            INTEGER PRIMARY KEY,

    art           TEXT NOT NULL
                  CHECK (art IN ('tshirt', 'material', 'schluessel')),
    vorgang_id    INTEGER NOT NULL,
    richtung      TEXT NOT NULL
                  CHECK (richtung IN ('ausgabe', 'rueckgabe')),

    titel         TEXT NOT NULL,
    wortlaut      TEXT NOT NULL,
    person        TEXT NOT NULL DEFAULT '',

    -- Warteschlange. Laeuft ein Eintrag ab, zeigt das Tablet ihn nicht mehr:
    -- ein abhandengekommener Link kann dann nichts anrichten, solange
    -- niemand am Tisch steht.
    angefordert_am TEXT NOT NULL,
    laeuft_ab_am  TEXT NOT NULL,
    kuerzel       TEXT NOT NULL DEFAULT '',

    -- Ergebnis. bild ist ein SVG-Pfad, kein Rasterbild: klein, scharf in
    -- jeder Groesse und ohne data:-URI, die die CSP ohnehin abweisen wuerde.
    unterschrieben_am TEXT,
    bild          TEXT,
    -- sha256 ueber Wortlaut, Bild und Zeitpunkt. Macht nicht faelschungs-
    -- sicher, aber nachtraegliche Aenderungen erkennbar.
    pruefsumme    TEXT,

    abgebrochen_am TEXT
);

CREATE INDEX IF NOT EXISTS idx_unterschrift_offen
    ON unterschrift (unterschrieben_am, abgebrochen_am, angefordert_am);
CREATE INDEX IF NOT EXISTS idx_unterschrift_vorgang
    ON unterschrift (art, vorgang_id);
