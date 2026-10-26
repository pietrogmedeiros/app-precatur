import jwt from "jsonwebtoken";
import type { Request, Response, NextFunction } from "express";
import { findByEmail, hashPassword, usuarioAtivo, type Role, type User } from "./users";

const JWT_SECRET = process.env.JWT_SECRET ?? "dev-secret-change-me";
const TOKEN_TTL = process.env.JWT_TTL ?? "12h";

export interface TokenPayload {
  sub: number; // user id
  name: string;
  email: string;
  role: Role;
}

// Validate email + password against the users table.
export async function authenticate(email: string, password: string): Promise<User | null> {
  const user = await findByEmail(email);
  if (!user) return null;
  if (user.password !== hashPassword(password)) return null;
  const { password: _pw, ...safe } = user;
  return safe;
}

export function signToken(user: User): string {
  const payload: TokenPayload = {
    sub: user.id,
    name: user.name,
    email: user.email,
    role: user.role,
  };
  const options: jwt.SignOptions = { expiresIn: TOKEN_TTL as jwt.SignOptions["expiresIn"] };
  return jwt.sign(payload, JWT_SECRET, options);
}

// Attach the decoded payload to the request.
export interface AuthedRequest extends Request {
  user?: TokenPayload;
}

// Confere o token E se a conta segue valendo. O segundo passo custa uma consulta
// por requisição e existe porque o token vive 12 horas: sem ele, desativar um
// usuário só surtiria efeito quando o dele vencesse — justo no caso (desligamento)
// em que se quer tirar o acesso agora.
export async function requireAuth(req: AuthedRequest, res: Response, next: NextFunction) {
  const header = req.headers.authorization ?? "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : null;
  if (!token) {
    return res.status(401).json({ error: "unauthorized", message: "Token ausente." });
  }
  let payload: TokenPayload;
  try {
    payload = jwt.verify(token, JWT_SECRET) as unknown as TokenPayload;
  } catch {
    return res.status(401).json({ error: "unauthorized", message: "Token inválido ou expirado." });
  }

  try {
    const ativo = await usuarioAtivo(payload.sub);
    // 401 (e não 403) de propósito: é o código que faz o app limpar a sessão e
    // mandar para o login, em vez de deixar a pessoa numa tela que não carrega.
    if (ativo === null) {
      return res.status(401).json({ error: "unauthorized", message: "Usuário não encontrado." });
    }
    if (!ativo) {
      return res.status(401).json({
        error: "inativo",
        message: "Seu acesso foi desativado. Fale com um administrador.",
      });
    }
  } catch (err) {
    return next(err);
  }

  req.user = payload;
  next();
}

// Perfil Jurídico só enxerga a Precificação. Aplicado nas demais rotas de
// negócio; escrever na Precificação já é barrado pelo requireAdmin.
export function blockJuridico(req: AuthedRequest, res: Response, next: NextFunction) {
  if (req.user?.role !== "juridico") return next();
  res.status(403).json({
    error: "forbidden",
    message: "O perfil Jurídico tem acesso apenas à Precificação.",
  });
}

export function requireAdmin(req: AuthedRequest, res: Response, next: NextFunction) {
  if (req.user?.role !== "admin") {
    return res.status(403).json({ error: "forbidden", message: "Acesso restrito a administradores." });
  }
  next();
}
