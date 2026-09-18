// Lógica pura da aba Precificação — sem React, para poder ser testada isolada.
// Portada da "calculadora final de precificação.html" e do "GERADOR DE
// GRÁFICOS.html"; as fórmulas são as mesmas, os ajustes estão comentados.

import type { PricingEntity, PricingRow } from "./api";

export const QUARTERS = ["1º Tri", "2º Tri", "3º Tri", "4º Tri"];

export function currentQuarterIndex(date = new Date()): number {
  return Math.floor(date.getMonth() / 3);
}

/* ---------------------------- Calculadora ------------------------------- */

// Tipo de ativo só é uma ESCOLHA quando a mesma safra aparece com ativos
// diferentes (caso de MG: "Regra vigente" para Precatório e Direito Creditório).
// Na Federal o ativo é consequência da safra, não escolha — o HTML antigo exibia
// botões de ativo ali que não filtravam nada.
export function hasAssetChoice(entity: PricingEntity): boolean {
  const years = new Set(entity.rows.map((r) => r.year));
  return years.size < entity.rows.length;
}

export function assetsOf(entity: PricingEntity): string[] {
  return Array.from(new Set(entity.rows.map((r) => r.asset)));
}

export function availableRows(entity: PricingEntity, asset: string): PricingRow[] {
  if (!hasAssetChoice(entity)) return entity.rows;
  const filtered = entity.rows.filter((r) => r.asset === asset);
  return filtered.length ? filtered : entity.rows;
}

// Proposta = valor cheio × % pago − abatimento fixo (regra RJ), nunca negativa.
export function finalProposal(face: number, pct: number, deduction: number): number {
  return Math.max(0, face * (pct / 100) - (deduction || 0));
}

// Inverso: percentual que gera uma proposta digitada (os dois campos são sincronizados).
export function pctFromProposal(proposal: number, face: number, deduction: number): number {
  if (!face) return 0;
  return Math.max(0, Math.min(100, ((proposal + (deduction || 0)) / face) * 100));
}

// Ano de pagamento a partir do rótulo da safra: "2027" → 2027, "2024 e 2025" →
// 2025, "Até 2023" → 2023. "Regra vigente" não tem ano → null, e quem chama
// deixa o campo como estava em vez de inventar.
export function paymentYearOf(label: string): number | null {
  const years = label.match(/\b(19|20)\d{2}\b/g);
  return years ? Number(years[years.length - 1]) : null;
}

// Anos de espera até o pagamento — prazo do simulador. Nunca menos que 1.
export function yearsUntil(label: string, currentYear: number): number | null {
  const y = paymentYearOf(label);
  return y === null ? null : Math.max(1, y - currentYear);
}

/* ----------------------------- Simulador -------------------------------- */

export interface SimInput {
  years: number;
  cdi: number; // % a.a.
  ipca: number; // % a.a.
  ir: number; // %
  init1: number; // Antecipar agora: valor recebido hoje
  spread1: number; // prêmio sobre CDI, % a.a.
  init2: number; // Esperar o governo: valor cheio
  spread2: number; // prêmio sobre IPCA, % a.a.
}

export interface SimSummary {
  gross: number;
  tax: number;
  net: number;
}

export interface SimResult {
  labels: string[];
  rate1: number; // % a.a.
  rate2: number;
  gross1: number[];
  gross2: number[];
  summary1: SimSummary;
  summary2: SimSummary;
}

// Mesma matemática do gerador de gráficos: CDI + prêmio é soma simples; IPCA +
// prêmio é composto; capitalização anual e IR só sobre o ganho, no fim.
export function simulate(p: SimInput): SimResult {
  const years = Math.max(1, Math.round(p.years));
  const rate1 = p.cdi / 100 + p.spread1 / 100;
  const rate2 = (1 + p.ipca / 100) * (1 + p.spread2 / 100) - 1;
  const ir = p.ir / 100;

  const labels: string[] = [];
  const gross1: number[] = [];
  const gross2: number[] = [];
  for (let t = 0; t <= years; t++) {
    labels.push(`Ano ${t}`);
    gross1.push(p.init1 * Math.pow(1 + rate1, t));
    gross2.push(p.init2 * Math.pow(1 + rate2, t));
  }

  const summary = (init: number, final: number): SimSummary => {
    const tax = Math.max(0, final - init) * ir;
    return { gross: final, tax, net: final - tax };
  };

  return {
    labels,
    rate1: rate1 * 100,
    rate2: rate2 * 100,
    gross1,
    gross2,
    summary1: summary(p.init1, gross1[years]),
    summary2: summary(p.init2, gross2[years]),
  };
}

/* --------------------------- Planilha (XLSX) ---------------------------- */

function stripAccents(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "");
}

// Percentual vindo da planilha: 0.76 (célula formatada em %) ou 76 ou "76%".
export function parseSpreadsheetPercent(value: unknown): number {
  if (typeof value === "number") return value <= 1 ? value * 100 : value;
  const text = String(value ?? "").trim().replace("%", "").replace(",", ".");
  const n = Number(text);
  return text !== "" && Number.isFinite(n) ? n : NaN;
}

// Procura o bloco "<KEYWORD> ... PREÇO" na primeira coluna e lê as linhas até a
// primeira vazia. Mesmo padrão da planilha comercial usado pelo HTML antigo, com
// uma correção: lá a busca era por "PRECO" sem cedilha e não achava "PREÇO".
export function extractBlock(sheet: unknown[][], keyword: string): PricingRow[] {
  const key = stripAccents(keyword).toUpperCase();

  for (let i = 0; i < sheet.length; i++) {
    const first = stripAccents(String(sheet[i]?.[0] ?? "")).toUpperCase();
    if (!first.includes(key) || !first.includes("PRECO")) continue;

    const out: PricingRow[] = [];
    // i + 1 é o cabeçalho (Safra | 1º Tri ...); dados começam em i + 2.
    for (let r = i + 2; r < sheet.length; r++) {
      const row = sheet[r] ?? [];
      const year = String(row[0] ?? "").trim();
      if (!year) break;

      const values = [row[1], row[2], row[3], row[4]].map(parseSpreadsheetPercent);
      if (values.some((v) => Number.isNaN(v))) break;

      const asset = stripAccents(String(row[5] ?? "")).toUpperCase().includes("DIREITO")
        ? "Direito Creditório"
        : "Precatório";
      out.push({ year, values: values.map((v) => Math.round(v * 100) / 100), asset });
    }
    return out;
  }
  return [];
}

/* ------------------------------ Formatação ------------------------------ */

export function formatBRL(value: number, decimals = 2): string {
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(Number(value) || 0);
}

export function formatPct(value: number): string {
  return `${Number(value || 0).toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}%`;
}

export function formatDecimal(value: number): string {
  return (Number(value) || 0).toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

// "R$ 100.000,50" / "100000.5" / "100.000" → número. Ponto é milhar, vírgula é decimal.
export function parseBRL(value: string): number {
  const raw = String(value ?? "").replace(/[R$\s]/g, "");
  const clean = raw.includes(",") ? raw.replace(/\./g, "").replace(",", ".") : raw.replace(/\.(?=\d{3}(\D|$))/g, "");
  const n = Number(clean.replace(/[^\d.-]/g, ""));
  return Number.isFinite(n) ? n : 0;
}
