import { Router } from "express";
import { authenticate, signToken, requireAuth, type AuthedRequest } from "../auth";
import { findById, findByEmail, updatePassword, hashPassword, recordLogin, updateProfile } from "../users";
import { criaToken, consomeToken, tokenValido, VALIDADE_MIN, RecuperacaoError } from "../recuperacao";
import { enviaEmail, emailRedefinicao, EmailError } from "../email";

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

/* ------------------------- Esqueci minha senha ---------------------------- */

// PÚBLICA. A resposta é sempre a mesma, exista ou não a conta: a tela de login é
// aberta, e dizer "e-mail não encontrado" entregaria a qualquer um a lista de
// quem tem acesso ao sistema. O envio, esse sim, só acontece se a conta existir.
authRouter.post("/forgot", async (req, res, next) => {
  const resposta = {
    ok: true,
    message: "Se existir uma conta com esse e-mail, enviamos o link de redefinição.",
  };
  try {
    const email = String(req.body?.email ?? "").trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      return res.status(400).json({ error: "bad_request", message: "Informe um e-mail válido." });
    }

    const user = await findByEmail(email);
    if (!user) return res.json(resposta);

    const token = await criaToken(user.id, (req.ip ?? "").slice(0, 60) || null);
    const base = (process.env.APP_URL ?? "").replace(/\/+$/, "");
    const link = `${base}/redefinir?token=${token}`;
    const { assunto, html, texto } = emailRedefinicao(user.name, link, VALIDADE_MIN);
    await enviaEmail(user.email, assunto, html, texto);

    res.json(resposta);
  } catch (err) {
    // Falha de limite também responde igual: diferenciar aqui voltaria a dizer
    // se a conta existe.
    if (err instanceof RecuperacaoError) return res.json(resposta);
    if (err instanceof EmailError) {
      return res.status(502).json({ error: "email", message: err.message });
    }
    next(err);
  }
});

// Confere o link ao abrir a tela, sem consumir.
authRouter.get("/reset/:token", async (req, res, next) => {
  try {
    res.json({ valido: await tokenValido(req.params.token) });
  } catch (err) {
    next(err);
  }
});

authRouter.post("/reset", async (req, res, next) => {
  try {
    const senha = String(req.body?.password ?? "");
    if (senha.length < 4) {
      return res.status(400).json({ error: "weak_password", message: "A nova senha deve ter ao menos 4 caracteres." });
    }
    const userId = await consomeToken(String(req.body?.token ?? ""));
    await updatePassword(userId, senha);
    res.json({ ok: true });
  } catch (err) {
    if (err instanceof RecuperacaoError) {
      return res.status(err.status).json({ error: "recuperacao", message: err.message });
    }
    next(err);
  }
});
