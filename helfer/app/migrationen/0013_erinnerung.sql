-- Erinnerung vor der Schicht und Danke nach der Veranstaltung (Lastenheft
-- 3.5: C-02, G-07).
--
-- Wer welche dieser Mails zu welcher Veranstaltung schon bekommen hat –
-- damit jede genau einmal kommt, auch wenn der Worker zweimal läuft oder
-- die Orga zweimal klickt.
CREATE TABLE erinnerung (
    veranstaltung_id INTEGER NOT NULL
                     REFERENCES kern.veranstaltung (id) ON DELETE CASCADE,
    helfer_id     INTEGER NOT NULL REFERENCES helfer (id) ON DELETE CASCADE,
    art           TEXT NOT NULL CHECK (art IN ('vorher', 'danke')),
    am            TEXT NOT NULL,
    PRIMARY KEY (veranstaltung_id, helfer_id, art)
);
