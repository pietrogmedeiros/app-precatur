-- Registra o último login de cada usuário (atualizado a cada autenticação
-- bem-sucedida). NULL = usuário nunca acessou.
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;
