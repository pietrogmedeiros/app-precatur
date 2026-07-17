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
  created_at: string;
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
  created_by: string | null;
  created_at: string;
}

export type ProposalInput = Omit<Proposal, "id" | "created_by" | "created_at">;

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
    create: (payload: { name: string; email: string; password: string; role: Role }) =>
      request<UserRecord>("/api/users", { method: "POST", body: JSON.stringify(payload) }),
    remove: (id: number) => request<void>(`/api/users/${id}`, { method: "DELETE" }),
  },
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
};
