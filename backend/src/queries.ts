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

// Shared metric expressions so aggregate and per-owner numbers always agree.
//   qualificados  = leads that reached (or passed) the qualified stage
//   convertidos   = leads that closed as won
//   taxa_qualif.  = qualificados / total_leads
//   taxa_convers. = convertidos / qualificados  (qualified -> won)
//   valor_pipeline = value still in the active pipeline (novo + qualificado)
const METRIC_COLUMNS = `
  COUNT(*)::int AS total_leads,
  COUNT(*) FILTER (WHERE status IN ('qualificado', 'convertido'))::int AS qualificados,
  COUNT(*) FILTER (WHERE status = 'convertido')::int AS convertidos,
  COALESCE(
    COUNT(*) FILTER (WHERE status IN ('qualificado', 'convertido'))::float
    / NULLIF(COUNT(*), 0), 0
  ) AS taxa_qualificacao,
  COALESCE(
    COUNT(*) FILTER (WHERE status = 'convertido')::float
    / NULLIF(COUNT(*) FILTER (WHERE status IN ('qualificado', 'convertido')), 0), 0
  ) AS taxa_conversao,
  COALESCE(SUM(value) FILTER (WHERE status IN ('novo', 'qualificado')), 0)::float AS valor_pipeline
`;

export async function getSummary(): Promise<SummaryMetrics> {
  const rows = await query<SummaryMetrics>(`SELECT ${METRIC_COLUMNS} FROM leads`);
  return (
    rows[0] ?? {
      total_leads: 0,
      qualificados: 0,
      convertidos: 0,
      taxa_qualificacao: 0,
      taxa_conversao: 0,
      valor_pipeline: 0,
    }
  );
}

export async function getByOwner(): Promise<OwnerMetrics[]> {
  return query<OwnerMetrics>(
    `SELECT owner, ${METRIC_COLUMNS}
     FROM leads
     GROUP BY owner
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
    `SELECT
       COUNT(*)::int AS total_leads,
       COUNT(*) FILTER (WHERE status IN ('qualificado', 'convertido'))::int AS qualificados,
       COUNT(*) FILTER (WHERE status = 'convertido')::int AS convertidos
     FROM leads`
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

export async function getTimeseries(): Promise<TimeseriesPoint[]> {
  return query<TimeseriesPoint>(
    `SELECT
       to_char(date_trunc('month', created_at), 'YYYY-MM') AS month,
       COUNT(*)::int AS leads,
       COUNT(*) FILTER (WHERE status = 'convertido')::int AS convertidos,
       COALESCE(SUM(value) FILTER (WHERE status IN ('novo', 'qualificado')), 0)::float AS valor_pipeline
     FROM leads
     GROUP BY 1
     ORDER BY 1`
  );
}
