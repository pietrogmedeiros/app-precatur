"use client";

import { useEffect, useMemo, useState } from "react";
import { Calculator, Search, X, Link2, Check, MapPin, Download, AlertTriangle, Trash2 } from "lucide-react";
import { api, type Simulacao, type ResumoPraca, type SerieMensal, type Fatia } from "@/lib/api";
import { getUser } from "@/lib/auth";
import { SimulacoesPorMes, Rosca, PracasBarras } from "@/components/charts/simulacoes-charts";
import { cn } from "@/lib/utils";
import { formatBRL } from "@/lib/pricing";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const inputClass =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring";

function fmtData(iso: string): string {
  const d = new Date(iso);
  return `${d.toLocaleDateString("pt-BR")} ${d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
}

export default function SimulacoesPage() {
  const [itens, setItens] = useState<Simulacao[]>([]);
  const [resumo, setResumo] = useState<ResumoPraca[]>([]);
  const [mensal, setMensal] = useState<SerieMensal[]>([]);
  const [natureza, setNatureza] = useState<Fatia[]>([]);
  const [porAtivo, setPorAtivo] = useState<Fatia[]>([]);
  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [busca, setBusca] = useState("");
  const [soLeads, setSoLeads] = useState(true);
  const [aberta, setAberta] = useState<Simulacao | null>(null);
  const [linkCopiado, setLinkCopiado] = useState(false);
  const [exportando, setExportando] = useState(false);

  useEffect(() => {
    setIsAdmin(getUser()?.role === "admin");
    api.simulacoes
      .list()
      .then((r) => {
        setItens(r.itens);
        setResumo(r.resumo);
        setMensal(r.mensal);
        setNatureza(r.natureza);
        setPorAtivo(r.ativo);
      })
      .catch((e) => setErro(e.message))
      .finally(() => setLoading(false));
  }, []);

  const filtrados = useMemo(() => {
    const q = busca.trim().toLowerCase();
    return itens.filter((s) => {
      if (soLeads && !s.contato_em) return false;
      if (!q) return true;
      return [s.nome, s.email, s.telefone, s.processo, s.praca_label, s.uf, s.safra]
        .some((v) => (v ?? "").toLowerCase().includes(q));
    });
  }, [itens, busca, soLeads]);

  // Deduções que consumiram todo o bruto: o lead vale, mas os números vieram
  // errados — o time precisa ver isso antes de ligar.
  const inconsistente = (s: Simulacao) => s.bruto > 0 && s.liquido <= 0;

  const totais = useMemo(() => {
    const leads = itens.filter((s) => s.contato_em);
    return {
      simulacoes: itens.length,
      leads: leads.length,
      volume: leads.reduce((s, i) => s + i.proposta, 0),
      inconsistentes: itens.filter(inconsistente).length,
    };
  }, [itens]);

  // Exporta o que está na tela (respeita busca e filtro). Planilha de verdade em
  // vez de CSV: evita o problema clássico de acento e separador no Excel pt-BR.
  // A biblioteca é carregada só no clique, para não pesar a página.
  async function exportar() {
    setErro(null);
    setExportando(true);
    try {
      const XLSX = await import("xlsx");
      const linhas = filtrados.map((s) => ({
        "Data": fmtData(s.created_at),
        "UF": s.uf ?? "União",
        "Praça": s.praca_label,
        "Estimativa": s.estimativa ? "Sim" : "Não",
        "Safra": s.safra,
        "Ativo": s.ativo ?? "",
        "Natureza": s.natureza ?? "",
        "Principal": s.principal,
        "Juros": s.juros,
        "SELIC": s.selic,
        "Honorários %": s.honorarios_pct,
        "Honorários R$": s.honorarios,
        "IR %": s.ir_pct,
        "IR base": s.ir_base === "bruto" ? "Valor atualizado" : "Principal",
        "IR R$": s.ir,
        "PSS": s.pss,
        "Parcela preferencial": s.preferencia,
        "Outras despesas": s.outras_despesas,
        "Bruto atualizado": s.bruto,
        "Líquido": s.liquido,
        "% da tabela": s.percentual,
        "Abatimento": s.abatimento,
        "Pagaríamos": s.proposta,
        "Nome": s.nome ?? "",
        "E-mail": s.email ?? "",
        "Telefone": s.telefone ?? "",
        "Processo": s.processo ?? "",
        "WhatsApp confirmado em": s.verificado_em ? fmtData(s.verificado_em) : "",
      }));
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(linhas), "Simulações");
      XLSX.utils.book_append_sheet(
        wb,
        XLSX.utils.json_to_sheet(
          resumo.map((r) => ({
            "UF": r.uf ?? "União",
            "Praça": r.praca_label,
            "Simulações": r.simulacoes,
            "Leads": r.leads,
            "Líquido simulado": r.volume_liquido,
            "Pagaríamos": r.volume_proposta,
          }))
        ),
        "Por praça"
      );
      XLSX.writeFile(wb, `simulacoes-${new Date().toISOString().slice(0, 10)}.xlsx`);
    } catch (e: any) {
      setErro(e?.message ?? "Não foi possível exportar.");
    } finally {
      setExportando(false);
    }
  }

  function copiarLink() {
    const url = `${window.location.origin}/calcular`;
    navigator.clipboard?.writeText(url).then(
      () => {
        setLinkCopiado(true);
        setTimeout(() => setLinkCopiado(false), 2000);
      },
      () => setErro(`Copie manualmente: ${url}`)
    );
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6 md:p-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <Calculator className="h-6 w-6" />
            Simulações
          </h1>
          <p className="text-sm text-muted-foreground">
            O que foi simulado na calculadora pública e quem pediu proposta.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" className="gap-2" onClick={exportar}
            disabled={exportando || !filtrados.length}
            title={filtrados.length ? "Exporta o que está filtrado na tela" : "Nada para exportar"}>
            <Download className="h-4 w-4" />
            {exportando ? "Gerando…" : `Exportar (${filtrados.length})`}
          </Button>
          <Button variant="outline" className="gap-2" onClick={copiarLink}>
            {linkCopiado ? <Check className="h-4 w-4" /> : <Link2 className="h-4 w-4" />}
            {linkCopiado ? "Link copiado" : "Copiar link da calculadora"}
          </Button>
        </div>
      </header>

      {erro ? <p className="rounded-md bg-secondary px-3 py-2 text-sm text-red-600">{erro}</p> : null}

      <div className="grid gap-4 sm:grid-cols-3">
        <Indicador titulo="Simulações" valor={String(totais.simulacoes)} nota="inclui quem não deixou contato" />
        <Indicador titulo="Pediram proposta" valor={String(totais.leads)}
          nota={totais.simulacoes ? `${Math.round((totais.leads / totais.simulacoes) * 100)}% das simulações` : "—"} />
        <Indicador titulo="Volume dos leads" valor={formatBRL(totais.volume)} nota="soma do que pagaríamos" />
      </div>

      {totais.inconsistentes ? (
        <p className="flex items-start gap-2 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
          <span>
            {totais.inconsistentes} simulação(ões) com deduções maiores que o valor atualizado — o
            resultado saiu zerado. Vale conferir antes de abordar.
          </span>
        </p>
      ) : null}

      {itens.length ? (
        <>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Simulações nos últimos 6 meses</CardTitle>
              <CardDescription>Quantas foram feitas e quantas confirmaram o WhatsApp.</CardDescription>
            </CardHeader>
            <CardContent>
              <SimulacoesPorMes dados={mensal} />
            </CardContent>
          </Card>

          <div className="grid gap-4 lg:grid-cols-3">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Natureza do precatório</CardTitle>
              </CardHeader>
              <CardContent>
                <Rosca dados={natureza} total={itens.length} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Tipo de ativo</CardTitle>
              </CardHeader>
              <CardContent>
                <Rosca dados={porAtivo} total={itens.length} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Praças mais simuladas</CardTitle>
                <CardDescription>Simulações e quanto pagaríamos.</CardDescription>
              </CardHeader>
              <CardContent>
                <PracasBarras dados={resumo} />
              </CardContent>
            </Card>
          </div>
        </>
      ) : null}

      {resumo.length ? (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <MapPin className="h-4 w-4" />
              Histórico por praça
            </CardTitle>
            <CardDescription>Onde estão os precatórios que o mercado está consultando.</CardDescription>
          </CardHeader>
          <CardContent className="px-0">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-sm">
                <thead className="bg-secondary text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2 font-medium">Praça</th>
                    <th className="px-4 py-2 text-right font-medium">Simulações</th>
                    <th className="px-4 py-2 text-right font-medium">Leads</th>
                    <th className="px-4 py-2 text-right font-medium">Líquido simulado</th>
                    <th className="px-4 py-2 text-right font-medium">Pagaríamos</th>
                  </tr>
                </thead>
                <tbody>
                  {resumo.map((r, i) => (
                    <tr key={i} className="border-t">
                      <td className="px-4 py-2">
                        <span className="font-medium">{r.uf ?? "União"}</span>
                        <span className="text-muted-foreground"> · {r.praca_label}</span>
                      </td>
                      <td className="px-4 py-2 text-right tabular-nums">{r.simulacoes}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{r.leads}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{formatBRL(r.volume_liquido)}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{formatBRL(r.volume_proposta)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:max-w-xs">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input className={cn(inputClass, "pl-9")} placeholder="Buscar por nome, praça, processo…"
            value={busca} onChange={(e) => setBusca(e.target.value)} />
        </div>
        <button onClick={() => setSoLeads(true)}
          className={cn("rounded-md border px-2.5 py-1.5 text-xs font-medium", soLeads ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent")}>
          Com contato ({totais.leads})
        </button>
        <button onClick={() => setSoLeads(false)}
          className={cn("rounded-md border px-2.5 py-1.5 text-xs font-medium", !soLeads ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent")}>
          Todas ({totais.simulacoes})
        </button>
      </div>

      {loading ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Carregando…</p>
      ) : !filtrados.length ? (
        <Card>
          <CardContent className="py-12 text-center">
            <Calculator className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              {itens.length ? "Nenhuma simulação para esse filtro." : "Nenhuma simulação ainda. Compartilhe o link da calculadora."}
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {filtrados.map((s) => (
            <Card key={s.id} className="cursor-pointer transition-colors hover:bg-accent/40" onClick={() => setAberta(s)}>
              <CardHeader className="flex flex-col gap-2 pb-3 sm:flex-row sm:items-start sm:justify-between sm:space-y-0">
                <div className="min-w-0">
                  <CardTitle className="text-base">
                    {s.nome ?? "Simulação sem contato"}
                  </CardTitle>
                  <CardDescription className="truncate">
                    {s.uf ?? "União"} · {s.praca_label} · safra {s.safra}
                    {s.estimativa ? " · estimativa" : ""}
                  </CardDescription>
                </div>
                <div className="shrink-0 text-right">
                  {inconsistente(s) ? (
                    <span className="inline-flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-900">
                      <AlertTriangle className="h-3 w-3" />
                      Deduções acima do valor
                    </span>
                  ) : (
                    <>
                      <div className="font-semibold tabular-nums">{formatBRL(s.proposta)}</div>
                      <div className="text-xs text-muted-foreground">{s.percentual}% do líquido</div>
                    </>
                  )}
                </div>
              </CardHeader>
              <CardContent className="flex flex-wrap items-center gap-x-4 gap-y-1 pt-0 text-xs text-muted-foreground">
                <span>{fmtData(s.created_at)}</span>
                <span>Líquido {formatBRL(s.liquido)}</span>
                {s.verificado_em ? <span className="text-emerald-700">WhatsApp confirmado</span> : <span>Não confirmou o código</span>}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {aberta ? (
        <Detalhe
          s={aberta}
          isAdmin={isAdmin}
          onClose={() => setAberta(null)}
          onApagar={async () => {
            if (!confirm(`Apagar a simulação #${aberta.id}? Isso não pode ser desfeito.`)) return;
            try {
              await api.simulacoes.remove(aberta.id);
              setItens((cur) => cur.filter((i) => i.id !== aberta.id));
              setAberta(null);
            } catch (e: any) {
              setErro(e.message);
            }
          }}
        />
      ) : null}
    </div>
  );
}

