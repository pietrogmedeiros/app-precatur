import { Router } from "express";
import {
  listaSimulacoes, resumoPorPraca, serieMensal, porNatureza, porAtivo, apagaSimulacao,
} from "../simulacoes";
import { requireAuth, requireAdmin, blockJuridico } from "../auth";

export const simulacoesRouter = Router();

// Tela interna: lista, histórico por praça e os agregados dos gráficos.
simulacoesRouter.get("/", requireAuth, blockJuridico, async (_req, res, next) => {
  try {
    const [itens, resumo, mensal, natureza, ativo] = await Promise.all([
      listaSimulacoes(), resumoPorPraca(), serieMensal(), porNatureza(), porAtivo(),
    ]);
    res.json({ itens, resumo, mensal, natureza, ativo });
  } catch (err) {
    next(err);
  }
});

// Remover simulação é coisa de admin: serve para limpar teste e lixo, e some
// com um lead de verdade se usado sem cuidado.
simulacoesRouter.delete("/:id", requireAuth, blockJuridico, requireAdmin, async (req, res, next) => {
  try {
    const id = Number(req.params.id);
    if (!Number.isInteger(id)) {
      return res.status(400).json({ error: "bad_request", message: "ID inválido." });
    }
    if (!(await apagaSimulacao(id))) {
      return res.status(404).json({ error: "not_found", message: "Simulação não encontrada." });
    }
    res.status(204).end();
  } catch (err) {
    next(err);
  }
});
