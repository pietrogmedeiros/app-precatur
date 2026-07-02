import jwt from "jsonwebtoken";
import type { Request, Response, NextFunction } from "express";
import { findByEmail, hashPassword, type Role, type User } from "./users";

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

export function requireAuth(req: AuthedRequest, res: Response, next: NextFunction) {
  const header = req.headers.authorization ?? "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : null;
  if (!token) {
    return res.status(401).json({ error: "unauthorized", message: "Token ausente." });
  }
  try {
    req.user = jwt.verify(token, JWT_SECRET) as unknown as TokenPayload;
    next();
  } catch {
    res.status(401).json({ error: "unauthorized", message: "Token inválido ou expirado." });
  }
}

export function requireAdmin(req: AuthedRequest, res: Response, next: NextFunction) {
  if (req.user?.role !== "admin") {
    return res.status(403).json({ error: "forbidden", message: "Acesso restrito a administradores." });
  }
  next();
}
