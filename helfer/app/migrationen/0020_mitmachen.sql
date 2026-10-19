-- Helfer werden ohne Veranstaltung (Lastenheft C-10).
--
-- Wer sich unter /mitmachen meldet, steht als gewöhnliche Person in
-- helfer – nur noch ohne Veranstaltung. Hier steht, wann das war: für den
-- Hinweis im Backoffice und damit nie bestätigte Einträge nach der Frist
-- wieder verschwinden (versand.fristen).
ALTER TABLE helfer ADD COLUMN mitmachen_am TEXT;
