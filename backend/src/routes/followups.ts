import { Router } from "express";
import {
  listFollowups,
  getFollowup,
  createFollowup,
  updateFollowup,
  deleteFollowup,
  type Followup,
  type FollowupInput,
} from "../followups";
import type { AuthedRequest } from "../auth";

export const followupsRouter = Router();

const MAX_TITLE = 160;
const MAX_BODY = 8000;

// Leitura é livre para qualquer usuário autenticado; escrita/remoção é do autor
// (ou de um admin). O e-mail serve de fallback para linhas cujo autor foi
// removido da tabela users (created_by_id vira NULL).
function canManage(req: AuthedRequest, followup: Followup): boolean {
  if (req.user?.role === "admin") return true;
  // O id do usuário nasce do pg como string (BIGSERIAL) e viaja assim no `sub`
  // do token — compare como número, senão o autor nunca casa com o dono.
  const userId = Number(req.user?.sub);
  if (followup.created_by_id != null && Number.isFinite(userId)) {
    return followup.created_by_id === userId;
  }
  return !!followup.created_by && followup.created_by === req.user?.email;
}

function parseInput(body: any): FollowupInput | { error: string } {
  const title = typeof body?.title === "string" ? body.title.trim() : "";
  const text = typeof body?.body === "string" ? body.body.trim() : "";
  if (!title) return { error: "O título é obrigatório." };
  if (!text) return { error: "O conteúdo do follow-up é obrigatório." };
  if (title.length > MAX_TITLE) return { error: `O título deve ter até ${MAX_TITLE} caracteres.` };
  if (text.length > MAX_BODY) return { error: `O conteúdo deve ter até ${MAX_BODY} caracteres.` };
  return { title, body: text };
}

function parseId(raw: string): number | null {
  const id = Number(raw);
  return Number.isInteger(id) ? id : null;
}

followupsRouter.get("/", async (_req, res, next) => {
  try {
    res.json(await listFollowups());
  } catch (err) {
    next(err);
  }
});

followupsRouter.get("/:id", async (req, res, next) => {
  try {
    const id = parseId(req.params.id);
    if (id === null) {
      return res.status(400).json({ error: "bad_request", message: "ID inválido." });
    }
    const followup = await getFollowup(id);
    if (!followup) {
      return res.status(404).json({ error: "not_found", message: "Follow-up não encontrado." });
    }
    res.json(followup);
  } catch (err) {
    next(err);
  }
});

followupsRouter.post("/", async (req: AuthedRequest, res, next) => {
  try {
    const parsed = parseInput(req.body);
    if ("error" in parsed) {
      return res.status(400).json({ error: "bad_request", message: parsed.error });
    }
    const author = req.user
      ? { id: req.user.sub, email: req.user.email, name: req.user.name }
      : null;
    res.status(201).json(await createFollowup(parsed, author));
  } catch (err) {
    next(err);
  }
});

followupsRouter.put("/:id", async (req: AuthedRequest, res, next) => {
  try {
    const id = parseId(req.params.id);
    if (id === null) {
      return res.status(400).json({ error: "bad_request", message: "ID inválido." });
    }
    const existing = await getFollowup(id);
    if (!existing) {
      return res.status(404).json({ error: "not_found", message: "Follow-up não encontrado." });
    }
    if (!canManage(req, existing)) {
      return res.status(403).json({
        error: "forbidden",
        message: "Só o autor do follow-up (ou um admin) pode editá-lo.",
      });
    }
    const parsed = parseInput(req.body);
    if ("error" in parsed) {
      return res.status(400).json({ error: "bad_request", message: parsed.error });
    }
    res.json(await updateFollowup(id, parsed));
  } catch (err) {
    next(err);
  }
});

followupsRouter.delete("/:id", async (req: AuthedRequest, res, next) => {
  try {
    const id = parseId(req.params.id);
    if (id === null) {
      return res.status(400).json({ error: "bad_request", message: "ID inválido." });
    }
    const existing = await getFollowup(id);
    if (!existing) {
      return res.status(404).json({ error: "not_found", message: "Follow-up não encontrado." });
    }
    if (!canManage(req, existing)) {
      return res.status(403).json({
        error: "forbidden",
        message: "Só o autor do follow-up (ou um admin) pode excluí-lo.",
      });
    }
    await deleteFollowup(id);
    res.status(204).end();
  } catch (err) {
    next(err);
  }
});
