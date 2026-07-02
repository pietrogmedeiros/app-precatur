-- Sales dashboard schema
-- A lead is the source of truth; all dashboard metrics are derived from this table.

CREATE TABLE IF NOT EXISTS leads (
  id          BIGSERIAL PRIMARY KEY,
  owner       TEXT        NOT NULL,
  status      TEXT        NOT NULL CHECK (status IN ('novo', 'qualificado', 'convertido', 'perdido')),
  value       NUMERIC(14, 2) NOT NULL DEFAULT 0,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_leads_owner   ON leads (owner);
CREATE INDEX IF NOT EXISTS idx_leads_status  ON leads (status);
CREATE INDEX IF NOT EXISTS idx_leads_created ON leads (created_at);
