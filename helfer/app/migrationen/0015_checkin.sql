-- Check-in zentral bei der Orga (Lastenheft 4.1: T-01 bis T-03).
--
-- Ob eine Veranstaltung ihn überhaupt hat, stellt sie ein – beim Angebot,
-- neben Shirt, Verpflegung und Party. Ohne Check-in bleibt alles, wie es war:
-- die Erinnerung schickt zum Treffpunkt, und niemand ist „noch nicht da“.
ALTER TABLE angebot
    ADD COLUMN checkin INTEGER NOT NULL DEFAULT 0 CHECK (checkin IN (0, 1));

-- Eingecheckt wird je Einteilung: wer morgens kommt, ist für alle seine
-- Schichten des Tages da. Wer 15 Minuten vor Beginn noch keinen Haken hat,
-- ist „noch nicht da“. Springer-Zeiten bekommen denselben Haken – dann weiß
-- die Orga, wer wirklich da ist.
ALTER TABLE einteilung
    ADD COLUMN eingecheckt_am TEXT,
    ADD COLUMN eingecheckt_von TEXT NOT NULL DEFAULT '';

ALTER TABLE verfuegbarkeit
    ADD COLUMN eingecheckt_am TEXT;

-- Der QR-Code für den Check-in reist mit der Erinnerung (C-02) – als Bild im
-- Anhang, die Mail selbst bleibt Text. Gespeichert wird nur, was er
-- enthält; das Bild entsteht beim Verschicken.
ALTER TABLE mail_out
    ADD COLUMN qr TEXT NOT NULL DEFAULT '';
