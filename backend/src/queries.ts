import { query } from "./db";

export interface SummaryMetrics {
  total_leads: number;
  qualificados: number;
  convertidos: number;
  taxa_qualificacao: number; // 0..1
  taxa_conversao: number; // 0..1
  valor_pipeline: number;
}

export interface OwnerMetrics extends SummaryMetrics {
  owner: string;
}

// The source tables store already-aggregated snapshots (not raw leads):
//   dados_sales             -> one snapshot row per period (created_at)
//   dados_sales_individual  -> one snapshot row per owner, per period
// Rates are recomputed from the counts so they are always 0..1 regardless of
// how taxa_* is scaled in the source (0..1 vs 0..100).
const RATE_COLUMNS = `
  total_leads,
  qualificados,
  convertidos,
  COALESCE(qualificados::float / NULLIF(total_leads, 0), 0)  AS taxa_qualificacao,
  COALESCE(convertidos::float / NULLIF(qualificados, 0), 0)  AS taxa_conversao,
  COALESCE(valor_pipeline, 0)::float                          AS valor_pipeline
`;

const EMPTY_SUMMARY: SummaryMetrics = {
  total_leads: 0,
  qualificados: 0,
  convertidos: 0,
  taxa_qualificacao: 0,
  taxa_conversao: 0,
  valor_pipeline: 0,
};

// Latest snapshot from dados_sales.
export async function getSummary(): Promise<SummaryMetrics> {
  const rows = await query<SummaryMetrics>(
    `SELECT ${RATE_COLUMNS}
     FROM dados_sales
     ORDER BY created_at DESC
     LIMIT 1`
  );
  return rows[0] ?? EMPTY_SUMMARY;
}

// Latest snapshot per owner from dados_sales_individual.
export async function getByOwner(): Promise<OwnerMetrics[]> {
  return query<OwnerMetrics>(
    `SELECT owner, ${RATE_COLUMNS}
     FROM (
       SELECT DISTINCT ON (owner) *
       FROM dados_sales_individual
       ORDER BY owner, created_at DESC
     ) latest
     ORDER BY convertidos DESC, total_leads DESC`
  );
}

export interface FunnelStage {
  stage: string;
  count: number;
}

export async function getFunnel(): Promise<FunnelStage[]> {
  const rows = await query<{
    total_leads: number;
    qualificados: number;
    convertidos: number;
  }>(
    `SELECT total_leads, qualificados, convertidos
     FROM dados_sales
     ORDER BY created_at DESC
     LIMIT 1`
  );
  const r = rows[0] ?? { total_leads: 0, qualificados: 0, convertidos: 0 };
  return [
    { stage: "Leads", count: r.total_leads },
    { stage: "Qualificados", count: r.qualificados },
    { stage: "Convertidos", count: r.convertidos },
  ];
}

export interface TimeseriesPoint {
  month: string; // YYYY-MM
  leads: number;
  convertidos: number;
  valor_pipeline: number;
}

// One point per month: the latest snapshot within each month.
export async function getTimeseries(): Promise<TimeseriesPoint[]> {
  return query<TimeseriesPoint>(
    `SELECT
       to_char(date_trunc('month', created_at), 'YYYY-MM') AS month,
       total_leads::int   AS leads,
       convertidos::int   AS convertidos,
       COALESCE(valor_pipeline, 0)::float AS valor_pipeline
     FROM (
       SELECT DISTINCT ON (date_trunc('month', created_at))
         created_at, total_leads, convertidos, valor_pipeline
       FROM dados_sales
       ORDER BY date_trunc('month', created_at), created_at DESC
     ) monthly
     ORDER BY month`
  );
}
