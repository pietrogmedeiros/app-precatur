// Thin typed client for the backend API. The base URL comes from the
// NEXT_PUBLIC_API_URL env var so the same build works locally and on Vercel.

import { getToken, clearSession, type Role, type SessionUser } from "./auth";

// Empty default = same-origin: the browser calls /api/* and Next.js proxies it
// to the backend (see rewrites() in next.config.mjs). No CORS, works on the
// single-domain all-in-one deploy. Override only for a split front/back setup.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

export interface SummaryMetrics {
  total_leads: number;
  qualificados: number;
  convertidos: number;
  taxa_qualificacao: number;
  taxa_conversao: number;
  valor_pipeline: number;
}

export interface OwnerMetrics extends SummaryMetrics {
  owner: string;
}

export interface FunnelStage {
  stage: string;
  count: number;
}

export interface TimeseriesPoint {
  month: string;
  leads: number;
  convertidos: number;
  valor_pipeline: number;
}

export interface UserRecord {
  id: number;
  name: string;
  email: string;
  role: Role;
  phone: string | null;
  created_at: string;
  last_login_at: string | null;
}

export interface Me {
  id: number;
  name: string;
  email: string;
  role: Role;
  phone: string | null;
}

export interface Proposal {
  id: number;
  proposal_number: string | null;
  proposal_date: string | null;
  client_name: string;
  client_doc: string | null;
  client_contact: string | null;
  precatorio_number: string | null;
  tribunal: string | null;
  ente_devedor: string | null;
  natureza: string | null;
  valor_face: number;
  valor_proposta: number;
  desagio: number;
  forma_pagamento: string | null;
  validade: string | null;
  observacoes: string | null;
  responsavel: string | null;
  // Campos que saem no PDF. `observacoes_proposta` é impressa; `observacoes`
  // (acima) segue sendo registro interno.
  ano_pagamento_estado: number | null;
  observacoes_proposta: string | null;
  detalhes_processo: string | null;
  created_by: string | null;
  created_at: string;
}

export type ProposalInput = Omit<Proposal, "id" | "created_by" | "created_at">;

// Wiki Sales · modelo de follow-up compartilhado entre os usuários.
export interface Followup {
  id: number;
  title: string;
  body: string;
  created_by_id: number | null;
  created_by: string | null;
  created_by_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface FollowupInput {
  title: string;
  body: string;
}

// Precificação · tabela de preço máximo de compra por ente (fonte única no banco).
export interface PricingRow {
  year: string;
  values: number[]; // 4 trimestres, em % (76 = 76%)
  asset: string;
}

export interface PricingEntity {
  key: string;
  label: string;
  description: string;
  position: number;
  fixed_deduction: number;
  municipal_reference: boolean;
  rows: PricingRow[];
  updated_by: string | null;
  updated_at: string;
}

export interface PricingImport {
  federal?: PricingRow[];
  estadual?: PricingRow[];
  municipal?: PricingRow[];
}

// Captação · envio feito por cedente/advogado no formulário público.
export type SubmissionStatus = "novo" | "em_analise" | "aprovado" | "recusado";

export interface SubmissionFileMeta {
  id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
}

export interface Submission {
  id: number;
  nome: string;
  email: string;
  telefone: string;
  processo: string | null;
  referente_a: string | null;
  credor_advogado: string | null;
  honorarios: string | null;
  observacoes: string | null;
  status: SubmissionStatus;
  status_by: string | null;
  status_at: string | null;
  created_at: string;
  files: SubmissionFileMeta[];
}

// Envio público: sem token e com FormData (o navegador precisa definir o
// boundary do multipart, por isso não passa pelo helper `request`).
export async function enviarCaptacao(form: FormData): Promise<{ id: number; arquivos: number }> {
  const res = await fetch(`${API_URL}/api/captacao`, { method: "POST", body: form });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body?.message ?? `Não foi possível enviar (erro ${res.status}).`);
  return body;
}

