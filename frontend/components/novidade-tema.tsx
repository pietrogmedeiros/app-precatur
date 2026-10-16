"use client";

import { useEffect, useState } from "react";
import { Moon, X } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Aviso de novidade no menu: conta que o tema escuro existe.
 *
 * O interruptor é um ícone pequeno no alto do menu — sozinho, ninguém acha.
 * Este cartão aparece uma vez por navegador, logo abaixo do botão que explica,
 * e some assim que a pessoa fecha.
 */
const CHAVE = "novidade:tema-escuro";

/**
 * Depois desta data o aviso para de aparecer sozinho. Quem entrar na casa em
 * dezembro não precisa ser apresentado ao que mudou em outubro — sem isso, um
 * aviso de novidade vira parte permanente da interface.
 */
const ATE = Date.parse("2026-12-15T23:59:59-03:00");

export function NovidadeTema() {
  const [mostrar, setMostrar] = useState(false);

  useEffect(() => {
    if (Date.now() > ATE) return;
    try {
      if (localStorage.getItem(CHAVE) === "1") return;
    } catch {
      /* storage bloqueado: aparece nesta aba e não grava nada */
    }
    setMostrar(true);
  }, []);

  function fechar() {
    setMostrar(false);
    try {
      localStorage.setItem(CHAVE, "1");
    } catch {
      /* idem: fechar vale só para esta aba */
    }
  }

  if (!mostrar) return null;

  return (
    <div className="relative mx-3 mt-3 rounded-lg border bg-secondary/60 p-3">
      <button
        onClick={fechar}
        aria-label="Fechar aviso"
        className="absolute right-1.5 top-1.5 rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
      >
        <X className="h-3.5 w-3.5" />
      </button>

      <p className="flex items-center gap-1.5 pr-5 text-xs font-semibold">
        <Moon className="h-3.5 w-3.5 flex-shrink-0" />
        Novidade: tema escuro
      </p>
      <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
        O botão aqui em cima, ao lado do nome do app, alterna entre claro e
        escuro. A escolha fica salva neste navegador — e a proposta em PDF sai
        igual nos dois.
      </p>

      <Button variant="outline" size="sm" className="mt-2.5 w-full" onClick={fechar}>
        Entendi
      </Button>
    </div>
  );
}
