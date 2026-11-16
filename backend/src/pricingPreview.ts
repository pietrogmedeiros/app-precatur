import type { PricingRow } from "./pricing";
import { calcular, aplicaAbatimento } from "./calculo";

// Pré-visualização de uma mudança de preço: mostra o antes × depois e avisa de
// incoerências SEM gravar nada. Funções puras (sem banco), para poderem ser
// testadas e reaproveitadas pela rota de edição, de importação e de restauração.

/** Crédito líquido usado para traduzir pontos percentuais em reais. */
export const LIQUIDO_REFERENCIA = 1_000_000;

/** Variação de uma célula (em pontos percentuais) a partir da qual avisamos. */
export const SALTO_SUSPEITO_PP = 15;

export interface PreviewLinha {
  /** Rótulo legível: "2027 · Precatório · alimentar". */
  rotulo: string;
  /** null = linha nova. */
  antes: number[] | null;
  /** null = linha removida. */
  depois: number[] | null;
  /** Variação por trimestre, em pontos percentuais (null quando não há os dois lados). */
  delta: (number | null)[];
  /** Proposta para LIQUIDO_REFERENCIA no trimestre vigente. */
  proposta_antes: number | null;
  proposta_depois: number | null;
}

export interface PreviewEntrada {
  rows: PricingRow[];
  fixed_deduction: number;
}

export interface PreviewResultado {
  linhas: PreviewLinha[];
  abatimento: { antes: number; depois: number };
  trimestre: number;
  liquido_referencia: number;
  avisos: string[];
  /** false quando nada muda: a tela pode dizer isso em vez de pedir confirmação. */
  mudou: boolean;
}

const r2 = (n: number) => Math.round(n * 100) / 100;

function faixaTexto(f: PricingRow["faixa"]): string {
  if (!f || (f.min == null && f.max == null)) return "";
  const fmt = (v: number) => v.toLocaleString("pt-BR");
  if (f.min != null && f.max != null) return `R$ ${fmt(f.min)} a ${fmt(f.max)}`;
  if (f.min != null) return `a partir de R$ ${fmt(f.min)}`;
  return `até R$ ${fmt(f.max as number)}`;
}

export function rotuloDaLinha(r: PricingRow): string {
  return [r.year, r.asset, r.natureza ?? "", faixaTexto(r.faixa)].filter(Boolean).join(" · ");
}

// Identidade da linha entre as duas versões. Duas linhas com o mesmo rótulo
// (erro de digitação) ganham sufixo #2, #3… para o diff não as confundir.
function indexa(rows: PricingRow[]): Map<string, PricingRow> {
  const m = new Map<string, PricingRow>();
  for (const r of rows) {
    const base = JSON.stringify([r.year, r.asset, r.natureza ?? null, r.faixa?.min ?? null, r.faixa?.max ?? null]);
    let k = base;
    for (let n = 2; m.has(k); n++) k = `${base}#${n}`;
    m.set(k, r);
  }
  return m;
}

function propostaDe(valores: number[] | null, trimestre: number, abatimento: number): number | null {
  if (!valores) return null;
  const pct = valores[trimestre] ?? 0;
  const calc = calcular(
    {
      principal: LIQUIDO_REFERENCIA, juros: 0, selic: 0, honorarios_pct: 0, ir_pct: 0,
      ir_base: "principal", pss: 0, preferencia: 0, outras_despesas: 0,
    },
    pct
  );
  return aplicaAbatimento(calc.proposta, abatimento);
}

/* ------------------------------ Coerência -------------------------------- */

