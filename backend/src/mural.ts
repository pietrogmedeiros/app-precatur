import { query } from "./db";

// Diretrizes de compra do Mural: o texto que o comercial lê antes de olhar até
// que safra pagamos em cada região.
//
// Guardadas uma linha por versão (ver a migration 017): a vigente é a mais
// recente. Nada aqui faz UPDATE — trocar o texto é escrever um novo, e o
// anterior continua lá para dizer o que valia na semana passada.

export interface Diretrizes {
  texto: string;
  autor: string | null;
  /** null quando ninguém escreveu ainda — a tela mostra o estado vazio. */
  atualizado_em: string | null;
}

export interface VersaoDiretrizes extends Diretrizes {
  id: number;
}

/** Teto generoso: são diretrizes, não um manual. Evita que um colar acidental
 *  (um PDF inteiro, por exemplo) vire a tela de todo mundo. */
export const MAX_CARACTERES = 8000;

export class MuralError extends Error {
  constructor(message: string, readonly status = 400) {
    super(message);
  }
}

export async function lerDiretrizes(): Promise<Diretrizes> {
  const [linha] = await query<any>(
    `SELECT texto, autor, criado_em FROM mural_diretrizes ORDER BY id DESC LIMIT 1`
  );
  if (!linha) return { texto: "", autor: null, atualizado_em: null };
  return { texto: linha.texto, autor: linha.autor, atualizado_em: linha.criado_em };
}

export async function salvarDiretrizes(texto: string, autor: string | null): Promise<Diretrizes> {
  const limpo = String(texto ?? "").replace(/\r\n/g, "\n").trim();
  if (limpo.length > MAX_CARACTERES) {
    throw new MuralError(`O texto passa de ${MAX_CARACTERES} caracteres.`);
  }
  // Texto idêntico ao vigente não vira versão nova: salvar sem mudar nada
  // encheria o histórico de ruído e mentiria sobre quando a regra mudou.
  const atual = await lerDiretrizes();
  if (atual.texto === limpo) return atual;

  const [linha] = await query<any>(
    `INSERT INTO mural_diretrizes (texto, autor) VALUES ($1, $2)
     RETURNING texto, autor, criado_em`,
    [limpo, autor]
  );
  return { texto: linha.texto, autor: linha.autor, atualizado_em: linha.criado_em };
}

export async function historicoDiretrizes(limite = 20): Promise<VersaoDiretrizes[]> {
  const linhas = await query<any>(
    `SELECT id, texto, autor, criado_em FROM mural_diretrizes
      ORDER BY id DESC LIMIT $1`,
    [Math.max(1, Math.min(limite, 100))]
  );
  return linhas.map((l) => ({
    id: Number(l.id), texto: l.texto, autor: l.autor, atualizado_em: l.criado_em,
  }));
}
