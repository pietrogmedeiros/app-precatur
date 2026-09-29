-- Captação: envios feitos por cedentes/advogados pelo formulário público.
--
-- Os anexos ficam no próprio Postgres (bytea) de propósito: o contêiner do
-- EasyPanel é reconstruído a cada deploy e, sem volume configurado, arquivos em
-- disco sumiriam. No banco eles sobrevivem ao rebuild e entram no backup.
--
-- ip/user_agent são guardados só para conter abuso no endpoint público (ele não
-- exige login) e para investigar envios suspeitos.

CREATE TABLE IF NOT EXISTS submissions (
  id               BIGSERIAL PRIMARY KEY,
  nome             TEXT        NOT NULL,  -- nome ou escritório
  email            TEXT        NOT NULL,
  telefone         TEXT        NOT NULL,  -- telefone / WhatsApp
  processo         TEXT,                  -- número do processo de execução
  referente_a      TEXT,                  -- a quem se refere o crédito
  credor_advogado  TEXT,
  honorarios       TEXT,
  observacoes      TEXT,
  status           TEXT        NOT NULL DEFAULT 'novo'
                   CHECK (status IN ('novo', 'em_analise', 'aprovado', 'recusado')),
  status_by        TEXT,
  status_at        TIMESTAMPTZ,
  ip               TEXT,
  user_agent       TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS submission_files (
  id             BIGSERIAL PRIMARY KEY,
  submission_id  BIGINT      NOT NULL REFERENCES submissions (id) ON DELETE CASCADE,
  filename       TEXT        NOT NULL,
  content_type   TEXT        NOT NULL,
  size_bytes     INTEGER     NOT NULL,
  data           BYTEA       NOT NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_submissions_created ON submissions (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_submissions_status ON submissions (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_submission_files_sub ON submission_files (submission_id);
