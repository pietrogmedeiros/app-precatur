-- Simulações feitas na calculadora pública (/calcular).
--
-- Toda simulação é guardada, mesmo sem contato: é o que permite ver o que o
-- mercado está consultando por praça. Quando a pessoa pede a proposta, a mesma
-- linha recebe os dados de contato e vira lead (contato_em preenchido).
--
-- Entradas e resultados ficam em colunas próprias, e não em JSON, porque a tela
-- soma e filtra por eles.

CREATE TABLE IF NOT EXISTS simulations (
  id              BIGSERIAL PRIMARY KEY,

  -- praça consultada
  esfera          TEXT           NOT NULL,
  uf              TEXT,
  municipio       TEXT,
  praca_label     TEXT           NOT NULL,
  estimativa      BOOLEAN        NOT NULL DEFAULT false,
  safra           TEXT           NOT NULL,
  ativo           TEXT,
  natureza        TEXT,

  -- o que a pessoa informou
  principal       NUMERIC(16, 2) NOT NULL DEFAULT 0,
  juros           NUMERIC(16, 2) NOT NULL DEFAULT 0,
  selic           NUMERIC(16, 2) NOT NULL DEFAULT 0,
  honorarios_pct  NUMERIC(6, 2)  NOT NULL DEFAULT 0,
  ir_pct          NUMERIC(6, 2)  NOT NULL DEFAULT 0,
  ir_base         TEXT,
  pss             NUMERIC(16, 2) NOT NULL DEFAULT 0,
  preferencia     NUMERIC(16, 2) NOT NULL DEFAULT 0,
  outras_despesas NUMERIC(16, 2) NOT NULL DEFAULT 0,

  -- o que a calculadora devolveu
  bruto           NUMERIC(16, 2) NOT NULL DEFAULT 0,
  honorarios      NUMERIC(16, 2) NOT NULL DEFAULT 0,
  ir              NUMERIC(16, 2) NOT NULL DEFAULT 0,
  liquido         NUMERIC(16, 2) NOT NULL DEFAULT 0,
  percentual      NUMERIC(6, 2)  NOT NULL DEFAULT 0,
  abatimento      NUMERIC(16, 2) NOT NULL DEFAULT 0,
  proposta        NUMERIC(16, 2) NOT NULL DEFAULT 0,

  -- preenchidos só quando a pessoa pede a proposta
  nome            TEXT,
  email           TEXT,
  telefone        TEXT,
  processo        TEXT,
  contato_em      TIMESTAMPTZ,

  ip              TEXT,
  user_agent      TEXT,
  created_at      TIMESTAMPTZ    NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_simulations_created ON simulations (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_simulations_praca   ON simulations (uf, esfera, safra);
-- Só os leads: a tela abre filtrada por quem deixou contato.
CREATE INDEX IF NOT EXISTS idx_simulations_lead    ON simulations (contato_em DESC) WHERE contato_em IS NOT NULL;
