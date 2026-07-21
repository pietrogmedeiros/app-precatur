"use client";

import { useEffect, useState } from "react";
import { X, UserRound } from "lucide-react";
import { api } from "@/lib/api";
import { patchSessionUser } from "@/lib/auth";
import { Button } from "@/components/ui/button";

const inputClass =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring";

export function ProfileModal({
  open,
  onClose,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  onSaved?: (phone: string) => void;
}) {
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Carrega dados frescos do usuário ao abrir.
  useEffect(() => {
    if (!open) return;
    setError(null);
    setOk(null);
    setLoading(true);
    api
      .me()
      .then((me) => {
        setEmail(me.email);
        setPhone(me.phone ?? "");
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [open]);

  // Fecha no ESC.
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
    setOk(null);
    if (!phone.trim()) {
      setError("Informe o telefone.");
      return;
    }
    setSaving(true);
    try {
      const me = await api.updateProfile({ phone: phone.trim() });
      patchSessionUser({ phone: me.phone });
      onSaved?.(me.phone ?? "");
      setOk("Telefone atualizado.");
      setTimeout(onClose, 1000);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="w-full max-w-sm rounded-lg border bg-card p-6 shadow-lg" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            <UserRound className="h-5 w-5" />
            Meu perfil
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
            <label className="text-sm font-medium">E-mail</label>
            <input className={inputClass + " opacity-60"} value={email} disabled readOnly />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Telefone</label>
            <input
              className={inputClass}
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="(27) 99999-9999"
              disabled={loading}
              required
            />
            <p className="text-xs text-muted-foreground">
              Usado como contato do responsável no rodapé das propostas.
            </p>
          </div>

          {error ? <p className="rounded-md bg-secondary px-3 py-2 text-sm">{error}</p> : null}
          {ok ? <p className="rounded-md bg-secondary px-3 py-2 text-sm text-green-700">{ok}</p> : null}

          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancelar
            </Button>
            <Button type="submit" disabled={saving || loading}>
              {saving ? "Salvando…" : "Salvar"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
