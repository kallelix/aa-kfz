-- Dubletten zusammenführen (Lastenheft 3.2: I-06).
--
-- Zusammengeführt wird ohne neue Spalte: was der zweiten Person gehörte,
-- wandert zur ersten, dann wird die zweite gelöscht (db.zusammenfuehren).
-- Neu ist nur das Gegenteil – Paare, von denen die Orga gesagt hat: das
-- sind zwei Menschen. Sie stehen danach nicht mehr unter „Vielleicht
-- dieselbe Person“.
CREATE TABLE keine_dublette (
    a_id          INTEGER NOT NULL REFERENCES helfer (id) ON DELETE CASCADE,
    b_id          INTEGER NOT NULL REFERENCES helfer (id) ON DELETE CASCADE,
    wer           TEXT NOT NULL DEFAULT '',
    am            TEXT NOT NULL,
    PRIMARY KEY (a_id, b_id),
    CHECK (a_id < b_id)
);
