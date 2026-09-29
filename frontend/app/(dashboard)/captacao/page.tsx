"use client";

import { useEffect, useMemo, useState } from "react";
import { Inbox, Search, Paperclip, Download, X, Link2, Check } from "lucide-react";
import { api, type Submission, type SubmissionStatus } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const inputClass =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring";

const SITUACOES: { valor: SubmissionStatus; label: string; classe: string }[] = [
  { valor: "novo", label: "Novo", classe: "bg-blue-50 text-blue-700 border-blue-200" },
  { valor: "em_analise", label: "Em análise", classe: "bg-amber-50 text-amber-800 border-amber-200" },
  { valor: "aprovado", label: "Aprovado", classe: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  { valor: "recusado", label: "Recusado", classe: "bg-red-50 text-red-700 border-red-200" },
];
const rotulo = (s: SubmissionStatus) => SITUACOES.find((x) => x.valor === s) ?? SITUACOES[0];

function fmtData(iso: string): string {
  const d = new Date(iso);
  return `${d.toLocaleDateString("pt-BR")} ${d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
}
const mb = (b: number) => (b >= 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);

export default function CaptacaoPage() {
  const [itens, setItens] = useState<Submission[]>([]);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [busca, setBusca] = useState("");
  const [filtro, setFiltro] = useState<SubmissionStatus | "todos">("todos");
  const [aberto, setAberto] = useState<Submission | null>(null);
  const [linkCopiado, setLinkCopiado] = useState(false);

  useEffect(() => {
    api.captacao
      .list()
      .then(setItens)
      .catch((e) => setErro(e.message))
      .finally(() => setLoading(false));
  }, []);

  const filtrados = useMemo(() => {
    const q = busca.trim().toLowerCase();
    return itens.filter((s) => {
      if (filtro !== "todos" && s.status !== filtro) return false;
      if (!q) return true;
      return [s.nome, s.email, s.telefone, s.processo, s.referente_a, s.credor_advogado]
        .some((v) => (v ?? "").toLowerCase().includes(q));
    });
  }, [itens, busca, filtro]);

  const contagem = useMemo(() => {
    const c: Record<string, number> = { todos: itens.length };
    for (const s of SITUACOES) c[s.valor] = itens.filter((i) => i.status === s.valor).length;
    return c;
  }, [itens]);

  async function mudarSituacao(s: Submission, status: SubmissionStatus) {
    setErro(null);
    try {
      const atualizado = await api.captacao.updateStatus(s.id, status);
      setItens((cur) => cur.map((i) => (i.id === atualizado.id ? atualizado : i)));
      setAberto((cur) => (cur && cur.id === atualizado.id ? atualizado : cur));
    } catch (e: any) {
      setErro(e.message);
    }
  }

  async function baixar(s: Submission, fileId: number, filename: string) {
    setErro(null);
    try {
      await api.captacao.baixarArquivo(s.id, fileId, filename);
    } catch (e: any) {
      setErro(e.message);
    }
  }

  function copiarLink() {
    const url = `${window.location.origin}/enviar`;
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
            <Inbox className="h-6 w-6" />
            Envios de cedentes
          </h1>
          <p className="text-sm text-muted-foreground">
            Precatórios enviados pelo formulário público, com documentos anexados.
          </p>
        </div>
        <Button variant="outline" className="gap-2" onClick={copiarLink}>
          {linkCopiado ? <Check className="h-4 w-4" /> : <Link2 className="h-4 w-4" />}
          {linkCopiado ? "Link copiado" : "Copiar link do formulário"}
        </Button>
      </header>

      {erro ? <p className="rounded-md bg-secondary px-3 py-2 text-sm text-red-600">{erro}</p> : null}

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:max-w-xs">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input className={cn(inputClass, "pl-9")} placeholder="Buscar por nome, processo, contato…"
            value={busca} onChange={(e) => setBusca(e.target.value)} />
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Filtro ativo={filtro === "todos"} onClick={() => setFiltro("todos")}>
            Todos ({contagem.todos})
          </Filtro>
          {SITUACOES.map((s) => (
            <Filtro key={s.valor} ativo={filtro === s.valor} onClick={() => setFiltro(s.valor)}>
              {s.label} ({contagem[s.valor] ?? 0})
            </Filtro>
          ))}
        </div>
      </div>

      {loading ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Carregando…</p>
      ) : !filtrados.length ? (
        <Card>
          <CardContent className="py-12 text-center">
            <Inbox className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              {itens.length ? "Nenhum envio para esse filtro." : "Nenhum envio recebido ainda. Compartilhe o link do formulário com os cedentes."}
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {filtrados.map((s) => (
            <Card key={s.id} className="cursor-pointer transition-colors hover:bg-accent/40"
              onClick={() => setAberto(s)}>
              <CardHeader className="flex flex-col gap-2 pb-3 sm:flex-row sm:items-start sm:justify-between sm:space-y-0">
                <div className="min-w-0">
                  <CardTitle className="text-base">
                    #{s.id} · {s.nome}
                  </CardTitle>
                  <CardDescription className="truncate">
                    {s.email} · {s.telefone}
                    {s.processo ? ` · processo ${s.processo}` : ""}
                  </CardDescription>
                </div>
                <span className={cn("shrink-0 rounded-full border px-2.5 py-0.5 text-xs font-medium", rotulo(s.status).classe)}>
                  {rotulo(s.status).label}
                </span>
              </CardHeader>
              <CardContent className="flex flex-wrap items-center gap-x-4 gap-y-1 pt-0 text-xs text-muted-foreground">
                <span>Recebido em {fmtData(s.created_at)}</span>
                {s.files.length ? (
                  <span className="inline-flex items-center gap-1">
                    <Paperclip className="h-3.5 w-3.5" />
                    {s.files.length} anexo(s)
                  </span>
                ) : (
                  <span>Sem anexos</span>
                )}
                {s.referente_a ? <span>Crédito de {s.referente_a}</span> : null}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {aberto ? (
        <Detalhe
          envio={aberto}
          onClose={() => setAberto(null)}
          onStatus={(st) => mudarSituacao(aberto, st)}
          onBaixar={(fileId, filename) => baixar(aberto, fileId, filename)}
        />
      ) : null}
    </div>
  );
}

function Filtro({ ativo, onClick, children }: { ativo: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick}
      className={cn("rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors",
        ativo ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent")}>
      {children}
    </button>
  );
}

function Detalhe({ envio, onClose, onStatus, onBaixar }: {
  envio: Submission;
  onClose: () => void;
  onStatus: (s: SubmissionStatus) => void;
  onBaixar: (fileId: number, filename: string) => void;
}) {
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
            <h2 className="text-lg font-semibold">Envio #{envio.id}</h2>
            <p className="text-sm text-muted-foreground">Recebido em {fmtData(envio.created_at)}</p>
          </div>
          <button onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:bg-accent" aria-label="Fechar">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mb-5 space-y-2">
          <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Situação</div>
          <div className="flex flex-wrap gap-1.5">
            {SITUACOES.map((s) => (
              <button key={s.valor} onClick={() => onStatus(s.valor)}
                className={cn("rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
                  envio.status === s.valor ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent")}>
                {s.label}
              </button>
            ))}
          </div>
          {envio.status_by ? (
            <p className="text-xs text-muted-foreground">
              Alterado por {envio.status_by}
              {envio.status_at ? ` em ${fmtData(envio.status_at)}` : ""}.
            </p>
          ) : null}
        </div>

        <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
          <Item rotulo="Nome / escritório" valor={envio.nome} />
          <Item rotulo="E-mail" valor={envio.email} />
          <Item rotulo="Telefone / WhatsApp" valor={envio.telefone} />
          <Item rotulo="Processo de execução" valor={envio.processo} />
          <Item rotulo="A quem se refere o crédito" valor={envio.referente_a} />
          <Item rotulo="Credor / advogado" valor={envio.credor_advogado} />
          <Item rotulo="Honorários" valor={envio.honorarios} />
        </dl>

        {envio.observacoes ? (
          <div className="mt-4">
            <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Observações</div>
            <p className="mt-1 whitespace-pre-wrap rounded-md bg-secondary/60 px-3 py-2 text-sm">{envio.observacoes}</p>
          </div>
        ) : null}

        <div className="mt-5">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Anexos ({envio.files.length})
          </div>
          {envio.files.length ? (
            <ul className="space-y-2">
              {envio.files.map((f) => (
                <li key={f.id} className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm">
                  <Paperclip className="h-4 w-4 flex-shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1 truncate">{f.filename}</span>
                  <span className="flex-shrink-0 text-xs text-muted-foreground">{mb(f.size_bytes)}</span>
                  <Button variant="ghost" size="icon" aria-label={`Baixar ${f.filename}`}
                    onClick={() => onBaixar(f.id, f.filename)}>
                    <Download className="h-4 w-4" />
                  </Button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">Nenhum arquivo enviado.</p>
          )}
        </div>
      </div>
    </div>
  );
}

function Item({ rotulo, valor }: { rotulo: string; valor: string | null }) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{rotulo}</dt>
      <dd className="text-sm">{valor || "—"}</dd>
    </div>
  );
}