// Calculadora pública · quanto a Precatur pagaria por um precatório.
export interface CalculoResposta {
  id: number;
  praca: { label: string; estimativa: boolean; observacao?: string };
  safra: string;
  ativo: string;
  trimestre: number;
  abatimento: number;
  bruto: number;
  honorarios: number;
  honorarios_pct?: number;
  ir: number;
  pss: number;
  preferencia: number;
  outras_despesas: number;
  liquido: number;
  percentual: number;
  proposta: number;
}

export interface CalculoEntrada {
  nome: string;
  email: string;
  telefone: string;
  processo?: string | null;
  esfera: "federal" | "estadual" | "municipal";
  uf?: string | null;
  municipio?: string | null;
  safra: string;
  ativo?: string | null;
  natureza?: "alimentar" | "comum";
  principal: number;
  juros: number;
  selic: number;
  honorarios_pct: number;
  ir_pct: number;
  ir_base: "principal" | "bruto";
  pss: number;
  preferencia: number;
  outras_despesas: number;
}

// Sem token: a calculadora é aberta por link, como o formulário de captação.
async function publico<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body?.message ?? `Não foi possível calcular (erro ${res.status}).`);
  return body as T;
}

export function safrasDaPraca(p: { esfera: string; uf?: string | null }) {
  const qs = new URLSearchParams({ esfera: p.esfera, ...(p.uf ? { uf: p.uf } : {}) });
  return publico<{ praca: { label: string; estimativa: boolean }; safras: string[]; ativos: string[] }>(
    `/api/calculo/safras?${qs.toString()}`
  );
}

// O cálculo NÃO devolve valores: manda um código por WhatsApp e devolve o id.
export interface CalculoPendente {
  id: number;
  verificacao: { telefone: string; expira_em: string };
}

export function verificarCodigo(id: number, codigo: string) {
  return publico<CalculoResposta>(`/api/calculo/${id}/verificar`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ codigo }),
  });
}

export function reenviarCodigo(id: number) {
  return publico<{ verificacao: { telefone: string; expira_em: string } }>(
    `/api/calculo/${id}/reenviar`,
    { method: "POST" }
  );
}

export interface Simulacao {
  id: number;
  esfera: string; uf: string | null; municipio: string | null;
  praca_label: string; estimativa: boolean; safra: string; ativo: string | null; natureza: string | null;
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

export interface ResumoPraca {
  esfera: string; uf: string | null; praca_label: string;
  simulacoes: number; leads: number; volume_liquido: number; volume_proposta: number;
}

export function calcularPrecatorio(entrada: CalculoEntrada) {
  return publico<CalculoPendente>("/api/calculo", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(entrada),
  });
}

// Deal hydrated from the Bitrix CRM (GET /api/bitrix/deal?ref=<link|id>).
// Only CRM-owned fields; every absent field is null (never omitted / "").
export interface BitrixDeal {
  dealId: string;
  clientName: string | null;
  clientDoc: string | null;
  clientContact: string | null;
  precatorioNumber: string | null;
  tribunal: string | null;
  enteDevedor: string | null;
  natureza: "alimentar" | "comum" | null;
  valorFace: number | null;
  valorProposta: number | null;
  meta: { fetchedAt: string; source: string };
}

