"use client";

// Peças do formulário da calculadora. São campos de TEXTO de propósito: o valor
// digitado viaja como o advogado escreveu ("1.234,56") e quem o interpreta é o
// motor. Um <input type="number"> aqui trocaria a vírgula pelo ponto conforme a
// região do navegador — e mudaria o número sem avisar ninguém.

import * as React from "react";
import { cn } from "@/lib/utils";

export const inputClass =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50";

export function Secao({
  numero, titulo, children, descricao,
}: {
  numero: number; titulo: string; descricao?: string; children: React.ReactNode;
}) {
  return (
    <section className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold tracking-tight">
          <span className="text-muted-foreground">{numero} ·</span> {titulo}
        </h3>
        {descricao && <p className="mt-1 text-xs text-muted-foreground">{descricao}</p>}
      </div>
      {children}
    </section>
  );
}

export function Campo({
  label, ajuda, children, className,
}: {
  label: string; ajuda?: string; children: React.ReactNode; className?: string;
}) {
  return (
    <label className={cn("block space-y-1.5", className)}>
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
      {ajuda && <span className="block text-[11px] leading-snug text-muted-foreground/80">{ajuda}</span>}
    </label>
  );
}

export function CampoTexto({
  label, valor, onChange, ajuda, placeholder, className, inputMode,
}: {
  label: string; valor: string; onChange: (v: string) => void;
  ajuda?: string; placeholder?: string; className?: string;
  inputMode?: "text" | "decimal" | "numeric";
}) {
  return (
    <Campo label={label} ajuda={ajuda} className={className}>
      <input
        className={inputClass}
        value={valor}
        inputMode={inputMode}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
    </Campo>
  );
}

export function CampoData({
  label, valor, onChange, ajuda, className,
}: {
  label: string; valor: string; onChange: (v: string) => void; ajuda?: string; className?: string;
}) {
  return (
    <Campo label={label} ajuda={ajuda} className={className}>
      <input type="date" className={inputClass} value={valor} onChange={(e) => onChange(e.target.value)} />
    </Campo>
  );
}

export function CampoSelect({
  label, valor, onChange, opcoes, ajuda, className,
}: {
  label: string; valor: string; onChange: (v: string) => void;
  opcoes: { valor: string; rotulo: string }[]; ajuda?: string; className?: string;
}) {
  return (
    <Campo label={label} ajuda={ajuda} className={className}>
      <select className={inputClass} value={valor} onChange={(e) => onChange(e.target.value)}>
        {opcoes.map((o) => (
          <option key={o.valor} value={o.valor}>{o.rotulo}</option>
        ))}
      </select>
    </Campo>
  );
}

/** Rádio em linha — o seletor de modo do PSS e do IR. */
export function Opcoes<T extends string>({
  label, valor, onChange, opcoes, ajuda,
}: {
  label: string; valor: T; onChange: (v: T) => void;
  opcoes: { valor: T; rotulo: string }[]; ajuda?: string;
}) {
  return (
    <div className="space-y-1.5">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <div className="flex flex-wrap gap-1 rounded-md border border-input p-1">
        {opcoes.map((o) => (
          <button
            key={o.valor}
            type="button"
            onClick={() => onChange(o.valor)}
            className={cn(
              "flex-1 whitespace-nowrap rounded px-2.5 py-1.5 text-xs font-medium transition-colors",
              valor === o.valor
                ? "bg-primary text-primary-foreground shadow-sm"
                : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            )}
          >
            {o.rotulo}
          </button>
        ))}
      </div>
      {ajuda && <span className="block text-[11px] leading-snug text-muted-foreground/80">{ajuda}</span>}
    </div>
  );
}

export function Aviso({
  tom = "info", children,
}: {
  tom?: "info" | "atencao" | "erro"; children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded-md border px-3 py-2 text-xs leading-relaxed",
        tom === "erro" && "border-destructive/40 bg-destructive/10 text-destructive",
        tom === "atencao" && "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400",
        tom === "info" && "border-border bg-muted/50 text-muted-foreground"
      )}
    >
      {children}
    </div>
  );
}
