import { Router } from "express";
import {
  listPricing,
  updatePricing,
  validateRows,
  PricingError,
  IMPORTABLE_KEYS,
  type PricingPatch,
} from "../pricing";
import { requireAdmin, type AuthedRequest } from "../auth";

export const pricingRouter = Router();

// Consulta é livre para qualquer usuário autenticado: todo o comercial precisa
// calcular com a mesma tabela.
pricingRouter.get("/", async (_req, res, next) => {
  try {
    res.json(await listPricing());
  } catch (err) {
    next(err);
  }
});

function sendError(res: any, err: unknown, next: (e: unknown) => void) {
  if (err instanceof PricingError) {
    return res.status(err.status).json({ error: "bad_request", message: err.message });
  }
  next(err);
}

// Edição manual de um ente (tabela, abatimento fixo, descrição) — só admin,
// porque define o preço máximo que a empresa paga.
pricingRouter.put("/:key", requireAdmin, async (req: AuthedRequest, res, next) => {
  try {
    const body = req.body ?? {};
    const patch: PricingPatch = {};

    if (body.rows !== undefined) {
      const v = validateRows(body.rows);
      if ("error" in v) return res.status(400).json({ error: "bad_request", message: v.error });
      patch.rows = v.rows;
    }
    if (body.fixed_deduction !== undefined) {
      const d = Number(body.fixed_deduction);
      if (!Number.isFinite(d) || d < 0 || d > 10_000_000) {
        return res.status(400).json({ error: "bad_request", message: "Abatimento fixo inválido." });
      }
      patch.fixed_deduction = Math.round(d * 100) / 100;
    }
    if (body.description !== undefined) {
      const t = String(body.description).trim();
      if (t.length > 300) {
        return res.status(400).json({ error: "bad_request", message: "Descrição com mais de 300 caracteres." });
      }
      patch.description = t;
    }
    if (!Object.keys(patch).length) {
      return res.status(400).json({ error: "bad_request", message: "Nada para atualizar." });
    }

    res.json(await updatePricing({ [req.params.key]: patch }, req.user?.email ?? null, "edit"));
  } catch (err) {
    sendError(res, err, next);
  }
});

// Importação da planilha comercial. O XLSX é lido no navegador (mesma lógica do
// HTML antigo) e chega aqui já como linhas — a API valida tudo antes de gravar.
pricingRouter.post("/import", requireAdmin, async (req: AuthedRequest, res, next) => {
  try {
    const body = req.body ?? {};
    const patches: Record<string, PricingPatch> = {};

    for (const key of IMPORTABLE_KEYS) {
      if (body[key] === undefined) continue;
      const v = validateRows(body[key]);
      if ("error" in v) {
        return res.status(400).json({ error: "bad_request", message: `Tabela ${key}: ${v.error}` });
      }
      patches[key] = { rows: v.rows };
    }
    if (!Object.keys(patches).length) {
      return res.status(400).json({
        error: "bad_request",
        message: "Nenhuma tabela Federal, Estadual ou Municipal encontrada na planilha.",
      });
    }

    const entities = await updatePricing(patches, req.user?.email ?? null, "import");
    res.json({ updated: Object.keys(patches), entities });
  } catch (err) {
    sendError(res, err, next);
  }
});
