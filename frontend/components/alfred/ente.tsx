"use client";

// Saúde do ente devedor: o que ele deve, como vem pagando e em que ano a fila
// zera. É a pergunta que vem antes da do crédito — não adianta o precatório ser
// bom se quem deve não paga.

import { useEffect, useState } from "react";
import { Loader2, Search, ChevronRight } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  brl, brlCurto, numero, buscarDevedores, saudeDoEnte, filaDoEnte,
  type Devedor, type FilaDoEnte,
} from "@/lib/alfred";
import { inputClass } from "@/components/calculadora/campos";

export function AbaEnte({ aoAbrirPrecatorio }: { aoAbrirPrecatorio: (id: number) => void }) {
  const [termo, setTermo] = useState("");
  const [achados, setAchados] = useState<Devedor[] | null>(null);
  const [ente, setEnte] = useState<Record<string, any> | null>(null);
  const [fila, setFila] = useState<FilaDoEnte | null>(null);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  async function tentar(rotulo: string, acao: () => Promise<void>) {
    setOcupado(rotulo); setErro(null);
    try { await acao(); } catch (e: any) { setErro(e?.message ?? "Falhou."); }
    finally { setOcupado(null); }
  }

  const procurar = () => tentar("busca", async () => {
    setEnte(null); setFila(null);
    setAchados((await buscarDevedores(termo.trim())).itens);
  });

  const abrir = (chave: string) => tentar("ente", async () => {
    const s = await saudeDoEnte(chave);
    setEnte(s); setAchados(null); setFila(null);
    const primeiro = (s.orgaos ?? [])[0];
    if (primeiro?.id) setFila(await filaDoEnte(primeiro.id, 0, 100));
  });

  return (
    <div className="space-y-5">
      <div className="flex gap-2">
        <input
          className={inputClass}
          placeholder="Município, Estado ou órgão devedor (ex.: Salvador, Estado da Bahia)"
          value={termo}
          onChange={(e) => setTermo(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void procurar(); } }}
        />
        <Button type="button" onClick={() => void procurar()} disabled={termo.trim().length < 2 || !!ocupado}>
          {ocupado === "busca" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          Procurar
        </Button>
      </div>

      {erro && <Aviso>{erro}</Aviso>}

      {achados?.length === 0 && <Aviso>Nenhum devedor encontrado para “{termo}”.</Aviso>}
      {achados && achados.length > 0 && (
        <div className="space-y-1">
          {achados.map((a) => (
            <button key={a.chave} type="button" onClick={() => void abrir(a.chave)}
              className="flex w-full items-center justify-between gap-3 rounded-md border border-border/70 px-3 py-2 text-left text-xs hover:bg-accent">
              <span>
                <span className="font-medium">{a.nome}</span>
                {a.uf && <span className="text-muted-foreground"> · {a.uf}</span>}
                {a.regime && <span className="text-muted-foreground"> · {a.regime}</span>}
              </span>
              <span className="flex items-center gap-3 text-muted-foreground">
                <span>{numero(a.n)} precatórios</span>
                <span className="tabular-nums">{brlCurto(a.valor)}</span>
                <ChevronRight className="h-3 w-3" />
              </span>
            </button>
          ))}
        </div>
      )}

      {ocupado === "ente" && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> carregando o ente…
        </p>
      )}

      {ente && <SaudeDoEnte ente={ente} fila={fila} aoAbrirPrecatorio={aoAbrirPrecatorio} />}
    </div>
  );
}

