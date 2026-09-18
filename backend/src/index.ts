import express from "express";
import cors from "cors";
import dotenv from "dotenv";
import { pool } from "./db";
import { runMigrations } from "./migrate";
import { seed, seedAdmin } from "./seed";
import { metricsRouter } from "./routes/metrics";
import { metabaseRouter } from "./routes/metabase";
import { authRouter } from "./routes/auth";
import { usersRouter } from "./routes/users";
import { proposalsRouter } from "./routes/proposals";
import { followupsRouter } from "./routes/followups";
import { pricingRouter } from "./routes/pricing";
import { bitrixRouter } from "./routes/bitrix";
import { requireAuth, requireAdmin } from "./auth";

dotenv.config();

const app = express();
const PORT = Number(process.env.PORT ?? 8080);

// CORS: allow a comma-separated list of origins, or * for any (dev).
const corsOrigin = process.env.CORS_ORIGIN ?? "*";
const allowedOrigins = corsOrigin.split(",").map((o) => o.trim());
app.use(
  cors({
    origin: allowedOrigins.includes("*") ? true : allowedOrigins,
  })
);
app.use(express.json());

// Estado da inicialização. A API passa a escutar na porta ANTES de migrar, para
// que um problema no boot vire uma resposta explicando o que houve — antes, o
// processo ficava pendurado na migration, nunca escutava, e todo /api/* virava
// um "Internal Server Error" opaco vindo do proxy do Next.
let ready = false;
let bootError: string | null = null;

app.get("/api/health", async (_req, res) => {
  const base = { ready, ...(bootError ? { bootError } : {}) };
  try {
    await pool.query("SELECT 1");
    res.status(ready ? 200 : 503).json({ status: ready ? "ok" : "starting", db: "up", ...base });
  } catch {
    res.status(503).json({ status: "degraded", db: "down", ...base });
  }
});

// Enquanto o boot não termina, as rotas respondem 503 com motivo — nunca um erro
// genérico. O /api/health acima fica fora do portão de propósito.
app.use("/api", (_req, res, next) => {
  if (ready) return next();
  res.status(503).json({
    error: "starting",
    message: bootError ?? "API ainda inicializando (migrations em andamento). Tente em instantes.",
  });
});

app.use("/api/auth", authRouter);
app.use("/api/metrics", requireAuth, metricsRouter);
app.use("/api/metabase", requireAuth, metabaseRouter);
app.use("/api/users", requireAuth, requireAdmin, usersRouter);
app.use("/api/propostas", requireAuth, proposalsRouter);
app.use("/api/followups", requireAuth, followupsRouter);
app.use("/api/pricing", requireAuth, pricingRouter);
app.use("/api/bitrix", requireAuth, bitrixRouter);

// Central error handler so route failures return JSON, not an HTML stack.
app.use((err: any, _req: express.Request, res: express.Response, _next: express.NextFunction) => {
  console.error("[api] error:", err);
  res.status(500).json({ error: "internal_error", message: err?.message ?? "unknown" });
});

async function bootstrap() {
  // Escuta primeiro: assim health e o portão de 503 já respondem enquanto o
  // resto do boot acontece.
  app.listen(PORT, () => {
    console.log(`[api] listening on :${PORT}`);
  });

  if (process.env.MIGRATE_ON_START !== "false") {
    await runMigrations();
  }
  // Always ensure an admin exists so login is possible.
  await seedAdmin();
  if (process.env.SEED_ON_START === "true") {
    await seed();
  }
  ready = true;
  console.log("[api] boot concluído — pronto para receber requisições");
}

bootstrap().catch((err) => {
  bootError = `Falha no boot da API: ${err?.message ?? err}`;
  console.error("[api] failed to start", err);
  // Sai para o orquestrador reiniciar: um lock transitório costuma passar na
  // próxima tentativa, e o crash fica visível no painel — ao contrário do
  // travamento silencioso que essa mudança elimina.
  process.exit(1);
});
