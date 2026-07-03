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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (res.status === 401) {
    clearSession();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new Error("Sessão expirada.");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.message ?? `API ${path} respondeu ${res.status}`);
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
  });
}

export const api = {
  summary: () => request<SummaryMetrics>("/api/metrics/summary"),
  byOwner: () => request<OwnerMetrics[]>("/api/metrics/by-owner"),
  funnel: () => request<FunnelStage[]>("/api/metrics/funnel"),
  timeseries: () => request<TimeseriesPoint[]>("/api/metrics/timeseries"),
  users: {
    list: () => request<UserRecord[]>("/api/users"),
    create: (payload: { name: string; email: string; password: string; role: Role }) =>
      request<UserRecord>("/api/users", { method: "POST", body: JSON.stringify(payload) }),
    remove: (id: number) => request<void>(`/api/users/${id}`, { method: "DELETE" }),
  },
};
