// Cliente da calculadora de precatórios. Conversa com /api/calculadora, que o
// Express encaminha para o motor Python — o mesmo motor que o time já usa.
//
// Decisão que atravessa este arquivo: **os campos trafegam como TEXTO**, do
// jeito que foram digitados ("1.234,56"). Quem lê número é o motor, com a regra
// dele; uma segunda regra de leitura aqui em TypeScript acabaria divergindo, e
// a divergência apareceria em dinheiro.

import { getToken, clearSession } from "./auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

export type ModoPss = "nao" | "valor" | "aliquota";
export type ModoIr = "nao" | "valor" | "estimar";

/** O formulário inteiro, com as chaves que o motor espera. */
export interface FormularioCalculo {
  modo: "oficio" | "originario";
  vt: string; vp: string; vj: string; vs: string; vo: string;
  data_base: string; data_calculo: string;
  nat_hist: string; assist_idx: string; regime: string;
  natureza: string;
  pss_modo: ModoPss; pss: string; apss: string;
  ir_modo: ModoIr; ir: string; meses: string;
  hc: string; hs: string;
  modalidade: string; data_apres: string;
  sp_val: string; sp_data: string;
  ente: string; ente_outro: string; ano_orc: string;
  data_expedicao: string; esfera: "auto" | "estadual" | "federal";
  data_alvo: string; ref: string; obs: string;
}

export const FORMULARIO_VAZIO: FormularioCalculo = {
  modo: "oficio",
  vt: "", vp: "", vj: "", vs: "", vo: "",
  data_base: "", data_calculo: "",
  nat_hist: "", assist_idx: "IPCA-E", regime: "simples-ipca-e",
  natureza: "",
  // O padrão do PSS espelha a tela antiga: alíquota de 14 já preenchida. Quem
  // apaga o número recebe erro — o 14 é da tela, não do motor.
  pss_modo: "nao", pss: "", apss: "14",
  ir_modo: "nao", ir: "", meses: "0",
  hc: "", hs: "",
  modalidade: "", data_apres: "",
  sp_val: "", sp_data: "",
  ente: "", ente_outro: "", ano_orc: "",
  data_expedicao: "", esfera: "auto",
  data_alvo: "", ref: "", obs: "",
};

export interface ComponenteAtualizacao {
  regime: string; fator: string; inicio: string; fim: string;
  cap_acionado?: boolean; fator_juros?: string | null;
  juros_novos?: string | null; taxa_juros_novos?: string | null;
}

export interface Atualizacao {
  regime: string; fator: string;
  data_origem: string; data_alvo: string; data_alvo_solicitada: string | null;
  status: string; mensagem: string;
  componentes: ComponenteAtualizacao[];
  ressalva_adi?: string | null;
}

export interface Cenario {
  nome: string;
  disponivel: boolean;
  valor_total: string | null;
  valor_pss: string | null;
  valor_ir: string | null;
  honorarios_contratuais_pct: string | null;
  valor_honorarios_contratuais: string | null;
  valor_liquido: string | null;
  valor_liquido_atualizado: string | null;
  principal_corrigido_atualizado: string | null;
  juros_moratorios_atualizado: string | null;
  selic_acumulada_atualizada: string | null;
  valor_total_atualizado: string | null;
  atualizacao: Atualizacao | null;
  observacoes: string[];
  status_sentencial: string | null;
  pss_detalhe: Record<string, string | null> | null;
  ir_detalhe: Record<string, string | number | boolean | null> | null;
  valor_superpreferencia: string | null;
  data_pagamento_superpreferencia: string | null;
  superpreferencia_detalhe: Record<string, unknown> | null;
}

export interface ResultadoCenarios {
  cenario_homologado: Cenario;
  cenario_sentencial: Cenario;
  pior_cenario: string | null;
  valor_oferta_base: string | null;
  originario?: Record<string, unknown>;
}

export interface LinhaHonorario { pct: string; liquido: string; atual: boolean }

export interface RespostaCalculo {
  resultado: ResultadoCenarios;
  avisos: string[];
  aviso_projecao: string | null;
  cenarios_honorarios: LinhaHonorario[] | null;
  sucumbenciais_valor: string | null;
  sucumbenciais_pct: string | null;
  versao_motor: string | null;
}

/** Erro de preenchimento: a tela mostra a lista como o app antigo mostrava. */
export class ErroDePreenchimento extends Error {
  constructor(public erros: string[]) {
    super(erros.join(" "));
    this.name = "ErroDePreenchimento";
  }
}

