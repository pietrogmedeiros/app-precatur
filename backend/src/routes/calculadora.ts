import { Router } from "express";
import type { Response } from "express";
import type { AuthedRequest } from "../auth";

export const calculadoraRouter = Router();

// O motor de cálculo é um processo Python ao lado, escutando só em 127.0.0.1.
// Quem abre a porta para o mundo é esta rota — autenticada como todo o resto.
const MOTOR_URL = (process.env.MOTOR_URL ?? "http://127.0.0.1:8090").replace(/\/$/, "");
const MOTOR_SEGREDO = process.env.MOTOR_SEGREDO ?? "";
// Leitura de PDF com OCR passa de um minuto em processo escaneado; o cálculo
// em si responde em milissegundos. Um timeout só, generoso, no maior dos dois.
const TIMEOUT_MS = Number(process.env.MOTOR_TIMEOUT_MS ?? 300_000);

type Corpo = Record<string, unknown> | undefined;

/**
 * Tenta de novo quando a conexão simplesmente não existe ainda.
 *
 * Os três processos do contêiner sobem juntos e o motor é o mais lento (carrega
 * as séries do BACEN). Sem isto, a primeira calculadora aberta logo após um
 * deploy recebe "motor indisponível" — e o advogado conclui que quebrou.
 */
async function tentarComRetomada(
  chamada: () => Promise<globalThis.Response>,
  retomadas: number
): Promise<globalThis.Response> {
  try {
    return await chamada();
  } catch (err: any) {
    if (retomadas <= 0 || err?.name === "AbortError") throw err;
    await new Promise((r) => setTimeout(r, 400));
    return chamada();
  }
}

/**
 * Encaminha a requisição ao motor e devolve a resposta como veio.
 *
 * Passa o status adiante de propósito: o 422 do motor é a lista de erros de
 * preenchimento que a tela mostra campo a campo, e transformá-lo num 500
 * genérico apagaria a única informação útil.
 */
async function encaminhar(
  req: AuthedRequest,
  res: Response,
  caminho: string,
  opcoes: { corpo?: Corpo; metodo?: string } = {}
) {
  const metodo = opcoes.metodo ?? req.method;
  const cabecalhos: Record<string, string> = {};
  if (MOTOR_SEGREDO) cabecalhos["x-motor-segredo"] = MOTOR_SEGREDO;

  let body: BodyInit | undefined;
  if (metodo !== "GET" && metodo !== "HEAD") {
    const tipo = req.headers["content-type"] ?? "";
    if (tipo.includes("multipart/form-data")) {
      // Upload de PDF: o express.json() não consumiu o corpo, então ele segue
      // como fluxo — nada de carregar um processo inteiro na memória do Node
      // só para repassar.
      cabecalhos["content-type"] = String(tipo);
      body = req as unknown as BodyInit;
    } else {
      cabecalhos["content-type"] = "application/json";
      body = JSON.stringify(opcoes.corpo ?? req.body ?? {});
    }
  }

  const controle = new AbortController();
  const relogio = setTimeout(() => controle.abort(), TIMEOUT_MS);
  const emFluxo = Boolean(body && typeof (body as any).pipe === "function");
  let resposta: globalThis.Response;
  try {
    resposta = await tentarComRetomada(
      () =>
        fetch(`${MOTOR_URL}${caminho}`, {
          method: metodo,
          headers: cabecalhos,
          body,
          signal: controle.signal,
          // Node exige isto para enviar um corpo em fluxo.
          ...(emFluxo ? { duplex: "half" } : {}),
        } as RequestInit),
      // Um corpo em fluxo só pode ser lido uma vez: reenviar mandaria um upload
      // vazio. Nesses casos vale o erro, não a segunda tentativa.
      emFluxo ? 0 : 1
    );
  } catch (err: any) {
    clearTimeout(relogio);
    const abortou = err?.name === "AbortError";
    return res.status(abortou ? 504 : 502).json({
      error: abortou ? "motor_timeout" : "motor_indisponivel",
      message: abortou
        ? "O motor de cálculo demorou demais para responder."
        : "O motor de cálculo não respondeu. Se o problema persistir, avise o suporte.",
    });
  }
  clearTimeout(relogio);

  const tipo = resposta.headers.get("content-type") ?? "";
  if (tipo.includes("application/pdf")) {
    const disposicao = resposta.headers.get("content-disposition");
    if (disposicao) res.setHeader("Content-Disposition", disposicao);
    res.setHeader("Content-Type", "application/pdf");
    const bytes = Buffer.from(await resposta.arrayBuffer());
    return res.status(resposta.status).send(bytes);
  }
  const texto = await resposta.text();
  res.status(resposta.status);
  res.setHeader("Content-Type", tipo || "application/json");
  return res.send(texto);
}

