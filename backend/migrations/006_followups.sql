-- Wiki Sales · Follow-ups.
-- Modelos de mensagem em texto puro, criados por qualquer usuário e visíveis a
-- todos (biblioteca compartilhada do time comercial). O autor é guardado por id
-- (dono canônico, usado na permissão de editar/excluir) e também por e-mail/nome
-- para exibição — assim a autoria continua legível se o usuário for removido.

CREATE TABLE IF NOT EXISTS followups (
  id              BIGSERIAL PRIMARY KEY,
  title           TEXT        NOT NULL,
  body            TEXT        NOT NULL,
  created_by_id   BIGINT      REFERENCES users (id) ON DELETE SET NULL,
  created_by      TEXT,
  created_by_name TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_followups_created ON followups (created_at DESC);
