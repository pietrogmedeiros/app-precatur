-- Novo perfil "juridico": enxerga somente a aba Precificação, sem editar nada.
-- A 002 criou a coluna com CHECK (role IN ('admin','padrao')); é preciso trocar
-- a restrição, senão qualquer INSERT/UPDATE com 'juridico' é rejeitado.
--
-- O nome da constraint é o padrão do Postgres para CHECK de coluna
-- (users_role_check). DROP ... IF EXISTS mantém a migration idempotente, já que
-- a pasta inteira é reaplicada a cada boot.

ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check
  CHECK (role IN ('admin', 'padrao', 'juridico'));
