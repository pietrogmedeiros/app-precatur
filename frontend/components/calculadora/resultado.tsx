"use client";

// O resultado do cálculo. A ordem é a da tela que o time já lê: oferta-base
// primeiro (é o número que vira proposta), depois a trilha de atualização fase a
// fase, a memória de PSS/IR e a cascata até o líquido.
//
// Nada aqui soma nem subtrai: todos os números vêm do motor. A tela só escolhe
// o que mostrar e em que ordem.

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Aviso } from "./campos";
import {
  brl, dataBr, variacao,
  type Cenario, type LinhaHonorario, type RespostaCalculo,
} from "@/lib/calculadora";

export function Resultado({ resposta }: { resposta: RespostaCalculo }) {
  const cen = resposta.resultado.cenario_homologado;
  const sentencial = resposta.resultado.cenario_sentencial;

  return (
    <div className="space-y-6">
      <OfertaBase resposta={resposta} />

      {resposta.aviso_projecao && <Aviso tom="atencao">⚠️ {resposta.aviso_projecao}</Aviso>}
      {resposta.avisos.map((a) => <Aviso key={a} tom="atencao">{a}</Aviso>)}
      {cen.atualizacao?.ressalva_adi && <Aviso tom="info">⚖ {cen.atualizacao.ressalva_adi}</Aviso>}
      {cen.observacoes?.map((o) => <Aviso key={o} tom="info">• {o}</Aviso>)}

      <Trilha cenario={cen} />
      <MemoriaDescontos cenario={cen} />
      <Cascata cenario={cen} sucumbenciaisPct={resposta.sucumbenciais_pct}
        sucumbenciaisValor={resposta.sucumbenciais_valor} />
      {resposta.cenarios_honorarios?.length ? (
        <CenariosHonorarios linhas={resposta.cenarios_honorarios} />
      ) : null}
      {sentencial?.disponivel && <CenarioSentencial cenario={sentencial} />}
    </div>
  );
}

function OfertaBase({ resposta }: { resposta: RespostaCalculo }) {
  const { valor_oferta_base, pior_cenario } = resposta.resultado;
  return (
    <Card className="border-primary/30 bg-primary/5">
      <CardContent className="p-6">
        <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          Oferta-base sugerida (líquido do pior cenário{pior_cenario ? ` — ${pior_cenario}` : ""})
        </p>
        <p className="mt-1 text-3xl font-bold tracking-tight">{brl(valor_oferta_base)}</p>
        {valor_oferta_base === null && (
          <p className="mt-2 text-xs text-muted-foreground">
            Sem oferta-base: faltam dados suficientes (ex.: valor de face ou data do cálculo).
          </p>
        )}
        {resposta.versao_motor && (
          <p className="mt-3 text-[11px] text-muted-foreground/70">motor {resposta.versao_motor}</p>
        )}
      </CardContent>
    </Card>
  );
}

