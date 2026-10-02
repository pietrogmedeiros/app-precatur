-- Verificação por WhatsApp antes de mostrar o valor da simulação.
--
-- O código fica guardado como hash: se o banco vazar, ninguém usa os códigos
-- pendentes. tentativas/expira_em evitam força bruta, e enviado_em controla o
-- intervalo mínimo entre reenvios.

CREATE TABLE IF NOT EXISTS phone_verifications (
  id             BIGSERIAL PRIMARY KEY,
  simulation_id  BIGINT      NOT NULL REFERENCES simulations (id) ON DELETE CASCADE,
  telefone       TEXT        NOT NULL,
  codigo_hash    TEXT        NOT NULL,
  tentativas     INTEGER     NOT NULL DEFAULT 0,
  enviado_em     TIMESTAMPTZ NOT NULL DEFAULT now(),
  expira_em      TIMESTAMPTZ NOT NULL,
  verificado_em  TIMESTAMPTZ,
  ip             TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_verif_simulacao ON phone_verifications (simulation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_verif_telefone  ON phone_verifications (telefone, created_at DESC);

-- Marca na própria simulação quando o telefone foi confirmado.
ALTER TABLE simulations ADD COLUMN IF NOT EXISTS verificado_em TIMESTAMPTZ;
