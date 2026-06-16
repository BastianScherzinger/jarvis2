-- JARVIS LeadHunter — Supabase-Migration (Juni 2026)
-- Neue Felder aus Säule 3 (echte Bewertung), Säule 4 (Bilder) und Säule 6 (Auto-Mail).
-- Idempotent: ADD COLUMN IF NOT EXISTS. Im Supabase SQL-Editor ausführen.

ALTER TABLE jarvis_leads ADD COLUMN IF NOT EXISTS sicherheit            integer DEFAULT 0;
ALTER TABLE jarvis_leads ADD COLUMN IF NOT EXISTS erwartungswert_euro   integer DEFAULT 0;
ALTER TABLE jarvis_leads ADD COLUMN IF NOT EXISTS sicherheit_breakdown  text;
ALTER TABLE jarvis_leads ADD COLUMN IF NOT EXISTS foto_urls             text;
ALTER TABLE jarvis_leads ADD COLUMN IF NOT EXISTS email_alle            text;
ALTER TABLE jarvis_leads ADD COLUMN IF NOT EXISTS ansprechpartner       text;
ALTER TABLE jarvis_leads ADD COLUMN IF NOT EXISTS email_status          text DEFAULT 'entwurf';
ALTER TABLE jarvis_leads ADD COLUMN IF NOT EXISTS email_opt_out         integer DEFAULT 0;

-- Schneller Sortier-Index für „sicherstes Geld zuerst"
CREATE INDEX IF NOT EXISTS idx_jarvis_leads_erwartungswert
  ON jarvis_leads (erwartungswert_euro DESC, sicherheit DESC);

-- Hinweis Railway-Leadsite (read-only):
--   Eigene Policy für anon-Key: nur SELECT auf jarvis_leads erlauben,
--   INSERT/UPDATE/DELETE bleiben dem service_role-Key (CloudSync) vorbehalten.
