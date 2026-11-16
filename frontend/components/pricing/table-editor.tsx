"use client";

import { useEffect, useState } from "react";
import { Pencil, Plus, Trash2, X } from "lucide-react";
import { api, type PricingEntity, type PricingPreview, type PricingRow } from "@/lib/api";
import { QUARTERS, formatDecimal, parseBRL } from "@/lib/pricing";
import { Button } from "@/components/ui/button";
import { PreviewDialog } from "@/components/pricing/preview-dialog";

const cell =
  "h-8 w-full rounded-md border border-input bg-transparent px-2 text-sm shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring";

interface DraftRow {
  year: string;
  values: string[];
  asset: string;
  /** "" = a linha vale para as duas naturezas. */
  natureza: "" | "alimentar" | "comum";
  /** Não é editável aqui, mas precisa voltar no save: sem isso a faixa se perde. */
  faixa: PricingRow["faixa"];
}

// Edição manual de uma tabela de preço (só admin). Serve sobretudo para as
// regras especiais — Bahia, RJ, MG, Paraíba — que não vêm da planilha.
const UFS = ["AC","AL","AM","AP","BA","CE","DF","ES","GO","MA","MG","MS","MT","PA","PB","PE","PI","PR","RJ","RN","RO","RR","RS","SC","SE","SP","TO"];

