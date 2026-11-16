import { test } from "node:test";
import assert from "node:assert/strict";
import { avisosDeCoerencia, previewMudanca, LIQUIDO_REFERENCIA } from "./pricingPreview";
import type { PricingRow } from "./pricing";

const L = (year: string, values: number[], extra: Partial<PricingRow> = {}): PricingRow => ({
  year, values, asset: "Precatório", ...extra,
});

// Tabela Federal de produção (008_pricing.sql): não deve gerar nenhum aviso.
const FEDERAL = [
  L("2026", [76, 80, 80, 80]), L("2027", [57, 62, 66, 70]), L("2028", [44, 47, 50, 54]),
  L("2029", [34, 36, 39, 41]), L("2030", [25, 27, 29, 31]), L("2031", [18, 20, 22, 23]),
];

test("tabela de produção não gera aviso de coerência", () => {
  assert.deepEqual(avisosDeCoerencia(FEDERAL), []);
});

test("regras com safra em texto (Bahia, RJ) não disparam o aviso entre safras", () => {
  const bahia = [L("Até 2023", [30, 30, 30, 30]), L("2024 e 2025", [22, 22, 22, 22])];
  assert.deepEqual(avisosDeCoerencia(bahia), []);
});

test("safra mais distante pagando mais é avisada", () => {
  const av = avisosDeCoerencia([L("2027", [57, 62, 66, 70]), L("2028", [44, 47, 50, 90])]);
  assert.equal(av.length, 1);
  assert.match(av[0], /Safra 2028 paga mais que a 2027 no 4º tri/);
});

test("trimestre que cai dentro do ano é avisado", () => {
  const av = avisosDeCoerencia([L("2027", [57, 62, 50, 70])]);
  assert.match(av[0], /3º tri \(50%\) é menor que o 2º \(62%\)/);
});

test("linha zerada e linha repetida são avisadas", () => {
  const av = avisosDeCoerencia([L("2027", [0, 0, 0, 0]), L("2027", [1, 2, 3, 4])]);
  assert.ok(av.some((a) => /Linha repetida/.test(a)));
  assert.ok(av.some((a) => /zerada/.test(a)));
});

test("diff traduz pontos percentuais em reais no trimestre vigente", () => {
  const depois = FEDERAL.map((r) => (r.year === "2027" ? L("2027", [57, 62, 66, 60]) : r));
  const p = previewMudanca(
    { rows: FEDERAL, fixed_deduction: 0 },
    { rows: depois, fixed_deduction: 0 },
    3
  );
  const l = p.linhas.find((x) => x.rotulo.startsWith("2027"))!;
  assert.deepEqual(l.delta, [0, 0, 0, -10]);
  assert.equal(l.proposta_antes, LIQUIDO_REFERENCIA * 0.7);
  assert.equal(l.proposta_depois, LIQUIDO_REFERENCIA * 0.6);
  assert.equal(p.mudou, true);
});

test("sem alteração: mudou=false e nenhum aviso", () => {
  const p = previewMudanca({ rows: FEDERAL, fixed_deduction: 0 }, { rows: FEDERAL, fixed_deduction: 0 }, 0);
  assert.equal(p.mudou, false);
  assert.deepEqual(p.avisos, []);
});

test("salto acima de 15 p.p. e linha removida são avisados", () => {
  const depois = [L("2026", [76, 80, 80, 10]), ...FEDERAL.slice(2)]; // sem 2027
  const p = previewMudanca({ rows: FEDERAL, fixed_deduction: 0 }, { rows: depois, fixed_deduction: 0 }, 0);
  assert.ok(p.avisos.some((a) => /4º tri muda de 80% para 10%/.test(a)));
  assert.ok(p.avisos.some((a) => /"2027 · Precatório" será removida/.test(a)));
  assert.equal(p.linhas.find((l) => l.rotulo.startsWith("2027"))!.depois, null);
});

test("abatimento fixo entra na proposta e no aviso", () => {
  const rj = [L("Até 2026", [27, 27, 27, 27])];
  const p = previewMudanca({ rows: rj, fixed_deduction: 6000 }, { rows: rj, fixed_deduction: 8000 }, 0);
  assert.equal(p.linhas[0].proposta_antes, 270000 - 6000);
  assert.equal(p.linhas[0].proposta_depois, 270000 - 8000);
  assert.equal(p.mudou, true);
  assert.ok(p.avisos.some((a) => /abatimento fixo muda/.test(a)));
});

test("linhas desdobradas por natureza são comparadas separadamente", () => {
  const antes = [L("2027", [50, 50, 50, 50], { natureza: "alimentar" }), L("2027", [40, 40, 40, 40], { natureza: "comum" })];
  const depois = [L("2027", [55, 50, 50, 50], { natureza: "alimentar" }), L("2027", [40, 40, 40, 40], { natureza: "comum" })];
  const p = previewMudanca({ rows: antes, fixed_deduction: 0 }, { rows: depois, fixed_deduction: 0 }, 0);
  assert.equal(p.linhas.length, 2);
  assert.deepEqual(p.linhas[0].delta, [5, 0, 0, 0]);
  assert.deepEqual(p.linhas[1].delta, [0, 0, 0, 0]);
});
