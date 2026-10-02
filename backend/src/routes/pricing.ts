import { Router } from "express";
import {
  criaPraca,
  listPricing,
  updatePricing,
  validateRows,
  PricingError,
  IMPORTABLE_KEYS,
  type PricingPatch,
} from "../pricing";
import { requireAdmin, blockJuridico, type AuthedRequest } from "../auth";

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
pricingRouter.put("/:key", blockJuridico, requireAdmin, async (req: AuthedRequest, res, next) => {
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
    if (body.hidden !== undefined) {
      patch.hidden = Boolean(body.hidden);
    }
    if (!Object.keys(patch).length) {
      return res.status(400).json({ error: "bad_request", message: "Nada para atualizar." });
    }

    res.json(await updatePricing({ [req.params.key]: patch }, req.user?.email ?? null, "edit"));
  } catch (err) {
    sendError(res, err, next);
  }
});

// Cadastro de praça nova — só admin, como toda escrita de preço.
pricingRouter.post("/", blockJuridico, requireAdmin, async (req: AuthedRequest, res, next) => {
  try {
    const b = req.body ?? {};
    const label = String(b.label ?? "").trim();
    if (label.length < 2 || label.length > 120) {
      return res.status(400).json({ error: "bad_request", message: "Informe o nome da praça." });
    }
    const esfera = ["federal", "estadual", "municipal"].includes(b.esfera) ? b.esfera : null;
    if (!esfera) {
      return res.status(400).json({ error: "bad_request", message: "Escolha a esfera (federal, estadual ou municipal)." });
    }
    const uf = String(b.uf ?? "").trim().toUpperCase().slice(0, 2) || null;
    if (esfera !== "federal" && !/^[A-Z]{2}$/.test(uf ?? "")) {
      return res.status(400).json({ error: "bad_request", message: "Informe a UF de duas letras." });
    }
    const v = validateRows(b.rows);
    if ("error" in v) return res.status(400).json({ error: "bad_request", message: v.error });

    // Identificador sem acento nem espaço, derivado do nome.
    const key = label.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
      .toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);
    if (!key) return res.status(400).json({ error: "bad_request", message: "Nome inválido." });

    const d = Number(b.fixed_deduction ?? 0);
    const entities = await criaPraca({
      key, label,
      description: String(b.description ?? "").trim().slice(0, 300),
      esfera, uf, municipio: String(b.municipio ?? "").trim().slice(0, 120) || null,
      fixed_deduction: Number.isFinite(d) && d >= 0 ? Math.round(d * 100) / 100 : 0,
      rows: v.rows,
      criadoPor: req.user?.email ?? null,
    });
    res.status(201).json(entities);
  } catch (err) {
    sendError(res, err, next);
  }
});

// Importação da planilha comercial. O XLSX é lido no navegador (mesma lógica do
// HTML antigo) e chega aqui já como linhas — a API valida tudo antes de gravar.
pricingRouter.post("/import", blockJuridico, requireAdmin, async (req: AuthedRequest, res, next) => {
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
