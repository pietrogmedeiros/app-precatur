import type { PricingEntity, PricingRow } from "./pricing";

/* ------------------------------ Praça ----------------------------------- */

export interface Praca {
  esfera: "federal" | "estadual" | "municipal";
  uf?: string | null;
  municipio?: string | null;
}

export interface PracaResolvida {
  entity: PricingEntity;
  /** true quando caiu no regime geral por não haver regra própria da praça. */
  estimativa: boolean;
}

// Procura a regra mais específica para a praça e, não achando, cai no regime
// geral da esfera — marcando o resultado como estimativa.
export function resolvePraca(entities: PricingEntity[], praca: Praca): PracaResolvida | null {
  const uf = (praca.uf ?? "").toUpperCase() || null;

  // 1) Regra da UF. esfera nula na tabela vale para qualquer esfera (caso de MG,
  //    que cobre o estado e Belo Horizonte).
  if (uf) {
    const daUf = entities.find(
      (e) => (e.uf ?? "").toUpperCase() === uf && (!e.esfera || e.esfera === praca.esfera)
    );
    if (daUf) return { entity: daUf, estimativa: false };
  }

  // 2) Regime geral da esfera (uf nula).
  const geral = entities.find((e) => !e.uf && e.esfera === praca.esfera);
  return geral ? { entity: geral, estimativa: true } : null;
}

/* --------------------------- Linha da tabela ----------------------------- */

export interface EscolhaLinha {
  safra: string;
  ativo?: string | null;
  natureza?: "alimentar" | "comum" | null;
  /** Usado para escolher a faixa de valor, quando a linha tiver faixa. */
  valorBruto?: number;
}

// Linhas podem trazer natureza e faixa de valor (como na concorrência). Quando
// não trazem, valem para qualquer natureza e qualquer valor — por isso as
// tabelas atuais seguem funcionando sem alteração.
function linhaServe(r: PricingRow, escolha: EscolhaLinha): boolean {
  if (r.year !== escolha.safra) return false;
  if (escolha.ativo && r.asset !== escolha.ativo) return false;
  if (r.natureza && escolha.natureza && r.natureza !== escolha.natureza) return false;
  if (r.faixa) {
    const v = escolha.valorBruto ?? 0;
    if (r.faixa.min != null && v < r.faixa.min) return false;
    if (r.faixa.max != null && v >= r.faixa.max) return false;
  }
  return true;
}

// Entre as linhas que servem, vence a mais específica (mais critérios casados).
export function escolheLinha(entity: PricingEntity, escolha: EscolhaLinha): PricingRow | null {
  const candidatas = entity.rows.filter((r) => linhaServe(r, escolha));
  if (!candidatas.length) return null;
  const peso = (r: PricingRow) => (r.natureza ? 2 : 0) + (r.faixa ? 1 : 0);
  return candidatas.sort((a, b) => peso(b) - peso(a))[0];
}

/* ------------------------------- Cálculo --------------------------------- */

export interface CalculoInput {
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

export interface CalculoResultado {
  bruto: number;
  honorarios: number;
  ir: number;
  pss: number;
  preferencia: number;
  outras_despesas: number;
  liquido: number;
  percentual: number;
  proposta: number;
}

const r2 = (n: number) => Math.round(n * 100) / 100;

// Mesma cadeia da ferramenta de referência: principal + juros + SELIC formam o
// bruto atualizado; as deduções (todas informadas por quem preenche) chegam ao
// líquido; o percentual da nossa tabela vira a proposta.
export function calcular(input: CalculoInput, percentual: number): CalculoResultado {
  const bruto = r2(input.principal + input.juros + input.selic);
  const honorarios = r2(bruto * (input.honorarios_pct / 100));
  const baseIr = input.ir_base === "principal" ? input.principal : bruto;
  const ir = r2(baseIr * (input.ir_pct / 100));
  const liquido = Math.max(
    0,
    r2(bruto - honorarios - ir - input.pss - input.preferencia - input.outras_despesas)
  );
  return {
    bruto,
    honorarios,
    ir,
    pss: r2(input.pss),
    preferencia: r2(input.preferencia),
    outras_despesas: r2(input.outras_despesas),
    liquido,
    percentual,
    proposta: r2(liquido * (percentual / 100)),
  };
}

// Abatimento fixo da praça (regra do RJ) entra depois do percentual, igual ao
// que a calculadora interna já faz.
export function aplicaAbatimento(proposta: number, abatimento: number): number {
  return Math.max(0, r2(proposta - (abatimento || 0)));
}
