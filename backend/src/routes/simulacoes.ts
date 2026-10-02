import { Router } from "express";
import { listaSimulacoes, resumoPorPraca } from "../simulacoes";
import { requireAuth, blockJuridico } from "../auth";

export const simulacoesRouter = Router();

// Tela interna: lista das simulações e o histórico por praça.
simulacoesRouter.get("/", requireAuth, blockJuridico, async (_req, res, next) => {
  try {
    const [itens, resumo] = await Promise.all([listaSimulacoes(), resumoPorPraca()]);
    res.json({ itens, resumo });
  } catch (err) {
    next(err);
  }
});
