// Lógica do Instrumento Preliminar de Cessão Onerosa (contrato do closer).
//
// Tudo aqui é puro (sem React) para poder ser testado sozinho: valor por
// extenso, concordância de gênero do cedente, nome do tribunal e cálculo da multa.

// ---------------------------------------------------------------- valor por extenso

const UNIDADES = [
  "zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove",
  "dez", "onze", "doze", "treze", "quatorze", "quinze", "dezesseis", "dezessete",
  "dezoito", "dezenove",
];
const DEZENAS = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"];
const CENTENAS = [
  "", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos",
  "setecentos", "oitocentos", "novecentos",
];

/** 0–999 por extenso ("cem" só para 100 exato). */
function ate999(n: number): string {
  if (n === 0) return "";
  if (n === 100) return "cem";
  const c = Math.floor(n / 100);
  const resto = n % 100;
  const partes: string[] = [];
  if (c) partes.push(CENTENAS[c]);
  if (resto) {
    if (resto < 20) partes.push(UNIDADES[resto]);
    else {
      const d = Math.floor(resto / 10);
      const u = resto % 10;
      partes.push(u ? `${DEZENAS[d]} e ${UNIDADES[u]}` : DEZENAS[d]);
    }
  }
  return partes.join(" e ");
}

const ESCALAS: Array<[string, string]> = [
  ["", ""],
  ["mil", "mil"],
  ["milhão", "milhões"],
  ["bilhão", "bilhões"],
  ["trilhão", "trilhões"],
];

/** Inteiro não negativo por extenso: 285045 → "duzentos e oitenta e cinco mil e quarenta e cinco". */
export function inteiroPorExtenso(n: number): string {
  if (!Number.isInteger(n) || n < 0) throw new Error("inteiro não negativo esperado");
  if (n === 0) return "zero";
  const grupos: number[] = [];
  for (let x = n; x > 0; x = Math.floor(x / 1000)) grupos.push(x % 1000);
  if (grupos.length > ESCALAS.length) throw new Error("valor grande demais");
  // Do grupo mais alto para o mais baixo, só os não nulos.
  const itens: Array<{ texto: string; valor: number }> = [];
  for (let i = grupos.length - 1; i >= 0; i--) {
    const g = grupos[i];
    if (!g) continue;
    let texto: string;
    if (i === 0) texto = ate999(g);
    else if (i === 1) texto = g === 1 ? "mil" : `${ate999(g)} mil`;
    else texto = `${ate999(g)} ${g === 1 ? ESCALAS[i][0] : ESCALAS[i][1]}`;
    itens.push({ texto, valor: g });
  }
  // Conectivo: " e " antes do último grupo quando ele é < 100 ou centena exata;
  // nos demais casos, vírgula ("duzentos e trinta mil, setecentos e doze").
  let out = itens[0].texto;
  for (let k = 1; k < itens.length; k++) {
    const ultimo = k === itens.length - 1;
    const v = itens[k].valor;
    const liga = ultimo && (v < 100 || v % 100 === 0) ? " e " : ", ";
    out += liga + itens[k].texto;
  }
  return out;
}

/** Reais por extenso: 285045.82 → "duzentos e oitenta e cinco mil e quarenta e cinco reais e oitenta e dois centavos". */
export function reaisPorExtenso(valor: number): string {
  if (!Number.isFinite(valor) || valor < 0) throw new Error("valor inválido");
  const totalCent = Math.round(valor * 100);
  const reais = Math.floor(totalCent / 100);
  const cent = totalCent % 100;
  const partes: string[] = [];
  if (reais > 0) {
    // "um milhão de reais", "dois bilhões de reais": exato em milhões usa "de".
    const exatoMilhao = reais % 1_000_000 === 0;
    const txt = inteiroPorExtenso(reais);
    partes.push(`${txt}${exatoMilhao ? " de" : ""} ${reais === 1 ? "real" : "reais"}`);
  }
  if (cent > 0) partes.push(`${inteiroPorExtenso(cent)} ${cent === 1 ? "centavo" : "centavos"}`);
  return partes.length ? partes.join(" e ") : "zero reais";
}

// ---------------------------------------------------------------- dinheiro

/** "285.045,82" (máscara BR) → 285045.82; vazio/inválido → null. */
export function lerMoeda(s: string): number | null {
  const t = s.trim();
  if (!t) return null;
  const n = parseFloat(t.replace(/\./g, "").replace(",", "."));
  return Number.isFinite(n) && n >= 0 ? n : null;
}

/** 285045.82 → "285.045,82". */
export function formatarMoeda(n: number): string {
  return new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
}

/** Multa de 5% sobre o valor do item 1.2, arredondada ao centavo. */
export function multaDe5Porcento(valor: number): number {
  return Math.round(valor * 5) / 100;
}

/** "100" → "100% (cem por cento)"; "12,5" → "12,5%" (fração fica sem extenso). */
export function percentualTexto(s: string): string | null {
  const t = s.trim().replace("%", "").trim();
  if (!t) return null;
  const n = parseFloat(t.replace(",", "."));
  if (!Number.isFinite(n) || n <= 0 || n > 100) return null;
  if (Number.isInteger(n)) return `${n}% (${inteiroPorExtenso(n)} por cento)`;
  return `${t.replace(".", ",")}%`;
}

// ---------------------------------------------------------------- cedente: PJ/PF e gênero

export type TipoCedente = "pj" | "pf";
export type GeneroCedente = "f" | "m";

/**
 * Formas que mudam com o cedente. Pessoa jurídica concorda no feminino ("a
 * CEDENTE"); pessoa física, no gênero escolhido. Uma chave só troca todas as
 * ocorrências do contrato — o comercial, à mão, deixava passar algumas.
 */
