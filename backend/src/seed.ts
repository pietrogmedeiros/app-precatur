import { pool } from "./db";
import { runMigrations } from "./migrate";
import { countUsers, createUser } from "./users";

const OWNERS = [
  "Ana Costa",
  "Bruno Almeida",
  "Carla Dias",
  "Diego Ferreira",
  "Elisa Gomes",
  "Felipe Rocha",
];

const STATUSES = ["novo", "qualificado", "convertido", "perdido"] as const;

// Per-owner "skill" weights so the dashboard shows a realistic ranking instead
// of uniform noise. Higher weight -> more likely to qualify and convert.
const OWNER_SKILL: Record<string, number> = {
  "Ana Costa": 1.25,
  "Bruno Almeida": 0.85,
  "Carla Dias": 1.1,
  "Diego Ferreira": 0.7,
  "Elisa Gomes": 1.0,
  "Felipe Rocha": 0.95,
};

function pickStatus(skill: number): (typeof STATUSES)[number] {
  // Base funnel: most leads stay new/lost, fewer qualify, fewer convert.
  const r = Math.random();
  const qualify = 0.45 * skill; // chance of at least qualifying
  const convert = 0.22 * skill; // chance of converting
  if (r < convert) return "convertido";
  if (r < qualify) return "qualificado";
  if (r < qualify + 0.25) return "perdido";
  return "novo";
}

function randomValue(): number {
  // Deal sizes between R$ 2k and R$ 60k, skewed toward smaller deals.
  const base = 2000 + Math.random() * Math.random() * 58000;
  return Math.round(base / 100) * 100;
}

function monthsAgoDate(maxMonths: number): Date {
  const now = new Date();
  const offsetDays = Math.floor(Math.random() * maxMonths * 30);
  const d = new Date(now);
  d.setDate(d.getDate() - offsetDays);
  return d;
}

// Ensures at least one admin exists so there's always a way to log in.
async function seedAdmin(): Promise<void> {
  if ((await countUsers()) > 0) {
    console.log("[seed] users table already populated, skipping admin.");
    return;
  }
  const name = process.env.ADMIN_NAME ?? "Admin";
  const email = process.env.ADMIN_EMAIL ?? "admin@precatur.com";
  const password = process.env.ADMIN_PASSWORD ?? "precatur";
  await createUser({ name, email, password, role: "admin" });
  console.log(`[seed] created admin user: ${email}`);
}

async function seed(count = 520): Promise<void> {
  await runMigrations();
  await seedAdmin();

  const existing = await pool.query<{ count: string }>("SELECT COUNT(*) AS count FROM leads");
  if (Number(existing.rows[0].count) > 0) {
    console.log(`[seed] leads table already has ${existing.rows[0].count} rows, skipping.`);
    return;
  }

  const values: string[] = [];
  const params: any[] = [];
  let i = 1;

  for (let n = 0; n < count; n++) {
    const owner = OWNERS[Math.floor(Math.random() * OWNERS.length)];
    const status = pickStatus(OWNER_SKILL[owner] ?? 1);
    const value = randomValue();
    const createdAt = monthsAgoDate(8);
    values.push(`($${i++}, $${i++}, $${i++}, $${i++})`);
    params.push(owner, status, value, createdAt.toISOString());
  }

  await pool.query(
    `INSERT INTO leads (owner, status, value, created_at) VALUES ${values.join(", ")}`,
    params
  );
  console.log(`[seed] inserted ${count} demo leads.`);
}

// Exported so index.ts can call them on boot.
export { seed, seedAdmin };

if (require.main === module) {
  seed()
    .then(() => pool.end())
    .catch((err) => {
      console.error("[seed] failed", err);
      process.exit(1);
    });
}
