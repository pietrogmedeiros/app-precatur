import { Pool } from "pg";
import dotenv from "dotenv";

dotenv.config();

const connectionString = process.env.DATABASE_URL;
const sslOption = process.env.PGSSL === "true" ? { rejectUnauthorized: false } : undefined;

// Password can be provided raw (PGPASSWORD) or base64-encoded (PGPASSWORD_B64).
// Base64 avoids any file-parser issues with special chars like # @ (a '#' in a
// .env line starts a comment). Encode once: printf '%s' 'yourpass' | base64
function resolvePassword(): string | undefined {
  const b64 = process.env.PGPASSWORD_B64;
  if (b64 && b64.trim()) {
    return Buffer.from(b64.trim(), "base64").toString("utf8");
  }
  return process.env.PGPASSWORD;
}

let poolConfig: import("pg").PoolConfig;

if (connectionString) {
  // Single connection URL. Note: special chars in the password (@ # etc.) must
  // be percent-encoded here — or use the discrete PG* vars below instead.
  const needsSsl = /sslmode=require/i.test(connectionString) || process.env.PGSSL === "true";
  poolConfig = {
    connectionString,
    ssl: needsSsl ? { rejectUnauthorized: false } : undefined,
  };
} else if (process.env.PGHOST && process.env.PGDATABASE) {
  // Discrete variables — the password is used RAW (no URL escaping needed),
  // which is the safe choice when it contains @ # / ? % etc.
  poolConfig = {
    host: process.env.PGHOST,
    port: Number(process.env.PGPORT ?? 5432),
    user: process.env.PGUSER,
    password: resolvePassword(),
    database: process.env.PGDATABASE,
    ssl: sslOption,
  };
} else {
  // Fail fast with a clear message rather than an obscure driver error.
  throw new Error(
    "Configure DATABASE_URL, ou as variáveis PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE. Veja .env.example."
  );
}

export const pool = new Pool(poolConfig);

export async function query<T = any>(text: string, params?: any[]): Promise<T[]> {
  const result = await pool.query(text, params);
  return result.rows as T[];
}
