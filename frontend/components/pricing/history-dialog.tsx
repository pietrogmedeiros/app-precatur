"use client";

import { useEffect, useState } from "react";
import { History, X } from "lucide-react";
import { api, type PricingEntity, type PricingHistoryEntry, type PricingPreview } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { PreviewDialog } from "@/components/pricing/preview-dialog";

const ORIGEM: Record<PricingHistoryEntry["source"], string> = {
  import: "importação da planilha",
  edit: "edição na tela",
  restore: "restauração",
};

function quando(iso: string): string {
  const d = new Date(iso);
  return `${d.toLocaleDateString("pt-BR")} às ${d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
}

// Versões anteriores de uma praça. Cada linha é a tabela COMO ESTAVA antes de ser
// substituída; restaurar mostra primeiro o antes × depois e guarda a versão atual
// no histórico, então dá para desfazer a própria restauração.
export function HistoryDialog({
  entity,
  open,
  onClose,
  onRestored,
}: {
  entity: PricingEntity;
  open: boolean;
  onClose: () => void;
  onRestored: (entities: PricingEntity[], versao: PricingHistoryEntry) => void;
}) {
  const [versoes, setVersoes] = useState<PricingHistoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [alvo, setAlvo] = useState<PricingHistoryEntry | null>(null);
  const [preview, setPreview] = useState<PricingPreview | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setVersoes(null);
    setError(null);
    setPreview(null);
    api.pricing.history(entity.key).then(setVersoes).catch((e) => setError(e.message));
  }, [open, entity.key]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !preview && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, preview]);

  if (!open) return null;

  async function comparar(v: PricingHistoryEntry) {
    setError(null);
    setBusy(true);
    try {
      setAlvo(v);
      setPreview(
        await api.pricing.preview(entity.key, {
          rows: v.rows,
          fixed_deduction: v.fixed_deduction,
          description: v.description,
        })
      );
    } catch (e: any) {
      setAlvo(null);
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function restaurar() {
    if (!alvo) return;
    setError(null);
    setBusy(true);
    try {
      const entities = await api.pricing.restore(entity.key, alvo.id);
      const v = alvo;
      setPreview(null);
      setAlvo(null);
      onRestored(entities, v);
      onClose();
    } catch (e: any) {
      setPreview(null);
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-lg border bg-card p-6 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            <History className="h-5 w-5" />
            Histórico · {entity.label}
          </h2>
          <button onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:bg-accent" aria-label="Fechar">
            <X className="h-4 w-4" />
          </button>
        </div>

        <p className="mb-4 rounded-md bg-secondary px-3 py-2 text-sm">
          Cada item é a tabela como ela estava antes de ser substituída. Ao restaurar, você vê o antes × depois
          e a versão que está valendo agora também vai para o histórico.
        </p>

        {error ? <p className="mb-3 rounded-md bg-secondary px-3 py-2 text-sm text-red-600 dark:text-red-400">{error}</p> : null}
        {!versoes && !error ? <p className="text-sm text-muted-foreground">Carregando…</p> : null}
        {versoes && !versoes.length ? (
          <p className="text-sm text-muted-foreground">Esta praça ainda não foi alterada desde que o histórico existe.</p>
        ) : null}

        <ul className="space-y-2">
          {(versoes ?? []).map((v) => (
            <li key={v.id} className="flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm">
              <div>
                <div className="font-medium">Substituída em {quando(v.changed_at)}</div>
                <div className="text-xs text-muted-foreground">
                  {ORIGEM[v.source] ?? v.source}
                  {v.changed_by ? ` · por ${v.changed_by}` : ""} · {v.rows.length} {v.rows.length === 1 ? "linha" : "linhas"}
                </div>
              </div>
              <Button variant="outline" size="sm" disabled={busy} onClick={() => comparar(v)}>
                Ver e restaurar
              </Button>
            </li>
          ))}
        </ul>
      </div>

      <PreviewDialog
        previews={preview ? [preview] : null}
        titulo={alvo ? `Restaurar a versão de ${quando(alvo.changed_at)}` : "Restaurar versão"}
        confirmarTexto="Restaurar para o time"
        busy={busy}
        onConfirm={restaurar}
        onCancel={() => { setPreview(null); setAlvo(null); }}
      />
    </div>
  );
}
