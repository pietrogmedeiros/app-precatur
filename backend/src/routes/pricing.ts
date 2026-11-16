import { Router } from "express";
import {
  criaPraca,
  listPricing,
  updatePricing,
  validateRows,
  PricingError,
  IMPORTABLE_KEYS,
  checaEdicaoMunicipal,
  getPricing,
  getHistoryEntry,
  listHistory,
  type PricingPatch,
} from "../pricing";
import { previewMudanca } from "../pricingPreview";
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

// Converte e valida o corpo de uma edição. Compartilhado pelo PUT e pela
// pré-visualização, para as duas aceitarem e recusarem exatamente o mesmo.
function lePatch(body: any): { patch: PricingPatch } | { error: string } {
  const patch: PricingPatch = {};

  // A chave continua imutável de propósito: ela é referência da importação da
  // planilha e do histórico. O que muda aqui é só o nome exibido.
  if (body.label !== undefined) {
    const t = String(body.label).trim();
    if (t.length < 2 || t.length > 120) return { error: "O nome da praça precisa ter de 2 a 120 caracteres." };
    patch.label = t;
  }
  if (body.rows !== undefined) {
    const v = validateRows(body.rows);
    if ("error" in v) return { error: v.error };
    patch.rows = v.rows;
  }
  if (body.fixed_deduction !== undefined) {
    const d = Number(body.fixed_deduction);
    if (!Number.isFinite(d) || d < 0 || d > 10_000_000) return { error: "Abatimento fixo inválido." };
    patch.fixed_deduction = Math.round(d * 100) / 100;
  }
  if (body.description !== undefined) {
    const t = String(body.description).trim();
    if (t.length > 300) return { error: "Descrição com mais de 300 caracteres." };
    patch.description = t;
  }
  if (body.hidden !== undefined) patch.hidden = Boolean(body.hidden);
  if (body.municipal_reference !== undefined) patch.municipal_reference = Boolean(body.municipal_reference);
  if (!Object.keys(patch).length) return { error: "Nada para atualizar." };
  return { patch };
}

function trimestreAtual(): number {
  return Math.floor(new Date().getMonth() / 3);
}

// Pré-visualização: compara o que está valendo com o que o patch gravaria, sem
// escrever nada. Serve a tela de edição, a restauração do histórico e a importação.
async function previewDoPatch(key: string, patch: PricingPatch) {
  const atual = await getPricing(key);
  checaEdicaoMunicipal(key, atual, patch);
  return {
    key,
    label: atual.label,
    ...previewMudanca(
      { rows: atual.rows, fixed_deduction: atual.fixed_deduction },
      {
        rows: patch.rows ?? atual.rows,
        fixed_deduction: patch.fixed_deduction ?? atual.fixed_deduction,
      },
      trimestreAtual()
    ),
  };
}

// Edição manual de um ente (tabela, abatimento fixo, descrição) — só admin,
// porque define o preço máximo que a empresa paga.
pricingRouter.put("/:key", blockJuridico, requireAdmin, async (req: AuthedRequest, res, next) => {
  try {
    const lido = lePatch(req.body ?? {});
    if ("error" in lido) return res.status(400).json({ error: "bad_request", message: lido.error });
    res.json(await updatePricing({ [req.params.key]: lido.patch }, req.user?.email ?? null, "edit"));
  } catch (err) {
    sendError(res, err, next);
  }
});

// Mostra o antes × depois (e os avisos de coerência) de uma edição, sem gravar.
pricingRouter.post("/:key/preview", blockJuridico, requireAdmin, async (req: AuthedRequest, res, next) => {
  try {
    const lido = lePatch(req.body ?? {});
    if ("error" in lido) return res.status(400).json({ error: "bad_request", message: lido.error });
    res.json(await previewDoPatch(req.params.key, lido.patch));
  } catch (err) {
    sendError(res, err, next);
  }
});

// Versões anteriores da praça (cada uma gravada ao ser substituída).
pricingRouter.get("/:key/history", blockJuridico, requireAdmin, async (req, res, next) => {
  try {
    res.json(await listHistory(req.params.key));
  } catch (err) {
    next(err);
  }
});

// Volta a praça a uma versão do histórico. A versão que está valendo agora vai
// para o histórico antes (source "restore"), então restaurar também é desfazível.
pricingRouter.post("/:key/restore/:id", blockJuridico, requireAdmin, async (req: AuthedRequest, res, next) => {
  try {
    const id = Number(req.params.id);
    if (!Number.isInteger(id)) return res.status(400).json({ error: "bad_request", message: "Versão inválida." });
    const versao = await getHistoryEntry(req.params.key, id);
    const v = validateRows(versao.rows);
    if ("error" in v) return res.status(400).json({ error: "bad_request", message: `Versão guardada inválida: ${v.error}` });
    const patch: PricingPatch = { rows: v.rows, fixed_deduction: versao.fixed_deduction, description: versao.description };
    res.json(await updatePricing({ [req.params.key]: patch }, req.user?.email ?? null, "restore"));
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
function patchesDaImportacao(body: any): { patches: Record<string, PricingPatch> } | { error: string } {
  const patches: Record<string, PricingPatch> = {};
  for (const key of IMPORTABLE_KEYS) {
    if (body[key] === undefined) continue;
    const v = validateRows(body[key]);
    if ("error" in v) return { error: `Tabela ${key}: ${v.error}` };
    // Planilha antiga ainda traz a coluna de ativo; gravamos tudo como
    // precatório, que é o que a casa compra hoje.
    patches[key] = { rows: v.rows.map((r) => ({ ...r, asset: "Precatório" })) };
  }
  if (!Object.keys(patches).length) {
    return { error: "Nenhuma tabela Federal, Estadual ou Municipal encontrada na planilha." };
  }
  return { patches };
}

// Antes × depois da planilha, praça por praça, sem gravar.
pricingRouter.post("/import-preview", blockJuridico, requireAdmin, async (req: AuthedRequest, res, next) => {
  try {
    const lido = patchesDaImportacao(req.body ?? {});
    if ("error" in lido) return res.status(400).json({ error: "bad_request", message: lido.error });
    const previews = [];
    for (const [key, patch] of Object.entries(lido.patches)) previews.push(await previewDoPatch(key, patch));
    res.json(previews);
  } catch (err) {
    sendError(res, err, next);
  }
});

pricingRouter.post("/import", blockJuridico, requireAdmin, async (req: AuthedRequest, res, next) => {
  try {
    const lido = patchesDaImportacao(req.body ?? {});
    if ("error" in lido) return res.status(400).json({ error: "bad_request", message: lido.error });
    const entities = await updatePricing(lido.patches, req.user?.email ?? null, "import");
    res.json({ updated: Object.keys(lido.patches), entities });
  } catch (err) {
    sendError(res, err, next);
  }
});
