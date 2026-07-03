-- Propostas de aquisição de precatório.
-- Cada linha é uma proposta gerada pelo painel (histórico). Valores em NUMERIC;
-- desagio é calculado no front (1 - proposta/face) e persistido para o histórico.

CREATE TABLE IF NOT EXISTS proposals (
  id                BIGSERIAL PRIMARY KEY,
  proposal_number   TEXT,
  proposal_date     TEXT,
  client_name       TEXT           NOT NULL,
  client_doc        TEXT,
  client_contact    TEXT,
  precatorio_number TEXT,
  tribunal          TEXT,
  ente_devedor      TEXT,
  natureza          TEXT,
  valor_face        NUMERIC(14, 2) NOT NULL DEFAULT 0,
  valor_proposta    NUMERIC(14, 2) NOT NULL DEFAULT 0,
  desagio           NUMERIC(6, 2)  NOT NULL DEFAULT 0,
  forma_pagamento   TEXT,
  validade          TEXT,
  observacoes       TEXT,
  responsavel       TEXT,
  created_by        TEXT,
  created_at        TIMESTAMPTZ    NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_proposals_created ON proposals (created_at DESC);
