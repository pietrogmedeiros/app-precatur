import { Router } from "express";
import jwt from "jsonwebtoken";

// Server-side minting of the short-lived Metabase embedding JWT.
// The secret NEVER reaches the browser: the frontend authenticates as usual
// (requireAuth on the mount below) and gets back only a signed token that
// expires in 10 minutes, which it hands to the <metabase-dashboard> element.
export const metabaseRouter = Router();

const METABASE_SECRET_KEY = process.env.METABASE_SECRET_KEY ?? "";
const METABASE_INSTANCE_URL =
  process.env.METABASE_INSTANCE_URL ?? "https://precatur-metabase.ty9ddu.easypanel.host";
const METABASE_DASHBOARD_ID = Number(process.env.METABASE_DASHBOARD_ID ?? 2);
const TTL_SECONDS = 10 * 60; // 10 minutes, per Metabase embedding guidance.

metabaseRouter.get("/token", (_req, res, next) => {
  try {
    if (!METABASE_SECRET_KEY) {
      return res.status(500).json({
        error: "config",
        message: "METABASE_SECRET_KEY não configurada no servidor.",
      });
    }

    const payload = {
      resource: { dashboard: METABASE_DASHBOARD_ID },
      params: {},
      exp: Math.round(Date.now() / 1000) + TTL_SECONDS,
    };
    const token = jwt.sign(payload, METABASE_SECRET_KEY);

    res.json({ token, instanceUrl: METABASE_INSTANCE_URL });
  } catch (err) {
    next(err);
  }
});