// ── cálculo ────────────────────────────────────────────────────────────────
calculadoraRouter.get("/saude", (req: AuthedRequest, res) => encaminhar(req, res, "/saude"));
calculadoraRouter.get("/opcoes", (req: AuthedRequest, res) => encaminhar(req, res, "/opcoes"));
calculadoraRouter.post("/calcular", (req: AuthedRequest, res) => encaminhar(req, res, "/calcular"));
calculadoraRouter.post("/memorial", (req: AuthedRequest, res) => encaminhar(req, res, "/memorial"));
calculadoraRouter.post("/numero", (req: AuthedRequest, res) => encaminhar(req, res, "/numero"));

// ── documentos (pré-análise, assistente de corte, prefill) ─────────────────
calculadoraRouter.get("/documentos/estado", (req: AuthedRequest, res) =>
  encaminhar(req, res, "/documentos/estado"));
calculadoraRouter.post("/documentos/analisar", (req: AuthedRequest, res) =>
  encaminhar(req, res, "/documentos/analisar"));
calculadoraRouter.post("/documentos/extrair-cortes", (req: AuthedRequest, res) =>
  encaminhar(req, res, "/documentos/extrair-cortes"));
calculadoraRouter.post("/documentos/extrair-pecas", (req: AuthedRequest, res) =>
  encaminhar(req, res, "/documentos/extrair-pecas"));
calculadoraRouter.post("/documentos/preencher", (req: AuthedRequest, res) =>
  encaminhar(req, res, "/documentos/preencher"));
// Páginas citadas, com o valor destacado. A sessão é um id opaco gerado pelo
// motor; validar o formato aqui evita que um caminho inventado vire requisição.
calculadoraRouter.get("/documentos/paginas/:sessao", (req: AuthedRequest, res) => {
  const sessao = String(req.params.sessao);
  if (!/^[a-f0-9]{32}$/.test(sessao)) {
    return res.status(400).json({ error: "bad_request", message: "Sessão inválida." });
  }
  return encaminhar(req, res, `/documentos/paginas/${sessao}`);
});

// ── CRM ────────────────────────────────────────────────────────────────────
calculadoraRouter.get("/crm/estado", (req: AuthedRequest, res) =>
  encaminhar(req, res, "/crm/estado"));
calculadoraRouter.get("/crm/cards", (req: AuthedRequest, res) => {
  const termo = String(req.query.termo ?? "").trim();
  if (!termo) return res.status(400).json({ error: "bad_request", message: "Informe o termo de busca." });
  const limite = Number(req.query.limite ?? 12);
  return encaminhar(req, res, `/crm/cards?termo=${encodeURIComponent(termo)}&limite=${limite}`);
});
calculadoraRouter.get("/crm/card/:id", (req: AuthedRequest, res) => {
  const id = String(req.params.id);
  if (!/^\d+$/.test(id)) {
    return res.status(400).json({ error: "bad_request", message: "Card inválido." });
  }
  return encaminhar(req, res, `/crm/card/${id}`);
});
calculadoraRouter.post("/crm/enviar", (req: AuthedRequest, res) => {
  // A autoria do registro no CRM vem do TOKEN, nunca do corpo: é ela que o
  // comercial lê para saber a quem perguntar quando o número é questionado.
  const corpo = { ...(req.body ?? {}), autor: req.user?.name ?? req.user?.email ?? null };
  return encaminhar(req, res, "/crm/enviar", { corpo });
});
