import { Router } from "express";
import {
  historicoDiretrizes, lerDiretrizes, salvarDiretrizes, MuralError,
} from "../mural";
import { requireAdmin, type AuthedRequest } from "../auth";

export const muralRouter = Router();

// Leitura é de todo usuário autenticado — inclusive o Jurídico, que é quem mais
// consulta o mural. Escrita é só do admin: diretriz de compra é regra da casa.
muralRouter.get("/diretrizes", async (_req, res, next) => {
  try {
    res.json(await lerDiretrizes());
  } catch (err) {
    next(err);
  }
});

muralRouter.put("/diretrizes", requireAdmin, async (req: AuthedRequest, res, next) => {
  try {
    const texto = req.body?.texto;
    if (typeof texto !== "string") {
      return res.status(400).json({ error: "bad_request", message: "Informe o texto." });
    }
    // A autoria vem do TOKEN, nunca do corpo: é ela que o time lê para saber a
    // quem perguntar quando a diretriz não bate com o que o vendedor ouviu.
    const autor = req.user?.name ?? req.user?.email ?? null;
    res.json(await salvarDiretrizes(texto, autor));
  } catch (err) {
    if (err instanceof MuralError) {
      return res.status(err.status).json({ error: "bad_request", message: err.message });
    }
    next(err);
  }
});

// Versões anteriores: quem muda a regra precisa poder mostrar o que valia antes.
muralRouter.get("/diretrizes/historico", requireAdmin, async (req, res, next) => {
  try {
    res.json(await historicoDiretrizes(Number(req.query.limite ?? 20)));
  } catch (err) {
    next(err);
  }
});