function SaudeDoEnte({
  ente, fila, aoAbrirPrecatorio,
}: {
  ente: Record<string, any>;
  fila: FilaDoEnte | null;
  aoAbrirPrecatorio: (id: number) => void;
}) {
  const proj = (ente.projecoes ?? [])[0];
  return (
    <div className="space-y-5">
      <Card className="border-primary/30 bg-primary/5">
        <CardContent className="p-5">
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            {ente.tipo === "municipio" ? "Município" : "Ente"} · {ente.uf} · regime {ente.regime ?? "—"}
          </p>
          <p className="mt-0.5 text-xl font-bold tracking-tight">{ente.nome}</p>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <Numero rotulo={`RCL ${ente.ano_rcl ?? ""}`} valor={brlCurto(ente.rcl)} nota={ente.fonte_rcl} />
            {proj && <Numero rotulo="Fila zera (lei)" valor={proj.fila_zera_lei ?? "—"} />}
            {proj && <Numero rotulo="Fila zera (ritmo observado)" valor={proj.fila_zera_ritmo ?? "—"} />}
          </div>
        </CardContent>
      </Card>

      {Array.isArray(ente.avisos) && ente.avisos.length > 0 && (
        <div className="space-y-2">
          {ente.avisos.map((a: string) => (
            <div key={a} className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs leading-relaxed text-amber-800 dark:text-amber-300">{a}</div>
          ))}
        </div>
      )}

      {ente.pagamento && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Comportamento de pagamento</CardTitle>
            <CardDescription className="text-xs">{ente.pagamento.fonte}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm">{ente.pagamento.resumo}</p>
            <div className="grid gap-3 sm:grid-cols-4">
              <Numero rotulo="Estoque de abertura" valor={brlCurto(ente.pagamento.estoque_abertura)} />
              <Numero rotulo="Pago no ano" valor={brlCurto(ente.pagamento.pago_no_ano)} />
              <Numero rotulo="Saldo" valor={brlCurto(ente.pagamento.saldo_fim_ano)} />
              <Numero rotulo="Expedidos" valor={brlCurto(ente.pagamento.expedidos_no_ano)} />
            </div>
          </CardContent>
        </Card>
      )}

      {proj && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">Orçamento e mora</CardTitle></CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-4">
            <Numero rotulo="Orçamento anual" valor={brlCurto(proj.orcamento_anual)} nota={proj.fonte_orcamento} />
            <Numero rotulo="Teto do §23" valor={brlCurto(proj.teto_p23)} />
            <Numero rotulo="Pago no ano" valor={brlCurto(proj.pago_no_ano)}
              nota={proj.pct_do_teto != null ? `${String(proj.pct_do_teto).replace(".", ",")}% do teto` : undefined} />
            <Numero rotulo="Mora na fila" valor={brlCurto(proj.mora_fila)} nota={proj.base_mora} />
          </CardContent>
        </Card>
      )}

      {Array.isArray(ente.por_ano) && ente.por_ano.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Estoque por ano de orçamento</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="max-h-64 overflow-auto rounded-md border border-border/70">
              <table className="w-full text-[11px]">
                <thead className="sticky top-0 bg-muted/80 text-left">
                  <tr><th className="px-2 py-1">Ano</th><th className="px-2 py-1 text-right">Qtd.</th><th className="px-2 py-1 text-right">Valor</th></tr>
                </thead>
                <tbody>
                  {ente.por_ano.map((a: any) => (
                    <tr key={a.ano} className="border-t border-border/50">
                      <td className="px-2 py-1">{a.ano ?? "—"}</td>
                      <td className="px-2 py-1 text-right tabular-nums">{numero(a.n)}</td>
                      <td className="px-2 py-1 text-right tabular-nums">{brl(a.valor)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {fila && fila.itens.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Fila cronológica</CardTitle>
            <CardDescription className="text-xs">
              {fila.ente} · {fila.tribunal} — mostrando {fila.itens.length} de {numero(fila.total)}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="max-h-96 overflow-auto rounded-md border border-border/70">
              <table className="w-full text-[11px]">
                <thead className="sticky top-0 bg-muted/80 text-left">
                  <tr>
                    <th className="px-2 py-1">#</th><th className="px-2 py-1">Credor</th>
                    <th className="px-2 py-1 text-right">Valor</th><th className="px-2 py-1 text-right">Acumulado</th>
                  </tr>
                </thead>
                <tbody>
                  {fila.itens.map((i) => (
                    <tr key={i.id} onClick={() => aoAbrirPrecatorio(i.id)}
                        className="cursor-pointer border-t border-border/50 hover:bg-accent">
                      <td className="px-2 py-1 tabular-nums">{i.ordem ?? "—"}</td>
                      <td className="px-2 py-1">{i.credor ?? <span className="text-muted-foreground">não publicado</span>}</td>
                      <td className="px-2 py-1 text-right tabular-nums">{brl(i.valor)}</td>
                      <td className="px-2 py-1 text-right tabular-nums text-muted-foreground">{brlCurto(i.acumulado)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
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

function Aviso({ children }: { children: React.ReactNode }) {
  return <div className="rounded-md border border-border bg-muted/50 px-3 py-2 text-xs text-muted-foreground">{children}</div>;
}
