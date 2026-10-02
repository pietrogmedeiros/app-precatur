import { query } from "./db";

export interface Simulacao {
  id: number;
  esfera: string;
  uf: string | null;
  municipio: string | null;
  praca_label: string;
  estimativa: boolean;
  safra: string;
  ativo: string | null;
  natureza: string | null;
  principal: number; juros: number; selic: number;
  honorarios_pct: number; ir_pct: number; ir_base: string | null;
  pss: number; preferencia: number; outras_despesas: number;
  bruto: number; honorarios: number; ir: number; liquido: number;
  percentual: number; abatimento: number; proposta: number;
  nome: string | null; email: string | null; telefone: string | null; processo: string | null;
  contato_em: string | null;
  verificado_em: string | null;
  created_at: string;
}

const NUMERICAS = [
  "principal","juros","selic","honorarios_pct","ir_pct","pss","preferencia","outras_despesas",
  "bruto","honorarios","ir","liquido","percentual","abatimento","proposta",
] as const;

// pg devolve NUMERIC e BIGSERIAL como string — normaliza tudo que a tela soma.
function normalize(row: any): Simulacao {
  const out: any = { ...row, id: Number(row.id) };
  for (const c of NUMERICAS) out[c] = Number(row[c]);
  return out as Simulacao;
}

const COLUNAS = `
  id, esfera, uf, municipio, praca_label, estimativa, safra, ativo, natureza,
  principal, juros, selic, honorarios_pct, ir_pct, ir_base, pss, preferencia, outras_despesas,
  bruto, honorarios, ir, liquido, percentual, abatimento, proposta,
  nome, email, telefone, processo, contato_em, verificado_em, created_at
`;

export async function registraSimulacao(dados: Record<string, unknown>): Promise<Simulacao> {
  const rows = await query<any>(
    `INSERT INTO simulations (
       esfera, uf, municipio, praca_label, estimativa, safra, ativo, natureza,
       principal, juros, selic, honorarios_pct, ir_pct, ir_base, pss, preferencia, outras_despesas,
       bruto, honorarios, ir, liquido, percentual, abatimento, proposta, ip, user_agent,
       nome, email, telefone, processo
     ) VALUES (
       $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,
       $27,$28,$29,$30
     ) RETURNING ${COLUNAS}`,
    [
      dados.esfera, dados.uf, dados.municipio, dados.praca_label, dados.estimativa, dados.safra,
      dados.ativo, dados.natureza, dados.principal, dados.juros, dados.selic, dados.honorarios_pct,
      dados.ir_pct, dados.ir_base, dados.pss, dados.preferencia, dados.outras_despesas,
      dados.bruto, dados.honorarios, dados.ir, dados.liquido, dados.percentual, dados.abatimento,
      dados.proposta, dados.ip, dados.user_agent,
      dados.nome, dados.email, dados.telefone, dados.processo,
    ]
  );
  return normalize(rows[0]);
}

export async function buscaSimulacao(id: number): Promise<Simulacao | null> {
  const rows = await query<any>(`SELECT ${COLUNAS} FROM simulations WHERE id = $1`, [id]);
  return rows[0] ? normalize(rows[0]) : null;
}

export async function listaSimulacoes(): Promise<Simulacao[]> {
  const rows = await query<any>(`SELECT ${COLUNAS} FROM simulations ORDER BY created_at DESC LIMIT 500`);
  return rows.map(normalize);
}

export interface ResumoPraca {
  esfera: string;
  uf: string | null;
  praca_label: string;
  simulacoes: number;
  leads: number;
  volume_liquido: number;
  volume_proposta: number;
}

// Histórico por praça: o que o mercado anda consultando e quanto disso virou contato.
export async function resumoPorPraca(): Promise<ResumoPraca[]> {
  const rows = await query<any>(
    `SELECT esfera, uf, praca_label,
            COUNT(*)                                   AS simulacoes,
            COUNT(contato_em)                          AS leads,
            COALESCE(SUM(liquido), 0)                  AS volume_liquido,
            COALESCE(SUM(proposta), 0)                 AS volume_proposta
       FROM simulations
      GROUP BY esfera, uf, praca_label
      ORDER BY COUNT(*) DESC, praca_label`
  );
  return rows.map((r) => ({
    ...r,
    simulacoes: Number(r.simulacoes),
    leads: Number(r.leads),
    volume_liquido: Number(r.volume_liquido),
    volume_proposta: Number(r.volume_proposta),
  }));
}

export interface SerieMensal {
  mes: string; // "2026-10"
  simulacoes: number;
  leads: number;
  volume_proposta: number;
}

// Últimos 6 meses, incluindo os meses sem simulação — senão o gráfico "pula"
// períodos vazios e dá impressão errada de continuidade.
export async function serieMensal(): Promise<SerieMensal[]> {
  const rows = await query<any>(
    `WITH meses AS (
       SELECT to_char(generate_series(
                date_trunc('month', now()) - interval '5 months',
                date_trunc('month', now()), interval '1 month'), 'YYYY-MM') AS mes
     )
     SELECT m.mes,
            COUNT(s.id)                           AS simulacoes,
            COUNT(s.contato_em)                   AS leads,
            COALESCE(SUM(s.proposta), 0)          AS volume_proposta
       FROM meses m
       LEFT JOIN simulations s ON to_char(s.created_at, 'YYYY-MM') = m.mes
      GROUP BY m.mes ORDER BY m.mes`
  );
  return rows.map((r) => ({
    mes: r.mes,
    simulacoes: Number(r.simulacoes),
    leads: Number(r.leads),
    volume_proposta: Number(r.volume_proposta),
  }));
}

export interface Fatia {
  rotulo: string;
  total: number;
}

export async function porNatureza(): Promise<Fatia[]> {
  const rows = await query<any>(
    `SELECT COALESCE(natureza, 'não informada') AS rotulo, COUNT(*) AS total
       FROM simulations GROUP BY 1 ORDER BY 2 DESC`
  );
  return rows.map((r) => ({ rotulo: r.rotulo, total: Number(r.total) }));
}

export async function porAtivo(): Promise<Fatia[]> {
  const rows = await query<any>(
    `SELECT COALESCE(ativo, 'não informado') AS rotulo, COUNT(*) AS total
       FROM simulations GROUP BY 1 ORDER BY 2 DESC`
  );
  return rows.map((r) => ({ rotulo: r.rotulo, total: Number(r.total) }));
}

export async function apagaSimulacao(id: number): Promise<boolean> {
  const rows = await query<any>(`DELETE FROM simulations WHERE id = $1 RETURNING id`, [id]);
  return Boolean(rows[0]);
}
