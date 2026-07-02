import { Pool } from "pg";
import dotenv from "dotenv";

dotenv.config();

const connectionString = process.env.DATABASE_URL;

if (!connectionString) {
  // Fail fast with a clear message rather than an obscure driver error.
  throw new Error("DATABASE_URL is not set. Copy .env.example to .env and configure it.");
}

// Some managed Postgres providers require SSL. Enable it when the connection
// string asks for it, otherwise keep it off for local docker-compose.
const needsSsl = /sslmode=require/i.test(connectionString) || process.env.PGSSL === "true";

export const pool = new Pool({
  connectionString,
  ssl: needsSsl ? { rejectUnauthorized: false } : undefined,
});

export async function query<T = any>(text: string, params?: any[]): Promise<T[]> {
  const result = await pool.query(text, params);
  return result.rows as T[];
}
