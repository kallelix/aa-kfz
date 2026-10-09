-- Was eine Veranstaltung nutzt (Lastenheft V-08, Schritt 2.1b): Kennzeichen,
-- Presse, Helfer, Materialausgabe. Das Backoffice zeigt nur diese Reiter.
-- Vorhandene Veranstaltungen nutzen alles – so sahen sie bisher aus.

ALTER TABLE veranstaltung
  ADD COLUMN nutzt TEXT[] NOT NULL
      DEFAULT ARRAY['kennzeichen', 'presse', 'helfer', 'ausgabe']
      CHECK (nutzt <@ ARRAY['kennzeichen', 'presse', 'helfer', 'ausgabe']);
