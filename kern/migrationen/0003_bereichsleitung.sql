-- Bereichsleitung als eigene Rolle (Lastenheft B-02, Schritt 2.1a). Sie
-- sieht im Helferbereich nur die Bereiche, die sie leitet; welche das sind,
-- steht im Helferbereich (helfer.bereich_leitung).
--
-- Dazu eine Nummer am Konto: wer einen Bereich leitet, muss am
-- Veranstaltungstag anrufbar sein, und die Nummer gehört in Erinnerungsmail
-- und Ausdruck (C-02, L-02).

ALTER TABLE konto DROP CONSTRAINT konto_rolle_check;
ALTER TABLE konto ADD CONSTRAINT konto_rolle_check
  CHECK (rolle IN ('admin', 'orga', 'bereichsleitung', 'lesend'));

ALTER TABLE konto ADD COLUMN telefon TEXT NOT NULL DEFAULT '';
