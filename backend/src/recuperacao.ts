import crypto from "crypto";
import { query } from "./db";

export const VALIDADE_MIN = 60;
const MAX_PEDIDOS_HORA = 5;

const hash = (token: string) => crypto.createHash("sha256").update(token).digest("hex");

export class RecuperacaoError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// Token longo e aleatório de verdade: é a única coisa que separa um estranho da
// conta. No banco guardamos só o hash.
export async function criaToken(userId: number, ip: string | null): Promise<string> {
  const recentes = await query<{ count: string }>(
    `SELECT COUNT(*) AS count FROM password_resets
      WHERE user_id = $1 AND created_at > now() - interval '1 hour'`,
    [userId]
  );
  if (Number(recentes[0]?.count ?? 0) >= MAX_PEDIDOS_HORA) {
    throw new RecuperacaoError(429, "Muitos pedidos para esta conta. Tente novamente mais tarde.");
  }

  const token = crypto.randomBytes(32).toString("hex");
  await query(
    `INSERT INTO password_resets (user_id, token_hash, expires_at, ip)
     VALUES ($1, $2, now() + ($3 || ' minutes')::interval, $4)`,
    [userId, hash(token), String(VALIDADE_MIN), ip]
  );
  return token;
}

// Consome o token: confere validade e uso, e devolve o usuário. Marcar como
// usado na mesma consulta evita que dois cliques simultâneos passem os dois.
export async function consomeToken(token: string): Promise<number> {
  const limpo = String(token ?? "").trim();
  if (!/^[a-f0-9]{64}$/.test(limpo)) {
    throw new RecuperacaoError(400, "Link inválido. Peça um novo e-mail de redefinição.");
  }
  const rows = await query<{ user_id: string }>(
    `UPDATE password_resets SET used_at = now()
      WHERE token_hash = $1 AND used_at IS NULL AND expires_at > now()
      RETURNING user_id`,
    [hash(limpo)]
  );
  if (!rows[0]) {
    throw new RecuperacaoError(410, "Este link expirou ou já foi usado. Peça um novo e-mail de redefinição.");
  }
  return Number(rows[0].user_id);
}

// Confere se o link ainda serve, sem gastá-lo — a tela usa isto ao abrir, para
// não mostrar o formulário de senha quando o link já morreu.
export async function tokenValido(token: string): Promise<boolean> {
  const limpo = String(token ?? "").trim();
  if (!/^[a-f0-9]{64}$/.test(limpo)) return false;
  const rows = await query(
    `SELECT 1 FROM password_resets
      WHERE token_hash = $1 AND used_at IS NULL AND expires_at > now()`,
    [hash(limpo)]
  );
  return rows.length > 0;
}
