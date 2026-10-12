import { Router } from "express";
import type { Response } from "express";
import type { AuthedRequest } from "../auth";

export const alfredRouter = Router();

// O Alfred é um serviço Python ao lado, escutando só em 127.0.0.1 — a base tem
// nome e CPF de credor, e não existe porta dele para o mundo. Quem autentica é
// esta rota, com o login do app.
const ALFRED_URL = (process.env.ALFRED_URL ?? "http://127.0.0.1:8610").replace(/\/$/, "");
const ALFRED_SEGREDO = process.env.ALFRED_SEGREDO ?? "";
const TIMEOUT_MS = Number(process.env.ALFRED_TIMEOUT_MS ?? 60_000);

/**
 * Papéis do Alfred: `leitor` vê CPF mascarado, `completo` vê inteiro.
 *
 * O mapeamento é por PAPEL DO APP, não por pessoa, e o padrão é o mais fechado
 * que ainda serve: só admin vê CPF sem máscara. `ALFRED_PERFIS_COMPLETO` abre
 * para outros perfis quando o time decidir — mudar isso é decisão de privacidade,
 * então mora em configuração e não em código.
 */
const PERFIS_COMPLETO = (process.env.ALFRED_PERFIS_COMPLETO ?? "admin")
  .split(",").map((p) => p.trim()).filter(Boolean);

const TOKEN_LEITOR = process.env.ALFRED_TOKEN_LEITOR ?? "";
const TOKEN_COMPLETO = process.env.ALFRED_TOKEN_COMPLETO ?? "";

function papelDe(req: AuthedRequest): "leitor" | "completo" {
  return PERFIS_COMPLETO.includes(req.user?.role ?? "") ? "completo" : "leitor";
}

function tokenDe(papel: "leitor" | "completo"): string {
  return papel === "completo" ? TOKEN_COMPLETO || TOKEN_LEITOR : TOKEN_LEITOR;
}

async function encaminhar(req: AuthedRequest, res: Response, caminho: string) {
  if (!TOKEN_LEITOR) {
    return res.status(503).json({
      error: "alfred_sem_token",
      message: "A consulta de precatórios não está configurada neste ambiente.",
    });
  }
  const papel = papelDe(req);
  const cabecalhos: Record<string, string> = {
    authorization: `Bearer ${tokenDe(papel)}`,
    // Quem consultou. A base tem nome e CPF: a trilha de auditoria precisa
    // apontar para uma pessoa, não para um papel.
    "x-alfred-usuario": req.user?.email ?? req.user?.name ?? "?",
  };
  if (ALFRED_SEGREDO) cabecalhos["x-alfred-segredo"] = ALFRED_SEGREDO;
  if (req.method !== "GET") cabecalhos["content-type"] = "application/json";

  const controle = new AbortController();
  const relogio = setTimeout(() => controle.abort(), TIMEOUT_MS);
  let resposta: globalThis.Response;
  try {
    resposta = await fetch(`${ALFRED_URL}${caminho}`, {
      method: req.method,
      headers: cabecalhos,
      body: req.method === "GET" ? undefined : JSON.stringify(req.body ?? {}),
      signal: controle.signal,
    });
  } catch (err: any) {
    clearTimeout(relogio);
    const abortou = err?.name === "AbortError";
    return res.status(abortou ? 504 : 502).json({
      error: abortou ? "alfred_timeout" : "alfred_indisponivel",
      message: abortou
        ? "A consulta demorou demais para responder."
        : "A base de precatórios não respondeu. Se persistir, avise o suporte.",
    });
  }
  clearTimeout(relogio);

  const tipo = resposta.headers.get("content-type") ?? "";
  if (tipo.includes("application/pdf")) {
    const disposicao = resposta.headers.get("content-disposition");
    if (disposicao) res.setHeader("Content-Disposition", disposicao);
    res.setHeader("Content-Type", "application/pdf");
    return res.status(resposta.status).send(Buffer.from(await resposta.arrayBuffer()));
  }
  const texto = await resposta.text();
  res.status(resposta.status);
  res.setHeader("Content-Type", tipo || "application/json");
  return res.send(texto);
}

