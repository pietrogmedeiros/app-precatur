-- Praça oculta: continua valendo para a calculadora pública (é o caso do
-- "Estadual — Regime Geral", que atende os estados sem tabela própria), mas
-- some da barra da Precificação para o time não cotar por ela sem querer.
ALTER TABLE pricing_entities ADD COLUMN IF NOT EXISTS hidden BOOLEAN NOT NULL DEFAULT false;
