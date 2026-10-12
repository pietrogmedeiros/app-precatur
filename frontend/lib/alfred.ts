// Cliente do Alfred — a base de consulta de precatórios. Conversa com
// /api/alfred, que o Express encaminha para o serviço Python ao lado.
//
// Duas regras herdadas do Alfred e preservadas aqui:
//   · CPF sai MASCARADO por padrão; só o papel "completo" vê inteiro.
//   · CPF NUNCA vai em URL — a busca é POST, porque o log de acesso registra o
//     caminho da requisição.

import { getToken, clearSession } from "./auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

export interface Eu { papel: "leitor" | "completo"; configurado: boolean }
export interface SaudeAlfred { ok: boolean; precatorios: number }

export interface ItemBusca {
  id: number;
  numero: string;
  tribunal: string;
  ordem: number | null;
  credor: string | null;
  cpf_cnpj: string | null;
  municipio: string | null;
  uf: string | null;
  valor: number | null;
  acumulado?: number | null;
}

export interface RespostaBusca {
  criterio: string;
  total: number;
  total_encontrado: number;
  pagina: number;
  limite: number;
  paginas: number;
  itens: ItemBusca[];
  explicacao?: string | null;
}

export interface Parecer {
  precatorio: {
    numero: string; numero_normalizado: string; numero_origem: string | null;
    tribunal: string; natureza: string | null; ano_orcamento: number | null;
    valor: number | null; situacao: string | null; superpreferencia: string | null;
    suspenso: boolean; coletado_em: string | null;
    numero_eproc?: string | null; numero_eproc_fmt?: string | null;
  };
  credor: {
    nome: string | null; cpf_cnpj: string | null; cpf_mascarado: boolean;
    advogado: string | null; fonte_nome: string | null;
  };
  devedor: {
    ente: string | null; ibge: string | null; municipio: string | null;
    uf: string | null; regime: string | null; rcl: number | null;
  };
  edital_acordo: Record<string, unknown> & {
    tem?: boolean; aberto?: boolean; edital?: string; situacao?: string;
    observacao?: string; desagio_min_pct?: number; desagio_max_pct?: number;
    inscricao_abre?: string; inscricao_fecha?: string; url?: string; fonte?: string;
  } | null;
  avisos: string[];
  pagamento: Record<string, any> | null;
  fila: Record<string, any> | null;
  projecao: Record<string, any> | null;
  id?: number;
}

export interface RespostaParecer { total: number; pareceres: Parecer[] }

/** Linha da busca de devedor: só metadado agregado, nenhum dado de credor. */
export interface Devedor {
  chave: string;
  nome: string;
  uf: string | null;
  tipo: string;            // "municipio" | "orgao"
  regime?: string | null;
  n_orgaos?: number;
  n?: number;              // quantos precatórios
  valor?: number | null;   // estoque
  tribunais?: string[];
}

export interface Ente {
  id: number; ente: string; tribunal: string;
  municipio: string | null; uf: string | null; n: number;
}

export interface FilaDoEnte {
  ente: string | null; tribunal: string | null;
  total: number; offset: number; itens: ItemBusca[];
}

async function pedir<T>(caminho: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_URL}/api/alfred${caminho}`, {
    cache: "no-store",
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (res.status === 401 && !getToken()) {
    clearSession();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new Error("Sessão expirada.");
  }
  if (!res.ok) {
    const corpo = await res.json().catch(() => ({}));
    const msg = corpo?.message ?? corpo?.detail ?? `A consulta respondeu ${res.status}.`;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return (await res.json()) as T;
}

export const eu = () => pedir<Eu>("/eu");
export const saude = () => pedir<SaudeAlfred>("/saude");

export const buscar = (termo: string, pagina = 1, limite = 50, ordem: "valor" | "nome" = "valor") =>
  pedir<RespostaBusca>("/busca", {
    method: "POST",
    body: JSON.stringify({ termo, pagina, limite, ordem }),
  });

export const parecerPorNumero = (numero: string, completo = false) =>
  pedir<RespostaParecer>(`/precatorio/${encodeURIComponent(numero)}${completo ? "?completo=1" : ""}`);

export const parecerPorId = (id: number, completo = false) =>
  pedir<RespostaParecer>(`/parecer_id/${id}${completo ? "?completo=1" : ""}`);

export const buscarDevedores = (q: string) =>
  pedir<{ q: string; itens: Devedor[] }>(`/devedores?q=${encodeURIComponent(q)}`);

export const saudeDoEnte = (chave: string) =>
  pedir<Record<string, any>>(`/ente/${encodeURIComponent(chave)}`);

export const listarEntes = () => pedir<{ total: number; entes: Ente[] }>("/entes");

export const filaDoEnte = (id: number, offset = 0, limite = 100) =>
  pedir<FilaDoEnte>(`/entes/${id}/fila?offset=${offset}&limite=${limite}`);

export const municipio = (ibge: string) =>
  pedir<Record<string, any>>(`/municipio/${encodeURIComponent(ibge)}`);

/** PDF do parecer — gerado no servidor, com a máscara decidida pelo papel. */
export async function parecerPdf(id: number, completo = false): Promise<{ blob: Blob; nome: string }> {
  const token = getToken();
  const res = await fetch(
    `${API_URL}/api/alfred/parecer_id/${id}/pdf${completo ? "?completo=1" : ""}`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} }
  );
  if (!res.ok) throw new Error(`Não foi possível gerar o parecer (${res.status}).`);
  const disp = res.headers.get("content-disposition") ?? "";
  // O Alfred manda os dois: `filename="parecer.pdf"` (compatibilidade) e
  // `filename*=UTF-8''<credor - processo>.pdf`. Pela RFC 6266 o segundo vence —
  // ler o primeiro faria todo parecer baixar como "parecer.pdf".
  const estendido = /filename\*=UTF-8''([^;]+)/i.exec(disp);
  const simples = /filename="([^"]+)"/i.exec(disp);
  const bruto = estendido?.[1] ?? simples?.[1] ?? `parecer_${id}.pdf`;
  let nome = bruto;
  try { nome = decodeURIComponent(bruto); } catch { /* nome já legível */ }
  return { blob: await res.blob(), nome };
}

// ── formatação ─────────────────────────────────────────────────────────────

export function brl(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 2 });
}

/** Valores de estoque na casa dos bilhões cansam de ler inteiros. */
export function brlCurto(v: number | null | undefined): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 1e9) return `R$ ${(n / 1e9).toLocaleString("pt-BR", { maximumFractionDigits: 2 })} bi`;
  if (Math.abs(n) >= 1e6) return `R$ ${(n / 1e6).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} mi`;
  return brl(n);
}

export function numero(v: number | null | undefined): string {
  return Number.isFinite(Number(v)) ? Number(v).toLocaleString("pt-BR") : "—";
}

export function pct(v: number | null | undefined, casas = 1): string {
  return Number.isFinite(Number(v)) ? `${(Number(v) * 100).toFixed(casas).replace(".", ",")}%` : "—";
}

export function dataBr(v: string | null | undefined): string {
  if (!v) return "—";
  const d = String(v).slice(0, 10);
  const [a, m, dia] = d.split("-");
  return a && m && dia ? `${dia}/${m}/${a}` : String(v);
}
