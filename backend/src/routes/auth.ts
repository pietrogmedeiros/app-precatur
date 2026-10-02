import { Router } from "express";
import { authenticate, signToken, requireAuth, type AuthedRequest } from "../auth";
import { findById, updatePassword, hashPassword, recordLogin, updateProfile } from "../users";

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
    res.json({
      token,
      user: { name: user.name, email: user.email, role: user.role, phone: user.phone },
    });
  } catch (err) {
    next(err);
  }
});

// Dados do usuário logado (sempre frescos do banco) — inclui telefone atual.
authRouter.get("/me", requireAuth, async (req: AuthedRequest, res, next) => {
  try {
    const user = await findById(req.user!.sub);
    if (!user) {
      return res.status(404).json({ error: "not_found", message: "Usuário não encontrado." });
    }
    res.json({
      id: user.id,
      name: user.name,
      avatar: user.avatar ?? null,
      created_at: user.created_at,
      last_login_at: user.last_login_at,
      email: user.email,
      role: user.role,
      phone: user.phone,
    });
  } catch (err) {
    next(err);
  }
});

// Atualiza o próprio perfil (por ora, apenas o telefone).
// Perfil: o usuário muda nome, telefone e foto. E-mail e papel ficam de fora —
// e-mail é a credencial de acesso e papel é decisão de administrador.
const MAX_AVATAR_BYTES = 400 * 1024;
const TIPOS_AVATAR = ["image/jpeg", "image/png", "image/webp"];

authRouter.patch("/profile", requireAuth, async (req: AuthedRequest, res, next) => {
  try {
    const b = req.body ?? {};
    const dados: { name?: string; phone?: string; avatar?: string; removerAvatar?: boolean } = {};

    if (b.name !== undefined) {
      const nome = String(b.name).trim();
      if (nome.length < 2 || nome.length > 120) {
        return res.status(400).json({ error: "bad_request", message: "Informe um nome entre 2 e 120 caracteres." });
      }
      dados.name = nome;
    }
    if (b.phone !== undefined) {
      const tel = String(b.phone).trim();
      if (!tel) return res.status(400).json({ error: "bad_request", message: "Informe o telefone." });
      dados.phone = tel.slice(0, 40);
    }
    if (b.removerAvatar === true) {
      dados.removerAvatar = true;
    } else if (b.avatar !== undefined && b.avatar !== null) {
      const avatar = String(b.avatar);
      const m = /^data:([a-z/+-]+);base64,/.exec(avatar);
      if (!m || !TIPOS_AVATAR.includes(m[1])) {
        return res.status(400).json({ error: "bad_request", message: "A foto deve ser JPEG, PNG ou WebP." });
      }
      // base64 cresce ~33%: confere o tamanho real dos bytes.
      if (Math.floor((avatar.length - m[0].length) * 0.75) > MAX_AVATAR_BYTES) {
        return res.status(400).json({ error: "bad_request", message: "A foto é grande demais. Envie uma imagem menor." });
      }
      dados.avatar = avatar;
    }

    if (!Object.keys(dados).length) {
      return res.status(400).json({ error: "bad_request", message: "Nada para atualizar." });
    }

    const user = await updateProfile(req.user!.sub, dados);
    if (!user) return res.status(404).json({ error: "not_found", message: "Usuário não encontrado." });
    res.json({
      id: user.id,
      name: user.name,
      email: user.email,
      role: user.role,
      phone: user.phone,
      avatar: user.avatar ?? null,
      created_at: user.created_at,
      last_login_at: user.last_login_at,
    });
  } catch (err) {
    next(err);
  }
});

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
