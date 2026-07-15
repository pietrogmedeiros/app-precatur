import crypto from "crypto";
import { query } from "./db";

export type Role = "admin" | "padrao";

export interface User {
  id: number;
  name: string;
  email: string;
  role: Role;
  created_at: string;
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
    `SELECT id, name, email, password, role, created_at FROM users WHERE email = $1`,
    [email.toLowerCase()]
  );
  return rows[0] ?? null;
}

export async function listUsers(): Promise<User[]> {
  return query<User>(
    `SELECT id, name, email, role, created_at FROM users ORDER BY created_at ASC`
  );
}

export async function createUser(input: {
  name: string;
  email: string;
  password: string;
  role: Role;
}): Promise<User> {
  const rows = await query<User>(
    `INSERT INTO users (name, email, password, role)
     VALUES ($1, $2, $3, $4)
     RETURNING id, name, email, role, created_at`,
    [input.name, input.email.toLowerCase(), hashPassword(input.password), input.role]
  );
  return rows[0];
}

export async function findById(id: number): Promise<UserWithHash | null> {
  const rows = await query<UserWithHash>(
    `SELECT id, name, email, password, role, created_at FROM users WHERE id = $1`,
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