function Indicador({ titulo, valor, nota }: { titulo: string; valor: string; nota: string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{titulo}</div>
        <div className="mt-1 text-2xl font-bold tabular-nums">{valor}</div>
        <div className="text-xs text-muted-foreground">{nota}</div>
      </CardContent>
    </Card>
  );
}

function Detalhe({ s, onClose, isAdmin, onApagar }: { s: Simulacao; onClose: () => void; isAdmin: boolean; onApagar: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4" onClick={onClose}>
      <div className="my-8 w-full max-w-2xl rounded-lg border bg-card p-6 shadow-lg" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">Simulação #{s.id}</h2>
            <p className="text-sm text-muted-foreground">
              {s.uf ?? "União"} · {s.praca_label} · safra {s.safra} · {s.ativo} · {s.natureza ?? "—"}
            </p>
            <p className="text-xs text-muted-foreground">Feita em {fmtData(s.created_at)}</p>
          </div>
          <button onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:bg-accent" aria-label="Fechar">
            <X className="h-4 w-4" />
          </button>
        </div>

        {s.estimativa ? (
          <p className="mb-4 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">
            Praça sem tabela própria — o valor saiu do {s.praca_label} e foi apresentado como estimativa.
          </p>
        ) : null}

        <div className="mb-5">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">A conta</div>
          <dl className="space-y-1.5 text-sm">
            <Linha k="Principal" v={formatBRL(s.principal)} />
            <Linha k="Juros" v={formatBRL(s.juros)} />
            <Linha k="SELIC" v={formatBRL(s.selic)} />
            <div className="flex justify-between border-t pt-1.5 font-medium">
              <dt>Bruto atualizado</dt>
              <dd className="tabular-nums">{formatBRL(s.bruto)}</dd>
            </div>
            <Linha k={`Honorários (${s.honorarios_pct}%)`} v={`− ${formatBRL(s.honorarios)}`} />
            <Linha k={`IR (${s.ir_pct}% sobre ${s.ir_base === "bruto" ? "o atualizado" : "o principal"})`} v={`− ${formatBRL(s.ir)}`} />
            {s.pss ? <Linha k="PSS" v={`− ${formatBRL(s.pss)}`} /> : null}
            {s.preferencia ? <Linha k="Parcela preferencial" v={`− ${formatBRL(s.preferencia)}`} /> : null}
            {s.outras_despesas ? <Linha k="Outras despesas" v={`− ${formatBRL(s.outras_despesas)}`} /> : null}
            <div className="flex justify-between border-t pt-1.5 font-semibold">
              <dt>Líquido</dt>
              <dd className="tabular-nums">{formatBRL(s.liquido)}</dd>
            </div>
          </dl>
        </div>

        <div className="mb-5 rounded-lg bg-primary p-4 text-primary-foreground">
          <div className="text-xs font-medium uppercase tracking-wider opacity-80">Valor apresentado</div>
          <div className="text-2xl font-bold tabular-nums">{formatBRL(s.proposta)}</div>
          <div className="text-xs opacity-80">
            {s.percentual}% do líquido{s.abatimento ? ` · abatimento de ${formatBRL(s.abatimento)}` : ""}
          </div>
        </div>

        {s.bruto > 0 && s.liquido <= 0 ? (
          <p className="mb-5 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">
            As deduções informadas somam mais que o valor atualizado, então o líquido ficou zerado e nada
            foi oferecido. O contato continua válido — provavelmente houve erro de digitação em algum campo.
          </p>
        ) : null}

        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Contato</div>
          {s.contato_em ? (
            <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
              <Item r="Nome / escritório" v={s.nome} />
              <Item r="E-mail" v={s.email} />
              <Item r="Telefone / WhatsApp" v={s.telefone} />
              <Item r="Processo" v={s.processo} />
              <Item r="WhatsApp confirmado em" v={s.verificado_em ? fmtData(s.verificado_em) : "—"} />
            </dl>
          ) : (
            <p className="text-sm text-muted-foreground">
              Preencheu os dados mas não confirmou o código do WhatsApp — o valor não chegou a ser mostrado.
            </p>
          )}
        </div>

        {isAdmin ? (
          <div className="mt-6 flex justify-end border-t pt-4">
            <Button variant="outline" size="sm" className="gap-2 text-red-600" onClick={onApagar}>
              <Trash2 className="h-4 w-4" />
              Apagar simulação
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function Linha({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="tabular-nums">{v}</dd>
    </div>
  );
}

function Item({ r, v }: { r: string; v: string | null }) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{r}</dt>
      <dd className="text-sm">{v || "—"}</dd>
    </div>
  );
}
