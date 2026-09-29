// Máscaras de digitação. Formatam a partir dos dígitos, então apagar funciona
// naturalmente: o valor é sempre recalculado do zero.

// Telefone brasileiro com DDD: (27) 99999-0000 (celular, 11 dígitos) ou
// (27) 9999-0000 (fixo, 10). Formata enquanto digita.
export function maskTelefone(valor: string): string {
  const d = valor.replace(/\D/g, "").slice(0, 11);
  if (d.length <= 2) return d.length ? `(${d}` : "";
  // Celular sempre começa com 9 depois do DDD; fixo, não. Decidir por aí evita
  // o número se reembaralhar quando o usuário apaga o último dígito.
  const corte = d[2] === "9" ? 7 : 6;
  if (d.length <= corte) return `(${d.slice(0, 2)}) ${d.slice(2)}`;
  return `(${d.slice(0, 2)}) ${d.slice(2, corte)}-${d.slice(corte)}`;
}

// Processo no padrão CNJ: NNNNNNN-DD.AAAA.J.TR.OOOO (20 dígitos).
//
// Processos antigos nem sempre seguem esse padrão. Por isso, se o texto tiver
// qualquer letra, ele é preservado como veio — é melhor aceitar um número fora
// do padrão do que impedir o cedente de informar o que ele tem.
export function maskProcesso(valor: string): string {
  if (/[a-zA-Z]/.test(valor)) return valor.slice(0, 120);
  const d = valor.replace(/\D/g, "").slice(0, 20);
  if (d.length <= 7) return d;
  let out = `${d.slice(0, 7)}-${d.slice(7, 9)}`;
  if (d.length > 9) out += `.${d.slice(9, 13)}`;
  if (d.length > 13) out += `.${d.slice(13, 14)}`;
  if (d.length > 14) out += `.${d.slice(14, 16)}`;
  if (d.length > 16) out += `.${d.slice(16, 20)}`;
  return out;
}
