-- Schema der Akkreditierungsdatenbank. Wird bei jedem Start idempotent
-- angewendet.

CREATE TABLE IF NOT EXISTS anmeldung (
  id          INTEGER PRIMARY KEY,
  vorname     TEXT NOT NULL,
  nachname    TEXT NOT NULL,
  firma       TEXT NOT NULL,
  email       TEXT NOT NULL,                  -- Pflicht: an der Mail haengen
                                              -- die bestaetigten Bedingungen
  telefon     TEXT,
  kommerziell INTEGER NOT NULL,               -- 0 | 1
  gegenleistung TEXT,                         -- NULL | gebuehr | bilderspende
  bemerkung   TEXT,

  status      TEXT NOT NULL DEFAULT 'neu'
              CHECK (status IN ('neu', 'ausgegeben')),
  badge_am    TEXT,                           -- Abholung am Orga-Buero
  badge_durch TEXT,                           -- Kuerzel des Ausgebenden

  gebuehr_bezahlt_am TEXT,                    -- nur bei gegenleistung=gebuehr
  bilder_erhalten_am TEXT,                    -- nur bei bilderspende
  erinnerung_am      TEXT,                    -- letzte Erinnerung an die Bilder

  -- Verlinkung auf Social Media, wenn gewuenscht. Gehoert zur Bilderspende:
  -- verlinkt wird, wer uns Bilder gibt.
  verlinkung   INTEGER NOT NULL DEFAULT 0,
  social_media TEXT,

  -- Zustimmungen mit Zeitstempel. Der Sicherheitshinweis ist bei einer
  -- Veranstaltung mit Sturzzonen mehr als Formalie, die Bildrechte sind eine
  -- Lizenz - beides gehoert belegt und nicht nur in einer Mail erwaehnt.
  sicherheit_ok_am TEXT NOT NULL,
  bildrechte_ok_am TEXT,

  created_at  TEXT NOT NULL,
  remote_ip   TEXT,                           -- nur fuer Missbrauchsfaelle

  CHECK (kommerziell IN (0, 1)),
  CHECK (gegenleistung IS NULL OR gegenleistung IN ('gebuehr', 'bilderspende')),
  -- Kommerziell heisst: eine Gegenleistung ist gewaehlt. Nicht kommerziell
  -- heisst: keine. Die Regel steht in der Validierung und hier als Netz.
  CHECK ((kommerziell = 1) = (gegenleistung IS NOT NULL)),
  -- Ohne zugestimmte Bildrechte keine Bilderspende.
  CHECK (gegenleistung IS NOT 'bilderspende' OR bildrechte_ok_am IS NOT NULL),
  CHECK (verlinkung IN (0, 1)),
  -- Verlinken koennen wir nur, wenn wir wissen wohin.
  CHECK (verlinkung = 0 OR COALESCE(TRIM(social_media), '') <> ''),
  -- Und nur bei Bilderspende - sonst posten wir keine Bilder von der Person.
  CHECK (verlinkung = 0 OR gegenleistung = 'bilderspende')
);

CREATE INDEX IF NOT EXISTS idx_anmeldung_status     ON anmeldung (status);
CREATE INDEX IF NOT EXISTS idx_anmeldung_created_at ON anmeldung (created_at);
CREATE INDEX IF NOT EXISTS idx_anmeldung_gegenleistung ON anmeldung (gegenleistung);

-- Ausgangs-Queue, gleiches Muster wie in der Kennzeichen-App.
CREATE TABLE IF NOT EXISTS mail_out (
  id          INTEGER PRIMARY KEY,
  anmeldung_id INTEGER REFERENCES anmeldung(id) ON DELETE CASCADE,
  typ         TEXT NOT NULL CHECK (typ IN ('eingang', 'erinnerung')),
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

-- Wenige Einstellungen, die zur Laufzeit aenderbar sein muessen.
CREATE TABLE IF NOT EXISTS einstellung (
  schluessel  TEXT PRIMARY KEY,
  wert        TEXT NOT NULL,
  geaendert_am TEXT NOT NULL
);
