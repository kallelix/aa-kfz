-- Stempelkarte und Abzeichen (Lastenheft 4.3: G-01, G-02, G-05).
--
-- Die Stempel und die meisten Abzeichen ergeben sich aus den Schichten
-- selbst. Nur eines nicht: ob jemand eine Schicht gerettet hat – sich
-- eingetragen, als sie unter ihrem Minimum war. Das zählt im Moment des
-- Eintragens und wird deshalb an der Einteilung vermerkt.
ALTER TABLE einteilung
    ADD COLUMN retter INTEGER NOT NULL DEFAULT 0 CHECK (retter IN (0, 1));
