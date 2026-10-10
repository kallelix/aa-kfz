-- Helferparty (Lastenheft 4.4: G-09).
--
-- Ob es eine gibt, steht schon beim Angebot (angebot.party). Hier, wann und
-- wo, und wer kommt – mit wie vielen Begleitpersonen, damit die Orga
-- Grillgut und Getränke planen kann.
CREATE TABLE party (
    veranstaltung_id INTEGER PRIMARY KEY
                     REFERENCES kern.veranstaltung (id) ON DELETE CASCADE,
    beginn        TEXT NOT NULL,
    ort           TEXT NOT NULL DEFAULT '',
    hinweis       TEXT NOT NULL DEFAULT '',
    geaendert_am  TEXT NOT NULL
);

-- Je Person eine Antwort. Begleitpersonen stehen bei der, die geantwortet
-- hat – für sich und alle, die sie mitangemeldet hat.
CREATE TABLE party_zusage (
    veranstaltung_id INTEGER NOT NULL
                     REFERENCES kern.veranstaltung (id) ON DELETE CASCADE,
    helfer_id     INTEGER NOT NULL REFERENCES helfer (id) ON DELETE CASCADE,
    kommt         INTEGER NOT NULL CHECK (kommt IN (0, 1)),
    begleitung    INTEGER NOT NULL DEFAULT 0 CHECK (begleitung BETWEEN 0 AND 20),
    am            TEXT NOT NULL,
    PRIMARY KEY (veranstaltung_id, helfer_id)
);

-- Einladung und Erinnerung am Tag gehen wie Erinnerung und Dank je
-- Veranstaltung und Person genau einmal.
ALTER TABLE erinnerung DROP CONSTRAINT erinnerung_art_check;
ALTER TABLE erinnerung ADD CONSTRAINT erinnerung_art_check
    CHECK (art IN ('vorher', 'danke', 'party', 'party_tag'));