async function request<T>(path: string, init?: RequestInit & { skipAuthRedirect?: boolean }): Promise<T> {
  const { skipAuthRedirect, ...fetchInit } = init ?? {};
  const token = getToken();
  const res = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    ...fetchInit,
    headers: {
      ...(fetchInit.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(fetchInit.headers ?? {}),
    },
  });
  // A 401 on a normal (already-authenticated) call means the session expired, so
  // we clear it and bounce to /login. But on the login call itself a 401 just
  // means wrong credentials — let it fall through so the real message surfaces
  // instead of a silent hard reload.
  if (res.status === 401 && !skipAuthRedirect) {
    clearSession();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new Error("Sessão expirada.");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    // Backend may reply with a nested envelope { error: { code, message } }
    // (e.g. /api/bitrix/deal) or a flat { message }. Support both.
    const message = body?.error?.message ?? body?.message;
    throw new Error(message ?? `API ${path} respondeu ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export interface LoginResult {
  token: string;
  user: SessionUser;
}

export async function login(email: string, password: string): Promise<LoginResult> {
  return request<LoginResult>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
    skipAuthRedirect: true,
  });
}

export interface MetabaseToken {
  token: string;
  instanceUrl: string;
}

export const api = {
  summary: () => request<SummaryMetrics>("/api/metrics/summary"),
  metabaseToken: () => request<MetabaseToken>("/api/metabase/token"),
  byOwner: () => request<OwnerMetrics[]>("/api/metrics/by-owner"),
  funnel: () => request<FunnelStage[]>("/api/metrics/funnel"),
  timeseries: () => request<TimeseriesPoint[]>("/api/metrics/timeseries"),
  users: {
    list: () => request<UserRecord[]>("/api/users"),
    create: (payload: { name: string; email: string; password: string; role: Role; phone: string }) =>
      request<UserRecord>("/api/users", { method: "POST", body: JSON.stringify(payload) }),
    update: (id: number, payload: { phone: string }) =>
      request<UserRecord>(`/api/users/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
    remove: (id: number) => request<void>(`/api/users/${id}`, { method: "DELETE" }),
  },
  me: () => request<Me>("/api/auth/me"),
  updateProfile: (payload: { phone: string }) =>
    request<Me>("/api/auth/profile", { method: "PATCH", body: JSON.stringify(payload) }),
  bitrixDeal: (ref: string) =>
    request<BitrixDeal>("/api/bitrix/deal?ref=" + encodeURIComponent(ref)),
  changePassword: (currentPassword: string, newPassword: string) =>
    request<{ ok: boolean }>("/api/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ currentPassword, newPassword }),
    }),
  proposals: {
    list: () => request<Proposal[]>("/api/propostas"),
    get: (id: number) => request<Proposal>(`/api/propostas/${id}`),
    create: (payload: ProposalInput) =>
      request<Proposal>("/api/propostas", { method: "POST", body: JSON.stringify(payload) }),
    remove: (id: number) => request<void>(`/api/propostas/${id}`, { method: "DELETE" }),
  },
  followups: {
    list: () => request<Followup[]>("/api/followups"),
    get: (id: number) => request<Followup>(`/api/followups/${id}`),
    create: (payload: FollowupInput) =>
      request<Followup>("/api/followups", { method: "POST", body: JSON.stringify(payload) }),
    update: (id: number, payload: FollowupInput) =>
      request<Followup>(`/api/followups/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
    remove: (id: number) => request<void>(`/api/followups/${id}`, { method: "DELETE" }),
  },
  captacao: {
    list: () => request<Submission[]>("/api/captacao"),
    get: (id: number) => request<Submission>(`/api/captacao/${id}`),
    updateStatus: (id: number, status: SubmissionStatus) =>
      request<Submission>(`/api/captacao/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
    // O download exige token, então um <a href> puro não serve: busca com o
    // cabeçalho de autorização e entrega o arquivo ao navegador.
    baixarArquivo: async (id: number, fileId: number, filename: string) => {
      const res = await fetch(`${API_URL}/api/captacao/${id}/arquivos/${fileId}`, {
        headers: { ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}) },
      });
      if (!res.ok) throw new Error("Não foi possível baixar o arquivo.");
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    },
  },
  simulacoes: {
    list: () => request<{ itens: Simulacao[]; resumo: ResumoPraca[] }>("/api/simulacoes"),
  },
  pricing: {
    list: () => request<PricingEntity[]>("/api/pricing"),
    update: (
      key: string,
      payload: { rows?: PricingRow[]; fixed_deduction?: number; description?: string }
    ) =>
      request<PricingEntity[]>(`/api/pricing/${key}`, { method: "PUT", body: JSON.stringify(payload) }),
    import: (payload: PricingImport) =>
      request<{ updated: string[]; entities: PricingEntity[] }>("/api/pricing/import", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
  },
};
