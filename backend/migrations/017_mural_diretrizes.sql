-- Diretrizes de compra do Mural — o texto que vem ANTES dos entes.
--
-- Mudam com frequência (é a reclamação que originou isto) e hoje circulam por
-- WhatsApp: quem leu a versão de ontem não sabe que leu a de ontem. No mural
-- elas ficam no mesmo lugar onde o time já consulta até que safra pagamos.
--
-- Uma LINHA POR VERSÃO, e a vigente é a mais recente: assim o histórico sai de
-- graça (nada a sincronizar entre "atual" e "anterior"), e voltar atrás é
-- inserir de novo o texto antigo — não há UPDATE que apague o que havia.
CREATE TABLE IF NOT EXISTS mural_diretrizes (
  id        BIGSERIAL   PRIMARY KEY,
  texto     TEXT        NOT NULL,
  autor     TEXT,
  criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mural_diretrizes_data ON mural_diretrizes (criado_em DESC);
