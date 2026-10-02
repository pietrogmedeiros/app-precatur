-- Recuperação de senha por e-mail.
--
-- O token vai por e-mail e aqui fica só o hash: se o banco vazar, nenhum link
-- pendente é utilizável. Uso único (used_at) e validade curta (expires_at).

CREATE TABLE IF NOT EXISTS password_resets (
  id          BIGSERIAL PRIMARY KEY,
  user_id     BIGINT      NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  token_hash  TEXT        NOT NULL,
  expires_at  TIMESTAMPTZ NOT NULL,
  used_at     TIMESTAMPTZ,
  ip          TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_reset_token ON password_resets (token_hash);
CREATE INDEX IF NOT EXISTS idx_reset_user  ON password_resets (user_id, created_at DESC);
