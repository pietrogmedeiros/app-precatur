"use client";

// O parecer de um precatório: quem é o crédito, quem deve, como esse devedor
// vem pagando, onde o crédito está na fila e em que ano a projeção o alcança.
//
// Nada aqui calcula. Todos os números — inclusive as duas projeções e a mora
// sobre a RCL — vêm prontos do Alfred; a tela escolhe o que mostrar e em que
// ordem.
//
// São DOIS cenários, e só dois: o limite da lei (o que o ente pode gastar pelo
// art. 100 §23 — é o número principal da tela) e o ritmo real (o que ele pagou
// de fato ao tribunal da fila). O leque conservador/central/otimista que ficava
// aqui saiu em 15/10/2026: três datas próximas não ajudam a decidir, e o Alfred
// segue mandando a banda para quem precisar dela.

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { AlertTriangle, Download, Eye, FileText, Loader2 } from "lucide-react";
import { brl, brlCurto, dataBr, numero, pct, type Parecer } from "@/lib/alfred";

export function ParecerView({
  parecer, papel, revelado, aoRevelar, aoBaixarPdf, baixando,
}: {
  parecer: Parecer;
  papel: "leitor" | "completo";
  revelado: boolean;
  aoRevelar: () => void;
  aoBaixarPdf: () => void;
  baixando: boolean;
}) {
  const { precatorio: p, credor, devedor, edital_acordo: edital, avisos, pagamento, fila, projecao } = parecer;

  return (
    <div className="space-y-5">
      <Card className="border-primary/30 bg-primary/5">
        <CardContent className="space-y-3 p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                {p.tribunal}{p.natureza ? ` · ${p.natureza}` : ""}{p.ano_orcamento ? ` · orçamento ${p.ano_orcamento}` : ""}
              </p>
              <p className="mt-0.5 font-mono text-sm">{p.numero}</p>
              <p className="mt-2 text-2xl font-bold tracking-tight">{brl(p.valor)}</p>
            </div>
            <div className="flex flex-col items-end gap-2">
              {projecao?.ano_previsto && <SeloPrevisao projecao={projecao} />}
              {parecer.id !== undefined && (
                <Button size="sm" variant="outline" onClick={aoBaixarPdf} disabled={baixando}>
                  {baixando ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                  Parecer em PDF
                </Button>
              )}
            </div>
          </div>
          {(p.suspenso || p.situacao || p.superpreferencia) && (
            <div className="flex flex-wrap gap-2 text-[11px]">
              {p.suspenso && <Marca tom="alerta">suspenso</Marca>}
              {p.situacao && <Marca>{p.situacao}</Marca>}
              {p.superpreferencia && <Marca tom="destaque">superpreferência: {p.superpreferencia}</Marca>}
            </div>
          )}
        </CardContent>
      </Card>

      {avisos?.length > 0 && (
        <div className="space-y-2">
          {avisos.map((a) => (
            <div key={a} className="flex gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs leading-relaxed text-amber-800 dark:text-amber-300">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{a}</span>
            </div>
          ))}
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <Bloco titulo="Credor">
          <Linha rotulo="Nome" valor={credor.nome ?? "não publicado pelo tribunal"} />
          <Linha
            rotulo="CPF/CNPJ"
            valor={
              <span className="inline-flex items-center gap-2">
                <span className="font-mono">{credor.cpf_cnpj ?? "—"}</span>
                {credor.cpf_mascarado && credor.cpf_cnpj && papel === "completo" && !revelado && (
                  <button type="button" onClick={aoRevelar}
                    className="inline-flex items-center gap-1 text-[11px] text-muted-foreground underline">
                    <Eye className="h-3 w-3" /> revelar
                  </button>
                )}
              </span>
            }
          />
          {credor.advogado && <Linha rotulo="Advogado" valor={credor.advogado} />}
          {p.numero_origem && <Linha rotulo="Processo de origem" valor={p.numero_origem} />}
          {p.numero_eproc_fmt && <Linha rotulo="eproc" valor={p.numero_eproc_fmt} />}
          <Linha rotulo="Coletado em" valor={dataBr(p.coletado_em)} />
        </Bloco>

        <Bloco titulo="Devedor">
          <Linha rotulo="Ente" valor={devedor.ente ?? "—"} />
          <Linha rotulo="Município / UF" valor={`${devedor.municipio ?? "—"}${devedor.uf ? ` / ${devedor.uf}` : ""}`} />
          <Linha rotulo="Regime" valor={devedor.regime ?? "—"} />
          <Linha rotulo="RCL" valor={brlCurto(devedor.rcl)} />
        </Bloco>
      </div>

      {fila && <FilaBloco fila={fila} />}
      {pagamento && <PagamentoBloco pagamento={pagamento} />}
      {projecao && (
        <ProjecaoBloco
          projecao={projecao}
          tribunal={p.tribunal}
          superprecatorio={!!fila?.e_superprecatorio}
        />
      )}
      {edital?.tem && <EditalBloco edital={edital} />}
    </div>
  );
}

function FilaBloco({ fila }: { fila: Record<string, any> }) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm">Posição na fila</CardTitle>
        <CardDescription className="text-xs">
          Ordem cronológica do ente e quanto há à frente deste crédito.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <Numero rotulo="Posição" valor={fila.ordem ? `${numero(fila.ordem)}º` : "—"}
            nota={fila.n_total ? `de ${numero(fila.n_total)}` : undefined} />
          <Numero rotulo="Acumulado à frente" valor={brlCurto(fila.acumulado_sem_p20 ?? fila.acumulado_bruto)} />
          <Numero rotulo="Estoque do ente" valor={brlCurto(fila.estoque_municipio)} />
        </div>
        {fila.estoque_em_mora != null && (
          <div className="rounded-md bg-muted/60 p-3 text-xs leading-relaxed">
            <strong>{brlCurto(fila.estoque_em_mora)}</strong> em mora
            {fila.n_em_mora ? ` (${numero(fila.n_em_mora)} precatórios)` : ""}
            {fila.mora_sobre_rcl_pct != null && <> — <strong>{String(fila.mora_sobre_rcl_pct).replace(".", ",")}%</strong> da RCL</>}
            {fila.base_mora_usada && <span className="text-muted-foreground"> · base: {fila.base_mora_usada}</span>}
          </div>
        )}
        {fila.e_superprecatorio && (
          <div className="rounded-md border border-border px-3 py-2 text-xs">
            Este é um <strong>superprecatório</strong> (art. 100 §20): entra em reserva própria e não disputa a fila comum.
          </div>
        )}
        {Array.isArray(fila.itens) && fila.itens.length > 0 && (
          <JanelaDaFila itens={fila.itens} janela={fila.itens_janela} />
        )}
      </CardContent>
    </Card>
  );
}

function JanelaDaFila({ itens, janela }: { itens: any[]; janela?: Record<string, any> }) {
  return (
    <div>
      <p className="mb-1.5 text-[11px] text-muted-foreground">
        Vizinhança na fila
        {janela ? ` — posições ${numero(janela.inicio)} a ${numero(janela.fim)} de ${numero(janela.total)}` : ""}
      </p>
      <div className="max-h-72 overflow-auto rounded-md border border-border/70">
        <table className="w-full text-[11px]">
          <thead className="sticky top-0 bg-muted/80 text-left">
            <tr>
              <th className="px-2 py-1 font-medium">#</th>
              <th className="px-2 py-1 font-medium">Natureza</th>
              <th className="px-2 py-1 text-right font-medium">Valor</th>
              <th className="px-2 py-1 text-right font-medium">Acumulado</th>
              <th className="px-2 py-1 text-right font-medium">Pela lei</th>
            </tr>
          </thead>
          <tbody>
            {itens.map((i) => (
              <tr key={`${i.id}-${i.posicao}`}
                  className={`border-t border-border/50 ${i.e_buscado ? "bg-primary/10 font-semibold" : ""}`}>
                <td className="px-2 py-1 tabular-nums">{numero(i.posicao)}</td>
                <td className="px-2 py-1">{i.natureza ?? "—"}{i.superprecatorio ? " · §20" : ""}</td>
                <td className="px-2 py-1 text-right tabular-nums">{brl(i.valor)}</td>
                <td className="px-2 py-1 text-right tabular-nums text-muted-foreground">{brlCurto(i.acumulado)}</td>
                <td className="px-2 py-1 text-right tabular-nums">{i.ano_previsto ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PagamentoBloco({ pagamento }: { pagamento: Record<string, any> }) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm">Como este devedor vem pagando</CardTitle>
        <CardDescription className="text-xs">
          {pagamento.fonte}{pagamento.escopo ? ` · ${pagamento.escopo}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {pagamento.resumo && <p className="text-sm">{pagamento.resumo}</p>}
        <div className="grid gap-3 sm:grid-cols-4">
          <Numero rotulo="Estoque de abertura" valor={brlCurto(pagamento.estoque_abertura)} />
          <Numero rotulo="Pago no ano" valor={brlCurto(pagamento.pago_no_ano)} />
          <Numero rotulo="Saldo no fim do ano" valor={brlCurto(pagamento.saldo_fim_ano)} />
          <Numero rotulo="Taxa de quitação" valor={pct(pagamento.taxa_quitacao)} />
        </div>
        {Array.isArray(pagamento.tribunais_inadimplentes) && pagamento.tribunais_inadimplentes.length > 0 && (
          <p className="text-xs text-amber-700 dark:text-amber-400">
            Inadimplente em: {pagamento.tribunais_inadimplentes.join(", ")} — disputam o mesmo caixa.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// Os dois cenários do parecer, lidos do mesmo payload do Alfred.
function cenarios(projecao: Record<string, any>) {
  const ritmo = projecao.ritmo_observado ?? null;
  return {
    ritmo,
    temRitmo: Boolean(ritmo?.ano_previsto),
    anosRitmo: Number(ritmo?.anos_media ?? 0),
    // devedor que paga a fila inteira no exercício do orçamento (União no TRF2,
    // INSS nos TJs, estatais): não há teto anual, logo não há limite a comparar
    // com ritmo nenhum — a tela passa a falar de uma data só.
    exercicio: projecao.fonte_orcamento === "pago_no_exercicio",
  };
}

// `pct_p23` já vem em pontos percentuais (1.5 = 1,5% da RCL). O `pct` da lib
// multiplica por 100 — serve para fração, não para este campo.
function pctDireto(v: number | null | undefined): string {
  const n = Number(v);
  return Number.isFinite(n) ? `${n.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}%` : "—";
}

// O número grande é SEMPRE o cenário da lei; o ritmo real vem abaixo, menor.
function SeloPrevisao({ projecao }: { projecao: Record<string, any> }) {
  const { ritmo, temRitmo, exercicio } = cenarios(projecao);
  return (
    <div className="rounded-md border border-border bg-background px-3 py-2 text-right">
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Previsão de pagamento</p>
      <p className="text-lg font-bold">{projecao.ano_previsto}</p>
      <p className="text-[11px] text-muted-foreground">
        {exercicio ? "paga a fila no exercício" : "se pagar o limite da lei"}
      </p>
      {!exercicio && temRitmo && (
        <p className="text-[11px] text-muted-foreground">no ritmo real: {ritmo.ano_previsto}</p>
      )}
    </div>
  );
}

function ProjecaoBloco({ projecao, tribunal, superprecatorio }: {
  projecao: Record<string, any>;
  tribunal: string;
  superprecatorio: boolean;
}) {
  const { ritmo, temRitmo, anosRitmo, exercicio } = cenarios(projecao);
  const rateio = projecao.rateio;
  const fonte = projecao.fonte_orcamento;

  const notaLei = exercicio
    ? "paga a fila inteira no exercício do orçamento — sem teto do art. 100 §23"
    : rateio
    ? `gastando ${brl(projecao.orcamento_anual)}/ano nesta justiça — parcela do §23 do ente `
      + `(${Math.round(Number(rateio.fracao) * 100)}% do teto de ${brl(projecao.teto_p23)}, `
      + `rateio ${rateio.fonte === "mapa" ? "provisório pelo Mapa CNJ" : "pelas filas das justiças"})`
    : `gastando ${brl(projecao.orcamento_anual)}/ano — ${pctDireto(projecao.pct_p23)} da RCL, `
      + (fonte === "oficial_valor" ? "valor do plano publicado pelo tribunal"
         : fonte === "oficial" ? "percentual homologado pelo tribunal"
         : "teto do art. 100 §23");

  const notaRitmo = exercicio
    ? "não se aplica — não há teto anual a medir"
    : !ritmo
    ? (superprecatorio
       ? "não se aplica — superprecatório (art. 100 §20): paga 15% à vista + 5 parcelas anuais quando a fila chegar nele"
       : `sem dado de pagamento para ${tribunal}`)
    : Number(ritmo.pago_no_ano) > 0
    ? (anosRitmo > 1
       ? `média de ${brl(ritmo.pago_no_ano)}/ano ao ${tribunal}`
       : `pagou ${brl(ritmo.pago_no_ano)} ao ${tribunal} no último ano`)
      + (Number(ritmo.pct_do_teto) > 100 ? " — acima do limite, sob as regras anteriores" : "")
    : `não pagou nada ao ${tribunal} no último ano`;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm">Projeção de pagamento</CardTitle>
        <CardDescription className="text-xs">
          Em que ano a fila alcança este crédito
          {projecao.exercicio_base ? ` · exercício base ${projecao.exercicio_base}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-md border border-primary/40 bg-primary/5 p-3">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
              {exercicio ? "Previsão de pagamento" : "Se pagar o limite da lei"}
            </p>
            <p className="text-2xl font-bold">{projecao.ano_previsto ?? "—"}</p>
            <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">{notaLei}</p>
          </div>
          <div className="rounded-md border border-border/70 p-3">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
              No ritmo real{anosRitmo > 1 ? ` (${anosRitmo} anos)` : ""}
            </p>
            <p className="text-2xl font-bold">{temRitmo ? ritmo.ano_previsto : "—"}</p>
            <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">{notaRitmo}</p>
          </div>
        </div>
        {projecao.fila_zera_em && !exercicio && (
          <p className="text-xs text-muted-foreground">
            No limite da lei, a fila inteira do ente zera em <strong>{projecao.fila_zera_em}</strong>.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function EditalBloco({ edital }: { edital: Record<string, any> }) {
  const aberto = edital.aberto === true;
  return (
    <Card className={aberto ? "border-emerald-500/40" : undefined}>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm">
          <FileText className="h-4 w-4" /> Acordo direto
          <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
            aberto ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400" : "bg-muted text-muted-foreground"}`}>
            {aberto ? "inscrição aberta" : edital.situacao ?? "encerrado"}
          </span>
        </CardTitle>
        <CardDescription className="text-xs">
          {edital.edital}{edital.municipio ? ` · ${edital.municipio}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-3">
          <Numero rotulo="Deságio" valor={
            edital.desagio_min_pct === edital.desagio_max_pct
              ? `${String(edital.desagio_min_pct ?? "—").replace(".", ",")}%`
              : `${edital.desagio_min_pct}–${edital.desagio_max_pct}%`} />
          <Numero rotulo="Inscrição" valor={`${dataBr(edital.inscricao_abre)} → ${dataBr(edital.inscricao_fecha)}`} />
          <Numero rotulo="Limite do certame" valor={brlCurto(edital.valor_certame)} />
        </div>
        {edital.observacao && (
          <p className="text-xs leading-relaxed text-muted-foreground">{edital.observacao}</p>
        )}
        {edital.url && (
          <a href={String(edital.url)} target="_blank" rel="noreferrer"
             className="inline-block text-xs underline">abrir o edital</a>
        )}
      </CardContent>
    </Card>
  );
}

// ── peças ──────────────────────────────────────────────────────────────────

function Bloco({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader className="pb-2"><CardTitle className="text-sm">{titulo}</CardTitle></CardHeader>
      <CardContent className="space-y-1 text-xs">{children}</CardContent>
    </Card>
  );
}

function Linha({ rotulo, valor }: { rotulo: string; valor: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-0.5">
      <span className="shrink-0 text-muted-foreground">{rotulo}</span>
      <span className="text-right">{valor}</span>
    </div>
  );
}

function Numero({ rotulo, valor, nota }: { rotulo: string; valor: React.ReactNode; nota?: string }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{rotulo}</p>
      <p className="text-sm font-semibold tabular-nums">{valor}</p>
      {nota && <p className="text-[11px] text-muted-foreground">{nota}</p>}
    </div>
  );
}

function Marca({ children, tom = "normal" }: { children: React.ReactNode; tom?: "normal" | "alerta" | "destaque" }) {
  const cor = tom === "alerta"
    ? "bg-destructive/15 text-destructive"
    : tom === "destaque"
    ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
    : "bg-muted text-muted-foreground";
  return <span className={`rounded px-1.5 py-0.5 font-medium ${cor}`}>{children}</span>;
}
