-- Freunde mitbringen (Lastenheft 4.5: G-06).
--
-- Wer über den Link einer anderen Person zur Anmeldung kam, zählt bei ihr
-- mit. Geht die einladende Person, bleibt die eingeladene – nur ohne den
-- Verweis.
ALTER TABLE helfer
    ADD COLUMN eingeladen_von INTEGER REFERENCES helfer (id) ON DELETE SET NULL;

CREATE INDEX idx_helfer_eingeladen_von ON helfer (eingeladen_von);
