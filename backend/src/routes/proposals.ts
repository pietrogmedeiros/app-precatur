import { Router } from "express";
import {
  listProposals,
  getProposal,
  createProposal,
  deleteProposal,
  type ProposalInput,
} from "../proposals";
import type { AuthedRequest } from "../auth";

export const proposalsRouter = Router();

function toNumber(v: unknown): number {
  const n = typeof v === "string" ? parseFloat(v) : (v as number);
  return Number.isFinite(n) ? n : 0;
}

// Ano opcional: vazio/inválido volta como null (não 0), para o PDF omitir a linha.
function toYear(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = typeof v === "string" ? parseInt(v, 10) : (v as number);
  if (!Number.isInteger(n) || n < 1900 || n > 2200) return null;
  return n;
}

function toText(v: unknown): string | null {
  if (typeof v !== "string") return null;
  const t = v.trim();
  return t ? t : null;
}

proposalsRouter.get("/", async (_req, res, next) => {
  try {
    res.json(await listProposals());
  } catch (err) {
    next(err);
  }
});

proposalsRouter.get("/:id", async (req, res, next) => {
  try {
    const id = Number(req.params.id);
    if (!Number.isInteger(id)) {
      return res.status(400).json({ error: "bad_request", message: "ID inválido." });
    }
    const proposal = await getProposal(id);
    if (!proposal) {
      return res.status(404).json({ error: "not_found", message: "Proposta não encontrada." });
    }
    res.json(proposal);
  } catch (err) {
    next(err);
  }
});

proposalsRouter.post("/", async (req: AuthedRequest, res, next) => {
  try {
    const body = req.body ?? {};
    if (typeof body.client_name !== "string" || !body.client_name.trim()) {
      return res.status(400).json({
        error: "bad_request",
        message: "O nome do cliente é obrigatório.",
      });
    }
    const input: ProposalInput = {
      proposal_number: body.proposal_number ?? null,
      proposal_date: body.proposal_date ?? null,
      client_name: body.client_name.trim(),
      client_doc: body.client_doc ?? null,
      client_contact: body.client_contact ?? null,
      precatorio_number: body.precatorio_number ?? null,
      tribunal: body.tribunal ?? null,
      ente_devedor: body.ente_devedor ?? null,
      natureza: body.natureza ?? null,
      valor_face: toNumber(body.valor_face),
      valor_proposta: toNumber(body.valor_proposta),
      desagio: toNumber(body.desagio),
      forma_pagamento: body.forma_pagamento ?? null,
      validade: body.validade ?? null,
      observacoes: body.observacoes ?? null,
      responsavel: body.responsavel ?? null,
      ano_pagamento_estado: toYear(body.ano_pagamento_estado),
      observacoes_proposta: toText(body.observacoes_proposta),
      detalhes_processo: toText(body.detalhes_processo),
    };
    const createdBy = req.user?.email ?? req.user?.name ?? null;
    const proposal = await createProposal(input, createdBy);
    res.status(201).json(proposal);
  } catch (err) {
    next(err);
  }
});

proposalsRouter.delete("/:id", async (req, res, next) => {
  try {
    const id = Number(req.params.id);
    if (!Number.isInteger(id)) {
      return res.status(400).json({ error: "bad_request", message: "ID inválido." });
    }
    await deleteProposal(id);
    res.status(204).end();
  } catch (err) {
    next(err);
  }
});
