"use client";

import { Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";
import { aplicarTema, salvarTema, temaAtual, type Tema } from "@/lib/tema";

/**
 * Interruptor de tema.
 *
 * O ícone NÃO vem de estado React: é o próprio CSS (`dark:`) que mostra o sol
 * ou a lua. Assim ele já nasce certo no primeiro quadro — com estado, o
 * servidor renderizaria sempre a lua e o ícone piscaria depois da hidratação.
 */
export function TemaToggle({
  className,
  rotulo,
}: {
  className?: string;
  /** Mostra o texto ao lado do ícone (menu aberto no celular, por exemplo). */
  rotulo?: boolean;
}) {
  function alternar() {
    const proximo: Tema = temaAtual() === "escuro" ? "claro" : "escuro";
    aplicarTema(proximo);
    salvarTema(proximo);
  }

  return (
    <button
      type="button"
      onClick={alternar}
      aria-label="Alternar entre tema claro e escuro"
      title="Alternar tema claro/escuro"
      className={cn(
        "flex items-center justify-center gap-2 rounded-md text-muted-foreground transition-colors",
        "hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        rotulo ? "px-3 py-2 text-sm font-medium" : "h-8 w-8",
        className
      )}
    >
      <Moon className="h-4 w-4 flex-shrink-0 dark:hidden" />
      <Sun className="hidden h-4 w-4 flex-shrink-0 dark:block" />
      {rotulo ? (
        <>
          <span className="dark:hidden">Tema escuro</span>
          <span className="hidden dark:inline">Tema claro</span>
        </>
      ) : null}
    </button>
  );
}