export interface Formas {
  a: string; //          a / o
  A: string; //          A / O
  aa: string; //         à / ao
  pela: string; //       pela / pelo
  da: string; //         da / do
  DA: string; //         DA / DO
  infrator: string; //   a infratora / o infrator
  legitimo: string; //   legítima e exclusiva / legítimo e exclusivo
}

export function formasDoCedente(tipo: TipoCedente, genero: GeneroCedente): Formas {
  const fem = tipo === "pj" || genero === "f";
  return fem
    ? { a: "a", A: "A", aa: "à", pela: "pela", da: "da", DA: "DA", infrator: "a infratora", legitimo: "legítima e exclusiva" }
    : { a: "o", A: "O", aa: "ao", pela: "pelo", da: "do", DA: "DO", infrator: "o infrator", legitimo: "legítimo e exclusivo" };
}

// ---------------------------------------------------------------- tribunal

const TJ_NOME: Record<string, string> = {
  TJAC: "do Acre", TJAL: "de Alagoas", TJAP: "do Amapá", TJAM: "do Amazonas",
  TJBA: "da Bahia", TJCE: "do Ceará", TJES: "do Espírito Santo", TJGO: "de Goiás",
  TJMA: "do Maranhão", TJMT: "de Mato Grosso", TJMS: "de Mato Grosso do Sul",
  TJMG: "de Minas Gerais", TJPA: "do Pará", TJPB: "da Paraíba", TJPR: "do Paraná",
  TJPE: "de Pernambuco", TJPI: "do Piauí", TJRJ: "do Rio de Janeiro",
  TJRN: "do Rio Grande do Norte", TJRS: "do Rio Grande do Sul", TJRO: "de Rondônia",
  TJRR: "de Roraima", TJSC: "de Santa Catarina", TJSE: "de Sergipe",
  TJSP: "de São Paulo", TJTO: "do Tocantins",
};

/** Sigla ("TJPA", "TRF1", "TRT5") → nome por extenso; sigla desconhecida volta como veio. */
export function tribunalPorExtenso(sigla: string | null | undefined): string {
  const s = (sigla ?? "").trim().toUpperCase();
  if (!s) return "";
  if (s === "TJDFT") return "Tribunal de Justiça do Distrito Federal e dos Territórios";
  if (TJ_NOME[s]) return `Tribunal de Justiça do Estado ${TJ_NOME[s]}`;
  const trf = s.match(/^TRF(\d)$/);
  if (trf) return `Tribunal Regional Federal da ${trf[1]}ª Região`;
  const trt = s.match(/^TRT(\d{1,2})$/);
  if (trt) return `Tribunal Regional do Trabalho da ${parseInt(trt[1], 10)}ª Região`;
  return sigla!.trim();
}

// ---------------------------------------------------------------- dados do contrato

export interface DadosContrato {
  // cedente
  tipo: TipoCedente;
  genero: GeneroCedente;
  cedenteNome: string;
  cedenteDoc: string; //          CPF (PF) ou CNPJ (PJ)
  cedenteEndereco: string; //     residência (PF) ou sede (PJ)
  nacionalidade: string; //       só PF
  estadoCivil: string; //         só PF
  // cessionária
  cessNome: string;
  cessCnpj: string;
  cessEndereco: string;
  cessRepresentante: string;
  // crédito
  natureza: "honorarios" | "principal";
  oficio: string;
  tribunal: string;
  processo: string;
  vara: string;
  valorLiquido: string; //        máscara BR, item 1.2
  percentual: string; //          item 1.3
  preco: string; //               item 2.1
  // assinatura
  local: string;
  data: string; //                ISO (yyyy-mm-dd) ou vazio
}

/** A cessionária padrão é a Precatur; outro comprador sobrescreve os campos. */
export const CESSIONARIA_PRECATUR = {
  cessNome: "PRECATUR INTERMEDIAÇÕES E NEGÓCIOS LTDA.",
  cessCnpj: "57.866.623/0001-69",
  cessEndereco: "Av. Jerônimo Monteiro, 1000, Sala 1501/1503, Ed. Trade Center, Centro, Vitória/ES, CEP 29010-002",
  cessRepresentante: "RAFAEL BUTILHEIRO SILVA",
} as const;

export const DADOS_VAZIOS: DadosContrato = {
  tipo: "pf",
  genero: "m",
  cedenteNome: "",
  cedenteDoc: "",
  cedenteEndereco: "",
  nacionalidade: "",
  estadoCivil: "",
  ...CESSIONARIA_PRECATUR,
  natureza: "honorarios",
  oficio: "",
  tribunal: "",
  processo: "",
  vara: "",
  valorLiquido: "",
  percentual: "100",
  preco: "",
  local: "Vitória/ES",
  data: "",
};

export interface Derivados {
  liquido: number | null;
  preco: number | null;
  multa: number | null;
  percentual: string | null;
}

export function derivar(d: DadosContrato): Derivados {
  const liquido = lerMoeda(d.valorLiquido);
  return {
    liquido,
    preco: lerMoeda(d.preco),
    multa: liquido === null ? null : multaDe5Porcento(liquido),
    percentual: percentualTexto(d.percentual),
  };
}

const MESES = [
  "janeiro", "fevereiro", "março", "abril", "maio", "junho",
  "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
];

/** "2026-11-25" → "25 de novembro de 2026"; vazio/inválido → null. */
export function dataPorExtenso(iso: string): string | null {
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return null;
  const mes = MESES[parseInt(m[2], 10) - 1];
  return mes ? `${parseInt(m[3], 10)} de ${mes} de ${m[1]}` : null;
}
