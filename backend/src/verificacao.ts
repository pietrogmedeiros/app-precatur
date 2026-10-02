import crypto from "crypto";
import { query } from "./db";

const VALIDADE_MIN = 10;
const MAX_TENTATIVAS = 5;
const INTERVALO_REENVIO_S = 60;
const MAX_CODIGOS_POR_TELEFONE_HORA = 5;

const hash = (codigo: string) => crypto.createHash("sha256").update(codigo).digest("hex");

// 6 dígitos sorteados de forma criptográfica — nada de Math.random para algo que
// protege o acesso ao valor.
function sorteiaCodigo(): string {
  return String(crypto.randomInt(0, 1_000_000)).padStart(6, "0");
}

export class VerificacaoError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function criaVerificacao(
  simulationId: number,
  telefone: string,
  ip: string | null
): Promise<{ codigo: string; expira_em: string }> {
  const recentes = await query<{ count: string }>(
    `SELECT COUNT(*) AS count FROM phone_verifications
      WHERE telefone = $1 AND created_at > now() - interval '1 hour'`,
    [telefone]
  );
  if (Number(recentes[0]?.count ?? 0) >= MAX_CODIGOS_POR_TELEFONE_HORA) {
    throw new VerificacaoError(429, "Muitos códigos pedidos para esse número. Tente mais tarde.");
  }

  const codigo = sorteiaCodigo();
  const rows = await query<{ expira_em: string }>(
    `INSERT INTO phone_verifications (simulation_id, telefone, codigo_hash, expira_em, ip)
     VALUES ($1, $2, $3, now() + ($4 || ' minutes')::interval, $5)
     RETURNING expira_em`,
    [simulationId, telefone, hash(codigo), String(VALIDADE_MIN), ip]
  );
  return { codigo, expira_em: rows[0].expira_em };
}

export async function podeReenviar(simulationId: number): Promise<boolean> {
  const rows = await query<{ segundos: string }>(
    `SELECT EXTRACT(EPOCH FROM (now() - enviado_em)) AS segundos
       FROM phone_verifications
      WHERE simulation_id = $1
      ORDER BY created_at DESC LIMIT 1`,
    [simulationId]
  );
  if (!rows[0]) return true;
  return Number(rows[0].segundos) >= INTERVALO_REENVIO_S;
}

// Confere o código mais recente da simulação. Conta tentativa a cada erro e
// queima a verificação ao estourar o limite — quem errar 5 vezes precisa pedir
// um código novo.
export async function verificaCodigo(simulationId: number, codigo: string): Promise<void> {
  const rows = await query<any>(
    `SELECT id, codigo_hash, tentativas, expira_em < now() AS expirado, verificado_em
       FROM phone_verifications
      WHERE simulation_id = $1
      ORDER BY created_at DESC LIMIT 1`,
    [simulationId]
  );
  const v = rows[0];
  if (!v) throw new VerificacaoError(404, "Não há código pendente para esta simulação.");
  if (v.verificado_em) return; // já verificado: deixa passar
  if (v.expirado) throw new VerificacaoError(410, "O código expirou. Peça um novo.");
  if (Number(v.tentativas) >= MAX_TENTATIVAS) {
    throw new VerificacaoError(429, "Muitas tentativas erradas. Peça um código novo.");
  }

  if (v.codigo_hash !== hash(String(codigo ?? "").trim())) {
    await query(`UPDATE phone_verifications SET tentativas = tentativas + 1 WHERE id = $1`, [v.id]);
    const restantes = MAX_TENTATIVAS - (Number(v.tentativas) + 1);
    throw new VerificacaoError(
      400,
      restantes > 0 ? `Código incorreto. Você ainda tem ${restantes} tentativa(s).` : "Código incorreto. Peça um código novo."
    );
  }

  await query(`UPDATE phone_verifications SET verificado_em = now() WHERE id = $1`, [v.id]);
  // Telefone confirmado: a simulação vira lead verificado.
  await query(
    `UPDATE simulations SET verificado_em = now(), contato_em = COALESCE(contato_em, now())
      WHERE id = $1`,
    [simulationId]
  );
}

// Esconde o miolo do número na tela: (27) 9****-**66
export function mascaraTelefone(telefone: string): string {
  const d = String(telefone ?? "").replace(/\D/g, "");
  if (d.length < 6) return "seu WhatsApp";
  return `(${d.slice(0, 2)}) ${d.slice(2, 3)}${"*".repeat(Math.max(0, d.length - 6))}${d.slice(-2)}`;
}
