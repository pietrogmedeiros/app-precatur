/**
 * Tema claro/escuro.
 *
 * A troca é só uma classe `dark` no <html> — a paleta inteira já vive em
 * variáveis CSS (globals.css) e o Tailwind está em `darkMode: ["class"]`.
 *
 * A preferência mora no localStorage. Quem nunca escolheu herda o sistema
 * operacional; a partir do primeiro clique, manda a escolha.
 */
export type Tema = "claro" | "escuro";

export const CHAVE_TEMA = "tema";

export function aplicarTema(tema: Tema): void {
  const raiz = document.documentElement;
  raiz.classList.toggle("dark", tema === "escuro");
  // Faz o navegador pintar barras de rolagem, campos nativos e o fundo do
  // próprio canvas no tom certo — sem isto o scroll continua branco no escuro.
  raiz.style.colorScheme = tema === "escuro" ? "dark" : "light";
}

export function temaAtual(): Tema {
  return document.documentElement.classList.contains("dark") ? "escuro" : "claro";
}

export function salvarTema(tema: Tema): void {
  try {
    localStorage.setItem(CHAVE_TEMA, tema);
  } catch {
    /* navegação anônima com storage bloqueado: vale só para esta aba */
  }
}

/**
 * Roda ANTES da primeira pintura (primeiro filho do <body> no layout raiz).
 * Sem isto a página nasce clara e pisca para o escuro a cada navegação.
 *
 * Também devolve a página ao claro na hora de imprimir: papel não tem tema, e
 * a proposta sai do mesmo jeito tendo sido montada em qualquer um dos dois.
 */
export const SCRIPT_TEMA = `(function(){var r=document.documentElement;function p(e){r.classList.toggle("dark",e);r.style.colorScheme=e?"dark":"light"}try{var s=localStorage.getItem("${CHAVE_TEMA}");p(s?s==="escuro":window.matchMedia("(prefers-color-scheme: dark)").matches)}catch(_){}var v=false;addEventListener("beforeprint",function(){v=r.classList.contains("dark");if(v)p(false)});addEventListener("afterprint",function(){if(v)p(true)})})();`;