/** `?completo=1` só segue adiante para quem o perfil autoriza. */
function sufixoCompleto(req: AuthedRequest): string {
  return req.query.completo === "1" && papelDe(req) === "completo" ? "?completo=1" : "";
}

// Quem é este usuário aos olhos da base — a tela usa para mostrar (ou não) o
// botão de revelar CPF.
alfredRouter.get("/eu", (req: AuthedRequest, res) => {
  res.json({ papel: papelDe(req), configurado: Boolean(TOKEN_LEITOR) });
});

alfredRouter.get("/saude", (req: AuthedRequest, res) => encaminhar(req, res, "/saude"));

// CPF NUNCA EM URL: a busca é POST porque o log de acesso registra o caminho —
// um CPF em query string iria parar no log. Regra do Alfred, mantida aqui.
alfredRouter.post("/busca", (req: AuthedRequest, res) => encaminhar(req, res, "/busca"));

alfredRouter.get("/precatorio/:numero", (req: AuthedRequest, res) => {
  const n = String(req.params.numero).replace(/\D/g, "");
  if (n.length < 15) {
    return res.status(400).json({ error: "bad_request", message: "Informe um número de processo (15 dígitos ou mais)." });
  }
  return encaminhar(req, res, `/precatorio/${encodeURIComponent(req.params.numero)}${sufixoCompleto(req)}`);
});

alfredRouter.get("/parecer_id/:pid", (req: AuthedRequest, res) => {
  if (!/^\d+$/.test(String(req.params.pid))) {
    return res.status(400).json({ error: "bad_request", message: "Identificador inválido." });
  }
  return encaminhar(req, res, `/parecer_id/${req.params.pid}${sufixoCompleto(req)}`);
});

alfredRouter.get("/parecer_id/:pid/pdf", (req: AuthedRequest, res) => {
  if (!/^\d+$/.test(String(req.params.pid))) {
    return res.status(400).json({ error: "bad_request", message: "Identificador inválido." });
  }
  return encaminhar(req, res, `/parecer_id/${req.params.pid}/pdf${sufixoCompleto(req)}`);
});

// Busca do ente devedor. O parâmetro é `q` — só metadado agregado, nenhum dado
// de credor, por isso pode ir na URL.
alfredRouter.get("/devedores", (req: AuthedRequest, res) => {
  const q = String(req.query.q ?? "").trim();
  if (q.length < 2) {
    return res.status(400).json({ error: "bad_request", message: "Informe ao menos 2 letras." });
  }
  return encaminhar(req, res, `/devedores?q=${encodeURIComponent(q)}`);
});

alfredRouter.get("/entes", (req: AuthedRequest, res) => encaminhar(req, res, "/entes"));

alfredRouter.get("/ente/:chave", (req: AuthedRequest, res) =>
  encaminhar(req, res, `/ente/${encodeURIComponent(req.params.chave)}`));

alfredRouter.get("/entes/:id/fila", (req: AuthedRequest, res) => {
  if (!/^\d+$/.test(String(req.params.id))) {
    return res.status(400).json({ error: "bad_request", message: "Ente inválido." });
  }
  const busca = new URLSearchParams();
  for (const chave of ["limite", "offset"]) {
    const v = req.query[chave];
    if (v !== undefined && v !== "") busca.set(chave, String(v));
  }
  const q = busca.toString();
  return encaminhar(req, res, `/entes/${req.params.id}/fila${q ? `?${q}` : ""}`);
});

alfredRouter.get("/municipio/:ibge", (req: AuthedRequest, res) =>
  encaminhar(req, res, `/municipio/${encodeURIComponent(req.params.ibge)}`));
