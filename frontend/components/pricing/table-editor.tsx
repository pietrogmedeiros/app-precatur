"use client";

import { useEffect, useState } from "react";
import { Pencil, Plus, Trash2, X } from "lucide-react";
import { api, type PricingEntity } from "@/lib/api";
import { QUARTERS, formatDecimal, parseBRL } from "@/lib/pricing";
import { Button } from "@/components/ui/button";

const cell =
  "h-8 w-full rounded-md border border-input bg-transparent px-2 text-sm shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring";

interface DraftRow {
  year: string;
  values: string[];
  asset: string;
}

// Edição manual de uma tabela de preço (só admin). Serve sobretudo para as
// regras especiais — Bahia, RJ, MG, Paraíba — que não vêm da planilha.
export function TableEditor({
  entity,
  open,
  onClose,
  onSaved,
}: {
  entity: PricingEntity;
  open: boolean;
  onClose: () => void;
  onSaved: (entities: PricingEntity[]) => void;
}) {
  const [rows, setRows] = useState<DraftRow[]>([]);
  const [deduction, setDeduction] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setRows(
      entity.rows.map((r) => ({
        year: r.year,
        values: r.values.map((v) => String(v).replace(".", ",")),
        asset: r.asset,
      }))
    );
    setDeduction(entity.fixed_deduction ? formatDecimal(entity.fixed_deduction) : "");
    setDescription(entity.description);
    setError(null);
  }, [open, entity]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const patch = (i: number, fn: (r: DraftRow) => DraftRow) =>
    setRows((cur) => cur.map((r, idx) => (idx === i ? fn(r) : r)));

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const entities = await api.pricing.update(entity.key, {
        // A API valida faixa (0–100) e formato; vírgula decimal é aceita aqui.
        rows: rows.map((r) => ({
          year: r.year,
          values: r.values.map((v) => Number(v.replace(",", "."))),
          asset: r.asset,
        })),
        fixed_deduction: deduction.trim() ? parseBRL(deduction) : 0,
        description,
      });
      onSaved(entities);
      onClose();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-lg border bg-card p-6 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            <Pencil className="h-5 w-5" />
            Editar tabela · {entity.label}
          </h2>
          <button onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:bg-accent" aria-label="Fechar">
            <X className="h-4 w-4" />
          </button>
        </div>

        <p className="mb-4 rounded-md bg-secondary px-3 py-2 text-sm">
          A alteração vale na hora para todo o time. A versão anterior fica guardada no histórico.
        </p>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground">
                <th className="pb-2 pr-2 font-medium">Safra / regra</th>
                {QUARTERS.map((q) => (
                  <th key={q} className="pb-2 pr-2 font-medium">{q} (%)</th>
                ))}
                <th className="pb-2 pr-2 font-medium">Ativo</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td className="py-1 pr-2">
                    <input className={cell} value={r.year} onChange={(e) => patch(i, (x) => ({ ...x, year: e.target.value }))} />
                  </td>
                  {r.values.map((v, q) => (
                    <td key={q} className="w-20 py-1 pr-2">
                      <input
                        className={cell}
                        inputMode="decimal"
                        value={v}
                        onChange={(e) =>
                          patch(i, (x) => ({ ...x, values: x.values.map((vv, qq) => (qq === q ? e.target.value : vv)) }))
                        }
                      />
                    </td>
                  ))}
                  <td className="py-1 pr-2">
                    <select className={cell} value={r.asset} onChange={(e) => patch(i, (x) => ({ ...x, asset: e.target.value }))}>
                      <option>Precatório</option>
                      <option>Direito Creditório</option>
                    </select>
                  </td>
                  <td className="py-1">
                    <Button variant="ghost" size="icon" aria-label="Remover linha" disabled={rows.length <= 1}
                      onClick={() => setRows((cur) => cur.filter((_, idx) => idx !== i))}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <Button variant="outline" size="sm" className="mt-2 gap-2"
          onClick={() => setRows((cur) => [...cur, { year: "", values: ["0", "0", "0", "0"], asset: "Precatório" }])}>
          <Plus className="h-4 w-4" />
          Adicionar linha
        </Button>

        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <label className="space-y-1.5 text-sm font-medium">
            <span>Abatimento fixo sobre a proposta (R$)</span>
            <input className={cell + " h-9"} inputMode="decimal" value={deduction} placeholder="0,00"
              onChange={(e) => setDeduction(e.target.value)} />
            <span className="block text-xs font-normal text-muted-foreground">
              Descontado do valor calculado (regra do RJ). Deixe vazio para não abater.
            </span>
          </label>
          <label className="space-y-1.5 text-sm font-medium">
            <span>Descrição</span>
            <textarea className={cell + " h-auto py-2"} rows={3} maxLength={300} value={description}
              onChange={(e) => setDescription(e.target.value)} />
          </label>
        </div>

        {error ? <p className="mt-4 rounded-md bg-secondary px-3 py-2 text-sm text-red-600">{error}</p> : null}

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Cancelar</Button>
          <Button onClick={save} disabled={saving}>{saving ? "Salvando…" : "Salvar para o time"}</Button>
        </div>
      </div>
    </div>
  );
}
