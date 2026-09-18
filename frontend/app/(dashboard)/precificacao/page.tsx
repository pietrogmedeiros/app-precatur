"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Calculator, FileText, Pencil, Upload } from "lucide-react";
import { api, type PricingEntity, type PricingImport } from "@/lib/api";
import { getUser } from "@/lib/auth";
import { cn } from "@/lib/utils";
import {
  QUARTERS,
  assetsOf,
  availableRows,
  currentQuarterIndex,
  extractBlock,
  finalProposal,
  formatBRL,
  formatDecimal,
  formatPct,
  hasAssetChoice,
  parseBRL,
  paymentYearOf,
  pctFromProposal,
  yearsUntil,
} from "@/lib/pricing";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { CurveChart } from "@/components/pricing/curve-chart";
import { Simulator } from "@/components/pricing/simulator";
import { TableEditor } from "@/components/pricing/table-editor";

const inputClass =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring";

function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  return `${d.toLocaleDateString("pt-BR")} às ${d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
}

export default function PrecificacaoPage() {
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement>(null);

  const [entities, setEntities] = useState<PricingEntity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [importing, setImporting] = useState(false);

  // Seleção (mesmo modelo da calculadora antiga).
  const [entityKey, setEntityKey] = useState("federal");
  const [asset, setAsset] = useState("Precatório");
  const [rowIndex, setRowIndex] = useState(0);
  const [quarter, setQuarter] = useState(0);
  const [anoAtual, setAnoAtual] = useState(new Date().getFullYear());

  // Calculadora: percentual e valor da proposta ficam sincronizados.
  const [face, setFace] = useState(100000);
  const [faceText, setFaceText] = useState(formatDecimal(100000));
  const [pct, setPct] = useState(0);
  const [pctText, setPctText] = useState("0,00");
  const [proposalText, setProposalText] = useState("0,00");

  const entity = entities.find((e) => e.key === entityKey) ?? entities[0];
  const rows = entity ? availableRows(entity, asset) : [];
  const row = rows[rowIndex] ?? rows[0];
  const tablePct = row ? row.values[quarter] : 0;
  const deduction = entity?.fixed_deduction ?? 0;
  const proposal = finalProposal(face, pct, deduction);

  // Carrega o preço de tabela da seleção atual no campo de percentual.
  const loadTablePrice = useCallback((value: number) => {
    setPct(value);
    setPctText(formatDecimal(value));
  }, []);

  useEffect(() => {
    // Trimestre e ano só no cliente, para o render do servidor não divergir.
    setQuarter(currentQuarterIndex());
    setAnoAtual(new Date().getFullYear());
    setIsAdmin(getUser()?.role === "admin");
    api.pricing
      .list()
      .then(setEntities)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // Ao carregar as tabelas (ou mudar a seleção), o percentual volta ao de tabela.
  useEffect(() => {
    if (row) loadTablePrice(row.values[quarter]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entities, entityKey, asset, rowIndex, quarter]);

  useEffect(() => {
    setProposalText(formatDecimal(proposal));
  }, [proposal]);

  function selectEntity(key: string) {
    const next = entities.find((e) => e.key === key);
    setEntityKey(key);
    setRowIndex(0);
    if (next) setAsset(next.rows[0]?.asset ?? "Precatório");
    setOk(null);
  }

  function commitFace() {
    const v = Math.max(0, parseBRL(faceText));
    setFace(v);
    setFaceText(formatDecimal(v));
  }

  function commitPct(text: string) {
    setPctText(text);
    const v = Number(text.replace(",", "."));
    if (Number.isFinite(v)) setPct(Math.max(0, Math.min(100, v)));
  }

  function commitProposal() {
    const v = pctFromProposal(parseBRL(proposalText), face, deduction);
    setPct(v);
    setPctText(formatDecimal(v));
  }

  // Ponte com o gerador: abre /proposta já preenchida com o que foi calculado.
  function sendToProposal() {
    const params = new URLSearchParams({
      face: String(face),
      liquido: String(Math.round(proposal * 100) / 100),
    });
    const ano = row ? paymentYearOf(row.year) : null;
    if (ano) params.set("ano", String(ano));
    if (entity?.key === "federal") params.set("ente", "União");
    router.push(`/proposta?${params.toString()}`);
  }

  async function onImportFile(file: File) {
    setError(null);
    setOk(null);
    setImporting(true);
    try {
      // Carregada sob demanda: só admin importa, ninguém mais paga esse peso.
      const XLSX = await import("xlsx");
      const wb = XLSX.read(await file.arrayBuffer(), { type: "array" });
      const sheet = XLSX.utils.sheet_to_json<unknown[]>(wb.Sheets[wb.SheetNames[0]], { header: 1, defval: "" });

      const found: PricingImport = {};
      const resumo: string[] = [];
      for (const [key, word, nome] of [
        ["federal", "FEDERAL", "Federal"],
        ["estadual", "ESTADUAL", "Estadual"],
        ["municipal", "MUNICIPAL", "Municipal"],
      ] as const) {
        const block = extractBlock(sheet, word);
        if (block.length) {
          found[key] = block;
          resumo.push(`${nome} (${block.length} safras)`);
        }
      }
      if (!resumo.length) {
        setError("Não encontrei as tabelas Federal, Estadual ou Municipal na planilha. Confira se segue o modelo comercial.");
        return;
      }
      if (!confirm(`Substituir para todo o time: ${resumo.join(", ")}?\n\nA versão atual fica guardada no histórico.`)) {
        return;
      }
      const res = await api.pricing.import(found);
      setEntities(res.entities);
      setOk(
        `Tabelas atualizadas para todo o time: ${resumo.join(", ")}.` +
          (found.municipal ? " Pernambuco e Mato Grosso acompanham a Municipal automaticamente." : "")
      );
    } catch (e: any) {
      setError(e.message ?? "Não foi possível processar a planilha.");
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const suggestion = useMemo(
    () => ({
      antecipar: proposal,
      esperar: face,
      years: row ? yearsUntil(row.year, anoAtual) : null,
    }),
    [proposal, face, row, anoAtual]
  );

  if (loading) {
    return <p className="p-8 text-center text-sm text-muted-foreground">Carregando tabelas…</p>;
  }
  if (!entity || !row) {
    return <p className="p-8 text-center text-sm text-muted-foreground">{error ?? "Nenhuma tabela de preço cadastrada."}</p>;
  }

  const ruleMessage = entity.fixed_deduction
    ? { tone: "warn", title: `Regra ${entity.label}:`, text: `será descontado automaticamente ${formatBRL(entity.fixed_deduction)} do valor final calculado.` }
    : entity.municipal_reference
      ? { tone: "warn", title: "Referência Municipal:", text: "esta precificação usa a curva do Regime Geral Municipal. Ajuste manualmente caso exista orientação adicional de pagamento." }
      : entity.key === "mg"
        ? { tone: "warn", title: "Atenção:", text: "quando abrir o edital, o preço do precatório deverá ser igualado ao do direito creditório, conforme a orientação comercial." }
        : { tone: "ok", title: "Preço máximo de compra:", text: "a proposta foi carregada com base na tabela selecionada. Você pode ajustar o percentual ou o valor diretamente." };

  const adjustment = pct - tablePct;

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6 md:p-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <Calculator className="h-6 w-6" />
            Precificação
          </h1>
          <p className="text-sm text-muted-foreground">
            Preço máximo de compra, proposta e simulação para o cliente — com a mesma tabela para todo o time.
          </p>
        </div>
        {isAdmin ? (
          <div className="flex flex-wrap gap-2">
            <input ref={fileRef} type="file" accept=".xlsx,.xls" className="hidden"
              onChange={(e) => e.target.files?.[0] && onImportFile(e.target.files[0])} />
            <Button variant="outline" className="gap-2" disabled={importing} onClick={() => fileRef.current?.click()}>
              <Upload className="h-4 w-4" />
              {importing ? "Importando…" : "Importar planilha"}
            </Button>
            <Button variant="outline" className="gap-2" disabled={entity.municipal_reference}
              title={entity.municipal_reference ? "Segue a tabela Municipal — edite a Municipal" : undefined}
              onClick={() => setEditorOpen(true)}>
              <Pencil className="h-4 w-4" />
              Editar tabela
            </Button>
          </div>
        ) : null}
      </header>

      {error ? <p className="rounded-md bg-secondary px-3 py-2 text-sm text-red-600">{error}</p> : null}
      {ok ? <p className="rounded-md bg-secondary px-3 py-2 text-sm text-green-700">{ok}</p> : null}

      <nav className="flex gap-2 overflow-x-auto pb-1" aria-label="Seleção de ente">
        {entities.map((e) => (
          <button key={e.key} onClick={() => selectEntity(e.key)}
            className={cn(
              "shrink-0 rounded-md border px-3 py-1.5 text-sm font-medium transition-colors",
              e.key === entity.key ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent"
            )}>
            {e.label}
          </button>
        ))}
      </nav>

      <div>
        <h2 className="text-xl font-semibold">{entity.label}</h2>
        <p className="text-sm text-muted-foreground">{entity.description}</p>
        <p className="mt-1 text-xs text-muted-foreground">
          Tabela atualizada em {fmtDateTime(entity.updated_at)}
          {entity.updated_by ? ` por ${entity.updated_by}` : ""}
          {entity.municipal_reference ? " (tabela Municipal)" : ""}.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.35fr_1fr] lg:items-start">
        <Card>
          <CardHeader>
            <CardTitle>Parâmetros de precificação</CardTitle>
            <CardDescription>Escolha a safra e o trimestre; o percentual de tabela vai para a calculadora.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            {hasAssetChoice(entity) ? (
              <Choices label="Tipo de ativo">
                {assetsOf(entity).map((a) => (
                  <Choice key={a} active={a === asset} onClick={() => { setAsset(a); setRowIndex(0); }}>{a}</Choice>
                ))}
              </Choices>
            ) : null}

            <Choices label="Safra / ano de previsão de pagamento">
              {rows.map((r, i) => (
                <Choice key={`${r.year}-${r.asset}`} active={i === rowIndex} onClick={() => setRowIndex(i)}
                  sub={formatPct(r.values[quarter])}>{r.year}</Choice>
              ))}
            </Choices>

            <Choices label="Trimestre vigente">
              {QUARTERS.map((q, i) => (
                <Choice key={q} active={i === quarter} onClick={() => setQuarter(i)} sub={formatPct(row.values[i])}>{q}</Choice>
              ))}
            </Choices>

            <p className={cn("rounded-md px-3 py-2 text-sm",
              ruleMessage.tone === "warn" ? "bg-amber-50 text-amber-900" : "bg-emerald-50 text-emerald-900")}>
              <strong>{ruleMessage.title}</strong> {ruleMessage.text}
            </p>

            <div className="overflow-x-auto rounded-md border">
              <table className="w-full min-w-[520px] text-sm">
                <thead className="bg-secondary text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 font-medium">Safra / regra</th>
                    {QUARTERS.map((q) => <th key={q} className="px-3 py-2 text-right font-medium">{q}</th>)}
                    <th className="px-3 py-2 font-medium">Ativo</th>
                  </tr>
                </thead>
                <tbody>
                  {entity.rows.map((r, i) => {
                    const sel = r.year === row.year && r.asset === row.asset;
                    return (
                      <tr key={i} className={cn("border-t", sel && "bg-primary/10 font-medium")}>
                        <td className="px-3 py-2">{r.year}</td>
                        {r.values.map((v, q) => (
                          <td key={q} className={cn("px-3 py-2 text-right tabular-nums", sel && q === quarter && "text-primary underline")}>
                            {formatPct(v)}
                          </td>
                        ))}
                        <td className="px-3 py-2">{r.asset}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Calculadora de proposta</CardTitle>
            <CardDescription>Percentual e valor da proposta são sincronizados.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <label className="block space-y-1.5 text-sm font-medium">
              <span>Valor cheio / líquido do crédito (R$)</span>
              <input className={inputClass} inputMode="decimal" value={faceText}
                onChange={(e) => setFaceText(e.target.value)} onBlur={commitFace}
                onKeyDown={(e) => e.key === "Enter" && commitFace()} />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block space-y-1.5 text-sm font-medium">
                <span>Percentual que vamos pagar (%)</span>
                <input className={inputClass} inputMode="decimal" value={pctText}
                  onChange={(e) => commitPct(e.target.value)} onBlur={() => setPctText(formatDecimal(pct))} />
              </label>
              <label className="block space-y-1.5 text-sm font-medium">
                <span>Valor da proposta (R$)</span>
                <input className={inputClass} inputMode="decimal" value={proposalText}
                  onChange={(e) => setProposalText(e.target.value)} onBlur={commitProposal}
                  onKeyDown={(e) => e.key === "Enter" && commitProposal()} />
              </label>
            </div>

            <div className="rounded-lg bg-primary p-4 text-primary-foreground">
              <div className="text-xs font-medium uppercase tracking-wider opacity-80">Proposta sugerida ao cliente</div>
              <div className="mt-1 text-3xl font-bold tabular-nums">{formatBRL(proposal)}</div>
              <div className="mt-1 text-xs opacity-80">
                {deduction
                  ? `Bruto ${formatBRL(face * (pct / 100))} · abatimento ${formatBRL(deduction)} · final ${formatBRL(proposal)}`
                  : `Valor cheio de ${formatBRL(face)} · pagamento de ${formatPct(pct)}`}
              </div>
            </div>

            <div className="grid grid-cols-3 gap-2 text-center">
              <Metric label="Preço de tabela" value={formatPct(tablePct)} />
              <Metric label="Deságio" value={formatPct(100 - pct)} />
              <Metric label="Ajuste manual"
                value={`${adjustment >= 0 ? "+" : ""}${adjustment.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} p.p.`}
                warn={Math.abs(adjustment) > 0.005} />
            </div>

            <Button className="w-full gap-2" onClick={sendToProposal} disabled={!face}>
              <FileText className="h-4 w-4" />
              Usar na proposta
            </Button>
            <p className="text-center text-xs text-muted-foreground">
              Abre o gerador já com valor de face, valor líquido
              {paymentYearOf(row.year) ? ` e ano de pagamento (${paymentYearOf(row.year)})` : ""}.
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Curva de precificação por trimestre</CardTitle>
          <CardDescription>Safra selecionada: {row.year} · ativo: {row.asset}</CardDescription>
        </CardHeader>
        <CardContent>
          <CurveChart entityLabel={entity.label} row={row} quarter={quarter} />
        </CardContent>
      </Card>

      <Simulator suggested={suggestion} />

      <TableEditor entity={entity} open={editorOpen} onClose={() => setEditorOpen(false)}
        onSaved={(list) => { setEntities(list); setOk(`Tabela ${entity.label} atualizada para todo o time.`); }} />
    </div>
  );
}

function Choices({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{label}</span>
      <div className="flex flex-wrap gap-2">{children}</div>
    </div>
  );
}

function Choice({ active, onClick, sub, children }: {
  active: boolean; onClick: () => void; sub?: string; children: React.ReactNode;
}) {
  return (
    <button onClick={onClick}
      className={cn(
        "flex flex-col items-start rounded-md border px-3 py-1.5 text-left text-sm font-medium transition-colors",
        active ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent"
      )}>
      <span>{children}</span>
      {sub ? <span className={cn("text-xs", active ? "opacity-80" : "text-muted-foreground")}>{sub}</span> : null}
    </button>
  );
}

function Metric({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="rounded-md border px-2 py-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className={cn("text-sm font-semibold tabular-nums", warn && "text-amber-700")}>{value}</div>
    </div>
  );
}
