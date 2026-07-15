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

app.get("/api/health", async (_req, res) => {
  try {
    await pool.query("SELECT 1");
    res.json({ status: "ok", db: "up" });
  } catch {
    res.status(503).json({ status: "degraded", db: "down" });
  }
});

app.use("/api/auth", authRouter);
app.use("/api/metrics", requireAuth, metricsRouter);
app.use("/api/metabase", requireAuth, metabaseRouter);
app.use("/api/users", requireAuth, requireAdmin, usersRouter);
app.use("/api/propostas", requireAuth, proposalsRouter);
app.use("/api/bitrix", requireAuth, bitrixRouter);

// Central error handler so route failures return JSON, not an HTML stack.
app.use((err: any, _req: express.Request, res: express.Response, _next: express.NextFunction) => {
  console.error("[api] error:", err);
  res.status(500).json({ error: "internal_error", message: err?.message ?? "unknown" });
});

async function bootstrap() {
  if (process.env.MIGRATE_ON_START !== "false") {
    await runMigrations();
  }
  // Always ensure an admin exists so login is possible.
  await seedAdmin();
  if (process.env.SEED_ON_START === "true") {
    await seed();
  }
  app.listen(PORT, () => {
    console.log(`[api] listening on :${PORT}`);
  });
}

bootstrap().catch((err) => {
  console.error("[api] failed to start", err);
  process.exit(1);
});
