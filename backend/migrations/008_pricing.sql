-- Tabelas de preço máximo de compra (aba Precificação).
--
-- Antes viviam fixas dentro de um HTML avulso, e o "importar planilha" só
-- atualizava o navegador de quem importava — sumia no F5 e ninguém mais via.
-- Aqui viram fonte única para o time.
--
-- rows: [{ "year": "2026", "values": [76, 80, 80, 80], "asset": "Precatório" }]
--   values = % do valor cheio por trimestre (1º a 4º). 76 significa 76%.
-- municipal_reference: o ente segue a curva do Regime Geral Municipal. As linhas
--   NÃO são copiadas — a API resolve na leitura, então as duas nunca divergem
--   (no HTML eram cópias que só andavam juntas se alguém lembrasse de importar).
-- fixed_deduction: abatimento fixo em R$ sobre a proposta calculada (regra RJ).

CREATE TABLE IF NOT EXISTS pricing_entities (
  key                 TEXT PRIMARY KEY,
  label               TEXT           NOT NULL,
  description         TEXT           NOT NULL DEFAULT '',
  position            INTEGER        NOT NULL DEFAULT 0,
  fixed_deduction     NUMERIC(14, 2) NOT NULL DEFAULT 0,
  municipal_reference BOOLEAN        NOT NULL DEFAULT false,
  rows                JSONB          NOT NULL DEFAULT '[]'::jsonb,
  updated_by          TEXT,
  updated_at          TIMESTAMPTZ    NOT NULL DEFAULT now()
);

-- Toda alteração guarda a versão anterior: uma importação errada define quanto
-- a empresa paga, então precisa dar para ver e restaurar o que havia antes.
CREATE TABLE IF NOT EXISTS pricing_history (
  id              BIGSERIAL PRIMARY KEY,
  entity_key      TEXT           NOT NULL,
  rows            JSONB          NOT NULL,
  fixed_deduction NUMERIC(14, 2) NOT NULL,
  description     TEXT           NOT NULL,
  changed_by      TEXT,
  source          TEXT           NOT NULL,  -- 'import' | 'edit'
  changed_at      TIMESTAMPTZ    NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pricing_history_entity ON pricing_history (entity_key, changed_at DESC);

-- Carga inicial com os valores da "calculadora final de precificação.html".
-- ON CONFLICT DO NOTHING: roda a cada boot (como toda migration aqui) mas nunca
-- sobrescreve o que o time já atualizou.
INSERT INTO pricing_entities (key, label, description, position, fixed_deduction, municipal_reference, rows) VALUES
  ('federal', 'Federal', 'Regime Geral Federal — preço máximo de compra por safra e trimestre.', 1, 0, false,
   '[{"year":"2026","values":[76,80,80,80],"asset":"Precatório"},
     {"year":"2027","values":[57,62,66,70],"asset":"Precatório"},
     {"year":"2028","values":[44,47,50,54],"asset":"Direito Creditório"},
     {"year":"2029","values":[34,36,39,41],"asset":"Direito Creditório"},
     {"year":"2030","values":[25,27,29,31],"asset":"Direito Creditório"},
     {"year":"2031","values":[18,20,22,23],"asset":"Direito Creditório"}]'),
  ('estadual', 'Estadual — Regime Geral', 'Regime Geral Estadual — preço máximo de compra por safra e trimestre.', 2, 0, false,
   '[{"year":"2026","values":[66,72,78,80],"asset":"Precatório"},
     {"year":"2027","values":[52,56,61,66],"asset":"Precatório"},
     {"year":"2028","values":[38,44,52,61],"asset":"Direito Creditório"},
     {"year":"2029","values":[33,38,44,50],"asset":"Direito Creditório"},
     {"year":"2030","values":[25,29,33,38],"asset":"Direito Creditório"},
     {"year":"2031","values":[18,21,25,29],"asset":"Direito Creditório"}]'),
  ('municipal', 'Municipal — Regime Geral', 'Regime Geral Municipal — preço máximo de compra por safra e trimestre.', 3, 0, false,
   '[{"year":"2026","values":[63,69,76,80],"asset":"Precatório"},
     {"year":"2027","values":[43,48,53,58],"asset":"Precatório"},
     {"year":"2028","values":[30,33,36,39],"asset":"Direito Creditório"},
     {"year":"2029","values":[24,27,29,32],"asset":"Direito Creditório"},
     {"year":"2030","values":[17,18,20,22],"asset":"Direito Creditório"},
     {"year":"2031","values":[14,15,17,18],"asset":"Direito Creditório"}]'),
  ('bahia', 'Bahia', 'Regra comercial específica para o Estado da Bahia.', 4, 0, false,
   '[{"year":"Até 2023","values":[30,30,30,30],"asset":"Precatório"},
     {"year":"2024 e 2025","values":[22,22,22,22],"asset":"Precatório"},
     {"year":"2026 e 2027","values":[15,15,15,15],"asset":"Precatório"},
     {"year":"2028","values":[10,10,10,10],"asset":"Precatório"}]'),
  ('rj', 'Rio de Janeiro', 'Regra comercial específica para o Estado do Rio de Janeiro.', 5, 6000, false,
   '[{"year":"Até 2026","values":[27,27,27,27],"asset":"Precatório"},
     {"year":"2027","values":[17,17,17,17],"asset":"Precatório"},
     {"year":"2028","values":[10,10,10,10],"asset":"Precatório"}]'),
  ('mg', 'Minas Gerais e Belo Horizonte', 'Precificação por tipo de ativo. A regra poderá ser revisada quando o edital abrir.', 6, 0, false,
   '[{"year":"Regra vigente","values":[47,47,47,47],"asset":"Precatório"},
     {"year":"Regra vigente","values":[36,36,36,36],"asset":"Direito Creditório"}]'),
  ('paraiba', 'Paraíba', 'Regra comercial específica para o Estado da Paraíba.', 7, 0, false,
   '[{"year":"Até 2017","values":[23,23,23,23],"asset":"Precatório"},
     {"year":"2018 a 2025","values":[10,10,10,10],"asset":"Precatório"}]'),
  ('pernambuco', 'Pernambuco', 'Utiliza a mesma curva de precificação do Regime Geral Municipal.', 8, 0, true, '[]'),
  ('matoGrosso', 'Mato Grosso', 'Utiliza a mesma curva de precificação do Regime Geral Municipal.', 9, 0, true, '[]')
ON CONFLICT (key) DO NOTHING;
