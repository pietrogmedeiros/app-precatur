"use client";

import { useEffect, useState } from "react";
import { FileText, Printer, Save, Trash2, RotateCcw, Download } from "lucide-react";
import { api, type Proposal, type ProposalInput } from "@/lib/api";
import { cn, formatMoney } from "@/lib/utils";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";

const inputClass =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring";
const textareaClass =
  "flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring";

function num(v: string): number {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : 0;
}

function naturezaLabel(v: string): string {
  if (v === "alimentar") return "Alimentar";
  if (v === "comum") return "Comum";
  return v || "—";
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" });
}

export default function PropostaPage() {
  // Form state
  const [proposalNumber, setProposalNumber] = useState("");
  const [proposalDate, setProposalDate] = useState("");
  const [clientName, setClientName] = useState("");
  const [clientDoc, setClientDoc] = useState("");
  const [clientContact, setClientContact] = useState("");
  const [precatorioNumber, setPrecatorioNumber] = useState("");
  const [tribunal, setTribunal] = useState("");
  const [enteDevedor, setEnteDevedor] = useState("");
  const [natureza, setNatureza] = useState("alimentar");
  const [valorFace, setValorFace] = useState("");
  const [valorProposta, setValorProposta] = useState("");
  const [formaPagamento, setFormaPagamento] = useState(
    "À vista, em até 5 dias úteis após a assinatura do contrato de cessão de crédito."
  );
  const [validade, setValidade] = useState("10 dias corridos a partir da data de emissão.");
  const [observacoes, setObservacoes] = useState("");
  const [responsavel, setResponsavel] = useState("");

  const [history, setHistory] = useState<Proposal[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Importação do Bitrix
  const [bitrixRef, setBitrixRef] = useState("");
  const [bitrixLoading, setBitrixLoading] = useState(false);
  const [bitrixErr, setBitrixErr] = useState<string | null>(null);

  const faceNum = num(valorFace);
  const propostaNum = num(valorProposta);
  const desagio = faceNum > 0 ? (1 - propostaNum / faceNum) * 100 : 0;
  // Deságio só é exibível quando há face (>0) e proposta preenchidos; senão "—".
  const desagioDisplay =
    valorFace.trim() && valorProposta.trim() && faceNum > 0 ? `${desagio.toFixed(1)}%` : "—";

  function loadHistory() {
    api.proposals
      .list()
      .then(setHistory)
      .catch((e) => setError(e.message));
  }

  async function importBitrix() {
    setBitrixErr(null);
    setOk(null);
    const ref = bitrixRef.trim();
    if (!ref) {
      setBitrixErr("Cole o link ou o ID do deal.");
      return;
    }
    setBitrixLoading(true);
    try {
      const d = await api.bitrixDeal(ref);
      // Preenche apenas os campos não-nulos; null preserva o que já foi digitado.
      if (d.clientName != null) setClientName(d.clientName);
      if (d.clientDoc != null) setClientDoc(d.clientDoc);
      if (d.clientContact != null) setClientContact(d.clientContact);
      if (d.precatorioNumber != null) setPrecatorioNumber(d.precatorioNumber);
      if (d.tribunal != null) setTribunal(d.tribunal);
      if (d.enteDevedor != null) setEnteDevedor(d.enteDevedor);
      if (d.natureza === "alimentar" || d.natureza === "comum") setNatureza(d.natureza);
      if (d.valorFace != null) setValorFace(String(d.valorFace));
      if (d.valorProposta != null) setValorProposta(String(d.valorProposta));
      setOk(`Deal #${d.dealId} importado.`);
    } catch (e: any) {
      setBitrixErr(e.message);
    } finally {
      setBitrixLoading(false);
    }
  }

  useEffect(() => {
    const d = new Date();
    const pad = (n: number) => String(n).padStart(2, "0");
    setProposalDate(d.toLocaleDateString("pt-BR"));
    setProposalNumber(`PROP-${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}`);
    loadHistory();
  }, []);

  function payload(): ProposalInput {
    return {
      proposal_number: proposalNumber || null,
      proposal_date: proposalDate || null,
      client_name: clientName.trim(),
      client_doc: clientDoc || null,
      client_contact: clientContact || null,
      precatorio_number: precatorioNumber || null,
      tribunal: tribunal || null,
      ente_devedor: enteDevedor || null,
      natureza: natureza || null,
      valor_face: faceNum,
      valor_proposta: propostaNum,
      desagio: Number(desagio.toFixed(2)),
      forma_pagamento: formaPagamento || null,
      validade: validade || null,
      observacoes: observacoes || null,
      responsavel: responsavel || null,
    };
  }

  async function save(): Promise<boolean> {
    setError(null);
    setOk(null);
    if (!clientName.trim()) {
      setError("Informe o nome do cliente.");
      return false;
    }
    setSaving(true);
    try {
      const created = await api.proposals.create(payload());
      setOk(`Proposta salva (#${created.id}).`);
      loadHistory();
      return true;
    } catch (e: any) {
      setError(e.message);
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function saveAndPrint() {
    const done = await save();
    if (done) setTimeout(() => window.print(), 150);
  }

  function reprint(p: Proposal) {
    setProposalNumber(p.proposal_number ?? "");
    setProposalDate(p.proposal_date ?? "");
    setClientName(p.client_name);
    setClientDoc(p.client_doc ?? "");
    setClientContact(p.client_contact ?? "");
    setPrecatorioNumber(p.precatorio_number ?? "");
    setTribunal(p.tribunal ?? "");
    setEnteDevedor(p.ente_devedor ?? "");
    setNatureza(p.natureza ?? "alimentar");
    setValorFace(String(p.valor_face ?? ""));
    setValorProposta(String(p.valor_proposta ?? ""));
    setFormaPagamento(p.forma_pagamento ?? "");
    setValidade(p.validade ?? "");
    setObservacoes(p.observacoes ?? "");
    setResponsavel(p.responsavel ?? "");
    setOk(null);
    setError(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function remove(p: Proposal) {
    if (!confirm(`Excluir a proposta de ${p.client_name}?`)) return;
    try {
      await api.proposals.remove(p.id);
      loadHistory();
    } catch (e: any) {
      setError(e.message);
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6 md:p-8">
      <header className="no-print flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <FileText className="h-6 w-6" />
            Gerar Proposta
          </h1>
          <p className="text-sm text-muted-foreground">
            Monte uma proposta de aquisição de precatório e gere o PDF.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => window.print()} className="gap-2">
            <Printer className="h-4 w-4" />
            Gerar PDF
          </Button>
          <Button onClick={saveAndPrint} disabled={saving} className="gap-2">
            <Save className="h-4 w-4" />
            {saving ? "Salvando…" : "Salvar e gerar PDF"}
          </Button>
        </div>
      </header>

      {error ? <p className="no-print rounded-md bg-secondary px-3 py-2 text-sm">{error}</p> : null}
      {ok ? <p className="no-print rounded-md bg-secondary px-3 py-2 text-sm">{ok}</p> : null}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* ---------- Form ---------- */}
        <div className="no-print space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Download className="h-4 w-4" />
                Importar do Bitrix
              </CardTitle>
              <CardDescription>
                Cole o link ou o ID do deal para preencher os campos automaticamente.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex gap-2">
                <input
                  className={inputClass}
                  placeholder="Link do deal ou ID (ex.: 1745)"
                  value={bitrixRef}
                  onChange={(e) => setBitrixRef(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      importBitrix();
                    }
                  }}
                />
                <Button onClick={importBitrix} disabled={bitrixLoading} className="shrink-0">
                  {bitrixLoading ? "Buscando…" : "Buscar"}
                </Button>
              </div>
              {bitrixErr ? (
                <p className="rounded-md bg-secondary px-3 py-2 text-sm text-red-600">{bitrixErr}</p>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Dados da proposta</CardTitle>
              <CardDescription>Número e data que aparecem no cabeçalho.</CardDescription>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-4">
              <Labeled label="Nº da proposta">
                <input className={inputClass} value={proposalNumber} onChange={(e) => setProposalNumber(e.target.value)} />
              </Labeled>
              <Labeled label="Data">
                <input className={inputClass} value={proposalDate} onChange={(e) => setProposalDate(e.target.value)} />
              </Labeled>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Cliente</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <Labeled label="Nome do cliente *">
                <input className={inputClass} value={clientName} onChange={(e) => setClientName(e.target.value)} required />
              </Labeled>
              <div className="grid grid-cols-2 gap-4">
                <Labeled label="CPF / CNPJ">
                  <input className={inputClass} value={clientDoc} onChange={(e) => setClientDoc(e.target.value)} />
                </Labeled>
                <Labeled label="Contato (e-mail / telefone)">
                  <input className={inputClass} value={clientContact} onChange={(e) => setClientContact(e.target.value)} />
                </Labeled>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Precatório</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-4">
              <Labeled label="Nº do precatório">
                <input className={inputClass} value={precatorioNumber} onChange={(e) => setPrecatorioNumber(e.target.value)} />
              </Labeled>
              <Labeled label="Tribunal">
                <input className={inputClass} value={tribunal} onChange={(e) => setTribunal(e.target.value)} />
              </Labeled>
              <Labeled label="Ente devedor">
                <input className={inputClass} value={enteDevedor} onChange={(e) => setEnteDevedor(e.target.value)} />
              </Labeled>
              <Labeled label="Natureza">
                <select className={inputClass} value={natureza} onChange={(e) => setNatureza(e.target.value)}>
                  <option value="alimentar">Alimentar</option>
                  <option value="comum">Comum</option>
                </select>
              </Labeled>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Financeiro</CardTitle>
              <CardDescription>O deságio é calculado a partir dos valores.</CardDescription>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-4">
              <Labeled label="Valor de face (R$)">
                <input type="number" step="0.01" min="0" className={inputClass} value={valorFace} onChange={(e) => setValorFace(e.target.value)} />
              </Labeled>
              <Labeled label="Valor da proposta (R$)">
                <input type="number" step="0.01" min="0" className={inputClass} value={valorProposta} onChange={(e) => setValorProposta(e.target.value)} />
              </Labeled>
              <div className="col-span-2 rounded-md bg-secondary px-3 py-2 text-sm">
                Deságio calculado: <span className="font-semibold">{desagio.toFixed(1)}%</span>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Condições</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <Labeled label="Forma de pagamento">
                <textarea className={textareaClass} rows={2} value={formaPagamento} onChange={(e) => setFormaPagamento(e.target.value)} />
              </Labeled>
              <Labeled label="Validade da proposta">
                <input className={inputClass} value={validade} onChange={(e) => setValidade(e.target.value)} />
              </Labeled>
              <Labeled label="Observações">
                <textarea className={textareaClass} rows={3} value={observacoes} onChange={(e) => setObservacoes(e.target.value)} />
              </Labeled>
              <Labeled label="Responsável">
                <input className={inputClass} value={responsavel} onChange={(e) => setResponsavel(e.target.value)} />
              </Labeled>
            </CardContent>
          </Card>
        </div>

        {/* ---------- Live A4 preview ---------- */}
        <div className="lg:sticky lg:top-20 lg:self-start">
          <div className="proposal-sheet mx-auto w-full max-w-[820px] rounded-lg bg-white shadow-sm ring-1 ring-neutral-200">
            <div className="ps-body">
              {/* Cabeçalho */}
              <header className="ps-header">
                <div className="ps-header-top">
                  <div className="ps-brand">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src="/precatur-logo.png" alt="Precatur" className="ps-logo" />
                  </div>
                  <div className="ps-meta">
                    Nº {proposalNumber || "—"} · {proposalDate || "—"}
                  </div>
                </div>
                <h1 className="ps-title">
                  Proposta de Cessão de Crédito
                  {clientName.trim() ? ` — ${clientName.trim()}` : ""}
                </h1>
                <div className="ps-subtitle">Documento gerado em {proposalDate || "—"}</div>
              </header>

              {/* 1 · Dados do cliente */}
              <section className="ps-section">
                <div className="ps-section-title">1 · Dados do cliente</div>
                <div className="ps-grid">
                  <PsField label="Nome / Razão social" value={clientName} />
                  <PsField label="CPF / CNPJ" value={clientDoc} />
                  <PsField label="Contato" value={clientContact} full />
                </div>
              </section>

              {/* 2 · Precatório */}
              <section className="ps-section">
                <div className="ps-section-title">2 · Precatório</div>
                <div className="ps-grid">
                  <PsField label="Nº do precatório" value={precatorioNumber} />
                  <PsField label="Tribunal" value={tribunal} />
                  <PsField label="Ente devedor" value={enteDevedor} />
                  <div className="ps-field">
                    <div className="ps-field-label">Natureza</div>
                    <div className="ps-field-value">
                      {natureza === "alimentar" || natureza === "comum" ? (
                        <span
                          className={cn(
                            "ps-chip",
                            natureza === "alimentar" ? "ps-chip-alimentar" : "ps-chip-comum"
                          )}
                        >
                          {naturezaLabel(natureza)}
                        </span>
                      ) : (
                        "—"
                      )}
                    </div>
                  </div>
                </div>
              </section>

              {/* 3 · Proposta */}
              <section className="ps-section">
                <div className="ps-section-title">3 · Proposta</div>

                {/* Bloco RESULTADO em destaque */}
                <div className="ps-result">
                  <div className="ps-result-left">
                    <div>
                      <div className="ps-result-item-label">Valor de face</div>
                      <div className="ps-result-item-value">{formatMoney(faceNum)}</div>
                    </div>
                    <div>
                      <div className="ps-result-item-label">Deságio</div>
                      <div className="ps-result-item-value">{desagioDisplay}</div>
                    </div>
                  </div>
                  <div className="ps-result-main">
                    <div className="ps-result-main-label">Valor da proposta</div>
                    <div className="ps-result-main-value">{formatMoney(propostaNum)}</div>
                  </div>
                </div>

                {/* Condições */}
                <div className="ps-grid">
                  <PsField label="Forma de pagamento" value={formaPagamento} full />
                  <PsField label="Validade" value={validade} />
                  <PsField label="Responsável" value={responsavel} />
                </div>

                {/* Observações (caixa creme, só se preenchida) */}
                {observacoes.trim() ? (
                  <div className="ps-note">
                    <span className="ps-note-label">Observações: </span>
                    {observacoes}
                  </div>
                ) : null}
              </section>
            </div>

            {/* Rodapé */}
            <footer className="ps-footer">
              <div className="ps-footer-line">
                CNPJ 57.866.623/0001-69 · (27) 99613-8930 · www.precatur.com.br
              </div>
              <div className="ps-footer-line">
                R. Prof. Almeida Cousin, 125, loja 09/10 — Ed. Enseada Trade Center, Enseada do Suá,
                Vitória/ES
              </div>
            </footer>
          </div>
        </div>
      </div>

      {/* ---------- Histórico ---------- */}
      <Card className="no-print">
        <CardHeader>
          <CardTitle>Propostas recentes</CardTitle>
          <CardDescription>{history.length} proposta(s) salva(s)</CardDescription>
        </CardHeader>
        <CardContent className="px-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Cliente</TableHead>
                <TableHead className="hidden sm:table-cell">Precatório</TableHead>
                <TableHead className="text-right">Valor da proposta</TableHead>
                <TableHead className="hidden text-right sm:table-cell">Deságio</TableHead>
                <TableHead className="hidden md:table-cell">Criada em</TableHead>
                <TableHead className="text-right">Ações</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {history.map((p) => (
                <TableRow key={p.id}>
                  <TableCell className="font-medium">{p.client_name}</TableCell>
                  <TableCell className="hidden text-muted-foreground sm:table-cell">
                    {p.precatorio_number ?? "—"}
                  </TableCell>
                  <TableCell className="text-right">{formatMoney(p.valor_proposta)}</TableCell>
                  <TableCell className="hidden text-right text-muted-foreground sm:table-cell">
                    {p.desagio.toFixed(1)}%
                  </TableCell>
                  <TableCell className="hidden text-muted-foreground md:table-cell">
                    {fmtDate(p.created_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button variant="ghost" size="icon" onClick={() => reprint(p)} aria-label="Carregar no formulário">
                      <RotateCcw className="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="icon" onClick={() => remove(p)} aria-label="Excluir proposta">
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {!history.length ? (
                <TableRow>
                  <TableCell colSpan={6} className="py-10 text-center text-muted-foreground">
                    Nenhuma proposta salva ainda.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function Labeled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm font-medium">{label}</label>
      {children}
    </div>
  );
}

function PsField({ label, value, full }: { label: string; value: string; full?: boolean }) {
  return (
    <div className={cn("ps-field", full && "ps-field-full")}>
      <div className="ps-field-label">{label}</div>
      <div className="ps-field-value">{value.trim() || "—"}</div>
    </div>
  );
}