export function TableEditor({
  entity,
  open,
  modo = "editar",
  onClose,
  onSaved,
}: {
  entity: PricingEntity;
  open: boolean;
  /** "criar" acrescenta os campos de identificação da praça nova. */
  modo?: "editar" | "criar";
  onClose: () => void;
  onSaved: (entities: PricingEntity[]) => void;
}) {
  const criando = modo === "criar";
  const [label, setLabel] = useState("");
  const [esfera, setEsfera] = useState("estadual");
  const [uf, setUf] = useState("");
  const [municipio, setMunicipio] = useState("");
  const [rows, setRows] = useState<DraftRow[]>([]);
  const [deduction, setDeduction] = useState("");
  const [description, setDescription] = useState("");
  const [oculta, setOculta] = useState(false);
  const [segueMunicipal, setSegueMunicipal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // Edição passa por uma conferência (antes × depois) antes de gravar.
  const [preview, setPreview] = useState<PricingPreview | null>(null);

  useEffect(() => {
    if (!open) return;
    if (criando) {
      setLabel("");
      setEsfera("estadual");
      setUf("");
      setMunicipio("");
    } else {
      setLabel(entity.label);
    }
    setRows(
      (criando ? [] : entity.rows).map((r) => ({
        year: r.year,
        values: r.values.map((v) => String(v).replace(".", ",")),
        asset: r.asset,
        natureza: r.natureza ?? "",
        faixa: r.faixa ?? null,
      }))
    );
    setDeduction(criando ? "" : entity.fixed_deduction ? formatDecimal(entity.fixed_deduction) : "");
    setDescription(criando ? "" : entity.description);
    setOculta(criando ? false : Boolean(entity.hidden));
    setSegueMunicipal(criando ? false : Boolean(entity.municipal_reference));
    setError(null);
  }, [open, entity, criando]);

  useEffect(() => {
    if (!open) return;
    // Com a conferência aberta, o Esc fecha só ela (o diálogo cuida do próprio).
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !preview && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, preview]);

  if (!open) return null;

  const patch = (i: number, fn: (r: DraftRow) => DraftRow) =>
    setRows((cur) => cur.map((r, idx) => (idx === i ? fn(r) : r)));

  function montaPayload() {
    // A API valida faixa (0–100) e formato; vírgula decimal é aceita aqui.
    const linhas: PricingRow[] = rows.map((r) => ({
      year: r.year,
      values: r.values.map((v) => Number(v.replace(",", "."))),
      asset: r.asset,
      natureza: r.natureza || null,
      faixa: r.faixa ?? null,
    }));
    return {
      label,
      rows: linhas,
      fixed_deduction: deduction.trim() ? parseBRL(deduction) : 0,
      description,
      hidden: oculta,
      municipal_reference: segueMunicipal,
    };
  }

  // Cadastro grava direto; edição pede antes a pré-visualização ao servidor.
  async function save() {
    setError(null);
    setSaving(true);
    try {
      const payload = montaPayload();
      if (criando) {
        const entities = await api.pricing.create({
          label, esfera, uf: uf || null, municipio: municipio || null,
          description, fixed_deduction: payload.fixed_deduction,
          rows: payload.rows,
        });
        onSaved(entities);
        onClose();
        return;
      }
      setPreview(await api.pricing.preview(entity.key, payload));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function confirmar() {
    setError(null);
    setSaving(true);
    try {
      const entities = await api.pricing.update(entity.key, montaPayload());
      setPreview(null);
      onSaved(entities);
      onClose();
    } catch (e: any) {
      setPreview(null);
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  // Mudanças que não mexem em valor (nome, descrição, ocultar) também gravam.
  const mudouOutroCampo =
    !criando &&
    (label !== entity.label ||
      description !== entity.description ||
      oculta !== Boolean(entity.hidden) ||
      segueMunicipal !== Boolean(entity.municipal_reference));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-lg border bg-card p-6 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            <Pencil className="h-5 w-5" />
            {criando ? "Nova praça" : `Editar tabela · ${entity.label}`}
          </h2>
          <button onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:bg-accent" aria-label="Fechar">
            <X className="h-4 w-4" />
          </button>
        </div>

        <p className="mb-4 rounded-md bg-secondary px-3 py-2 text-sm">
          {criando
            ? "A praça passa a valer na hora para todo o time e aparece na barra acima. Onde não houver regra própria, o regime geral da esfera continua valendo."
            : "Ao salvar você vê antes × depois e os avisos de coerência. Só depois de confirmar a alteração vale para todo o time, e a versão anterior fica no histórico."}
        </p>

        {criando ? null : (
          <div className="mb-5 grid gap-4 sm:grid-cols-2">
            <label className="space-y-1.5 text-sm font-medium">
              <span>Nome da praça</span>
              <input className={cell + " h-9"} value={label} maxLength={120} placeholder="Ex.: Alagoas"
                onChange={(e) => setLabel(e.target.value)} />
            </label>
          </div>
        )}

        {criando ? (
          <div className="mb-5 grid gap-4 sm:grid-cols-2">
            <label className="space-y-1.5 text-sm font-medium">
              <span>Nome da praça</span>
              <input className={cell + " h-9"} value={label} maxLength={120} placeholder="Ex.: Alagoas"
                onChange={(e) => setLabel(e.target.value)} />
            </label>
            <label className="space-y-1.5 text-sm font-medium">
              <span>Esfera</span>
              <select className={cell + " h-9"} value={esfera} onChange={(e) => setEsfera(e.target.value)}>
                <option value="estadual">Estadual</option>
                <option value="municipal">Municipal</option>
                <option value="federal">Federal</option>
              </select>
            </label>
            {esfera !== "federal" ? (
              <label className="space-y-1.5 text-sm font-medium">
                <span>UF</span>
                <select className={cell + " h-9"} value={uf} onChange={(e) => setUf(e.target.value)}>
                  <option value="">Selecione…</option>
                  {UFS.map((u) => <option key={u} value={u}>{u}</option>)}
                </select>
              </label>
            ) : null}
            {esfera === "municipal" ? (
              <label className="space-y-1.5 text-sm font-medium">
                <span>Município</span>
                <input className={cell + " h-9"} value={municipio} maxLength={120}
                  onChange={(e) => setMunicipio(e.target.value)} />
              </label>
            ) : null}
          </div>
        ) : null}

        <div className="overflow-x-auto">
          <table className="w-full min-w-[740px] text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground">
                <th className="pb-2 pr-2 font-medium">Safra / regra</th>
                {QUARTERS.map((q) => (
                  <th key={q} className="pb-2 pr-2 font-medium">{q} (%)</th>
                ))}
                <th className="pb-2 pr-2 font-medium">Ativo</th>
                <th className="pb-2 pr-2 font-medium">Natureza</th>
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
                  <td className="py-1 pr-2">
                    {/* Vazio = vale para alimentar e comum, como na maioria das praças.
                        Só desdobramos quando o estado paga preços diferentes (Alagoas). */}
                    <select className={cell} value={r.natureza}
                      onChange={(e) => patch(i, (x) => ({ ...x, natureza: e.target.value as DraftRow["natureza"] }))}>
                      <option value="">Ambas</option>
                      <option value="alimentar">Alimentar</option>
                      <option value="comum">Comum</option>
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
          onClick={() => setRows((cur) => [...cur, { year: "", values: ["0", "0", "0", "0"], asset: "Precatório", natureza: "", faixa: null }])}>
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

        {!criando && entity.municipal_reference ? (
          <label className="mt-4 flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-0.5 h-4 w-4" checked={segueMunicipal}
              onChange={(e) => setSegueMunicipal(e.target.checked)} />
            <span>
              Seguir a curva do Regime Geral Municipal
              <span className="block text-xs font-normal text-muted-foreground">
                Marcada, esta praça não tem tabela própria: mostra a do Municipal e acompanha as
                mudanças dela. Desmarque para dar a ela a tabela acima.
              </span>
            </span>
          </label>
        ) : null}

        {!criando ? (
          <label className="mt-4 flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-0.5 h-4 w-4" checked={oculta}
              onChange={(e) => setOculta(e.target.checked)} />
            <span>
              Ocultar da barra de praças
              <span className="block text-xs font-normal text-muted-foreground">
                O time deixa de ver esta tabela na Precificação. Ela continua no sistema e segue
                valendo na calculadora pública para quem não tem tabela própria.
              </span>
            </span>
          </label>
        ) : null}

        {error ? <p className="mt-4 rounded-md bg-secondary px-3 py-2 text-sm text-red-600 dark:text-red-400">{error}</p> : null}

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Cancelar</Button>
          <Button onClick={save} disabled={saving || (criando && (!label.trim() || (esfera !== "federal" && !uf) || !rows.length))}>
            {saving ? (criando ? "Salvando…" : "Conferindo…") : criando ? "Cadastrar praça" : "Conferir alteração"}
          </Button>
        </div>
      </div>

      <PreviewDialog
        previews={preview ? [preview] : null}
        titulo={`Conferir alteração · ${entity.label}`}
        confirmarTexto="Salvar para o time"
        busy={saving}
        confirmarSempre={mudouOutroCampo}
        onConfirm={confirmar}
        onCancel={() => setPreview(null)}
      />
    </div>
  );
}
