import { Router } from "express";
import { listUsers, createUser, deleteUser } from "../users";
import type { AuthedRequest } from "../auth";

export const usersRouter = Router();

usersRouter.get("/", async (_req, res, next) => {
  try {
    res.json(await listUsers());
  } catch (err) {
    next(err);
  }
});

usersRouter.post("/", async (req, res, next) => {
  try {
    const { name, email, password, role } = req.body ?? {};
    if (
      typeof name !== "string" ||
      typeof email !== "string" ||
      typeof password !== "string" ||
      !name.trim() ||
      !email.trim() ||
      password.length < 4
    ) {
      return res.status(400).json({
        error: "bad_request",
        message: "Nome, e-mail e senha (mín. 4 caracteres) são obrigatórios.",
      });
    }
    const finalRole = role === "admin" ? "admin" : "padrao";
    const user = await createUser({ name: name.trim(), email: email.trim(), password, role: finalRole });
    res.status(201).json(user);
  } catch (err: any) {
    if (err?.code === "23505") {
      return res.status(409).json({ error: "conflict", message: "Já existe um usuário com esse e-mail." });
    }
    next(err);
  }
});

usersRouter.delete("/:id", async (req: AuthedRequest, res, next) => {
  try {
    const id = Number(req.params.id);
    if (!Number.isInteger(id)) {
      return res.status(400).json({ error: "bad_request", message: "ID inválido." });
    }
    // Prevent an admin from deleting their own account.
    if (Number(req.user?.sub) === id) {
      return res.status(400).json({ error: "bad_request", message: "Você não pode excluir a própria conta." });
    }
    await deleteUser(id);
    res.status(204).end();
  } catch (err) {
    next(err);
  }
});
