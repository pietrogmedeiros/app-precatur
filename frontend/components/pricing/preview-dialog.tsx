"use client";

import { useEffect } from "react";
import { AlertTriangle, X } from "lucide-react";
import type { PricingPreview } from "@/lib/api";
import { QUARTERS, formatBRL } from "@/lib/pricing";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const pp = (n: number) => `${n > 0 ? "+" : ""}${n.toLocaleString("pt-BR", { maximumFractionDigits: 2 })} p.p.`;

// Antes × depois de uma mudança de preço, com os avisos de coerência. Nada é
// gravado até o admin confirmar aqui: é a última checagem antes de o valor
// passar a valer para o time e para a calculadora pública.
export function PreviewDialog({
  previews,
  titulo,
  confirmarTexto,
  busy,
  confirmarSempre,
  onConfirm,
  onCancel,
}: {
  previews: PricingPreview[] | null;
  titulo: string;
  confirmarTexto: string;
  busy?: boolean;
  /** Permite confirmar mesmo sem mudança de valor (ex.: só renomear ou ocultar a praça). */
  confirmarSempre?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  useEffect(() => {
    if (!previews) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !busy && onCancel();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [previews, busy, onCancel]);

  if (!previews) return null;

  const mudou = previews.some((p) => p.mudou);
  const totalAvisos = previews.reduce((n, p) => n + p.avisos.length, 0);

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4" onClick={(e) => { e.stopPropagation(); if (!busy) onCancel(); }}>
      <div
        className="max-h-[90vh] w-full max-w-4xl overflow-y-auto rounded-lg border bg-card p-6 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{titulo}</h2>
          <button onClick={onCancel} disabled={busy} className="rounded-md p-1 text-muted-foreground hover:bg-accent" aria-label="Fechar">
            <X className="h-4 w-4" />
          </button>
        </div>

        {!mudou ? (
          <p className="rounded-md bg-secondary px-3 py-2 text-sm">
            Nenhum valor muda com esta alteração.
          </p>
        ) : (
          <p className="mb-4 text-sm text-muted-foreground">
            Confira o que muda antes de salvar. Os valores em reais usam um crédito líquido de{" "}
            {formatBRL(previews[0].liquido_referencia, 0)} no trimestre vigente ({QUARTERS[previews[0].trimestre]}).
          </p>
        )}

        {previews.map((p) => {
          const alteradas = p.linhas.filter(
            (l) => !l.antes || !l.depois || l.delta.some((x) => x !== 0)
          );
          const iguais = p.linhas.length - alteradas.length;
          return (
            <section key={p.key} className="mb-5">
              <h3 className="mb-2 text-sm font-semibold">{p.label}</h3>

              {p.abatimento.antes !== p.abatimento.depois ? (
                <p className="mb-2 text-sm">
                  Abatimento fixo: {formatBRL(p.abatimento.antes)} → <strong>{formatBRL(p.abatimento.depois)}</strong>
                </p>
              ) : null}

              {alteradas.length ? (
                <div className="overflow-x-auto rounded-md border">
                  <table className="w-full min-w-[680px] text-sm">
                    <thead className="bg-secondary text-left text-xs text-muted-foreground">
                      <tr>
                        <th className="px-3 py-2 font-medium">Safra / regra</th>
                        {QUARTERS.map((q) => <th key={q} className="px-3 py-2 text-right font-medium">{q}</th>)}
                        <th className="px-3 py-2 text-right font-medium">Proposta ({QUARTERS[p.trimestre]})</th>
                      </tr>
                    </thead>
                    <tbody>
                      {alteradas.map((l) => (
                        <tr key={l.rotulo} className="border-t align-top">
                          <td className="px-3 py-2">
                            {l.rotulo}
                            {!l.antes ? <span className="ml-1.5 text-xs text-emerald-700 dark:text-emerald-300">nova</span> : null}
                            {!l.depois ? <span className="ml-1.5 text-xs text-red-600 dark:text-red-400">removida</span> : null}
                          </td>
                          {[0, 1, 2, 3].map((q) => {
                            const a = l.antes?.[q];
                            const d = l.depois?.[q];
                            const delta = l.delta[q];
                            const mudouCelula = delta !== 0;
                            return (
                              <td key={q} className={cn("px-3 py-2 text-right tabular-nums", !mudouCelula && "text-muted-foreground")}>
                                {mudouCelula ? (
                                  <>
                                    <div>
                                      {a != null ? `${a}%` : "—"} → <strong>{d != null ? `${d}%` : "—"}</strong>
                                    </div>
                                    {delta != null ? (
                                      <div className={cn("text-xs", delta > 0 ? "text-emerald-700 dark:text-emerald-300" : "text-red-600 dark:text-red-400")}>
                                        {pp(delta)}
                                      </div>
                                    ) : null}
                                  </>
                                ) : (
                                  `${d}%`
                                )}
                              </td>
                            );
                          })}
                          <td className="px-3 py-2 text-right tabular-nums">
                            <div>
                              {l.proposta_antes != null ? formatBRL(l.proposta_antes, 0) : "—"} →{" "}
                              <strong>{l.proposta_depois != null ? formatBRL(l.proposta_depois, 0) : "—"}</strong>
                            </div>
                            {l.proposta_antes != null && l.proposta_depois != null && l.proposta_antes !== l.proposta_depois ? (
                              <div className="text-xs text-muted-foreground">
                                {l.proposta_depois - l.proposta_antes > 0 ? "+" : ""}
                                {formatBRL(l.proposta_depois - l.proposta_antes, 0)}
                              </div>
                            ) : null}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
              {iguais ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  {iguais} {iguais === 1 ? "linha sem alteração" : "linhas sem alteração"}.
                </p>
              ) : null}

              {p.avisos.length ? (
                <ul className="mt-3 space-y-1 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
                  {p.avisos.map((a, i) => (
                    <li key={i} className="flex gap-2">
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                      <span>{a}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </section>
          );
        })}

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="outline" onClick={onCancel} disabled={busy}>Voltar</Button>
          <Button onClick={onConfirm} disabled={busy || !(mudou || confirmarSempre)}>
            {busy ? "Salvando…" : totalAvisos ? `${confirmarTexto} mesmo assim` : confirmarTexto}
          </Button>
        </div>
      </div>
    </div>
  );
}
