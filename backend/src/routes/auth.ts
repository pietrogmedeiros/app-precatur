import { Router } from "express";
import { authenticate, signToken, requireAuth, type AuthedRequest } from "../auth";
import { findById, updatePassword, hashPassword, recordLogin } from "../users";

export const authRouter = Router();

authRouter.post("/login", async (req, res, next) => {
  try {
    const { email, password } = req.body ?? {};
    if (typeof email !== "string" || typeof password !== "string") {
      return res.status(400).json({ error: "bad_request", message: "Informe e-mail e senha." });
    }
    const user = await authenticate(email, password);
    if (!user) {
      return res.status(401).json({ error: "invalid_credentials", message: "E-mail ou senha incorretos." });
    }
    await recordLogin(user.id);
    const token = signToken(user);
    res.json({ token, user: { name: user.name, email: user.email, role: user.role } });
  } catch (err) {
    next(err);
  }
});

// Troca da própria senha (usuário autenticado). Exige a senha atual.
authRouter.post("/change-password", requireAuth, async (req: AuthedRequest, res, next) => {
  try {
    const { currentPassword, newPassword } = req.body ?? {};
    if (typeof currentPassword !== "string" || typeof newPassword !== "string") {
      return res.status(400).json({ error: "bad_request", message: "Informe a senha atual e a nova senha." });
    }
    if (newPassword.length < 4) {
      return res.status(400).json({ error: "weak_password", message: "A nova senha deve ter ao menos 4 caracteres." });
    }
    const uid = req.user!.sub;
    const user = await findById(uid);
    if (!user) {
      return res.status(404).json({ error: "not_found", message: "Usuário não encontrado." });
    }
    if (user.password !== hashPassword(currentPassword)) {
      return res.status(400).json({ error: "invalid_current", message: "Senha atual incorreta." });
    }
    await updatePassword(uid, newPassword);
    res.json({ ok: true });
  } catch (err) {
    next(err);
  }
});
