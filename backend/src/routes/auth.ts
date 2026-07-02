import { Router } from "express";
import { authenticate, signToken } from "../auth";

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
    const token = signToken(user);
    res.json({ token, user: { name: user.name, email: user.email, role: user.role } });
  } catch (err) {
    next(err);
  }
});
