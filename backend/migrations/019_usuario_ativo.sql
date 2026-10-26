-- Desativar usuário em vez de excluir.
--
-- Excluir apaga o histórico junto; desativar tira o acesso e mantém os dados
-- visíveis para o admin. Quem já está cadastrado continua ativo.
ALTER TABLE users ADD COLUMN IF NOT EXISTS ativo BOOLEAN NOT NULL DEFAULT TRUE;