// Avisos sobre a tabela NOVA, sozinha. Não bloqueiam: há regras comerciais
// legítimas fora do padrão, mas quase sempre isso é erro de digitação.
export function avisosDeCoerencia(rows: PricingRow[]): string[] {
  const avisos: string[] = [];

  const vistos = new Set<string>();
  for (const r of rows) {
    const k = rotuloDaLinha(r);
    if (vistos.has(k)) avisos.push(`Linha repetida: "${k}". A calculadora usará só uma delas.`);
    vistos.add(k);
  }

  for (const r of rows) {
    if (r.values.every((v) => v === 0)) {
      avisos.push(`"${rotuloDaLinha(r)}" está zerada em todos os trimestres — a proposta sairia R$ 0,00.`);
    }
    // Dentro do ano o preço sobe (ou fica igual) a cada trimestre: quanto mais
    // perto do pagamento, menos desconto.
    for (let q = 1; q < r.values.length; q++) {
      if (r.values[q] < r.values[q - 1]) {
        avisos.push(`"${rotuloDaLinha(r)}": o ${q + 1}º tri (${r.values[q]}%) é menor que o ${q}º (${r.values[q - 1]}%).`);
        break;
      }
    }
  }

  // Entre safras (só as que são um ano, como "2027") o preço cai quanto mais
  // distante o pagamento. Compara linhas do mesmo ativo/natureza/faixa.
  const grupos = new Map<string, PricingRow[]>();
  for (const r of rows) {
    if (!/^\d{4}$/.test(r.year)) continue;
    const g = JSON.stringify([r.asset, r.natureza ?? null, r.faixa?.min ?? null, r.faixa?.max ?? null]);
    grupos.set(g, [...(grupos.get(g) ?? []), r]);
  }
  for (const lista of grupos.values()) {
    const ord = [...lista].sort((a, b) => Number(a.year) - Number(b.year));
    for (let i = 1; i < ord.length; i++) {
      const q = ord[i].values.findIndex((v, idx) => v > (ord[i - 1].values[idx] ?? 0));
      if (q !== -1) {
        const suf = [ord[i].asset, ord[i].natureza].filter(Boolean).join(" · ");
        avisos.push(
          `Safra ${ord[i].year} paga mais que a ${ord[i - 1].year} no ${q + 1}º tri ` +
            `(${ord[i].values[q]}% × ${ord[i - 1].values[q]}%)${suf ? ` — ${suf}` : ""}.`
        );
      }
    }
  }
  return avisos;
}

/* -------------------------------- Diff ----------------------------------- */

export function previewMudanca(
  antes: PreviewEntrada,
  depois: PreviewEntrada,
  trimestre: number
): PreviewResultado {
  const a = indexa(antes.rows);
  const d = indexa(depois.rows);
  const linhas: PreviewLinha[] = [];
  const avisos = avisosDeCoerencia(depois.rows);

  // Ordem da tabela nova primeiro; as removidas vão ao fim.
  const chaves = [...d.keys(), ...[...a.keys()].filter((k) => !d.has(k))];
  for (const k of chaves) {
    const ra = a.get(k) ?? null;
    const rd = d.get(k) ?? null;
    const delta = [0, 1, 2, 3].map((q) =>
      ra && rd ? r2((rd.values[q] ?? 0) - (ra.values[q] ?? 0)) : null
    );
    const rotulo = rotuloDaLinha((rd ?? ra) as PricingRow);
    linhas.push({
      rotulo,
      antes: ra ? ra.values : null,
      depois: rd ? rd.values : null,
      delta,
      proposta_antes: propostaDe(ra?.values ?? null, trimestre, antes.fixed_deduction),
      proposta_depois: propostaDe(rd?.values ?? null, trimestre, depois.fixed_deduction),
    });

    if (!rd) avisos.push(`A linha "${rotulo}" será removida — a calculadora pública deixa de ter preço para ela.`);
    const salto = delta.findIndex((x) => x != null && Math.abs(x) > SALTO_SUSPEITO_PP);
    if (salto !== -1) {
      avisos.push(
        `"${rotulo}": o ${salto + 1}º tri muda de ${ra!.values[salto]}% para ${rd!.values[salto]}% ` +
          `(${(delta[salto] as number) > 0 ? "+" : ""}${delta[salto]} p.p.). Confira se não é erro de digitação.`
      );
    }
  }

  if (antes.fixed_deduction !== depois.fixed_deduction) {
    avisos.push(
      `O abatimento fixo muda de R$ ${antes.fixed_deduction.toLocaleString("pt-BR")} ` +
        `para R$ ${depois.fixed_deduction.toLocaleString("pt-BR")}.`
    );
  }

  const mudou =
    antes.fixed_deduction !== depois.fixed_deduction ||
    linhas.some((l) => !l.antes || !l.depois || l.delta.some((x) => x !== 0));

  return {
    linhas,
    abatimento: { antes: antes.fixed_deduction, depois: depois.fixed_deduction },
    trimestre,
    liquido_referencia: LIQUIDO_REFERENCIA,
    avisos,
    mudou,
  };
}
