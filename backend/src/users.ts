import crypto from "crypto";
import { query } from "./db";

export type Role = "admin" | "padrao";

export interface User {
  id: number;
  name: string;
  email: string;
  role: Role;
  phone: string | null;
  created_at: string;
  last_login_at: string | null;
}

interface UserWithHash extends User {
  password: string;
}

// SHA-256 (hex) — matches the `password` column format.
export function hashPassword(plain: string): string {
  return crypto.createHash("sha256").update(plain).digest("hex");
}

export async function findByEmail(email: string): Promise<UserWithHash | null> {
  const rows = await query<UserWithHash>(
    `SELECT id, name, email, password, role, phone, created_at, last_login_at FROM users WHERE email = $1`,
    [email.toLowerCase()]
  );
  return rows[0] ?? null;
}

export async function listUsers(): Promise<User[]> {
  return query<User>(
    `SELECT id, name, email, role, phone, created_at, last_login_at FROM users ORDER BY created_at ASC`
  );
}

export async function createUser(input: {
  name: string;
  email: string;
  password: string;
  role: Role;
  phone: string;
}): Promise<User> {
  const rows = await query<User>(
    `INSERT INTO users (name, email, password, role, phone)
     VALUES ($1, $2, $3, $4, $5)
     RETURNING id, name, email, role, phone, created_at, last_login_at`,
    [input.name, input.email.toLowerCase(), hashPassword(input.password), input.role, input.phone]
  );
  return rows[0];
}

// Atualiza o telefone de um usuário (edição pelo admin ou pelo próprio no perfil).
export async function updateUserPhone(id: number, phone: string): Promise<User | null> {
  const rows = await query<User>(
    `UPDATE users SET phone = $2 WHERE id = $1
     RETURNING id, name, email, role, phone, created_at, last_login_at`,
    [id, phone]
  );
  return rows[0] ?? null;
}

// Carimba o horário do último acesso. Chamado após um login bem-sucedido.
export async function recordLogin(id: number): Promise<void> {
  await query(`UPDATE users SET last_login_at = now() WHERE id = $1`, [id]);
}

export async function findById(id: number): Promise<UserWithHash | null> {
  const rows = await query<UserWithHash>(
    `SELECT id, name, email, password, role, phone, created_at, last_login_at FROM users WHERE id = $1`,
    [id]
  );
  return rows[0] ?? null;
}

export async function updatePassword(id: number, newPlain: string): Promise<void> {
  await query(`UPDATE users SET password = $2 WHERE id = $1`, [id, hashPassword(newPlain)]);
}

export async function deleteUser(id: number): Promise<void> {
  await query(`DELETE FROM users WHERE id = $1`, [id]);
}

export async function countUsers(): Promise<number> {
  const rows = await query<{ count: string }>(`SELECT COUNT(*)::int AS count FROM users`);
  return Number(rows[0]?.count ?? 0);
}