async function pedir<T>(caminho: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_URL}/api/calculadora${caminho}`, {
    cache: "no-store",
    ...init,
    headers: {
      ...(init?.body && typeof init.body === "string" ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (res.status === 401) {
    clearSession();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new Error("Sessão expirada.");
  }
  if (res.status === 422) {
    const corpo = await res.json().catch(() => ({}));
    throw new ErroDePreenchimento(corpo?.erros ?? [corpo?.message ?? "Preenchimento inválido."]);
  }
  if (!res.ok) {
    const corpo = await res.json().catch(() => ({}));
    throw new Error(corpo?.message ?? corpo?.detail ?? `A calculadora respondeu ${res.status}.`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function calcular(form: FormularioCalculo): Promise<RespostaCalculo> {
  return pedir<RespostaCalculo>("/calcular", { method: "POST", body: JSON.stringify(form) });
}

export interface SaudeMotor {
  ok: boolean;
  indices_ultimo_mes_real: Record<string, string | null>;
  versao: string | null;
}

export const saudeDoMotor = () => pedir<SaudeMotor>("/saude");

export interface OpcoesCalculadora {
  regimes: { valor: string; rotulo: string }[];
  naturezas_historicas: string[];
  naturezas_tributarias: string[];
  entes: string[];
  pss_modos: Record<string, string>;
  ir_modos: Record<string, string>;
  anos_orcamentarios: string[];
}

export const opcoes = () => pedir<OpcoesCalculadora>("/opcoes");

/** Memorial em PDF — o mesmo arquivo que o advogado entrega. */
export async function memorialPdf(form: FormularioCalculo): Promise<{ blob: Blob; nome: string }> {
  const token = getToken();
  const res = await fetch(`${API_URL}/api/calculadora/memorial`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(form),
  });
  if (res.status === 422) {
    const corpo = await res.json().catch(() => ({}));
    throw new ErroDePreenchimento(corpo?.erros ?? ["Preenchimento inválido."]);
  }
  if (!res.ok) throw new Error(`Não foi possível gerar o memorial (${res.status}).`);
  const disposicao = res.headers.get("content-disposition") ?? "";
  const achado = /filename="([^"]+)"/.exec(disposicao);
  return { blob: await res.blob(), nome: achado?.[1] ?? "memorial_calculo.pdf" };
}

// ── documentos (pré-análise / assistente de corte / prefill) ───────────────

export interface EstadoDocumentos { habilitado: boolean; ocr: boolean; llm: boolean }
export const estadoDocumentos = () => pedir<EstadoDocumentos>("/documentos/estado");

export interface CorteSugerido {
  tipo: string; pagina_inicio: number; pagina_fim: number; rotulo?: string;
}
export interface RespostaAnalise {
  sessao: string;
  cortes_sugeridos: CorteSugerido[];
  homologacao: Record<string, unknown> | null;
  n_paginas: number;
  escaneadas: number;
}

export function analisarPdf(arquivo: File): Promise<RespostaAnalise> {
  const dados = new FormData();
  dados.append("arquivo", arquivo);
  return pedir<RespostaAnalise>("/documentos/analisar", { method: "POST", body: dados });
}

export interface CampoExtraido {
  valor: string | null;
  citacao?: { pagina?: number; trecho?: string } | null;
}
export interface RespostaExtracao {
  ok: boolean;
  erro?: string;
  campos?: Record<string, CampoExtraido>;
  query?: Record<string, string>;
  prova?: { ok?: boolean | null; dif_pct?: number | null };
  data_apresentacao?: string | null;
  mapa_paginas?: Record<string, string>;
  multi_conta?: boolean;
  multi_oficio?: boolean;
}

export function extrairCortes(sessao: string, cortes: CorteSugerido[]): Promise<RespostaExtracao> {
  return pedir<RespostaExtracao>("/documentos/extrair-cortes", {
    method: "POST", body: JSON.stringify({ sessao, cortes }),
  });
}

export function extrairPecas(
  conta: File, oficio?: File | null, sentencas: File[] = []
): Promise<RespostaExtracao> {
  const dados = new FormData();
  dados.append("conta", conta);
  if (oficio) dados.append("oficio", oficio);
  sentencas.forEach((s) => dados.append("sentencas", s));
  return pedir<RespostaExtracao>("/documentos/extrair-pecas", { method: "POST", body: dados });
}

export function preencherPorProcesso(arquivo: File): Promise<RespostaExtracao> {
  const dados = new FormData();
  dados.append("arquivo", arquivo);
  return pedir<RespostaExtracao>("/documentos/preencher", { method: "POST", body: dados });
}

// ── CRM ────────────────────────────────────────────────────────────────────

export interface EstadoCrm { bitrix: boolean; hub: boolean; funil_permitido: number | null }
export const estadoCrm = () => pedir<EstadoCrm>("/crm/estado");

export interface CardCrm {
  id: number; titulo: string; funil?: string; etapa?: string; url?: string;
  honorarios_contratuais_pct?: string | null; numero_precatorio?: string | null;
}
export const buscarCards = (termo: string) =>
  pedir<{ cards: CardCrm[] }>(`/crm/cards?termo=${encodeURIComponent(termo)}`);
export const lerCard = (id: number) => pedir<CardCrm>(`/crm/card/${id}`);

export interface EnvioCrm {
  deal_id: number;
  valor_liquido?: string | null;
  honorarios_contratuais_pct?: string | null;
  numero_precatorio?: string | null;
  numero_oficio?: string | null;
  natureza?: string | null;
  atualizado_para?: string | null;
  aviso_projecao?: string | null;
  referencia?: string | null;
  memorial_pdf?: string | null; // base64
  aplicar: boolean;
}
export interface RespostaEnvio {
  ensaio?: boolean; aplicado?: boolean; nada_novo?: boolean;
  campos?: string[]; descricao?: string[]; comentario?: string;
  pulados?: string[]; linhas_auditoria?: string[]; avisos?: string[];
  ja_rodou_antes?: boolean; completou?: boolean; detalhe?: string;
}
export const enviarAoCrm = (envio: EnvioCrm) =>
  pedir<RespostaEnvio>("/crm/enviar", { method: "POST", body: JSON.stringify(envio) });

// ── formatação (só exibição; nada aqui vira conta) ─────────────────────────

export function brl(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

export function dataBr(v: string | null | undefined): string {
  if (!v) return "—";
  const d = String(v).slice(0, 10);
  const [a, m, dia] = d.split("-");
  return a && m && dia ? `${dia}/${m}/${a}` : String(v);
}

/** Fator 1,0985 → "+9,85%". */
export function variacao(fator: string | null | undefined): string {
  const n = Number(fator);
  if (!Number.isFinite(n)) return "—";
  const v = (n - 1) * 100;
  return `${v >= 0 ? "+" : ""}${v.toFixed(2).replace(".", ",")}%`;
}
