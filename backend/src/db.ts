import { Pool } from "pg";
import dotenv from "dotenv";

dotenv.config();

const connectionString = process.env.DATABASE_URL;
const sslOption = process.env.PGSSL === "true" ? { rejectUnauthorized: false } : undefined;

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
    password: process.env.PGPASSWORD,
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
