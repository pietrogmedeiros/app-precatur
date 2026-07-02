-- Users table for authentication.
-- password holds a SHA-256 (hex) hash of the plaintext password.
-- Two roles: 'admin' (can manage users) and 'padrao' (dashboard only).

CREATE TABLE IF NOT EXISTS users (
  id          BIGSERIAL PRIMARY KEY,
  name        TEXT        NOT NULL,
  email       TEXT        NOT NULL UNIQUE,
  password    TEXT        NOT NULL,
  role        TEXT        NOT NULL DEFAULT 'padrao' CHECK (role IN ('admin', 'padrao')),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);
