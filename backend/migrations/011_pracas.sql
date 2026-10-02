-- Praças: dá endereço às tabelas de preço (esfera / UF / município).
--
-- O modelo já era "regime geral + exceção" — Federal, Estadual e Municipal são
-- as regras gerais, e Bahia, RJ, MG, Paraíba, PE e MT são exceções. Estas
-- colunas só tornam isso explícito, para a calculadora pública resolver o preço
-- de qualquer praça do país: procura a regra mais específica e, não achando,
-- cai no regime geral da esfera.
--
-- NULL significa "vale para qualquer": esfera NULL vale para estadual e
-- municipal (caso de MG, que cobre o estado e Belo Horizonte); uf NULL é o
-- regime geral, válido em todo o país.

ALTER TABLE pricing_entities ADD COLUMN IF NOT EXISTS esfera    TEXT;
ALTER TABLE pricing_entities ADD COLUMN IF NOT EXISTS uf        TEXT;
ALTER TABLE pricing_entities ADD COLUMN IF NOT EXISTS municipio TEXT;

-- Endereço das 9 tabelas que já existem. Só preenche onde ainda está vazio,
-- para não desfazer ajuste feito pelo time.
UPDATE pricing_entities SET esfera = 'federal'   WHERE key = 'federal'    AND esfera IS NULL;
UPDATE pricing_entities SET esfera = 'estadual'  WHERE key = 'estadual'   AND esfera IS NULL;
UPDATE pricing_entities SET esfera = 'municipal' WHERE key = 'municipal'  AND esfera IS NULL;

UPDATE pricing_entities SET esfera = 'estadual', uf = 'BA' WHERE key = 'bahia'      AND uf IS NULL;
UPDATE pricing_entities SET esfera = 'estadual', uf = 'RJ' WHERE key = 'rj'         AND uf IS NULL;
UPDATE pricing_entities SET esfera = 'estadual', uf = 'PB' WHERE key = 'paraiba'    AND uf IS NULL;
UPDATE pricing_entities SET esfera = 'estadual', uf = 'PE' WHERE key = 'pernambuco' AND uf IS NULL;
UPDATE pricing_entities SET esfera = 'estadual', uf = 'MT' WHERE key = 'matoGrosso' AND uf IS NULL;
-- MG vale para o estado E para Belo Horizonte, então fica sem esfera.
UPDATE pricing_entities SET uf = 'MG' WHERE key = 'mg' AND uf IS NULL;

CREATE INDEX IF NOT EXISTS idx_pricing_praca ON pricing_entities (uf, esfera);
