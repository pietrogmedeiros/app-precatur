-- Telefone do usuário — usado como contato do responsável no rodapé da proposta.
-- Nullable: usuários existentes começam sem telefone (admin/usuário preenchem depois);
-- a obrigatoriedade em novos cadastros é validada na API.
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT;
