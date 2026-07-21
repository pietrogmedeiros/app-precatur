import { Router } from "express";
import { listUsers, createUser, deleteUser, updateUserPhone } from "../users";
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
    const { name, email, password, role, phone } = req.body ?? {};
    if (
      typeof name !== "string" ||
      typeof email !== "string" ||
      typeof password !== "string" ||
      typeof phone !== "string" ||
      !name.trim() ||
      !email.trim() ||
      !phone.trim() ||
      password.length < 4
    ) {
      return res.status(400).json({
        error: "bad_request",
        message: "Nome, e-mail, telefone e senha (mín. 4 caracteres) são obrigatórios.",
      });
    }
    const finalRole = role === "admin" ? "admin" : "padrao";
    const user = await createUser({
      name: name.trim(),
      email: email.trim(),
      password,
      role: finalRole,
      phone: phone.trim(),
    });
    res.status(201).json(user);
  } catch (err: any) {
    if (err?.code === "23505") {
      return res.status(409).json({ error: "conflict", message: "Já existe um usuário com esse e-mail." });
    }
    next(err);
  }
});

// Edição do telefone de um usuário (admin). Só o telefone é editável por aqui.
usersRouter.put("/:id", async (req, res, next) => {
  try {
    const id = Number(req.params.id);
    if (!Number.isInteger(id)) {
      return res.status(400).json({ error: "bad_request", message: "ID inválido." });
    }
    const { phone } = req.body ?? {};
    if (typeof phone !== "string" || !phone.trim()) {
      return res.status(400).json({ error: "bad_request", message: "Informe o telefone." });
    }
    const user = await updateUserPhone(id, phone.trim());
    if (!user) {
      return res.status(404).json({ error: "not_found", message: "Usuário não encontrado." });
    }
    res.json(user);
  } catch (err) {
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
