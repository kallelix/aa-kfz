-- Datenschutz und Jugendschutz (Lastenheft 2.9: D-03, D-05, D-06).

ALTER TABLE helfer
    -- D-03: „Ihr dürft mich für künftige Veranstaltungen ansprechen“ –
    -- eigene, nicht vorangekreuzte Einwilligung. Ohne sie wird nach der
    -- Veranstaltung gelöscht (deploy/daten-loeschen.py). Widerruf in Mein
    -- Helferplatz setzt sie wieder auf NULL (D-05).
    ADD COLUMN stamm_einwilligung_am TEXT,
    -- D-06: unter 18 eine erziehungsberechtigte Person, die per Link
    -- bestätigt. Erst dann gilt die Anmeldung.
    ADD COLUMN eltern_name TEXT NOT NULL DEFAULT '',
    ADD COLUMN eltern_email TEXT NOT NULL DEFAULT '',
    ADD COLUMN eltern_bestaetigt_am TEXT,
    ADD COLUMN eltern_erinnert_am TEXT;
