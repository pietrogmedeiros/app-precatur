import fs from "fs";
import path from "path";
import { pool } from "./db";

// Applies every .sql file in ../migrations in filename order.
// Statements use IF NOT EXISTS, so running this repeatedly is safe.
export async function runMigrations(): Promise<void> {
  const dir = path.join(__dirname, "..", "migrations");
  const files = fs
    .readdirSync(dir)
    .filter((f) => f.endsWith(".sql"))
    .sort();

  // Um ALTER TABLE precisa de lock exclusivo. Se outra sessão segurar a tabela
  // (deploy simultâneo, transação ociosa), o comando espera para SEMPRE e o boot
  // fica pendurado sem erro. Com lock_timeout ele falha rápido e a falha aparece
  // no log em vez de virar uma API que nunca sobe.
  const lockTimeout = process.env.MIGRATE_LOCK_TIMEOUT ?? "15s";
  const statementTimeout = process.env.MIGRATE_STATEMENT_TIMEOUT ?? "60s";

  const client = await pool.connect();
  try {
    await client.query(`SET lock_timeout = '${lockTimeout}'`);
    await client.query(`SET statement_timeout = '${statementTimeout}'`);
    for (const file of files) {
      const sql = fs.readFileSync(path.join(dir, file), "utf8");
      await client.query(sql);
      console.log(`[migrate] applied ${file}`);
    }
  } finally {
    client.release();
  }
}

// Allow running standalone: `npm run migrate`
if (require.main === module) {
  runMigrations()
    .then(() => {
      console.log("[migrate] done");
      return pool.end();
    })
    .catch((err) => {
      console.error("[migrate] failed", err);
      process.exit(1);
    });
}
