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

  for (const file of files) {
    const sql = fs.readFileSync(path.join(dir, file), "utf8");
    await pool.query(sql);
    console.log(`[migrate] applied ${file}`);
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
