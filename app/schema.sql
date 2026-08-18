-- Schema der Antragsdatenbank. Wird bei jedem Start idempotent angewendet.

CREATE TABLE IF NOT EXISTS antrag (
  id          INTEGER PRIMARY KEY,
  vorname     TEXT NOT NULL,
  nachname    TEXT NOT NULL,
  funktion    TEXT NOT NULL,
  kategorie   TEXT NOT NULL,                    -- Schlüssel aus KATEGORIEN (Env)
  email       TEXT,                             -- optional, mind. eines von email/telefon
  telefon     TEXT,                             -- optional
  kennzeichen TEXT,                             -- optional, amtliches Kfz-Kennzeichen
  bemerkung   TEXT,
  status      TEXT NOT NULL DEFAULT 'neu'
              CHECK (status IN ('neu', 'genehmigt', 'abgelehnt', 'ausgegeben')),
  entscheidung_am    TEXT,
  entscheidung_durch TEXT,                      -- Kürzel, frei eingetragen
  begruendung        TEXT,                      -- Pflicht bei Ablehnung
  tel_informiert_am  TEXT,                      -- für Anträge ohne Mailadresse
  created_at  TEXT NOT NULL,
  remote_ip   TEXT,                             -- nur für Missbrauchsfälle, kurz aufbewahren
  CHECK (
    COALESCE(NULLIF(TRIM(email), ''), NULLIF(TRIM(telefon), '')) IS NOT NULL
  )
);

CREATE INDEX IF NOT EXISTS idx_antrag_status     ON antrag (status);
CREATE INDEX IF NOT EXISTS idx_antrag_kategorie  ON antrag (kategorie);
CREATE INDEX IF NOT EXISTS idx_antrag_created_at ON antrag (created_at);

-- Ausgangs-Queue. Wird ab Schritt 6 (Mail-Worker) befüllt und abgearbeitet.
CREATE TABLE IF NOT EXISTS mail_out (
  id          INTEGER PRIMARY KEY,
  antrag_id   INTEGER REFERENCES antrag(id) ON DELETE CASCADE,
  typ         TEXT NOT NULL
              CHECK (typ IN ('eingang', 'genehmigt', 'abgelehnt', 'orga')),
  empfaenger  TEXT NOT NULL,
  betreff     TEXT NOT NULL,
  body        TEXT NOT NULL,
  versuche    INTEGER NOT NULL DEFAULT 0,
  gesendet_am TEXT,
  letzter_fehler TEXT,
  naechster_versuch TEXT,             -- Backoff: fruehestens ab diesem Zeitpunkt
  created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mail_out_offen ON mail_out (gesendet_am, versuche);

-- Wenige Einstellungen, die zur Laufzeit aenderbar sein muessen und deshalb
-- nicht in die Env gehoeren. Aktuell nur der Token fuer die oeffentliche
-- Durchfahrtsliste, der sich im Backoffice neu erzeugen laesst.
CREATE TABLE IF NOT EXISTS einstellung (
  schluessel  TEXT PRIMARY KEY,
  wert        TEXT NOT NULL,
  geaendert_am TEXT NOT NULL
);
