-- Der Assistent (Lastenheft 3.1: A-02 bis A-05).
--
-- A-03: wozu ein Bereich passt – draußen an der Strecke, mit Menschen,
-- anpacken, fahren (selbstanmeldung.VORLIEBEN). Die Orga hakt es je Bereich
-- an. Leer heißt: passt zu allem. Sonst verschwände ein Bereich aus den
-- Vorschlägen, nur weil niemand an die Haken gedacht hat.
--
-- Was die Person selbst angibt, steht schon seit 0004 in
-- teilnahme.vorlieben.
ALTER TABLE bereich
    ADD COLUMN vorlieben TEXT[] NOT NULL DEFAULT '{}';
