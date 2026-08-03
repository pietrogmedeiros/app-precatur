"use client";

import { useEffect, useMemo, useState } from "react";
import {
  MessageSquareText,
  Plus,
  Search,
  Copy,
  Check,
  Pencil,
  Trash2,
  X,
} from "lucide-react";
import { api, type Followup, type FollowupInput } from "@/lib/api";
import { cn } from "@/lib/utils";
import { getUser, type SessionUser } from "@/lib/auth";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const inputClass =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring";
const textareaClass =
  "flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring";

// Acima disso o corpo aparece recortado, com "Ver tudo" para expandir.
const CLAMP_CHARS = 320;

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

// navigator.clipboard só existe em contexto seguro (https/localhost); o fallback
// com textarea + execCommand cobre um acesso por IP/http.
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* cai no fallback abaixo */
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

export default function FollowUpPage() {
  const [items, setItems] = useState<Followup[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [user, setUser] = useState<SessionUser | null>(null);

  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<Followup | null>(null);
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<number[]>([]);

  useEffect(() => {
    setUser(getUser());
    load();
  }, []);

  function load() {
    setLoading(true);
    api.followups
      .list()
      .then(setItems)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }

  // Autor ou admin podem editar/excluir — a API reforça a mesma regra.
  function canManage(f: Followup): boolean {
    if (!user) return false;
    if (user.role === "admin") return true;
    return !!f.created_by && f.created_by === user.email;
  }

  // Busca no título e no conteúdo.
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (f) => f.title.toLowerCase().includes(q) || f.body.toLowerCase().includes(q)
    );
  }, [items, search]);

  async function copy(f: Followup) {
    const done = await copyText(f.body);
    if (done) {
      setCopiedId(f.id);
      setTimeout(() => setCopiedId((cur) => (cur === f.id ? null : cur)), 1800);
    } else {
      setError("Não foi possível copiar. Selecione o texto e copie manualmente.");
    }
  }

  async function remove(f: Followup) {
    if (!confirm(`Excluir o follow-up "${f.title}"?`)) return;
    setError(null);
    try {
      await api.followups.remove(f.id);
      setItems((cur) => cur.filter((i) => i.id !== f.id));
      setOk("Follow-up excluído.");
    } catch (e: any) {
      setError(e.message);
    }
  }

  function openNew() {
    setEditing(null);
    setEditorOpen(true);
  }

  function openEdit(f: Followup) {
    setEditing(f);
    setEditorOpen(true);
  }

  function onSaved(saved: Followup, wasEditing: boolean) {
    setItems((cur) =>
      wasEditing ? cur.map((i) => (i.id === saved.id ? saved : i)) : [saved, ...cur]
    );
    setOk(wasEditing ? "Follow-up atualizado." : "Follow-up criado e compartilhado com o time.");
    setEditorOpen(false);
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6 md:p-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <MessageSquareText className="h-6 w-6" />
            Follow-up
          </h1>
          <p className="text-sm text-muted-foreground">
            Modelos de mensagem prontos para copiar e usar. Todo follow-up criado aqui fica
            disponível para o time inteiro.
          </p>
        </div>
        <Button onClick={openNew} className="gap-2">
          <Plus className="h-4 w-4" />
          Novo follow-up
        </Button>
      </header>

      {error ? <p className="rounded-md bg-secondary px-3 py-2 text-sm">{error}</p> : null}
      {ok ? <p className="rounded-md bg-secondary px-3 py-2 text-sm text-green-700">{ok}</p> : null}

      <div className="relative w-full sm:max-w-sm">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <input
          className={cn(inputClass, "pl-9")}
          placeholder="Buscar por título ou conteúdo…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {loading ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Carregando…</p>
      ) : !filtered.length ? (
        <Card>
          <CardContent className="py-12 text-center">
            <MessageSquareText className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              {items.length
                ? "Nenhum follow-up encontrado para essa busca."
                : "Nenhum follow-up cadastrado ainda. Crie o primeiro e compartilhe com o time."}
            </p>
            {!items.length ? (
              <Button onClick={openNew} className="mt-4 gap-2">
                <Plus className="h-4 w-4" />
                Novo follow-up
              </Button>
            ) : null}
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">
            {search.trim()
              ? `${filtered.length} resultado(s) de ${items.length}`
              : `${items.length} follow-up(s) disponível(is)`}
          </p>

          {filtered.map((f) => {
            const isExpanded = expanded.includes(f.id);
            const isLong = f.body.length > CLAMP_CHARS;
            return (
              <Card key={f.id}>
                <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <CardTitle className="text-base">{f.title}</CardTitle>
                    <CardDescription>
                      {f.created_by_name ?? f.created_by ?? "—"} · {fmtDate(f.created_at)}
                      {f.updated_at !== f.created_at ? ` · editado em ${fmtDate(f.updated_at)}` : ""}
                    </CardDescription>
                  </div>
                  <div className="flex flex-shrink-0 gap-2">
                    <Button
                      variant={copiedId === f.id ? "default" : "outline"}
                      size="sm"
                      className="gap-2"
                      onClick={() => copy(f)}
                    >
                      {copiedId === f.id ? (
                        <>
                          <Check className="h-4 w-4" />
                          Copiado
                        </>
                      ) : (
                        <>
                          <Copy className="h-4 w-4" />
                          Copiar
                        </>
                      )}
                    </Button>
                    {canManage(f) ? (
                      <>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => openEdit(f)}
                          aria-label="Editar follow-up"
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => remove(f)}
                          aria-label="Excluir follow-up"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </>
                    ) : null}
                  </div>
                </CardHeader>
                <CardContent>
                  <p
                    className={cn(
                      "whitespace-pre-wrap rounded-md bg-secondary/60 px-3 py-3 text-sm leading-relaxed",
                      isLong && !isExpanded && "line-clamp-6"
                    )}
                  >
                    {f.body}
                  </p>
                  {isLong ? (
                    <button
                      className="mt-2 text-xs font-medium text-muted-foreground hover:text-foreground"
                      onClick={() =>
                        setExpanded((cur) =>
                          isExpanded ? cur.filter((id) => id !== f.id) : [...cur, f.id]
                        )
                      }
                    >
                      {isExpanded ? "Ver menos" : "Ver tudo"}
                    </button>
                  ) : null}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      <FollowupEditor
        open={editorOpen}
        followup={editing}
        onClose={() => setEditorOpen(false)}
        onSaved={onSaved}
      />
    </div>
  );
}

function FollowupEditor({
  open,
  followup,
  onClose,
  onSaved,
}: {
  open: boolean;
  followup: Followup | null;
  onClose: () => void;
  onSaved: (saved: Followup, wasEditing: boolean) => void;
}) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Recarrega o formulário sempre que abrir (novo = vazio, edição = valores).
  useEffect(() => {
    if (!open) return;
    setTitle(followup?.title ?? "");
    setBody(followup?.body ?? "");
    setError(null);
  }, [open, followup]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!title.trim()) {
      setError("Informe um título.");
      return;
    }
    if (!body.trim()) {
      setError("Escreva o conteúdo do follow-up.");
      return;
    }
    const payload: FollowupInput = { title: title.trim(), body: body.trim() };
    setSaving(true);
    try {
      const saved = followup
        ? await api.followups.update(followup.id, payload)
        : await api.followups.create(payload);
      onSaved(saved, !!followup);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-lg border bg-card p-6 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            <MessageSquareText className="h-5 w-5" />
            {followup ? "Editar follow-up" : "Novo follow-up"}
          </h2>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
            aria-label="Fechar"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Título</label>
            <input
              className={inputClass}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Ex.: Cliente não respondeu após a proposta"
              maxLength={160}
              required
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Conteúdo</label>
            <textarea
              className={textareaClass}
              rows={12}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="Escreva a mensagem como o time deve enviar…"
              maxLength={8000}
              required
            />
            <p className="text-xs text-muted-foreground">
              As quebras de linha são preservadas ao copiar. {body.length}/8000 caracteres.
            </p>
          </div>

          {error ? <p className="rounded-md bg-secondary px-3 py-2 text-sm">{error}</p> : null}

          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancelar
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? "Salvando…" : followup ? "Salvar alterações" : "Criar e compartilhar"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
