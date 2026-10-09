-- Einladen bei Anmeldestart (Lastenheft 3.3: C-08).
--
-- Wer aus dem Helferstamm zu einer Veranstaltung eingeladen wurde – damit
-- niemand dieselbe Einladung zweimal bekommt, auch wenn die Orga zweimal
-- klickt. Die Vorgemerkten (interesse) brauchen das nicht: ihre Zeile ist
-- weg, sobald die Mail unterwegs ist.
CREATE TABLE einladung (
    veranstaltung_id INTEGER NOT NULL
                     REFERENCES kern.veranstaltung (id) ON DELETE CASCADE,
    helfer_id     INTEGER NOT NULL REFERENCES helfer (id) ON DELETE CASCADE,
    wer           TEXT NOT NULL DEFAULT '',
    am            TEXT NOT NULL,
    PRIMARY KEY (veranstaltung_id, helfer_id)
);
