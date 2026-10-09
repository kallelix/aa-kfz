-- Goodies mit klarem Schalter und das Shirt mit Schnitt (Lastenheft V-07,
-- I-02, Schritt 2.1b).
--
-- goodies: gibt die Veranstaltung überhaupt etwas aus? Ohne Goodies gibt es
-- auch kein Shirt, und die Anmeldung fragt nach keiner Größe.
-- schnitte: beim Shirt Damen- und Herrenschnitt, sonst ein Schnitt für alle.
--
-- Wer bisher ein Shirt oder Goodies eingetragen hat, gibt welche aus.

ALTER TABLE angebot
    ADD COLUMN goodies INTEGER NOT NULL DEFAULT 0 CHECK (goodies IN (0, 1)),
    ADD COLUMN schnitte INTEGER NOT NULL DEFAULT 0 CHECK (schnitte IN (0, 1));

UPDATE angebot a SET goodies = 1
 WHERE a.shirt = 1
    OR EXISTS (SELECT 1 FROM goodie g WHERE g.veranstaltung_id = a.veranstaltung_id);