function Trilha({ cenario }: { cenario: Cenario }) {
  const at = cenario.atualizacao;
  if (!at) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Memorial de cálculo</CardTitle>
        <CardDescription className="text-xs">
          {dataBr(at.data_origem)} → {dataBr(at.data_alvo)} · fator acumulado {variacao(at.fator)}
          {at.data_alvo_solicitada && at.data_alvo_solicitada !== at.data_alvo && (
            <> · a data pedida ({dataBr(at.data_alvo_solicitada)}) passa da cobertura publicada</>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {at.componentes.map((c, i) => (
          <div key={`${c.inicio}-${c.fim}-${i}`} className="rounded-md border border-border/70 p-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-xs font-semibold">
                {i + 1}ª fase — {c.regime}
              </p>
              <p className="text-[11px] text-muted-foreground">
                {dataBr(c.inicio)} → {dataBr(c.fim)}
              </p>
            </div>
            <div className="mt-1 flex flex-wrap gap-x-6 gap-y-1 text-[11px] text-muted-foreground">
              <span>fator {Number(c.fator).toFixed(6).replace(".", ",")} ({variacao(c.fator)})</span>
              {c.juros_novos && Number(c.juros_novos) > 0 && (
                <span>+ juros de mora {brl(c.juros_novos)}</span>
              )}
              {c.cap_acionado && <span className="text-amber-600">teto SELIC acionado</span>}
            </div>
          </div>
        ))}
        <div className="rounded-md bg-muted/60 p-3 text-xs">
          <strong>Valor atualizado ao presente</strong> = {brl(cenario.principal_corrigido_atualizado)} (principal)
          {" + "}{brl(cenario.juros_moratorios_atualizado)} (juros)
          {Number(cenario.selic_acumulada_atualizada ?? 0) > 0 && (
            <> {" + "}{brl(cenario.selic_acumulada_atualizada)} (SELIC)</>
          )}
          {" = "}<strong>{brl(cenario.valor_total_atualizado)}</strong>
        </div>
      </CardContent>
    </Card>
  );
}

function MemoriaDescontos({ cenario }: { cenario: Cenario }) {
  const pss = cenario.pss_detalhe;
  const ir = cenario.ir_detalhe;
  if (!pss && !ir) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">PSS e IR — memória de cálculo</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-6 sm:grid-cols-2">
        {pss && (
          <div className="space-y-1 text-xs">
            <p className="font-semibold">PSS — contribuição previdenciária</p>
            <Linha rotulo="Principal atualizado (sem juros)" valor={brl(pss.principal_atualizado)} />
            {pss.contratuais_pct && <Linha rotulo="Honorários contratuais" valor={`${pss.contratuais_pct}%`} />}
            <Linha rotulo="Base" valor={brl(pss.base)} />
            <Linha rotulo="Alíquota" valor={`${pss.aliquota_pct}%`} />
            <Linha rotulo="PSS" valor={brl(pss.valor)} forte />
          </div>
        )}
        {ir && (
          <div className="space-y-1 text-xs">
            <p className="font-semibold">IR-RRA (art. 12-A Lei 7.713)</p>
            <Linha rotulo="Base total" valor={brl(String(ir.base_total ?? ""))} />
            <Linha rotulo="(−) PSS deduzido" valor={brl(String(ir.pss_deduzido ?? ""))} />
            <Linha rotulo="Meses de competência" valor={String(ir.meses_competencia ?? "—")} />
            <Linha rotulo="Base mensal" valor={brl(String(ir.base_mensal ?? ""))} />
            <Linha rotulo="Alíquota efetiva" valor={`${ir.aliquota_efetiva_pct ?? "—"}%`} />
            <Linha rotulo="IR" valor={brl(String(ir.valor_ir ?? ""))} forte />
            {ir.justificativa && (
              <p className="pt-1 text-[11px] leading-snug text-muted-foreground">{String(ir.justificativa)}</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Linha({ rotulo, valor, forte }: { rotulo: string; valor: string; forte?: boolean }) {
  return (
    <div className={`flex justify-between gap-4 ${forte ? "border-t border-border pt-1 font-semibold" : ""}`}>
      <span className="text-muted-foreground">{rotulo}</span>
      <span className="tabular-nums">{valor}</span>
    </div>
  );
}

function Cascata({
  cenario, sucumbenciaisPct, sucumbenciaisValor,
}: {
  cenario: Cenario; sucumbenciaisPct: string | null; sucumbenciaisValor: string | null;
}) {
  const linhas: { rotulo: string; valor: string | null; sinal: "+" | "−" | "=" }[] = [
    { rotulo: "Valor bruto atualizado", valor: cenario.valor_total_atualizado, sinal: "+" },
  ];
  if (cenario.valor_superpreferencia) {
    linhas.push({
      rotulo: `Superpreferência já paga (${dataBr(cenario.data_pagamento_superpreferencia)})`,
      valor: cenario.valor_superpreferencia, sinal: "−",
    });
  }
  linhas.push({ rotulo: "PSS", valor: cenario.valor_pss, sinal: "−" });
  linhas.push({ rotulo: "IR-RRA", valor: cenario.valor_ir, sinal: "−" });
  if (cenario.valor_honorarios_contratuais) {
    linhas.push({
      rotulo: `Honorários contratuais (${cenario.honorarios_contratuais_pct}%)`,
      valor: cenario.valor_honorarios_contratuais, sinal: "−",
    });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Do bruto ao líquido</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1 text-sm">
        {linhas.map((l) => (
          <div key={l.rotulo} className="flex items-baseline justify-between gap-4 py-1">
            <span className="text-muted-foreground">
              <span className="mr-2 inline-block w-3 text-center font-mono text-xs">{l.sinal}</span>
              {l.rotulo}
            </span>
            <span className="tabular-nums">
              {l.valor === null ? <span className="text-muted-foreground">a apurar</span> : brl(l.valor)}
            </span>
          </div>
        ))}
        <div className="flex items-baseline justify-between gap-4 border-t border-border pt-2 text-base font-bold">
          <span><span className="mr-2 inline-block w-3 text-center font-mono text-xs">=</span>Líquido atualizado</span>
          <span className="tabular-nums">{brl(cenario.valor_liquido_atualizado)}</span>
        </div>
        {sucumbenciaisValor && (
          <p className="pt-3 text-[11px] leading-snug text-muted-foreground">
            ℹ️ Honorários sucumbenciais de {sucumbenciaisPct}% = {brl(sucumbenciaisValor)}.
            Não saem do líquido do credor — o valor vai no memorial, na seção “Honorários do advogado”.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function CenariosHonorarios({ linhas }: { linhas: LinhaHonorario[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Líquido por % de honorário contratual</CardTitle>
        <CardDescription className="text-xs">
          Cada linha é o motor inteiro, não um desconto por fora: o percentual entra na base do PSS e do
          IR, e pode mudar a faixa do IR-RRA — o efeito não é linear.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid gap-1 text-sm sm:grid-cols-2">
          {linhas.map((l) => (
            <div
              key={l.pct}
              className={`flex items-baseline justify-between gap-4 rounded px-2 py-1 ${
                l.atual ? "bg-primary/10 font-semibold" : ""
              }`}
            >
              <span className="text-muted-foreground">{l.pct}%{l.atual && " (atual)"}</span>
              <span className="tabular-nums">{brl(l.liquido)}</span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function CenarioSentencial({ cenario }: { cenario: Cenario }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Cenário sentencial</CardTitle>
        <CardDescription className="text-xs">
          Recálculo pelo regime da sentença — aparece quando a conta homologada diverge dela.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-1 text-sm">
        <Linha rotulo="Bruto atualizado" valor={brl(cenario.valor_total_atualizado)} />
        <Linha rotulo="PSS" valor={brl(cenario.valor_pss)} />
        <Linha rotulo="IR-RRA" valor={brl(cenario.valor_ir)} />
        <Linha rotulo="Líquido atualizado" valor={brl(cenario.valor_liquido_atualizado)} forte />
        {cenario.observacoes?.map((o) => (
          <p key={o} className="pt-1 text-[11px] text-muted-foreground">{o}</p>
        ))}
      </CardContent>
    </Card>
  );
}
